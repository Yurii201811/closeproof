"""Integrated, synthetic-only v1 platform declaration and system check."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .accounting.money import Money
from .accounting.proposals import SupplierInvoiceProposal
from .approvals import (
    ApprovalBinding,
    ApprovalOutcome,
    ApprovalRequest,
    ReviewerIdentity,
    ReviewerRole,
    SQLiteApprovalStore,
)
from .autonomy import (
    AUTONOMY_LADDER,
    AutonomyPlan,
    AutonomyRunState,
    CheckpointedAutonomyRunner,
    ProcessorResult,
    SAFE_PERMISSION_CEILING,
    SQLiteAutonomyStore,
    trusted_preparation_processor,
)
from .close import (
    CLOSE_STAGE_ORDER,
    CloseFact,
    CloseFactStatus,
    CloseOutcome,
    CloseSnapshot,
    CloseVerificationContext,
    PeriodCloseIdentity,
    compute_close_evidence_bundle_hash,
    evaluate_period_close,
)
from .connector_contract import (
    ConnectorBinding,
    ConnectorEnvironment,
    ConnectorPage,
    ConnectorReadRequest,
    RetryMetadata,
    assert_v1_preview_registry_safe,
    get_connector_manifest,
    list_connector_manifests,
    raw_snapshot_sha256,
    read_connector_page_guarded,
)
from .evidence import ContentAddressedEvidenceStore, HashChainedEventLog
from .ledger import JournalValidationPolicy
from .model_runtime import (
    DataClassification,
    ModelPurpose,
    ModelRouteRequest,
    ProviderId,
    RouteStatus,
    list_provider_manifests,
    plan_model_route,
)


V1_RELEASE = "1.0.0"


class _SyntheticGuardedReadAdapter:
    """In-memory adapter used only by the zero-network v1 system check."""

    provider_id = "fortnox"
    manifest = get_connector_manifest(provider_id)

    def __init__(self) -> None:
        self.binding = ConnectorBinding(
            "tenant-v1-preview",
            "entity-se-preview",
            ConnectorEnvironment.SANDBOX,
        )
        self.read_calls = 0

    def check_health(self) -> None:
        raise AssertionError("the v1 system check must not call connector health")

    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        self.read_calls += 1
        raw = b'{"records":[{"account":"2440"}]}'
        return ConnectorPage(
            provider_id=self.provider_id,
            binding=request.binding,
            resource=request.resource,
            schema_version=self.manifest.schema_version,
            mapping_version=self.manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(raw),
            records=({"account": "2440"},),
            source_cursor=request.cursor,
            next_cursor="page:2",
            retry=RetryMetadata(1, 1, False),
        )


def build_v1_platform_summary() -> dict[str, Any]:
    """Return the static v1 capability declaration without contacting providers."""

    return {
        "release": V1_RELEASE,
        "market_focus": "Sweden-first, international foundation",
        "accounting_controls": (
            "currency-aware money",
            "balanced double-entry journal",
            "evidence-bound proposals",
            "period and account validation",
        ),
        "trust_controls": (
            "client-scoped content-addressed evidence",
            "hash-chained event history",
            "identity-bound immutable approvals",
            "segregation of duties",
        ),
        "close": {
            "stages": [stage.value for stage in CLOSE_STAGE_ORDER],
            "terminal_state": "ready_for_human_lock",
            "lock_execution_available": False,
        },
        "autonomy": {
            "stages": [stage.value for stage in AUTONOMY_LADDER],
            "permission_ceiling": list(SAFE_PERMISSION_CEILING),
            "terminal_state": "awaiting_human_decision",
        },
        "connectors": [
            {
                "provider_id": manifest.provider_id,
                "display_name": manifest.display_name,
                "lifecycle": manifest.lifecycle.value,
                "dry_run_only": manifest.guard.dry_run_only,
                "read_only": manifest.guard.read_only,
            }
            for manifest in list_connector_manifests()
        ],
        "model_providers": [
            {
                "provider_id": manifest.provider_id.value,
                "label": manifest.label,
                "network_scope": manifest.network_scope.value,
                "enabled_by_default": manifest.enabled_by_default,
                "advisory_only": manifest.advisory_only,
            }
            for manifest in list_provider_manifests()
        ],
        "external_writes": "forbidden",
        "tax_filing": "human decision only; no submission adapter",
        "computer_use": "supervised evidence collection only",
        "data_posture": "synthetic preview; private course material local-only",
    }


def run_v1_synthetic_system_check() -> dict[str, Any]:
    """Exercise every v1 control-plane seam with deterministic synthetic data."""

    now = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)
    evidence_bytes = b"Synthetic supplier invoice: total SEK 125.00"
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    policy_hash = _sha("policy-se-preview-v1")
    proposal_hash = _sha("balanced-synthetic-proposal-v1")
    checks: dict[str, bool] = {}

    checks["money_precision"] = (
        Money.from_major("125.00", "SEK").minor == 12_500
        and Money.from_major("125", "JPY").minor == 125
        and Money.from_major("1.2345", "KWD").minor == 1_235
    )
    amount = Money.from_major("125.00", "SEK")
    proposal = SupplierInvoiceProposal(
        proposal_id="proposal-synthetic-v1",
        case_id="case-synthetic-v1",
        client_id="client-synthetic-v1",
        entity_id="entity-se-preview",
        supplier_id="supplier-synthetic-v1",
        supplier_name="Synthetic Supplier AB",
        invoice_number="INV-SYNTHETIC-V1",
        invoice_date="2026-06-30",
        due_date="2026-07-30",
        currency="SEK",
        net_amount_minor=amount.minor,
        vat_amount_minor=0,
        gross_amount_minor=amount.minor,
        vat_rate_percent=0,
        expense_account="4000",
        description="Synthetic supplier invoice proposal",
        source_document_hash=evidence_hash,
    )
    journal = proposal.to_journal_draft()
    checks["proposal_entity_binding"] = (
        proposal.client_id == "client-synthetic-v1"
        and proposal.entity_id == "entity-se-preview"
        and journal.client_id == proposal.client_id
        and journal.entity_id == proposal.entity_id
    )
    checks["balanced_journal"] = journal.validate(
        JournalValidationPolicy(
            chart_id="synthetic-chart-v1",
            allowed_accounts=frozenset({"2440", "4000"}),
        )
    ).is_valid

    with tempfile.TemporaryDirectory(prefix="accounting-agent-v1-check-") as directory:
        root = Path(directory)
        evidence_store = ContentAddressedEvidenceStore(root / "evidence", clock=lambda: now)
        evidence = evidence_store.put(
            client_id="client-preview",
            content=evidence_bytes,
            media_type="application/pdf",
        )
        checks["evidence_integrity"] = evidence_store.verify(
            client_id="client-preview", record=evidence
        )

        event_log = HashChainedEventLog(root / "events.jsonl", clock=lambda: now)
        event_log.append(
            client_id="client-preview",
            event_type="synthetic.check",
            actor_id="system-check",
            object_id="case-preview",
            details={"evidence_hash": evidence.content_sha256},
        )
        checks["event_chain"] = event_log.verify().valid

        binding = ApprovalBinding(
            client_id="client-preview",
            entity_id="entity-se-preview",
            case_id="case-preview",
            proposal_hash=proposal_hash,
            evidence_hashes=(evidence_hash,),
            policy_hash=policy_hash,
            provider_id="fortnox-dry-run",
            environment="preview",
        )
        request = ApprovalRequest(
            request_id="approval-preview",
            binding=binding,
            action="synthetic_close_signoff",
            requestor_id="preparer-preview",
            required_roles=(ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        approvals = SQLiteApprovalStore(root / "approvals.sqlite")
        for identity in (
            ReviewerIdentity(
                "controller-preview",
                "client-preview",
                (ReviewerRole.CONTROLLER,),
                "synthetic-registry",
                True,
                True,
            ),
            ReviewerIdentity(
                "auditor-preview",
                "client-preview",
                (ReviewerRole.AUDITOR,),
                "synthetic-registry",
                True,
                True,
            ),
        ):
            approvals.register_reviewer(identity)
        approvals.create_request(request)
        approvals.record_decision(
            request_id=request.request_id,
            reviewer_id="controller-preview",
            role=ReviewerRole.CONTROLLER,
            outcome=ApprovalOutcome.APPROVE,
            reason="Synthetic deterministic controls passed.",
            decided_at=now,
        )
        approvals.record_decision(
            request_id=request.request_id,
            reviewer_id="auditor-preview",
            role=ReviewerRole.AUDITOR,
            outcome=ApprovalOutcome.APPROVE,
            reason="Synthetic evidence trace is complete.",
            decided_at=now,
        )
        checks["identity_bound_approvals"] = approvals.verify(request, now=now).valid

        autonomy_store = SQLiteAutonomyStore(root / "autonomy.sqlite")
        autonomy_runner = CheckpointedAutonomyRunner(
            autonomy_store,
            processors={
                stage: trusted_preparation_processor(
                    lambda context: ProcessorResult(
                        summary=f"{context.stage.value} completed on synthetic metadata.",
                        output={"stage": context.stage.value, "synthetic": True},
                    ),
                    environment="preview",
                )
                for stage in AUTONOMY_LADDER
            },
            clock=lambda: now,
        )
        autonomy_run = autonomy_runner.create_run(
            AutonomyPlan(
                plan_id="autonomy-preview",
                client_id="client-preview",
                entity_id="entity-se-preview",
                case_id="case-preview",
                environment="preview",
                data_classification="synthetic",
                evidence_hashes=(evidence_hash,),
            )
        )
        autonomy_report = autonomy_runner.run(
            run_id=autonomy_run, client_id="client-preview"
        )
        checks["checkpointed_autonomy"] = (
            autonomy_report.state is AutonomyRunState.AWAITING_HUMAN_DECISION
        )

    close_facts = tuple(
        CloseFact(
            stage=stage,
            status=CloseFactStatus.SATISFIED,
            evidence_hashes=(evidence_hash,),
            summary=f"Synthetic {stage.value} control satisfied.",
            actor_id=(
                "preparer-preview"
                if stage.value == "preparer_review"
                else "controller-preview"
                if stage.value == "independent_signoff"
                else None
            ),
        )
        for stage in CLOSE_STAGE_ORDER
    )
    close_identity = PeriodCloseIdentity(
        "client-preview",
        "entity-se-preview",
        "2026-06",
    )
    close_snapshot = CloseSnapshot(
        identity=close_identity,
        evidence_bundle_hash=compute_close_evidence_bundle_hash(
            close_identity,
            close_facts,
        ),
        policy_hash=policy_hash,
        facts=close_facts,
    )
    close_assessment = evaluate_period_close(
        close_snapshot,
        verification=CloseVerificationContext(
            evidence_exists=lambda identity, digest: (
                identity == close_identity and digest == evidence_hash
            ),
            policy_is_current=lambda identity, digest: (
                identity == close_identity and digest == policy_hash
            ),
            signoff_is_authorized=lambda identity, preparer, reviewer, digest, bundle, action: (
                identity == close_identity
                and preparer == "preparer-preview"
                and reviewer == "controller-preview"
                and digest == policy_hash
                and bundle == close_snapshot.evidence_bundle_hash
                and action == "period_close_ready_for_human_lock"
            ),
        ),
    )
    checks["period_close_controls"] = (
        close_assessment.outcome is CloseOutcome.READY_FOR_HUMAN_LOCK
        and not close_assessment.lock_performed
    )

    assert_v1_preview_registry_safe()
    checks["connector_write_guards"] = True
    connector = _SyntheticGuardedReadAdapter()
    connector_request = ConnectorReadRequest(
        binding=connector.binding,
        resource="accounts",
        cursor="page:1",
        page_size=1,
    )
    connector_page = read_connector_page_guarded(connector, connector_request)
    checks["connector_read_gateway"] = (
        connector.read_calls == 1
        and connector_page.provider_id == "fortnox"
        and connector_page.binding == connector_request.binding
        and connector_page.resource == connector_request.resource
        and len(connector_page.records) == 1
    )
    local_route = plan_model_route(
        ModelRouteRequest(
            request_id="route-local-preview",
            purpose=ModelPurpose.EXPLANATION,
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            preferred_provider=ProviderId.OLLAMA,
        )
    )
    hosted_route = plan_model_route(
        ModelRouteRequest(
            request_id="route-hosted-preview",
            purpose=ModelPurpose.EXPLANATION,
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            preferred_provider=ProviderId.OPENAI,
        )
    )
    checks["model_routing_guards"] = (
        local_route.status is RouteStatus.ROUTED
        and hosted_route.status is RouteStatus.BLOCKED
    )

    return {
        "release": V1_RELEASE,
        "passed": all(checks.values()),
        "checks": checks,
        "autonomy_terminal": autonomy_report.state.value,
        "close_terminal": close_assessment.outcome.value,
        "external_calls": 0,
        "hosted_model_calls": 0,
        "erp_writes": 0,
    }


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
