from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime

from accounting_agent import (
    ActionType,
    ApprovalPacket,
    JsonlAuditLog,
    MissingInfoReason,
    PolicyContext,
    ProposedAccountingEntry,
    ReviewDecision,
    draft_missing_info_email,
    evaluate_policy,
    record_approval_decision,
    render_approval_packet,
    render_email_draft,
    write_approval_packet,
)


FIXED_NOW = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


def sample_supplier_invoice_packet() -> ApprovalPacket:
    decision = evaluate_policy(
        PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_alpha",
            currency_code="SEK",
            amount_minor=12_500_00,
            supplier_known=False,
            duplicate_risk=0.12,
            vat_confidence=0.72,
            ocr_confidence=0.93,
        )
    )
    return ApprovalPacket(
        case_id="case_sup_001",
        client_id="client_alpha",
        source_document="inbox/supplier-invoice-2026-05.pdf",
        extracted_fields={
            "supplier_name": "Nordic Office AB",
            "invoice_date": "2026-05-13",
            "due_date": "2026-06-12",
            "total_amount": "12,500.00 SEK",
            "vat_amount": "2,500.00 SEK",
        },
        proposed_entries=(
            ProposedAccountingEntry(
                account="5410",
                description="Consumables",
                debit_minor=10_000_00,
                vat_code="SE25",
                evidence="invoice line 1",
            ),
            ProposedAccountingEntry(
                account="2641",
                description="Input VAT",
                debit_minor=2_500_00,
                vat_code="SE25",
                evidence="invoice VAT total",
            ),
            ProposedAccountingEntry(
                account="2440",
                description="Supplier debt",
                credit_minor=12_500_00,
                evidence="invoice total",
            ),
        ),
        confidence_scores={
            "ocr": 0.93,
            "supplier_match": 0.41,
            "vat": 0.72,
            "duplicate_check": 0.88,
        },
        risk_flags=("supplier_not_previously_known", "vat_confidence_below_threshold"),
        policy_decision=decision,
        proposed_fortnox_action=(
            "Create a Fortnox draft supplier invoice for Nordic Office AB, attach the source document, "
            "and leave it unapproved for accountant review."
        ),
        fortnox_payload_summary={
            "resource": "supplier_invoice",
            "mode": "draft",
            "supplier": "Nordic Office AB",
            "amount_minor": 12_500_00,
            "currency": "SEK",
        },
    )


class HermesApprovalPacketTests(unittest.TestCase):
    def test_supplier_invoice_packet_renders_reviewer_context(self) -> None:
        markdown = render_approval_packet(sample_supplier_invoice_packet())

        self.assertIn("# Approval packet: case_sup_001", markdown)
        self.assertIn("`client_alpha`", markdown)
        self.assertIn("inbox/supplier-invoice-2026-05.pdf", markdown)
        self.assertIn("supplier_name", markdown)
        self.assertIn("Nordic Office AB", markdown)
        self.assertIn("`5410`", markdown)
        self.assertIn("`2440`", markdown)
        self.assertIn("72%", markdown)
        self.assertIn("`approval_required`", markdown)
        self.assertIn("supplier not previously known", markdown.lower())
        self.assertIn("vat confidence below threshold", markdown.lower())
        self.assertIn("Create a Fortnox draft supplier invoice", markdown)
        self.assertIn("`approve`", markdown)
        self.assertIn("`reject`", markdown)
        self.assertIn("`escalate`", markdown)
        self.assertIn("`missing_info`", markdown)

    def test_packet_can_be_written_to_markdown_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_approval_packet(sample_supplier_invoice_packet(), temp_dir)

            self.assertEqual("case_sup_001.md", path.name)
            self.assertIn("Approval packet", path.read_text(encoding="utf-8"))


class HermesEmailDraftTests(unittest.TestCase):
    def test_missing_info_email_drafts_cover_required_reasons_without_sending(self) -> None:
        reasons = (
            MissingInfoReason.MISSING_RECEIPT,
            MissingInfoReason.UNCLEAR_BUSINESS_PURPOSE,
            MissingInfoReason.UNKNOWN_SUPPLIER,
            MissingInfoReason.CHANGED_BANK_DETAILS_CONFIRMATION,
            MissingInfoReason.VAT_UNCERTAINTY,
        )

        for reason in reasons:
            with self.subTest(reason=reason.value):
                draft = draft_missing_info_email(
                    case_id="case_sup_001",
                    client_id="client_alpha",
                    reason=reason,
                    supplier_name="Nordic Office AB",
                    document_label="invoice 123",
                    recipient_name="Lena",
                    to_address="client@example.invalid",
                )

                self.assertEqual("draft_only_not_sent", draft.send_status)
                self.assertTrue(draft.subject)
                self.assertTrue(draft.body.startswith("Hi Lena,"))
                self.assertLessEqual(len(draft.body.split()), 45)
                self.assertIn("Email draft", render_email_draft(draft))

    def test_changed_bank_details_draft_is_explicitly_cautious(self) -> None:
        draft = draft_missing_info_email(
            case_id="case_sup_002",
            client_id="client_alpha",
            reason=MissingInfoReason.CHANGED_BANK_DETAILS_CONFIRMATION,
            supplier_name="Nordic Office AB",
        )

        self.assertIn("confirm bank details", draft.subject.lower())
        self.assertIn("will not update bank details", draft.body.lower())
        self.assertEqual("draft_only_not_sent", draft.send_status)


class HermesAuditDecisionTests(unittest.TestCase):
    def test_review_decisions_are_recorded_in_append_only_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audit_log = JsonlAuditLog(f"{temp_dir}/audit.jsonl", clock=lambda: FIXED_NOW)
            packet = sample_supplier_invoice_packet()

            for decision in ReviewDecision:
                record_approval_decision(
                    packet=packet,
                    decision=decision,
                    audit_log=audit_log,
                    actor="accountant:lena",
                    note=f"{decision.value} selected",
                )

            events = audit_log.read_events()
            self.assertEqual(4, len(events))
            self.assertEqual(
                [decision.value for decision in ReviewDecision],
                [event.action for event in events],
            )
            self.assertTrue(all(event.event_type == "approval_decision" for event in events))
            self.assertTrue(all(event.case_id == "case_sup_001" for event in events))

    def test_audit_log_redacts_sensitive_decision_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audit_log = JsonlAuditLog(f"{temp_dir}/audit.jsonl", clock=lambda: FIXED_NOW)
            audit_log.append_event(
                event_type="approval_decision",
                case_id="case_sup_003",
                client_id="client_alpha",
                actor="accountant:lena",
                action="missing_info",
                details={
                    "bank_details": "SE123",
                    "raw_text": "private invoice text",
                    "policy_mode": "approval_required",
                },
            )

            raw_event = json.loads((audit_log.path).read_text(encoding="utf-8").strip())
            self.assertEqual("[redacted]", raw_event["details"]["bank_details"])
            self.assertEqual("[redacted]", raw_event["details"]["raw_text"])
            self.assertEqual("approval_required", raw_event["details"]["policy_mode"])


if __name__ == "__main__":
    unittest.main()
