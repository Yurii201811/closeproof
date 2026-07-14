"""SQLite source of truth for local document intake cases."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from accounting_agent.client_identity import canonical_client_id

from .models import ClientMappingRule, ExtractionTask, IntakeCase, IntakeSourceType


class SQLiteIntakeStore:
    """Small local SQLite store for normalized intake cases and tasks."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = None
        self._ensure_schema()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def add_client_mapping_rule(self, rule: ClientMappingRule) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO client_mapping_rules (
                    rule_id, match_type, pattern, client_id, priority
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rule.rule_id,
                    rule.match_type,
                    rule.pattern,
                    canonical_client_id(rule.client_id),
                    rule.priority,
                ),
            )

    def list_client_mapping_rules(self) -> tuple[ClientMappingRule, ...]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT rule_id, match_type, pattern, client_id, priority
                FROM client_mapping_rules
                ORDER BY priority ASC, rule_id ASC
                """
            ).fetchall()
        return tuple(
            ClientMappingRule(
                rule_id=row["rule_id"],
                match_type=row["match_type"],
                pattern=row["pattern"],
                client_id=row["client_id"],
                priority=row["priority"],
            )
            for row in rows
        )

    def get_case_by_source_fingerprint(self, source_fingerprint: str) -> IntakeCase | None:
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM document_intake_cases
                WHERE source_fingerprint = ?
                """,
                (source_fingerprint,),
            ).fetchone()
        return _case_from_row(row) if row is not None else None

    def find_duplicate_by_hash(self, client_id: str, sha256: str) -> IntakeCase | None:
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM document_intake_cases
                WHERE client_id = ?
                  AND sha256 = ?
                ORDER BY created_at ASC, case_id ASC
                LIMIT 1
                """,
                (canonical_client_id(client_id), sha256),
            ).fetchone()
        return _case_from_row(row) if row is not None else None

    def find_duplicate_by_invoice_key(self, client_id: str, invoice_duplicate_key: str) -> IntakeCase | None:
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM document_intake_cases
                WHERE client_id = ?
                  AND invoice_duplicate_key = ?
                ORDER BY created_at ASC, case_id ASC
                LIMIT 1
                """,
                (canonical_client_id(client_id), invoice_duplicate_key),
            ).fetchone()
        return _case_from_row(row) if row is not None else None

    def insert_case(self, case: IntakeCase) -> None:
        canonical = canonical_client_id(case.client_id)
        if canonical != case.client_id:
            raise ValueError("IntakeCase client_id must already be canonical")
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO document_intake_cases (
                    case_id,
                    source_type,
                    source_reference,
                    source_fingerprint,
                    original_path,
                    stored_path,
                    storage_mode,
                    file_name,
                    content_type,
                    file_size,
                    sha256,
                    client_id,
                    client_mapping_rule,
                    source_metadata_json,
                    invoice_metadata_json,
                    invoice_duplicate_key,
                    duplicate_of_case_id,
                    duplicate_reasons_json,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.source_type.value,
                    case.source_reference,
                    case.source_fingerprint,
                    case.original_path,
                    case.stored_path,
                    case.storage_mode,
                    case.file_name,
                    case.content_type,
                    case.file_size,
                    case.sha256,
                    case.client_id,
                    case.client_mapping_rule,
                    _json(case.source_metadata),
                    _json(case.invoice_metadata),
                    case.invoice_duplicate_key,
                    case.duplicate_of_case_id,
                    _json(list(case.duplicate_reasons)),
                    case.status,
                    case.created_at,
                ),
            )

    def enqueue_extraction_task(
        self,
        *,
        task_id: str,
        case_id: str,
        payload: Mapping[str, Any],
        created_at: str,
    ) -> ExtractionTask:
        task = ExtractionTask(
            task_id=task_id,
            case_id=case_id,
            task_type="extract_document",
            status="queued",
            payload=dict(payload),
            created_at=created_at,
        )
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO extraction_tasks (
                    task_id, case_id, task_type, status, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.case_id,
                    task.task_type,
                    task.status,
                    _json(task.payload),
                    task.created_at,
                ),
            )
        return task

    def add_audit_event(
        self,
        *,
        event_id: str,
        event_type: str,
        case_id: str | None,
        payload: Mapping[str, Any],
        created_at: str,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO document_intake_audit_events (
                    event_id, event_type, case_id, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, event_type, case_id, _json(payload), created_at),
            )

    def list_cases(self) -> tuple[IntakeCase, ...]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM document_intake_cases
                ORDER BY created_at ASC, case_id ASC
                """
            ).fetchall()
        return tuple(_case_from_row(row) for row in rows)

    def list_extraction_tasks(self) -> tuple[ExtractionTask, ...]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM extraction_tasks
                ORDER BY created_at ASC, task_id ASC
                """
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def list_audit_events(self) -> tuple[dict[str, Any], ...]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, case_id, payload_json, created_at
                FROM document_intake_audit_events
                ORDER BY created_at ASC, event_id ASC
                """
            ).fetchall()
        return tuple(
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "case_id": row["case_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def _ensure_schema(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS document_intake_cases (
                    case_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL UNIQUE,
                    original_path TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    storage_mode TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content_type TEXT,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    client_mapping_rule TEXT,
                    source_metadata_json TEXT NOT NULL,
                    invoice_metadata_json TEXT NOT NULL,
                    invoice_duplicate_key TEXT,
                    duplicate_of_case_id TEXT,
                    duplicate_reasons_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS document_intake_cases_sha256_idx
                    ON document_intake_cases (client_id, sha256);
                CREATE INDEX IF NOT EXISTS document_intake_cases_invoice_duplicate_idx
                    ON document_intake_cases (client_id, invoice_duplicate_key);

                CREATE TABLE IF NOT EXISTS extraction_tasks (
                    task_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS extraction_tasks_case_id_idx
                    ON extraction_tasks (case_id);
                CREATE INDEX IF NOT EXISTS extraction_tasks_status_idx
                    ON extraction_tasks (status);

                CREATE TABLE IF NOT EXISTS client_mapping_rules (
                    rule_id TEXT PRIMARY KEY,
                    match_type TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    priority INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_intake_audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    case_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS document_intake_audit_events_case_id_idx
                    ON document_intake_audit_events (case_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        if self.database_path == ":memory:":
            if self._connection is None:
                self._connection = sqlite3.connect(":memory:")
                self._connection.row_factory = sqlite3.Row
            return self._connection

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            if self.database_path != ":memory:":
                connection.close()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _case_from_row(row: sqlite3.Row) -> IntakeCase:
    return IntakeCase(
        case_id=row["case_id"],
        source_type=IntakeSourceType(row["source_type"]),
        source_reference=row["source_reference"],
        source_fingerprint=row["source_fingerprint"],
        original_path=row["original_path"],
        stored_path=row["stored_path"],
        storage_mode=row["storage_mode"],
        file_name=row["file_name"],
        content_type=row["content_type"],
        file_size=row["file_size"],
        sha256=row["sha256"],
        client_id=row["client_id"],
        client_mapping_rule=row["client_mapping_rule"],
        source_metadata=json.loads(row["source_metadata_json"]),
        invoice_metadata=json.loads(row["invoice_metadata_json"]),
        invoice_duplicate_key=row["invoice_duplicate_key"],
        duplicate_of_case_id=row["duplicate_of_case_id"],
        duplicate_reasons=tuple(json.loads(row["duplicate_reasons_json"])),
        status=row["status"],
        created_at=row["created_at"],
    )


def _task_from_row(row: sqlite3.Row) -> ExtractionTask:
    return ExtractionTask(
        task_id=row["task_id"],
        case_id=row["case_id"],
        task_type=row["task_type"],
        status=row["status"],
        payload=json.loads(row["payload_json"]),
        created_at=row["created_at"],
    )


def _json(value: Any) -> str:
    return json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":"))


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_to_jsonable(item) for item in value]
    return value
