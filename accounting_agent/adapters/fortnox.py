"""Safe Fortnox adapter boundary.

The adapter is read-first and dry-run only in this phase. It can prepare
Fortnox-shaped draft payloads without credentials, but it has no external write
path even when a caller supplies permissive configuration or a forged permit.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from accounting_agent.idempotency import (
    IdempotencyRecord,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)
from accounting_agent.permits import ExecutionPermit, PermitValidator, canonical_payload_hash
from accounting_agent.policy import ActionType, POLICY_VERSION


DEFAULT_FORTNOX_BASE_URL = "https://api.fortnox.se/3"

FORBIDDEN_LIVE_ACTIONS = {
    ActionType.POST_VOUCHER,
    ActionType.SEND_INVOICE,
    ActionType.APPROVE_SUPPLIER_INVOICE,
    ActionType.START_PAYMENT,
    ActionType.DELETE_RECORD,
    ActionType.CHANGE_SETTINGS,
}


class FortnoxAdapterError(Exception):
    """Base class for Fortnox adapter errors."""


class MissingFortnoxCredentials(FortnoxAdapterError):
    """Raised when live Fortnox access is requested without credentials."""


class FortnoxPolicyViolation(FortnoxAdapterError):
    """Raised when a requested Fortnox action violates local safety policy."""


class FortnoxProtectedOperation(FortnoxPolicyViolation):
    """Raised for operations that remain intentionally blocked."""


class FortnoxTransportError(FortnoxAdapterError):
    """Raised when the underlying Fortnox transport fails."""


class FortnoxTransport(Protocol):
    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        ...

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, Any],
        idempotency_key: str,
        permit: ExecutionPermit | None,
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class FortnoxConfig:
    """Runtime configuration with dry-run defaults and no secret logging."""

    base_url: str = DEFAULT_FORTNOX_BASE_URL
    environment: str = "sandbox"
    access_token: str | None = None
    dry_run: bool = True
    allow_draft_writes: bool = False
    allow_sensitive_reads: bool = False
    timeout_seconds: int = 20

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "FortnoxConfig":
        source = environ or os.environ
        return cls(
            base_url=source.get("FORTNOX_BASE_URL", DEFAULT_FORTNOX_BASE_URL),
            environment=source.get("FORTNOX_ENVIRONMENT", "sandbox"),
            access_token=_blank_to_none(source.get("FORTNOX_ACCESS_TOKEN")),
            dry_run=_env_bool(source.get("FORTNOX_DRY_RUN"), default=True),
            allow_draft_writes=_env_bool(
                source.get("FORTNOX_ALLOW_DRAFT_WRITES"),
                default=False,
            ),
            allow_sensitive_reads=_env_bool(
                source.get("FORTNOX_ALLOW_SENSITIVE_READS"),
                default=False,
            ),
            timeout_seconds=int(source.get("FORTNOX_TIMEOUT_SECONDS", "20")),
        )

    def require_access_token(self) -> str:
        if not self.access_token:
            raise MissingFortnoxCredentials(
                "Fortnox access token is not configured. Set FORTNOX_ACCESS_TOKEN "
                "for separately approved live reads, or inject a mocked FortnoxTransport in tests."
            )
        return self.access_token


@dataclass(frozen=True)
class FortnoxDraftResult:
    adapter: str
    action_type: ActionType
    case_id: str
    idempotency_key: str
    payload_hash: str
    status: str
    dry_run: bool
    external_reference: str | None = None
    duplicate_of: str | None = None
    response: Mapping[str, Any] = field(default_factory=dict)


class HttpFortnoxTransport:
    """Small direct-REST transport kept replaceable behind FortnoxTransport."""

    def __init__(self, config: FortnoxConfig) -> None:
        self.config = config

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, Any],
        idempotency_key: str,
        permit: ExecutionPermit | None,
    ) -> Mapping[str, Any]:
        raise FortnoxPolicyViolation(
            "Fortnox HTTP POST is structurally disabled in the current adapter phase; "
            "configuration and permits cannot enable it."
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        if method.upper() != "GET":
            raise FortnoxPolicyViolation(
                "Only HTTP GET is available through the current Fortnox transport."
            )
        access_token = self.config.require_access_token()
        url = _join_url(self.config.base_url, path)
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        body = None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise FortnoxTransportError(
                f"Fortnox {method} {path} failed with HTTP {error.code}: "
                f"{_redact(error_body)}"
            ) from error
        except urllib.error.URLError as error:
            raise FortnoxTransportError(
                f"Fortnox {method} {path} failed: {_redact(str(error.reason))}"
            ) from error
        if not response_body:
            return {}
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise FortnoxTransportError(
                f"Fortnox {method} {path} returned non-JSON response"
            ) from error
        if not isinstance(parsed, Mapping):
            raise FortnoxTransportError(
                f"Fortnox {method} {path} returned an unexpected response shape"
            )
        return parsed


class FortnoxAdapter:
    """Internal Fortnox API boundary for reads, draft payloads, and draft writes."""

    adapter_name = "fortnox"

    def __init__(
        self,
        *,
        config: FortnoxConfig | None = None,
        transport: FortnoxTransport | None = None,
        permit_validator: PermitValidator | None = None,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self.config = config or FortnoxConfig.from_env()
        self.transport = transport or HttpFortnoxTransport(self.config)
        self.permit_validator = permit_validator or PermitValidator(
            accepted_policy_version=POLICY_VERSION
        )
        self.idempotency_store = idempotency_store or InMemoryIdempotencyStore()

    def list_accounts(self, params: Mapping[str, Any] | None = None) -> Sequence[Mapping[str, Any]]:
        return self._list_reference("/accounts", "Accounts", params=params)

    def get_account(self, account_number: int | str) -> Mapping[str, Any]:
        return self._get_reference(f"/accounts/{account_number}", "Account")

    def list_suppliers(self, params: Mapping[str, Any] | None = None) -> Sequence[Mapping[str, Any]]:
        return self._list_reference("/suppliers", "Suppliers", params=params)

    def get_supplier(self, supplier_number: int | str) -> Mapping[str, Any]:
        return self._get_reference(f"/suppliers/{supplier_number}", "Supplier")

    def list_customers(self, params: Mapping[str, Any] | None = None) -> Sequence[Mapping[str, Any]]:
        return self._list_reference("/customers", "Customers", params=params)

    def get_customer(self, customer_number: int | str) -> Mapping[str, Any]:
        return self._get_reference(f"/customers/{customer_number}", "Customer")

    def list_financial_years(
        self,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        return self._list_reference("/financialyears", "FinancialYears", params=params)

    def get_financial_year(self, year_id: int | str) -> Mapping[str, Any]:
        return self._get_reference(f"/financialyears/{year_id}", "FinancialYear")

    def list_vouchers(self, params: Mapping[str, Any] | None = None) -> Sequence[Mapping[str, Any]]:
        self._require_sensitive_reads("vouchers")
        return self._list_reference("/vouchers", "Vouchers", params=params)

    def get_voucher(
        self,
        *,
        financial_year: int | str,
        series: str,
        voucher_number: int | str,
    ) -> Mapping[str, Any]:
        self._require_sensitive_reads("vouchers")
        return self._get_reference(
            f"/vouchers/{series}/{voucher_number}",
            "Voucher",
            params={"financialyear": financial_year},
        )

    def list_invoices(self, params: Mapping[str, Any] | None = None) -> Sequence[Mapping[str, Any]]:
        self._require_sensitive_reads("invoices")
        return self._list_reference("/invoices", "Invoices", params=params)

    def get_invoice(self, document_number: int | str) -> Mapping[str, Any]:
        self._require_sensitive_reads("invoices")
        return self._get_reference(f"/invoices/{document_number}", "Invoice")

    def list_supplier_invoices(
        self,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        self._require_sensitive_reads("supplierinvoices")
        return self._list_reference("/supplierinvoices", "SupplierInvoices", params=params)

    def get_supplier_invoice(self, given_number: int | str) -> Mapping[str, Any]:
        self._require_sensitive_reads("supplierinvoices")
        return self._get_reference(f"/supplierinvoices/{given_number}", "SupplierInvoice")

    def prepare_supplier_invoice_draft_payload(
        self,
        *,
        supplier_number: str,
        invoice_number: str,
        invoice_date: str,
        due_date: str,
        total: Decimal | int | str,
        vat: Decimal | int | str,
        rows: Sequence[Mapping[str, Any]],
        currency: str = "SEK",
        comments: str | None = None,
        our_reference: str | None = None,
        your_reference: str | None = None,
    ) -> dict[str, Any]:
        _require_non_empty("supplier_number", supplier_number)
        _require_non_empty("invoice_number", invoice_number)
        _require_non_empty("invoice_date", invoice_date)
        _require_non_empty("due_date", due_date)
        if not rows:
            raise ValueError("supplier invoice drafts require at least one row")
        supplier_invoice: dict[str, Any] = {
            "SupplierNumber": supplier_number,
            "InvoiceNumber": invoice_number,
            "InvoiceDate": invoice_date,
            "DueDate": due_date,
            "Currency": currency,
            "Total": _money(total),
            "VAT": _money(vat),
            "Booked": False,
            "PaymentPending": False,
            "DisablePaymentFile": True,
            "SupplierInvoiceRows": [_supplier_invoice_row(row) for row in rows],
        }
        if comments:
            supplier_invoice["Comments"] = comments
        if our_reference:
            supplier_invoice["OurReference"] = our_reference
        if your_reference:
            supplier_invoice["YourReference"] = your_reference
        return {"SupplierInvoice": supplier_invoice}

    def prepare_voucher_draft_payload(
        self,
        *,
        transaction_date: str,
        description: str,
        voucher_series: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        _require_non_empty("transaction_date", transaction_date)
        _require_non_empty("description", description)
        _require_non_empty("voucher_series", voucher_series)
        voucher_rows = [_voucher_row(row) for row in rows]
        _validate_balanced_voucher(voucher_rows)
        return {
            "Voucher": {
                "TransactionDate": transaction_date,
                "Description": description,
                "VoucherSeries": voucher_series,
                "VoucherRows": voucher_rows,
            }
        }

    def create_supplier_invoice_draft(
        self,
        *,
        case_id: str,
        entity_id: str,
        payload: Mapping[str, Any],
        permit: ExecutionPermit | None,
    ) -> FortnoxDraftResult:
        return self._create_draft(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            case_id=case_id,
            entity_id=entity_id,
            payload=payload,
            permit=permit,
        )

    def create_voucher_draft(
        self,
        *,
        case_id: str,
        entity_id: str,
        payload: Mapping[str, Any],
        permit: ExecutionPermit | None,
    ) -> FortnoxDraftResult:
        return self._create_draft(
            action_type=ActionType.DRAFT_VOUCHER,
            case_id=case_id,
            entity_id=entity_id,
            payload=payload,
            permit=permit,
        )

    def _create_draft(
        self,
        *,
        action_type: ActionType,
        case_id: str,
        entity_id: str,
        payload: Mapping[str, Any],
        permit: ExecutionPermit | None,
    ) -> FortnoxDraftResult:
        self._raise_if_action_forbidden(action_type)
        if not self.config.dry_run:
            raise FortnoxPolicyViolation(
                "Live Fortnox draft creation is structurally disabled in the current "
                "adapter phase; configuration and permits cannot enable it."
            )
        self.permit_validator.require_valid(
            permit=permit,
            case_id=case_id,
            entity_id=entity_id,
            action_type=action_type,
            payload=payload,
        )
        assert permit is not None
        payload_hash = canonical_payload_hash(payload)
        existing = self.idempotency_store.get(permit.idempotency_key)
        if existing is not None:
            return FortnoxDraftResult(
                adapter=self.adapter_name,
                action_type=action_type,
                case_id=case_id,
                idempotency_key=permit.idempotency_key,
                payload_hash=payload_hash,
                status="duplicate_idempotency_key",
                dry_run=existing.dry_run,
                external_reference=existing.external_reference,
                duplicate_of=existing.key,
                response=existing.response,
            )

        if action_type is ActionType.DRAFT_VOUCHER:
            return self._record_result(
                action_type=action_type,
                case_id=case_id,
                idempotency_key=permit.idempotency_key,
                payload_hash=payload_hash,
                status="dry_run_voucher_payload_prepared_only",
                dry_run=True,
                response={"reason": "live voucher creation may post bookkeeping and is blocked"},
            )

        _assert_no_forbidden_payload_markers(payload)
        return self._record_result(
            action_type=action_type,
            case_id=case_id,
            idempotency_key=permit.idempotency_key,
            payload_hash=payload_hash,
            status="dry_run_draft_not_created",
            dry_run=True,
            response={"payload": dict(payload)},
        )

    def _list_reference(
        self,
        path: str,
        key: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        response = self.transport.get(path, params=params)
        records = response.get(key, ())
        if not isinstance(records, Sequence) or isinstance(records, str | bytes):
            raise FortnoxTransportError(f"Fortnox response field {key} is not a list")
        return records

    def _get_reference(
        self,
        path: str,
        key: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        response = self.transport.get(path, params=params)
        record = response.get(key)
        if not isinstance(record, Mapping):
            raise FortnoxTransportError(f"Fortnox response field {key} is not an object")
        return record

    def _require_sensitive_reads(self, resource: str) -> None:
        if not self.config.allow_sensitive_reads:
            raise FortnoxPolicyViolation(
                f"Fortnox {resource} reads are disabled by default because they can expose "
                "transaction-level client data. Enable allow_sensitive_reads only for an "
                "approved read-only/sandbox workflow."
            )

    def _record_result(
        self,
        *,
        action_type: ActionType,
        case_id: str,
        idempotency_key: str,
        payload_hash: str,
        status: str,
        dry_run: bool,
        external_reference: str | None = None,
        response: Mapping[str, Any] | None = None,
    ) -> FortnoxDraftResult:
        result = FortnoxDraftResult(
            adapter=self.adapter_name,
            action_type=action_type,
            case_id=case_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            status=status,
            dry_run=dry_run,
            external_reference=external_reference,
            response=response or {},
        )
        self.idempotency_store.save(
            IdempotencyRecord(
                key=idempotency_key,
                adapter=self.adapter_name,
                action_type=action_type,
                case_id=case_id,
                payload_hash=payload_hash,
                status=status,
                dry_run=dry_run,
                external_reference=external_reference,
                response=response or {},
            )
        )
        return result

    def _raise_if_action_forbidden(self, action_type: ActionType) -> None:
        if action_type in FORBIDDEN_LIVE_ACTIONS:
            raise FortnoxProtectedOperation(
                f"Fortnox action {action_type.value} is blocked by adapter policy"
            )


def _supplier_invoice_row(row: Mapping[str, Any]) -> dict[str, Any]:
    account = row.get("account") or row.get("Account")
    if account is None:
        raise ValueError("supplier invoice row requires account")
    prepared: dict[str, Any] = {"Account": int(account)}
    description = row.get("description") or row.get("TransactionInformation")
    if description:
        prepared["TransactionInformation"] = str(description)
    if row.get("debit") is not None or row.get("Debit") is not None:
        prepared["Debit"] = _money(row.get("debit", row.get("Debit")))
    if row.get("credit") is not None or row.get("Credit") is not None:
        prepared["Credit"] = _money(row.get("credit", row.get("Credit")))
    for source_key, target_key in (
        ("cost_center", "CostCenter"),
        ("project", "Project"),
        ("item_description", "ItemDescription"),
    ):
        if row.get(source_key):
            prepared[target_key] = str(row[source_key])
    return prepared


def _voucher_row(row: Mapping[str, Any]) -> dict[str, Any]:
    account = row.get("account") or row.get("Account")
    if account is None:
        raise ValueError("voucher row requires account")
    prepared: dict[str, Any] = {"Account": int(account)}
    debit = _decimal(row.get("debit", row.get("Debit", "0")))
    credit = _decimal(row.get("credit", row.get("Credit", "0")))
    if debit < 0 or credit < 0:
        raise ValueError("voucher row debit/credit must not be negative")
    if debit and credit:
        raise ValueError("voucher row cannot contain both debit and credit")
    if debit:
        prepared["Debit"] = _money(debit)
    if credit:
        prepared["Credit"] = _money(credit)
    description = row.get("description") or row.get("TransactionInformation")
    if description:
        prepared["TransactionInformation"] = str(description)
    for source_key, target_key in (("cost_center", "CostCenter"), ("project", "Project")):
        if row.get(source_key):
            prepared[target_key] = str(row[source_key])
    return prepared


def _validate_balanced_voucher(rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError("voucher drafts require at least one row")
    debit = sum(_decimal(row.get("Debit", "0")) for row in rows)
    credit = sum(_decimal(row.get("Credit", "0")) for row in rows)
    if debit != credit:
        raise ValueError("voucher draft rows must balance debit and credit")


def _assert_no_forbidden_payload_markers(payload: Mapping[str, Any]) -> None:
    for path, value in _walk_payload(payload):
        key = path[-1].lower()
        if key in {"approved", "approval", "sent", "send", "deleted", "delete"} and value:
            raise FortnoxProtectedOperation(
                f"payload field {'.'.join(path)} is blocked by adapter policy"
            )
        if key in {"booked", "paymentpending"} and value is True:
            raise FortnoxProtectedOperation(
                f"payload field {'.'.join(path)} would create a posted/payment state"
            )


def _walk_payload(value: Any, path: tuple[str, ...] = ()) -> Sequence[tuple[tuple[str, ...], Any]]:
    results: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            results.extend(_walk_payload(item, path + (str(key),)))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            results.extend(_walk_payload(item, path + (str(index),)))
    else:
        results.append((path, value))
    return results


def _money(value: Decimal | int | str | Any) -> str:
    amount = _decimal(value).quantize(Decimal("0.01"))
    return format(amount, "f")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid decimal value: {value!r}") from error


def _require_non_empty(name: str, value: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} is required")


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _redact(value: str) -> str:
    for env_name in ("FORTNOX_ACCESS_TOKEN",):
        secret = os.environ.get(env_name)
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value
