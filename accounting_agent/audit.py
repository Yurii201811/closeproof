"""Append-only local audit log helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


SENSITIVE_KEY_PARTS = (
    "account_number",
    "bank_account",
    "bank_details",
    "bankgiro",
    "bic",
    "credential",
    "document_text",
    "email",
    "iban",
    "ocr_text",
    "password",
    "phone",
    "plusgiro",
    "raw_text",
    "secret",
    "token",
)


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    case_id: str
    client_id: str
    actor: str
    action: str
    details: dict[str, Any]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "case_id": self.case_id,
            "client_id": self.client_id,
            "actor": self.actor,
            "action": self.action,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
        }


class JsonlAuditLog:
    """Small append-only JSONL audit log for local approval decisions."""

    def __init__(self, path: str | Path, *, clock: Any | None = None) -> None:
        self.path = Path(path)
        self.clock = clock or _utc_now

    def append_event(
        self,
        *,
        event_type: str,
        case_id: str,
        client_id: str,
        actor: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            case_id=case_id,
            client_id=client_id,
            actor=actor,
            action=action,
            details=_redact(details or {}),
            created_at=self.clock(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        return event

    def read_events(self) -> tuple[AuditEvent, ...]:
        if not self.path.exists():
            return ()
        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                data = json.loads(line)
                events.append(
                    AuditEvent(
                        event_type=str(data["event_type"]),
                        case_id=str(data["case_id"]),
                        client_id=str(data["client_id"]),
                        actor=str(data["actor"]),
                        action=str(data["action"]),
                        details=dict(data.get("details", {})),
                        created_at=_parse_datetime(data["created_at"]),
                    )
                )
        return tuple(events)


def _redact(value: Any) -> Any:
    if dataclass_is_instance(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, tuple | list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and len(value) > 240:
        return value[:237] + "..."
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def dataclass_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__") and not isinstance(value, type)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(UTC)
