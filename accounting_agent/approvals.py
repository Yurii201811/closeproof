"""Immutable, identity-bound approval primitives for Accounting Agent v1."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .client_identity import canonical_client_id


SAFE_ENVIRONMENTS = frozenset({"local", "test", "preview", "dry_run"})


class ApprovalError(Exception):
    """Base class for trusted approval failures."""


class ApprovalConflict(ApprovalError):
    """Raised when an immutable approval record already exists."""


class ApprovalValidationError(ApprovalError):
    """Raised when identity, scope, role, or time validation fails."""


class ReviewerRole(str, Enum):
    PREPARER = "preparer"
    REVIEWER = "reviewer"
    CONTROLLER = "controller"
    AUDITOR = "auditor"
    CLIENT_RESPONSIBLE = "client_responsible"
    TAX_REVIEWER = "tax_reviewer"
    SECURITY_REVIEWER = "security_reviewer"


class ApprovalOutcome(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class ReviewerIdentity:
    reviewer_id: str
    client_id: str
    roles: tuple[ReviewerRole, ...]
    identity_provider: str
    verified: bool
    active: bool

    def __post_init__(self) -> None:
        _canonical_text(self.reviewer_id, "reviewer_id")
        object.__setattr__(self, "client_id", canonical_client_id(self.client_id))
        _canonical_text(self.identity_provider, "identity_provider")
        roles = tuple(ReviewerRole(role) for role in self.roles)
        object.__setattr__(self, "roles", roles)
        if not roles or len(set(roles)) != len(roles):
            raise ValueError("roles must be non-empty and unique")
        if not isinstance(self.verified, bool) or not isinstance(self.active, bool):
            raise TypeError("verified and active must be boolean")


@dataclass(frozen=True)
class ApprovalBinding:
    client_id: str
    entity_id: str
    case_id: str
    proposal_hash: str
    evidence_hashes: tuple[str, ...]
    policy_hash: str
    provider_id: str
    environment: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", canonical_client_id(self.client_id))
        object.__setattr__(self, "entity_id", canonical_client_id(self.entity_id))
        for name, value in (
            ("case_id", self.case_id),
            ("provider_id", self.provider_id),
        ):
            _canonical_text(value, name)
        _require_sha256(self.proposal_hash, "proposal_hash")
        _require_sha256(self.policy_hash, "policy_hash")
        if not self.evidence_hashes or len(set(self.evidence_hashes)) != len(
            self.evidence_hashes
        ):
            raise ValueError("evidence_hashes must be non-empty and unique")
        for evidence_hash in self.evidence_hashes:
            _require_sha256(evidence_hash, "evidence_hash")
        if self.environment not in SAFE_ENVIRONMENTS:
            raise ValueError("approval bindings are limited to safe non-production environments")

    @property
    def digest(self) -> str:
        return _canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "entity_id": self.entity_id,
            "case_id": self.case_id,
            "proposal_hash": self.proposal_hash,
            "evidence_hashes": list(self.evidence_hashes),
            "policy_hash": self.policy_hash,
            "provider_id": self.provider_id,
            "environment": self.environment,
        }


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    binding: ApprovalBinding
    action: str
    requestor_id: str
    required_roles: tuple[ReviewerRole, ...]
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _canonical_text(self.request_id, "request_id")
        _canonical_text(self.action, "action")
        _canonical_text(self.requestor_id, "requestor_id")
        roles = tuple(ReviewerRole(role) for role in self.required_roles)
        object.__setattr__(self, "required_roles", roles)
        if not roles or len(set(roles)) != len(roles):
            raise ValueError("required_roles must be non-empty and unique")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("approval request must expire after it is created")

    @property
    def digest(self) -> str:
        return _canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "binding": self.binding.to_dict(),
            "action": self.action,
            "requestor_id": self.requestor_id,
            "required_roles": [role.value for role in self.required_roles],
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True)
class ApprovalDecision:
    decision_id: str
    request_id: str
    request_digest: str
    reviewer_id: str
    role: ReviewerRole
    outcome: ApprovalOutcome
    reason: str
    decided_at: datetime


@dataclass(frozen=True)
class ApprovalVerification:
    valid: bool
    request_id: str | None
    binding_digest: str
    request_digest: str
    missing_roles: tuple[ReviewerRole, ...]
    decision_ids: tuple[str, ...]
    errors: tuple[str, ...] = ()


class SQLiteApprovalStore:
    """Local immutable approval registry used by synthetic and dry-run workflows."""

    def __init__(self, database_path: str | Path, *, clock: Any | None = None) -> None:
        self.database_path = str(database_path)
        self.clock = clock or _utc_now
        self._ensure_schema()

    def register_reviewer(self, identity: ReviewerIdentity) -> None:
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO reviewer_identities (
                            reviewer_id, client_id, roles, identity_provider, verified, active
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            identity.reviewer_id,
                            identity.client_id,
                            json.dumps(
                                [role.value for role in identity.roles],
                                separators=(",", ":"),
                            ),
                            identity.identity_provider,
                            int(identity.verified),
                            int(identity.active),
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise ApprovalConflict("reviewer identity is immutable and already exists") from exc

    def create_request(self, request: ApprovalRequest) -> None:
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN IMMEDIATE")
                existing_attempts = connection.execute(
                    """
                    SELECT
                        request_id,
                        expires_at,
                        (
                            SELECT MIN(decided_at)
                            FROM approval_decisions
                            WHERE approval_decisions.request_id = approval_requests.request_id
                              AND outcome = ?
                        ) AS rejected_at
                    FROM approval_requests
                    WHERE binding_digest = ?
                    """,
                    (ApprovalOutcome.REJECT.value, request.binding.digest),
                ).fetchall()
                for existing in existing_attempts:
                    terminal_at = _parse_datetime(
                        existing["rejected_at"] or existing["expires_at"]
                    )
                    if request.created_at < terminal_at:
                        raise ApprovalConflict(
                            "an active exact-scope approval request already exists"
                        )
                with connection:
                    connection.execute(
                    """
                    INSERT INTO approval_requests (
                        request_id, binding_digest, binding_json, action, requestor_id,
                        required_roles, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            request.request_id,
                            request.binding.digest,
                            json.dumps(
                                request.binding.to_dict(),
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            request.action,
                            request.requestor_id,
                            json.dumps(
                                [role.value for role in request.required_roles],
                                separators=(",", ":"),
                            ),
                            request.created_at.isoformat(),
                            request.expires_at.isoformat(),
                        ),
                    )
        except ApprovalConflict:
            raise
        except sqlite3.IntegrityError as exc:
            raise ApprovalConflict("approval request is immutable and already exists") from exc

    def record_decision(
        self,
        *,
        request_id: str,
        reviewer_id: str,
        role: ReviewerRole,
        outcome: ApprovalOutcome,
        reason: str,
        decided_at: datetime,
    ) -> ApprovalDecision:
        _require_aware(decided_at, "decided_at")
        authority_now = self.clock()
        _require_aware(authority_now, "approval authority clock")
        if decided_at > authority_now:
            raise ApprovalValidationError(
                "approval decision timestamp cannot be in the future"
            )
        _canonical_text(reason, "reason")
        role = ReviewerRole(role)
        outcome = ApprovalOutcome(outcome)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            request_row = connection.execute(
                "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if request_row is None:
                raise ApprovalValidationError("approval request does not exist")
            identity_row = connection.execute(
                "SELECT * FROM reviewer_identities WHERE reviewer_id = ?", (reviewer_id,)
            ).fetchone()
            if identity_row is None:
                raise ApprovalValidationError("reviewer identity is not registered")
            request = _request_from_row(request_row)
            identity = _identity_from_row(identity_row)
            exact_existing = connection.execute(
                """
                SELECT 1 FROM approval_decisions
                WHERE request_id = ? AND reviewer_id = ? AND role = ?
                """,
                (request_id, reviewer_id, role.value),
            ).fetchone()
            if exact_existing is not None:
                raise ApprovalConflict("approval decisions are immutable")
            if reviewer_id == request.requestor_id:
                raise ApprovalValidationError("requestors cannot approve their own request")
            if decided_at < request.created_at or decided_at >= request.expires_at:
                raise ApprovalValidationError(
                    "approval decision must fall within the request validity window"
                )
            if not identity.verified or not identity.active:
                raise ApprovalValidationError("reviewer identity is not verified and active")
            if identity.client_id != request.binding.client_id:
                raise ApprovalValidationError("reviewer belongs to a different client")
            if role not in identity.roles or role not in request.required_roles:
                raise ApprovalValidationError("reviewer is not authorized for the required role")
            other_role = connection.execute(
                """
                SELECT 1 FROM approval_decisions
                WHERE request_id = ? AND reviewer_id = ?
                """,
                (request_id, reviewer_id),
            ).fetchone()
            if other_role is not None:
                raise ApprovalValidationError(
                    "one reviewer cannot satisfy more than one required role"
                )
            decision_id = "decision_" + _canonical_hash(
                {
                    "request_id": request_id,
                    "request_digest": request.digest,
                    "reviewer_id": reviewer_id,
                    "role": role.value,
                    "outcome": outcome.value,
                    "reason": reason,
                    "decided_at": decided_at.isoformat(),
                }
            )
            decision = ApprovalDecision(
                decision_id=decision_id,
                request_id=request_id,
                request_digest=request.digest,
                reviewer_id=reviewer_id,
                role=role,
                outcome=outcome,
                reason=reason,
                decided_at=decided_at,
            )
            try:
                with connection:
                    connection.execute(
                    """
                    INSERT INTO approval_decisions (
                        decision_id, request_id, request_digest, reviewer_id,
                        role, outcome, reason, decided_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            decision.decision_id,
                            decision.request_id,
                            decision.request_digest,
                            decision.reviewer_id,
                            decision.role.value,
                            decision.outcome.value,
                            decision.reason,
                            decision.decided_at.isoformat(),
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise ApprovalConflict("approval decision is immutable and already exists") from exc
        return decision

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Load one immutable request for trusted permit revalidation."""

        _canonical_text(request_id, "request_id")
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return _request_from_row(row) if row is not None else None

    def verify(
        self,
        expected_request: ApprovalRequest,
        *,
        now: datetime,
    ) -> ApprovalVerification:
        _require_aware(now, "now")
        if not isinstance(expected_request, ApprovalRequest):
            raise TypeError("expected_request must be an ApprovalRequest")
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE request_id = ?",
                (expected_request.request_id,),
            ).fetchone()
            if row is None:
                return ApprovalVerification(
                    valid=False,
                    request_id=None,
                    binding_digest=expected_request.binding.digest,
                    request_digest=expected_request.digest,
                    missing_roles=(),
                    decision_ids=(),
                    errors=("approval_request_not_found_for_exact_request",),
                )
            request = _request_from_row(row)
            decisions = tuple(
                _decision_from_row(item)
                for item in connection.execute(
                    """
                    SELECT * FROM approval_decisions
                    WHERE request_id = ? ORDER BY decided_at, decision_id
                    """,
                    (request.request_id,),
                ).fetchall()
            )
        errors: list[str] = []
        if request != expected_request or request.digest != expected_request.digest:
            errors.append("approval_request_mismatch")
        if now < request.created_at:
            errors.append("approval_request_not_yet_valid")
        if now >= request.expires_at:
            errors.append("approval_request_expired")
        approved_roles: set[ReviewerRole] = set()
        for decision in decisions:
            if decision.decided_at > now:
                errors.append("approval_decision_in_future")
            if decision.request_digest != expected_request.digest:
                errors.append("approval_decision_request_mismatch")
            if decision.outcome is ApprovalOutcome.REJECT:
                errors.append(f"approval_rejected:{decision.role.value}")
            elif decision.request_digest == expected_request.digest:
                approved_roles.add(decision.role)
        missing_roles = tuple(
            role for role in expected_request.required_roles if role not in approved_roles
        )
        if missing_roles:
            errors.append("required_approvals_missing")
        return ApprovalVerification(
            valid=not errors,
            request_id=request.request_id,
            binding_digest=expected_request.binding.digest,
            request_digest=expected_request.digest,
            missing_roles=missing_roles,
            decision_ids=tuple(decision.decision_id for decision in decisions),
            errors=tuple(errors),
        )

    def _ensure_schema(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            with connection:
                connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reviewer_identities (
                    reviewer_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    roles TEXT NOT NULL,
                    identity_provider TEXT NOT NULL,
                    verified INTEGER NOT NULL,
                    active INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    binding_json TEXT NOT NULL,
                    action TEXT NOT NULL,
                    requestor_id TEXT NOT NULL,
                    required_roles TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approval_decisions (
                    decision_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    UNIQUE (request_id, reviewer_id, role),
                    FOREIGN KEY (request_id) REFERENCES approval_requests(request_id),
                    FOREIGN KEY (reviewer_id) REFERENCES reviewer_identities(reviewer_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS approval_one_role_per_reviewer
                ON approval_decisions (request_id, reviewer_id);
                """
                )
                if _binding_digest_has_unique_index(connection):
                    connection.execute(
                        """
                        CREATE TABLE approval_requests_without_binding_unique (
                            request_id TEXT PRIMARY KEY,
                            binding_digest TEXT NOT NULL,
                            binding_json TEXT NOT NULL,
                            action TEXT NOT NULL,
                            requestor_id TEXT NOT NULL,
                            required_roles TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            expires_at TEXT NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO approval_requests_without_binding_unique
                        SELECT
                            request_id, binding_digest, binding_json, action,
                            requestor_id, required_roles, created_at, expires_at
                        FROM approval_requests
                        """
                    )
                    connection.execute("DROP TABLE approval_requests")
                    connection.execute(
                        """
                        ALTER TABLE approval_requests_without_binding_unique
                        RENAME TO approval_requests
                        """
                    )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS approval_requests_binding_lookup
                    ON approval_requests (binding_digest)
                    """
                )


def _request_from_row(row: sqlite3.Row) -> ApprovalRequest:
    binding_data = json.loads(row["binding_json"])
    binding = ApprovalBinding(
        client_id=binding_data["client_id"],
        entity_id=binding_data["entity_id"],
        case_id=binding_data["case_id"],
        proposal_hash=binding_data["proposal_hash"],
        evidence_hashes=tuple(binding_data["evidence_hashes"]),
        policy_hash=binding_data["policy_hash"],
        provider_id=binding_data["provider_id"],
        environment=binding_data["environment"],
    )
    if binding.digest != row["binding_digest"]:
        raise ApprovalValidationError("stored approval binding failed integrity validation")
    return ApprovalRequest(
        request_id=row["request_id"],
        binding=binding,
        action=row["action"],
        requestor_id=row["requestor_id"],
        required_roles=tuple(ReviewerRole(value) for value in json.loads(row["required_roles"])),
        created_at=_parse_datetime(row["created_at"]),
        expires_at=_parse_datetime(row["expires_at"]),
    )


def _binding_digest_has_unique_index(connection: sqlite3.Connection) -> bool:
    for index in connection.execute("PRAGMA index_list(approval_requests)").fetchall():
        if not bool(index[2]):
            continue
        columns = tuple(
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info({json.dumps(index[1])})"
            ).fetchall()
        )
        if columns == ("binding_digest",):
            return True
    return False


def _identity_from_row(row: sqlite3.Row) -> ReviewerIdentity:
    return ReviewerIdentity(
        reviewer_id=row["reviewer_id"],
        client_id=row["client_id"],
        roles=tuple(ReviewerRole(value) for value in json.loads(row["roles"])),
        identity_provider=row["identity_provider"],
        verified=bool(row["verified"]),
        active=bool(row["active"]),
    )


def _decision_from_row(row: sqlite3.Row) -> ApprovalDecision:
    return ApprovalDecision(
        decision_id=row["decision_id"],
        request_id=row["request_id"],
        request_digest=row["request_digest"],
        reviewer_id=row["reviewer_id"],
        role=ReviewerRole(row["role"]),
        outcome=ApprovalOutcome(row["outcome"]),
        reason=row["reason"],
        decided_at=_parse_datetime(row["decided_at"]),
    )


def _canonical_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty canonical string")


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _parse_datetime(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    _require_aware(parsed, "datetime")
    return parsed


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)
