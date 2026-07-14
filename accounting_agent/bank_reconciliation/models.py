"""Typed models for fixture-only bank reconciliation proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Mapping


class MatchTargetType(str, Enum):
    CUSTOMER_INVOICE = "customer_invoice"
    SUPPLIER_INVOICE = "supplier_invoice"
    RECEIPT = "receipt"
    VOUCHER = "voucher"


@dataclass(frozen=True)
class BankTransaction:
    transaction_id: str
    date: date
    amount_minor: int
    currency: str
    counterparty: str
    reference: str
    bank_account: str
    source: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BankTransaction":
        return cls(
            transaction_id=str(data["transaction_id"]),
            date=date.fromisoformat(str(data["date"])),
            amount_minor=int(data["amount_minor"]),
            currency=str(data.get("currency") or "SEK"),
            counterparty=str(data.get("counterparty") or ""),
            reference=str(data.get("reference") or ""),
            bank_account=str(data.get("bank_account") or ""),
            source=str(data.get("source") or "fixture"),
        )

    @property
    def direction(self) -> str:
        if self.amount_minor > 0:
            return "inflow"
        if self.amount_minor < 0:
            return "outflow"
        return "zero"

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "date": self.date.isoformat(),
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "counterparty": self.counterparty,
            "reference": self.reference,
            "bank_account": self.bank_account,
            "source": self.source,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class MatchTarget:
    target_id: str
    target_type: MatchTargetType
    date: date
    amount_minor: int
    currency: str
    counterparty: str
    reference: str
    source: str
    due_date: date | None = None
    remaining_amount_minor: int | None = None
    counterparty_id: str | None = None
    counterparty_known: bool = True
    bank_account: str | None = None
    description: str = ""
    status: str = "open"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchTarget":
        due_date = data.get("due_date")
        return cls(
            target_id=str(data["target_id"]),
            target_type=MatchTargetType(str(data["target_type"])),
            date=date.fromisoformat(str(data["date"])),
            due_date=date.fromisoformat(str(due_date)) if due_date else None,
            amount_minor=int(data["amount_minor"]),
            remaining_amount_minor=(
                int(data["remaining_amount_minor"])
                if data.get("remaining_amount_minor") is not None
                else None
            ),
            currency=str(data.get("currency") or "SEK"),
            counterparty=str(data.get("counterparty") or ""),
            reference=str(data.get("reference") or ""),
            counterparty_id=(
                str(data["counterparty_id"])
                if data.get("counterparty_id") is not None
                else None
            ),
            counterparty_known=bool(data.get("counterparty_known", True)),
            bank_account=(
                str(data["bank_account"]) if data.get("bank_account") is not None else None
            ),
            source=str(data.get("source") or "fixture"),
            description=str(data.get("description") or ""),
            status=str(data.get("status") or "open"),
            metadata=dict(data.get("metadata") or {}),
        )

    @property
    def expected_amount_minor(self) -> int:
        if self.remaining_amount_minor is not None:
            return self.remaining_amount_minor
        return self.amount_minor

    @property
    def direction(self) -> str:
        if self.expected_amount_minor > 0:
            return "inflow"
        if self.expected_amount_minor < 0:
            return "outflow"
        return "zero"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_type": self.target_type.value,
            "date": self.date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "amount_minor": self.amount_minor,
            "remaining_amount_minor": self.remaining_amount_minor,
            "expected_amount_minor": self.expected_amount_minor,
            "currency": self.currency,
            "counterparty": self.counterparty,
            "reference": self.reference,
            "counterparty_id": self.counterparty_id,
            "counterparty_known": self.counterparty_known,
            "bank_account": self.bank_account,
            "source": self.source,
            "description": self.description,
            "status": self.status,
            "metadata": dict(self.metadata),
            "direction": self.direction,
        }


@dataclass(frozen=True)
class MatchCandidate:
    transaction_id: str
    target_id: str
    target_type: MatchTargetType
    confidence: float
    amount_delta_minor: int
    date_delta_days: int
    score_breakdown: Mapping[str, float]
    explanations: tuple[str, ...]
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "target_id": self.target_id,
            "target_type": self.target_type.value,
            "confidence": self.confidence,
            "amount_delta_minor": self.amount_delta_minor,
            "date_delta_days": self.date_delta_days,
            "score_breakdown": dict(self.score_breakdown),
            "explanations": list(self.explanations),
            "flags": list(self.flags),
        }
