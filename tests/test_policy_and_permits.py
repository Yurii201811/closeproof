from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from accounting_agent import (
    ActionType,
    AmountThresholds,
    EmailWriteAdapter,
    ExecutionPermit,
    FortnoxWriteAdapter,
    InMemoryPermitStore,
    PermissionMode,
    PermitIssuer,
    PermitReviewRequired,
    PermitValidationError,
    PermitValidator,
    PolicyContext,
    PolicyConfig,
    PolicyDecision,
    SQLitePermitStore,
    canonical_payload_hash,
    evaluate_policy,
)
from tests.permit_approval_helpers import issue_test_permit


FIXED_NOW = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
ENTITY_ID = "entity_123"


class PolicyDecisionTests(unittest.TestCase):
    def test_low_risk_draft_supplier_invoice_is_draft_only(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=1_500_00,
                supplier_known=True,
                duplicate_risk=0.0,
                vat_confidence=0.99,
                ocr_confidence=0.98,
                risk_evidence_complete=True,
            )
        )

        self.assertEqual(PermissionMode.DRAFT_ONLY, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)
        self.assertTrue(decision.is_external_write)

    def test_unconfigured_non_sek_currency_escalates_external_draft(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="JPY",
                amount_minor=1,
                risk_evidence_complete=True,
            )
        )

        self.assertEqual("JPY", decision.currency_code)
        self.assertIsNone(decision.amount_thresholds)
        self.assertEqual(PermissionMode.ESCALATION_REQUIRED, decision.permission_mode)
        self.assertIn("currency_thresholds_not_configured", decision.reasons)
        self.assertIn("senior_accountant_review", decision.required_reviews)

    def test_explicit_currency_thresholds_enable_currency_safe_draft(self) -> None:
        thresholds = AmountThresholds(
            draft_without_review_minor=10_000,
            escalation_required_minor=100_000,
        )
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="JPY",
                amount_minor=9_999,
                risk_evidence_complete=True,
            ),
            PolicyConfig(currency_amount_thresholds={"JPY": thresholds}),
        )

        self.assertEqual(thresholds, decision.amount_thresholds)
        self.assertEqual(PermissionMode.DRAFT_ONLY, decision.permission_mode)
        self.assertNotIn("currency_thresholds_not_configured", decision.reasons)

    def test_client_currency_threshold_overrides_global_currency_threshold(self) -> None:
        global_thresholds = AmountThresholds(
            draft_without_review_minor=10_000,
            escalation_required_minor=100_000,
        )
        client_thresholds = AmountThresholds(
            draft_without_review_minor=500,
            escalation_required_minor=2_000,
        )
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="JPY",
                amount_minor=2_000,
                risk_evidence_complete=True,
            ),
            PolicyConfig(
                currency_amount_thresholds={"JPY": global_thresholds},
                client_currency_amount_thresholds={
                    ("client_123", "JPY"): client_thresholds
                },
            ),
        )

        self.assertEqual(client_thresholds, decision.amount_thresholds)
        self.assertEqual(PermissionMode.ESCALATION_REQUIRED, decision.permission_mode)
        self.assertIn("amount_exceeds_escalation_threshold", decision.reasons)

    def test_currency_and_threshold_configuration_rejects_ambiguous_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "uppercase three-letter"):
            evaluate_policy(
                PolicyContext(
                    action_type=ActionType.READ_ANALYSIS,
                    client_id="client_123",
                    currency_code="sek",
                )
            )
        with self.assertRaisesRegex(ValueError, "must exceed"):
            AmountThresholds(
                draft_without_review_minor=100,
                escalation_required_minor=100,
            )

    def test_changed_bank_details_escalate(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.UPDATE_SUPPLIER_BANK_DETAILS,
                client_id="client_123",
                currency_code="SEK",
                bank_details_changed=True,
            )
        )

        self.assertEqual(PermissionMode.ESCALATION_REQUIRED, decision.permission_mode)
        self.assertIn("senior_accountant_review", decision.required_reviews)
        self.assertIn("security_review", decision.required_reviews)

    def test_large_amount_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=50_000_00,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("accountant_review", decision.required_reviews)
        self.assertIn("amount_exceeds_draft_threshold", decision.reasons)

    def test_unknown_supplier_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                supplier_known=False,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("supplier_not_previously_known", decision.reasons)

    def test_vat_uncertainty_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                vat_confidence=0.71,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("vat_confidence_below_threshold", decision.reasons)

    def test_duplicate_risk_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                duplicate_risk=0.87,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("duplicate_risk", decision.reasons)

    def test_destructive_action_is_forbidden(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DELETE_RECORD,
                client_id="client_123",
                currency_code="SEK",
                destructive_action=True,
            )
        )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)

    def test_payment_is_forbidden(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.START_PAYMENT,
                client_id="client_123",
                currency_code="SEK",
                tax_filing_payment=True,
            )
        )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)

    def test_live_bank_reconciliation_is_forbidden(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.RECONCILE_BANK_TRANSACTION,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=1_500_00,
            )
        )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)

    def test_tax_filing_escalates(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.FILE_TAX_RETURN,
                client_id="client_123",
                currency_code="SEK",
                tax_filing_payment=True,
            )
        )

        self.assertEqual(PermissionMode.ESCALATION_REQUIRED, decision.permission_mode)
        self.assertIn("client_responsible_review", decision.required_reviews)


class PermitAndExternalWriteTests(unittest.TestCase):
    def test_external_write_requires_valid_execution_permit(self) -> None:
        adapter = FortnoxWriteAdapter()
        payload = {"supplier_id": "supplier_1", "amount_minor": 1_500_00}

        with self.assertRaises(PermitValidationError):
            adapter.execute(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=None,
            )

    def test_valid_draft_permit_allows_adapter_boundary(self) -> None:
        store = InMemoryPermitStore()
        issuer = PermitIssuer(
            store,
            clock=lambda: FIXED_NOW,
            id_factory=lambda: "permit_test_1",
        )
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            currency_code="SEK",
            amount_minor=1_500_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        payload = {"supplier_id": "supplier_1", "amount_minor": 1_500_00}

        permit = issuer.issue(
            decision=decision,
            context=context,
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload=payload,
        )
        result = FortnoxWriteAdapter(
            PermitValidator(accepted_policy_version=decision.policy_version, clock=lambda: FIXED_NOW)
        ).execute(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload=payload,
            permit=permit,
        )

        self.assertEqual("permit_validated_no_live_write", result.status)
        self.assertEqual(permit.idempotency_key, result.idempotency_key)
        self.assertEqual(permit, store.get("permit_test_1"))

    def test_payload_change_invalidates_permit(self) -> None:
        issuer = PermitIssuer(clock=lambda: FIXED_NOW, id_factory=lambda: "permit_test_2")
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            currency_code="SEK",
            amount_minor=1_500_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        permit = issuer.issue(
            decision=decision,
            context=context,
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload={"supplier_id": "supplier_1", "amount_minor": 1_500_00},
        )

        with self.assertRaises(PermitValidationError):
            FortnoxWriteAdapter(
                PermitValidator(accepted_policy_version=decision.policy_version, clock=lambda: FIXED_NOW)
            ).execute(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload={"supplier_id": "supplier_1", "amount_minor": 1_600_00},
                permit=permit,
            )

    def test_approval_required_decision_cannot_issue_without_review(self) -> None:
        issuer = PermitIssuer(clock=lambda: FIXED_NOW, id_factory=lambda: "permit_test_3")
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            currency_code="SEK",
            amount_minor=50_000_00,
        )
        decision = evaluate_policy(context)

        with self.assertRaises(PermitReviewRequired):
            issuer.issue(
                decision=decision,
                context=context,
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload={"amount_minor": 50_000_00},
            )

    def test_caller_asserted_review_labels_cannot_issue_reviewed_permit(self) -> None:
        issuer = PermitIssuer(clock=lambda: FIXED_NOW, id_factory=lambda: "permit_forged_review")
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)

        with self.assertRaisesRegex(PermitReviewRequired, "trusted approval"):
            issuer.issue(
                decision=decision,
                context=context,
                case_id="case_forged_review",
                entity_id=ENTITY_ID,
                payload={"amount_minor": 50_000_00},
                approved_reviews=("accountant_review",),
            )

    def test_email_adapter_validates_permit_but_does_not_send(self) -> None:
        context = PolicyContext(
            action_type=ActionType.SEND_EMAIL,
            client_id="client_123",
            currency_code="SEK",
            external_communication=True,
        )
        decision = evaluate_policy(context)
        payload = {"to": "reviewer@example.invalid", "subject": "Missing receipt"}
        permit, _, permit_store, approval_authority = issue_test_permit(
            context=context,
            case_id="case_2",
            payload=payload,
            now=FIXED_NOW,
            permit_id="permit_test_4",
            entity_id=ENTITY_ID,
        )

        result = EmailWriteAdapter(
            PermitValidator(
                accepted_policy_version=decision.policy_version,
                clock=lambda: FIXED_NOW,
                permit_store=permit_store,
                approval_authority=approval_authority,
            )
        ).execute(
            action_type=ActionType.SEND_EMAIL,
            case_id="case_2",
            entity_id=ENTITY_ID,
            payload=payload,
            permit=permit,
        )

        self.assertEqual("permit_validated_no_email_sent", result.status)

    def test_sqlite_store_round_trips_permit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLitePermitStore(f"{temp_dir}/permits.sqlite")
            issuer = PermitIssuer(
                store,
                clock=lambda: FIXED_NOW,
                id_factory=lambda: "permit_test_5",
            )
            context = PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=1_500_00,
                risk_evidence_complete=True,
            )
            decision = evaluate_policy(context)
            permit = issuer.issue(
                decision=decision,
                context=context,
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload={"amount_minor": 1_500_00},
            )

            self.assertEqual(permit, store.get("permit_test_5"))

    def test_missing_risk_evidence_fails_closed_for_external_draft(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=1_500_00,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("risk_evidence_incomplete", decision.reasons)

    def test_unmapped_client_fails_closed_for_external_draft(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="unmapped",
                currency_code="SEK",
                amount_minor=1_500_00,
                risk_evidence_complete=True,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("client_mapping_unmapped", decision.reasons)

    def test_forged_policy_decision_cannot_issue_permit(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        real_decision = evaluate_policy(context)
        forged_decision = PolicyDecision(
            action_type=real_decision.action_type,
            client_id=real_decision.client_id,
            currency_code=real_decision.currency_code,
            permission_mode=PermissionMode.DRAFT_ONLY,
            policy_version=real_decision.policy_version,
            amount_thresholds=real_decision.amount_thresholds,
            required_reviews=(),
            reasons=("forged",),
            is_external_write=real_decision.is_external_write,
        )

        with self.assertRaises(PermitValidationError):
            PermitIssuer(clock=lambda: FIXED_NOW).issue(
                decision=forged_decision,
                context=context,
                case_id="case_forged",
                entity_id=ENTITY_ID,
                payload={"amount_minor": 50_000_00},
            )

    def test_direct_permit_with_empty_idempotency_key_is_rejected(self) -> None:
        payload = {"supplier_id": "supplier_1", "amount_minor": 1_500_00}
        permit = ExecutionPermit(
            permit_id="permit_direct",
            case_id="case_direct",
            client_id="client_123",
            allowed_action=ActionType.DRAFT_SUPPLIER_INVOICE,
            payload_hash=canonical_payload_hash(payload),
            policy_version="accounting-policy-v1",
            required_reviews=(),
            permission_mode=PermissionMode.DRAFT_ONLY,
            expires_at=datetime(2026, 5, 16, 12, 30, tzinfo=UTC),
            idempotency_key="",
            issued_at=FIXED_NOW,
            entity_id=ENTITY_ID,
        )

        with self.assertRaises(PermitValidationError):
            FortnoxWriteAdapter(
                PermitValidator(clock=lambda: FIXED_NOW)
            ).execute(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="case_direct",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )


if __name__ == "__main__":
    unittest.main()
