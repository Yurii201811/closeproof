from __future__ import annotations

import unittest

from accounting_agent import (
    AccountingEntry,
    LocalGnubokShadowLedgerAdapter,
    SupplierInvoiceProposal,
    mirror_supplier_invoice_proposal_to_shadow,
)


def sample_supplier_invoice_proposal() -> SupplierInvoiceProposal:
    return SupplierInvoiceProposal(
        proposal_id="proposal_fixture_1",
        case_id="case_fixture_1",
        client_id="client_fixture",
        entity_id="entity_fixture",
        supplier_id="supplier_42",
        supplier_name="Kontorsvaror AB",
        invoice_number="INV-2026-001",
        invoice_date="2026-05-10",
        due_date="2026-06-09",
        currency="SEK",
        net_amount_minor=100000,
        vat_amount_minor=25000,
        gross_amount_minor=125000,
        vat_rate_percent=25,
        expense_account="6110",
        vat_account="2641",
        payable_account="2440",
        description="Office supplies",
        confidence=0.97,
    )


class GnuBokShadowLedgerAdapterTests(unittest.TestCase):
    def test_adapter_creates_company_context_and_account_lookup(self) -> None:
        adapter = LocalGnubokShadowLedgerAdapter()

        company = adapter.get_or_create_company_context(
            company_id="client_fixture",
            fiscal_year="2026",
        )
        account = adapter.lookup_account(company, "6110")

        self.assertEqual("client_fixture", company.company_id)
        self.assertIsNotNone(account)
        self.assertEqual("expense", account.account_type)

    def test_supplier_invoice_proposal_mirrors_to_balanced_shadow_draft(self) -> None:
        comparison = mirror_supplier_invoice_proposal_to_shadow(
            sample_supplier_invoice_proposal(),
            adapter=LocalGnubokShadowLedgerAdapter(),
        )

        self.assertEqual("mirrored", comparison.status)
        self.assertEqual((), comparison.differences)
        self.assertTrue(all(validation.passed for validation in comparison.validations))
        self.assertIsNotNone(comparison.shadow_proposal)

    def test_validation_warnings_include_vat_and_balance_problems(self) -> None:
        proposal = sample_supplier_invoice_proposal()
        proposal = SupplierInvoiceProposal(
            **{
                **proposal.to_dict(),
                "entries": (
                    AccountingEntry(account="6110", debit_minor=100000),
                    AccountingEntry(account="2440", credit_minor=90000),
                ),
                "vat_account": "2650",
            }
        )

        comparison = mirror_supplier_invoice_proposal_to_shadow(
            proposal,
            adapter=LocalGnubokShadowLedgerAdapter(),
        )

        self.assertEqual("mirrored_with_warnings", comparison.status)
        self.assertIn("debit_credit_imbalance:100000:90000", comparison.warnings)
        self.assertIn(
            "vat_account_mismatch:expected_2641:actual_2650",
            comparison.warnings,
        )


if __name__ == "__main__":
    unittest.main()
