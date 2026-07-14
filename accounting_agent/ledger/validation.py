"""Fail-closed validation for canonical journal drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from accounting_agent.accounting.money import Money

from .models import JournalDraft


@dataclass(frozen=True)
class JournalValidationPolicy:
    chart_id: str | None = None
    allowed_accounts: frozenset[str] | None = None
    require_line_evidence: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.require_line_evidence, bool):
            raise TypeError("require_line_evidence must be boolean")
        if self.chart_id is not None and (
            not isinstance(self.chart_id, str) or not self.chart_id.strip()
        ):
            raise ValueError("chart_id must be a non-empty string when provided")
        if self.allowed_accounts is not None:
            accounts = frozenset(self.allowed_accounts)
            if not accounts or any(
                not isinstance(account, str) or not account.strip()
                for account in accounts
            ):
                raise ValueError("allowed_accounts must contain non-empty account identifiers")
            object.__setattr__(self, "allowed_accounts", accounts)


@dataclass(frozen=True)
class JournalIssue:
    code: str
    message: str
    line_index: int | None = None


@dataclass(frozen=True)
class JournalValidation:
    journal_id: str
    is_valid: bool
    issues: tuple[JournalIssue, ...]
    debit_total: Money | None
    credit_total: Money | None

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


class JournalValidationError(ValueError):
    def __init__(self, validation: JournalValidation) -> None:
        self.validation = validation
        codes = ", ".join(validation.error_codes)
        super().__init__(f"journal {validation.journal_id} is invalid: {codes}")


def validate_journal(
    draft: JournalDraft,
    policy: JournalValidationPolicy | None = None,
) -> JournalValidation:
    policy = policy or JournalValidationPolicy()
    issues: list[JournalIssue] = []
    if not draft.journal_id.strip():
        issues.append(JournalIssue("journal_id_missing", "Journal id is required."))
    if policy.chart_id is None or policy.allowed_accounts is None:
        issues.append(
            JournalIssue(
                "chart_of_accounts_not_bound",
                "Journal validation requires an explicit versioned chart of accounts.",
            )
        )
    try:
        date.fromisoformat(draft.posting_date)
    except ValueError:
        issues.append(JournalIssue("posting_date_invalid", "Posting date must be ISO YYYY-MM-DD."))
    if draft.period_locked:
        issues.append(JournalIssue("period_locked", "The accounting period is locked."))
    if not re.fullmatch(r"[0-9a-fA-F]{64}", draft.source_document_hash):
        issues.append(
            JournalIssue(
                "source_document_hash_invalid",
                "A source-document SHA-256 digest is required.",
            )
        )
    if len(draft.lines) < 2:
        issues.append(JournalIssue("journal_lines_missing", "At least two journal lines are required."))

    currencies: set[str] = set()
    debit_minor = 0
    credit_minor = 0
    for index, line in enumerate(draft.lines):
        if not isinstance(line.account, str) or not line.account.strip():
            issues.append(
                JournalIssue(
                    "account_missing",
                    "Every journal line requires a non-empty account identifier.",
                    index,
                )
            )
        sides = int(line.debit is not None) + int(line.credit is not None)
        if sides != 1:
            issues.append(
                JournalIssue(
                    "line_must_have_exactly_one_side",
                    "Each journal line must have either debit or credit, never both or neither.",
                    index,
                )
            )
        for amount in (line.debit, line.credit):
            if amount is None:
                continue
            currencies.add(amount.currency)
            if amount.minor <= 0:
                issues.append(
                    JournalIssue(
                        "line_amount_must_be_positive",
                        "Journal-line amounts must be positive; use the opposite side for reversals.",
                        index,
                    )
                )
        if line.debit is not None:
            debit_minor += line.debit.minor
        if line.credit is not None:
            credit_minor += line.credit.minor
        if policy.allowed_accounts is not None and line.account not in policy.allowed_accounts:
            issues.append(
                JournalIssue(
                    "account_not_allowed",
                    f"Account {line.account!r} is not in the selected chart.",
                    index,
                )
            )
        if policy.require_line_evidence and not line.evidence_hashes:
            issues.append(
                JournalIssue(
                    "line_evidence_missing",
                    "Every journal line requires supporting evidence.",
                    index,
                )
            )
        for digest in line.evidence_hashes:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                issues.append(
                    JournalIssue(
                        "line_evidence_hash_invalid",
                        "Journal-line evidence must use SHA-256 digests.",
                        index,
                    )
                )
        if (
            policy.require_line_evidence
            and re.fullmatch(r"[0-9a-fA-F]{64}", draft.source_document_hash)
            and draft.source_document_hash.lower()
            not in {digest.lower() for digest in line.evidence_hashes}
        ):
            issues.append(
                JournalIssue(
                    "line_evidence_not_bound_to_source",
                    "Every journal line must retain the journal's source-document digest.",
                    index,
                )
            )

    if len(currencies) > 1:
        issues.append(
            JournalIssue(
                "mixed_currencies",
                "A canonical journal must use one functional currency; convert with evidence first.",
            )
        )
    currency = next(iter(currencies), None)
    debit_total = Money(debit_minor, currency) if currency is not None else None
    credit_total = Money(credit_minor, currency) if currency is not None else None
    if debit_minor != credit_minor:
        issues.append(
            JournalIssue(
                "journal_unbalanced",
                "Total debits must equal total credits.",
            )
        )

    return JournalValidation(
        journal_id=draft.journal_id,
        is_valid=not issues,
        issues=tuple(issues),
        debit_total=debit_total,
        credit_total=credit_total,
    )
