"""Evidence-bound human decisions and workpaper export."""

from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from accounting_agent.evidence import EvidenceIntegrityError, HashChainedEventLog

from .integrity import compute_review_context_sha256, validate_golden_case_snapshot


class DecisionAction(str, Enum):
    APPROVE_TREATMENT = "approve_treatment"
    REQUEST_EVIDENCE = "request_evidence"
    REJECT = "reject"


class DecisionError(ValueError):
    """Raised when a decision is not bound to the current evidence snapshot."""


class CloseProofDecisionStore:
    def __init__(self, case: dict[str, Any], events_path: str | Path) -> None:
        if case.get("schema_version") != "closeproof-case-v1":
            raise DecisionError("expected a BalanceDocket v1 case")
        self.case = case
        self.log = HashChainedEventLog(events_path)
        self._assert_case_integrity()

    def _assert_case_integrity(self) -> None:
        try:
            validate_golden_case_snapshot(self.case)
            current_review_context = compute_review_context_sha256(self.case)
        except ValueError as exc:
            raise DecisionError(str(exc)) from exc
        if self.case.get("review_context_sha256") != current_review_context:
            raise DecisionError("case review context failed integrity validation")

    def record(
        self,
        *,
        action: DecisionAction | str,
        rationale: str,
        snapshot_sha256: str,
        review_context_sha256: str,
        finding_id: str,
        actor_id: str = "demo-controller",
    ) -> dict[str, Any]:
        self._assert_case_integrity()
        try:
            action = DecisionAction(action)
        except ValueError as exc:
            raise DecisionError("decision action is invalid") from exc
        rationale = rationale.strip() if isinstance(rationale, str) else ""
        if not 12 <= len(rationale) <= 1000:
            raise DecisionError("rationale must contain 12 to 1000 characters")
        if snapshot_sha256 != self.case["snapshot_sha256"]:
            raise DecisionError("case snapshot changed; refresh before deciding")
        if review_context_sha256 != self.case["review_context_sha256"]:
            raise DecisionError("review context changed; refresh before deciding")
        if finding_id != self.case["finding_id"]:
            raise DecisionError("decision finding does not match the open proof")
        if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 100:
            raise DecisionError("actor id is invalid")
        existing = self.latest()
        if existing is not None and not existing["stale"]:
            raise DecisionError("a current human decision already exists for this review context")
        try:
            event = self.log.append(
                client_id=self.case["entity"]["id"],
                event_type=f"closeproof_{action.value}",
                actor_id=actor_id.strip(),
                object_id=finding_id,
                details={
                    "action": action.value,
                    "rationale_chunks": _split_rationale(rationale),
                    "snapshot_sha256": snapshot_sha256,
                    "review_context_sha256": review_context_sha256,
                    "advisory_payload_sha256": self.case.get("advisory", {})
                    .get("provenance", {})
                    .get("payload_sha256"),
                    "controlled_display_sha256": self.case.get("advisory", {})
                    .get("provenance", {})
                    .get("controlled_display_sha256"),
                    "accounting_action_performed": False,
                    "erp_write_performed": False,
                },
                precondition=self._require_undecided_current_context,
            )
        except EvidenceIntegrityError as exc:
            raise DecisionError("decision event chain failed verification") from exc
        events, verification = self._verified_events()
        if not events or events[-1].event_hash != event.event_hash:
            raise DecisionError("decision event chain changed during validation")
        return self._decision_from_event(events[-1], verification.valid)

    def latest(self) -> dict[str, Any] | None:
        self._assert_case_integrity()
        decision, _verification = self._latest_with_verification()
        return decision

    def _latest_with_verification(self) -> tuple[dict[str, Any] | None, Any]:
        events, verification = self._verified_events()
        if not events:
            return None, verification
        decisions = [
            self._decision_from_event(event, verification.valid) for event in events
        ]
        return decisions[-1], verification

    def _verified_events(self) -> tuple[tuple[Any, ...], Any]:
        verification = self.log.verify()
        if not verification.valid:
            raise DecisionError("decision event chain failed verification")
        try:
            events = self.log.read()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DecisionError("decision event chain failed verification") from exc
        if len(events) != verification.event_count:
            raise DecisionError("decision event chain changed during validation")
        if events and events[-1].event_hash != verification.head_hash:
            raise DecisionError("decision event chain changed during validation")
        return events, verification

    def _decision_from_event(
        self, event: Any, event_chain_valid: bool
    ) -> dict[str, Any]:
        details = event.details
        try:
            action = DecisionAction(details.get("action"))
            rationale = _join_rationale(details)
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionError("persisted decision event is invalid") from exc
        recorded_review_context = details.get("review_context_sha256")
        expected_event_type = f"closeproof_{action.value}"
        expected_provenance = self.case.get("advisory", {}).get("provenance", {})
        if (
            event.client_id != self.case["entity"]["id"]
            or event.event_type != expected_event_type
            or event.object_id != self.case["finding_id"]
            or not isinstance(event.actor_id, str)
            or not event.actor_id.strip()
            or len(event.actor_id) > 100
            or details.get("snapshot_sha256") != self.case["snapshot_sha256"]
            or not _is_sha256(recorded_review_context)
            or details.get("accounting_action_performed") is not False
            or details.get("erp_write_performed") is not False
            or not _is_optional_sha256(details.get("advisory_payload_sha256"))
            or not _is_optional_sha256(details.get("controlled_display_sha256"))
        ):
            raise DecisionError("persisted decision event is invalid")
        if recorded_review_context == self.case["review_context_sha256"] and (
            details.get("advisory_payload_sha256")
            != expected_provenance.get("payload_sha256")
            or details.get("controlled_display_sha256")
            != expected_provenance.get("controlled_display_sha256")
        ):
            raise DecisionError("persisted decision event is invalid")
        stale = recorded_review_context != self.case["review_context_sha256"]
        return {
            "action": action.value,
            "label": _action_label(action),
            "rationale": rationale,
            "actor_id": event.actor_id,
            "finding_id": event.object_id,
            "snapshot_sha256": details["snapshot_sha256"],
            "review_context_sha256": recorded_review_context,
            "event_sequence": event.sequence,
            "event_sha256": event.event_hash,
            "created_at": event.created_at.isoformat(),
            "event_chain_valid": event_chain_valid,
            "stale": stale,
            "accounting_action_performed": details["accounting_action_performed"],
            "erp_write_performed": details["erp_write_performed"],
        }

    def workpaper(self) -> dict[str, Any]:
        self._assert_case_integrity()
        decision, verification = self._latest_with_verification()
        if decision is None:
            raise DecisionError("a current human decision is required before export")
        if decision["stale"]:
            raise DecisionError("human decision is stale for the current review context")
        return {
            "schema_version": "closeproof-workpaper-v1",
            "case_id": self.case["case_id"],
            "entity": self.case["entity"],
            "period": self.case["period"],
            "snapshot_sha256": self.case["snapshot_sha256"],
            "review_context_sha256": self.case["review_context_sha256"],
            "evidence": self.case["evidence"],
            "checks": self.case["checks"],
            "finding": self.case["finding"],
            "advisory": self.case["advisory"],
            "human_decision": decision,
            "event_chain": {
                "valid": verification.valid,
                "event_count": verification.event_count,
                "head_sha256": verification.head_hash,
                "errors": list(verification.errors),
                "semantic_validation_scope": "current_decision",
                "semantically_validated_event_sequence": decision["event_sequence"],
                "semantically_validated_event_sha256": decision["event_sha256"],
            },
            "safety": self.case["safety"],
            "external_actions_performed": [],
        }

    def _require_undecided_current_context(self, events: tuple[Any, ...]) -> None:
        """Enforce one current decision while holding the event-log file lock."""

        if not events:
            return
        decisions = [self._decision_from_event(event, True) for event in events]
        if decisions[-1]["review_context_sha256"] == self.case["review_context_sha256"]:
            raise DecisionError("a current human decision already exists for this review context")

    def write_workpaper(self, path: str | Path) -> Path:
        payload = (
            json.dumps(self.workpaper(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory_descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
        return target


def _action_label(action: DecisionAction) -> str:
    return {
        DecisionAction.APPROVE_TREATMENT: "Treatment approved for workpaper",
        DecisionAction.REQUEST_EVIDENCE: "Additional evidence requested",
        DecisionAction.REJECT: "Proposed treatment rejected",
    }[action]


def _split_rationale(rationale: str) -> list[str]:
    """Keep approved rationale lossless across the generic 240-char log guard."""

    return [rationale[index : index + 200] for index in range(0, len(rationale), 200)]


def _join_rationale(details: dict[str, Any]) -> str:
    chunks = details.get("rationale_chunks")
    if isinstance(chunks, list) and chunks and all(
        isinstance(chunk, str) and 1 <= len(chunk) <= 200 for chunk in chunks
    ):
        rationale = "".join(chunks)
    else:
        rationale = details.get("rationale", "")
    if not isinstance(rationale, str) or not 12 <= len(rationale) <= 1000:
        raise DecisionError("persisted decision rationale is invalid")
    return rationale


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_optional_sha256(value: Any) -> bool:
    return value is None or _is_sha256(value)
