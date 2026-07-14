"""Canonical draft-journal models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from accounting_agent.accounting.money import Money
from accounting_agent.client_identity import canonical_client_id

if TYPE_CHECKING:
    from .validation import JournalValidation, JournalValidationPolicy


@dataclass(frozen=True)
class JournalLine:
    account: str
    description: str
    debit: Money | None = None
    credit: Money | None = None
    evidence_hashes: tuple[str, ...] = ()
    dimension: str | None = None


@dataclass(frozen=True)
class JournalDraft:
    journal_id: str
    client_id: str
    entity_id: str
    posting_date: str
    description: str
    source_document_hash: str
    lines: tuple[JournalLine, ...]
    period_locked: bool = False
    reversal_of: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", canonical_client_id(self.client_id))
        object.__setattr__(self, "entity_id", canonical_client_id(self.entity_id))
        object.__setattr__(self, "lines", tuple(self.lines))

    def validate(self, policy: "JournalValidationPolicy | None" = None) -> "JournalValidation":
        from .validation import validate_journal

        return validate_journal(self, policy)

    def require_valid(self, policy: "JournalValidationPolicy | None" = None) -> None:
        result = self.validate(policy)
        if not result.is_valid:
            from .validation import JournalValidationError

            raise JournalValidationError(result)

    def t_accounts(self) -> dict[str, dict[str, int]]:
        accounts: dict[str, dict[str, int]] = {}
        for line in self.lines:
            totals = accounts.setdefault(
                line.account,
                {"debit_minor": 0, "credit_minor": 0},
            )
            if line.debit is not None:
                totals["debit_minor"] += line.debit.minor
            if line.credit is not None:
                totals["credit_minor"] += line.credit.minor
        return accounts
