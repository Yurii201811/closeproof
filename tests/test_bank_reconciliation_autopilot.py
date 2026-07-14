from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from accounting_agent import ActionType, PermissionMode, PolicyContext, evaluate_policy
from accounting_agent.bank_reconciliation import (
    BankReconciliationPipeline,
    MatchTargetType,
    load_fixture_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "bank_reconciliation"


class BankReconciliationAutopilotTests(unittest.TestCase):
    def run_pipeline(self) -> tuple[list[dict], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_dir = Path(temp_dir.name) / "packets"
        pipeline = BankReconciliationPipeline(output_dir=output_dir)
        proposals = pipeline.process_fixture_dir(FIXTURES)
        return proposals, output_dir

    def test_processes_bank_transactions_into_policy_gated_proposals(self) -> None:
        proposals, output_dir = self.run_pipeline()

        self.assertEqual(7, len(proposals))
        self.assertEqual(4, len(list(output_dir.glob("*.bank_reconciliation_packet.json"))))

        modes = {proposal["policy_decision"]["mode"] for proposal in proposals}
        modes.add(proposals[0]["matching_policy_decision"]["mode"])
        modes.add(proposals[0]["live_reconciliation_policy_decision"]["mode"])
        self.assertIn("auto_allowed", modes)
        self.assertIn("draft_only", modes)
        self.assertIn("approval_required", modes)
        self.assertIn("escalation_required", modes)
        self.assertIn("forbidden", modes)

        for proposal in proposals:
            transaction = proposal["transaction"]
            self.assertTrue(transaction["transaction_id"])
            self.assertTrue(transaction["date"])
            self.assertIsInstance(transaction["amount_minor"], int)
            self.assertTrue(transaction["currency"])
            self.assertIn("counterparty", transaction)
            self.assertIn("reference", transaction)
            self.assertTrue(transaction["bank_account"])
            self.assertTrue(transaction["source"])
            self.assertEqual("auto_allowed", proposal["matching_policy_decision"]["mode"])
            self.assertEqual("forbidden", proposal["live_reconciliation_policy_decision"]["mode"])
            self.assertFalse(proposal["reconciliation_payload"]["live_api_call"])
            self.assertFalse(proposal["reconciliation_payload"]["reconciles_in_fortnox"])
            self.assertTrue(proposal["explanations"])

    def test_exact_customer_invoice_payment_is_high_confidence_draft_only(self) -> None:
        proposals, _ = self.run_pipeline()
        proposal = by_transaction(proposals, "BR-001")

        self.assertEqual("CI-2026-2001", proposal["selected_candidate"]["target_id"])
        self.assertEqual("customer_invoice", proposal["selected_candidate"]["target_type"])
        self.assertGreaterEqual(proposal["confidence"], 0.95)
        self.assertEqual("draft_only", proposal["policy_decision"]["mode"])
        self.assertNotIn("approval_packet", proposal)
        self.assertIn("Amount exactly equals", " ".join(proposal["explanations"]))

    def test_exact_supplier_invoice_payment_is_high_confidence_draft_only(self) -> None:
        proposals, _ = self.run_pipeline()
        proposal = by_transaction(proposals, "BR-002")

        self.assertEqual("SI-2026-0501", proposal["selected_candidate"]["target_id"])
        self.assertEqual("supplier_invoice", proposal["selected_candidate"]["target_type"])
        self.assertGreaterEqual(proposal["confidence"], 0.95)
        self.assertEqual("draft_only", proposal["policy_decision"]["mode"])
        self.assertFalse(proposal["reconciliation_payload"]["starts_payment"])

    def test_partial_payment_requires_approval_packet(self) -> None:
        proposals, _ = self.run_pipeline()
        proposal = by_transaction(proposals, "BR-003")

        self.assertEqual("CI-2026-2003", proposal["selected_candidate"]["target_id"])
        self.assertLess(proposal["confidence"], 0.85)
        self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
        self.assertIn("partial_payment", risk_codes(proposal))
        self.assertIn("approval_packet", proposal)
        self.assertEqual(
            "prepare_partial_reconciliation_proposal_only",
            proposal["reconciliation_payload"]["proposal_action"],
        )

    def test_duplicate_looking_transactions_require_review(self) -> None:
        proposals, _ = self.run_pipeline()
        first = by_transaction(proposals, "BR-004A")
        second = by_transaction(proposals, "BR-004B")

        for proposal in (first, second):
            self.assertEqual("CI-2026-2002", proposal["selected_candidate"]["target_id"])
            self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
            self.assertEqual(0.85, proposal["risk"]["duplicate_risk"])
            self.assertIn("duplicate_looking_transaction", risk_codes(proposal))
            self.assertIn("approval_packet", proposal)

    def test_bank_fee_matches_voucher_template_without_live_posting(self) -> None:
        proposals, _ = self.run_pipeline()
        proposal = by_transaction(proposals, "BR-005")

        self.assertEqual("VOUCHER-BANK-FEE-2026-05", proposal["selected_candidate"]["target_id"])
        self.assertEqual("voucher", proposal["selected_candidate"]["target_type"])
        self.assertEqual("draft_only", proposal["policy_decision"]["mode"])
        self.assertEqual(
            "prepare_voucher_match_proposal_only",
            proposal["reconciliation_payload"]["proposal_action"],
        )
        self.assertIn("post_voucher", proposal["reconciliation_payload"]["blocked_actions"])

    def test_unknown_large_transaction_escalates_with_approval_packet(self) -> None:
        proposals, _ = self.run_pipeline()
        proposal = by_transaction(proposals, "BR-006")

        self.assertIsNone(proposal["selected_candidate"])
        self.assertEqual(0.0, proposal["confidence"])
        self.assertEqual("escalation_required", proposal["policy_decision"]["mode"])
        self.assertIn("unknown_transaction", risk_codes(proposal))
        self.assertIn("amount_exceeds_escalation_threshold", proposal["policy_decision"]["reasons"])
        self.assertIn("approval_packet", proposal)

    def test_fixture_catalog_includes_receipt_matching_target_type(self) -> None:
        _, targets = load_fixture_catalog(FIXTURES)

        self.assertIn(MatchTargetType.RECEIPT, {target.target_type for target in targets})

    def test_policy_engine_knows_bank_reconciliation_actions(self) -> None:
        draft_decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_BANK_RECONCILIATION,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=1_250_00,
                ocr_confidence=0.99,
                risk_evidence_complete=True,
            )
        )
        live_decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.RECONCILE_BANK_TRANSACTION,
                client_id="client_123",
                currency_code="SEK",
                amount_minor=1_250_00,
            )
        )

        self.assertEqual(PermissionMode.DRAFT_ONLY, draft_decision.permission_mode)
        self.assertEqual(PermissionMode.FORBIDDEN, live_decision.permission_mode)

    def test_cli_processes_bank_reconciliation_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "packets"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "reconcile-bank-fixtures",
                    "--fixtures",
                    str(FIXTURES),
                    "--output",
                    str(output_dir),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("Processed 7 bank transaction fixtures", result.stdout)
        self.assertIn("Approval packets generated: 4", result.stdout)


def by_transaction(proposals: list[dict], transaction_id: str) -> dict:
    for proposal in proposals:
        if proposal["transaction"]["transaction_id"] == transaction_id:
            return proposal
    raise AssertionError(f"Missing proposal for transaction {transaction_id}")


def risk_codes(proposal: dict) -> set[str]:
    return {flag["code"] for flag in proposal["risk"]["flags"]}


if __name__ == "__main__":
    unittest.main()
