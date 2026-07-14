"""Checkpointed preparation-only autonomy for Accounting Agent v1.

The runner automates reversible preparation stages and always terminates at a
human-decision boundary. It has no API for approvals, posting, payments,
filings, communication, deletion, or settings changes.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from .client_identity import canonical_client_id


class AutonomyStage(str, Enum):
    COLLECT = "collect"
    EXTRACT = "extract"
    VALIDATE = "validate"
    MATCH = "match"
    REQUEST_MISSING_EVIDENCE = "request_missing_evidence"
    DRAFT = "draft"
    EXPLAIN = "explain"
    ASSEMBLE_REVIEW_PACKET = "assemble_review_packet"


AUTONOMY_LADDER = tuple(AutonomyStage)
SAFE_PERMISSION_CEILING = (
    "read_fixture_evidence",
    "derive_structured_facts",
    "validate_deterministic_controls",
    "propose_matches",
    "draft_missing_evidence_request",
    "draft_accounting_proposal",
    "explain_proposal",
    "assemble_review_packet",
)
SAFE_ENVIRONMENTS = frozenset({"local", "test", "preview", "dry_run"})
ACTIVE_EXECUTION_WAIT_SECONDS = 30.0
ACTIVE_EXECUTION_POLL_SECONDS = 0.005
EXECUTION_LEASE_TTL = timedelta(seconds=30)
EXECUTION_HEARTBEAT_SECONDS = 5.0


class ProcessorCapabilityDenied(PermissionError):
    """Raised when a processor requests authority outside preparation work."""


class PreparationCapabilities:
    """Narrow capability view exposed to preparation-only processors.

    The object can confirm a preparation capability, but it never exposes a
    network client, filesystem handle, ERP adapter, approval service, or
    accounting executor. Denied requests are retained so a processor cannot
    catch the exception and pretend that its stage completed safely.

    This is an object-capability boundary, not a Python code sandbox. Callbacks
    must still be trusted application code; untrusted code belongs in an
    external OS sandbox and is rejected by the in-process runner.
    """

    __slots__ = ("_allowed", "_denied")

    def __init__(self, allowed: tuple[str, ...]) -> None:
        self._allowed = allowed
        self._denied: list[str] = []

    @property
    def allowed(self) -> tuple[str, ...]:
        return self._allowed

    def require(self, capability: str) -> None:
        _canonical_text(capability, "capability")
        if capability not in self._allowed:
            self._deny(capability)

    @property
    def denied(self) -> tuple[str, ...]:
        return tuple(self._denied)

    def _deny(self, capability: str) -> None:
        self._denied.append(capability)
        raise ProcessorCapabilityDenied(
            f"processor capability is not available: {capability}"
        )


class StageState(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class AutonomyRunState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    AWAITING_HUMAN_DECISION = "awaiting_human_decision"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AutonomyPlan:
    plan_id: str
    client_id: str
    entity_id: str
    case_id: str
    environment: str
    data_classification: str
    evidence_hashes: tuple[str, ...]
    stages: tuple[AutonomyStage, ...] = AUTONOMY_LADDER
    permission_ceiling: tuple[str, ...] = SAFE_PERMISSION_CEILING

    def __post_init__(self) -> None:
        _canonical_text(self.plan_id, "plan_id")
        object.__setattr__(self, "client_id", canonical_client_id(self.client_id))
        _canonical_text(self.entity_id, "entity_id")
        _canonical_text(self.case_id, "case_id")
        if self.environment not in SAFE_ENVIRONMENTS:
            raise ValueError("autonomy is limited to safe non-production environments")
        if self.data_classification != "synthetic":
            raise ValueError("the v1 autonomous runner accepts synthetic data only")
        if self.stages != AUTONOMY_LADDER:
            raise ValueError("autonomy stages must use the fixed preparation-only ladder")
        if self.permission_ceiling != SAFE_PERMISSION_CEILING:
            raise ValueError("autonomy permission ceiling cannot be extended")
        if not self.evidence_hashes or len(set(self.evidence_hashes)) != len(
            self.evidence_hashes
        ):
            raise ValueError("evidence_hashes must be non-empty and unique")
        for evidence_hash in self.evidence_hashes:
            _require_sha256(evidence_hash, "evidence_hash")

    @property
    def digest(self) -> str:
        return _canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "client_id": self.client_id,
            "entity_id": self.entity_id,
            "case_id": self.case_id,
            "environment": self.environment,
            "data_classification": self.data_classification,
            "evidence_hashes": list(self.evidence_hashes),
            "stages": [stage.value for stage in self.stages],
            "permission_ceiling": list(self.permission_ceiling),
        }


@dataclass(frozen=True)
class ProcessorResult:
    summary: str
    output: dict[str, Any]
    requires_review: bool = False
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        _canonical_text(self.summary, "summary")
        if not isinstance(self.output, dict):
            raise TypeError("processor output must be a JSON object")
        try:
            json.dumps(self.output, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise TypeError("processor output must be JSON serializable") from exc
        if self.requires_review and self.blocked_reason:
            raise ValueError("a result cannot be both review-required and blocked")
        if self.blocked_reason is not None:
            _canonical_text(self.blocked_reason, "blocked_reason")


@dataclass(frozen=True)
class StageContext:
    run_id: str
    plan: AutonomyPlan
    stage: AutonomyStage
    attempt: int
    prior_output_hashes: tuple[str, ...]
    capabilities: PreparationCapabilities


@dataclass(frozen=True)
class StageCheckpoint:
    stage: AutonomyStage
    state: StageState
    summary: str
    output_hash: str | None
    attempt: int
    completed_at: datetime
    error: str | None = None


@dataclass(frozen=True)
class AutonomyRunReport:
    run_id: str
    plan_id: str
    client_id: str
    state: AutonomyRunState
    next_stage: AutonomyStage | None
    stages: tuple[StageCheckpoint, ...]
    updated_at: datetime


_TRUSTED_PROCESSOR_FACTORY_TOKEN = object()


class TrustedPreparationProcessor:
    """Explicit trust wrapper for reviewed, synthetic-only preparation code.

    Wrapping does not sandbox the callback. It records the operator/developer
    decision that the callback is trusted application code and binds it to one
    safe environment. Raw or untrusted callbacks are not accepted by the
    runner; they require a separate OS-sandboxed worker boundary.
    """

    __slots__ = ("_callback", "environment")

    def __init__(
        self,
        callback: Callable[[StageContext], ProcessorResult],
        *,
        environment: str,
        _factory_token: object,
    ) -> None:
        if _factory_token is not _TRUSTED_PROCESSOR_FACTORY_TOKEN:
            raise TypeError(
                "TrustedPreparationProcessor must be created by "
                "trusted_preparation_processor()"
            )
        self._callback = callback
        self.environment = environment

    def __call__(self, context: StageContext) -> ProcessorResult:
        return self._callback(context)


def trusted_preparation_processor(
    callback: Callable[[StageContext], ProcessorResult],
    *,
    environment: str,
) -> TrustedPreparationProcessor:
    """Mark reviewed preparation code as trusted for one safe environment."""

    if environment not in SAFE_ENVIRONMENTS:
        raise ValueError("trusted processors are limited to safe environments")
    if not callable(callback):
        raise TypeError("processor callback must be callable")
    return TrustedPreparationProcessor(
        callback,
        environment=environment,
        _factory_token=_TRUSTED_PROCESSOR_FACTORY_TOKEN,
    )


Processor = TrustedPreparationProcessor


class SQLiteAutonomyStore:
    """Operational checkpoint store; legal audit events belong in the event ledger."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._ensure_schema()

    def create(self, plan: AutonomyPlan, *, created_at: datetime) -> str:
        _require_aware(created_at, "created_at")
        run_id = f"run_{plan.digest[:24]}"
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                existing = connection.execute(
                    "SELECT plan_digest FROM autonomy_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if existing is not None:
                    if existing[0] != plan.digest:
                        raise RuntimeError("autonomy run identifier collision")
                    return run_id
                connection.execute(
                    """
                    INSERT INTO autonomy_runs (
                        run_id, plan_id, client_id, plan_digest, plan_json,
                        state, cancel_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        run_id,
                        plan.plan_id,
                        plan.client_id,
                        plan.digest,
                        json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":")),
                        AutonomyRunState.CREATED.value,
                        created_at.isoformat(),
                        created_at.isoformat(),
                    ),
                )
        return run_id

    def load_plan(self, run_id: str) -> AutonomyPlan:
        row = self._run_row(run_id)
        data = json.loads(row["plan_json"])
        plan = AutonomyPlan(
            plan_id=data["plan_id"],
            client_id=data["client_id"],
            entity_id=data["entity_id"],
            case_id=data["case_id"],
            environment=data["environment"],
            data_classification=data["data_classification"],
            evidence_hashes=tuple(data["evidence_hashes"]),
            stages=tuple(AutonomyStage(value) for value in data["stages"]),
            permission_ceiling=tuple(data["permission_ceiling"]),
        )
        if plan.digest != row["plan_digest"]:
            raise RuntimeError("stored autonomy plan failed integrity validation")
        return plan

    def state(self, run_id: str) -> AutonomyRunState:
        return AutonomyRunState(self._run_row(run_id)["state"])

    def acquire_execution_lease(
        self,
        run_id: str,
        *,
        lease_token: str,
        updated_at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Atomically claim the one permitted execution lease for a run."""

        _require_aware(updated_at, "updated_at")
        _require_aware(expires_at, "expires_at")
        if expires_at <= updated_at:
            raise ValueError("execution lease expiry must be after its update time")
        _canonical_text(lease_token, "lease_token")
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE autonomy_runs
                    SET state = ?, lease_token = ?, lease_expires_at = ?,
                        updated_at = ?
                    WHERE run_id = ?
                      AND (
                        (
                          state IN (?, ?)
                          AND lease_token IS NULL
                        )
                        OR
                        (
                          state = ?
                          AND (
                            lease_token IS NULL
                            OR lease_expires_at IS NULL
                            OR lease_expires_at <= ?
                          )
                        )
                      )
                    """,
                    (
                        AutonomyRunState.RUNNING.value,
                        lease_token,
                        expires_at.isoformat(),
                        updated_at.isoformat(),
                        run_id,
                        AutonomyRunState.CREATED.value,
                        AutonomyRunState.INTERRUPTED.value,
                        AutonomyRunState.RUNNING.value,
                        updated_at.isoformat(),
                    ),
                )
        return cursor.rowcount == 1

    def execution_lease_is_owned(
        self,
        run_id: str,
        lease_token: str,
        *,
        now: datetime,
    ) -> bool:
        _require_aware(now, "now")
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM autonomy_runs
                WHERE run_id = ? AND state = ? AND lease_token = ?
                  AND lease_expires_at > ?
                """,
                (
                    run_id,
                    AutonomyRunState.RUNNING.value,
                    lease_token,
                    now.isoformat(),
                ),
            ).fetchone()
        return row is not None

    def heartbeat_execution_lease(
        self,
        run_id: str,
        *,
        lease_token: str,
        updated_at: datetime,
        expires_at: datetime,
    ) -> bool:
        """Renew an unexpired lease without allowing a late owner to revive it."""

        _require_aware(updated_at, "updated_at")
        _require_aware(expires_at, "expires_at")
        if expires_at <= updated_at:
            raise ValueError("execution lease expiry must be after its update time")
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE autonomy_runs
                    SET lease_expires_at = ?, updated_at = ?
                    WHERE run_id = ? AND state = ? AND lease_token = ?
                      AND lease_expires_at > ?
                    """,
                    (
                        expires_at.isoformat(),
                        updated_at.isoformat(),
                        run_id,
                        AutonomyRunState.RUNNING.value,
                        lease_token,
                        updated_at.isoformat(),
                    ),
                )
        return cursor.rowcount == 1

    def finish_execution_if_leased(
        self,
        run_id: str,
        *,
        lease_token: str,
        updated_at: datetime,
    ) -> bool:
        _require_aware(updated_at, "updated_at")
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE autonomy_runs
                    SET state = ?, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?
                    WHERE run_id = ? AND state = ? AND lease_token = ?
                      AND lease_expires_at > ?
                    """,
                    (
                        AutonomyRunState.AWAITING_HUMAN_DECISION.value,
                        updated_at.isoformat(),
                        run_id,
                        AutonomyRunState.RUNNING.value,
                        lease_token,
                        updated_at.isoformat(),
                    ),
                )
        return cursor.rowcount == 1

    def commit_checkpoint_if_leased(
        self,
        run_id: str,
        checkpoint: StageCheckpoint,
        *,
        lease_token: str,
        output: dict[str, Any] | None,
        run_state: AutonomyRunState,
    ) -> bool:
        """Atomically bind a stage checkpoint to the current execution lease.

        A cancellation takes the same SQLite write lock. Whichever transaction
        commits first becomes authoritative; cancelled or stale workers cannot
        write after their lease has been cleared or replaced.
        """

        output_json = (
            json.dumps(output, sort_keys=True, separators=(",", ":"))
            if output is not None
            else None
        )
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE autonomy_runs
                    SET state = ?, lease_token = ?,
                        lease_expires_at = CASE
                          WHEN ? = 1 THEN lease_expires_at
                          ELSE NULL
                        END,
                        updated_at = ?
                    WHERE run_id = ? AND state = ? AND lease_token = ?
                      AND lease_expires_at > ?
                    """,
                    (
                        run_state.value,
                        (
                            lease_token
                            if run_state is AutonomyRunState.RUNNING
                            else None
                        ),
                        1 if run_state is AutonomyRunState.RUNNING else 0,
                        checkpoint.completed_at.isoformat(),
                        run_id,
                        AutonomyRunState.RUNNING.value,
                        lease_token,
                        checkpoint.completed_at.isoformat(),
                    ),
                )
                if cursor.rowcount != 1:
                    return False
                _upsert_checkpoint(connection, run_id, checkpoint, output_json)
        return True

    def cancel_run(
        self,
        run_id: str,
        plan: AutonomyPlan,
        *,
        reason: str,
        updated_at: datetime,
    ) -> None:
        """Atomically persist cancellation and every unfinished checkpoint."""

        _require_aware(updated_at, "updated_at")
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.row_factory = sqlite3.Row
                # Acquire SQLite's write lock before reading checkpoint state so
                # the completed-vs-cancelled decision and terminal transition
                # are one serializable transaction.
                claimed = connection.execute(
                    """
                    UPDATE autonomy_runs
                    SET updated_at = updated_at
                    WHERE run_id = ?
                    """,
                    (run_id,),
                )
                if claimed.rowcount != 1:
                    raise KeyError(f"unknown autonomy run: {run_id}")
                rows = {
                    row["stage"]: row
                    for row in connection.execute(
                        "SELECT * FROM autonomy_checkpoints WHERE run_id = ?",
                        (run_id,),
                    ).fetchall()
                }
                for stage in plan.stages:
                    previous = rows.get(stage.value)
                    if (
                        previous is not None
                        and StageState(previous["state"]) is StageState.COMPLETED
                    ):
                        continue
                    checkpoint = StageCheckpoint(
                        stage=stage,
                        state=StageState.CANCELLED,
                        summary="Cancelled by an authorized operator.",
                        output_hash=None,
                        attempt=int(previous["attempt"]) if previous is not None else 0,
                        completed_at=updated_at,
                        error=reason,
                    )
                    _upsert_checkpoint(connection, run_id, checkpoint, None)
                connection.execute(
                    """
                    UPDATE autonomy_runs
                    SET state = ?, lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?, cancel_reason = ?
                    WHERE run_id = ?
                    """,
                    (
                        AutonomyRunState.CANCELLED.value,
                        updated_at.isoformat(),
                        reason,
                        run_id,
                    ),
                )

    def checkpoints(self, run_id: str) -> tuple[StageCheckpoint, ...]:
        plan = self.load_plan(run_id)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = {
                row["stage"]: row
                for row in connection.execute(
                    "SELECT * FROM autonomy_checkpoints WHERE run_id = ?", (run_id,)
                ).fetchall()
            }
        return tuple(
            _checkpoint_from_row(rows[stage.value])
            for stage in plan.stages
            if stage.value in rows
        )

    def report(self, run_id: str) -> AutonomyRunReport:
        row = self._run_row(run_id)
        plan = self.load_plan(run_id)
        checkpoints = self.checkpoints(run_id)
        state = AutonomyRunState(row["state"])
        checkpoint_map = {item.stage: item for item in checkpoints}
        next_stage: AutonomyStage | None = None
        if state in {
            AutonomyRunState.CREATED,
            AutonomyRunState.RUNNING,
            AutonomyRunState.INTERRUPTED,
            AutonomyRunState.REVIEW_REQUIRED,
            AutonomyRunState.BLOCKED,
        }:
            for stage in plan.stages:
                item = checkpoint_map.get(stage)
                if item is None or item.state is not StageState.COMPLETED:
                    next_stage = stage
                    break
        return AutonomyRunReport(
            run_id=run_id,
            plan_id=plan.plan_id,
            client_id=plan.client_id,
            state=state,
            next_stage=next_stage,
            stages=checkpoints,
            updated_at=_parse_datetime(row["updated_at"]),
        )

    def _run_row(self, run_id: str) -> sqlite3.Row:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM autonomy_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown autonomy run: {run_id}")
        return row

    def _ensure_schema(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS autonomy_runs (
                        run_id TEXT PRIMARY KEY,
                        plan_id TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        plan_digest TEXT NOT NULL,
                        plan_json TEXT NOT NULL,
                        state TEXT NOT NULL,
                        lease_token TEXT,
                        lease_expires_at TEXT,
                        cancel_reason TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS autonomy_checkpoints (
                        run_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        state TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        output_json TEXT,
                        output_hash TEXT,
                        attempt INTEGER NOT NULL,
                        completed_at TEXT NOT NULL,
                        error TEXT,
                        PRIMARY KEY (run_id, stage),
                        FOREIGN KEY (run_id) REFERENCES autonomy_runs(run_id)
                    );
                    """
                )
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(autonomy_runs)"
                    ).fetchall()
                }
                if "lease_token" not in columns:
                    connection.execute(
                        "ALTER TABLE autonomy_runs ADD COLUMN lease_token TEXT"
                    )
                if "lease_expires_at" not in columns:
                    connection.execute(
                        "ALTER TABLE autonomy_runs ADD COLUMN lease_expires_at TEXT"
                    )


class CheckpointedAutonomyRunner:
    def __init__(
        self,
        store: SQLiteAutonomyStore,
        *,
        processors: Mapping[AutonomyStage, Processor],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.processors = dict(processors)
        if any(
            not isinstance(processor, TrustedPreparationProcessor)
            for processor in self.processors.values()
        ):
            raise TypeError(
                "raw processor callables are forbidden; use "
                "trusted_preparation_processor() only for reviewed synthetic "
                "preparation code, and an external OS sandbox for untrusted code"
            )
        self.clock = clock or _utc_now

    def create_run(self, plan: AutonomyPlan) -> str:
        return self.store.create(plan, created_at=self.clock())

    def run(self, *, run_id: str, client_id: str) -> AutonomyRunReport:
        plan = self._authorized_plan(run_id, client_id)
        current_state = self.store.state(run_id)
        if current_state in {
            AutonomyRunState.CANCELLED,
            AutonomyRunState.AWAITING_HUMAN_DECISION,
            AutonomyRunState.REVIEW_REQUIRED,
            AutonomyRunState.BLOCKED,
        }:
            return self.store.report(run_id)
        lease_token = secrets.token_hex(32)
        if not self._acquire_or_wait_for_execution(run_id, lease_token):
            return self.store.report(run_id)
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_execution,
            args=(run_id, lease_token, heartbeat_stop),
            daemon=True,
            name="accounting-agent-autonomy-heartbeat",
        )
        heartbeat.start()
        try:
            return self._run_leased(run_id, plan, lease_token)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)

    def _run_leased(
        self,
        run_id: str,
        plan: AutonomyPlan,
        lease_token: str,
    ) -> AutonomyRunReport:
        completed = {
            item.stage: item
            for item in self.store.checkpoints(run_id)
            if item.state is StageState.COMPLETED
        }
        for stage in plan.stages:
            if stage in completed:
                continue
            if not self.store.execution_lease_is_owned(
                run_id, lease_token, now=self.clock()
            ):
                return self.store.report(run_id)
            previous = {item.stage: item for item in self.store.checkpoints(run_id)}.get(stage)
            attempt = (previous.attempt if previous is not None else 0) + 1
            processor = self.processors.get(stage)
            if processor is None:
                checkpoint = StageCheckpoint(
                    stage=stage,
                    state=StageState.BLOCKED,
                    summary="No approved processor is configured for this stage.",
                    output_hash=None,
                    attempt=attempt,
                    completed_at=self.clock(),
                    error="processor_missing",
                )
                self.store.commit_checkpoint_if_leased(
                    run_id,
                    checkpoint,
                    lease_token=lease_token,
                    output=None,
                    run_state=AutonomyRunState.BLOCKED,
                )
                return self.store.report(run_id)
            if processor.environment != plan.environment:
                checkpoint = StageCheckpoint(
                    stage=stage,
                    state=StageState.BLOCKED,
                    summary="Trusted processor environment does not match the run.",
                    output_hash=None,
                    attempt=attempt,
                    completed_at=self.clock(),
                    error="processor_environment_mismatch",
                )
                self.store.commit_checkpoint_if_leased(
                    run_id,
                    checkpoint,
                    lease_token=lease_token,
                    output=None,
                    run_state=AutonomyRunState.BLOCKED,
                )
                return self.store.report(run_id)
            capabilities = PreparationCapabilities(plan.permission_ceiling)
            context = StageContext(
                run_id=run_id,
                plan=plan,
                stage=stage,
                attempt=attempt,
                prior_output_hashes=tuple(
                    item.output_hash
                    for item in self.store.checkpoints(run_id)
                    if item.output_hash is not None
                ),
                capabilities=capabilities,
            )
            try:
                result = processor(context)
                if capabilities.denied:
                    raise ProcessorCapabilityDenied(
                        "processor attempted denied capabilities: "
                        + ", ".join(dict.fromkeys(capabilities.denied))
                    )
                if not self.store.execution_lease_is_owned(
                    run_id, lease_token, now=self.clock()
                ):
                    return self.store.report(run_id)
                if not isinstance(result, ProcessorResult):
                    raise TypeError("processor must return ProcessorResult")
            except Exception as exc:
                checkpoint = StageCheckpoint(
                    stage=stage,
                    state=StageState.FAILED,
                    summary="Stage interrupted before a valid checkpoint was produced.",
                    output_hash=None,
                    attempt=attempt,
                    completed_at=self.clock(),
                    error=f"{type(exc).__name__}: {exc}",
                )
                self.store.commit_checkpoint_if_leased(
                    run_id,
                    checkpoint,
                    lease_token=lease_token,
                    output=None,
                    run_state=AutonomyRunState.INTERRUPTED,
                )
                return self.store.report(run_id)
            output_hash = _canonical_hash(result.output)
            if result.blocked_reason:
                state = StageState.BLOCKED
                run_state = AutonomyRunState.BLOCKED
            elif result.requires_review:
                state = StageState.REVIEW_REQUIRED
                run_state = AutonomyRunState.REVIEW_REQUIRED
            else:
                state = StageState.COMPLETED
                run_state = AutonomyRunState.RUNNING
            checkpoint = StageCheckpoint(
                stage=stage,
                state=state,
                summary=result.summary,
                output_hash=output_hash,
                attempt=attempt,
                completed_at=self.clock(),
                error=result.blocked_reason,
            )
            if not self.store.commit_checkpoint_if_leased(
                run_id,
                checkpoint,
                lease_token=lease_token,
                output=result.output,
                run_state=run_state,
            ):
                return self.store.report(run_id)
            if run_state is not AutonomyRunState.RUNNING:
                return self.store.report(run_id)
            completed[stage] = checkpoint
        self.store.finish_execution_if_leased(
            run_id,
            lease_token=lease_token,
            updated_at=self.clock(),
        )
        return self.store.report(run_id)

    def cancel(self, *, run_id: str, client_id: str, reason: str) -> None:
        plan = self._authorized_plan(run_id, client_id)
        _canonical_text(reason, "reason")
        self.store.cancel_run(
            run_id,
            plan,
            reason=reason,
            updated_at=self.clock(),
        )

    def _authorized_plan(self, run_id: str, client_id: str) -> AutonomyPlan:
        canonical = canonical_client_id(client_id)
        plan = self.store.load_plan(run_id)
        if plan.client_id != canonical:
            raise PermissionError("autonomy run belongs to a different client")
        return plan

    def _acquire_or_wait_for_execution(
        self,
        run_id: str,
        lease_token: str,
    ) -> bool:
        deadline = time.monotonic() + ACTIVE_EXECUTION_WAIT_SECONDS
        while True:
            now = self.clock()
            if self.store.acquire_execution_lease(
                run_id,
                lease_token=lease_token,
                updated_at=now,
                expires_at=now + EXECUTION_LEASE_TTL,
            ):
                return True
            state = self.store.state(run_id)
            if state not in {
                AutonomyRunState.CREATED,
                AutonomyRunState.RUNNING,
                AutonomyRunState.INTERRUPTED,
            }:
                return False
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for the active autonomy execution")
            time.sleep(ACTIVE_EXECUTION_POLL_SECONDS)

    def _heartbeat_execution(
        self,
        run_id: str,
        lease_token: str,
        stop: threading.Event,
    ) -> None:
        while not stop.wait(EXECUTION_HEARTBEAT_SECONDS):
            now = self.clock()
            if not self.store.heartbeat_execution_lease(
                run_id,
                lease_token=lease_token,
                updated_at=now,
                expires_at=now + EXECUTION_LEASE_TTL,
            ):
                return


def _upsert_checkpoint(
    connection: sqlite3.Connection,
    run_id: str,
    checkpoint: StageCheckpoint,
    output_json: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO autonomy_checkpoints (
            run_id, stage, state, summary, output_json, output_hash,
            attempt, completed_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, stage) DO UPDATE SET
            state = excluded.state,
            summary = excluded.summary,
            output_json = excluded.output_json,
            output_hash = excluded.output_hash,
            attempt = excluded.attempt,
            completed_at = excluded.completed_at,
            error = excluded.error
        """,
        (
            run_id,
            checkpoint.stage.value,
            checkpoint.state.value,
            checkpoint.summary,
            output_json,
            checkpoint.output_hash,
            checkpoint.attempt,
            checkpoint.completed_at.isoformat(),
            checkpoint.error,
        ),
    )


def _checkpoint_from_row(row: sqlite3.Row) -> StageCheckpoint:
    return StageCheckpoint(
        stage=AutonomyStage(row["stage"]),
        state=StageState(row["state"]),
        summary=row["summary"],
        output_hash=row["output_hash"],
        attempt=int(row["attempt"]),
        completed_at=_parse_datetime(row["completed_at"]),
        error=row["error"],
    )


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _utc_now() -> datetime:
    return datetime.now(UTC)
