from __future__ import annotations

import hashlib
import shutil
import tempfile
import weakref
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from accounting_agent.approvals import (
    ApprovalOutcome,
    ReviewerIdentity,
    SQLiteApprovalStore,
)
from accounting_agent.permits import (
    InMemoryPermitStore,
    PermitIssuer,
    build_permit_approval_request,
)
from accounting_agent.policy import PolicyContext, evaluate_policy


def issue_test_permit(
    *,
    context: PolicyContext,
    case_id: str,
    payload: Any,
    now: datetime,
    permit_id: str,
    entity_id: str = "synthetic-test-entity",
):
    """Issue a synthetic permit through the real immutable approval bridge."""

    decision = evaluate_policy(context)
    permit_store = InMemoryPermitStore()
    if not decision.required_reviews:
        return (
            PermitIssuer(
                permit_store,
                clock=lambda: now,
                id_factory=lambda: permit_id,
            ).issue(
                decision=decision,
                context=context,
                case_id=case_id,
                entity_id=entity_id,
                payload=payload,
            ),
            decision,
            permit_store,
            None,
        )

    directory = Path(tempfile.mkdtemp())
    store = SQLiteApprovalStore(
        directory / "approvals.sqlite",
        clock=lambda: now,
    )
    store._test_cleanup = weakref.finalize(  # type: ignore[attr-defined]
        store,
        shutil.rmtree,
        directory,
        True,
    )
    request = build_permit_approval_request(
        request_id=f"approval_{permit_id}",
        decision=decision,
        case_id=case_id,
        entity_id=entity_id,
        payload=payload,
        evidence_hashes=(
            hashlib.sha256(f"evidence:{permit_id}".encode("utf-8")).hexdigest(),
        ),
        provider_id="synthetic-dry-run",
        environment="test",
        requestor_id=f"requestor_{permit_id}",
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    for index, role in enumerate(request.required_roles):
        reviewer_id = f"reviewer_{index}_{permit_id}"
        store.register_reviewer(
            ReviewerIdentity(
                reviewer_id=reviewer_id,
                client_id=context.client_id,
                roles=(role,),
                identity_provider="synthetic-test-registry",
                verified=True,
                active=True,
            )
        )
    store.create_request(request)
    for index, role in enumerate(request.required_roles):
        store.record_decision(
            request_id=request.request_id,
            reviewer_id=f"reviewer_{index}_{permit_id}",
            role=role,
            outcome=ApprovalOutcome.APPROVE,
            reason="Synthetic exact-scope test approval.",
            decided_at=now,
        )
    permit = PermitIssuer(
        permit_store,
        approval_authority=store,
        clock=lambda: now,
        id_factory=lambda: permit_id,
    ).issue(
        decision=decision,
        context=context,
        case_id=case_id,
        entity_id=entity_id,
        payload=payload,
        approval_request=request,
    )
    return permit, decision, permit_store, store
