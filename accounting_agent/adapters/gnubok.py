"""Optional gnubok shadow-ledger adapter.

This module intentionally starts with a local stub. It mirrors supplier-invoice
proposals into a ledger-shaped draft for validation and comparison, while
Fortnox remains the production source of truth.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from accounting_agent.accounting.bas import AccountPlan, BasAccount
from accounting_agent.accounting.proposals import (
    SupplierInvoiceProposal,
    fortnox_supplier_invoice_payload,
)
from accounting_agent.accounting.vat import (
    expected_purchase_vat_mapping,
    expected_vat_amount_minor,
)


class ShadowLedgerUnavailable(Exception):
    """Raised when an optional shadow ledger cannot be reached."""


@dataclass(frozen=True)
class ShadowCompanyContext:
    company_id: str
    fiscal_year: str
    display_name: str
    adapter: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowAccount:
    number: str
    name: str
    account_type: str
    vat_supported: bool

    @classmethod
    def from_bas_account(cls, account: BasAccount) -> "ShadowAccount":
        return cls(
            number=account.number,
            name=account.name,
            account_type=account.account_type,
            vat_supported=account.vat_supported,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowLedgerLine:
    account: str
    debit_minor: int
    credit_minor: int
    description: str
    vat_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    check: str
    passed: bool
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowTransactionDraft:
    draft_id: str
    company: ShadowCompanyContext
    source_proposal_id: str
    date: str
    description: str
    currency: str
    lines: tuple[ShadowLedgerLine, ...]
    metadata: dict[str, Any]
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["company"] = self.company.to_dict()
        data["lines"] = [line.to_dict() for line in self.lines]
        return data


@dataclass(frozen=True)
class ShadowLedgerComparison:
    status: str
    source_of_truth: str
    fortnox_payload: dict[str, Any]
    accounting_proposal: dict[str, Any]
    shadow_proposal: dict[str, Any] | None
    differences: tuple[str, ...]
    warnings: tuple[str, ...]
    validations: tuple[ValidationResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_of_truth": self.source_of_truth,
            "fortnox_payload": self.fortnox_payload,
            "accounting_proposal": self.accounting_proposal,
            "shadow_proposal": self.shadow_proposal,
            "differences": list(self.differences),
            "warnings": list(self.warnings),
            "validations": [validation.to_dict() for validation in self.validations],
        }


class ShadowLedgerAdapter(Protocol):
    adapter_name: str

    def get_or_create_company_context(
        self,
        *,
        company_id: str,
        fiscal_year: str,
        display_name: str | None = None,
    ) -> ShadowCompanyContext:
        ...

    def lookup_account(
        self,
        company: ShadowCompanyContext,
        account_number: str,
    ) -> ShadowAccount | None:
        ...

    def create_draft_transaction(
        self,
        company: ShadowCompanyContext,
        proposal: SupplierInvoiceProposal,
    ) -> ShadowTransactionDraft:
        ...

    def validate_debit_credit_balance(
        self,
        draft: ShadowTransactionDraft,
    ) -> ValidationResult:
        ...

    def validate_vat_mapping(
        self,
        proposal: SupplierInvoiceProposal,
        draft: ShadowTransactionDraft,
    ) -> ValidationResult:
        ...

    def export_comparison(
        self,
        proposal: SupplierInvoiceProposal,
        draft: ShadowTransactionDraft,
    ) -> ShadowLedgerComparison:
        ...


class LocalGnubokShadowLedgerAdapter:
    """Local gnubok-shaped shadow adapter with no external writes."""

    adapter_name = "local_gnubok_shadow_stub"

    def __init__(self, account_plan: AccountPlan | None = None) -> None:
        self.account_plan = account_plan or AccountPlan()
        self._companies: dict[tuple[str, str], ShadowCompanyContext] = {}

    def get_or_create_company_context(
        self,
        *,
        company_id: str,
        fiscal_year: str,
        display_name: str | None = None,
    ) -> ShadowCompanyContext:
        key = (company_id, fiscal_year)
        if key not in self._companies:
            self._companies[key] = ShadowCompanyContext(
                company_id=company_id,
                fiscal_year=fiscal_year,
                display_name=display_name or company_id,
                adapter=self.adapter_name,
            )
        return self._companies[key]

    def lookup_account(
        self,
        company: ShadowCompanyContext,
        account_number: str,
    ) -> ShadowAccount | None:
        del company
        account = self.account_plan.lookup(account_number)
        if account is None:
            return None
        return ShadowAccount.from_bas_account(account)

    def create_draft_transaction(
        self,
        company: ShadowCompanyContext,
        proposal: SupplierInvoiceProposal,
    ) -> ShadowTransactionDraft:
        lines = tuple(
            ShadowLedgerLine(
                account=entry.account,
                debit_minor=entry.debit_minor,
                credit_minor=entry.credit_minor,
                description=entry.description,
                vat_code=entry.vat_code,
            )
            for entry in proposal.accounting_entries()
        )
        return ShadowTransactionDraft(
            draft_id=f"shadow_{proposal.proposal_id}",
            company=company,
            source_proposal_id=proposal.proposal_id,
            date=proposal.invoice_date,
            description=proposal.description or f"Supplier invoice {proposal.invoice_number}",
            currency=proposal.currency,
            lines=lines,
            metadata={
                "case_id": proposal.case_id,
                "supplier_id": proposal.supplier_id,
                "supplier_name": proposal.supplier_name,
                "invoice_number": proposal.invoice_number,
                "source": "supplier_invoice_proposal",
                "production_source_of_truth": "fortnox",
            },
        )

    def validate_debit_credit_balance(
        self,
        draft: ShadowTransactionDraft,
    ) -> ValidationResult:
        debit_total = sum(line.debit_minor for line in draft.lines)
        credit_total = sum(line.credit_minor for line in draft.lines)
        errors: list[str] = []
        if debit_total != credit_total:
            errors.append(
                f"debit_credit_imbalance:{debit_total}:{credit_total}"
            )
        return ValidationResult(
            check="debit_credit_balance",
            passed=not errors,
            errors=tuple(errors),
        )

    def validate_vat_mapping(
        self,
        proposal: SupplierInvoiceProposal,
        draft: ShadowTransactionDraft,
    ) -> ValidationResult:
        del draft
        mapping = expected_purchase_vat_mapping(proposal.vat_rate_percent)
        warnings: list[str] = []
        errors: list[str] = []
        if mapping is None:
            warnings.append(f"unknown_purchase_vat_rate:{proposal.vat_rate_percent}")
        else:
            if mapping.input_vat_account is None and proposal.vat_amount_minor:
                errors.append("vat_amount_present_for_zero_vat_mapping")
            if mapping.input_vat_account is not None:
                if proposal.vat_account != mapping.input_vat_account:
                    errors.append(
                        "vat_account_mismatch:"
                        f"expected_{mapping.input_vat_account}:actual_{proposal.vat_account}"
                    )
            expected_amount = expected_vat_amount_minor(
                proposal.net_amount_minor,
                proposal.vat_rate_percent,
            )
            if abs(expected_amount - proposal.vat_amount_minor) > 1:
                warnings.append(
                    "vat_amount_differs_from_rate:"
                    f"expected_{expected_amount}:actual_{proposal.vat_amount_minor}"
                )

        missing_accounts = [
            line.account
            for line in proposal.accounting_entries()
            if self.account_plan.lookup(line.account) is None
        ]
        if missing_accounts:
            errors.append("unknown_bas_accounts:" + ",".join(sorted(set(missing_accounts))))

        return ValidationResult(
            check="vat_mapping",
            passed=not errors,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def export_comparison(
        self,
        proposal: SupplierInvoiceProposal,
        draft: ShadowTransactionDraft,
    ) -> ShadowLedgerComparison:
        validations = (
            self.validate_debit_credit_balance(draft),
            self.validate_vat_mapping(proposal, draft),
        )
        warnings = [
            "gnubok_shadow_ledger_is_experimental",
            "fortnox_remains_production_source_of_truth",
        ]
        for validation in validations:
            warnings.extend(validation.warnings)
            warnings.extend(validation.errors)
        differences = _compare_rows(
            fortnox_supplier_invoice_payload(proposal)["accounting_rows"],
            [line.to_dict() for line in draft.lines],
        )
        return ShadowLedgerComparison(
            status="mirrored" if all(item.passed for item in validations) else "mirrored_with_warnings",
            source_of_truth="fortnox",
            fortnox_payload=fortnox_supplier_invoice_payload(proposal),
            accounting_proposal=proposal.to_dict(),
            shadow_proposal={
                "adapter": self.adapter_name,
                "gnubok_mode": "local_stub",
                "sie4i_candidate": True,
                "draft": draft.to_dict(),
            },
            differences=tuple(differences),
            warnings=tuple(dict.fromkeys(warnings)),
            validations=validations,
        )


def default_shadow_ledger_adapter() -> ShadowLedgerAdapter:
    """Return the best safe shadow adapter for the current environment."""

    if shutil.which("gnubok") is None:
        return LocalGnubokShadowLedgerAdapter()
    return LocalGnubokShadowLedgerAdapter()


def mirror_supplier_invoice_proposal_to_shadow(
    proposal: SupplierInvoiceProposal,
    *,
    adapter: ShadowLedgerAdapter | None = None,
    fiscal_year: str | None = None,
    fail_soft: bool = True,
) -> ShadowLedgerComparison:
    adapter = adapter or default_shadow_ledger_adapter()
    try:
        company = adapter.get_or_create_company_context(
            company_id=proposal.client_id,
            fiscal_year=fiscal_year or proposal.invoice_date[:4],
            display_name=proposal.client_id,
        )
        draft = adapter.create_draft_transaction(company, proposal)
        return adapter.export_comparison(proposal, draft)
    except ShadowLedgerUnavailable as exc:
        return _shadow_unavailable_comparison(proposal, str(exc))
    except Exception as exc:
        if not fail_soft:
            raise
        return _shadow_unavailable_comparison(
            proposal,
            f"shadow_ledger_failed_soft:{exc.__class__.__name__}",
        )


def _shadow_unavailable_comparison(
    proposal: SupplierInvoiceProposal,
    warning: str,
) -> ShadowLedgerComparison:
    return ShadowLedgerComparison(
        status="shadow_unavailable",
        source_of_truth="fortnox",
        fortnox_payload=fortnox_supplier_invoice_payload(proposal),
        accounting_proposal=proposal.to_dict(),
        shadow_proposal=None,
        differences=(),
        warnings=(
            warning,
            "main_pipeline_unaffected",
            "fortnox_remains_production_source_of_truth",
        ),
        validations=(),
    )


def _compare_rows(
    fortnox_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
) -> list[str]:
    differences: list[str] = []
    fortnox_canonical = [_canonical_row(row) for row in fortnox_rows]
    shadow_canonical = [_canonical_row(row) for row in shadow_rows]
    if fortnox_canonical != shadow_canonical:
        differences.append("accounting_rows_differ")

    fortnox_total = _row_totals(fortnox_rows)
    shadow_total = _row_totals(shadow_rows)
    if fortnox_total != shadow_total:
        differences.append(
            "accounting_totals_differ:"
            f"fortnox_{fortnox_total[0]}_{fortnox_total[1]}:"
            f"shadow_{shadow_total[0]}_{shadow_total[1]}"
        )
    return differences


def _canonical_row(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("account")),
        int(row.get("debit_minor", 0)),
        int(row.get("credit_minor", 0)),
        row.get("vat_code"),
    )


def _row_totals(rows: list[dict[str, Any]]) -> tuple[int, int]:
    return (
        sum(int(row.get("debit_minor", 0)) for row in rows),
        sum(int(row.get("credit_minor", 0)) for row in rows),
    )
