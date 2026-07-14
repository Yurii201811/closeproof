"""Hermes approval packets and communication drafts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .audit import AuditEvent, JsonlAuditLog
from .policy import ActionType, PolicyDecision


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    MISSING_INFO = "missing_info"


class MissingInfoReason(str, Enum):
    MISSING_RECEIPT = "missing_receipt"
    UNCLEAR_BUSINESS_PURPOSE = "unclear_business_purpose"
    UNKNOWN_SUPPLIER = "unknown_supplier"
    CHANGED_BANK_DETAILS_CONFIRMATION = "changed_bank_details_confirmation"
    VAT_UNCERTAINTY = "vat_uncertainty"


@dataclass(frozen=True)
class ProposedAccountingEntry:
    account: str
    description: str
    debit_minor: int = 0
    credit_minor: int = 0
    vat_code: str | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class ApprovalPacket:
    case_id: str
    client_id: str
    source_document: str
    extracted_fields: Mapping[str, Any]
    proposed_entries: tuple[ProposedAccountingEntry, ...]
    confidence_scores: Mapping[str, float]
    risk_flags: tuple[str, ...]
    policy_decision: PolicyDecision
    proposed_fortnox_action: str
    fortnox_payload_summary: Mapping[str, Any] = field(default_factory=dict)
    risk_findings: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MissingInfoEmailDraft:
    case_id: str
    client_id: str
    reason: MissingInfoReason
    subject: str
    body: str
    send_status: str = "draft_only_not_sent"
    to_address: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "client_id": self.client_id,
            "reason": self.reason.value,
            "subject": self.subject,
            "body": self.body,
            "send_status": self.send_status,
            "to_address": self.to_address,
        }


def render_approval_packet(packet: ApprovalPacket) -> str:
    """Render a readable accountant-facing Markdown approval packet."""

    lines: list[str] = [
        f"# Approval packet: {packet.case_id}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Case id | `{_md(packet.case_id)}` |",
        f"| Client id | `{_md(packet.client_id)}` |",
        f"| Source document | {_md(packet.source_document)} |",
        f"| Policy decision | `{packet.policy_decision.permission_mode.value}` |",
        "",
        "## What happened",
        "",
        "A supplier invoice was processed into a draft accounting proposal. No email has been sent and no final Fortnox write has been approved from this packet.",
        "",
        "## Extracted fields",
        "",
    ]

    lines.extend(_mapping_table(packet.extracted_fields))
    lines.extend(
        [
            "",
            "## Proposed accounting entries",
            "",
            "| Account | Description | Debit | Credit | VAT | Evidence |",
            "| --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    if packet.proposed_entries:
        for entry in packet.proposed_entries:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{_md(entry.account)}`",
                        _md(entry.description),
                        _format_minor(entry.debit_minor),
                        _format_minor(entry.credit_minor),
                        _md(entry.vat_code or "-"),
                        _md(entry.evidence or "-"),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | No entries proposed | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Confidence scores",
            "",
        ]
    )
    lines.extend(_confidence_table(packet.confidence_scores))

    lines.extend(
        [
            "",
            "## Risk flags",
            "",
        ]
    )
    if packet.risk_flags:
        lines.extend(f"- {_humanize(flag)}" for flag in packet.risk_flags)
    else:
        lines.append("- No special risk flags found.")

    lines.extend(["", "## Structured risk findings", ""])
    if packet.risk_findings:
        lines.extend(
            [
                "| Signal | Severity | Policy impact | Evidence | Explanation |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in packet.risk_findings:
            policy_impact = finding.get("policy_impact", {})
            impact_value = (
                policy_impact.get("minimum_permission_mode", "-")
                if isinstance(policy_impact, Mapping)
                else "-"
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md(_format_value(finding.get("signal", "-"))),
                        _md(_format_value(finding.get("severity", "-"))),
                        _md(_format_value(impact_value)),
                        _md(_format_value(finding.get("evidence", {}))),
                        _md(_format_value(finding.get("explanation") or "-")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- No structured risk findings.")

    decision = packet.policy_decision
    lines.extend(
        [
            "",
            "## Policy decision",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Mode | `{decision.permission_mode.value}` |",
            f"| Required reviews | {_join_or_dash(decision.required_reviews)} |",
            f"| Reasons | {_join_or_dash(decision.reasons)} |",
            f"| Policy version | `{_md(decision.policy_version)}` |",
            "",
            "## Exact proposed Fortnox action",
            "",
            f"- Action: `{_md(packet.policy_decision.action_type.value)}`",
            f"- Next step: {_md(packet.proposed_fortnox_action)}",
        ]
    )
    if packet.fortnox_payload_summary:
        lines.extend(["", "| Payload field | Value |", "| --- | --- |"])
        for key, value in packet.fortnox_payload_summary.items():
            lines.append(f"| {_md(str(key))} | {_md(_format_value(value))} |")

    lines.extend(
        [
            "",
            "## Review options",
            "",
            "| Decision | Use when | Result |",
            "| --- | --- | --- |",
            "| `approve` | The proposal is correct and required reviews are complete. | Record approval; a separate permit is still needed before any Fortnox draft write. |",
            "| `reject` | The proposal is wrong or unsupported. | Record rejection and keep the case blocked. |",
            "| `escalate` | Senior, tax, security, or client-responsible review is needed. | Record escalation and do not write externally. |",
            "| `missing_info` | The client or supplier must clarify something first. | Record missing information and use a draft email only. |",
            "",
        ]
    )
    return "\n".join(lines)


def write_approval_packet(packet: ApprovalPacket, folder: str | Path) -> Path:
    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    packet_path = folder_path / f"{_safe_filename(packet.case_id)}.md"
    packet_path.write_text(render_approval_packet(packet), encoding="utf-8")
    return packet_path


def draft_missing_info_email(
    *,
    case_id: str,
    client_id: str,
    reason: MissingInfoReason | str,
    supplier_name: str | None = None,
    document_label: str | None = None,
    recipient_name: str | None = None,
    to_address: str | None = None,
) -> MissingInfoEmailDraft:
    """Create a client-facing email draft. This never sends email."""

    reason = MissingInfoReason(reason)
    supplier = supplier_name or "the supplier"
    document = document_label or "the document"
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"

    if reason is MissingInfoReason.MISSING_RECEIPT:
        subject = f"Missing receipt for {supplier}"
        body = (
            f"{greeting}\n\n"
            f"Could you send the receipt for {document}? I need it before I can book the cost correctly.\n\n"
            "Thanks"
        )
    elif reason is MissingInfoReason.UNCLEAR_BUSINESS_PURPOSE:
        subject = f"Business purpose for {supplier}"
        body = (
            f"{greeting}\n\n"
            f"What was the business purpose for {document}? A short note is enough.\n\n"
            "Thanks"
        )
    elif reason is MissingInfoReason.UNKNOWN_SUPPLIER:
        subject = f"Can you confirm {supplier}?"
        body = (
            f"{greeting}\n\n"
            f"I do not recognise {supplier} from the current supplier records. Can you confirm what this purchase relates to before I book it?\n\n"
            "Thanks"
        )
    elif reason is MissingInfoReason.CHANGED_BANK_DETAILS_CONFIRMATION:
        subject = f"Please confirm bank details for {supplier}"
        body = (
            f"{greeting}\n\n"
            f"The bank details for {supplier} look changed. Can you confirm the new details through your usual secure channel? I will not update bank details or prepare payment before that is confirmed.\n\n"
            "Thanks"
        )
    else:
        subject = f"VAT question for {supplier}"
        body = (
            f"{greeting}\n\n"
            f"The VAT treatment on {document} is unclear. Can you confirm whether VAT should be claimed, or send the invoice details that show it?\n\n"
            "Thanks"
        )

    return MissingInfoEmailDraft(
        case_id=case_id,
        client_id=client_id,
        reason=reason,
        subject=subject,
        body=body,
        to_address=to_address,
    )


def render_email_draft(draft: MissingInfoEmailDraft) -> str:
    to_line = draft.to_address or "[not set]"
    return "\n".join(
        [
            f"# Email draft: {draft.case_id}",
            "",
            f"- Client id: `{_md(draft.client_id)}`",
            f"- Reason: `{draft.reason.value}`",
            f"- Send status: `{draft.send_status}`",
            f"- To: {_md(to_line)}",
            f"- Subject: {_md(draft.subject)}",
            "",
            "## Body",
            "",
            draft.body,
            "",
        ]
    )


def record_approval_decision(
    *,
    packet: ApprovalPacket,
    decision: ReviewDecision | str,
    audit_log: JsonlAuditLog,
    actor: str,
    note: str | None = None,
) -> AuditEvent:
    review_decision = ReviewDecision(decision)
    return audit_log.append_event(
        event_type="approval_decision",
        case_id=packet.case_id,
        client_id=packet.client_id,
        actor=actor,
        action=review_decision.value,
        details={
            "source_document": packet.source_document,
            "policy_mode": packet.policy_decision.permission_mode.value,
            "required_reviews": packet.policy_decision.required_reviews,
            "risk_flags": packet.risk_flags,
            "risk_findings": packet.risk_findings,
            "proposed_fortnox_action": packet.proposed_fortnox_action,
            "note": note or "",
        },
    )


def _mapping_table(mapping: Mapping[str, Any]) -> list[str]:
    lines = ["| Field | Value |", "| --- | --- |"]
    if not mapping:
        lines.append("| - | No fields extracted |")
        return lines
    for key, value in mapping.items():
        lines.append(f"| {_md(str(key))} | {_md(_format_value(value))} |")
    return lines


def _confidence_table(scores: Mapping[str, float]) -> list[str]:
    lines = ["| Signal | Score |", "| --- | ---: |"]
    if not scores:
        lines.append("| - | - |")
        return lines
    for key, score in scores.items():
        lines.append(f"| {_md(str(key))} | {_format_confidence(score)} |")
    return lines


def _format_confidence(score: float) -> str:
    return f"{score:.0%}"


def _format_minor(amount_minor: int) -> str:
    if amount_minor == 0:
        return "-"
    sign = "-" if amount_minor < 0 else ""
    absolute = abs(amount_minor)
    return f"{sign}{absolute // 100:,}.{absolute % 100:02d}"


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Enum):
        return value.value
    if dataclass_is_instance(value):
        return _format_value(asdict(value))
    if isinstance(value, Mapping):
        return ", ".join(f"{key}: {_format_value(item)}" for key, item in value.items())
    if isinstance(value, tuple | list):
        return ", ".join(_format_value(item) for item in value)
    return str(value)


def _join_or_dash(values: tuple[str, ...]) -> str:
    if not values:
        return "-"
    return ", ".join(f"`{_md(value)}`" for value in values)


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "approval-packet"


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def dataclass_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__") and not isinstance(value, type)
