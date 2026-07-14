from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .client_identity import (
    canonical_client_id,
    client_storage_key,
)


LOCAL_QUEUE_SCHEMA_VERSION = 3


class QueueSchemaError(RuntimeError):
    """Raised when a queue schema cannot be upgraded without guessing scope."""


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS intake_cases (
    case_id TEXT PRIMARY KEY,
    fixture_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_hash TEXT PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE REFERENCES intake_cases(case_id),
    source_path TEXT NOT NULL,
    invoice_signature TEXT NOT NULL,
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    supplier_name TEXT,
    supplier_org_number TEXT,
    invoice_number TEXT,
    invoice_date TEXT,
    gross_amount TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_invoice_signature
    ON documents(invoice_signature);

CREATE TABLE IF NOT EXISTS extracted_fields (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounting_proposals (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    proposal_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    decision_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_packets (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    packet_json TEXT NOT NULL,
    packet_path TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT REFERENCES intake_cases(case_id),
    client_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    identity_scope_version INTEGER NOT NULL DEFAULT 3,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class LocalQueue:
    """SQLite persistence for local MVP queue and audit records."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if schema_version > LOCAL_QUEUE_SCHEMA_VERSION:
                raise QueueSchemaError(
                    "Queue schema is newer than this runtime; refusing an unsafe downgrade"
                )
            connection.executescript(SCHEMA_SQL)
            self._ensure_scope_columns(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_client_entity_signature
                    ON documents(client_id, entity_id, invoice_signature)
                """
            )
            connection.execute(f"PRAGMA user_version = {LOCAL_QUEUE_SCHEMA_VERSION}")

    def schema_version(self) -> int:
        self.initialize()
        with self.session() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def session(self) -> Any:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def find_duplicate_signature(
        self,
        invoice_signature: str,
        current_case_id: str,
        *,
        client_id: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        canonical_client = canonical_client_id(client_id)
        canonical_entity = canonical_client_id(entity_id)
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT case_id, source_path, supplier_name, invoice_number,
                       invoice_date, gross_amount, created_at
                FROM documents
                WHERE client_id = ?
                  AND entity_id = ?
                  AND identity_scope_version = ?
                  AND invoice_signature = ?
                ORDER BY created_at ASC, case_id ASC
                """,
                (
                    canonical_client,
                    canonical_entity,
                    LOCAL_QUEUE_SCHEMA_VERSION,
                    invoice_signature,
                ),
            ).fetchall()

            legacy_signatures = _legacy_unscoped_signatures(
                invoice_signature,
                client_id=canonical_client,
                entity_id=canonical_entity,
            )
            legacy_row = connection.execute(
                """
                SELECT 1
                FROM documents
                WHERE (
                        client_id IS NULL
                        OR entity_id IS NULL
                        OR identity_scope_version < ?
                      )
                  AND (client_id IS NULL OR client_id = ?)
                  AND case_id != ?
                  AND invoice_signature IN (?, ?, ?)
                LIMIT 1
                """,
                (
                    LOCAL_QUEUE_SCHEMA_VERSION,
                    canonical_client,
                    current_case_id,
                    *legacy_signatures,
                ),
            ).fetchone()

        if not rows:
            if legacy_row is None:
                return None
            # A legacy row has no trustworthy legal-entity owner. Do not expose
            # or link its case/path; return only a hard-stop marker until an
            # operator explicitly maps both client and entity scope.
            return {"scope_status": "legacy_unscoped_review"}

        first = dict(rows[0])
        for row in rows:
            if row["case_id"] == current_case_id:
                return None if first["case_id"] == current_case_id else first

        return first

    def map_legacy_rows_to_client(self, client_id: str) -> int:
        """Reject client-only migration because it cannot establish legal entity scope."""

        canonical_client_id(client_id)
        self.initialize()
        raise QueueSchemaError(
            "Legacy rows require explicit client_id and entity_id mapping; "
            "client-only assignment is forbidden"
        )

    def map_legacy_rows_to_entity(self, *, client_id: str, entity_id: str) -> int:
        """Explicitly bind all legacy queue rows to one verified client/entity pair."""

        self.initialize()
        canonical_client = canonical_client_id(client_id)
        canonical_entity = canonical_client_id(entity_id)
        client_prefix = f"{client_storage_key(canonical_client)}|"
        entity_prefix = f"{client_storage_key(canonical_entity)}|"
        with self.session() as connection:
            legacy_cases = connection.execute(
                """
                SELECT case_id, client_id, entity_id
                FROM intake_cases
                WHERE client_id IS NULL
                   OR entity_id IS NULL
                   OR identity_scope_version < ?
                ORDER BY case_id
                """,
                (LOCAL_QUEUE_SCHEMA_VERSION,),
            ).fetchall()
            for row in legacy_cases:
                if row["client_id"] not in (None, canonical_client):
                    raise QueueSchemaError(
                        "Legacy queue contains a conflicting partial client mapping"
                    )
                if row["entity_id"] not in (None, canonical_entity):
                    raise QueueSchemaError(
                        "Legacy queue contains a conflicting partial entity mapping"
                    )

            legacy_documents = connection.execute(
                """
                SELECT doc_hash, invoice_signature, client_id, entity_id
                FROM documents
                WHERE client_id IS NULL
                   OR entity_id IS NULL
                   OR identity_scope_version < ?
                ORDER BY doc_hash
                """,
                (LOCAL_QUEUE_SCHEMA_VERSION,),
            ).fetchall()
            for row in legacy_documents:
                if row["client_id"] not in (None, canonical_client):
                    raise QueueSchemaError(
                        "Legacy queue contains a conflicting partial client mapping"
                    )
                if row["entity_id"] not in (None, canonical_entity):
                    raise QueueSchemaError(
                        "Legacy queue contains a conflicting partial entity mapping"
                    )
                unscoped_signature = str(row["invoice_signature"])
                if unscoped_signature.startswith(client_prefix):
                    unscoped_signature = unscoped_signature.removeprefix(client_prefix)
                if unscoped_signature.startswith(entity_prefix):
                    unscoped_signature = unscoped_signature.removeprefix(entity_prefix)
                connection.execute(
                    """
                    UPDATE documents
                    SET client_id = ?, entity_id = ?, identity_scope_version = ?,
                        invoice_signature = ?
                    WHERE doc_hash = ?
                    """,
                    (
                        canonical_client,
                        canonical_entity,
                        LOCAL_QUEUE_SCHEMA_VERSION,
                        client_prefix + entity_prefix + unscoped_signature,
                        row["doc_hash"],
                    ),
                )

            legacy_case_ids = tuple(str(row["case_id"]) for row in legacy_cases)
            if legacy_case_ids:
                placeholders = ", ".join("?" for _ in legacy_case_ids)
                connection.execute(
                    f"""
                    UPDATE intake_cases
                    SET client_id = ?, entity_id = ?, identity_scope_version = ?
                    WHERE case_id IN ({placeholders})
                    """,
                    (
                        canonical_client,
                        canonical_entity,
                        LOCAL_QUEUE_SCHEMA_VERSION,
                        *legacy_case_ids,
                    ),
                )
                for table_name in (
                    "extracted_fields",
                    "accounting_proposals",
                    "policy_decisions",
                    "approval_packets",
                    "audit_events",
                ):
                    connection.execute(
                        f"""
                        UPDATE {table_name}
                        SET client_id = ?, entity_id = ?, identity_scope_version = ?
                        WHERE case_id IN ({placeholders})
                        """,
                        (
                            canonical_client,
                            canonical_entity,
                            LOCAL_QUEUE_SCHEMA_VERSION,
                            *legacy_case_ids,
                        ),
                    )
        return len(legacy_documents)

    def store_pipeline_result(self, packet: dict[str, Any], packet_path: Path) -> None:
        self.initialize()
        now = packet["generated_at"]
        case = packet["case"]
        document = packet["document"]
        extracted = packet["extracted_fields"]
        client_id = canonical_client_id(str(case.get("client_id") or ""))
        entity_id = canonical_client_id(str(case.get("entity_id") or ""))
        scoped_file_hash = scoped_entity_identity_hash(
            client_id,
            entity_id,
            str(case["file_hash"]),
        )
        scoped_document_hash = scoped_entity_identity_hash(
            client_id,
            entity_id,
            str(document["file_hash"]),
        )

        with self.session() as connection:
            existing_case = connection.execute(
                """
                SELECT client_id, entity_id
                FROM intake_cases
                WHERE case_id = ?
                """,
                (case["case_id"],),
            ).fetchone()
            if existing_case is not None and (
                existing_case["client_id"] != client_id
                or existing_case["entity_id"] != entity_id
            ):
                raise QueueSchemaError(
                    "Existing case_id is bound to a different client or legal entity"
                )
            connection.execute(
                """
                INSERT INTO intake_cases (
                    case_id, fixture_name, source_path, file_hash,
                    client_id, entity_id, identity_scope_version, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    fixture_name = excluded.fixture_name,
                    source_path = excluded.source_path,
                    file_hash = excluded.file_hash,
                    client_id = excluded.client_id,
                    entity_id = excluded.entity_id,
                    identity_scope_version = excluded.identity_scope_version,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    case["case_id"],
                    case["fixture_name"],
                    case["source_path"],
                    scoped_file_hash,
                    client_id,
                    entity_id,
                    LOCAL_QUEUE_SCHEMA_VERSION,
                    case["status"],
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO documents (
                    doc_hash, case_id, source_path, invoice_signature,
                    client_id, entity_id, identity_scope_version,
                    supplier_name, supplier_org_number, invoice_number,
                    invoice_date, gross_amount, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_hash) DO UPDATE SET
                    source_path = excluded.source_path,
                    invoice_signature = excluded.invoice_signature,
                    client_id = excluded.client_id,
                    entity_id = excluded.entity_id,
                    identity_scope_version = excluded.identity_scope_version,
                    supplier_name = excluded.supplier_name,
                    supplier_org_number = excluded.supplier_org_number,
                    invoice_number = excluded.invoice_number,
                    invoice_date = excluded.invoice_date,
                    gross_amount = excluded.gross_amount,
                    updated_at = excluded.updated_at
                """,
                (
                    scoped_document_hash,
                    case["case_id"],
                    case["source_path"],
                    document["invoice_signature"],
                    client_id,
                    entity_id,
                    LOCAL_QUEUE_SCHEMA_VERSION,
                    extracted.get("supplier_name"),
                    extracted.get("supplier_org_number"),
                    extracted.get("invoice_number"),
                    extracted.get("invoice_date"),
                    extracted["amounts"].get("gross"),
                    now,
                    now,
                ),
            )
            self._upsert_json(
                connection,
                "extracted_fields",
                "payload_json",
                case["case_id"],
                client_id,
                entity_id,
                extracted,
                now,
            )
            self._upsert_json(
                connection,
                "accounting_proposals",
                "proposal_json",
                case["case_id"],
                client_id,
                entity_id,
                packet["accounting_proposal"],
                now,
            )
            self._upsert_json(
                connection,
                "policy_decisions",
                "decision_json",
                case["case_id"],
                client_id,
                entity_id,
                packet["policy_decision"],
                now,
            )
            connection.execute(
                """
                INSERT INTO approval_packets (
                    case_id, client_id, entity_id, identity_scope_version,
                    packet_json, packet_path, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    client_id = excluded.client_id,
                    entity_id = excluded.entity_id,
                    identity_scope_version = excluded.identity_scope_version,
                    packet_json = excluded.packet_json,
                    packet_path = excluded.packet_path,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    case["case_id"],
                    client_id,
                    entity_id,
                    LOCAL_QUEUE_SCHEMA_VERSION,
                    _json(packet),
                    str(packet_path),
                    "pending_human_review",
                    now,
                ),
            )
            for event in packet["audit_events"]:
                connection.execute(
                    """
                    INSERT INTO audit_events (
                        case_id, client_id, entity_id, identity_scope_version,
                        event_type, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case["case_id"],
                        client_id,
                        entity_id,
                        LOCAL_QUEUE_SCHEMA_VERSION,
                        event["event_type"],
                        _json(event["payload"]),
                        event["created_at"],
                    ),
                )

    def count(self, table_name: str) -> int:
        if table_name not in {
            "intake_cases",
            "documents",
            "extracted_fields",
            "accounting_proposals",
            "policy_decisions",
            "approval_packets",
            "audit_events",
        }:
            raise ValueError(f"Unsupported table: {table_name}")
        self.initialize()
        with self.session() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])

    @staticmethod
    def _ensure_scope_columns(connection: sqlite3.Connection) -> None:
        for table_name in (
            "intake_cases",
            "documents",
            "extracted_fields",
            "accounting_proposals",
            "policy_decisions",
            "approval_packets",
            "audit_events",
        ):
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            if "client_id" not in columns:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN client_id TEXT")
            if "entity_id" not in columns:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN entity_id TEXT")
            if "identity_scope_version" not in columns:
                connection.execute(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN identity_scope_version INTEGER NOT NULL DEFAULT 1"
                )

    @staticmethod
    def _upsert_json(
        connection: sqlite3.Connection,
        table_name: str,
        json_column: str,
        case_id: str,
        client_id: str,
        entity_id: str,
        payload: dict[str, Any],
        updated_at: str,
    ) -> None:
        connection.execute(
            f"""
            INSERT INTO {table_name} (
                case_id, client_id, entity_id, identity_scope_version,
                {json_column}, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                client_id = excluded.client_id,
                entity_id = excluded.entity_id,
                identity_scope_version = excluded.identity_scope_version,
                {json_column} = excluded.{json_column},
                updated_at = excluded.updated_at
            """,
            (
                case_id,
                client_id,
                entity_id,
                LOCAL_QUEUE_SCHEMA_VERSION,
                _json(payload),
                updated_at,
            ),
        )


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def scoped_entity_identity_hash(
    client_id: str,
    entity_id: str,
    evidence_hash: str,
) -> str:
    client = canonical_client_id(client_id)
    entity = canonical_client_id(entity_id)
    material = (
        client.encode("utf-8")
        + b"\x00"
        + entity.encode("utf-8")
        + b"\x00"
        + evidence_hash.encode("utf-8")
    )
    return hashlib.sha256(material).hexdigest()


def _legacy_unscoped_signatures(
    invoice_signature: str,
    *,
    client_id: str,
    entity_id: str,
) -> tuple[str, str, str]:
    client_prefix = f"{client_storage_key(client_id)}|"
    prefix = client_prefix + f"{client_storage_key(entity_id)}|"
    if not invoice_signature.startswith(prefix):
        raise QueueSchemaError(
            "invoice signature does not match its declared client and entity scope"
        )
    unscoped = invoice_signature.removeprefix(prefix)
    return (unscoped, client_prefix + unscoped, invoice_signature)
