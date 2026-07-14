"""Deterministic bounded-specialist planning for accounting review work."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from .client_identity import canonical_client_id
from .erp import DANGEROUS_CAPABILITIES, ErpProvider, get_erp_profile
from .jurisdictions import get_jurisdiction_pack


class InterfaceMode(str, Enum):
    GUIDED = "guided"
    EXPERT = "expert"


class SpecialistId(str, Enum):
    INTAKE = "intake_and_classification"
    EXTRACTION = "evidence_preserving_extraction"
    RISK = "supplier_duplicate_and_anomaly_risk"
    TAX = "tax_and_jurisdiction_proposal"
    ACCOUNTING = "accounting_entry_proposal"
    RECONCILIATION = "reconciliation_proposal"
    EVIDENCE = "evidence_packet_builder"
    VERIFIER = "independent_verifier"


@dataclass(frozen=True)
class RoleProfile:
    role_id: str
    label: str
    default_mode: InterfaceMode
    focus: tuple[str, ...]
    can_review: bool
    can_approve: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["default_mode"] = self.default_mode.value
        return payload


@dataclass(frozen=True)
class SpecialistDefinition:
    specialist_id: SpecialistId
    purpose: str
    output_type: str
    can_approve: bool = False
    can_elevate_permissions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "specialist_id": self.specialist_id.value,
            "purpose": self.purpose,
            "output_type": self.output_type,
            "can_approve": self.can_approve,
            "can_elevate_permissions": self.can_elevate_permissions,
        }


@dataclass(frozen=True)
class AgentBudget:
    max_specialists: int = 8
    timeout_seconds: int = 300
    max_evidence_items: int = 50
    max_retries_per_specialist: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.max_specialists <= 8:
            raise ValueError("max_specialists must stay between 1 and 8")
        if self.timeout_seconds <= 0 or self.max_evidence_items <= 0:
            raise ValueError("agent budgets must be positive")


@dataclass(frozen=True)
class EvidenceReference:
    """A locator whose owning accounting entity is explicit and validated."""

    entity_id: str
    uri: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", canonical_client_id(self.entity_id))
        if not isinstance(self.uri, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+", self.uri
        ):
            raise ValueError("evidence uri must be a non-empty absolute URI")
        parsed = urlsplit(self.uri)
        if not parsed.scheme or not (parsed.netloc or parsed.path.strip("/")):
            raise ValueError("evidence uri must identify a concrete resource")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("evidence uri must not contain embedded credentials")
        if self.sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError("evidence sha256 must contain exactly 64 hexadecimal characters")
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", self.sha256.lower())

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "uri": self.uri,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class AgentStage:
    stage_id: str
    specialists: tuple[SpecialistId, ...]
    parallel: bool
    depends_on: tuple[str, ...]
    requires_human: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "specialists": [item.value for item in self.specialists],
            "parallel": self.parallel,
            "depends_on": list(self.depends_on),
            "requires_human": self.requires_human,
        }


@dataclass(frozen=True)
class AgenticWorkPlan:
    plan_id: str
    entity_id: str
    jurisdiction_pack: str
    provider: ErpProvider
    role_id: str
    interface_mode: InterfaceMode
    evidence_refs: tuple[EvidenceReference, ...]
    budget: AgentBudget
    permission_ceiling: tuple[str, ...]
    blocked_capabilities: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    stages: tuple[AgentStage, ...]
    coordination_patterns: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", canonical_client_id(self.entity_id))
        if not self.evidence_refs or any(
            not isinstance(item, EvidenceReference) for item in self.evidence_refs
        ):
            raise ValueError("AgenticWorkPlan requires typed evidence references")
        if any(item.entity_id != self.entity_id for item in self.evidence_refs):
            raise ValueError("AgenticWorkPlan evidence must belong to its entity_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "entity_id": self.entity_id,
            "jurisdiction_pack": self.jurisdiction_pack,
            "provider": self.provider.value,
            "role_id": self.role_id,
            "interface_mode": self.interface_mode.value,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "budget": asdict(self.budget),
            "permission_ceiling": list(self.permission_ceiling),
            "blocked_capabilities": list(self.blocked_capabilities),
            "stop_conditions": list(self.stop_conditions),
            "stages": [stage.to_dict() for stage in self.stages],
            "coordination_patterns": list(self.coordination_patterns),
        }


ROLE_PROFILES: dict[str, RoleProfile] = {
    item.role_id: item
    for item in (
        RoleProfile(
            "small_firm_accountant",
            "Small-firm accountant",
            InterfaceMode.GUIDED,
            ("daily_queue", "clear_next_decision", "missing_information"),
            True,
        ),
        RoleProfile(
            "accountant",
            "Accountant",
            InterfaceMode.GUIDED,
            ("transaction_evidence", "coding", "exceptions"),
            True,
        ),
        RoleProfile(
            "senior_accountant",
            "Senior accountant",
            InterfaceMode.EXPERT,
            ("policy_conflicts", "complex_vat", "escalation"),
            True,
        ),
        RoleProfile(
            "financial_controller",
            "Financial controller",
            InterfaceMode.EXPERT,
            ("close", "reconciliation", "completeness", "variance"),
            True,
        ),
        RoleProfile(
            "auditor",
            "Auditor",
            InterfaceMode.EXPERT,
            ("provenance", "decision_history", "control_evidence"),
            True,
        ),
        RoleProfile(
            "agent_operator",
            "Agent operator",
            InterfaceMode.EXPERT,
            ("capability_envelope", "budgets", "traces", "stop_conditions"),
            False,
        ),
    )
}


SPECIALISTS: dict[SpecialistId, SpecialistDefinition] = {
    item.specialist_id: item
    for item in (
        SpecialistDefinition(SpecialistId.INTAKE, "Classify entity-scoped intake.", "intake_proposal"),
        SpecialistDefinition(SpecialistId.EXTRACTION, "Extract fields with evidence references.", "extraction_proposal"),
        SpecialistDefinition(SpecialistId.RISK, "Find supplier, duplicate, bank, and anomaly risks.", "risk_proposal"),
        SpecialistDefinition(SpecialistId.TAX, "Propose effective-dated jurisdiction and tax treatment.", "tax_proposal"),
        SpecialistDefinition(SpecialistId.ACCOUNTING, "Propose accounts, dimensions, and posting-book entries.", "accounting_proposal"),
        SpecialistDefinition(SpecialistId.RECONCILIATION, "Propose explainable open-item matches and residuals.", "reconciliation_proposal"),
        SpecialistDefinition(SpecialistId.EVIDENCE, "Assemble a reviewable evidence packet.", "evidence_packet"),
        SpecialistDefinition(SpecialistId.VERIFIER, "Independently verify provenance, conflicts, and policy alignment.", "verification_result"),
    )
}


def list_role_profiles() -> tuple[RoleProfile, ...]:
    return tuple(ROLE_PROFILES[key] for key in ROLE_PROFILES)


def build_agentic_work_plan(
    *,
    entity_id: str,
    jurisdiction_pack: str = "se-2026",
    provider: ErpProvider | str = ErpProvider.GENERIC_EXCHANGE,
    role_id: str = "accountant",
    interface_mode: InterfaceMode | str | None = None,
    evidence_refs: tuple[EvidenceReference, ...],
    budget: AgentBudget | None = None,
) -> AgenticWorkPlan:
    entity_id = canonical_client_id(entity_id)
    if not evidence_refs:
        raise ValueError("At least one entity-scoped evidence reference is required")
    if any(not isinstance(item, EvidenceReference) for item in evidence_refs):
        raise TypeError("evidence_refs must contain EvidenceReference values")
    if any(item.entity_id != entity_id for item in evidence_refs):
        raise ValueError("Every evidence reference must belong to the plan entity_id")
    if len({(item.entity_id, item.uri, item.sha256) for item in evidence_refs}) != len(
        evidence_refs
    ):
        raise ValueError("Evidence references must be unique within a plan")

    pack = get_jurisdiction_pack(jurisdiction_pack)
    profile = get_erp_profile(provider)
    try:
        role = ROLE_PROFILES[role_id]
    except KeyError as exc:
        raise ValueError(f"Unknown role profile: {role_id}") from exc
    mode = InterfaceMode(interface_mode) if interface_mode else role.default_mode
    resolved_budget = budget or AgentBudget()
    if len(evidence_refs) > resolved_budget.max_evidence_items:
        raise ValueError("Evidence references exceed the plan evidence-item budget")
    selected_specialists = tuple(SpecialistId)[: resolved_budget.max_specialists]
    selected = set(selected_specialists)

    def stage(
        stage_id: str,
        specialists: tuple[SpecialistId, ...],
        *,
        parallel: bool,
        depends_on: tuple[str, ...],
    ) -> AgentStage | None:
        included = tuple(item for item in specialists if item in selected)
        if not included:
            return None
        return AgentStage(stage_id, included, parallel, depends_on)

    stage_items = [
        stage("intake", (SpecialistId.INTAKE,), parallel=False, depends_on=()),
        stage("inspect", (SpecialistId.EXTRACTION, SpecialistId.RISK, SpecialistId.TAX), parallel=True, depends_on=("intake",)),
        stage("propose", (SpecialistId.ACCOUNTING, SpecialistId.RECONCILIATION), parallel=True, depends_on=("inspect",)),
        stage("evidence", (SpecialistId.EVIDENCE,), parallel=False, depends_on=("propose",)),
        stage("verify", (SpecialistId.VERIFIER,), parallel=False, depends_on=("evidence",)),
    ]
    stages = tuple(item for item in stage_items if item is not None)
    dependencies = (stages[-1].stage_id,) if stages else ()
    stages += (AgentStage("human_decision", (), False, dependencies, True),)

    safe_modes = {"local_only", "guarded_read_only"}
    permission_ceiling = tuple(
        declaration.capability.value
        for declaration in profile.capabilities
        if declaration.mode.value in safe_modes
    )
    blocked = tuple(item.value for item in DANGEROUS_CAPABILITIES)
    stop_conditions = (
        "entity_or_evidence_scope_change",
        "schema_validation_failure",
        "missing_or_conflicting_evidence",
        "currency_tax_supplier_or_period_conflict",
        "policy_disagreement",
        "prompt_injection_or_credential_request",
        "budget_or_timeout_reached",
    )
    identity = {
        "entity_id": entity_id,
        "jurisdiction_pack": pack.pack_id,
        "provider": profile.provider.value,
        "role_id": role.role_id,
        "mode": mode.value,
        "evidence_refs": [item.to_dict() for item in evidence_refs],
        "budget": asdict(resolved_budget),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    plan = AgenticWorkPlan(
        plan_id=f"accounting_plan_{digest}",
        entity_id=entity_id,
        jurisdiction_pack=pack.pack_id,
        provider=profile.provider,
        role_id=role.role_id,
        interface_mode=mode,
        evidence_refs=evidence_refs,
        budget=resolved_budget,
        permission_ceiling=permission_ceiling,
        blocked_capabilities=blocked,
        stop_conditions=stop_conditions,
        stages=stages,
        coordination_patterns=(
            "OpenClaw: one entity-scoped queue, policy merge, deny unknown, append-only events",
            "Hermes: human-readable review and missing-information packets",
            "Monitor may stop work but cannot approve or elevate authority",
        ),
    )
    validate_agentic_work_plan(plan)
    return plan


def validate_agentic_work_plan(plan: AgenticWorkPlan) -> None:
    dangerous = {item.value for item in DANGEROUS_CAPABILITIES}
    exposed = dangerous.intersection(plan.permission_ceiling)
    if exposed:
        raise ValueError(f"Agent plan exposes forbidden capabilities: {sorted(exposed)}")
    if not dangerous.issubset(plan.blocked_capabilities):
        raise ValueError("Agent plan must explicitly block every consequential capability")
    if not plan.evidence_refs:
        raise ValueError("Agent plan must retain at least one evidence reference")
    if any(item.entity_id != plan.entity_id for item in plan.evidence_refs):
        raise ValueError("Agent plan contains evidence owned by another entity")
    if len(plan.evidence_refs) > plan.budget.max_evidence_items:
        raise ValueError("Agent plan exceeds its evidence-item budget")
    for stage in plan.stages:
        for specialist_id in stage.specialists:
            specialist = SPECIALISTS[specialist_id]
            if specialist.can_approve or specialist.can_elevate_permissions:
                raise ValueError(f"Unsafe specialist authority: {specialist_id.value}")
    if not plan.stages or plan.stages[-1].stage_id != "human_decision":
        raise ValueError("Every specialist plan must end at a human decision gate")


def agentic_platform_summary() -> dict[str, Any]:
    sample = build_agentic_work_plan(
        entity_id="synthetic_fixture_entity",
        evidence_refs=(
            EvidenceReference(
                entity_id="synthetic_fixture_entity",
                uri="fixture://supplier-invoice",
            ),
            EvidenceReference(
                entity_id="synthetic_fixture_entity",
                uri="fixture://bank-transaction",
            ),
        ),
    )
    return {
        "roles": [role.to_dict() for role in list_role_profiles()],
        "specialists": [SPECIALISTS[key].to_dict() for key in SpecialistId],
        "sample_plan": sample.to_dict(),
        "execution": "deterministic_plan_only_no_model_or_provider_calls",
    }
