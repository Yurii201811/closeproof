from __future__ import annotations

import importlib.util
from datetime import date
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from accounting_agent.accounting.money import (
    CurrencyAmountError,
    ExchangeRateEvidence,
    Money,
)
from accounting_agent.accounting.proposals import (
    AccountingEntry,
    SupplierInvoiceProposal,
    supplier_invoice_proposal_from_dict,
)
from accounting_agent.ledger import (
    JournalDraft,
    JournalLine,
    JournalValidationError,
    JournalValidationPolicy,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.supplier_invoice.pipeline import (
    apply_journal_validation_to_policy,
    build_fortnox_accounting_rows,
    minor_amount,
)
from accounting_agent.supplier_invoice.rules import SUPPLIERS


ROOT = Path(__file__).resolve().parents[1]


class MoneyAndJournalV1Tests(unittest.TestCase):
    def test_v1_money_module_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("accounting_agent.accounting.money"))

    def test_money_uses_registered_currency_precision_and_half_up_rounding(self) -> None:
        self.assertEqual(123_456, Money.from_major("1234.56", "sek").minor)
        self.assertEqual(1_234, Money.from_major("1234", "JPY").minor)
        self.assertEqual(12_345, Money.from_major("12.345", "KWD").minor)
        self.assertEqual(101, Money.from_major("1.005", "SEK").minor)
        self.assertEqual(1_001, Money.from_major("1.0005", "BHD").minor)

    def test_supplier_pipeline_minor_amount_uses_the_invoice_currency(self) -> None:
        self.assertEqual(1_234, minor_amount("1234", "JPY"))
        self.assertEqual(12_345, minor_amount("12.345", "KWD"))
        self.assertEqual(-12_345, minor_amount("-12.345", "BHD"))

    def test_fortnox_dry_run_rows_use_the_document_currency(self) -> None:
        rows = build_fortnox_accounting_rows(
            [
                {"account": "4010", "debit": "1234", "credit": "0"},
                {"account": "2440", "debit": "0", "credit": "1234"},
            ],
            "JPY",
        )

        self.assertEqual(1_234, rows[0]["debit_minor"])
        self.assertEqual(1_234, rows[1]["credit_minor"])

    def test_money_rejects_float_and_currency_mismatch(self) -> None:
        with self.assertRaises(CurrencyAmountError):
            Money.from_major(1.25, "SEK")
        with self.assertRaises(CurrencyAmountError):
            Money.from_major("12.00", "ZZZ")
        with self.assertRaises(CurrencyAmountError):
            Money(100, "SEK") + Money(100, "EUR")

    def test_exchange_conversion_requires_typed_evidence(self) -> None:
        evidence = ExchangeRateEvidence(
            base_currency="EUR",
            quote_currency="SEK",
            rate=Decimal("11.2500"),
            rate_date="2026-07-10",
            source_uri="https://example.invalid/rates/2026-07-10",
            source_sha256="a" * 64,
        )

        converted = Money.from_major("100.00", "EUR").convert(
            evidence,
            transaction_date="2026-07-10",
        )

        self.assertEqual(Money.from_major("1125.00", "SEK"), converted)
        with self.assertRaises(CurrencyAmountError):
            Money.from_major("100.00", "USD").convert(
                evidence,
                transaction_date="2026-07-10",
            )
        for transaction_date, max_rate_age_days in (
            ("2026-07-09", 3),
            ("2026-07-20", 3),
            ("not-a-date", 3),
            ("2026-07-10", -1),
        ):
            with self.subTest(
                transaction_date=transaction_date,
                max_rate_age_days=max_rate_age_days,
            ):
                with self.assertRaises(CurrencyAmountError):
                    Money.from_major("100.00", "EUR").convert(
                        evidence,
                        transaction_date=transaction_date,
                        max_rate_age_days=max_rate_age_days,
                    )
        with self.assertRaises(CurrencyAmountError):
            ExchangeRateEvidence(
                base_currency="EUR",
                quote_currency="SEK",
                rate=Decimal("0"),
                rate_date="2026-07-10",
                source_uri="https://example.invalid/rates/2026-07-10",
                source_sha256="a" * 64,
            )

    def test_v1_ledger_package_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("accounting_agent.ledger"))

    def test_supplier_proposal_requires_an_explicit_entity_id(self) -> None:
        proposal_fields = {
            "proposal_id": "proposal-identity",
            "case_id": "case-identity",
            "client_id": "accounting-firm",
            "supplier_id": "supplier-1",
            "supplier_name": "Synthetic Supplier AB",
            "invoice_number": "INV-IDENTITY",
            "invoice_date": "2026-07-01",
            "due_date": "2026-07-31",
            "currency": "SEK",
            "net_amount_minor": 10_000,
            "vat_amount_minor": 2_500,
            "gross_amount_minor": 12_500,
            "vat_rate_percent": 25,
            "expense_account": "4010",
        }

        with self.assertRaises(TypeError):
            SupplierInvoiceProposal(**proposal_fields)

    def test_supplier_proposal_rejects_blank_or_ambiguous_entity_id(self) -> None:
        proposal_fields = {
            "proposal_id": "proposal-identity",
            "case_id": "case-identity",
            "client_id": "accounting-firm",
            "supplier_id": "supplier-1",
            "supplier_name": "Synthetic Supplier AB",
            "invoice_number": "INV-IDENTITY",
            "invoice_date": "2026-07-01",
            "due_date": "2026-07-31",
            "currency": "SEK",
            "net_amount_minor": 10_000,
            "vat_amount_minor": 2_500,
            "gross_amount_minor": 12_500,
            "vat_rate_percent": 25,
            "expense_account": "4010",
        }

        for entity_id in ("", " ", "entity-a "):
            with self.subTest(entity_id=entity_id):
                with self.assertRaises(ValueError):
                    SupplierInvoiceProposal(entity_id=entity_id, **proposal_fields)

    def test_supplier_proposal_parser_requires_entity_id_field(self) -> None:
        proposal = SupplierInvoiceProposal(
            proposal_id="proposal-identity",
            case_id="case-identity",
            client_id="accounting-firm",
            entity_id="legal-entity-se-1",
            supplier_id="supplier-1",
            supplier_name="Synthetic Supplier AB",
            invoice_number="INV-IDENTITY",
            invoice_date="2026-07-01",
            due_date="2026-07-31",
            currency="SEK",
            net_amount_minor=10_000,
            vat_amount_minor=2_500,
            gross_amount_minor=12_500,
            vat_rate_percent=25,
            expense_account="4010",
        )
        serialized = proposal.to_dict()
        serialized.pop("entity_id")

        with self.assertRaises(Exception) as captured:
            supplier_invoice_proposal_from_dict(serialized)
        self.assertIsInstance(captured.exception, KeyError)

    def test_balanced_journal_produces_t_accounts_and_control_totals(self) -> None:
        draft = self._valid_journal()

        result = draft.validate(self._journal_policy())

        self.assertTrue(result.is_valid)
        self.assertEqual(12_500, result.debit_total.minor)
        self.assertEqual(12_500, result.credit_total.minor)
        self.assertEqual(
            {"debit_minor": 10_000, "credit_minor": 0},
            draft.t_accounts()["4010"],
        )
        draft.require_valid(self._journal_policy())

    def test_unbalanced_or_two_sided_journal_is_blocked(self) -> None:
        unbalanced = self._valid_journal(
            lines=(
                self._line("4010", debit=10_000),
                self._line("2440", credit=9_999),
            )
        )
        two_sided = self._valid_journal(
            lines=(
                self._line("4010", debit=10_000, credit=1),
                self._line("2440", credit=10_000),
            )
        )

        self.assertIn("journal_unbalanced", unbalanced.validate().error_codes)
        self.assertIn("line_must_have_exactly_one_side", two_sided.validate().error_codes)
        with self.assertRaises(JournalValidationError):
            unbalanced.require_valid()

    def test_blank_account_and_unrelated_line_evidence_are_blocked(self) -> None:
        draft = self._valid_journal(
            lines=(
                JournalLine(
                    account="   ",
                    description="Synthetic debit",
                    debit=Money(12_500, "SEK"),
                    evidence_hashes=("a" * 64,),
                ),
                JournalLine(
                    account="2440",
                    description="Synthetic credit",
                    credit=Money(12_500, "SEK"),
                    evidence_hashes=("a" * 64,),
                ),
            )
        )

        result = draft.validate()

        self.assertFalse(result.is_valid)
        self.assertIn("account_missing", result.error_codes)
        self.assertIn("line_evidence_not_bound_to_source", result.error_codes)

    def test_invalid_amount_currency_account_evidence_and_period_fail_closed(self) -> None:
        draft = JournalDraft(
            journal_id="journal-invalid",
            client_id="client-a",
            entity_id="client-a",
            posting_date="not-a-date",
            description="Invalid journal",
            source_document_hash="not-a-hash",
            period_locked=True,
            lines=(
                JournalLine(
                    account="9999",
                    description="Bad debit",
                    debit=Money(-10_000, "SEK"),
                    evidence_hashes=(),
                ),
                JournalLine(
                    account="2440",
                    description="Mixed currency",
                    credit=Money(10_000, "EUR"),
                    evidence_hashes=("a" * 64,),
                ),
            ),
        )

        result = draft.validate(self._journal_policy())

        self.assertFalse(result.is_valid)
        self.assertTrue(
            {
                "posting_date_invalid",
                "period_locked",
                "source_document_hash_invalid",
                "line_amount_must_be_positive",
                "line_evidence_missing",
                "account_not_allowed",
                "mixed_currencies",
            }.issubset(set(result.error_codes))
        )

    def test_supplier_proposal_cannot_hide_unbalanced_custom_entries(self) -> None:
        proposal = SupplierInvoiceProposal(
            proposal_id="proposal-1",
            case_id="case-1",
            client_id="client-a",
            supplier_id="supplier-1",
            supplier_name="Synthetic Supplier AB",
            invoice_number="INV-1",
            invoice_date="2026-07-01",
            due_date="2026-07-31",
            currency="SEK",
            net_amount_minor=10_000,
            vat_amount_minor=2_500,
            gross_amount_minor=12_500,
            vat_rate_percent=25,
            expense_account="4010",
            entity_id="entity-a",
            source_document_hash="c" * 64,
            entries=(
                AccountingEntry(account="4010", debit_minor=10_000),
                AccountingEntry(account="2440", credit_minor=12_500),
            ),
        )

        journal = proposal.to_journal_draft()
        validation = journal.validate()

        self.assertFalse(validation.is_valid)
        self.assertIn("journal_unbalanced", validation.error_codes)
        self.assertEqual("client-a", journal.client_id)
        self.assertEqual("entity-a", journal.entity_id)

    def test_pipeline_emits_authoritative_journal_validation(self) -> None:
        packet = SupplierInvoicePipeline(
            db_path=None,
            output_dir=None,
            entity_id="fixture-entity",
            evaluation_date=date(2026, 5, 16),
        ).process_fixture(ROOT / "fixtures/supplier_invoices/01_normal_25_vat.json")

        self.assertTrue(packet["journal_validation"]["is_valid"])
        self.assertEqual(
            packet["journal_validation"]["debit_total_minor"],
            packet["journal_validation"]["credit_total_minor"],
        )

    def test_pipeline_blocks_account_outside_bound_sweden_preview_chart(self) -> None:
        supplier = SUPPLIERS["5566778899"]
        with patch.dict(
            supplier,
            {
                "default_bas_account": "NOT-A-BAS-ACCOUNT",
                "default_bas_name": "Synthetic invalid account",
            },
        ):
            packet = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                entity_id="fixture-entity",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(ROOT / "fixtures/supplier_invoices/01_normal_25_vat.json")

        self.assertFalse(packet["journal_validation"]["is_valid"])
        self.assertIn(
            "account_not_allowed",
            packet["journal_validation"]["error_codes"],
        )
        self.assertEqual("forbidden", packet["policy_decision"]["mode"])

    def test_invalid_journal_forces_a_forbidden_policy_result(self) -> None:
        validation = self._valid_journal(
            lines=(
                self._line("4010", debit=10_000),
                self._line("2440", credit=9_999),
            )
        ).validate()

        decision = apply_journal_validation_to_policy(
            {
                "mode": "draft_only",
                "required_reviews": (),
                "exact_proposed_external_action": {
                    "action": "prepare_fortnox_supplier_invoice_draft",
                    "live_api_call": False,
                },
            },
            validation,
        )

        self.assertEqual("forbidden", decision["mode"])
        self.assertEqual("none_until_journal_corrected", decision["exact_proposed_external_action"]["action"])
        self.assertIn("journal_unbalanced", decision["journal_error_codes"])

    @staticmethod
    def _journal_policy() -> JournalValidationPolicy:
        return JournalValidationPolicy(
            chart_id="se-bas-test-v1",
            allowed_accounts=frozenset({"2440", "2641", "4010"}),
            require_line_evidence=True,
        )

    @staticmethod
    def _line(
        account: str,
        *,
        debit: int | None = None,
        credit: int | None = None,
    ) -> JournalLine:
        return JournalLine(
            account=account,
            description=f"Line {account}",
            debit=Money(debit, "SEK") if debit is not None else None,
            credit=Money(credit, "SEK") if credit is not None else None,
            evidence_hashes=("b" * 64,),
        )

    def _valid_journal(self, *, lines: tuple[JournalLine, ...] | None = None) -> JournalDraft:
        return JournalDraft(
            journal_id="journal-1",
            client_id="client-a",
            entity_id="client-a",
            posting_date="2026-07-10",
            description="Supplier invoice proposal",
            source_document_hash="b" * 64,
            lines=lines
            or (
                self._line("4010", debit=10_000),
                self._line("2641", debit=2_500),
                self._line("2440", credit=12_500),
            ),
        )


if __name__ == "__main__":
    unittest.main()
