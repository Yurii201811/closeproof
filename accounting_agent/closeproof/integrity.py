"""Canonical review-context integrity helpers for CloseProof."""

from __future__ import annotations

import hashlib
import json
from typing import Any


GOLDEN_CLOSEPROOF_SNAPSHOT_SHA256 = (
    "fda76d0752396535f0e5eb2f7f7b8a3e374db2ea44ee5431ba7ea4a18e10243b"
)
_CASE_RUNTIME_FIELDS = {
    "advisory",
    "decision",
    "review_context_sha256",
    "snapshot_sha256",
}


def default_advisory_envelope(snapshot_sha256: str) -> dict[str, Any]:
    """Return the honest no-model state for a freshly generated case."""

    return {
        "status": "not_requested",
        "provider": "none",
        "output": None,
        "provenance": {
            "transport": "none",
            "requested_model": None,
            "reported_model": None,
            "model_attestation": "unverified",
            "run_id": None,
            "response_id": None,
            "schema_validated": False,
            "payload_sha256": None,
            "controlled_display_sha256": None,
            "evidence_snapshot_sha256": snapshot_sha256,
        },
        "safe_error_code": None,
    }


def compute_review_context_sha256(case: dict[str, Any]) -> str:
    """Bind a human decision to evidence, controls, and advisory context.

    Operational identifiers are intentionally excluded. Re-running an identical
    advisory should not invalidate a decision merely because a provider assigned
    a different run or response identifier.
    """

    advisory = case.get("advisory")
    if not isinstance(advisory, dict):
        raise ValueError("BalanceDocket advisory envelope is missing")
    provenance = advisory.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("BalanceDocket advisory provenance is missing")
    material = {
        "snapshot_sha256": case.get("snapshot_sha256"),
        "advisory": {
            "status": advisory.get("status"),
            "provider": advisory.get("provider"),
            "output": advisory.get("output"),
            "safe_error_code": advisory.get("safe_error_code"),
            "requested_model": provenance.get("requested_model"),
            "reported_model": provenance.get("reported_model"),
            "model_attestation": provenance.get("model_attestation"),
            "schema_validated": provenance.get("schema_validated"),
            "payload_sha256": provenance.get("payload_sha256"),
            "controlled_display_sha256": provenance.get(
                "controlled_display_sha256"
            ),
            "evidence_snapshot_sha256": provenance.get(
                "evidence_snapshot_sha256"
            ),
        },
    }
    return canonical_sha256(material)


def refresh_review_context(case: dict[str, Any]) -> dict[str, Any]:
    """Update and return a case after its advisory envelope changes."""

    case["review_context_sha256"] = compute_review_context_sha256(case)
    return case


def compute_case_snapshot_sha256(case: dict[str, Any]) -> str:
    """Recompute the immutable case snapshot without runtime review state."""

    if not isinstance(case, dict):
        raise ValueError("BalanceDocket case must be an object")
    material = {
        key: value
        for key, value in case.items()
        if key not in _CASE_RUNTIME_FIELDS
    }
    return canonical_sha256(material)


def validate_golden_case_snapshot(case: dict[str, Any]) -> None:
    """Permit provider use only for the exact bundled synthetic golden case."""

    snapshot = case.get("snapshot_sha256") if isinstance(case, dict) else None
    if snapshot != GOLDEN_CLOSEPROOF_SNAPSHOT_SHA256:
        raise ValueError("BalanceDocket provider input is not the approved synthetic golden case")
    if compute_case_snapshot_sha256(case) != snapshot:
        raise ValueError("BalanceDocket synthetic case snapshot failed integrity validation")


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
