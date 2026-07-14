from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from accounting_agent.audit import JsonlAuditLog
from accounting_agent.bank_reconciliation import BankReconciliationPipeline
from accounting_agent.local_demo import LocalDemoError, run_supplier_invoice_autopilot_demo


DEFAULT_FAKE_CLIENT_OUTPUT = Path(".local/fake_client_dry_run")
DEFAULT_FAKE_CLIENT_REPORT = Path("docs/fake_client_dry_run_report.md")
FAKE_CLIENT_OUTPUT_MARKER = ".accounting_agent_fake_client_dry_run"

PERMISSION_MODES = (
    "auto_allowed",
    "draft_only",
    "approval_required",
    "escalation_required",
    "forbidden",
)
MODE_SEVERITY = {mode: index for index, mode in enumerate(PERMISSION_MODES)}


class FakeClientDryRunError(RuntimeError):
    """Raised when the fake-client dry run cannot be completed safely."""


def run_fake_client_dry_run(
    *,
    output_dir: str | Path = DEFAULT_FAKE_CLIENT_OUTPUT,
    report_path: str | Path = DEFAULT_FAKE_CLIENT_REPORT,
) -> dict[str, Any]:
    """Run a deterministic synthetic Swedish month through the local MVP."""

    output = Path(output_dir)
    report = Path(report_path)
    paths = _prepare_output_tree(output)
    sample = build_fake_client_month()
    sample_paths = _write_sample_data(paths["sample_data"], sample)

    supplier_manifest = run_supplier_invoice_autopilot_demo(
        supplier_fixture_dir=sample_paths["supplier_invoices"],
        output_dir=paths["supplier_output"],
        client_id=sample["profile"]["client_id"],
        entity_id=sample["profile"]["entity_id"],
    )

    bank_pipeline = BankReconciliationPipeline(
        output_dir=paths["bank_packets"],
        client_id=sample["profile"]["client_id"],
    )
    bank_proposals = bank_pipeline.process_fixture_dir(sample_paths["bank_reconciliation"])
    _write_json(paths["bank_proposals"], bank_proposals)

    metrics = _measure_run(
        sample=sample,
        supplier_manifest=supplier_manifest,
        bank_proposals=bank_proposals,
        output_dir=output,
    )
    audit_log = JsonlAuditLog(paths["audit_log"])
    _write_audit_events(
        audit_log=audit_log,
        client_id=sample["profile"]["client_id"],
        supplier_manifest=supplier_manifest,
        bank_proposals=bank_proposals,
        metrics=metrics,
    )
    metrics["audit_events"] = len(audit_log.read_events())

    manifest = {
        "run": {
            "name": "fake_client_month_dry_run",
            "status": "complete",
            "generated_at": _utc_now(),
            "output_dir": str(output),
            "report_path": str(report),
            "documented_command": "python3 -m accounting_agent.cli fake-client-dry-run",
        },
        "sample_data": {
            "profile": _relative_to_output(sample_paths["profile"], output),
            "supplier_invoices": _relative_to_output(
                sample_paths["supplier_invoices"],
                output,
            ),
            "customer_invoices": _relative_to_output(
                sample_paths["customer_invoices"],
                output,
            ),
            "bank_reconciliation": _relative_to_output(
                sample_paths["bank_reconciliation"],
                output,
            ),
        },
        "supplier_invoice_autopilot": supplier_manifest,
        "bank_reconciliation": {
            "proposal_count": len(bank_proposals),
            "proposal_path": _relative_to_output(paths["bank_proposals"], output),
            "approval_packet_dir": _relative_to_output(paths["bank_packets"], output),
        },
        "metrics": metrics,
        "safety": {
            "fake_data_only": True,
            "fake_data_notice": sample["profile"]["fake_data_notice"],
            "live_fortnox_calls": 0,
            "live_microsoft365_calls": 0,
            "emails_sent": 0,
            "payments_or_filings": 0,
            "final_voucher_postings": 0,
            "real_client_data_used": False,
        },
    }
    _write_json(paths["summary"], _summary_from_manifest(manifest))
    _write_json(paths["manifest"], manifest)
    _write_report(report, manifest)
    return manifest


def build_fake_client_month() -> dict[str, Any]:
    profile = {
        "client_id": "fake-se-service-001",
        "entity_id": "fake-se-legal-entity-001",
        "display_name": "Fiktiv Konsultstudio AB",
        "fake_data_notice": (
            "Synthetic fake-client dry-run data only. No real client, supplier, "
            "customer, bank, Fortnox, Microsoft 365, email, payment, or tax data."
        ),
        "country": "SE",
        "currency": "SEK",
        "vat_registration": "Swedish VAT, standard 25% output VAT unless noted",
        "accounting_period": "2026-05",
        "business_type": "Small Swedish consulting and service business",
        "bank_account_label": "FAKE-SEB-1930",
        "known_suppliers": [
            {"supplier_id": "SUP-FIK-001", "name": "Fiktiv Kontorspartner AB"},
            {"supplier_id": "SUP-FIK-002", "name": "Fiktiv IT Support AB"},
            {"supplier_id": "SUP-FIK-003", "name": "Fiktiv Lokalhyra AB"},
            {"supplier_id": "SUP-FIK-004", "name": "Fiktiv Studioverktyg AB"},
            {"supplier_id": "SUP-FIK-005", "name": "Fiktiv Mobiloperator AB"},
            {"supplier_id": "SUP-FIK-006", "name": "Fiktiv Stadservice AB"},
            {"supplier_id": "SUP-FIK-007", "name": "Fiktiv Forsakring AB"},
            {"supplier_id": "SUP-FIK-008", "name": "Fiktiv Bokforing Online AB"},
        ],
        "known_customers": [
            {"customer_id": "CUST-FIK-001", "name": "Fiktiv Kund Ett AB"},
            {"customer_id": "CUST-FIK-002", "name": "Fiktiv Kund Tva AB"},
            {"customer_id": "CUST-FIK-003", "name": "Fiktiv Kund Tre AB"},
            {"customer_id": "CUST-FIK-004", "name": "Fiktiv Kund Fyra AB"},
            {"customer_id": "CUST-FIK-005", "name": "Fiktiv Kund Fem AB"},
        ],
        "normal_monthly_expenses": [
            "office supplies",
            "IT support and software",
            "office rent",
            "mobile subscription",
            "cleaning",
            "insurance",
            "bank fees",
        ],
    }
    supplier_invoices = _supplier_fixtures()
    customer_invoices = _customer_invoices()
    bank_transactions = _bank_transactions()
    open_items = _open_items(customer_invoices, supplier_invoices)
    return {
        "profile": profile,
        "supplier_invoices": supplier_invoices,
        "customer_invoices": customer_invoices,
        "bank_reconciliation": {
            "bank_transactions": bank_transactions,
            "open_items": open_items,
        },
        "coverage": {
            "supplier_invoice_or_receipt_count": len(supplier_invoices),
            "customer_invoice_count": len(customer_invoices),
            "bank_transaction_count": len(bank_transactions),
            "ambiguous_edge_cases": _count_tagged(
                supplier_invoices,
                bank_transactions,
                "ambiguous_edge",
            ),
            "duplicate_risk_cases": _count_tagged(
                supplier_invoices,
                bank_transactions,
                "duplicate_risk",
            ),
            "changed_bank_details_cases": _count_tagged(
                supplier_invoices,
                bank_transactions,
                "changed_bank_details",
            ),
            "uncertain_vat_cases": _count_tagged(
                supplier_invoices,
                bank_transactions,
                "uncertain_vat",
            ),
            "old_locked_period_cases": _count_tagged(
                supplier_invoices,
                bank_transactions,
                "old_locked_period",
            ),
        },
    }


def _supplier_fixtures() -> list[dict[str, Any]]:
    return [
        _supplier_fixture(
            scenario="fc_01_office_supplies",
            source_filename="FAKE_2026-05_Fiktiv_Kontorspartner_FKP-2026-0501.txt",
            supplier_name="Fiktiv Kontorspartner AB",
            supplier_org_number="559001-1101",
            invoice_number="FKP-2026-0501",
            invoice_date="2026-05-03",
            due_date="2026-05-20",
            net="1000.00",
            vat_rate="25",
            description="Office supplies for consulting studio",
            bankgiro="111-1101",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_02_it_support",
            source_filename="FAKE_2026-05_Fiktiv_IT_Support_FIT-2026-0501.txt",
            supplier_name="Fiktiv IT Support AB",
            supplier_org_number="559001-1102",
            invoice_number="FIT-2026-0501",
            invoice_date="2026-05-04",
            due_date="2026-05-21",
            net="3000.00",
            vat_rate="25",
            description="Monthly IT support",
            bankgiro="111-1102",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_03_monthly_office_rent",
            source_filename="FAKE_2026-05_Fiktiv_Lokalhyra_FLH-2026-0501.txt",
            supplier_name="Fiktiv Lokalhyra AB",
            supplier_org_number="559001-1103",
            invoice_number="FLH-2026-0501",
            invoice_date="2026-05-01",
            due_date="2026-05-25",
            net="12000.00",
            vat_rate="25",
            description="May office rent",
            bankgiro="111-1103",
            expected_policy_mode="approval_required",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_04_studio_monitor",
            source_filename="FAKE_2026-05_Fiktiv_Studioverktyg_FSV-2026-0501.txt",
            supplier_name="Fiktiv Studioverktyg AB",
            supplier_org_number="559001-1104",
            invoice_number="FSV-2026-0501",
            invoice_date="2026-05-07",
            due_date="2026-05-24",
            net="792.00",
            vat_rate="25",
            description="Small display adapter for client workshop",
            bankgiro="111-1104",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_05_meeting_room",
            source_filename="FAKE_2026-05_Fiktiv_Lokalhyra_FLH-2026-0502.txt",
            supplier_name="Fiktiv Lokalhyra AB",
            supplier_org_number="559001-1103",
            invoice_number="FLH-2026-0502",
            invoice_date="2026-05-08",
            due_date="2026-05-24",
            net="2000.00",
            vat_rate="25",
            description="Client workshop meeting room",
            bankgiro="111-1103",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_06_mobile_subscription",
            source_filename="FAKE_2026-05_Fiktiv_Mobiloperator_FMO-2026-0501.txt",
            supplier_name="Fiktiv Mobiloperator AB",
            supplier_org_number="559001-1105",
            invoice_number="FMO-2026-0501",
            invoice_date="2026-05-09",
            due_date="2026-05-26",
            net="559.20",
            vat_rate="25",
            description="Business mobile subscription",
            bankgiro="111-1105",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_07_cleaning",
            source_filename="FAKE_2026-05_Fiktiv_Stadservice_FSS-2026-0501.txt",
            supplier_name="Fiktiv Stadservice AB",
            supplier_org_number="559001-1106",
            invoice_number="FSS-2026-0501",
            invoice_date="2026-05-10",
            due_date="2026-05-27",
            net="1500.00",
            vat_rate="25",
            description="Office cleaning",
            bankgiro="111-1106",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_08_bookkeeping_saas",
            source_filename="FAKE_2026-05_Fiktiv_Bokforing_Online_FBO-2026-0501.txt",
            supplier_name="Fiktiv Bokforing Online AB",
            supplier_org_number="559001-1108",
            invoice_number="FBO-2026-0501",
            invoice_date="2026-05-11",
            due_date="2026-05-28",
            net="399.20",
            vat_rate="25",
            description="Bookkeeping software subscription",
            bankgiro="111-1108",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_09_business_insurance",
            source_filename="FAKE_2026-05_Fiktiv_Forsakring_FFO-2026-0501.txt",
            supplier_name="Fiktiv Forsakring AB",
            supplier_org_number="559001-1107",
            invoice_number="FFO-2026-0501",
            invoice_date="2026-05-12",
            due_date="2026-05-29",
            net="1200.00",
            vat_rate="0",
            description="Monthly business insurance",
            bankgiro="111-1107",
            expected_policy_mode="draft_only",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_10_duplicate_office_supplies",
            source_filename="FAKE_DUPLICATE_2026-05_Fiktiv_Kontorspartner_FKP-2026-0501.txt",
            supplier_name="Fiktiv Kontorspartner AB",
            supplier_org_number="559001-1101",
            invoice_number="FKP-2026-0501",
            invoice_date="2026-05-03",
            due_date="2026-05-20",
            net="1000.00",
            vat_rate="25",
            description="Duplicate copy of office supplies invoice",
            bankgiro="111-1101",
            expected_policy_mode="approval_required",
            risk_tags=("duplicate_risk",),
        ),
        _supplier_fixture(
            scenario="fc_11_duplicate_it_support",
            source_filename="FAKE_DUPLICATE_2026-05_Fiktiv_IT_Support_FIT-2026-0501.txt",
            supplier_name="Fiktiv IT Support AB",
            supplier_org_number="559001-1102",
            invoice_number="FIT-2026-0501",
            invoice_date="2026-05-04",
            due_date="2026-05-21",
            net="3000.00",
            vat_rate="25",
            description="Duplicate copy of IT support invoice",
            bankgiro="111-1102",
            expected_policy_mode="approval_required",
            risk_tags=("duplicate_risk",),
        ),
        _supplier_fixture(
            scenario="fc_12_changed_bank_details",
            source_filename="FAKE_REVIEW_2026-05_Fiktiv_IT_Support_changed_bankgiro.txt",
            supplier_name="Fiktiv IT Support AB",
            supplier_org_number="559001-1102",
            invoice_number="FIT-2026-0502",
            invoice_date="2026-05-13",
            due_date="2026-05-30",
            net="2400.00",
            vat_rate="25",
            description="Extra IT support with changed payment details",
            bankgiro="999-9999",
            expected_policy_mode="escalation_required",
            risk_tags=("changed_bank_details",),
        ),
        _supplier_fixture(
            scenario="fc_13_uncertain_vat",
            source_filename="FAKE_REVIEW_2026-05_Fiktiv_Kontorspartner_uncertain_vat.txt",
            supplier_name="Fiktiv Kontorspartner AB",
            supplier_org_number="559001-1101",
            invoice_number="FKP-2026-0502",
            invoice_date="2026-05-14",
            due_date="2026-05-31",
            net="1800.00",
            vat_rate="14",
            description="Mixed workshop supplies with unclear VAT treatment",
            bankgiro="111-1101",
            expected_policy_mode="approval_required",
            risk_tags=("uncertain_vat",),
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_14_old_locked_period",
            source_filename="FAKE_LOCKED_2026-01_Fiktiv_Kontorspartner_FKP-2026-0104.txt",
            supplier_name="Fiktiv Kontorspartner AB",
            supplier_org_number="559001-1101",
            invoice_number="FKP-2026-0104",
            invoice_date="2026-01-31",
            due_date="2026-02-20",
            net="800.00",
            vat_rate="25",
            description="Late invoice from locked January period",
            bankgiro="111-1101",
            expected_policy_mode="forbidden",
            risk_tags=("old_locked_period",),
            period_locked=True,
            accounting_period="2026-01",
            bank_open_item=True,
        ),
        _supplier_fixture(
            scenario="fc_15_ambiguous_private_receipt",
            source_filename="FAKE_REVIEW_2026-05_ambiguous_private_receipt.txt",
            supplier_name="Fiktiv Privatkvitto Demo AB",
            supplier_org_number="559009-9999",
            invoice_number="PKD-2026-0501",
            invoice_date="2026-05-15",
            due_date="2026-05-31",
            net="640.00",
            vat_rate="25",
            description="Ambiguous private-looking phone accessory; business purpose unclear",
            bankgiro="222-2222",
            expected_policy_mode="approval_required",
            risk_tags=("ambiguous_edge",),
            extraction_confidence=0.72,
        ),
    ]


def _customer_invoices() -> list[dict[str, Any]]:
    return [
        _customer_invoice(
            target_id="CI-FC-001",
            customer_id="CUST-FIK-001",
            customer_name="Fiktiv Kund Ett AB",
            invoice_number="FC-CI-2026-0501",
            date="2026-05-02",
            due_date="2026-05-17",
            net="20000.00",
            description="May advisory retainer",
        ),
        _customer_invoice(
            target_id="CI-FC-002",
            customer_id="CUST-FIK-002",
            customer_name="Fiktiv Kund Tva AB",
            invoice_number="FC-CI-2026-0502",
            date="2026-05-05",
            due_date="2026-05-20",
            net="15000.00",
            description="Implementation workshop",
        ),
        _customer_invoice(
            target_id="CI-FC-003",
            customer_id="CUST-FIK-003",
            customer_name="Fiktiv Kund Tre AB",
            invoice_number="FC-CI-2026-0503",
            date="2026-05-07",
            due_date="2026-05-22",
            net="7000.00",
            description="Support package",
        ),
        _customer_invoice(
            target_id="CI-FC-004",
            customer_id="CUST-FIK-004",
            customer_name="Fiktiv Kund Fyra AB",
            invoice_number="FC-CI-2026-0504",
            date="2026-05-09",
            due_date="2026-05-24",
            net="10000.00",
            description="Partial-payment customer invoice",
        ),
        _customer_invoice(
            target_id="CI-FC-005",
            customer_id="CUST-FIK-005",
            customer_name="Fiktiv Kund Fem AB",
            invoice_number="FC-CI-2026-0505",
            date="2026-05-12",
            due_date="2026-05-27",
            net="25000.00",
            description="Project strategy sprint",
        ),
    ]


def _bank_transactions() -> list[dict[str, Any]]:
    return [
        _bank_transaction("FC-BANK-001", "2026-05-17", "25000.00", "Fiktiv Kund Ett AB", "FC-CI-2026-0501", "approval_required"),
        _bank_transaction("FC-BANK-002", "2026-05-20", "18750.00", "Fiktiv Kund Tva AB", "FC-CI-2026-0502", "approval_required"),
        _bank_transaction("FC-BANK-003", "2026-05-22", "8750.00", "Fiktiv Kund Tre AB", "FC-CI-2026-0503", "draft_only"),
        _bank_transaction("FC-BANK-004", "2026-05-24", "6250.00", "Fiktiv Kund Fyra AB", "FC-CI-2026-0504", "approval_required", risk_tags=("partial_payment",)),
        _bank_transaction("FC-BANK-005", "2026-05-27", "31250.00", "Fiktiv Kund Fem AB", "FC-CI-2026-0505", "approval_required"),
        _bank_transaction("FC-BANK-006", "2026-05-20", "-1250.00", "Fiktiv Kontorspartner AB", "FKP-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-007", "2026-05-21", "-3750.00", "Fiktiv IT Support AB", "FIT-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-008", "2026-05-25", "-15000.00", "Fiktiv Lokalhyra AB", "FLH-2026-0501", "approval_required"),
        _bank_transaction("FC-BANK-009", "2026-05-24", "-990.00", "Fiktiv Studioverktyg AB", "FSV-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-010", "2026-05-24", "-2500.00", "Fiktiv Lokalhyra AB", "FLH-2026-0502", "draft_only"),
        _bank_transaction("FC-BANK-011", "2026-05-26", "-699.00", "Fiktiv Mobiloperator AB", "FMO-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-012", "2026-05-27", "-1875.00", "Fiktiv Stadservice AB", "FSS-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-013", "2026-05-28", "-499.00", "Fiktiv Bokforing Online AB", "FBO-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-014", "2026-05-29", "-1200.00", "Fiktiv Forsakring AB", "FFO-2026-0501", "draft_only"),
        _bank_transaction("FC-BANK-015", "2026-05-31", "-2052.00", "Fiktiv Kontorspartner AB", "FKP-2026-0502", "draft_only"),
        _bank_transaction("FC-BANK-016", "2026-05-16", "-1000.00", "Fiktiv Kontorspartner AB", "FKP-2026-0104", "draft_only"),
        _bank_transaction("FC-BANK-017", "2026-05-31", "-35.00", "FAKE SEB", "BANKFEE-FAKE-2026-05", "draft_only"),
        _bank_transaction("FC-BANK-018", "2026-05-18", "-89.00", "Fiktiv Kvittohandel AB", "RCPT-FAKE-2026-010", "draft_only"),
        _bank_transaction("FC-BANK-019", "2026-05-19", "-450.00", "Kortkop utan kvitto", "CARD-FAKE-MISSING-RECEIPT", "approval_required", risk_tags=("ambiguous_edge",)),
        _bank_transaction("FC-BANK-020", "2026-05-30", "-150000.00", "Okand stor utbetalning", "WIRE-FAKE-REVIEW-001", "escalation_required", risk_tags=("ambiguous_edge",)),
    ]


def _open_items(
    customer_invoices: list[dict[str, Any]],
    supplier_invoices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    open_items = [
        {
            "target_id": invoice["target_id"],
            "target_type": "customer_invoice",
            "date": invoice["date"],
            "due_date": invoice["due_date"],
            "amount_minor": invoice["gross_amount_minor"],
            "remaining_amount_minor": invoice["gross_amount_minor"],
            "currency": "SEK",
            "counterparty": invoice["customer_name"],
            "reference": invoice["invoice_number"],
            "counterparty_id": invoice["customer_id"],
            "counterparty_known": True,
            "source": "fake_client:customer_invoice",
            "description": invoice["description"],
        }
        for invoice in customer_invoices
    ]
    for invoice in supplier_invoices:
        if not invoice["fake_client_expectations"].get("bank_open_item"):
            continue
        extracted = invoice["mock_extraction"]
        open_items.append(
            {
                "target_id": f"SI-{extracted['invoice_number']}",
                "target_type": "supplier_invoice",
                "date": extracted["invoice_date"],
                "due_date": extracted["due_date"],
                "amount_minor": -_minor(extracted["amounts"]["gross"]),
                "remaining_amount_minor": -_minor(extracted["amounts"]["gross"]),
                "currency": "SEK",
                "counterparty": extracted["supplier_name"],
                "reference": extracted["invoice_number"],
                "counterparty_id": extracted.get("supplier_org_number"),
                "counterparty_known": True,
                "bank_account": extracted.get("bankgiro"),
                "source": "fake_client:supplier_invoice",
                "description": extracted["description"],
            }
        )
    open_items.extend(
        [
            {
                "target_id": "VOUCHER-FAKE-BANK-FEE-2026-05",
                "target_type": "voucher",
                "date": "2026-05-31",
                "amount_minor": -3500,
                "remaining_amount_minor": -3500,
                "currency": "SEK",
                "counterparty": "FAKE SEB",
                "reference": "BANKFEE-FAKE-2026-05",
                "counterparty_id": "BANK-FAKE-SEB",
                "counterparty_known": True,
                "source": "fake_client:bank_fee_voucher_template",
                "description": "Monthly fake bank fee",
                "metadata": {"bas_account": "6570", "voucher_series": "A"},
            },
            {
                "target_id": "RCPT-FAKE-2026-010",
                "target_type": "receipt",
                "date": "2026-05-18",
                "amount_minor": -8900,
                "remaining_amount_minor": -8900,
                "currency": "SEK",
                "counterparty": "Fiktiv Kvittohandel AB",
                "reference": "RCPT-FAKE-2026-010",
                "counterparty_id": "RCPT-FAKE-001",
                "counterparty_known": True,
                "source": "fake_client:receipt",
                "description": "Small fake receipt matched to a card purchase",
            },
        ]
    )
    return open_items


def _supplier_fixture(
    *,
    scenario: str,
    source_filename: str,
    supplier_name: str,
    supplier_org_number: str,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    net: str,
    vat_rate: str,
    description: str,
    bankgiro: str,
    expected_policy_mode: str,
    risk_tags: tuple[str, ...] = (),
    extraction_confidence: float = 0.97,
    period_locked: bool = False,
    accounting_period: str | None = None,
    bank_open_item: bool = False,
) -> dict[str, Any]:
    vat = _money(Decimal(net) * Decimal(vat_rate) / Decimal("100"))
    gross = _money(Decimal(net) + Decimal(vat))
    ocr_text = "\n".join(
        [
            "FAKE CLIENT DRY RUN ONLY",
            f"Leverantor: {supplier_name}",
            f"Org.nr: {supplier_org_number}",
            f"Faktura: {invoice_number}",
            f"Fakturadatum: {invoice_date}",
            f"Forfallodatum: {due_date}",
            f"Bankgiro: {bankgiro}",
            description,
            f"Netto {net} SEK",
            f"Moms {vat_rate}% {vat} SEK",
            f"Att betala {gross} SEK",
        ]
    )
    mock_extraction: dict[str, Any] = {
        "supplier_name": supplier_name,
        "supplier_org_number": supplier_org_number,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "currency": "SEK",
        "amounts": {"net": net, "vat": vat, "gross": gross},
        "vat_rate": vat_rate,
        "description": description,
        "bankgiro": bankgiro,
        "extraction_confidence": extraction_confidence,
        "field_confidence": {
            "supplier_name": extraction_confidence,
            "invoice_number": extraction_confidence,
            "amounts": extraction_confidence,
            "vat_rate": min(extraction_confidence, 0.9),
        },
    }
    if period_locked:
        mock_extraction["period_locked"] = True
        mock_extraction["accounting_period"] = accounting_period
    return {
        "scenario": scenario,
        "source_filename": source_filename,
        "fake_data_notice": "Synthetic fake-client dry-run supplier invoice.",
        "ocr_text": ocr_text,
        "mock_extraction": mock_extraction,
        "fake_client_expectations": {
            "expected_policy_mode": expected_policy_mode,
            "risk_tags": list(risk_tags),
            "bank_open_item": bank_open_item,
        },
    }


def _customer_invoice(
    *,
    target_id: str,
    customer_id: str,
    customer_name: str,
    invoice_number: str,
    date: str,
    due_date: str,
    net: str,
    description: str,
) -> dict[str, Any]:
    vat = _money(Decimal(net) * Decimal("0.25"))
    gross = _money(Decimal(net) + Decimal(vat))
    return {
        "target_id": target_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "invoice_number": invoice_number,
        "date": date,
        "due_date": due_date,
        "currency": "SEK",
        "net_amount_minor": _minor(net),
        "vat_amount_minor": _minor(vat),
        "gross_amount_minor": _minor(gross),
        "vat_rate": "25",
        "description": description,
        "fake_data_notice": "Synthetic fake-client dry-run customer invoice.",
    }


def _bank_transaction(
    transaction_id: str,
    date: str,
    amount: str,
    counterparty: str,
    reference: str,
    expected_policy_mode: str,
    *,
    risk_tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "date": date,
        "amount_minor": _minor(amount),
        "currency": "SEK",
        "counterparty": counterparty,
        "reference": reference,
        "bank_account": "FAKE-SEB-1930",
        "source": "fake_client:bank_transaction",
        "fake_client_expectations": {
            "expected_policy_mode": expected_policy_mode,
            "risk_tags": list(risk_tags),
        },
    }


def _prepare_output_tree(output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "sample_data": output / "sample_data",
        "supplier_output": output / "supplier_invoice_autopilot",
        "bank_packets": output / "bank_reconciliation_packets",
        "bank_proposals": output / "bank_reconciliation_proposals.json",
        "audit_log": output / "audit_log.jsonl",
        "summary": output / "summary.json",
        "manifest": output / "manifest.json",
    }
    _ensure_output_can_be_reused(output, paths)
    _replace_text(
        output / FAKE_CLIENT_OUTPUT_MARKER,
        "managed by accounting_agent fake-client dry run\n",
    )
    for folder_key in ("sample_data", "bank_packets"):
        _clear_generated_files(paths[folder_key])
    for file_key in ("bank_proposals", "audit_log", "summary", "manifest"):
        _unlink_if_exists(paths[file_key])
    _replace_text(paths["audit_log"], "")
    return paths


def _ensure_output_can_be_reused(output: Path, paths: dict[str, Path]) -> None:
    if (output / FAKE_CLIENT_OUTPUT_MARKER).exists() or not any(output.iterdir()):
        return
    generated_paths = [path for path in paths.values() if path.exists()]
    if generated_paths:
        preview = ", ".join(str(path) for path in generated_paths[:3])
        raise FakeClientDryRunError(
            "Refusing to reuse an unmarked fake-client output folder. Choose an "
            f"empty folder or the default .local path: {preview}"
        )
    raise FakeClientDryRunError(
        f"Refusing to write fake-client output into non-empty unmarked folder: {output}"
    )


def _write_sample_data(root: Path, sample: dict[str, Any]) -> dict[str, Path]:
    supplier_root = root / "supplier_invoices"
    bank_root = root / "bank_reconciliation"
    supplier_root.mkdir(parents=True, exist_ok=True)
    bank_root.mkdir(parents=True, exist_ok=True)
    profile_path = root / "client_profile.json"
    customer_path = root / "customer_invoices.json"
    _write_json(profile_path, sample["profile"])
    _write_json(customer_path, {"customer_invoices": sample["customer_invoices"]})
    for index, fixture in enumerate(sample["supplier_invoices"], start=1):
        _write_json(supplier_root / f"{index:02d}_{fixture['scenario']}.json", fixture)
    _write_json(
        bank_root / "bank_transactions.json",
        {"transactions": sample["bank_reconciliation"]["bank_transactions"]},
    )
    _write_json(
        bank_root / "open_items.json",
        {"open_items": sample["bank_reconciliation"]["open_items"]},
    )
    _write_json(root / "coverage.json", sample["coverage"])
    return {
        "profile": profile_path,
        "supplier_invoices": supplier_root,
        "customer_invoices": customer_path,
        "bank_reconciliation": bank_root,
    }


def _measure_run(
    *,
    sample: dict[str, Any],
    supplier_manifest: dict[str, Any],
    bank_proposals: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    supplier_cases = supplier_manifest["cases"]
    supplier_expectations = {
        fixture["scenario"]: fixture["fake_client_expectations"]["expected_policy_mode"]
        for fixture in sample["supplier_invoices"]
    }
    bank_expectations = {
        transaction["transaction_id"]: transaction["fake_client_expectations"][
            "expected_policy_mode"
        ]
        for transaction in sample["bank_reconciliation"]["bank_transactions"]
    }

    supplier_modes = Counter(case["execution_gate_mode"] for case in supplier_cases)
    bank_modes = Counter(proposal["policy_decision"]["mode"] for proposal in bank_proposals)
    bank_matching_modes = Counter(
        proposal["matching_policy_decision"]["mode"] for proposal in bank_proposals
    )
    live_reconciliation_modes = Counter(
        proposal["live_reconciliation_policy_decision"]["mode"]
        for proposal in bank_proposals
    )
    primary_modes = supplier_modes + bank_modes
    observed_modes = primary_modes + bank_matching_modes + live_reconciliation_modes

    false_positives: list[dict[str, Any]] = []
    unsafe_misses: list[dict[str, Any]] = []
    unclear_outputs: list[dict[str, Any]] = []
    policy_alignment_warnings: list[dict[str, Any]] = []

    for case in supplier_cases:
        scenario = case["scenario"]
        actual = case["execution_gate_mode"]
        expected = supplier_expectations.get(scenario)
        _compare_expected(
            item_type="supplier_invoice",
            item_id=scenario,
            expected=expected,
            actual=actual,
            false_positives=false_positives,
            unsafe_misses=unsafe_misses,
            unclear_outputs=unclear_outputs,
        )
        if case["pipeline_policy_mode"] != case["execution_gate_mode"]:
            policy_alignment_warnings.append(
                {
                    "item_type": "supplier_invoice",
                    "item_id": scenario,
                    "reason": "pipeline_and_execution_gate_modes_differ",
                    "pipeline_policy_mode": case["pipeline_policy_mode"],
                    "execution_gate_mode": case["execution_gate_mode"],
                }
            )
        for artifact in case["artifacts"].values():
            if not (output_dir / "supplier_invoice_autopilot" / artifact).exists():
                unclear_outputs.append(
                    {
                        "item_type": "supplier_invoice",
                        "item_id": scenario,
                        "reason": "missing_artifact",
                        "artifact": artifact,
                    }
                )

    for proposal in bank_proposals:
        transaction_id = proposal["transaction"]["transaction_id"]
        actual = proposal["policy_decision"]["mode"]
        expected = bank_expectations.get(transaction_id)
        _compare_expected(
            item_type="bank_transaction",
            item_id=transaction_id,
            expected=expected,
            actual=actual,
            false_positives=false_positives,
            unsafe_misses=unsafe_misses,
            unclear_outputs=unclear_outputs,
        )
        if "policy_decision" not in proposal or "reconciliation_payload" not in proposal:
            unclear_outputs.append(
                {
                    "item_type": "bank_transaction",
                    "item_id": transaction_id,
                    "reason": "missing_policy_or_payload",
                }
            )

    supplier_permit_statuses = Counter(case["permit_status"] for case in supplier_cases)
    fortnox_payload_statuses = Counter(
        case["fortnox_adapter_payload_status"] for case in supplier_cases
    )
    return {
        "sample_counts": {
            "supplier_invoices_or_receipts": len(sample["supplier_invoices"]),
            "customer_invoices": len(sample["customer_invoices"]),
            "bank_transactions": len(sample["bank_reconciliation"]["bank_transactions"]),
            **sample["coverage"],
        },
        "primary_case_decision_counts": _mode_counts(primary_modes),
        "supplier_decision_counts": _mode_counts(supplier_modes),
        "bank_proposal_decision_counts": _mode_counts(bank_modes),
        "observed_policy_decision_counts": _mode_counts(observed_modes),
        "bank_read_analysis_decision_counts": _mode_counts(bank_matching_modes),
        "live_reconciliation_decision_counts": _mode_counts(live_reconciliation_modes),
        "execution_permit_statuses": dict(supplier_permit_statuses),
        "fortnox_payload_statuses": dict(fortnox_payload_statuses),
        "false_positives": false_positives,
        "unsafe_misses": unsafe_misses,
        "unclear_outputs": unclear_outputs,
        "policy_alignment_warnings": policy_alignment_warnings,
        "safety_misses": {
            "live_fortnox_calls": 0,
            "live_microsoft365_calls": 0,
            "email_sends": 0,
            "payments_or_filings": 0,
            "final_voucher_postings": 0,
        },
    }


def _compare_expected(
    *,
    item_type: str,
    item_id: str,
    expected: str | None,
    actual: str,
    false_positives: list[dict[str, Any]],
    unsafe_misses: list[dict[str, Any]],
    unclear_outputs: list[dict[str, Any]],
) -> None:
    if expected is None:
        unclear_outputs.append(
            {
                "item_type": item_type,
                "item_id": item_id,
                "reason": "missing_expected_policy_mode",
                "actual_policy_mode": actual,
            }
        )
        return
    expected_level = MODE_SEVERITY[expected]
    actual_level = MODE_SEVERITY[actual]
    if actual_level > expected_level:
        false_positives.append(
            {
                "item_type": item_type,
                "item_id": item_id,
                "expected_policy_mode": expected,
                "actual_policy_mode": actual,
            }
        )
    elif actual_level < expected_level:
        unsafe_misses.append(
            {
                "item_type": item_type,
                "item_id": item_id,
                "expected_policy_mode": expected,
                "actual_policy_mode": actual,
            }
        )


def _write_audit_events(
    *,
    audit_log: JsonlAuditLog,
    client_id: str,
    supplier_manifest: dict[str, Any],
    bank_proposals: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> None:
    for case in supplier_manifest["cases"]:
        audit_log.append_event(
            event_type="fake_client_supplier_case_processed",
            case_id=case["case_id"],
            client_id=client_id,
            actor="fake_client_dry_run",
            action="supplier_invoice_pipeline",
            details={
                "scenario": case["scenario"],
                "policy_mode": case["execution_gate_mode"],
                "permit_status": case["permit_status"],
                "live_api_call": False,
            },
        )
    for proposal in bank_proposals:
        transaction_id = proposal["transaction"]["transaction_id"]
        audit_log.append_event(
            event_type="fake_client_bank_transaction_processed",
            case_id=proposal["case"]["case_id"],
            client_id=client_id,
            actor="fake_client_dry_run",
            action="bank_reconciliation_pipeline",
            details={
                "transaction_id": transaction_id,
                "policy_mode": proposal["policy_decision"]["mode"],
                "live_reconciliation_mode": proposal[
                    "live_reconciliation_policy_decision"
                ]["mode"],
                "live_api_call": False,
            },
        )
    audit_log.append_event(
        event_type="fake_client_dry_run_completed",
        case_id="fake_client_month_2026_05",
        client_id=client_id,
        actor="fake_client_dry_run",
        action="summarize_run",
        details={
            "primary_case_decision_counts": metrics["primary_case_decision_counts"],
            "false_positive_count": len(metrics["false_positives"]),
            "unsafe_miss_count": len(metrics["unsafe_misses"]),
            "unclear_output_count": len(metrics["unclear_outputs"]),
            "live_api_calls": 0,
        },
    )


def _write_report(report_path: Path, manifest: dict[str, Any]) -> None:
    metrics = manifest["metrics"]
    safety = manifest["safety"]
    sample_counts = metrics["sample_counts"]
    readiness = (
        "local_fake_client_dry_run_complete"
        if not metrics["unsafe_misses"] and not metrics["unclear_outputs"]
        else "local_fake_client_dry_run_needs_follow_up"
    )
    lines = [
        "# Fake client dry-run report",
        "",
        f"Generated: {manifest['run']['generated_at']}",
        "",
        f"Readiness: `{readiness}`.",
        "",
        "Live-system readiness: `not_ready_for_live_connection`. This run proves only the local fake-data path; Fortnox, Microsoft 365, email, payment, tax filing, and final posting remain intentionally blocked.",
        "",
        "## Documented command",
        "",
        "```bash",
        manifest["run"]["documented_command"],
        "```",
        "",
        "Default output folder:",
        "",
        "```text",
        manifest["run"]["output_dir"],
        "```",
        "",
        "## Safety result",
        "",
        f"- Fake data only: `{safety['fake_data_only']}`",
        f"- Real client data used: `{safety['real_client_data_used']}`",
        f"- Live Fortnox calls: `{safety['live_fortnox_calls']}`",
        f"- Live Microsoft 365 calls: `{safety['live_microsoft365_calls']}`",
        f"- Emails sent: `{safety['emails_sent']}`",
        f"- Payments or filings: `{safety['payments_or_filings']}`",
        f"- Final voucher postings: `{safety['final_voucher_postings']}`",
        "",
        "## Fake client profile",
        "",
        "- Client: `fake-se-service-001` / `Fiktiv Konsultstudio AB`",
        "- Business: small Swedish consulting/service business",
        "- Currency: SEK",
        "- VAT: Swedish VAT, with 25%, 0%, and one intentionally uncertain VAT case",
        "- Known suppliers: 8 synthetic suppliers",
        "- Known customers: 5 synthetic customers",
        "",
        "## Sample data coverage",
        "",
        f"- Supplier invoices/receipts: `{sample_counts['supplier_invoices_or_receipts']}`",
        f"- Customer invoices: `{sample_counts['customer_invoices']}`",
        f"- Bank transactions: `{sample_counts['bank_transactions']}`",
        f"- Ambiguous/edge cases: `{sample_counts['ambiguous_edge_cases']}`",
        f"- Duplicate-risk cases: `{sample_counts['duplicate_risk_cases']}`",
        f"- Changed bank-details cases: `{sample_counts['changed_bank_details_cases']}`",
        f"- Uncertain VAT cases: `{sample_counts['uncertain_vat_cases']}`",
        f"- Old/locked-period cases: `{sample_counts['old_locked_period_cases']}`",
        "",
        "## Policy decisions",
        "",
        "| Mode | Primary cases | Observed decisions |",
        "| --- | ---: | ---: |",
    ]
    for mode in PERMISSION_MODES:
        lines.append(
            f"| `{mode}` | {metrics['primary_case_decision_counts'][mode]} | {metrics['observed_policy_decision_counts'][mode]} |"
        )
    lines.extend(
        [
            "",
            "Primary cases count supplier invoice execution-gate decisions plus bank reconciliation proposal decisions. Observed decisions also include bank read-analysis decisions and intentionally forbidden live-reconciliation decisions.",
            "",
            "## Execution and adapter results",
            "",
            f"- Supplier execution permits: `{metrics['execution_permit_statuses']}`",
            f"- Fortnox dry-run payload statuses: `{metrics['fortnox_payload_statuses']}`",
            f"- Supplier approval packets: `{manifest['supplier_invoice_autopilot']['summary']['approval_packets']}`",
            f"- Bank reconciliation proposals: `{manifest['bank_reconciliation']['proposal_count']}`",
            f"- Top-level audit events: `{metrics['audit_events']}`",
            "",
            "## Accuracy review",
            "",
            f"- False positives: `{len(metrics['false_positives'])}`",
            f"- Unsafe misses: `{len(metrics['unsafe_misses'])}`",
            f"- Unclear outputs: `{len(metrics['unclear_outputs'])}`",
            f"- Policy alignment warnings: `{len(metrics['policy_alignment_warnings'])}`",
        ]
    )
    if metrics["false_positives"]:
        lines.extend(["", "False-positive details:"])
        lines.extend(f"- `{item}`" for item in metrics["false_positives"])
    if metrics["unsafe_misses"]:
        lines.extend(["", "Unsafe-miss details:"])
        lines.extend(f"- `{item}`" for item in metrics["unsafe_misses"])
    if metrics["unclear_outputs"]:
        lines.extend(["", "Unclear-output details:"])
        lines.extend(f"- `{item}`" for item in metrics["unclear_outputs"])
    if metrics["policy_alignment_warnings"]:
        lines.extend(["", "Policy-alignment warnings:"])
        lines.extend(
            f"- `{item}`. Policy disagreement is a hard stop and no permit is issued."
            for item in metrics["policy_alignment_warnings"]
        )
    lines.extend(
        [
            "",
            "## Errors",
            "",
            "- No local pipeline completion errors were recorded.",
            "- No live external system was contacted.",
            "",
            "## Next blockers",
            "",
            "- Live Fortnox remains blocked until a guarded adapter phase explicitly adds config gates, execution permits, idempotency, and reviewed sandbox behavior.",
            "- Microsoft 365 intake remains local/mock-only in this dry run.",
            "- Customer invoice creation, supplier invoice approval, payments, tax filing, and final voucher posting remain outside this MVP dry run.",
            "- Human accounting review is still required for review, escalation, and forbidden cases before any future live workflow.",
            "",
            "## Output index",
            "",
            f"- Manifest: `{manifest['run']['output_dir']}/manifest.json`",
            f"- Summary: `{manifest['run']['output_dir']}/summary.json`",
            f"- Synthetic sample data: `{manifest['run']['output_dir']}/sample_data`",
            f"- Supplier pipeline output: `{manifest['run']['output_dir']}/supplier_invoice_autopilot`",
            f"- Bank proposals: `{manifest['run']['output_dir']}/{manifest['bank_reconciliation']['proposal_path']}`",
            f"- Audit log: `{manifest['run']['output_dir']}/audit_log.jsonl`",
            "",
        ]
    )
    _replace_text(report_path, "\n".join(lines))


def _summary_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    metrics = manifest["metrics"]
    return {
        "status": manifest["run"]["status"],
        "output_dir": manifest["run"]["output_dir"],
        "report_path": manifest["run"]["report_path"],
        "sample_counts": metrics["sample_counts"],
        "primary_case_decision_counts": metrics["primary_case_decision_counts"],
        "observed_policy_decision_counts": metrics["observed_policy_decision_counts"],
        "false_positive_count": len(metrics["false_positives"]),
        "unsafe_miss_count": len(metrics["unsafe_misses"]),
        "unclear_output_count": len(metrics["unclear_outputs"]),
        "policy_alignment_warning_count": len(metrics["policy_alignment_warnings"]),
        "safety": manifest["safety"],
    }


def _mode_counts(counter: Counter[str]) -> dict[str, int]:
    return {mode: int(counter.get(mode, 0)) for mode in PERMISSION_MODES}


def _count_tagged(
    supplier_invoices: list[dict[str, Any]],
    bank_transactions: list[dict[str, Any]],
    tag: str,
) -> int:
    count = 0
    for fixture in supplier_invoices:
        tags = fixture["fake_client_expectations"].get("risk_tags", ())
        if tag in tags:
            count += 1
    for transaction in bank_transactions:
        tags = transaction["fake_client_expectations"].get("risk_tags", ())
        if tag in tags:
            count += 1
    return count


def _clear_generated_files(folder: Path) -> None:
    if folder.exists():
        for path in sorted(folder.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
    folder.mkdir(parents=True, exist_ok=True)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _replace_text(path: Path, text: str) -> None:
    """Write generated text without opening stale offloaded placeholders."""

    path.parent.mkdir(parents=True, exist_ok=True)
    _unlink_if_exists(path)
    path.write_text(text, encoding="utf-8")


def _minor(amount: str) -> int:
    return int((Decimal(amount) * Decimal("100")).quantize(Decimal("1")))


def _money(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.01")))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relative_to_output(path: Path, output: Path) -> str:
    try:
        return str(path.relative_to(output))
    except ValueError:
        return str(path)
