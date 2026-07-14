"""Local exported-file intake helpers.

This module stores normalized metadata plus either references or safe local
copies. It is for local exports/manual uploads only and does not call Microsoft
Graph, email, or live document systems.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from accounting_agent.client_identity import canonical_client_id, client_storage_key
from accounting_agent.documents.hash import file_sha256
from accounting_agent.documents.invoice_metadata import InvoiceMetadata, extract_invoice_metadata

from .models import (
    ClientMappingResult,
    ClientMappingRule,
    IntakeCase,
    IntakeSource,
    IntakeSourceType,
)
from .store import SQLiteIntakeStore, utc_now_iso


class ClientMapper:
    """Deterministic local client mapping from metadata and path rules."""

    def __init__(
        self,
        rules: Iterable[ClientMappingRule] = (),
        *,
        default_client_id: str = "unmapped",
    ) -> None:
        self.rules = tuple(sorted(rules, key=lambda rule: (rule.priority, rule.rule_id)))
        self.default_client_id = canonical_client_id(default_client_id)

    @classmethod
    def from_store(
        cls,
        store: SQLiteIntakeStore,
        *,
        default_client_id: str = "unmapped",
    ) -> "ClientMapper":
        return cls(store.list_client_mapping_rules(), default_client_id=default_client_id)

    def map(self, source: IntakeSource) -> ClientMappingResult:
        return self.map_client(source)

    def map_client(
        self,
        source: IntakeSource,
        invoice_metadata: InvoiceMetadata | None = None,
    ) -> ClientMappingResult:
        metadata = {str(key).lower(): str(value).lower() for key, value in source.source_metadata.items()}
        invoice_metadata = invoice_metadata or InvoiceMetadata()
        path_text = str(source.file_path).lower()
        reference_text = source.source_reference.lower()
        supplier_text = (invoice_metadata.supplier or "").lower()
        sender = _extract_email(metadata.get("sender") or metadata.get("from") or "")
        domain = sender.split("@", 1)[1] if "@" in sender else metadata.get("sender_domain", "")
        folder = metadata.get("folder_path") or metadata.get("folder") or path_text

        for rule in self.rules:
            match_type = rule.match_type.strip().lower()
            pattern = rule.pattern.strip().lower()
            if match_type == "sender" and sender == pattern:
                return ClientMappingResult(
                    canonical_client_id(rule.client_id), rule.rule_id, "sender"
                )
            if match_type == "domain" and domain == pattern:
                return ClientMappingResult(
                    canonical_client_id(rule.client_id), rule.rule_id, "domain"
                )
            if match_type == "folder" and pattern in folder:
                return ClientMappingResult(
                    canonical_client_id(rule.client_id), rule.rule_id, "folder"
                )
            if match_type == "source_metadata":
                if any(pattern in value for value in metadata.values()):
                    return ClientMappingResult(
                        canonical_client_id(rule.client_id),
                        rule.rule_id,
                        "source_metadata",
                    )
            elif match_type == "path_contains" and pattern in path_text:
                return ClientMappingResult(
                    canonical_client_id(rule.client_id), rule.rule_id, "path_contains"
                )
            elif match_type == "reference_contains" and pattern in reference_text:
                return ClientMappingResult(
                    canonical_client_id(rule.client_id),
                    rule.rule_id,
                    "reference_contains",
                )
            elif match_type == "supplier_contains" and pattern in supplier_text:
                return ClientMappingResult(
                    canonical_client_id(rule.client_id),
                    rule.rule_id,
                    "supplier_contains",
                )
            elif match_type == "default":
                return ClientMappingResult(
                    canonical_client_id(rule.client_id), rule.rule_id, "default"
                )
        return ClientMappingResult(self.default_client_id, None, "no_matching_rule")


class LocalIntakeProcessor:
    """Normalize local document sources into intake cases and extraction tasks."""

    def __init__(
        self,
        *,
        store: SQLiteIntakeStore,
        storage_root: str | Path | None = None,
        client_mapper: ClientMapper | None = None,
        copy_files: bool = True,
        id_factory: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.store = store
        self.storage_root = Path(storage_root) if storage_root is not None else None
        self.client_mapper = client_mapper or ClientMapper.from_store(store)
        self.copy_files = copy_files
        self.id_factory = id_factory or (lambda prefix: f"{prefix}_{uuid.uuid4().hex}")
        self.clock = clock or utc_now_iso

    def process_source(self, source: IntakeSource) -> IntakeCase:
        path = Path(source.file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"intake source file does not exist: {path}")

        sha256 = file_sha256(path)
        invoice_metadata = extract_invoice_metadata(path)
        raw_mapping = self.client_mapper.map_client(source, invoice_metadata)
        mapping = ClientMappingResult(
            canonical_client_id(raw_mapping.client_id),
            raw_mapping.rule_id,
            raw_mapping.reason,
        )
        source_fingerprint = _source_fingerprint(
            source,
            sha256,
            client_id=mapping.client_id,
        )
        existing = self.store.get_case_by_source_fingerprint(source_fingerprint)
        if existing is not None:
            return existing
        legacy_existing = self.store.get_case_by_source_fingerprint(
            _legacy_v01_source_fingerprint(source, sha256)
        )
        if legacy_existing is not None and legacy_existing.client_id == mapping.client_id:
            # v0.1 fingerprints were global and omitted the client.  Reuse a
            # same-client row for idempotency, but never let that global key
            # link a new client to the legacy owner.
            return legacy_existing
        duplicate_of, duplicate_reasons = self._find_duplicate(
            sha256=sha256,
            client_id=mapping.client_id,
            invoice_duplicate_key=invoice_metadata.duplicate_key(client_id=mapping.client_id),
        )
        now = self.clock()
        stored_path, storage_mode = self._store_file(
            path,
            sha256,
            client_id=mapping.client_id,
        )
        source_metadata = _jsonable_mapping(source.source_metadata)
        source_metadata["client_mapping_reason"] = mapping.reason
        case = IntakeCase(
            case_id=self.id_factory("case"),
            source_type=source.source_type,
            source_reference=source.source_reference,
            source_fingerprint=source_fingerprint,
            original_path=str(path),
            stored_path=str(stored_path),
            storage_mode=storage_mode,
            file_name=path.name,
            content_type=mimetypes.guess_type(path.name)[0],
            file_size=path.stat().st_size,
            sha256=sha256,
            client_id=mapping.client_id,
            client_mapping_rule=mapping.rule_id,
            source_metadata=source_metadata,
            invoice_metadata=invoice_metadata.to_dict(),
            invoice_duplicate_key=invoice_metadata.duplicate_key(client_id=mapping.client_id),
            duplicate_of_case_id=duplicate_of.case_id if duplicate_of is not None else None,
            duplicate_reasons=tuple(duplicate_reasons),
            status="duplicate_review" if duplicate_reasons else "queued_for_extraction",
            created_at=now,
        )
        self.store.insert_case(case)
        self.store.enqueue_extraction_task(
            task_id=self.id_factory("extract"),
            case_id=case.case_id,
            payload={
                "source_type": case.source_type.value,
                "stored_path": case.stored_path,
                "sha256": case.sha256,
                "client_id": case.client_id,
                "duplicate_reasons": list(case.duplicate_reasons),
                "invoice_metadata": case.invoice_metadata,
            },
            created_at=now,
        )
        self.store.add_audit_event(
            event_id=self.id_factory("audit"),
            event_type="intake_case_created",
            case_id=case.case_id,
            payload={
                "source_type": case.source_type.value,
                "source_reference": case.source_reference,
                "storage_mode": case.storage_mode,
                "sha256": case.sha256,
                "client_id": case.client_id,
                "duplicate_reasons": list(case.duplicate_reasons),
            },
            created_at=now,
        )
        if case.duplicate_reasons:
            self.store.add_audit_event(
                event_id=self.id_factory("audit"),
                event_type="intake_duplicate_detected",
                case_id=case.case_id,
                payload={
                    "duplicate_of_case_id": case.duplicate_of_case_id,
                    "duplicate_reasons": list(case.duplicate_reasons),
                },
                created_at=now,
            )
        self.store.add_audit_event(
            event_id=self.id_factory("audit"),
            event_type="extraction_task_queued",
            case_id=case.case_id,
            payload={"task_type": "extract_document"},
            created_at=now,
        )
        return case

    def ingest(self, source: IntakeSource) -> IntakeCase:
        return self.process_source(source)

    def scan_folder(
        self,
        folder_path: str | Path,
        *,
        source_type: IntakeSourceType = IntakeSourceType.ONEDRIVE_FOLDER_FILE,
    ) -> tuple[IntakeCase, ...]:
        folder = Path(folder_path).expanduser().resolve()
        if not folder.is_dir():
            raise NotADirectoryError(f"intake folder does not exist: {folder}")

        cases: list[IntakeCase] = []
        for file_path in sorted(path for path in folder.rglob("*") if path.is_file()):
            relative_path = file_path.relative_to(folder).as_posix()
            source = IntakeSource(
                source_type=source_type,
                file_path=file_path,
                source_reference=f"{source_type.value}://local-sample/{relative_path}",
                source_metadata={
                    "folder_path": str(file_path.parent),
                    "relative_path": relative_path,
                    "mock_scan": True,
                },
            )
            cases.append(self.process_source(source))
        return tuple(cases)

    def _find_duplicate(
        self,
        *,
        sha256: str,
        client_id: str,
        invoice_duplicate_key: str | None,
    ) -> tuple[IntakeCase | None, tuple[str, ...]]:
        duplicate_of: IntakeCase | None = None
        reasons: list[str] = []
        by_hash = self.store.find_duplicate_by_hash(client_id, sha256)
        if by_hash is not None:
            duplicate_of = by_hash
            reasons.append("sha256")
        if invoice_duplicate_key:
            by_invoice = self.store.find_duplicate_by_invoice_key(client_id, invoice_duplicate_key)
            if by_invoice is not None:
                duplicate_of = duplicate_of or by_invoice
                reasons.append("invoice_metadata")
        return duplicate_of, tuple(reasons)

    def _store_file(
        self,
        source_path: Path,
        sha256: str,
        *,
        client_id: str,
    ) -> tuple[Path, str]:
        if not self.copy_files:
            return source_path, "referenced"
        if self.storage_root is None:
            return source_path, "reference_only"

        storage_key = client_storage_key(client_id)
        target_dir = (
            self.storage_root
            / "clients"
            / storage_key
            / "documents"
            / sha256[:2]
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{sha256}-{source_path.name}"
        if not target_path.exists():
            shutil.copy2(source_path, target_path)
        return target_path, "copied"


def manual_upload_source(
    file_path: str | Path,
    *,
    uploaded_by: str | None = None,
    note: str | None = None,
    source_reference: str | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> IntakeSource:
    path = Path(file_path)
    metadata = dict(source_metadata or {})
    if uploaded_by is not None:
        metadata["uploaded_by"] = uploaded_by
    if note is not None:
        metadata["note"] = note
    return IntakeSource(
        source_type=IntakeSourceType.MANUAL_LOCAL_UPLOAD,
        file_path=path,
        source_reference=source_reference or f"manual://local/{path.expanduser().resolve()}",
        source_metadata=metadata,
    )


def onedrive_file_source(
    file_path: str | Path,
    *,
    drive_item_id: str | None = None,
    folder_path: str | None = None,
    drive_id: str | None = None,
    item_id: str | None = None,
    created_by: str | None = None,
    modified_at: str | datetime | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> IntakeSource:
    metadata = dict(source_metadata or {})
    metadata.update(
        {
            key: value
            for key, value in {
                "folder_path": folder_path,
                "drive_id": drive_id,
                "item_id": item_id or drive_item_id,
                "created_by": created_by,
                "modified_at": modified_at,
            }.items()
            if value is not None
        }
    )
    if drive_id and (item_id or drive_item_id):
        source_reference = f"onedrive://drives/{drive_id}/items/{item_id or drive_item_id}"
    else:
        source_reference = drive_item_id or f"onedrive://local-sample/{Path(file_path).name}"
    return IntakeSource(
        source_type=IntakeSourceType.ONEDRIVE_FOLDER_FILE,
        file_path=Path(file_path),
        source_reference=source_reference,
        source_metadata=metadata,
    )


def outlook_attachment_source(
    file_path: str | Path,
    *,
    message_id: str,
    attachment_id: str,
    sender: str | None = None,
    received_at: str | datetime | None = None,
    subject: str | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> IntakeSource:
    metadata = dict(source_metadata or {})
    metadata.update(
        {
            key: value
            for key, value in {
                "sender": sender,
                "sender_domain": _email_domain(sender or ""),
                "received_at": received_at,
                "message_id": message_id,
                "attachment_id": attachment_id,
                "subject": subject,
            }.items()
            if value is not None
        }
    )
    return IntakeSource(
        source_type=IntakeSourceType.OUTLOOK_EMAIL_ATTACHMENT,
        file_path=Path(file_path),
        source_reference=f"outlook://messages/{message_id}/attachments/{attachment_id}",
        source_metadata=metadata,
    )


def teams_message_file_source(
    file_path: str | Path,
    *,
    team_id: str | None = None,
    channel_id: str | None = None,
    message_id: str,
    file_id: str,
    sender: str | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> IntakeSource:
    metadata = dict(source_metadata or {})
    metadata.update(
        {
            key: value
            for key, value in {
                "team_id": team_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "file_id": file_id,
                "sender": sender,
                "sender_domain": _email_domain(sender or ""),
                "connector_status": "future_interface_only",
            }.items()
            if value is not None
        }
    )
    if team_id and channel_id:
        source_reference = (
            f"teams://teams/{team_id}/channels/{channel_id}/messages/{message_id}/files/{file_id}"
        )
    else:
        source_reference = f"teams://messages/{message_id}/files/{file_id}"
    return IntakeSource(
        source_type=IntakeSourceType.TEAMS_MESSAGE_FILE,
        file_path=Path(file_path),
        source_reference=source_reference,
        source_metadata=metadata,
    )


def _source_fingerprint(
    source: IntakeSource,
    sha256: str,
    *,
    client_id: str,
) -> str:
    canonical = canonical_client_id(client_id)
    material = json.dumps(
        [
            canonical,
            source.source_type.value,
            source.source_reference,
            str(source.file_path),
            sha256,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _legacy_v01_source_fingerprint(source: IntakeSource, sha256: str) -> str:
    material = "|".join(
        (
            source.source_type.value,
            source.source_reference,
            str(source.file_path),
            sha256,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _jsonable_mapping(metadata: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, datetime):
            result[str(key)] = value.isoformat()
        elif isinstance(value, Path):
            result[str(key)] = str(value)
        else:
            result[str(key)] = value
    return result


def _extract_email(value: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+", value)
    return match.group(0).lower() if match else value.strip().lower()


def _email_domain(value: str) -> str | None:
    email = _extract_email(value)
    if "@" not in email:
        return None
    return email.split("@", 1)[1]
