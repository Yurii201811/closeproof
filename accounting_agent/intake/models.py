"""Typed intake models shared by local and future connector adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class IntakeSourceType(str, Enum):
    OUTLOOK_EMAIL_ATTACHMENT = "outlook_email_attachment"
    ONEDRIVE_FOLDER_FILE = "onedrive_folder_file"
    MANUAL_LOCAL_UPLOAD = "manual_local_upload"
    TEAMS_MESSAGE_FILE = "teams_message_file"


@dataclass(frozen=True)
class IntakeSource:
    source_type: IntakeSourceType
    file_path: Path
    source_reference: str
    source_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ClientMappingRule:
    rule_id: str
    match_type: str
    pattern: str
    client_id: str
    priority: int = 100


@dataclass(frozen=True)
class ClientMappingResult:
    client_id: str
    rule_id: str | None
    reason: str


@dataclass(frozen=True)
class IntakeCase:
    case_id: str
    source_type: IntakeSourceType
    source_reference: str
    source_fingerprint: str
    original_path: str
    stored_path: str
    storage_mode: str
    file_name: str
    content_type: str | None
    file_size: int
    sha256: str
    client_id: str
    client_mapping_rule: str | None
    source_metadata: dict[str, Any]
    invoice_metadata: dict[str, Any]
    invoice_duplicate_key: str | None
    duplicate_of_case_id: str | None
    duplicate_reasons: tuple[str, ...]
    status: str
    created_at: str


@dataclass(frozen=True)
class ExtractionTask:
    task_id: str
    case_id: str
    task_type: str
    status: str
    payload: dict[str, Any]
    created_at: str
