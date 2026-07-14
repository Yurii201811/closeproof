"""Local idempotency records for guarded external adapter calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .policy import ActionType


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    adapter: str
    action_type: ActionType
    case_id: str
    payload_hash: str
    status: str
    dry_run: bool
    external_reference: str | None = None
    response: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class IdempotencyStore(Protocol):
    def get(self, key: str) -> IdempotencyRecord | None:
        ...

    def save(self, record: IdempotencyRecord) -> None:
        ...


class InMemoryIdempotencyStore:
    """Process-local idempotency store for tests and dry-run development."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get(self, key: str) -> IdempotencyRecord | None:
        return self._records.get(key)

    def save(self, record: IdempotencyRecord) -> None:
        if record.key in self._records:
            return
        self._records[record.key] = record
