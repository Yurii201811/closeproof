"""Client-scoped, content-addressed evidence primitives for v1.

The store deliberately persists bytes under hashes rather than source filenames.
It is suitable for deterministic local fixtures and previews; encryption and an
authenticated tenant context remain deployment responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import fcntl

from .client_identity import canonical_client_id, client_storage_key


ZERO_HASH = "0" * 64
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


class EvidenceError(Exception):
    """Base class for evidence-store failures."""


class EvidenceScopeError(EvidenceError):
    """Raised when an evidence record is accessed from another client scope."""


class EvidenceIntegrityError(EvidenceError):
    """Raised when persisted evidence no longer matches its content hash."""


_EVENT_THREAD_LOCKS: dict[str, threading.RLock] = {}
_EVENT_THREAD_LOCKS_GUARD = threading.Lock()


@contextmanager
def _exclusive_event_lock(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = str(path.resolve())
    with _EVENT_THREAD_LOCKS_GUARD:
        thread_lock = _EVENT_THREAD_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        descriptor = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class FieldProvenance:
    """Trace one extracted field back to exact evidence and extractor context."""

    source_hash: str
    field_path: str
    extractor: str
    extractor_version: str
    page: int | None = None
    span: str | None = None
    bounding_box: tuple[float, float, float, float] | None = None
    transformation_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256(self.source_hash, "source_hash")
        for name, value in (
            ("field_path", self.field_path),
            ("extractor", self.extractor),
            ("extractor_version", self.extractor_version),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty canonical string")
        if self.page is not None and self.page < 1:
            raise ValueError("page must be one-based")
        if self.bounding_box is not None and len(self.bounding_box) != 4:
            raise ValueError("bounding_box must contain four coordinates")


@dataclass(frozen=True)
class EvidenceRecord:
    client_id: str
    evidence_id: str
    content_sha256: str
    media_type: str
    size_bytes: int
    created_at: datetime
    storage_key: str

    def __post_init__(self) -> None:
        canonical_client_id(self.client_id)
        _require_sha256(self.content_sha256, "content_sha256")
        if not self.evidence_id or not self.storage_key:
            raise ValueError("evidence identifiers must not be empty")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        _require_aware(self.created_at, "created_at")


class ContentAddressedEvidenceStore:
    """Filesystem-backed evidence bytes isolated by canonical client identity."""

    def __init__(self, root: str | Path, *, clock: Any | None = None) -> None:
        self.root = Path(root)
        self.clock = clock or _utc_now

    def put(self, *, client_id: str, content: bytes, media_type: str) -> EvidenceRecord:
        canonical = canonical_client_id(client_id)
        if not isinstance(content, bytes):
            raise TypeError("evidence content must be bytes")
        if not media_type or media_type != media_type.strip():
            raise ValueError("media_type must be a non-empty canonical string")
        content_hash = hashlib.sha256(content).hexdigest()
        object_path = self._object_path(canonical, content_hash)
        metadata_path = object_path.with_suffix(".json")
        if object_path.exists() or metadata_path.exists():
            record = self._load_metadata(metadata_path)
            if record.client_id != canonical or record.content_sha256 != content_hash:
                raise EvidenceIntegrityError("evidence metadata does not match its scope")
            if record.media_type != media_type:
                raise EvidenceIntegrityError("existing evidence media type does not match")
            if not self.verify(client_id=canonical, record=record):
                raise EvidenceIntegrityError("existing evidence bytes failed integrity verification")
            return record

        object_path.parent.mkdir(parents=True, exist_ok=True)
        created_at = self.clock()
        _require_aware(created_at, "clock result")
        scope_key = client_storage_key(canonical)
        record = EvidenceRecord(
            client_id=canonical,
            evidence_id=f"ev_{content_hash}",
            content_sha256=content_hash,
            media_type=media_type,
            size_bytes=len(content),
            created_at=created_at,
            storage_key=f"{scope_key}:{content_hash}",
        )
        _atomic_write_bytes(object_path, content)
        _atomic_write_text(
            metadata_path,
            json.dumps(_record_to_dict(record), sort_keys=True, separators=(",", ":")),
        )
        return record

    def read(self, *, client_id: str, record: EvidenceRecord) -> bytes:
        path = self.path_for(client_id=client_id, record=record)
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise EvidenceIntegrityError("evidence object is missing") from exc
        if hashlib.sha256(content).hexdigest() != record.content_sha256:
            raise EvidenceIntegrityError("evidence content hash mismatch")
        if len(content) != record.size_bytes:
            raise EvidenceIntegrityError("evidence byte size mismatch")
        return content

    def verify(self, *, client_id: str, record: EvidenceRecord) -> bool:
        try:
            self.read(client_id=client_id, record=record)
        except EvidenceError:
            return False
        return True

    def path_for(self, *, client_id: str, record: EvidenceRecord) -> Path:
        canonical = canonical_client_id(client_id)
        if record.client_id != canonical:
            raise EvidenceScopeError("evidence belongs to a different client")
        expected_key = f"{client_storage_key(canonical)}:{record.content_sha256}"
        if record.storage_key != expected_key:
            raise EvidenceIntegrityError("evidence storage key is not canonical")
        return self._object_path(canonical, record.content_sha256)

    def _object_path(self, client_id: str, content_hash: str) -> Path:
        _require_sha256(content_hash, "content_hash")
        return (
            self.root
            / client_storage_key(client_id)
            / "objects"
            / content_hash[:2]
            / content_hash
        )

    @staticmethod
    def _load_metadata(path: Path) -> EvidenceRecord:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return EvidenceRecord(
                client_id=str(data["client_id"]),
                evidence_id=str(data["evidence_id"]),
                content_sha256=str(data["content_sha256"]),
                media_type=str(data["media_type"]),
                size_bytes=int(data["size_bytes"]),
                created_at=_parse_datetime(data["created_at"]),
                storage_key=str(data["storage_key"]),
            )
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceIntegrityError("evidence metadata is missing or invalid") from exc


@dataclass(frozen=True)
class EventRecord:
    sequence: int
    previous_hash: str
    event_hash: str
    client_id: str
    event_type: str
    actor_id: str
    object_id: str
    details: dict[str, Any]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
            "client_id": self.client_id,
            "event_type": self.event_type,
            "actor_id": self.actor_id,
            "object_id": self.object_id,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class EventLogVerification:
    valid: bool
    event_count: int
    head_hash: str
    errors: tuple[str, ...] = ()


class HashChainedEventLog:
    """Append-only JSONL events with a separately anchored chain head."""

    def __init__(self, path: str | Path, *, clock: Any | None = None) -> None:
        self.path = Path(path)
        self.head_path = self.path.with_suffix(self.path.suffix + ".head.json")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.clock = clock or _utc_now

    def append(
        self,
        *,
        client_id: str,
        event_type: str,
        actor_id: str,
        object_id: str,
        details: dict[str, Any] | None = None,
        precondition: Callable[[tuple[EventRecord, ...]], None] | None = None,
    ) -> EventRecord:
        canonical = canonical_client_id(client_id)
        for name, value in (
            ("event_type", event_type),
            ("actor_id", actor_id),
            ("object_id", object_id),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty canonical string")
        with _exclusive_event_lock(self.lock_path):
            verification = self._verify_unlocked()
            if not verification.valid:
                raise EvidenceIntegrityError("cannot append to an invalid event chain")
            if precondition is not None:
                precondition(self._read_unlocked())
            created_at = self.clock()
            _require_aware(created_at, "clock result")
            payload = {
                "sequence": verification.event_count + 1,
                "previous_hash": verification.head_hash,
                "client_id": canonical,
                "event_type": event_type,
                "actor_id": actor_id,
                "object_id": object_id,
                "details": _redact(details or {}),
                "created_at": created_at.isoformat(),
            }
            event_hash = _canonical_hash(payload)
            event = EventRecord(
                sequence=verification.event_count + 1,
                previous_hash=verification.head_hash,
                event_hash=event_hash,
                client_id=canonical,
                event_type=event_type,
                actor_id=actor_id,
                object_id=object_id,
                details=payload["details"],
                created_at=created_at,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o600,
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        event.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            _atomic_write_text(
                self.head_path,
                json.dumps(
                    {"event_count": event.sequence, "head_hash": event.event_hash},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            return event

    def read(self) -> tuple[EventRecord, ...]:
        with _exclusive_event_lock(self.lock_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> tuple[EventRecord, ...]:
        if not self.path.exists():
            return ()
        events: list[EventRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            events.append(_event_from_dict(data))
        return tuple(events)

    def verify(self) -> EventLogVerification:
        with _exclusive_event_lock(self.lock_path):
            return self._verify_unlocked()

    def reset(self) -> None:
        """Atomically clear the event body and anchored head for a fresh demo."""

        with _exclusive_event_lock(self.lock_path):
            self.path.unlink(missing_ok=True)
            self.head_path.unlink(missing_ok=True)
            if self.path.parent.exists():
                _fsync_directory(self.path.parent)

    def _verify_unlocked(self) -> EventLogVerification:
        if not self.path.exists() and not self.head_path.exists():
            return EventLogVerification(True, 0, ZERO_HASH)
        errors: list[str] = []
        try:
            events = self._read_unlocked()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return EventLogVerification(False, 0, ZERO_HASH, ("event_log_invalid_json",))
        previous_hash = ZERO_HASH
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence != expected_sequence:
                errors.append(f"event_sequence_mismatch:{expected_sequence}")
            if event.previous_hash != previous_hash:
                errors.append(f"event_previous_hash_mismatch:{expected_sequence}")
            payload = event.to_dict()
            payload.pop("event_hash")
            calculated = _canonical_hash(payload)
            if event.event_hash != calculated:
                errors.append(f"event_hash_mismatch:{expected_sequence}")
            previous_hash = event.event_hash
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
            if int(head["event_count"]) != len(events):
                errors.append("event_count_head_mismatch")
            if str(head["head_hash"]) != previous_hash:
                errors.append("event_hash_head_mismatch")
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            errors.append("event_head_missing_or_invalid")
        return EventLogVerification(not errors, len(events), previous_hash, tuple(errors))


def _record_to_dict(record: EvidenceRecord) -> dict[str, Any]:
    data = asdict(record)
    data["created_at"] = record.created_at.isoformat()
    return data


def _event_from_dict(data: dict[str, Any]) -> EventRecord:
    return EventRecord(
        sequence=int(data["sequence"]),
        previous_hash=str(data["previous_hash"]),
        event_hash=str(data["event_hash"]),
        client_id=str(data["client_id"]),
        event_type=str(data["event_type"]),
        actor_id=str(data["actor_id"]),
        object_id=str(data["object_id"]),
        details=dict(data.get("details", {})),
        created_at=_parse_datetime(data["created_at"]),
    )


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple | list):
        return [_redact(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and len(value) > 240:
        return value[:237] + "..."
    return value


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_text(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
