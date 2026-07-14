from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any

from accounting_agent import (
    ActionType,
    FortnoxAdapter,
    FortnoxConfig,
    FortnoxPolicyViolation,
    FortnoxProtectedOperation,
    InMemoryIdempotencyStore,
    MissingFortnoxCredentials,
    PermissionMode,
    PermitValidationError,
    PermitValidator,
    PolicyContext,
    evaluate_policy,
)
from accounting_agent.adapters.fortnox import HttpFortnoxTransport
from tests.permit_approval_helpers import issue_test_permit


PERMIT_ISSUED_AT = datetime.now(UTC).replace(microsecond=0)
ENTITY_ID = "synthetic-test-entity"


class MockFortnoxTransport:
    def __init__(self) -> None:
        self.get_responses: dict[tuple[str, tuple[tuple[str, Any], ...]], dict[str, Any]] = {}
        self.post_responses: dict[str, dict[str, Any]] = {}
        self.posts: list[tuple[str, dict[str, Any], str]] = []

    def add_get(
        self,
        path: str,
        response: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> None:
        self.get_responses[(path, tuple(sorted((params or {}).items())))] = response

    def add_post(self, path: str, response: dict[str, Any]) -> None:
        self.post_responses[path] = response

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.get_responses[(path, tuple(sorted((params or {}).items())))]

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        idempotency_key: str,
        permit: object,
    ) -> dict[str, Any]:
        self.posts.append((path, json_body, idempotency_key))
        return self.post_responses[path]


class FortnoxReadTests(unittest.TestCase):
    def test_reads_reference_data_from_mock_transport(self) -> None:
        transport = MockFortnoxTransport()
        transport.add_get("/accounts", {"Accounts": [{"Number": 2440}]})
        transport.add_get("/accounts/2440", {"Account": {"Number": 2440}})
        transport.add_get("/suppliers", {"Suppliers": [{"SupplierNumber": "42"}]})
        transport.add_get("/suppliers/42", {"Supplier": {"SupplierNumber": "42"}})
        transport.add_get("/customers", {"Customers": [{"CustomerNumber": "7"}]})
        transport.add_get("/customers/7", {"Customer": {"CustomerNumber": "7"}})
        transport.add_get("/financialyears", {"FinancialYears": [{"Id": 1}]})
        transport.add_get("/financialyears/1", {"FinancialYear": {"Id": 1}})

        adapter = FortnoxAdapter(transport=transport)

        self.assertEqual(2440, adapter.list_accounts()[0]["Number"])
        self.assertEqual(2440, adapter.get_account(2440)["Number"])
        self.assertEqual("42", adapter.list_suppliers()[0]["SupplierNumber"])
        self.assertEqual("42", adapter.get_supplier("42")["SupplierNumber"])
        self.assertEqual("7", adapter.list_customers()[0]["CustomerNumber"])
        self.assertEqual("7", adapter.get_customer("7")["CustomerNumber"])
        self.assertEqual(1, adapter.list_financial_years()[0]["Id"])
        self.assertEqual(1, adapter.get_financial_year(1)["Id"])

    def test_sensitive_reads_are_blocked_by_default(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())

        with self.assertRaises(FortnoxPolicyViolation):
            adapter.list_vouchers()
        with self.assertRaises(FortnoxPolicyViolation):
            adapter.list_invoices()
        with self.assertRaises(FortnoxPolicyViolation):
            adapter.list_supplier_invoices()

    def test_sensitive_reads_can_be_enabled_for_mocked_read_only_flow(self) -> None:
        transport = MockFortnoxTransport()
        transport.add_get("/supplierinvoices", {"SupplierInvoices": [{"GivenNumber": "1"}]})
        adapter = FortnoxAdapter(
            config=FortnoxConfig(allow_sensitive_reads=True),
            transport=transport,
        )

        self.assertEqual("1", adapter.list_supplier_invoices()[0]["GivenNumber"])

    def test_real_transport_requires_credentials_for_reads(self) -> None:
        adapter = FortnoxAdapter(config=FortnoxConfig(access_token=None))

        with self.assertRaises(MissingFortnoxCredentials):
            adapter.list_accounts()


class FortnoxDraftPayloadTests(unittest.TestCase):
    def test_prepare_supplier_invoice_draft_payload(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())

        payload = adapter.prepare_supplier_invoice_draft_payload(
            supplier_number="42",
            invoice_number="INV-123",
            invoice_date="2026-05-16",
            due_date="2026-06-15",
            total="1250.00",
            vat="250.00",
            rows=[
                {
                    "account": 4010,
                    "debit": "1000.00",
                    "description": "Consulting",
                    "project": "pilot",
                }
            ],
            comments="Prepared by accounting agent dry run",
        )

        invoice = payload["SupplierInvoice"]
        self.assertFalse(invoice["Booked"])
        self.assertFalse(invoice["PaymentPending"])
        self.assertTrue(invoice["DisablePaymentFile"])
        self.assertEqual("42", invoice["SupplierNumber"])
        self.assertEqual("1250.00", invoice["Total"])
        self.assertEqual(4010, invoice["SupplierInvoiceRows"][0]["Account"])

    def test_prepare_voucher_draft_payload_requires_balanced_rows(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())

        payload = adapter.prepare_voucher_draft_payload(
            transaction_date="2026-05-16",
            description="Supplier invoice proposal",
            voucher_series="A",
            rows=[
                {"account": 4010, "debit": "1000.00"},
                {"account": 2440, "credit": "1000.00"},
            ],
        )

        self.assertEqual("A", payload["Voucher"]["VoucherSeries"])
        self.assertEqual("1000.00", payload["Voucher"]["VoucherRows"][0]["Debit"])

        with self.assertRaises(ValueError):
            adapter.prepare_voucher_draft_payload(
                transaction_date="2026-05-16",
                description="Unbalanced proposal",
                voucher_series="A",
                rows=[
                    {"account": 4010, "debit": "1000.00"},
                    {"account": 2440, "credit": "999.00"},
                ],
            )


class FortnoxDraftCreateTests(unittest.TestCase):
    def test_create_supplier_invoice_draft_requires_permit_even_in_dry_run(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())
        payload = _supplier_invoice_payload(adapter)

        with self.assertRaises(PermitValidationError):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=None,
            )

    def test_create_supplier_invoice_draft_dry_run_records_idempotency(self) -> None:
        store = InMemoryIdempotencyStore()
        transport = MockFortnoxTransport()
        adapter = FortnoxAdapter(transport=transport, idempotency_store=store)
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(ActionType.DRAFT_SUPPLIER_INVOICE, payload)

        first = adapter.create_supplier_invoice_draft(
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload=payload,
            permit=permit,
        )
        second = adapter.create_supplier_invoice_draft(
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload=payload,
            permit=permit,
        )

        self.assertEqual("dry_run_draft_not_created", first.status)
        self.assertTrue(first.dry_run)
        self.assertEqual("duplicate_idempotency_key", second.status)
        self.assertEqual(first.idempotency_key, second.duplicate_of)
        self.assertEqual([], transport.posts)

    def test_create_supplier_invoice_draft_rejects_cross_entity_permit(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(ActionType.DRAFT_SUPPLIER_INVOICE, payload)

        with self.assertRaisesRegex(PermitValidationError, "entity_id"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id="different-entity",
                payload=payload,
                permit=permit,
            )

    def test_live_supplier_invoice_draft_requires_explicit_config(self) -> None:
        transport = MockFortnoxTransport()
        adapter = FortnoxAdapter(
            config=FortnoxConfig(dry_run=False, allow_draft_writes=False),
            transport=transport,
        )
        payload = _supplier_invoice_payload(adapter)
        permit, permit_store, approval_authority = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
            return_store=True,
        )
        adapter.permit_validator = PermitValidator(
            clock=lambda: PERMIT_ISSUED_AT,
            permit_store=permit_store,
            approval_authority=approval_authority,
        )

        with self.assertRaises(FortnoxPolicyViolation):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_live_supplier_invoice_draft_rejects_draft_only_permit(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            ),
            transport=MockFortnoxTransport(),
        )
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(ActionType.DRAFT_SUPPLIER_INVOICE, payload)

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_live_supplier_invoice_draft_remains_blocked_after_permit_and_config(self) -> None:
        transport = MockFortnoxTransport()
        transport.add_post(
            "/supplierinvoices",
            {"SupplierInvoice": {"GivenNumber": "1001", "Booked": False}},
        )
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            ),
            transport=transport,
        )
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
        )

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )
        self.assertEqual([], transport.posts)

    def test_http_transport_post_requires_execution_permit(self) -> None:
        transport = HttpFortnoxTransport(
            FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            )
        )

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            transport.post(
                "/supplierinvoices",
                json_body={"SupplierInvoice": {"Booked": False}},
                idempotency_key="not-a-valid-permit-key",
                permit=None,  # type: ignore[arg-type]
            )

    def test_live_write_without_credentials_has_clear_error(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(dry_run=False, allow_draft_writes=True, access_token=None)
        )
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
        )

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_voucher_draft_never_posts_live(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            ),
            transport=MockFortnoxTransport(),
        )
        payload = adapter.prepare_voucher_draft_payload(
            transaction_date="2026-05-16",
            description="Dry-run voucher only",
            voucher_series="A",
            rows=[
                {"account": 4010, "debit": "1000.00"},
                {"account": 2440, "credit": "1000.00"},
            ],
        )
        permit = _permit_for(ActionType.DRAFT_VOUCHER, payload)

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_voucher_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_forbidden_payload_markers_are_blocked(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=True,
                allow_draft_writes=True,
            ),
            transport=MockFortnoxTransport(),
        )
        payload = _supplier_invoice_payload(adapter)
        payload["SupplierInvoice"]["Booked"] = True
        permit, permit_store, approval_authority = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
            return_store=True,
        )
        adapter.permit_validator = PermitValidator(
            clock=lambda: PERMIT_ISSUED_AT,
            permit_store=permit_store,
            approval_authority=approval_authority,
        )

        with self.assertRaises(FortnoxProtectedOperation):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )


class FortnoxPolicyProtectionTests(unittest.TestCase):
    def test_forbidden_fortnox_actions_are_policy_forbidden(self) -> None:
        for action_type in (
            ActionType.POST_VOUCHER,
            ActionType.SEND_INVOICE,
            ActionType.APPROVE_SUPPLIER_INVOICE,
            ActionType.START_PAYMENT,
            ActionType.DELETE_RECORD,
            ActionType.CHANGE_SETTINGS,
        ):
            decision = evaluate_policy(
                PolicyContext(action_type=action_type, client_id="client_123", currency_code="SEK")
            )
            self.assertEqual(
                PermissionMode.FORBIDDEN,
                decision.permission_mode,
                f"{action_type.value} should be blocked",
            )


def _supplier_invoice_payload(adapter: FortnoxAdapter) -> dict[str, Any]:
    return adapter.prepare_supplier_invoice_draft_payload(
        supplier_number="42",
        invoice_number="INV-123",
        invoice_date="2026-05-16",
        due_date="2026-06-15",
        total="1250.00",
        vat="250.00",
        rows=[{"account": 4010, "debit": "1000.00"}],
    )


def _permit_for(
    action_type: ActionType,
    payload: dict[str, Any],
    *,
    amount_minor: int = 1_250_00,
    return_store: bool = False,
):
    context = PolicyContext(
        action_type=action_type,
        client_id="client_123",
        currency_code="SEK",
        amount_minor=amount_minor,
        risk_evidence_complete=True,
    )
    permit, _, permit_store, approval_authority = issue_test_permit(
        context=context,
        case_id="case_1",
        payload=payload,
        now=PERMIT_ISSUED_AT,
        permit_id=f"permit_{action_type.value}",
        entity_id=ENTITY_ID,
    )
    if return_store:
        return permit, permit_store, approval_authority
    return permit


if __name__ == "__main__":
    unittest.main()
