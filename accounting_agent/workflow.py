"""End-to-end local case review workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .audit import AuditEvent, JsonlAuditLog
from .hermes import ApprovalPacket, ProposedAccountingEntry
from .policy import ActionType, PolicyContext, PolicyDecision, evaluate_policy
from .risk_review import (
    AccountingCase,
    RiskExplanationProvider,
    RiskFinding,
    RiskReviewConfig,
    RiskSignal,
    findings_to_dicts,
    has_signal,
    max_duplicate_score,
    review_accounting_case,
)


@dataclass(frozen=True)
class CaseReviewResult:
    accounting_case: AccountingCase
    risk_findings: tuple[RiskFinding, ...]
    policy_decision: PolicyDecision
    approval_packet: ApprovalPacket
    audit_event: AuditEvent | None = None


def review_supplier_invoice_case(
    accounting_case: AccountingCase,
    *,
    action_type: ActionType = ActionType.DRAFT_SUPPLIER_INVOICE,
    source_document: str | None = None,
    extracted_fields: Mapping[str, Any] | None = None,
    proposed_entries: tuple[ProposedAccountingEntry, ...] = (),
    confidence_scores: Mapping[str, float] | None = None,
    proposed_fortnox_action: str | None = None,
    fortnox_payload_summary: Mapping[str, Any] | None = None,
    risk_config: RiskReviewConfig | None = None,
    explanation_provider: RiskExplanationProvider | None = None,
    audit_log: JsonlAuditLog | None = None,
) -> CaseReviewResult:
    """Run Openclaw risk review before policy and Hermes packet finalization."""

    risk_findings = review_accounting_case(
        accounting_case,
        config=risk_config,
        explanation_provider=explanation_provider,
    )
    context = policy_context_from_case(
        accounting_case,
        action_type=action_type,
        risk_findings=risk_findings,
    )
    decision = evaluate_policy(context)
    risk_findings_dicts = findings_to_dicts(risk_findings)
    packet = ApprovalPacket(
        case_id=accounting_case.case_id,
        client_id=accounting_case.client_id,
        source_document=source_document or accounting_case.source_document_id or "missing",
        extracted_fields=dict(extracted_fields or {}),
        proposed_entries=proposed_entries,
        confidence_scores=dict(
            confidence_scores
            or {
                "ocr": accounting_case.ocr_confidence,
                "vat": accounting_case.vat_confidence,
            }
        ),
        risk_flags=tuple(finding.signal.value for finding in risk_findings),
        policy_decision=decision,
        proposed_fortnox_action=proposed_fortnox_action
        or "Prepare a Fortnox draft only after policy and permit requirements are satisfied.",
        fortnox_payload_summary=dict(fortnox_payload_summary or {}),
        risk_findings=risk_findings_dicts,
    )
    event: AuditEvent | None = None
    if audit_log is not None:
        event = audit_log.append_event(
            event_type="openclaw_risk_review_completed",
            case_id=accounting_case.case_id,
            client_id=accounting_case.client_id,
            actor="openclaw",
            action="risk_review",
            details={
                "risk_findings": risk_findings_dicts,
                "policy_mode": decision.permission_mode.value,
                "policy_reasons": decision.reasons,
                "required_reviews": decision.required_reviews,
                "approval_packet_case_id": packet.case_id,
            },
        )
    return CaseReviewResult(
        accounting_case=accounting_case,
        risk_findings=risk_findings,
        policy_decision=decision,
        approval_packet=packet,
        audit_event=event,
    )


def policy_context_from_case(
    accounting_case: AccountingCase,
    *,
    action_type: ActionType,
    risk_findings: tuple[RiskFinding, ...],
) -> PolicyContext:
    return PolicyContext(
        action_type=action_type,
        client_id=accounting_case.client_id,
        currency_code=accounting_case.currency,
        amount_minor=accounting_case.amount_minor,
        supplier_known=accounting_case.supplier_known,
        bank_details_changed=has_signal(risk_findings, RiskSignal.CHANGED_BANK_DETAILS),
        duplicate_risk=max_duplicate_score(risk_findings),
        vat_confidence=accounting_case.vat_confidence,
        ocr_confidence=accounting_case.ocr_confidence,
        period_locked=accounting_case.period_locked,
        new_supplier=not accounting_case.supplier_known,
        risk_findings=risk_findings,
        risk_evidence_complete=True,
    )
