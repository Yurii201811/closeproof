"""Fixture-only Bank Reconciliation Autopilot for MVP 2."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from accounting_agent.client_identity import canonical_client_id
from accounting_agent.policy import (
    ActionType,
    PermissionMode,
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
)

from .matching import build_candidates, duplicate_transaction_risks
from .models import BankTransaction, MatchCandidate, MatchTarget, MatchTargetType


PACKET_VERSION = "bank_reconciliation_autopilot_mvp2.v1"
DEFAULT_CLIENT_ID = "fixture_client"


class BankReconciliationPipeline:
    """Generate explainable bank reconciliation proposals from local fixtures."""

    def __init__(
        self,
        output_dir: str | Path | None = ".local/bank_reconciliation_packets",
        *,
        client_id: str = DEFAULT_CLIENT_ID,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else None
        self.client_id = canonical_client_id(client_id)

    def process_fixture_dir(self, fixtures_dir: str | Path) -> list[dict[str, Any]]:
        root = Path(fixtures_dir)
        transactions, targets = load_fixture_catalog(root)
        return self.process(transactions, targets)

    def process(
        self,
        transactions: list[BankTransaction],
        targets: list[MatchTarget],
    ) -> list[dict[str, Any]]:
        now = utc_now()
        duplicate_risks = duplicate_transaction_risks(transactions)
        target_by_id = {target.target_id: target for target in targets}
        candidates_by_transaction = {
            transaction.transaction_id: build_candidates(transaction, targets)
            for transaction in transactions
        }
        selected_target_counts = Counter(
            candidates[0].target_id
            for candidates in candidates_by_transaction.values()
            if candidates
        )
        proposals = []
        for transaction in transactions:
            candidates = candidates_by_transaction[transaction.transaction_id]
            selected = candidates[0] if candidates else None
            selected_target = target_by_id.get(selected.target_id) if selected else None
            proposal = build_reconciliation_proposal(
                now=now,
                client_id=self.client_id,
                transaction=transaction,
                candidates=candidates,
                selected_target=selected_target,
                duplicate_risk=duplicate_risks.get(transaction.transaction_id, 0.0),
                target_reuse_count=(
                    selected_target_counts.get(selected.target_id, 0) if selected else 0
                ),
            )
            packet = proposal.get("approval_packet")
            if packet:
                packet_path = self._write_approval_packet(packet)
                packet["packet_path"] = str(packet_path)
                proposal["approval_packet_path"] = str(packet_path)
            proposals.append(proposal)
        return proposals

    def _write_approval_packet(self, packet: dict[str, Any]) -> Path:
        if not self.output_dir:
            return Path("")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe_case_id = _safe_filename(packet["case"]["case_id"])
        packet_path = self.output_dir / f"{safe_case_id}.bank_reconciliation_packet.json"
        packet_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return packet_path


def load_fixture_catalog(
    fixtures_dir: str | Path,
) -> tuple[list[BankTransaction], list[MatchTarget]]:
    root = Path(fixtures_dir)
    transactions_data = json.loads((root / "bank_transactions.json").read_text(encoding="utf-8"))
    targets_data = json.loads((root / "open_items.json").read_text(encoding="utf-8"))
    transactions = [
        BankTransaction.from_dict(item) for item in transactions_data["transactions"]
    ]
    targets = [MatchTarget.from_dict(item) for item in targets_data["open_items"]]
    return transactions, targets


def build_reconciliation_proposal(
    *,
    now: str,
    client_id: str,
    transaction: BankTransaction,
    candidates: list[MatchCandidate],
    selected_target: MatchTarget | None,
    duplicate_risk: float,
    target_reuse_count: int = 0,
) -> dict[str, Any]:
    selected_candidate = candidates[0] if candidates else None
    case_id = f"br_{transaction.transaction_id}"
    target_reused = target_reuse_count > 1
    risk_flags = _risk_flags(
        transaction,
        selected_candidate,
        selected_target,
        duplicate_risk,
        target_reused=target_reused,
    )
    proposal_decision = _evaluate_proposal_policy(
        client_id=client_id,
        transaction=transaction,
        selected_candidate=selected_candidate,
        selected_target=selected_target,
        duplicate_risk=max(duplicate_risk, 0.85 if target_reused else 0.0),
    )
    matching_decision = evaluate_policy(
        PolicyContext(
            action_type=ActionType.READ_ANALYSIS,
            client_id=client_id,
            currency_code=transaction.currency,
        )
    )
    live_reconciliation_decision = evaluate_policy(
        PolicyContext(
            action_type=ActionType.RECONCILE_BANK_TRANSACTION,
            client_id=client_id,
            currency_code=transaction.currency,
            amount_minor=abs(transaction.amount_minor),
        )
    )
    proposal_status = _proposal_status(
        selected_candidate,
        duplicate_risk,
        target_reused=target_reused,
    )
    payload = _reconciliation_payload(
        case_id=case_id,
        transaction=transaction,
        selected_candidate=selected_candidate,
        selected_target=selected_target,
        proposal_decision=proposal_decision,
    )
    proposal = {
        "packet_version": PACKET_VERSION,
        "generated_at": now,
        "case": {
            "case_id": case_id,
            "client_id": client_id,
            "source": "local_bank_fixture",
            "status": proposal_status,
        },
        "transaction": transaction.to_dict(),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "selected_candidate": selected_candidate.to_dict() if selected_candidate else None,
        "selected_target": selected_target.to_dict() if selected_target else None,
        "confidence": selected_candidate.confidence if selected_candidate else 0.0,
        "explanations": _proposal_explanations(selected_candidate, selected_target, risk_flags),
        "risk": {
            "duplicate_risk": duplicate_risk,
            "target_reuse_count": target_reuse_count,
            "allocation_conflict": target_reused,
            "flags": risk_flags,
            "level": _risk_level(risk_flags, proposal_decision.permission_mode),
        },
        "matching_policy_decision": policy_decision_to_dict(matching_decision),
        "policy_decision": policy_decision_to_dict(proposal_decision),
        "live_reconciliation_policy_decision": policy_decision_to_dict(
            live_reconciliation_decision
        ),
        "required_human_decision": _required_human_decision(
            proposal_decision,
            selected_candidate,
            risk_flags,
        ),
        "reconciliation_payload": payload,
        "audit_events": [
            {
                "event_type": "bank_transaction_loaded",
                "created_at": now,
                "payload": {
                    "case_id": case_id,
                    "transaction_id": transaction.transaction_id,
                    "source": transaction.source,
                },
            },
            {
                "event_type": "bank_reconciliation_proposal_generated",
                "created_at": now,
                "payload": {
                    "case_id": case_id,
                    "policy_mode": proposal_decision.permission_mode.value,
                    "confidence": selected_candidate.confidence if selected_candidate else 0.0,
                    "risk_flags": [flag["code"] for flag in risk_flags],
                    "live_reconciliation_mode": (
                        live_reconciliation_decision.permission_mode.value
                    ),
                },
            },
        ],
    }
    if proposal_decision.permission_mode in {
        PermissionMode.APPROVAL_REQUIRED,
        PermissionMode.ESCALATION_REQUIRED,
        PermissionMode.FORBIDDEN,
    }:
        proposal["approval_packet"] = build_approval_packet(proposal)
    return proposal


def build_approval_packet(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_version": PACKET_VERSION,
        "generated_at": proposal["generated_at"],
        "case": proposal["case"],
        "transaction": proposal["transaction"],
        "selected_candidate": proposal["selected_candidate"],
        "selected_target": proposal["selected_target"],
        "alternatives": proposal["candidates"][1:4],
        "confidence": proposal["confidence"],
        "explanations": proposal["explanations"],
        "risk": proposal["risk"],
        "policy_decision": proposal["policy_decision"],
        "required_human_decision": proposal["required_human_decision"],
        "reconciliation_payload": proposal["reconciliation_payload"],
        "blocked_actions": proposal["reconciliation_payload"]["blocked_actions"],
        "audit_events": proposal["audit_events"],
    }


def policy_decision_to_dict(decision: PolicyDecision) -> dict[str, Any]:
    return {
        "action_type": decision.action_type.value,
        "client_id": decision.client_id,
        "mode": decision.permission_mode.value,
        "policy_version": decision.policy_version,
        "amount_thresholds": {
            "draft_without_review_minor": (
                decision.amount_thresholds.draft_without_review_minor
            ),
            "escalation_required_minor": (
                decision.amount_thresholds.escalation_required_minor
            ),
        },
        "required_reviews": list(decision.required_reviews),
        "reasons": list(decision.reasons),
        "is_external_write": decision.is_external_write,
    }


def _evaluate_proposal_policy(
    *,
    client_id: str,
    transaction: BankTransaction,
    selected_candidate: MatchCandidate | None,
    selected_target: MatchTarget | None,
    duplicate_risk: float,
) -> PolicyDecision:
    supplier_known = True
    customer_known = True
    if selected_target is None:
        supplier_known = transaction.amount_minor >= 0
        customer_known = transaction.amount_minor <= 0
    elif selected_target.target_type is MatchTargetType.SUPPLIER_INVOICE:
        supplier_known = selected_target.counterparty_known
    elif selected_target.target_type is MatchTargetType.CUSTOMER_INVOICE:
        customer_known = selected_target.counterparty_known

    confidence = selected_candidate.confidence if selected_candidate else 0.0
    return evaluate_policy(
        PolicyContext(
            action_type=ActionType.DRAFT_BANK_RECONCILIATION,
            client_id=client_id,
            currency_code=transaction.currency,
            amount_minor=abs(transaction.amount_minor),
            supplier_known=supplier_known,
            customer_known=customer_known,
            duplicate_risk=duplicate_risk,
            ocr_confidence=confidence,
            vat_confidence=1.0,
            bank_details_changed=_bank_details_changed(selected_target),
            new_supplier=not supplier_known and transaction.amount_minor < 0,
            risk_evidence_complete=True,
        )
    )


def _risk_flags(
    transaction: BankTransaction,
    selected_candidate: MatchCandidate | None,
    selected_target: MatchTarget | None,
    duplicate_risk: float,
    *,
    target_reused: bool = False,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if selected_candidate is None:
        flags.append(
            {
                "code": "unknown_transaction",
                "severity": "high",
                "message": "No open invoice, supplier invoice, receipt, or voucher candidate reached the matching threshold.",
            }
        )
        flags.append(
            {
                "code": "unusual_transaction",
                "severity": "high",
                "message": "The transaction needs classification before any reconciliation proposal can be trusted.",
            }
        )
    else:
        for flag in selected_candidate.flags:
            severity = "medium"
            if flag in {"partial_payment", "currency_mismatch", "direction_mismatch"}:
                severity = "high"
            flags.append(
                {
                    "code": flag,
                    "severity": severity,
                    "message": _candidate_flag_message(flag),
                }
            )
        if selected_candidate.confidence < 0.85:
            flags.append(
                {
                    "code": "low_match_confidence",
                    "severity": "medium",
                    "message": "The best match is below the low-risk confidence threshold.",
                }
            )
    if duplicate_risk >= 0.5:
        flags.append(
            {
                "code": "duplicate_looking_transaction",
                "severity": "high",
                "message": (
                    "Another sample bank transaction has the same amount, reference, "
                    "currency, counterparty, and bank account within the review window."
                ),
            }
        )
    if target_reused:
        flags.append(
            {
                "code": "target_already_proposed",
                "severity": "high",
                "message": (
                    "More than one bank transaction points to the same open item; "
                    "residual allocation must be reviewed before reconciliation."
                ),
            }
        )
    if _bank_details_changed(selected_target):
        flags.append(
            {
                "code": "changed_bank_details",
                "severity": "high",
                "message": "The selected supplier item indicates changed bank details.",
            }
        )
    return list({flag["code"]: flag for flag in flags}.values())


def _candidate_flag_message(flag: str) -> str:
    return {
        "partial_payment": "Payment covers only part of the open amount.",
        "amount_mismatch": "Amount does not equal the open item.",
        "small_amount_delta": "Amount is close but not exact.",
        "reference_mismatch": "OCR/reference does not match the open item.",
        "counterparty_mismatch": "Counterparty does not match the open item.",
        "date_distance": "Transaction date is far from the open item date or due date.",
        "currency_mismatch": "Currency differs from the open item.",
        "direction_mismatch": "Payment direction differs from the open item.",
    }.get(flag, flag)


def _proposal_status(
    selected_candidate: MatchCandidate | None,
    duplicate_risk: float,
    *,
    target_reused: bool = False,
) -> str:
    if selected_candidate is None:
        return "unmatched_needs_review"
    if duplicate_risk >= 0.5 or target_reused:
        return "duplicate_review_required"
    if "partial_payment" in selected_candidate.flags:
        return "partial_payment_review_required"
    if selected_candidate.confidence >= 0.95:
        return "exact_match_proposed"
    return "candidate_match_review_required"


def _proposal_explanations(
    selected_candidate: MatchCandidate | None,
    selected_target: MatchTarget | None,
    risk_flags: list[dict[str, Any]],
) -> list[str]:
    if selected_candidate is None:
        return [
            "No candidate passed the matching threshold.",
            "Approval is required before classifying or reconciling this transaction.",
        ]
    explanations = list(selected_candidate.explanations)
    if selected_target:
        explanations.insert(
            0,
            f"Best candidate is {selected_target.target_type.value} {selected_target.target_id}.",
        )
    if risk_flags:
        explanations.append(
            "Policy-relevant flags: "
            + ", ".join(flag["code"] for flag in risk_flags)
            + "."
        )
    return explanations


def _required_human_decision(
    decision: PolicyDecision,
    selected_candidate: MatchCandidate | None,
    risk_flags: list[dict[str, Any]],
) -> str:
    if decision.permission_mode is PermissionMode.DRAFT_ONLY:
        return (
            "No human decision is required for the local proposal, but Fortnox reconciliation remains blocked."
        )
    if decision.permission_mode is PermissionMode.ESCALATION_REQUIRED:
        return (
            "Senior/accounting review must classify the transaction, confirm the match, and decide whether a future guarded draft workflow is appropriate."
        )
    if decision.permission_mode is PermissionMode.FORBIDDEN:
        return "Stop: policy forbids the requested reconciliation action."
    if selected_candidate is None:
        return "Review the bank transaction, classify the counterparty, and choose whether to create a new voucher or request more evidence."
    if any(flag["code"] == "partial_payment" for flag in risk_flags):
        return "Confirm whether the partial payment should be allocated to the selected open item and whether a residual remains open."
    if any(flag["code"] == "duplicate_looking_transaction" for flag in risk_flags):
        return "Check whether this is a true duplicate bank transaction or a valid second payment before any reconciliation."
    if any(flag["code"] == "target_already_proposed" for flag in risk_flags):
        return "Review all transactions proposed for this open item and confirm the residual allocation before reconciliation."
    return "Review the match evidence and approve, reject, or reassign the proposed reconciliation."


def _reconciliation_payload(
    *,
    case_id: str,
    transaction: BankTransaction,
    selected_candidate: MatchCandidate | None,
    selected_target: MatchTarget | None,
    proposal_decision: PolicyDecision,
) -> dict[str, Any]:
    target = selected_target.to_dict() if selected_target else None
    residual_amount_minor = 0
    if selected_target is not None:
        residual_amount_minor = (
            selected_target.expected_amount_minor - transaction.amount_minor
        )
    return {
        "target_adapter": "fortnox_bank_reconciliation_dry_run",
        "dry_run": True,
        "live_api_call": False,
        "posts_bookkeeping": False,
        "reconciles_in_fortnox": False,
        "starts_payment": False,
        "case_id": case_id,
        "proposal_action": _proposal_action(selected_candidate, selected_target),
        "policy_mode": proposal_decision.permission_mode.value,
        "bank_transaction": transaction.to_dict(),
        "matched_target": target,
        "matched_amount_minor": transaction.amount_minor if selected_target else 0,
        "residual_amount_minor": residual_amount_minor if selected_target else None,
        "confidence": selected_candidate.confidence if selected_candidate else 0.0,
        "blocked_from_live_use": True,
        "blocked_reason": (
            "MVP 2 proposes reconciliation only. Fortnox reconciliation, final posting, "
            "supplier invoice approval, payment initiation, and voucher posting remain disabled."
        ),
        "blocked_actions": [
            "auto_reconcile_in_fortnox",
            "post_voucher",
            "approve_supplier_invoice",
            "start_or_approve_payment",
            "send_invoice",
            "change_bank_details",
        ],
    }


def _proposal_action(
    selected_candidate: MatchCandidate | None,
    selected_target: MatchTarget | None,
) -> str:
    if selected_candidate is None or selected_target is None:
        return "none_until_transaction_classified"
    if "partial_payment" in selected_candidate.flags:
        return "prepare_partial_reconciliation_proposal_only"
    if selected_target.target_type is MatchTargetType.VOUCHER:
        return "prepare_voucher_match_proposal_only"
    return f"prepare_{selected_target.target_type.value}_payment_match_proposal_only"


def _risk_level(
    risk_flags: list[dict[str, Any]],
    mode: PermissionMode,
) -> str:
    if mode in {PermissionMode.ESCALATION_REQUIRED, PermissionMode.FORBIDDEN}:
        return "high"
    if any(flag["severity"] == "high" for flag in risk_flags):
        return "high"
    if risk_flags:
        return "medium"
    return "low"


def _bank_details_changed(selected_target: MatchTarget | None) -> bool:
    if selected_target is None:
        return False
    return bool(selected_target.metadata.get("bank_details_changed", False))


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
