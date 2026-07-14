from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from accounting_agent.bank_reconciliation.matching import (
    build_candidates,
    duplicate_transaction_risks,
    normalize_reference,
)
from accounting_agent.bank_reconciliation.pipeline import BankReconciliationPipeline
from accounting_agent.bank_reconciliation.models import (
    BankTransaction,
    MatchTarget,
    MatchTargetType,
)
from accounting_agent.documents.invoice_metadata import extract_invoice_metadata


class LocaleAndReconciliationSafetyTests(unittest.TestCase):
    def test_bank_pipeline_uses_canonical_client_identity(self) -> None:
        self.assertEqual(
            "Client-A",
            BankReconciliationPipeline(output_dir=None, client_id="Client-A").client_id,
        )
        with self.assertRaises(ValueError):
            BankReconciliationPipeline(output_dir=None, client_id=" Client-A")

    def test_swedish_and_international_amount_separators(self) -> None:
        cases = {
            "1.234,56 EUR": (123456, "EUR"),
            "1,234.56 USD": (123456, "USD"),
            "1 234,50 SEK": (123450, "SEK"),
            "1,234 JPY": (1234, "JPY"),
            "12,345.678 KWD": (12345678, "KWD"),
            "12.345,678 BHD": (12345678, "BHD"),
        }
        with tempfile.TemporaryDirectory() as temp:
            for index, (amount, expected) in enumerate(cases.items()):
                path = Path(temp) / f"invoice-{index}.txt"
                path.write_text(f"Amount: {amount}\n", encoding="utf-8")
                metadata = extract_invoice_metadata(path)
                self.assertEqual(expected, (metadata.amount_minor, metadata.currency))

    def test_three_decimal_currency_with_lone_three_digit_separator_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for index, ambiguous in enumerate(("1,234 KWD", "1.234 KWD", "1,234 BHD", "1.234 BHD")):
                with self.subTest(ambiguous=ambiguous):
                    path = Path(temp) / f"ambiguous-{index}.txt"
                    path.write_text(f"Total: {ambiguous}\n", encoding="utf-8")
                    metadata = extract_invoice_metadata(path)

                    self.assertIsNone(metadata.amount_minor)
                    self.assertEqual(ambiguous[-3:], metadata.currency)

    def test_unknown_or_missing_currency_precision_fails_closed(self) -> None:
        cases = {
            "123.45 ZZZ": (None, "ZZZ"),
            "123.45": (None, None),
        }
        with tempfile.TemporaryDirectory() as temp:
            for index, (amount, expected) in enumerate(cases.items()):
                path = Path(temp) / f"unknown-currency-{index}.txt"
                path.write_text(f"Amount: {amount}\n", encoding="utf-8")
                metadata = extract_invoice_metadata(path)
                self.assertEqual(expected, (metadata.amount_minor, metadata.currency))

    def test_unicode_reference_is_not_erased(self) -> None:
        self.assertEqual("åäö東京", normalize_reference("Å Ä Ö / 東京"))

    def test_closed_and_zero_residual_targets_are_excluded(self) -> None:
        transaction = BankTransaction(
            transaction_id="TX-1",
            date=date(2026, 7, 10),
            amount_minor=10_000,
            currency="SEK",
            counterparty="Example AB",
            reference="INV-1",
            bank_account="1930",
            source="fixture",
        )

        def target(target_id: str, *, status: str, remaining: int) -> MatchTarget:
            return MatchTarget(
                target_id=target_id,
                target_type=MatchTargetType.CUSTOMER_INVOICE,
                date=date(2026, 7, 10),
                amount_minor=10_000,
                remaining_amount_minor=remaining,
                currency="SEK",
                counterparty="Example AB",
                reference="INV-1",
                source="fixture",
                status=status,
            )

        candidates = build_candidates(
            transaction,
            [
                target("closed", status="closed", remaining=10_000),
                target("allocated", status="open", remaining=0),
                target("open", status="open", remaining=10_000),
            ],
        )
        self.assertEqual(["open"], [candidate.target_id for candidate in candidates])

    def test_duplicate_risk_is_scoped_by_bank_account_and_date_window(self) -> None:
        def transaction(transaction_id: str, *, day: int, account: str) -> BankTransaction:
            return BankTransaction(
                transaction_id=transaction_id,
                date=date(2026, 7, day),
                amount_minor=10_000,
                currency="SEK",
                counterparty="Example AB",
                reference="INV-1",
                bank_account=account,
                source="fixture",
            )

        adjacent = transaction("adjacent", day=10, account="1930")
        duplicate = transaction("duplicate", day=11, account="1930")
        other_account = transaction("other-account", day=11, account="1940")
        later = transaction("later", day=20, account="1930")
        risks = duplicate_transaction_risks([adjacent, duplicate, other_account, later])

        self.assertEqual(0.85, risks["adjacent"])
        self.assertEqual(0.85, risks["duplicate"])
        self.assertEqual(0.0, risks["other-account"])
        self.assertEqual(0.0, risks["later"])

    def test_multiple_transactions_cannot_silently_consume_one_target(self) -> None:
        transactions = [
            BankTransaction(
                transaction_id=f"TX-{index}",
                date=date(2026, 7, day),
                amount_minor=10_000,
                currency="SEK",
                counterparty="Example AB",
                reference="INV-1",
                bank_account="1930",
                source="fixture",
            )
            for index, day in enumerate((10, 20), start=1)
        ]
        open_item = MatchTarget(
            target_id="CI-1",
            target_type=MatchTargetType.CUSTOMER_INVOICE,
            date=date(2026, 7, 10),
            amount_minor=10_000,
            remaining_amount_minor=10_000,
            currency="SEK",
            counterparty="Example AB",
            reference="INV-1",
            source="fixture",
        )

        proposals = BankReconciliationPipeline(output_dir=None).process(
            transactions,
            [open_item],
        )

        for proposal in proposals:
            self.assertTrue(proposal["risk"]["allocation_conflict"])
            self.assertEqual(2, proposal["risk"]["target_reuse_count"])
            self.assertIn(
                "target_already_proposed",
                {flag["code"] for flag in proposal["risk"]["flags"]},
            )
            self.assertEqual("approval_required", proposal["policy_decision"]["mode"])


if __name__ == "__main__":
    unittest.main()
