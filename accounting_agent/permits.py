"""Execution permits for policy-approved external writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .approvals import (
    ApprovalBinding,
    ApprovalRequest,
    ApprovalVerification,
    ReviewerRole,
)
from .client_identity import canonical_client_id
from .policy import (
    EXTERNAL_WRITE_ACTIONS,
    ActionType,
    PermissionMode,
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
)


class PermitError(Exception):
    """Base class for execution permit failures."""


class PermitForbidden(PermitError):
    """Raised when a forbidden policy decision is used to request a permit."""


class PermitReviewRequired(PermitError):
    """Raised when required reviews have not been supplied."""


class PermitValidationError(PermitError):
    """Raised when an execution permit does not match the attempted write."""


class TrustedApprovalAuthority(Protocol):
    """Narrow trust boundary used to reload and verify an exact approval request."""

    def verify(
        self,
        expected_request: ApprovalRequest,
        *,
        now: datetime,
    ) -> ApprovalVerification:
        ...

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        ...


@dataclass(frozen=True)
class PermitApprovalReceipt:
    """Verified approval material embedded in a reviewed execution permit."""

    request_id: str
    binding_digest: str
    request_digest: str
    client_id: str
    entity_id: str
    case_id: str
    action: str
    payload_hash: str
    policy_hash: str
    decision_ids: tuple[str, ...]
    verified_at: datetime

    def __post_init__(self) -> None:
        if not self.request_id or self.request_id != self.request_id.strip():
            raise ValueError("approval receipt request_id must be canonical")
        _require_sha256(self.binding_digest, "approval receipt binding_digest")
        _require_sha256(self.request_digest, "approval receipt request_digest")
        if canonical_client_id(self.client_id) != self.client_id:
            raise ValueError("approval receipt client_id must be canonical")
        if canonical_client_id(self.entity_id) != self.entity_id:
            raise ValueError("approval receipt entity_id must be canonical")
        for name, value in (("case_id", self.case_id), ("action", self.action)):
            if not value or value != value.strip():
                raise ValueError(f"approval receipt {name} must be canonical")
        _require_sha256(self.payload_hash, "approval receipt payload_hash")
        _require_sha256(self.policy_hash, "approval receipt policy_hash")
        if not self.decision_ids or len(set(self.decision_ids)) != len(self.decision_ids):
            raise ValueError("approval receipt decision_ids must be non-empty and unique")
        if any(not item or item != item.strip() for item in self.decision_ids):
            raise ValueError("approval receipt decision_ids must be canonical")
        _require_aware(self.verified_at, "approval receipt verified_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "binding_digest": self.binding_digest,
            "request_digest": self.request_digest,
            "client_id": self.client_id,
            "entity_id": self.entity_id,
            "case_id": self.case_id,
            "action": self.action,
            "payload_hash": self.payload_hash,
            "policy_hash": self.policy_hash,
            "decision_ids": list(self.decision_ids),
            "verified_at": self.verified_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermitApprovalReceipt":
        return cls(
            request_id=str(data["request_id"]),
            binding_digest=str(data["binding_digest"]),
            request_digest=str(data["request_digest"]),
            client_id=str(data["client_id"]),
            entity_id=str(data["entity_id"]),
            case_id=str(data["case_id"]),
            action=str(data["action"]),
            payload_hash=str(data["payload_hash"]),
            policy_hash=str(data["policy_hash"]),
            decision_ids=tuple(str(value) for value in data["decision_ids"]),
            verified_at=_parse_datetime(data["verified_at"]),
        )


_POLICY_REVIEW_ROLES = {
    "accountant_review": ReviewerRole.REVIEWER,
    "senior_accountant_review": ReviewerRole.CONTROLLER,
    "client_responsible_review": ReviewerRole.CLIENT_RESPONSIBLE,
    "tax_review": ReviewerRole.TAX_REVIEWER,
    "security_review": ReviewerRole.SECURITY_REVIEWER,
}


def canonical_policy_decision_hash(decision: PolicyDecision) -> str:
    """Hash every permit-relevant field of a deterministic policy decision."""

    return canonical_payload_hash(
        {
            "action_type": decision.action_type.value,
            "client_id": decision.client_id,
            "currency_code": decision.currency_code,
            "permission_mode": decision.permission_mode.value,
            "policy_version": decision.policy_version,
            "amount_thresholds": _to_jsonable(decision.amount_thresholds),
            "required_reviews": list(decision.required_reviews),
            "reasons": list(decision.reasons),
            "is_external_write": decision.is_external_write,
        }
    )


def build_permit_approval_request(
    *,
    request_id: str,
    decision: PolicyDecision,
    case_id: str,
    entity_id: str,
    payload: Any,
    evidence_hashes: tuple[str, ...],
    provider_id: str,
    environment: str,
    requestor_id: str,
    created_at: datetime,
    expires_at: datetime,
) -> ApprovalRequest:
    """Build the exact immutable approval request required by :class:`PermitIssuer`."""

    roles: list[ReviewerRole] = []
    for review in decision.required_reviews:
        role = _POLICY_REVIEW_ROLES.get(review)
        if role is None:
            raise PermitReviewRequired(f"unsupported policy review type: {review}")
        if role in roles:
            raise PermitReviewRequired(
                "policy review types cannot be represented by independent approval roles"
            )
        roles.append(role)
    if not roles:
        raise PermitReviewRequired(
            "approval requests are only valid for decisions that require review"
        )
    return ApprovalRequest(
        request_id=request_id,
        binding=ApprovalBinding(
            client_id=decision.client_id,
            entity_id=entity_id,
            case_id=case_id,
            proposal_hash=canonical_payload_hash(payload),
            evidence_hashes=evidence_hashes,
            policy_hash=canonical_policy_decision_hash(decision),
            provider_id=provider_id,
            environment=environment,
        ),
        action=decision.action_type.value,
        requestor_id=requestor_id,
        required_roles=tuple(roles),
        created_at=created_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ExecutionPermit:
    permit_id: str
    case_id: str
    client_id: str
    allowed_action: ActionType
    payload_hash: str
    policy_version: str
    required_reviews: tuple[str, ...]
    permission_mode: PermissionMode
    expires_at: datetime
    idempotency_key: str
    issued_at: datetime
    entity_id: str | None = None
    policy_decision_hash: str | None = None
    approval_receipt: PermitApprovalReceipt | None = None
    approved_reviews: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_action"] = self.allowed_action.value
        data["permission_mode"] = self.permission_mode.value
        data["expires_at"] = self.expires_at.isoformat()
        data["issued_at"] = self.issued_at.isoformat()
        data["approval_receipt"] = (
            self.approval_receipt.to_dict() if self.approval_receipt is not None else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionPermit":
        return cls(
            permit_id=str(data["permit_id"]),
            case_id=str(data["case_id"]),
            client_id=str(data["client_id"]),
            allowed_action=ActionType(data["allowed_action"]),
            payload_hash=str(data["payload_hash"]),
            policy_version=str(data["policy_version"]),
            required_reviews=tuple(data.get("required_reviews", ())),
            permission_mode=PermissionMode(data["permission_mode"]),
            expires_at=_parse_datetime(data["expires_at"]),
            idempotency_key=str(data["idempotency_key"]),
            issued_at=_parse_datetime(data["issued_at"]),
            entity_id=(str(data["entity_id"]) if data.get("entity_id") else None),
            policy_decision_hash=(
                str(data["policy_decision_hash"])
                if data.get("policy_decision_hash")
                else None
            ),
            approval_receipt=(
                PermitApprovalReceipt.from_dict(data["approval_receipt"])
                if data.get("approval_receipt")
                else None
            ),
            approved_reviews=tuple(data.get("approved_reviews", ())),
        )


class PermitStore(Protocol):
    def save(self, permit: ExecutionPermit) -> None:
        ...

    def get(self, permit_id: str) -> ExecutionPermit | None:
        ...


class InMemoryPermitStore:
    def __init__(self) -> None:
        self._permits: dict[str, ExecutionPermit] = {}

    def save(self, permit: ExecutionPermit) -> None:
        _require_permit_entity(permit)
        _require_permit_policy_hash(permit)
        self._permits[permit.permit_id] = permit

    def get(self, permit_id: str) -> ExecutionPermit | None:
        return self._permits.get(permit_id)


class SQLitePermitStore:
    """Small SQLite-compatible permit store for local development and tests."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._ensure_schema()

    def save(self, permit: ExecutionPermit) -> None:
        _require_permit_entity(permit)
        _require_permit_policy_hash(permit)
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO execution_permits (
                        permit_id,
                        case_id,
                        client_id,
                        allowed_action,
                        payload_hash,
                        policy_version,
                        required_reviews,
                        permission_mode,
                        expires_at,
                        idempotency_key,
                        issued_at,
                        entity_id,
                        policy_decision_hash,
                        approval_receipt,
                        approved_reviews
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        permit.permit_id,
                        permit.case_id,
                        permit.client_id,
                        permit.allowed_action.value,
                        permit.payload_hash,
                        permit.policy_version,
                        json.dumps(list(permit.required_reviews), separators=(",", ":")),
                        permit.permission_mode.value,
                        permit.expires_at.isoformat(),
                        permit.idempotency_key,
                        permit.issued_at.isoformat(),
                        permit.entity_id,
                        permit.policy_decision_hash,
                        (
                            json.dumps(
                                permit.approval_receipt.to_dict(),
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            if permit.approval_receipt is not None
                            else None
                        ),
                        json.dumps(list(permit.approved_reviews), separators=(",", ":")),
                    ),
                )

    def get(self, permit_id: str) -> ExecutionPermit | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT *
                FROM execution_permits
                WHERE permit_id = ?
                """,
                (permit_id,),
            ).fetchone()
        if row is None:
            return None
        return ExecutionPermit.from_dict(
            {
                "permit_id": row["permit_id"],
                "case_id": row["case_id"],
                "client_id": row["client_id"],
                "allowed_action": row["allowed_action"],
                "payload_hash": row["payload_hash"],
                "policy_version": row["policy_version"],
                "required_reviews": tuple(json.loads(row["required_reviews"])),
                "permission_mode": row["permission_mode"],
                "expires_at": row["expires_at"],
                "idempotency_key": row["idempotency_key"],
                "issued_at": row["issued_at"],
                "entity_id": row["entity_id"],
                "policy_decision_hash": row["policy_decision_hash"],
                "approval_receipt": (
                    json.loads(row["approval_receipt"])
                    if row["approval_receipt"] is not None
                    else None
                ),
                "approved_reviews": tuple(json.loads(row["approved_reviews"])),
            }
        )

    def _ensure_schema(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_permits (
                        permit_id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        allowed_action TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        required_reviews TEXT NOT NULL,
                        permission_mode TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        issued_at TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        policy_decision_hash TEXT NOT NULL,
                        approval_receipt TEXT,
                        approved_reviews TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(execution_permits)"
                    ).fetchall()
                }
                if "entity_id" not in columns:
                    connection.execute(
                        "ALTER TABLE execution_permits ADD COLUMN entity_id TEXT"
                    )
                if "approval_receipt" not in columns:
                    connection.execute(
                        "ALTER TABLE execution_permits ADD COLUMN approval_receipt TEXT"
                    )
                if "policy_decision_hash" not in columns:
                    connection.execute(
                        "ALTER TABLE execution_permits ADD COLUMN policy_decision_hash TEXT"
                    )


class PermitIssuer:
    def __init__(
        self,
        store: PermitStore | None = None,
        *,
        clock: Any | None = None,
        id_factory: Any | None = None,
        ttl: timedelta = timedelta(minutes=30),
        approval_authority: TrustedApprovalAuthority | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or _utc_now
        self.id_factory = id_factory or (lambda: f"permit_{uuid.uuid4().hex}")
        self.ttl = ttl
        self.approval_authority = approval_authority

    def issue(
        self,
        *,
        decision: PolicyDecision,
        context: PolicyContext,
        case_id: str,
        payload: Any,
        entity_id: str | None = None,
        approval_request: ApprovalRequest | None = None,
        approved_reviews: tuple[str, ...] = (),
    ) -> ExecutionPermit:
        if decision.permission_mode is PermissionMode.FORBIDDEN:
            raise PermitForbidden("forbidden policy decisions cannot receive execution permits")
        if decision.action_type != context.action_type:
            raise PermitValidationError("policy decision action does not match policy context")
        if decision.client_id != context.client_id:
            raise PermitValidationError("policy decision client does not match policy context")
        _require_current_policy_decision(decision, context)
        if entity_id is None:
            raise PermitValidationError("execution permits require an explicit entity_id")
        try:
            canonical_entity_id = canonical_client_id(entity_id)
        except (TypeError, ValueError) as exc:
            raise PermitValidationError("execution permit entity_id is invalid") from exc

        if approved_reviews:
            raise PermitReviewRequired(
                "caller-supplied review labels are not trusted approval evidence"
            )

        now = self.clock()
        payload_hash = canonical_payload_hash(payload)
        policy_decision_hash = canonical_policy_decision_hash(decision)
        approval_receipt: PermitApprovalReceipt | None = None
        if decision.required_reviews:
            if self.approval_authority is None or approval_request is None:
                raise PermitReviewRequired(
                    "reviewed permits require verification by a trusted approval authority"
                )
            if self.store is None:
                raise PermitReviewRequired(
                    "reviewed permits require persistence in a trusted permit store"
                )
            _require_exact_approval_scope(
                approval_request=approval_request,
                decision=decision,
                case_id=case_id,
                entity_id=canonical_entity_id,
                payload_hash=payload_hash,
            )
            verification = self.approval_authority.verify(approval_request, now=now)
            if (
                not verification.valid
                or verification.request_id != approval_request.request_id
                or verification.binding_digest != approval_request.binding.digest
                or verification.request_digest != approval_request.digest
                or verification.missing_roles
                or not verification.decision_ids
                or verification.errors
            ):
                detail = ", ".join(verification.errors) or "approval verification mismatch"
                raise PermitReviewRequired(f"trusted approval is not valid: {detail}")
            approval_receipt = PermitApprovalReceipt(
                request_id=approval_request.request_id,
                binding_digest=approval_request.binding.digest,
                request_digest=approval_request.digest,
                client_id=approval_request.binding.client_id,
                entity_id=approval_request.binding.entity_id,
                case_id=approval_request.binding.case_id,
                action=approval_request.action,
                payload_hash=approval_request.binding.proposal_hash,
                policy_hash=approval_request.binding.policy_hash,
                decision_ids=verification.decision_ids,
                verified_at=now,
            )
        elif approval_request is not None:
            raise PermitValidationError(
                "zero-review decisions must not carry an approval request"
            )

        permit = ExecutionPermit(
            permit_id=str(self.id_factory()),
            case_id=case_id,
            client_id=context.client_id,
            allowed_action=decision.action_type,
            payload_hash=payload_hash,
            policy_version=decision.policy_version,
            required_reviews=decision.required_reviews,
            permission_mode=decision.permission_mode,
            expires_at=now + self.ttl,
            idempotency_key=_idempotency_key(
                client_id=context.client_id,
                case_id=case_id,
                entity_id=canonical_entity_id,
                action_type=decision.action_type,
                payload_hash=payload_hash,
                policy_version=decision.policy_version,
            ),
            issued_at=now,
            entity_id=canonical_entity_id,
            policy_decision_hash=policy_decision_hash,
            approval_receipt=approval_receipt,
            approved_reviews=(),
        )
        if self.store is not None:
            self.store.save(permit)
        return permit


class PermitValidator:
    def __init__(
        self,
        *,
        accepted_policy_version: str | None = None,
        clock: Any | None = None,
        permit_store: PermitStore | None = None,
        approval_authority: TrustedApprovalAuthority | None = None,
    ) -> None:
        self.accepted_policy_version = accepted_policy_version
        self.clock = clock or _utc_now
        self.permit_store = permit_store
        self.approval_authority = approval_authority

    def require_valid(
        self,
        *,
        permit: ExecutionPermit | None,
        case_id: str,
        entity_id: str,
        action_type: ActionType,
        payload: Any,
    ) -> None:
        if permit is None:
            raise PermitValidationError("external writes require an execution permit")
        now = self.clock()
        _require_aware(now, "permit validator clock")
        action_type = ActionType(action_type)
        if not permit.permit_id.strip():
            raise PermitValidationError("execution permit id is required")
        if not permit.case_id.strip():
            raise PermitValidationError("execution permit case_id is required")
        if not permit.client_id.strip():
            raise PermitValidationError("execution permit client_id is required")
        try:
            expected_entity = canonical_client_id(entity_id)
        except (TypeError, ValueError) as exc:
            raise PermitValidationError("attempted write entity_id is invalid") from exc
        _require_permit_entity(permit)
        _require_permit_policy_hash(permit)
        if permit.entity_id != expected_entity:
            raise PermitValidationError(
                "permit entity_id does not match attempted write"
            )
        if not permit.idempotency_key.strip():
            raise PermitValidationError("execution permit idempotency key is required")
        if permit.allowed_action not in EXTERNAL_WRITE_ACTIONS:
            raise PermitValidationError("execution permit action is not an external write")
        if permit.permission_mode in {PermissionMode.AUTO_ALLOWED, PermissionMode.FORBIDDEN}:
            raise PermitValidationError(
                f"execution permit mode {permit.permission_mode.value} is not valid for writes"
            )
        if (
            permit.permission_mode
            in {PermissionMode.APPROVAL_REQUIRED, PermissionMode.ESCALATION_REQUIRED}
            and not permit.required_reviews
        ):
            raise PermitValidationError(
                "reviewed execution permits must include required review types"
            )
        if permit.approved_reviews:
            raise PermitValidationError(
                "caller-supplied approved reviews are not valid permit evidence"
            )
        if permit.required_reviews:
            if permit.approval_receipt is None:
                raise PermitValidationError(
                    "reviewed execution permits require a trusted approval receipt"
                )
            if permit.approval_receipt.verified_at != permit.issued_at:
                raise PermitValidationError(
                    "approval receipt verification time does not match permit issuance"
                )
            receipt_scope = (
                permit.approval_receipt.client_id,
                permit.approval_receipt.entity_id,
                permit.approval_receipt.case_id,
                permit.approval_receipt.action,
                permit.approval_receipt.payload_hash,
                permit.approval_receipt.policy_hash,
            )
            permit_scope = (
                permit.client_id,
                permit.entity_id,
                permit.case_id,
                permit.allowed_action.value,
                permit.payload_hash,
                permit.policy_decision_hash,
            )
            if receipt_scope != permit_scope:
                raise PermitValidationError(
                    "trusted approval receipt scope does not match execution permit"
                )
            if self.permit_store is None:
                raise PermitValidationError(
                    "reviewed execution permits require a trusted permit store"
                )
            stored_permit = self.permit_store.get(permit.permit_id)
            if stored_permit != permit:
                raise PermitValidationError(
                    "reviewed execution permit does not match trusted permit store"
                )
            if self.approval_authority is None:
                raise PermitValidationError(
                    "reviewed execution permits require a trusted approval authority"
                )
            approval_request = self.approval_authority.get_request(
                permit.approval_receipt.request_id
            )
            if approval_request is None:
                raise PermitValidationError(
                    "approval receipt request is missing from trusted approval authority"
                )
            request_scope = (
                approval_request.binding.client_id,
                approval_request.binding.entity_id,
                approval_request.binding.case_id,
                approval_request.action,
                approval_request.binding.proposal_hash,
                approval_request.binding.policy_hash,
                approval_request.binding.digest,
                approval_request.digest,
            )
            receipt_request_scope = receipt_scope + (
                permit.approval_receipt.binding_digest,
                permit.approval_receipt.request_digest,
            )
            if request_scope != receipt_request_scope:
                raise PermitValidationError(
                    "approval receipt does not match trusted approval request"
                )
            expected_roles = tuple(
                _POLICY_REVIEW_ROLES[review]
                for review in permit.required_reviews
                if review in _POLICY_REVIEW_ROLES
            )
            if (
                len(expected_roles) != len(permit.required_reviews)
                or approval_request.required_roles != expected_roles
            ):
                raise PermitValidationError(
                    "approval request roles do not match execution permit policy"
                )
            verification = self.approval_authority.verify(
                approval_request,
                now=now,
            )
            if (
                not verification.valid
                or verification.request_id != permit.approval_receipt.request_id
                or verification.binding_digest != permit.approval_receipt.binding_digest
                or verification.request_digest != permit.approval_receipt.request_digest
                or verification.missing_roles
                or verification.decision_ids != permit.approval_receipt.decision_ids
                or verification.errors
            ):
                raise PermitValidationError(
                    "approval receipt failed trusted authority revalidation"
                )
        elif permit.approval_receipt is not None:
            raise PermitValidationError(
                "zero-review execution permits must not carry an approval receipt"
            )
        if permit.permission_mode is PermissionMode.FORBIDDEN:
            raise PermitValidationError("forbidden permits are never valid")
        if permit.case_id != case_id:
            raise PermitValidationError("permit case_id does not match attempted write")
        if permit.allowed_action != action_type:
            raise PermitValidationError("permit action does not match attempted write")
        if permit.issued_at >= permit.expires_at:
            raise PermitValidationError("execution permit expiry must be after issue time")
        if permit.expires_at <= now:
            raise PermitValidationError("execution permit has expired")
        if self.accepted_policy_version is not None:
            if permit.policy_version != self.accepted_policy_version:
                raise PermitValidationError("execution permit policy version is not accepted")
        payload_hash = canonical_payload_hash(payload)
        if permit.payload_hash != payload_hash:
            raise PermitValidationError("permit payload hash does not match attempted write")
        expected_idempotency_key = _idempotency_key(
            client_id=permit.client_id,
            case_id=case_id,
            entity_id=expected_entity,
            action_type=action_type,
            payload_hash=payload_hash,
            policy_version=permit.policy_version,
        )
        if permit.idempotency_key != expected_idempotency_key:
            raise PermitValidationError(
                "execution permit idempotency key does not match attempted write"
            )



def _require_exact_approval_scope(
    *,
    approval_request: ApprovalRequest,
    decision: PolicyDecision,
    case_id: str,
    entity_id: str,
    payload_hash: str,
) -> None:
    expected_roles: list[ReviewerRole] = []
    for review in decision.required_reviews:
        role = _POLICY_REVIEW_ROLES.get(review)
        if role is None or role in expected_roles:
            raise PermitReviewRequired(
                "trusted approval scope cannot represent the policy review requirements"
            )
        expected_roles.append(role)
    binding = approval_request.binding
    mismatches: list[str] = []
    if binding.client_id != canonical_client_id(decision.client_id):
        mismatches.append("client_id")
    if binding.entity_id != entity_id:
        mismatches.append("entity_id")
    if binding.case_id != case_id:
        mismatches.append("case_id")
    if binding.proposal_hash != payload_hash:
        mismatches.append("payload_hash")
    if binding.policy_hash != canonical_policy_decision_hash(decision):
        mismatches.append("policy_hash")
    if approval_request.action != decision.action_type.value:
        mismatches.append("action")
    if approval_request.required_roles != tuple(expected_roles):
        mismatches.append("required_roles")
    if mismatches:
        raise PermitReviewRequired(
            "trusted approval scope does not match permit request: "
            + ", ".join(mismatches)
        )


def _require_permit_entity(permit: ExecutionPermit) -> None:
    if permit.entity_id is None:
        raise PermitValidationError("execution permit entity_id is required")
    try:
        canonical_entity = canonical_client_id(permit.entity_id)
    except (TypeError, ValueError) as exc:
        raise PermitValidationError("execution permit entity_id is invalid") from exc
    if canonical_entity != permit.entity_id:
        raise PermitValidationError("execution permit entity_id is not canonical")


def _require_permit_policy_hash(permit: ExecutionPermit) -> None:
    if permit.policy_decision_hash is None:
        raise PermitValidationError("execution permit policy_decision_hash is required")
    try:
        _require_sha256(permit.policy_decision_hash, "execution permit policy_decision_hash")
    except ValueError as exc:
        raise PermitValidationError(
            "execution permit policy_decision_hash is invalid"
        ) from exc


def canonical_payload_hash(payload: Any) -> str:
    serialized = json.dumps(
        _to_jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _require_current_policy_decision(
    decision: PolicyDecision,
    context: PolicyContext,
) -> None:
    expected = evaluate_policy(context)
    mismatches: list[str] = []
    if decision.permission_mode != expected.permission_mode:
        mismatches.append("permission_mode")
    if decision.policy_version != expected.policy_version:
        mismatches.append("policy_version")
    if decision.currency_code != expected.currency_code:
        mismatches.append("currency_code")
    if decision.amount_thresholds != expected.amount_thresholds:
        mismatches.append("amount_thresholds")
    if decision.required_reviews != expected.required_reviews:
        mismatches.append("required_reviews")
    if decision.reasons != expected.reasons:
        mismatches.append("reasons")
    if decision.is_external_write != expected.is_external_write:
        mismatches.append("is_external_write")
    if mismatches:
        raise PermitValidationError(
            "policy decision does not match current policy evaluation: "
            + ", ".join(mismatches)
        )


def _idempotency_key(
    *,
    client_id: str,
    case_id: str,
    entity_id: str,
    action_type: ActionType,
    payload_hash: str,
    policy_version: str,
) -> str:
    material = (
        f"{client_id}:{entity_id}:{case_id}:{action_type.value}:"
        f"{payload_hash}:{policy_version}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _to_jsonable(value: Any) -> Any:
    if dataclass_is_instance(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_to_jsonable(item) for item in value]
    return value


def dataclass_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__") and not isinstance(value, type)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _utc_now() -> datetime:
    return datetime.now(UTC)
