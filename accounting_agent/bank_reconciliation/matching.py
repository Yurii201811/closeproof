"""Explainable candidate matching for local bank reconciliation fixtures."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable
import unicodedata

from .models import BankTransaction, MatchCandidate, MatchTarget


MIN_CANDIDATE_CONFIDENCE = 0.35


def build_candidates(
    transaction: BankTransaction,
    targets: Iterable[MatchTarget],
) -> list[MatchCandidate]:
    candidates = [
        candidate
        for target in targets
        if _target_is_available(target)
        if (candidate := score_candidate(transaction, target)) is not None
    ]
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.confidence,
            -abs(candidate.amount_delta_minor),
            -candidate.date_delta_days,
        ),
        reverse=True,
    )


def score_candidate(
    transaction: BankTransaction,
    target: MatchTarget,
) -> MatchCandidate | None:
    breakdown: dict[str, float] = {}
    explanations: list[str] = []
    flags: list[str] = []

    if transaction.currency == target.currency:
        breakdown["currency"] = 0.05
        explanations.append("Currency matches.")
    else:
        breakdown["currency"] = -0.25
        flags.append("currency_mismatch")
        explanations.append("Currency differs from the open item.")

    if transaction.direction == target.direction:
        breakdown["direction"] = 0.10
        explanations.append(f"Bank movement direction matches {target.target_type.value}.")
    else:
        breakdown["direction"] = -0.20
        flags.append("direction_mismatch")
        explanations.append("Bank movement direction does not match the expected item direction.")

    amount_delta = transaction.amount_minor - target.expected_amount_minor
    absolute_delta = abs(amount_delta)
    if absolute_delta == 0:
        breakdown["amount"] = 0.35
        explanations.append("Amount exactly equals the open amount.")
    elif _is_partial_payment(transaction, target):
        breakdown["amount"] = 0.18
        flags.append("partial_payment")
        explanations.append(
            "Amount is lower than the open amount while the reference still points to the item."
        )
    else:
        ratio = Decimal(absolute_delta) / Decimal(max(abs(target.expected_amount_minor), 1))
        if ratio <= Decimal("0.02"):
            breakdown["amount"] = 0.16
            flags.append("small_amount_delta")
            explanations.append("Amount is close, but not exact.")
        else:
            breakdown["amount"] = 0.0
            flags.append("amount_mismatch")
            explanations.append("Amount does not match the open amount.")

    reference_score, reference_explanation = _score_reference(transaction, target)
    breakdown["reference"] = reference_score
    if reference_score <= 0:
        flags.append("reference_mismatch")
    explanations.append(reference_explanation)

    counterparty_score, counterparty_explanation = _score_counterparty(transaction, target)
    breakdown["counterparty"] = counterparty_score
    if counterparty_score <= 0:
        flags.append("counterparty_mismatch")
    explanations.append(counterparty_explanation)

    date_delta = _date_delta_days(transaction, target)
    if date_delta <= 3:
        breakdown["date"] = 0.12
        explanations.append("Transaction date is within three days of the expected date.")
    elif date_delta <= 10:
        breakdown["date"] = 0.06
        explanations.append("Transaction date is within ten days of the expected date.")
    else:
        breakdown["date"] = 0.0
        flags.append("date_distance")
        explanations.append("Transaction date is far from the expected date.")

    confidence = round(max(0.0, min(0.99, sum(breakdown.values()))), 2)
    if "partial_payment" in flags:
        confidence = min(confidence, 0.78)
    if "currency_mismatch" in flags or "direction_mismatch" in flags:
        confidence = min(confidence, 0.55)
    if confidence < MIN_CANDIDATE_CONFIDENCE:
        return None

    return MatchCandidate(
        transaction_id=transaction.transaction_id,
        target_id=target.target_id,
        target_type=target.target_type,
        confidence=confidence,
        amount_delta_minor=amount_delta,
        date_delta_days=date_delta,
        score_breakdown=breakdown,
        explanations=tuple(explanations),
        flags=tuple(dict.fromkeys(flags)),
    )


def duplicate_transaction_risks(
    transactions: Iterable[BankTransaction],
) -> dict[str, float]:
    transaction_list = list(transactions)
    risks = {transaction.transaction_id: 0.0 for transaction in transaction_list}
    for index, transaction in enumerate(transaction_list):
        for candidate in transaction_list[index + 1 :]:
            if not _looks_like_duplicate(transaction, candidate):
                continue
            risks[transaction.transaction_id] = 0.85
            risks[candidate.transaction_id] = 0.85
    return risks


def normalize_reference(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def normalize_counterparty(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _score_reference(
    transaction: BankTransaction,
    target: MatchTarget,
) -> tuple[float, str]:
    tx_reference = normalize_reference(transaction.reference)
    target_reference = normalize_reference(target.reference)
    if not target_reference:
        return 0.0, "Open item has no reference to compare."
    if tx_reference == target_reference:
        return 0.30, "OCR/reference exactly matches the open item."
    if target_reference and target_reference in tx_reference:
        return 0.23, "OCR/reference contains the open item reference."
    alternate_references = [
        normalize_reference(str(value))
        for value in target.metadata.get("alternate_references", ())
    ]
    if tx_reference in alternate_references:
        return 0.26, "OCR/reference matches an alternate open item reference."
    return 0.0, "OCR/reference does not match the open item."


def _score_counterparty(
    transaction: BankTransaction,
    target: MatchTarget,
) -> tuple[float, str]:
    tx_counterparty = normalize_counterparty(transaction.counterparty)
    target_counterparty = normalize_counterparty(target.counterparty)
    if not target_counterparty:
        return 0.0, "Open item has no counterparty to compare."
    if tx_counterparty == target_counterparty:
        return 0.15, "Counterparty exactly matches the open item."
    if tx_counterparty and (
        tx_counterparty in target_counterparty or target_counterparty in tx_counterparty
    ):
        return 0.08, "Counterparty text partially matches the open item."
    return 0.0, "Counterparty does not match the open item."


def _is_partial_payment(transaction: BankTransaction, target: MatchTarget) -> bool:
    if transaction.direction != target.direction:
        return False
    if abs(transaction.amount_minor) >= abs(target.expected_amount_minor):
        return False
    if normalize_reference(transaction.reference) == normalize_reference(target.reference):
        return True
    return normalize_counterparty(transaction.counterparty) == normalize_counterparty(
        target.counterparty
    )


def _date_delta_days(transaction: BankTransaction, target: MatchTarget) -> int:
    comparison_date = target.due_date or target.date
    return abs((transaction.date - comparison_date).days)


def _duplicate_signature(transaction: BankTransaction) -> tuple[str, int, str, str, str]:
    return (
        transaction.currency,
        transaction.amount_minor,
        normalize_reference(transaction.reference),
        normalize_counterparty(transaction.counterparty),
        normalize_reference(transaction.bank_account),
    )


def _looks_like_duplicate(
    first: BankTransaction,
    second: BankTransaction,
    *,
    date_window_days: int = 3,
) -> bool:
    """Return whether two bank rows need duplicate review.

    The bank-account boundary and a narrow date window avoid treating recurring
    monthly payments as duplicates while still catching adjacent imported rows.
    """

    return (
        _duplicate_signature(first) == _duplicate_signature(second)
        and abs((first.date - second.date).days) <= date_window_days
    )


def _target_is_available(target: MatchTarget) -> bool:
    """Only open targets with a non-zero residual may receive proposals."""

    return target.status.casefold() in {"open", "partially_open", "partial"} and (
        target.expected_amount_minor != 0
    )
