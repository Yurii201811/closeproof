"""Deterministic, side-effect-free period-close control evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .client_identity import canonical_client_id


class CloseStage(str, Enum):
    EVIDENCE_COMPLETENESS = "evidence_completeness"
    BANK_RECONCILIATION = "bank_reconciliation"
    SUBLEDGERS = "subledgers"
    ADJUSTMENTS = "adjustments"
    BALANCED_TRIAL_BALANCE = "balanced_trial_balance"
    VAT_CONTROL = "vat_control"
    PREPARER_REVIEW = "preparer_review"
    INDEPENDENT_SIGNOFF = "independent_signoff"
    LOCK_READINESS = "lock_readiness"


CLOSE_STAGE_ORDER = (
    CloseStage.EVIDENCE_COMPLETENESS,
    CloseStage.BANK_RECONCILIATION,
    CloseStage.SUBLEDGERS,
    CloseStage.ADJUSTMENTS,
    CloseStage.BALANCED_TRIAL_BALANCE,
    CloseStage.VAT_CONTROL,
    CloseStage.PREPARER_REVIEW,
    CloseStage.INDEPENDENT_SIGNOFF,
    CloseStage.LOCK_READINESS,
)


class CloseFactStatus(str, Enum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    UNKNOWN = "unknown"
    REVIEW_REQUIRED = "review_required"


class CloseStageStatus(str, Enum):
    COMPLETE = "complete"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    WAITING = "waiting"


class CloseOutcome(str, Enum):
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    READY_FOR_HUMAN_LOCK = "ready_for_human_lock"


@dataclass(frozen=True)
class PeriodCloseIdentity:
    client_id: str
    entity_id: str
    period: str

    def __post_init__(self) -> None:
        client_id = canonical_client_id(self.client_id)
        entity_id = canonical_client_id(self.entity_id)
        period = self.period
        if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", period):
            raise ValueError("period must be a valid year and month in YYYY-MM format")
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "period", period)


@dataclass(frozen=True)
class CloseVerificationContext:
    """Authoritative verification adapters required by close evaluation."""

    evidence_exists: Callable[[PeriodCloseIdentity, str], bool]
    policy_is_current: Callable[[PeriodCloseIdentity, str], bool]
    signoff_is_authorized: Callable[
        [PeriodCloseIdentity, str, str, str, str, str],
        bool,
    ]

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_exists",
            "policy_is_current",
            "signoff_is_authorized",
        ):
            if not callable(getattr(self, field_name)):
                raise TypeError(f"{field_name} must be callable")


@dataclass(frozen=True)
class CloseFact:
    stage: CloseStage
    status: CloseFactStatus
    evidence_hashes: tuple[str, ...] = ()
    summary: str = ""
    actor_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", CloseStage(self.stage))
        object.__setattr__(self, "status", CloseFactStatus(self.status))
        object.__setattr__(self, "evidence_hashes", tuple(self.evidence_hashes))
        object.__setattr__(self, "summary", self.summary.strip())
        if self.actor_id is not None:
            object.__setattr__(self, "actor_id", self.actor_id.strip() or None)


@dataclass(frozen=True)
class CloseSnapshot:
    identity: PeriodCloseIdentity
    evidence_bundle_hash: str | None
    policy_hash: str | None
    facts: tuple[CloseFact, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", tuple(self.facts))


def compute_close_evidence_bundle_hash(
    identity: PeriodCloseIdentity,
    facts: tuple[CloseFact, ...],
) -> str:
    """Bind the evidence set to the exact client, entity, period, and stage."""

    if not isinstance(identity, PeriodCloseIdentity):
        raise TypeError("identity must be a PeriodCloseIdentity")
    facts = tuple(facts)
    payload = {
        "bundle_version": "close-evidence-v1",
        "client_id": identity.client_id,
        "entity_id": identity.entity_id,
        "period": identity.period,
        "facts": [
            {
                "stage": fact.stage.value,
                "status": fact.status.value,
                "evidence_hashes": list(fact.evidence_hashes),
                "summary": fact.summary,
                "actor_id": fact.actor_id,
            }
            for fact in sorted(
                facts,
                key=lambda item: CLOSE_STAGE_ORDER.index(item.stage),
            )
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CloseBlocker:
    stage: CloseStage
    code: str
    message: str


@dataclass(frozen=True)
class CloseStageAssessment:
    stage: CloseStage
    status: CloseStageStatus
    fact: CloseFact | None
    blockers: tuple[CloseBlocker, ...] = ()
    depends_on: tuple[CloseStage, ...] = ()


@dataclass(frozen=True)
class CloseAssessment:
    identity: PeriodCloseIdentity
    evidence_bundle_hash: str | None
    policy_hash: str | None
    stages: tuple[CloseStageAssessment, ...]
    blockers: tuple[CloseBlocker, ...]
    outcome: CloseOutcome
    ready_for_human_lock: bool
    external_actions_performed: tuple[str, ...] = field(default=(), init=False)
    lock_performed: bool = field(default=False, init=False)


def evaluate_period_close(
    snapshot: CloseSnapshot,
    *,
    verification: CloseVerificationContext | None = None,
) -> CloseAssessment:
    """Evaluate close readiness without posting, locking, or calling an adapter."""

    facts_by_stage: dict[CloseStage, list[CloseFact]] = {
        stage: [] for stage in CLOSE_STAGE_ORDER
    }
    for fact in snapshot.facts:
        facts_by_stage[fact.stage].append(fact)
    snapshot_blockers: list[CloseBlocker] = []
    if verification is None:
        snapshot_blockers.append(
            CloseBlocker(
                CloseStage.EVIDENCE_COMPLETENESS,
                "verification_context_missing",
                "Authoritative evidence, policy, and signoff verification is required.",
            )
        )
    for value, label in (
        (snapshot.evidence_bundle_hash, "evidence_bundle_hash"),
        (snapshot.policy_hash, "policy_hash"),
    ):
        if value is None or not value.strip():
            code = f"{label}_missing"
            message = f"{label.replace('_', ' ').title()} is required."
        elif not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            code = f"{label}_invalid"
            message = f"{label.replace('_', ' ').title()} must be a SHA-256 digest."
        else:
            continue
        snapshot_blockers.append(
            CloseBlocker(CloseStage.EVIDENCE_COMPLETENESS, code, message)
        )

    if (
        verification is not None
        and snapshot.policy_hash is not None
        and re.fullmatch(r"[0-9a-fA-F]{64}", snapshot.policy_hash)
        and not _verified(
            verification.policy_is_current,
            snapshot.identity,
            snapshot.policy_hash,
        )
    ):
        snapshot_blockers.append(
            CloseBlocker(
                CloseStage.EVIDENCE_COMPLETENESS,
                "policy_hash_unverified",
                "The close policy digest is not current for this client, entity, and period.",
            )
        )
    if (
        snapshot.evidence_bundle_hash is not None
        and re.fullmatch(r"[0-9a-fA-F]{64}", snapshot.evidence_bundle_hash)
        and snapshot.evidence_bundle_hash.lower()
        != compute_close_evidence_bundle_hash(snapshot.identity, snapshot.facts)
    ):
        snapshot_blockers.append(
            CloseBlocker(
                CloseStage.EVIDENCE_COMPLETENESS,
                "evidence_bundle_hash_mismatch",
                "The evidence bundle digest does not bind the supplied close facts.",
            )
        )

    if snapshot_blockers:
        stages = tuple(
            CloseStageAssessment(
                stage=stage,
                status=(
                    CloseStageStatus.BLOCKED
                    if index == 0
                    else CloseStageStatus.WAITING
                ),
                fact=facts_by_stage[stage][0] if facts_by_stage[stage] else None,
                blockers=tuple(snapshot_blockers) if index == 0 else (),
                depends_on=(CLOSE_STAGE_ORDER[index - 1],) if index else (),
            )
            for index, stage in enumerate(CLOSE_STAGE_ORDER)
        )
        return CloseAssessment(
            identity=snapshot.identity,
            evidence_bundle_hash=snapshot.evidence_bundle_hash,
            policy_hash=snapshot.policy_hash,
            stages=stages,
            blockers=tuple(snapshot_blockers),
            outcome=CloseOutcome.BLOCKED,
            ready_for_human_lock=False,
        )

    stages_list: list[CloseStageAssessment] = []
    fact_blockers: list[CloseBlocker] = []
    dependency_complete = True
    requires_review = False
    preparer_actor_id: str | None = None
    for index, stage in enumerate(CLOSE_STAGE_ORDER):
        stage_facts = facts_by_stage[stage]
        fact = stage_facts[0] if stage_facts else None
        depends_on = (CLOSE_STAGE_ORDER[index - 1],) if index else ()
        if not dependency_complete:
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.WAITING,
                    fact=fact,
                    depends_on=depends_on,
                )
            )
            continue
        if len(stage_facts) > 1:
            blocker = CloseBlocker(
                stage,
                "fact_duplicate",
                f"The {stage.value.replace('_', ' ')} stage has multiple facts.",
            )
            fact_blockers.append(blocker)
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.BLOCKED,
                    fact=fact,
                    blockers=(blocker,),
                    depends_on=depends_on,
                )
            )
            dependency_complete = False
            continue
        if fact is None:
            blocker = CloseBlocker(
                stage,
                "fact_missing",
                f"The {stage.value.replace('_', ' ')} close fact is required.",
            )
            fact_blockers.append(blocker)
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.BLOCKED,
                    fact=None,
                    blockers=(blocker,),
                    depends_on=depends_on,
                )
            )
            dependency_complete = False
            continue
        if fact.status in {CloseFactStatus.UNKNOWN, CloseFactStatus.FAILED}:
            code = (
                "fact_unknown"
                if fact.status is CloseFactStatus.UNKNOWN
                else "fact_failed"
            )
            blocker = CloseBlocker(
                stage,
                code,
                f"The {stage.value.replace('_', ' ')} close fact is {fact.status.value}.",
            )
            fact_blockers.append(blocker)
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.BLOCKED,
                    fact=fact,
                    blockers=(blocker,),
                    depends_on=depends_on,
                )
            )
            dependency_complete = False
            continue
        if fact.status is CloseFactStatus.REVIEW_REQUIRED:
            blocker = CloseBlocker(
                stage,
                "fact_requires_review",
                f"The {stage.value.replace('_', ' ')} close fact requires human review.",
            )
            fact_blockers.append(blocker)
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.REVIEW_REQUIRED,
                    fact=fact,
                    blockers=(blocker,),
                    depends_on=depends_on,
                )
            )
            dependency_complete = False
            requires_review = True
            continue
        evidence_code: str | None = None
        evidence_message = ""
        if not fact.evidence_hashes:
            evidence_code = "fact_evidence_missing"
            evidence_message = "A satisfied close fact requires supporting evidence."
        elif any(
            not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
            for digest in fact.evidence_hashes
        ):
            evidence_code = "fact_evidence_hash_invalid"
            evidence_message = "Close-fact evidence must use SHA-256 digests."
        elif verification is None or any(
            not _verified(
                verification.evidence_exists,
                snapshot.identity,
                digest,
            )
            for digest in fact.evidence_hashes
        ):
            evidence_code = "fact_evidence_unverified"
            evidence_message = (
                "Close-fact evidence was not verified for this client, entity, and period."
            )
        if evidence_code is not None:
            blocker = CloseBlocker(stage, evidence_code, evidence_message)
            fact_blockers.append(blocker)
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.BLOCKED,
                    fact=fact,
                    blockers=(blocker,),
                    depends_on=depends_on,
                )
            )
            dependency_complete = False
            continue
        identity_code: str | None = None
        identity_message = ""
        if stage is CloseStage.PREPARER_REVIEW:
            if fact.actor_id is None:
                identity_code = "preparer_identity_missing"
                identity_message = "Completed preparer review requires a human actor id."
            else:
                preparer_actor_id = fact.actor_id
        elif stage is CloseStage.INDEPENDENT_SIGNOFF:
            if fact.actor_id is None:
                identity_code = "independent_signoff_identity_missing"
                identity_message = "Completed independent signoff requires a human actor id."
            elif fact.actor_id == preparer_actor_id:
                identity_code = "signoff_not_independent"
                identity_message = "The independent signoff actor must differ from the preparer."
            elif (
                preparer_actor_id is None
                or snapshot.policy_hash is None
                or verification is None
                or not _verified(
                    verification.signoff_is_authorized,
                    snapshot.identity,
                    preparer_actor_id,
                    fact.actor_id,
                    snapshot.policy_hash,
                    snapshot.evidence_bundle_hash,
                    "period_close_ready_for_human_lock",
                )
            ):
                identity_code = "signoff_approval_unverified"
                identity_message = (
                    "Independent close signoff was not verified against the approval policy."
                )
        if identity_code is not None:
            blocker = CloseBlocker(stage, identity_code, identity_message)
            fact_blockers.append(blocker)
            stages_list.append(
                CloseStageAssessment(
                    stage=stage,
                    status=CloseStageStatus.BLOCKED,
                    fact=fact,
                    blockers=(blocker,),
                    depends_on=depends_on,
                )
            )
            dependency_complete = False
            continue
        stages_list.append(
            CloseStageAssessment(
                stage=stage,
                status=CloseStageStatus.COMPLETE,
                fact=fact,
                depends_on=depends_on,
            )
        )
    stages = tuple(stages_list)
    if any(stage.status is CloseStageStatus.BLOCKED for stage in stages):
        outcome = CloseOutcome.BLOCKED
    elif requires_review:
        outcome = CloseOutcome.REVIEW_REQUIRED
    else:
        outcome = CloseOutcome.READY_FOR_HUMAN_LOCK
    return CloseAssessment(
        identity=snapshot.identity,
        evidence_bundle_hash=snapshot.evidence_bundle_hash,
        policy_hash=snapshot.policy_hash,
        stages=stages,
        blockers=tuple(fact_blockers),
        outcome=outcome,
        ready_for_human_lock=outcome is CloseOutcome.READY_FOR_HUMAN_LOCK,
    )


def _verified(callback: Callable[..., bool], *args: object) -> bool:
    try:
        result = callback(*args)
    except Exception:
        return False
    return result is True
