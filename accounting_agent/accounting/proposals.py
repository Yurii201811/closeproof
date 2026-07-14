"""Supplier-invoice accounting proposal models and Fortnox dry-run payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from accounting_agent.accounting.money import Money
from accounting_agent.client_identity import canonical_client_id
from accounting_agent.ledger import JournalDraft, JournalLine

from .vat import expected_purchase_vat_mapping


@dataclass(frozen=True)
class AccountingEntry:
    account: str
    debit_minor: int = 0
    credit_minor: int = 0
    description: str = ""
    vat_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupplierInvoiceProposal:
    proposal_id: str
    case_id: str
    client_id: str
    entity_id: str
    supplier_id: str
    supplier_name: str
    invoice_number: str
    invoice_date: str
    due_date: str
    currency: str
    net_amount_minor: int
    vat_amount_minor: int
    gross_amount_minor: int
    vat_rate_percent: int
    expense_account: str
    vat_account: str = "2641"
    payable_account: str = "2440"
    description: str = ""
    confidence: float = 1.0
    entries: tuple[AccountingEntry, ...] = field(default_factory=tuple)
    source_document_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", canonical_client_id(self.entity_id))

    def accounting_entries(self) -> tuple[AccountingEntry, ...]:
        if self.entries:
            return self.entries

        vat_mapping = expected_purchase_vat_mapping(self.vat_rate_percent)
        vat_code = vat_mapping.vat_code if vat_mapping else None
        description = self.description or f"Supplier invoice {self.invoice_number}"
        entries = [
            AccountingEntry(
                account=self.expense_account,
                debit_minor=self.net_amount_minor,
                description=description,
                vat_code=vat_code,
            )
        ]
        if self.vat_amount_minor:
            entries.append(
                AccountingEntry(
                    account=self.vat_account,
                    debit_minor=self.vat_amount_minor,
                    description=f"Input VAT {self.invoice_number}",
                    vat_code=vat_code,
                )
            )
        entries.append(
            AccountingEntry(
                account=self.payable_account,
                credit_minor=self.gross_amount_minor,
                description=f"Accounts payable {self.supplier_name}",
            )
        )
        return tuple(entries)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entries"] = [entry.to_dict() for entry in self.accounting_entries()]
        return data

    def to_journal_draft(self, *, period_locked: bool = False) -> JournalDraft:
        evidence = (self.source_document_hash,) if self.source_document_hash else ()
        lines = tuple(
            JournalLine(
                account=entry.account,
                description=entry.description,
                debit=(
                    Money(entry.debit_minor, self.currency)
                    if entry.debit_minor != 0
                    else None
                ),
                credit=(
                    Money(entry.credit_minor, self.currency)
                    if entry.credit_minor != 0
                    else None
                ),
                evidence_hashes=evidence,
            )
            for entry in self.accounting_entries()
        )
        return JournalDraft(
            journal_id=f"journal:{self.proposal_id}",
            client_id=self.client_id,
            entity_id=self.entity_id,
            posting_date=self.invoice_date,
            description=self.description or f"Supplier invoice {self.invoice_number}",
            source_document_hash=self.source_document_hash,
            lines=lines,
            period_locked=period_locked,
        )


def supplier_invoice_proposal_from_dict(
    data: Mapping[str, Any],
) -> SupplierInvoiceProposal:
    entries = tuple(
        AccountingEntry(
            account=str(entry["account"]),
            debit_minor=int(entry.get("debit_minor", 0)),
            credit_minor=int(entry.get("credit_minor", 0)),
            description=str(entry.get("description", "")),
            vat_code=entry.get("vat_code"),
        )
        for entry in data.get("entries", ())
    )
    return SupplierInvoiceProposal(
        proposal_id=str(data["proposal_id"]),
        case_id=str(data["case_id"]),
        client_id=str(data["client_id"]),
        entity_id=data["entity_id"],
        supplier_id=str(data["supplier_id"]),
        supplier_name=str(data["supplier_name"]),
        invoice_number=str(data["invoice_number"]),
        invoice_date=str(data["invoice_date"]),
        due_date=str(data["due_date"]),
        currency=str(data.get("currency", "SEK")),
        net_amount_minor=int(data["net_amount_minor"]),
        vat_amount_minor=int(data["vat_amount_minor"]),
        gross_amount_minor=int(data["gross_amount_minor"]),
        vat_rate_percent=int(data["vat_rate_percent"]),
        expense_account=str(data["expense_account"]),
        vat_account=str(data.get("vat_account", "2641")),
        payable_account=str(data.get("payable_account", "2440")),
        description=str(data.get("description", "")),
        confidence=float(data.get("confidence", 1.0)),
        entries=entries,
        source_document_hash=str(data.get("source_document_hash", "")),
    )


def fortnox_supplier_invoice_payload(
    proposal: SupplierInvoiceProposal,
) -> dict[str, Any]:
    """Return a Fortnox-facing dry-run payload for comparison and permits."""

    return {
        "source": "fortnox_dry_run",
        "production_source_of_truth": "fortnox",
        "case_id": proposal.case_id,
        "proposal_id": proposal.proposal_id,
        "client_id": proposal.client_id,
        "entity_id": proposal.entity_id,
        "supplier": {
            "supplier_id": proposal.supplier_id,
            "name": proposal.supplier_name,
        },
        "invoice": {
            "invoice_number": proposal.invoice_number,
            "invoice_date": proposal.invoice_date,
            "due_date": proposal.due_date,
            "currency": proposal.currency,
            "net_amount_minor": proposal.net_amount_minor,
            "vat_amount_minor": proposal.vat_amount_minor,
            "gross_amount_minor": proposal.gross_amount_minor,
            "vat_rate_percent": proposal.vat_rate_percent,
        },
        "accounting_rows": [
            {
                "account": entry.account,
                "debit_minor": entry.debit_minor,
                "credit_minor": entry.credit_minor,
                "vat_code": entry.vat_code,
                "description": entry.description,
            }
            for entry in proposal.accounting_entries()
        ],
    }
