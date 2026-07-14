from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime

from accounting_agent import (
    AccountingCase,
    InvoiceHistoryEntry,
    JsonlAuditLog,
    PermissionMode,
    ProposedAccountingEntry,
    RiskReviewConfig,
    RiskSignal,
    build_risk_report,
    render_approval_packet,
    review_accounting_case,
    review_supplier_invoice_case,
)


FIXED_NOW = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


class OpenclawRiskReviewTests(unittest.TestCase):
    def test_detects_all_required_supplier_invoice_risk_signals(self) -> None:
        findings = review_accounting_case(
            AccountingCase(
                case_id="case_risk_001",
                client_id="client_alpha",
                amount_minor=80_000_00,
                supplier_id="supplier_new",
                supplier_name="Fixture Supplier AB",
                supplier_known=False,
                invoice_number="INV-9",
                invoice_date=date(2026, 1, 10),
                accounting_period="2026-01",
                period_locked=True,
                source_document_id=None,
                source_document_hash="hash-current",
                has_source_document=False,
                ocr_confidence=0.42,
                vat_confidence=0.55,
                vat_amount_minor=12_500_00,
                known_supplier_bank_account="123-4567",
                stated_supplier_bank_account="999-0000",
                business_purpose="",
                description="Private home purchase",
                possible_personal_expense=True,
                supplier_amount_history_minor=(10_000_00, 12_000_00, 11_500_00),
                prior_invoices=(
                    InvoiceHistoryEntry(
                        case_id="case_prior",
                        supplier_id="supplier_new",
                        invoice_number="INV-9",
                        amount_minor=80_000_00,
                        invoice_date=date(2026, 1, 10),
                    ),
                ),
            ),
            today=date(2026, 5, 16),
        )

        self.assertEqual(
            {
                RiskSignal.DUPLICATE_RISK,
                RiskSignal.UNUSUAL_AMOUNT,
                RiskSignal.UNKNOWN_SUPPLIER,
                RiskSignal.CHANGED_BANK_DETAILS,
                RiskSignal.UNCLEAR_VAT,
                RiskSignal.LOW_OCR_CONFIDENCE,
                RiskSignal.LOCKED_OLD_PERIOD,
                RiskSignal.MISSING_SOURCE_DOCUMENT,
                RiskSignal.POSSIBLE_PERSONAL_EXPENSE,
                RiskSignal.MISSING_BUSINESS_PURPOSE,
            },
            {finding.signal for finding in findings},
        )
        self.assertTrue(all(finding.deterministic for finding in findings))

    def test_supplier_invoice_workflow_feeds_findings_into_policy_packet_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audit_log = JsonlAuditLog(f"{temp_dir}/audit.jsonl", clock=lambda: FIXED_NOW)
            result = review_supplier_invoice_case(
                AccountingCase(
                    case_id="case_bank_001",
                    client_id="client_alpha",
                    amount_minor=3_750_00,
                    supplier_id="supplier_123",
                    supplier_name="Fixture IT AB",
                    source_document_id="doc_123",
                    ocr_confidence=0.96,
                    vat_confidence=0.98,
                    known_supplier_bank_account="123-4567",
                    stated_supplier_bank_account="999-0000",
                    business_purpose="IT support",
                ),
                proposed_entries=(
                    ProposedAccountingEntry(
                        account="6540",
                        description="IT support",
                        debit_minor=3_000_00,
                        vat_code="input_vat_25",
                    ),
                ),
                audit_log=audit_log,
            )

            self.assertEqual(
                PermissionMode.ESCALATION_REQUIRED,
                result.policy_decision.permission_mode,
            )
            self.assertIn("security_review", result.policy_decision.required_reviews)
            self.assertIn("risk:changed_bank_details", result.policy_decision.reasons)
            self.assertEqual(
                "changed_bank_details",
                result.approval_packet.risk_findings[0]["signal"],
            )
            self.assertIn(
                "Structured risk findings",
                render_approval_packet(result.approval_packet),
            )
            self.assertEqual(1, len(audit_log.read_events()))
            self.assertEqual(
                "openclaw_risk_review_completed",
                audit_log.read_events()[0].event_type,
            )

    def test_optional_explanation_only_runs_for_deterministic_flags(self) -> None:
        calls: list[str] = []

        def explain(accounting_case: AccountingCase, finding) -> str:
            calls.append(finding.signal.value)
            return f"Explain {finding.signal.value} for {accounting_case.case_id}."

        clean_findings = review_accounting_case(
            AccountingCase(
                case_id="case_clean",
                client_id="client_alpha",
                amount_minor=1_250_00,
                source_document_id="doc_clean",
                business_purpose="Office material",
            ),
            config=RiskReviewConfig(require_business_purpose=True),
            explanation_provider=explain,
        )

        flagged_findings = review_accounting_case(
            AccountingCase(
                case_id="case_unknown",
                client_id="client_alpha",
                amount_minor=1_250_00,
                supplier_known=False,
                source_document_id="doc_unknown",
                business_purpose="Client event material",
            ),
            explanation_provider=explain,
        )

        self.assertEqual((), clean_findings)
        self.assertEqual(["unknown_supplier"], calls)
        self.assertEqual("unknown_supplier", flagged_findings[0].signal.value)
        self.assertIn("Explain unknown_supplier", flagged_findings[0].explanation or "")

    def test_daily_and_weekly_risk_report_stub_is_machine_readable(self) -> None:
        first = review_accounting_case(
            AccountingCase(
                case_id="case_report_1",
                client_id="client_alpha",
                supplier_known=False,
                source_document_id="doc_1",
                business_purpose="Office material",
            )
        )
        second = review_accounting_case(
            AccountingCase(
                case_id="case_report_2",
                client_id="client_alpha",
                source_document_id="doc_2",
                known_supplier_bank_account="123-4567",
                stated_supplier_bank_account="999-0000",
                business_purpose="IT support",
            )
        )

        daily = build_risk_report(
            {"case_report_1": first, "case_report_2": second},
            period="daily",
            report_date=date(2026, 5, 16),
        )
        weekly = build_risk_report(
            {"case_report_1": first, "case_report_2": second},
            period="weekly",
            report_date=date(2026, 5, 16),
        )

        self.assertEqual("daily", daily.period)
        self.assertEqual("weekly", weekly.period)
        self.assertEqual(2, daily.reviewed_cases)
        self.assertEqual(2, daily.cases_with_findings)
        self.assertEqual(1, daily.findings_by_signal["unknown_supplier"])
        self.assertEqual(1, daily.findings_by_signal["changed_bank_details"])
        self.assertEqual(1, daily.blocked_cases)
        self.assertEqual("2026-05-16", daily.to_dict()["report_date"])


if __name__ == "__main__":
    unittest.main()
