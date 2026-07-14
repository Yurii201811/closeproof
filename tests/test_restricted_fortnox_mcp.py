from __future__ import annotations

import unittest
from datetime import UTC, datetime

from accounting_agent import (
    ActionType,
    FortnoxWriteAdapter,
    MCPPermissionMode,
    PermissionMode,
    PermitIssuer,
    PermitReviewRequired,
    PermitValidator,
    PolicyContext,
    RestrictedFortnoxMCP,
    RestrictedToolForbidden,
    RestrictedToolPermitError,
    ToolCallAuditLog,
    UnknownRestrictedTool,
    evaluate_policy,
)
from tests.permit_approval_helpers import issue_test_permit


FIXED_NOW = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
LOW_RISK_EVIDENCE = {
    "entity_id": "synthetic-test-entity",
    "currency": "SEK",
    "supplier_known": True,
    "customer_known": True,
    "bank_details_changed": False,
    "duplicate_risk": 0.0,
    "vat_confidence": 1.0,
    "ocr_confidence": 1.0,
    "period_locked": False,
    "new_supplier": False,
    "destructive_action": False,
    "external_communication": False,
    "tax_filing_payment": False,
}


def restricted_mcp() -> RestrictedFortnoxMCP:
    return RestrictedFortnoxMCP(
        audit_log=ToolCallAuditLog(),
        fortnox_adapter=FortnoxWriteAdapter(
            PermitValidator(clock=lambda: FIXED_NOW)
        ),
    )


def with_risk_evidence(payload: dict[str, object], **overrides: object) -> dict[str, object]:
    return {**payload, **LOW_RISK_EVIDENCE, **overrides}


def issue_permit(
    *,
    action_type: ActionType,
    case_id: str,
    payload: dict[str, object],
    permit_id: str = "permit_test",
):
    context = PolicyContext(
        action_type=action_type,
        client_id=str(payload["client_id"]),
        currency_code=str(payload["currency"]),
        amount_minor=int(payload.get("amount_minor", 0)),
        supplier_known=bool(payload["supplier_known"]),
        customer_known=bool(payload["customer_known"]),
        bank_details_changed=bool(payload["bank_details_changed"]),
        duplicate_risk=float(payload["duplicate_risk"]),
        vat_confidence=float(payload["vat_confidence"]),
        ocr_confidence=float(payload["ocr_confidence"]),
        period_locked=bool(payload["period_locked"]),
        new_supplier=bool(payload["new_supplier"]),
        destructive_action=bool(payload["destructive_action"]),
        external_communication=bool(payload["external_communication"]),
        tax_filing_payment=bool(payload["tax_filing_payment"]),
        risk_evidence_complete=True,
    )
    permit, decision, permit_store, approval_authority = issue_test_permit(
        context=context,
        case_id=case_id,
        payload=payload,
        now=FIXED_NOW,
        permit_id=permit_id,
        entity_id=str(payload["entity_id"]),
    )
    return permit, decision, permit_store, approval_authority


class RestrictedFortnoxRegistryTests(unittest.TestCase):
    def test_registry_classifies_all_required_permission_modes(self) -> None:
        mcp = restricted_mcp()
        modes = {metadata.permission_mode for metadata in mcp.tool_registry()}

        self.assertIn(MCPPermissionMode.READ_SAFE, modes)
        self.assertIn(MCPPermissionMode.DRAFT_ONLY, modes)
        self.assertIn(MCPPermissionMode.APPROVAL_REQUIRED, modes)
        self.assertIn(MCPPermissionMode.ESCALATION_REQUIRED, modes)
        self.assertIn(MCPPermissionMode.FORBIDDEN, modes)

        approve_tool = next(
            metadata
            for metadata in mcp.tool_registry()
            if metadata.tool_name == "fortnox_approve_supplier_invoice"
        )
        self.assertEqual(MCPPermissionMode.FORBIDDEN, approve_tool.permission_mode)
        self.assertEqual("not_issuable", approve_tool.required_permit)

    def test_agents_only_see_read_and_draft_tools(self) -> None:
        mcp = restricted_mcp()
        exposed_names = {metadata.tool_name for metadata in mcp.available_tools()}

        self.assertEqual(
            {
                "fortnox_get_supplier",
                "fortnox_list_accounts",
                "fortnox_prepare_supplier_invoice_draft",
                "fortnox_prepare_voucher_draft",
            },
            exposed_names,
        )
        self.assertNotIn("fortnox_approve_supplier_invoice", exposed_names)
        self.assertNotIn("fortnox_delete_supplier", exposed_names)


class RestrictedFortnoxToolTests(unittest.TestCase):
    def test_read_safe_get_supplier_is_allowed_without_permit_and_logged(self) -> None:
        mcp = restricted_mcp()

        result = mcp.call_tool(
            "fortnox_get_supplier",
            {"client_id": "client_alpha", "supplier_id": "supplier_123"},
        )

        self.assertEqual("read_safe", result["permission_mode"])
        self.assertEqual("supplier_123", result["supplier"]["supplier_id"])
        self.assertEqual(1, len(mcp.audit_log.entries))
        self.assertEqual("allowed", mcp.audit_log.entries[0].status)
        self.assertIsNone(mcp.audit_log.entries[0].permit_id)

    def test_draft_only_supplier_invoice_requires_execution_permit(self) -> None:
        mcp = restricted_mcp()
        payload = with_risk_evidence({
            "client_id": "client_alpha",
            "supplier_id": "supplier_123",
            "amount_minor": 1_500_00,
            "currency": "SEK",
        })

        with self.assertRaises(RestrictedToolPermitError):
            mcp.call_tool(
                "fortnox_prepare_supplier_invoice_draft",
                payload,
                case_id="case_draft_1",
            )

        self.assertEqual("denied", mcp.audit_log.entries[0].status)

    def test_draft_tool_fails_closed_when_risk_evidence_is_omitted(self) -> None:
        mcp = restricted_mcp()

        with self.assertRaises(RestrictedToolPermitError):
            mcp.call_tool(
                "fortnox_prepare_supplier_invoice_draft",
                {
                    "client_id": "client_alpha",
                    "entity_id": "synthetic-test-entity",
                    "supplier_id": "supplier_123",
                    "amount_minor": 1_500_00,
                    "currency": "SEK",
                },
                case_id="case_missing_evidence",
            )

        self.assertEqual("denied", mcp.audit_log.entries[0].status)

    def test_valid_draft_only_permit_prepares_supplier_invoice_mock(self) -> None:
        mcp = restricted_mcp()
        payload = with_risk_evidence({
            "client_id": "client_alpha",
            "supplier_id": "supplier_123",
            "amount_minor": 1_500_00,
            "currency": "SEK",
        })
        permit, decision, _, _ = issue_permit(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            case_id="case_draft_2",
            payload=payload,
            permit_id="permit_draft_2",
        )

        result = mcp.call_tool(
            "fortnox_prepare_supplier_invoice_draft",
            payload,
            case_id="case_draft_2",
            permit=permit,
        )

        self.assertEqual(PermissionMode.DRAFT_ONLY, decision.permission_mode)
        self.assertEqual("supplier_invoice_draft_prepared_no_live_write", result["status"])
        self.assertEqual("permit_validated_no_live_write", result["adapter_status"])
        self.assertEqual("draft_only", result["policy"]["permission_mode"])
        self.assertEqual("allowed", mcp.audit_log.entries[0].status)
        self.assertEqual("permit_draft_2", mcp.audit_log.entries[0].permit_id)

    def test_valid_draft_only_permit_prepares_voucher_mock(self) -> None:
        mcp = restricted_mcp()
        payload = with_risk_evidence({
            "client_id": "client_alpha",
            "amount_minor": 2_500_00,
            "voucher_date": "2026-05-16",
            "rows": [
                {"account": "5410", "debit_minor": 2_000_00},
                {"account": "2641", "debit_minor": 500_00},
                {"account": "2440", "credit_minor": 2_500_00},
            ],
        })
        permit, decision, _, _ = issue_permit(
            action_type=ActionType.DRAFT_VOUCHER,
            case_id="case_voucher_1",
            payload=payload,
            permit_id="permit_voucher_1",
        )

        result = mcp.call_tool(
            "fortnox_prepare_voucher_draft",
            payload,
            case_id="case_voucher_1",
            permit=permit,
        )

        self.assertEqual(PermissionMode.DRAFT_ONLY, decision.permission_mode)
        self.assertEqual("voucher_draft_prepared_no_live_write", result["status"])
        self.assertEqual("permit_validated_no_live_write", result["adapter_status"])

    def test_approval_required_draft_fails_closed_without_reviewed_permit(self) -> None:
        payload = with_risk_evidence({
            "client_id": "client_alpha",
            "supplier_id": "supplier_123",
            "amount_minor": 50_000_00,
            "currency": "SEK",
        })
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_alpha",
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)

        with self.assertRaises(PermitReviewRequired):
            PermitIssuer(clock=lambda: FIXED_NOW).issue(
                decision=decision,
                context=context,
                case_id="case_review_1",
                entity_id=str(payload["entity_id"]),
                payload=payload,
            )

    def test_approval_required_draft_succeeds_only_with_reviewed_permit(self) -> None:
        mcp = restricted_mcp()
        payload = with_risk_evidence({
            "client_id": "client_alpha",
            "supplier_id": "supplier_123",
            "amount_minor": 50_000_00,
            "currency": "SEK",
        })
        permit, decision, permit_store, approval_authority = issue_permit(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            case_id="case_review_2",
            payload=payload,
            permit_id="permit_review_2",
        )
        mcp.fortnox_adapter.permit_validator = PermitValidator(
            clock=lambda: FIXED_NOW,
            permit_store=permit_store,
            approval_authority=approval_authority,
        )

        result = mcp.call_tool(
            "fortnox_prepare_supplier_invoice_draft",
            payload,
            case_id="case_review_2",
            permit=permit,
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertEqual("approval_required", result["policy"]["permission_mode"])
        self.assertEqual("supplier_invoice_draft_prepared_no_live_write", result["status"])

    def test_draft_tool_rejects_cross_entity_permit(self) -> None:
        mcp = restricted_mcp()
        payload = with_risk_evidence({
            "client_id": "client_alpha",
            "supplier_id": "supplier_123",
            "amount_minor": 1_500_00,
            "currency": "SEK",
        })
        permit, _, _, _ = issue_permit(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            case_id="case_cross_entity",
            payload=payload,
            permit_id="permit_cross_entity",
        )

        with self.assertRaisesRegex(RestrictedToolPermitError, "entity_id"):
            mcp.call_tool(
                "fortnox_prepare_supplier_invoice_draft",
                {**payload, "entity_id": "different-entity"},
                case_id="case_cross_entity",
                permit=permit,
            )

    def test_approval_and_delete_examples_are_forbidden_even_with_permit_attempts(self) -> None:
        mcp = restricted_mcp()
        approval_payload = {
            "client_id": "client_alpha",
            "supplier_invoice_id": "supplier_invoice_123",
        }
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.APPROVE_SUPPLIER_INVOICE,
                client_id="client_alpha",
                currency_code="SEK",
            )
        )

        with self.assertRaises(RestrictedToolForbidden):
            mcp.call_tool(
                "fortnox_approve_supplier_invoice",
                approval_payload,
                case_id="case_forbidden_approval",
            )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual("denied", mcp.audit_log.entries[0].status)

        with self.assertRaises(RestrictedToolForbidden):
            mcp.call_tool(
                "fortnox_delete_supplier",
                {"client_id": "client_alpha", "supplier_id": "supplier_123"},
                case_id="case_forbidden_delete",
            )

        self.assertEqual("denied", mcp.audit_log.entries[1].status)

    def test_unknown_tool_fails_closed_and_is_logged(self) -> None:
        mcp = restricted_mcp()

        with self.assertRaises(UnknownRestrictedTool):
            mcp.call_tool("fortnox_raw_update_supplier", {"client_id": "client_alpha"})

        self.assertEqual(1, len(mcp.audit_log.entries))
        self.assertEqual("denied", mcp.audit_log.entries[0].status)
        self.assertEqual("fortnox_raw_update_supplier", mcp.audit_log.entries[0].tool_name)


if __name__ == "__main__":
    unittest.main()
