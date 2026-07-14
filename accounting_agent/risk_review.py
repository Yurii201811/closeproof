"""Structured Openclaw risk review for accounting cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from statistics import median
from typing import Any


RISK_REVIEW_VERSION = "openclaw-risk-review-v1"


class AccountingCaseType(str, Enum):
    SUPPLIER_INVOICE = "supplier_invoice"
    BANK_RECONCILIATION = "bank_reconciliation"


class RiskSignal(str, Enum):
    DUPLICATE_RISK = "duplicate_risk"
    UNUSUAL_AMOUNT = "unusual_amount"
    UNKNOWN_SUPPLIER = "unknown_supplier"
    CHANGED_BANK_DETAILS = "changed_bank_details"
    UNCLEAR_VAT = "unclear_vat"
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    LOCKED_OLD_PERIOD = "locked_old_period"
    DOCUMENT_AGE_REVIEW = "document_age_review"
    MISSING_SOURCE_DOCUMENT = "missing_source_document"
    POSSIBLE_PERSONAL_EXPENSE = "possible_personal_private_expense"
    MISSING_BUSINESS_PURPOSE = "missing_business_purpose"


class RiskSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True)
class RiskPolicyImpact:
    minimum_permission_mode: str
    required_reviews: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskFinding:
    signal: RiskSignal
    severity: RiskSeverity
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    policy_impact: RiskPolicyImpact = field(
        default_factory=lambda: RiskPolicyImpact("approval_required")
    )
    deterministic: bool = True
    explanation: str | None = None
    review_version: str = RISK_REVIEW_VERSION

    def with_explanation(self, explanation: str | None) -> "RiskFinding":
        if not explanation:
            return self
        return RiskFinding(
            signal=self.signal,
            severity=self.severity,
            message=self.message,
            evidence=dict(self.evidence),
            policy_impact=self.policy_impact,
            deterministic=self.deterministic,
            explanation=explanation,
            review_version=self.review_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.value,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": _jsonable(dict(self.evidence)),
            "policy_impact": self.policy_impact.to_dict(),
            "deterministic": self.deterministic,
            "explanation": self.explanation,
            "review_version": self.review_version,
        }


@dataclass(frozen=True)
class InvoiceHistoryEntry:
    case_id: str
    supplier_id: str | None = None
    supplier_name: str | None = None
    invoice_number: str | None = None
    amount_minor: int | None = None
    source_document_hash: str | None = None
    invoice_date: date | None = None


@dataclass(frozen=True)
class AccountingCase:
    case_id: str
    client_id: str
    case_type: AccountingCaseType = AccountingCaseType.SUPPLIER_INVOICE
    amount_minor: int = 0
    currency: str = "SEK"
    supplier_id: str | None = None
    supplier_name: str | None = None
    supplier_known: bool = True
    invoice_number: str | None = None
    invoice_date: date | None = None
    accounting_period: str | None = None
    period_locked: bool = False
    source_document_id: str | None = None
    source_document_hash: str | None = None
    has_source_document: bool = True
    ocr_confidence: float = 1.0
    vat_confidence: float = 1.0
    vat_amount_minor: int | None = None
    known_supplier_bank_account: str | None = None
    stated_supplier_bank_account: str | None = None
    bank_details_changed: bool = False
    business_purpose: str | None = None
    description: str | None = None
    expense_category: str | None = None
    possible_personal_expense: bool = False
    supplier_amount_history_minor: tuple[int, ...] = ()
    prior_invoices: tuple[InvoiceHistoryEntry, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskReviewConfig:
    duplicate_review_threshold: float = 0.50
    minimum_ocr_confidence: float = 0.85
    minimum_vat_confidence: float = 0.90
    unusual_amount_multiplier: float = 3.0
    unusual_amount_minimum_minor: int = 10_000_00
    old_period_days: int = 60
    require_business_purpose: bool = True
    private_expense_terms: tuple[str, ...] = (
        "private",
        "personal",
        "privat",
        "egen",
        "household",
    )


RiskExplanationProvider = Callable[[AccountingCase, RiskFinding], str | None]


def review_accounting_case(
    accounting_case: AccountingCase,
    *,
    config: RiskReviewConfig | None = None,
    explanation_provider: RiskExplanationProvider | None = None,
    today: date | None = None,
) -> tuple[RiskFinding, ...]:
    """Return deterministic structured risk findings for an accounting case.

    Optional explanations are added only to findings already created by
    deterministic checks. They do not create, remove, or downgrade findings.
    """

    config = config or RiskReviewConfig()
    today = today or date.today()
    _validate_case(accounting_case)

    findings: list[RiskFinding] = []
    duplicate_score, duplicate_evidence = _duplicate_risk(accounting_case)
    if duplicate_score >= config.duplicate_review_threshold:
        findings.append(
            RiskFinding(
                signal=RiskSignal.DUPLICATE_RISK,
                severity=RiskSeverity.WARNING,
                message="Potential duplicate supplier invoice detected.",
                evidence={"duplicate_score": duplicate_score, **duplicate_evidence},
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:duplicate_risk",
                ),
            )
        )

    unusual_evidence = _unusual_amount_evidence(accounting_case, config)
    if unusual_evidence is not None:
        findings.append(
            RiskFinding(
                signal=RiskSignal.UNUSUAL_AMOUNT,
                severity=RiskSeverity.WARNING,
                message="Invoice amount is unusual for this supplier history.",
                evidence=unusual_evidence,
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:unusual_amount",
                ),
            )
        )

    if not accounting_case.supplier_known:
        findings.append(
            RiskFinding(
                signal=RiskSignal.UNKNOWN_SUPPLIER,
                severity=RiskSeverity.WARNING,
                message="Supplier is not known in the available history.",
                evidence={
                    "supplier_id": accounting_case.supplier_id,
                    "supplier_name": accounting_case.supplier_name,
                },
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:unknown_supplier",
                ),
            )
        )

    bank_changed = accounting_case.bank_details_changed
    if (
        accounting_case.known_supplier_bank_account
        and accounting_case.stated_supplier_bank_account
        and accounting_case.known_supplier_bank_account
        != accounting_case.stated_supplier_bank_account
    ):
        bank_changed = True
    if bank_changed:
        findings.append(
            RiskFinding(
                signal=RiskSignal.CHANGED_BANK_DETAILS,
                severity=RiskSeverity.BLOCKER,
                message="Supplier bank details changed or do not match known details.",
                evidence={
                    "known_supplier_bank_account": _masked_account(
                        accounting_case.known_supplier_bank_account
                    ),
                    "stated_supplier_bank_account": _masked_account(
                        accounting_case.stated_supplier_bank_account
                    ),
                    "bank_details_changed": accounting_case.bank_details_changed,
                },
                policy_impact=RiskPolicyImpact(
                    "escalation_required",
                    ("accountant_review", "senior_accountant_review", "security_review"),
                    "risk:changed_bank_details",
                ),
            )
        )

    if accounting_case.vat_confidence < config.minimum_vat_confidence:
        findings.append(
            RiskFinding(
                signal=RiskSignal.UNCLEAR_VAT,
                severity=RiskSeverity.WARNING,
                message="VAT treatment is below the deterministic confidence threshold.",
                evidence={
                    "vat_confidence": accounting_case.vat_confidence,
                    "minimum_vat_confidence": config.minimum_vat_confidence,
                    "vat_amount_minor": accounting_case.vat_amount_minor,
                },
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review", "tax_review"),
                    "risk:unclear_vat",
                ),
            )
        )

    if accounting_case.ocr_confidence < config.minimum_ocr_confidence:
        findings.append(
            RiskFinding(
                signal=RiskSignal.LOW_OCR_CONFIDENCE,
                severity=RiskSeverity.WARNING,
                message="OCR confidence is below the deterministic threshold.",
                evidence={
                    "ocr_confidence": accounting_case.ocr_confidence,
                    "minimum_ocr_confidence": config.minimum_ocr_confidence,
                },
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:low_ocr_confidence",
                ),
            )
        )

    old_period = _old_period_evidence(accounting_case, config, today)
    if accounting_case.period_locked:
        locked_evidence = {
            "period_locked": accounting_case.period_locked,
            "accounting_period": accounting_case.accounting_period,
            **(old_period or {}),
        }
        findings.append(
            RiskFinding(
                signal=RiskSignal.LOCKED_OLD_PERIOD,
                severity=RiskSeverity.BLOCKER,
                message="Accounting period is explicitly locked.",
                evidence=locked_evidence,
                policy_impact=RiskPolicyImpact(
                    "forbidden",
                    (),
                    "risk:locked_old_period",
                ),
            )
        )
    elif old_period is not None:
        findings.append(
            RiskFinding(
                signal=RiskSignal.DOCUMENT_AGE_REVIEW,
                severity=RiskSeverity.WARNING,
                message="Document age exceeds the review threshold; no period lock was asserted.",
                evidence={
                    "period_locked": False,
                    "accounting_period": accounting_case.accounting_period,
                    **old_period,
                },
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:document_age_review",
                ),
            )
        )

    if not accounting_case.has_source_document or not accounting_case.source_document_id:
        findings.append(
            RiskFinding(
                signal=RiskSignal.MISSING_SOURCE_DOCUMENT,
                severity=RiskSeverity.BLOCKER,
                message="Case is missing a source document reference.",
                evidence={
                    "has_source_document": accounting_case.has_source_document,
                    "source_document_id": accounting_case.source_document_id,
                },
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:missing_source_document",
                ),
            )
        )

    private_evidence = _private_expense_evidence(accounting_case, config)
    if private_evidence is not None:
        findings.append(
            RiskFinding(
                signal=RiskSignal.POSSIBLE_PERSONAL_EXPENSE,
                severity=RiskSeverity.WARNING,
                message="Expense may be personal or private.",
                evidence=private_evidence,
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:possible_personal_private_expense",
                ),
            )
        )

    if config.require_business_purpose and not _present(accounting_case.business_purpose):
        findings.append(
            RiskFinding(
                signal=RiskSignal.MISSING_BUSINESS_PURPOSE,
                severity=RiskSeverity.WARNING,
                message="Business purpose is missing.",
                evidence={"business_purpose_present": False},
                policy_impact=RiskPolicyImpact(
                    "approval_required",
                    ("accountant_review",),
                    "risk:missing_business_purpose",
                ),
            )
        )

    if explanation_provider is None or not findings:
        return tuple(findings)

    return tuple(
        finding.with_explanation(explanation_provider(accounting_case, finding))
        for finding in findings
    )


def findings_to_dicts(findings: Sequence[RiskFinding]) -> tuple[dict[str, Any], ...]:
    return tuple(finding.to_dict() for finding in findings)


def max_duplicate_score(findings: Sequence[RiskFinding]) -> float:
    scores = [
        float(finding.evidence.get("duplicate_score", 0.0))
        for finding in findings
        if finding.signal is RiskSignal.DUPLICATE_RISK
    ]
    return max(scores, default=0.0)


def has_signal(findings: Sequence[RiskFinding], signal: RiskSignal) -> bool:
    return any(finding.signal is signal for finding in findings)


def _duplicate_risk(accounting_case: AccountingCase) -> tuple[float, dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    score = 0.0
    for prior in accounting_case.prior_invoices:
        reasons: list[str] = []
        candidate_score = 0.0
        if (
            accounting_case.source_document_hash
            and prior.source_document_hash
            and accounting_case.source_document_hash == prior.source_document_hash
        ):
            reasons.append("same_source_document_hash")
            candidate_score = max(candidate_score, 1.0)
        if (
            _same_supplier(accounting_case, prior)
            and _present(accounting_case.invoice_number)
            and accounting_case.invoice_number == prior.invoice_number
        ):
            reasons.append("same_supplier_invoice_number")
            candidate_score = max(candidate_score, 0.95)
        if (
            _same_supplier(accounting_case, prior)
            and accounting_case.amount_minor
            and prior.amount_minor == accounting_case.amount_minor
            and accounting_case.invoice_date
            and prior.invoice_date == accounting_case.invoice_date
        ):
            reasons.append("same_supplier_amount_and_date")
            candidate_score = max(candidate_score, 0.75)
        if candidate_score:
            matches.append(
                {
                    "case_id": prior.case_id,
                    "score": candidate_score,
                    "reasons": tuple(reasons),
                }
            )
            score = max(score, candidate_score)
    return score, {"matches": tuple(matches)}


def _unusual_amount_evidence(
    accounting_case: AccountingCase,
    config: RiskReviewConfig,
) -> dict[str, Any] | None:
    history = tuple(amount for amount in accounting_case.supplier_amount_history_minor if amount > 0)
    if not history or accounting_case.amount_minor < config.unusual_amount_minimum_minor:
        return None
    baseline = int(median(history))
    if baseline <= 0:
        return None
    multiplier = accounting_case.amount_minor / baseline
    if multiplier < config.unusual_amount_multiplier:
        return None
    return {
        "amount_minor": accounting_case.amount_minor,
        "supplier_median_amount_minor": baseline,
        "multiplier": round(multiplier, 2),
        "history_count": len(history),
        "threshold_multiplier": config.unusual_amount_multiplier,
    }


def _old_period_evidence(
    accounting_case: AccountingCase,
    config: RiskReviewConfig,
    today: date,
) -> dict[str, Any] | None:
    if accounting_case.invoice_date is None:
        return None
    age_days = (today - accounting_case.invoice_date).days
    if age_days <= config.old_period_days:
        return None
    return {
        "invoice_date": accounting_case.invoice_date.isoformat(),
        "age_days": age_days,
        "old_period_days": config.old_period_days,
    }


def findings_from_dicts(items: Sequence[Mapping[str, Any]]) -> tuple[RiskFinding, ...]:
    """Rehydrate serialized findings for the canonical typed policy gate."""

    findings: list[RiskFinding] = []
    for item in items:
        impact_data = item.get("policy_impact")
        if not isinstance(impact_data, Mapping):
            raise ValueError("risk finding policy_impact must be an object")
        findings.append(
            RiskFinding(
                signal=RiskSignal(str(item["signal"])),
                severity=RiskSeverity(str(item["severity"])),
                message=str(item["message"]),
                evidence=dict(item.get("evidence") or {}),
                policy_impact=RiskPolicyImpact(
                    minimum_permission_mode=str(impact_data["minimum_permission_mode"]),
                    required_reviews=tuple(
                        str(review) for review in impact_data.get("required_reviews", ())
                    ),
                    reason=str(impact_data.get("reason") or ""),
                ),
                deterministic=bool(item.get("deterministic", True)),
                explanation=(
                    str(item["explanation"])
                    if item.get("explanation") is not None
                    else None
                ),
                review_version=str(item.get("review_version") or RISK_REVIEW_VERSION),
            )
        )
    return tuple(findings)


def _private_expense_evidence(
    accounting_case: AccountingCase,
    config: RiskReviewConfig,
) -> dict[str, Any] | None:
    if accounting_case.possible_personal_expense:
        return {"explicit_flag": True}
    haystack = " ".join(
        value
        for value in (
            accounting_case.description,
            accounting_case.expense_category,
            accounting_case.business_purpose,
        )
        if value
    ).lower()
    matched = tuple(term for term in config.private_expense_terms if term in haystack)
    if not matched:
        return None
    return {"matched_terms": matched}


def _same_supplier(accounting_case: AccountingCase, prior: InvoiceHistoryEntry) -> bool:
    if accounting_case.supplier_id and prior.supplier_id:
        return accounting_case.supplier_id == prior.supplier_id
    if accounting_case.supplier_name and prior.supplier_name:
        return accounting_case.supplier_name.casefold() == prior.supplier_name.casefold()
    return False


def _masked_account(account: str | None) -> str | None:
    if not account:
        return None
    compact = "".join(char for char in account if char.isalnum())
    if len(compact) <= 4:
        return "****"
    return f"****{compact[-4:]}"


def _present(value: str | None) -> bool:
    return bool(value and value.strip())


def _validate_case(accounting_case: AccountingCase) -> None:
    if not accounting_case.case_id.strip():
        raise ValueError("case_id must not be empty")
    if not accounting_case.client_id.strip():
        raise ValueError("client_id must not be empty")
    if accounting_case.amount_minor < 0:
        raise ValueError("amount_minor must not be negative")
    _validate_confidence("ocr_confidence", accounting_case.ocr_confidence)
    _validate_confidence("vat_confidence", accounting_case.vat_confidence)


def _validate_confidence(name: str, value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value
