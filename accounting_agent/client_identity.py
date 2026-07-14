"""Canonical client identity handling shared by local accounting components.

Client IDs are opaque, case-sensitive identifiers.  They are normalized to
Unicode NFC, but are never case-folded or silently trimmed.  Filesystem keys
use canonical base32 so that visually similar or path-hostile IDs cannot
collapse onto the same directory, including on case-insensitive filesystems.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata


MAX_CLIENT_ID_UTF8_BYTES = 128
CLIENT_STORAGE_KEY_PREFIX = "v1-"


def canonical_client_id(value: str) -> str:
    """Validate and return the canonical, case-sensitive client identifier."""

    if not isinstance(value, str):
        raise TypeError("client_id must be a string")
    if value != value.strip():
        raise ValueError("client_id must not contain leading or trailing whitespace")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized:
        raise ValueError("client_id must not be empty")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("client_id must not contain control or invisible format characters")
    if len(normalized.encode("utf-8")) > MAX_CLIENT_ID_UTF8_BYTES:
        raise ValueError(
            f"client_id must not exceed {MAX_CLIENT_ID_UTF8_BYTES} UTF-8 bytes"
        )
    return normalized


def client_storage_key(client_id: str) -> str:
    """Return a reversible, path-safe key for a canonical client identifier."""

    encoded = base64.b32encode(canonical_client_id(client_id).encode("utf-8"))
    return CLIENT_STORAGE_KEY_PREFIX + encoded.decode("ascii").rstrip("=").lower()


def client_id_from_storage_key(storage_key: str) -> str:
    """Decode a storage key produced by :func:`client_storage_key`."""

    if not storage_key.startswith(CLIENT_STORAGE_KEY_PREFIX):
        raise ValueError("unsupported client storage key version")
    payload = storage_key.removeprefix(CLIENT_STORAGE_KEY_PREFIX).upper()
    if not payload:
        raise ValueError("client storage key payload is empty")
    padding = "=" * ((8 - len(payload) % 8) % 8)
    try:
        decoded = base64.b32decode(payload + padding, casefold=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid client storage key") from exc
    canonical = canonical_client_id(decoded)
    if client_storage_key(canonical) != storage_key:
        raise ValueError("client storage key is not canonical")
    return canonical


def scoped_identity_hash(client_id: str, evidence_hash: str) -> str:
    """Hash an evidence identity inside an exact client boundary."""

    canonical = canonical_client_id(client_id)
    material = canonical.encode("utf-8") + b"\x00" + evidence_hash.encode("utf-8")
    return hashlib.sha256(material).hexdigest()
