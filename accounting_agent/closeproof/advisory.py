"""Provider-neutral, bounded advisory integration for synthetic CloseProof evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .integrity import validate_golden_case_snapshot


RESPONSES_URL = "https://api.openai.com/v1/responses"
MODEL_ID = "gpt-5.6"
# Codex exposes the concrete GPT-5.6 Sol slug. The unsuffixed identifier above
# is the Responses API alias and the provider-neutral family label used by the
# manual ChatGPT handoff; it is not currently a Codex CLI catalog entry.
CODEX_MODEL_ID = "gpt-5.6-sol"
ADVISORY_REQUEST_SCHEMA_VERSION = "closeproof-advisory-request-v1"
ADVISORY_IMPORT_SCHEMA_VERSION = "closeproof-advisory-import-v1"
PROVIDER_NONE = "none"
PROVIDER_CODEX_SESSION = "codex_session"
PROVIDER_OPENAI_API = "openai_api"
PROVIDER_CODEX_SUBSCRIPTION = "codex_cli"
PROVIDER_MANUAL_IMPORT = "chatgpt_manual"
CONTROLLED_DISPLAY_CONCLUSION = (
    "The advisory selected source-linked evidence for the June service-period "
    "exception; the accounting treatment remains subject to human review."
)
CONTROLLED_DISPLAY_RATIONALE = (
    "The selected citations and reported uncertainty are shown beside the exact "
    "deterministic allocation. The local control remains authoritative for both "
    "amounts; no model recommendation is treated as a human decision."
)
CONTROLLED_MISSING_EVIDENCE = (
    "Additional evidence was flagged for human review; consult the selected citations."
)
MAX_RESPONSE_BYTES = 2_000_000
MAX_CODEX_EVENT_BYTES = 1_000_000
MAX_CODEX_OUTPUT_BYTES = 100_000
MAX_CODEX_EVENTS = 1_000

_ADVISORY_FIELDS = {
    "conclusion",
    "rationale",
    "citation_ids",
    "uncertainty",
    "missing_evidence",
    "current_period_expense_ore",
    "prepaid_asset_ore",
    "cannot_approve",
}
_SAFE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
_CODEX_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "plugins",
    "shell_tool",
    "standalone_web_search",
    "unified_exec",
)
_CODEX_ALLOWED_ITEM_TYPES = {"agent_message", "reasoning"}
_CODEX_SKILL_BUDGET_WARNING = (
    "Skill descriptions were shortened to fit the 2% skills context budget. "
    "Codex can still see every skill, but some descriptions are shorter. "
    "Disable unused skills or plugins to leave more room for the rest."
)
_CODEX_TOOL_ITEM_TYPES = {
    "command_execution",
    "computer_use",
    "image_generation",
    "mcp_tool_call",
    "tool_call",
    "web_search",
}
_PROVIDER_TRANSPORT = {
    PROVIDER_NONE: "none",
    PROVIDER_CODEX_SESSION: "codex_skill",
    PROVIDER_CODEX_SUBSCRIPTION: "codex_cli_chatgpt",
    PROVIDER_MANUAL_IMPORT: "manual_import",
    PROVIDER_OPENAI_API: "responses_api",
}


class AdvisoryError(RuntimeError):
    """Stable, non-secret-bearing advisory failure."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or message


def advisory_output_schema(case: dict[str, Any]) -> dict[str, Any]:
    """Return the strict provider-neutral advisory output schema for one case."""

    _validate_case_boundary(case)
    calculation = case["finding"]["calculation"]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "conclusion": {"type": "string", "minLength": 20, "maxLength": 800},
            "rationale": {"type": "string", "minLength": 40, "maxLength": 1600},
            "citation_ids": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "items": {"type": "string"},
            },
            "uncertainty": {"type": "string", "enum": ["low", "medium", "high"]},
            "missing_evidence": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string", "maxLength": 300},
            },
            "current_period_expense_ore": {
                "type": "integer",
                "enum": [calculation["current_period_expense_ore"]],
            },
            "prepaid_asset_ore": {
                "type": "integer",
                "enum": [calculation["prepaid_asset_ore"]],
            },
            "cannot_approve": {"type": "boolean", "enum": [True]},
        },
        "required": sorted(_ADVISORY_FIELDS),
    }


def build_advisory_input(case: dict[str, Any]) -> dict[str, Any]:
    """Extract the only evidence providers are allowed to receive."""

    _validate_case_boundary(case)
    finding = case["finding"]
    calculation = finding["calculation"]
    return {
        "case_id": case["case_id"],
        "snapshot_sha256": case["snapshot_sha256"],
        "period": case["period"],
        "finding": {
            "title": finding["title"],
            "summary": finding["summary"],
            "calculation": {
                "currency": calculation["currency"],
                "service_start": calculation["service_start"],
                "service_end": calculation["service_end"],
                "service_days": calculation["service_days"],
                "current_period_days": calculation["current_period_days"],
                "current_period_expense_ore": calculation["current_period_expense_ore"],
                "prepaid_asset_ore": calculation["prepaid_asset_ore"],
                "formula": calculation["formula"],
            },
            "sources": [
                {"source_id": item["source_id"], "text": item["text"]}
                for item in finding["citations"]
            ],
        },
    }


def advisory_instructions() -> str:
    return (
        "You are an advisory-only month-end close reviewer. Use only the supplied "
        "synthetic sources and exact deterministic amounts. Cite source_id values "
        "verbatim. State uncertainty and missing evidence. Never claim to approve, "
        "post, lock, file, pay, or communicate. Use impersonal, present-tense "
        "evidence analysis without first-person pronouns, external systems or "
        "recipients, or claims that a treatment, entry, workpaper, or decision "
        "changed state. Return only the requested schema."
    )


def prepare_advisory(case: dict[str, Any]) -> dict[str, Any]:
    """Build a portable, provider-neutral request for offline/manual execution."""

    return {
        "schema_version": ADVISORY_REQUEST_SCHEMA_VERSION,
        "requested_model": MODEL_ID,
        "evidence_snapshot_sha256": case.get("snapshot_sha256"),
        "instructions": advisory_instructions(),
        "input": build_advisory_input(case),
        "output_schema": advisory_output_schema(case),
    }


def prepared_advisory_envelope(case: dict[str, Any]) -> dict[str, Any]:
    _validate_case_boundary(case)
    return _advisory_envelope(
        case,
        status="running",
        provider=PROVIDER_MANUAL_IMPORT,
        output=None,
        transport="manual_import",
        requested_model=MODEL_ID,
        reported_model=None,
        model_attestation="unverified",
        run_id=None,
        response_id=None,
        schema_validated=False,
        payload_sha256=None,
        controlled_display_sha256=None,
        safe_error_code=None,
    )


def build_advisory_request(case: dict[str, Any]) -> dict[str, Any]:
    """Build the optional OpenAI Responses API request from the shared contract."""

    prepared = prepare_advisory(case)
    return {
        "model": MODEL_ID,
        "store": False,
        "max_output_tokens": 1200,
        "reasoning": {"effort": "medium"},
        "safety_identifier": hashlib.sha256(b"closeproof-synthetic-demo").hexdigest()[:32],
        "instructions": prepared["instructions"],
        "input": json.dumps(prepared["input"], ensure_ascii=False, sort_keys=True),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "closeproof_advisory",
                "strict": True,
                "schema": prepared["output_schema"],
            }
        },
    }


def invoke_gpt56_advisory(
    case: dict[str, Any],
    *,
    api_key: str,
    timeout: float = 60.0,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Invoke the preserved, explicit API-key Responses API provider."""

    if not isinstance(api_key, str) or not api_key.strip():
        raise AdvisoryError(
            "OPENAI_API_KEY is required for the explicit GPT-5.6 path",
            code="openai_api_key_required",
        )
    request_body = build_advisory_request(case)
    request = Request(
        RESPONSES_URL,
        data=json.dumps(request_body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            response_data = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise AdvisoryError(
            "GPT-5.6 advisory request failed", code="openai_request_failed"
        ) from exc
    if len(response_data) > MAX_RESPONSE_BYTES:
        raise AdvisoryError(
            "GPT-5.6 response exceeded the safe size limit",
            code="openai_response_too_large",
        )
    try:
        payload = json.loads(response_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdvisoryError(
            "GPT-5.6 returned an invalid response envelope",
            code="openai_invalid_envelope",
        ) from exc
    return validate_advisory_response(case, payload)


def validate_advisory_response(case: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a Responses API envelope and return the common provider envelope."""

    _validate_case_boundary(case)
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        raise AdvisoryError("GPT-5.6 response did not complete", code="openai_incomplete")
    model = payload.get("model")
    if not isinstance(model, str) or not _api_model_matches(model):
        raise AdvisoryError(
            "response model does not match GPT-5.6", code="model_mismatch"
        )
    output_texts: list[str] = []
    output_items = payload.get("output", [])
    if not isinstance(output_items, list):
        raise AdvisoryError("response must contain exactly one structured output", code="invalid_output")
    for item in output_items:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content_items = item.get("content", [])
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                output_texts.append(content["text"])
    if len(output_texts) != 1:
        raise AdvisoryError(
            "response must contain exactly one structured output", code="invalid_output"
        )
    advisory = _parse_advisory_json(output_texts[0])
    validate_advisory_output(case, advisory)
    return completed_advisory_envelope(
        case,
        advisory,
        provider=PROVIDER_OPENAI_API,
        transport="responses_api",
        requested_model=MODEL_ID,
        reported_model=model,
        model_attestation="api_response",
        run_id=None,
        response_id=_optional_string(payload.get("id")),
    )


def import_advisory(
    case: dict[str, Any],
    payload: dict[str, Any],
    *,
    provider: str = PROVIDER_MANUAL_IMPORT,
    reported_model: str | None = None,
    run_id: str | None = None,
    response_id: str | None = None,
) -> dict[str, Any]:
    """Validate a manual/offline result and attach explicit provenance."""

    _validate_case_boundary(case)
    if not isinstance(payload, dict):
        raise AdvisoryError("manual advisory import must be an object", code="invalid_import")
    output = payload
    if payload.get("schema_version") == ADVISORY_IMPORT_SCHEMA_VERSION:
        output = payload.get("output")
        provenance = payload.get("provenance", {})
        if not isinstance(provenance, dict):
            raise AdvisoryError("manual advisory provenance is invalid", code="invalid_import")
        reported_model = reported_model or _optional_string(provenance.get("reported_model"))
        run_id = run_id or _optional_string(provenance.get("run_id"))
        response_id = response_id or _optional_string(provenance.get("response_id"))
    if not isinstance(output, dict):
        raise AdvisoryError("manual advisory output must be an object", code="invalid_import")
    validate_advisory_output(case, output)
    if reported_model is not None and not _model_matches(reported_model):
        raise AdvisoryError("imported model does not match GPT-5.6", code="model_mismatch")
    return completed_advisory_envelope(
        case,
        output,
        provider=provider,
        transport="manual_import",
        requested_model=MODEL_ID,
        reported_model=reported_model,
        model_attestation="user_declared" if reported_model else "unverified",
        run_id=run_id,
        response_id=response_id,
    )


def invoke_codex_subscription_advisory(
    case: dict[str, Any],
    *,
    allow_subscription_advisory: bool = False,
    timeout: float = 120.0,
    codex_executable: str = "codex",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Invoke GPT-5.6 Sol through a standalone ChatGPT-authenticated Codex CLI.

    The invocation is one-shot, read-only, ephemeral, tool-disabled, and never
    retried. The case is sent over stdin, never in argv.
    """

    _validate_case_boundary(case)
    if allow_subscription_advisory is not True:
        raise AdvisoryError(
            "Codex subscription advisory requires explicit allowance confirmation",
            code="codex_allowance_required",
        )
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise AdvisoryError("Codex timeout must be between 1 and 600 seconds", code="invalid_timeout")
    base_env = os.environ if environ is None else environ
    with tempfile.TemporaryDirectory(prefix="closeproof-codex-") as temporary:
        workdir = Path(temporary)
        workdir.chmod(0o700)
        safe_env = _sanitized_codex_env(base_env, temp_dir=workdir)
        _require_chatgpt_codex_login(
            codex_executable=codex_executable,
            runner=runner,
            env=safe_env,
            cwd=workdir,
            timeout=min(float(timeout), 20.0),
        )
        schema_path = workdir / "advisory-schema.json"
        output_path = workdir / "advisory-output.json"
        schema_path.write_text(
            json.dumps(advisory_output_schema(case), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        schema_path.chmod(0o600)
        argv = _codex_advisory_argv(
            codex_executable=codex_executable,
            workdir=workdir,
            schema_path=schema_path,
            output_path=output_path,
        )
        prompt = json.dumps(prepare_advisory(case), ensure_ascii=False, sort_keys=True)
        try:
            result = runner(
                argv,
                input=prompt,
                cwd=str(workdir),
                env=safe_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=float(timeout),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdvisoryError("Codex advisory timed out", code="codex_timeout") from exc
        except OSError as exc:
            raise AdvisoryError("Codex advisory could not start", code="codex_unavailable") from exc
        events, run_id, reported_model = _validate_codex_events(result.stdout)
        if result.returncode != 0:
            raise AdvisoryError("Codex advisory failed", code="codex_failed")
        if not events:
            raise AdvisoryError("Codex returned no events", code="codex_invalid_events")
        advisory = _read_codex_output(output_path)
        validate_advisory_output(case, advisory)
        if reported_model is not None and not _codex_model_matches(reported_model):
            raise AdvisoryError("Codex reported a different model", code="model_mismatch")
        return completed_advisory_envelope(
            case,
            advisory,
            provider=PROVIDER_CODEX_SUBSCRIPTION,
            transport="codex_cli_chatgpt",
            requested_model=CODEX_MODEL_ID,
            reported_model=reported_model,
            model_attestation="codex_requested",
            run_id=run_id,
            response_id=None,
        )


def completed_advisory_envelope(
    case: dict[str, Any],
    advisory: dict[str, Any],
    *,
    provider: str,
    transport: str,
    requested_model: str | None,
    reported_model: str | None,
    model_attestation: str,
    run_id: str | None,
    response_id: str | None,
) -> dict[str, Any]:
    validate_advisory_output(case, advisory)
    controlled_advisory = _controlled_display_advisory(advisory)
    provider_canonical = json.dumps(
        advisory, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    controlled_canonical = json.dumps(
        controlled_advisory, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    envelope = _advisory_envelope(
        case,
        status="completed",
        provider=provider,
        output=controlled_advisory,
        transport=transport,
        requested_model=requested_model,
        reported_model=reported_model,
        model_attestation=model_attestation,
        run_id=run_id,
        response_id=response_id,
        schema_validated=True,
        payload_sha256=hashlib.sha256(provider_canonical.encode("utf-8")).hexdigest(),
        controlled_display_sha256=hashlib.sha256(
            controlled_canonical.encode("utf-8")
        ).hexdigest(),
        safe_error_code=None,
    )
    validate_advisory_envelope(case, envelope)
    return envelope


def failed_advisory_envelope(
    case: dict[str, Any],
    *,
    provider: str,
    transport: str,
    requested_model: str | None,
    safe_error_code: str,
    status: str | None = None,
) -> dict[str, Any]:
    _validate_case_boundary(case)
    if not safe_error_code or len(safe_error_code) > 80:
        raise AdvisoryError("safe advisory error code is invalid", code="invalid_error_code")
    resolved_status = status or _failure_status(safe_error_code)
    if resolved_status not in {"unavailable", "invalid"}:
        raise AdvisoryError("failed advisory status is invalid", code="invalid_error_code")
    return _advisory_envelope(
        case,
        status=resolved_status,
        provider=provider,
        output=None,
        transport=transport,
        requested_model=requested_model,
        reported_model=None,
        model_attestation="unverified",
        run_id=None,
        response_id=None,
        schema_validated=False,
        payload_sha256=None,
        controlled_display_sha256=None,
        safe_error_code=safe_error_code,
    )


def write_live_advisory(case_path: str | Path, advisory: dict[str, Any]) -> dict[str, Any]:
    """Persist a validated provider envelope without accepting stale evidence."""

    path = Path(case_path)
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise OSError("case path must be a regular file")
        with path.open("rb") as handle:
            content = handle.read(1_000_001)
        if not 1 <= len(content) <= 1_000_000:
            raise OSError("case size is invalid")
        case = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdvisoryError("BalanceDocket case file is invalid", code="invalid_case_file") from exc
    validate_advisory_envelope(case, advisory)
    case["advisory"] = advisory
    # Imported lazily to keep the advisory contract usable during case creation.
    from .integrity import refresh_review_context

    refresh_review_context(case)
    _atomic_write_text(
        path,
        json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return case


def validate_advisory_envelope(case: dict[str, Any], envelope: dict[str, Any]) -> None:
    _validate_case_boundary(case)
    if not isinstance(envelope, dict):
        raise AdvisoryError("advisory envelope must be an object", code="invalid_envelope")
    required = {"status", "provider", "output", "provenance", "safe_error_code"}
    if set(envelope) != required:
        raise AdvisoryError("advisory envelope fields are invalid", code="invalid_envelope")
    if not isinstance(envelope["status"], str) or envelope["status"] not in {
        "not_requested",
        "running",
        "completed",
        "unavailable",
        "invalid",
    }:
        raise AdvisoryError("advisory status is invalid", code="invalid_envelope")
    status = envelope["status"]
    provider = envelope["provider"]
    if provider not in _PROVIDER_TRANSPORT:
        raise AdvisoryError("advisory provider is invalid", code="invalid_envelope")
    provenance = envelope["provenance"]
    provenance_fields = {
        "transport",
        "requested_model",
        "reported_model",
        "model_attestation",
        "run_id",
        "response_id",
        "schema_validated",
        "payload_sha256",
        "controlled_display_sha256",
        "evidence_snapshot_sha256",
    }
    if not isinstance(provenance, dict) or set(provenance) != provenance_fields:
        raise AdvisoryError("advisory provenance is invalid", code="invalid_envelope")
    if not isinstance(provenance["model_attestation"], str) or provenance["model_attestation"] not in {
        "unverified",
        "codex_requested",
        "user_declared",
        "api_response",
    }:
        raise AdvisoryError("advisory model attestation is invalid", code="invalid_envelope")
    for field in ("requested_model", "reported_model", "run_id", "response_id"):
        value = provenance[field]
        if value is not None and (
            not isinstance(value, str) or _SAFE_IDENTIFIER_PATTERN.fullmatch(value) is None
        ):
            raise AdvisoryError("advisory provenance is invalid", code="invalid_envelope")
    for field in ("payload_sha256", "controlled_display_sha256"):
        value = provenance[field]
        if value is not None and (
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        ):
            raise AdvisoryError("advisory provenance is invalid", code="invalid_envelope")
    if provenance["transport"] != _PROVIDER_TRANSPORT[provider]:
        raise AdvisoryError("advisory provider transport is inconsistent", code="invalid_envelope")
    if not isinstance(provenance["schema_validated"], bool):
        raise AdvisoryError("advisory provenance is invalid", code="invalid_envelope")
    if provenance["evidence_snapshot_sha256"] != case["snapshot_sha256"]:
        raise AdvisoryError("advisory evidence snapshot is stale", code="stale_advisory")

    if provider == PROVIDER_NONE:
        empty_fields = (
            "requested_model",
            "reported_model",
            "run_id",
            "response_id",
            "payload_sha256",
            "controlled_display_sha256",
        )
        if status != "not_requested" or any(provenance[field] is not None for field in empty_fields):
            raise AdvisoryError("no-provider advisory state is inconsistent", code="invalid_envelope")
        if provenance["model_attestation"] != "unverified":
            raise AdvisoryError("no-provider attestation is inconsistent", code="invalid_envelope")
    elif status == "not_requested" or provenance["requested_model"] != _requested_model_for_provider(
        provider
    ):
        raise AdvisoryError("provider model request is inconsistent", code="invalid_envelope")

    if status == "completed":
        validate_advisory_output(case, envelope["output"])
        if envelope["output"] != _controlled_display_advisory(envelope["output"]):
            raise AdvisoryError(
                "completed advisory output is not normalized for controlled display",
                code="invalid_envelope",
            )
        canonical = json.dumps(
            envelope["output"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if (
            provenance["payload_sha256"] is None
            or provenance["controlled_display_sha256"] != expected_hash
            or provenance["schema_validated"] is not True
        ):
            raise AdvisoryError("advisory payload provenance is invalid", code="invalid_envelope")
        if envelope["safe_error_code"] is not None:
            raise AdvisoryError("completed advisory cannot contain an error", code="invalid_envelope")
        reported_model = provenance["reported_model"]
        if reported_model is not None and not _reported_model_matches(provider, reported_model):
            raise AdvisoryError("advisory reported model is inconsistent", code="invalid_envelope")
        expected_attestation = {
            PROVIDER_MANUAL_IMPORT: "user_declared" if reported_model else "unverified",
            PROVIDER_CODEX_SESSION: "codex_requested",
            PROVIDER_CODEX_SUBSCRIPTION: "codex_requested",
            PROVIDER_OPENAI_API: "api_response",
        }[provider]
        if provenance["model_attestation"] != expected_attestation:
            raise AdvisoryError("advisory model attestation is inconsistent", code="invalid_envelope")
        if provider == PROVIDER_OPENAI_API and (
            reported_model is None or provenance["response_id"] is None or provenance["run_id"] is not None
        ):
            raise AdvisoryError("API response provenance is incomplete", code="invalid_envelope")
        if provider in {PROVIDER_CODEX_SESSION, PROVIDER_CODEX_SUBSCRIPTION} and (
            provenance["response_id"] is not None or provenance["run_id"] is None
        ):
            raise AdvisoryError("Codex response provenance is incomplete", code="invalid_envelope")
    else:
        if envelope["output"] is not None:
            raise AdvisoryError("incomplete advisory cannot contain output", code="invalid_envelope")
        if (
            provenance["schema_validated"] is not False
            or provenance["payload_sha256"] is not None
            or provenance["controlled_display_sha256"] is not None
        ):
            raise AdvisoryError("incomplete advisory provenance is inconsistent", code="invalid_envelope")
        if any(provenance[field] is not None for field in ("reported_model", "run_id", "response_id")):
            raise AdvisoryError("incomplete advisory identifiers are inconsistent", code="invalid_envelope")
        if provenance["model_attestation"] != "unverified":
            raise AdvisoryError("incomplete advisory attestation is inconsistent", code="invalid_envelope")
        if status in {"unavailable", "invalid"}:
            error_code = envelope["safe_error_code"]
            if not isinstance(error_code, str) or not error_code or len(error_code) > 80:
                raise AdvisoryError("failed advisory error is invalid", code="invalid_envelope")
        elif envelope["safe_error_code"] is not None:
            raise AdvisoryError("non-failed advisory cannot contain an error", code="invalid_envelope")


def validate_advisory_output(case: dict[str, Any], advisory: dict[str, Any]) -> None:
    """Apply the shared semantic validation after any provider/schema parser."""

    _validate_case_boundary(case)
    if not isinstance(advisory, dict):
        raise AdvisoryError("advisory must be an object", code="invalid_advisory")
    if set(advisory) != _ADVISORY_FIELDS:
        raise AdvisoryError("advisory fields are invalid", code="invalid_advisory")
    if not isinstance(advisory["conclusion"], str) or not 20 <= len(advisory["conclusion"]) <= 800:
        raise AdvisoryError("advisory conclusion length is invalid", code="invalid_advisory")
    if not isinstance(advisory["rationale"], str) or not 40 <= len(advisory["rationale"]) <= 1600:
        raise AdvisoryError("advisory rationale length is invalid", code="invalid_advisory")
    allowed_citations = {item["source_id"] for item in case["finding"]["citations"]}
    citations = advisory["citation_ids"]
    if (
        not isinstance(citations, list)
        or not 2 <= len(citations) <= 3
        or any(not isinstance(item, str) for item in citations)
        or len(set(citations)) != len(citations)
        or not set(citations).issubset(allowed_citations)
    ):
        raise AdvisoryError("advisory citations are missing or unknown", code="invalid_citations")
    if not isinstance(advisory["uncertainty"], str) or advisory["uncertainty"] not in {
        "low",
        "medium",
        "high",
    }:
        raise AdvisoryError("advisory uncertainty is invalid", code="invalid_advisory")
    missing = advisory["missing_evidence"]
    if (
        not isinstance(missing, list)
        or len(missing) > 5
        or any(not isinstance(item, str) or len(item) > 300 for item in missing)
    ):
        raise AdvisoryError("missing-evidence list is invalid", code="invalid_advisory")
    calculation = case["finding"]["calculation"]
    for field in ("current_period_expense_ore", "prepaid_asset_ore"):
        value = advisory[field]
        if not isinstance(value, int) or isinstance(value, bool):
            raise AdvisoryError("advisory amount type is invalid", code="invalid_advisory")
    if advisory["current_period_expense_ore"] != calculation["current_period_expense_ore"]:
        raise AdvisoryError(
            "advisory changed the deterministic current-period amount",
            code="deterministic_amount_changed",
        )
    if advisory["prepaid_asset_ore"] != calculation["prepaid_asset_ore"]:
        raise AdvisoryError(
            "advisory changed the deterministic prepaid amount",
            code="deterministic_amount_changed",
        )
    if advisory["cannot_approve"] is not True:
        raise AdvisoryError(
            "advisory attempted to claim approval authority",
            code="approval_authority_claimed",
        )


def _controlled_display_advisory(advisory: Mapping[str, Any]) -> dict[str, Any]:
    """Discard provider prose and retain only validated structured advisory choices."""

    return {
        "conclusion": CONTROLLED_DISPLAY_CONCLUSION,
        "rationale": CONTROLLED_DISPLAY_RATIONALE,
        "citation_ids": list(advisory["citation_ids"]),
        "uncertainty": advisory["uncertainty"],
        "missing_evidence": (
            [CONTROLLED_MISSING_EVIDENCE] if advisory["missing_evidence"] else []
        ),
        "current_period_expense_ore": advisory["current_period_expense_ore"],
        "prepaid_asset_ore": advisory["prepaid_asset_ore"],
        "cannot_approve": True,
    }


def _advisory_envelope(
    case: dict[str, Any],
    *,
    status: str,
    provider: str,
    output: dict[str, Any] | None,
    transport: str,
    requested_model: str | None,
    reported_model: str | None,
    model_attestation: str,
    run_id: str | None,
    response_id: str | None,
    schema_validated: bool,
    payload_sha256: str | None,
    controlled_display_sha256: str | None,
    safe_error_code: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "provider": provider,
        "output": output,
        "provenance": {
            "transport": transport,
            "requested_model": requested_model,
            "reported_model": reported_model,
            "model_attestation": model_attestation,
            "run_id": run_id,
            "response_id": response_id,
            "schema_validated": schema_validated,
            "payload_sha256": payload_sha256,
            "controlled_display_sha256": controlled_display_sha256,
            "evidence_snapshot_sha256": case["snapshot_sha256"],
        },
        "safe_error_code": safe_error_code,
    }


def _codex_advisory_argv(
    *,
    codex_executable: str,
    workdir: Path,
    schema_path: Path,
    output_path: Path,
) -> list[str]:
    argv = [
        codex_executable,
        "exec",
        "--model",
        CODEX_MODEL_ID,
        "--sandbox",
        "read-only",
        "--config",
        'approval_policy="never"',
        "--config",
        "mcp_servers={}",
        "--config",
        "plugins={}",
        "--config",
        "notify=[]",
        "--config",
        'web_search="disabled"',
        "--config",
        'shell_environment_policy.inherit="none"',
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "--cd",
        str(workdir),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--json",
        "--color",
        "never",
    ]
    for feature in _CODEX_DISABLED_FEATURES:
        argv.extend(("--disable", feature))
    argv.append("-")
    return argv


def _sanitized_codex_env(source: Mapping[str, str], *, temp_dir: Path) -> dict[str, str]:
    allowed = {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "USER",
    }
    result = {key: value for key, value in source.items() if key in allowed and isinstance(value, str)}
    result["TMPDIR"] = str(temp_dir)
    return result


def _require_chatgpt_codex_login(
    *,
    codex_executable: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    env: Mapping[str, str],
    cwd: Path,
    timeout: float,
) -> None:
    try:
        result = runner(
            [codex_executable, "login", "status"],
            cwd=str(cwd),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdvisoryError("Codex login status timed out", code="codex_login_timeout") from exc
    except OSError as exc:
        raise AdvisoryError("Codex login status unavailable", code="codex_unavailable") from exc
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if len(output.encode("utf-8", errors="replace")) > 64_000:
        raise AdvisoryError("Codex login status was invalid", code="codex_login_invalid")
    if result.returncode != 0 or "Logged in using ChatGPT" not in output:
        if "API key" in output or "api key" in output.lower():
            raise AdvisoryError(
                "Codex subscription provider refuses API-key login",
                code="codex_api_key_login_blocked",
            )
        raise AdvisoryError(
            "Codex is not logged in using ChatGPT", code="codex_chatgpt_login_required"
        )


def _validate_codex_events(stdout: str | None) -> tuple[list[dict[str, Any]], str, str | None]:
    raw = stdout or ""
    if len(raw.encode("utf-8", errors="replace")) > MAX_CODEX_EVENT_BYTES:
        raise AdvisoryError("Codex event stream exceeded the safe size limit", code="codex_events_too_large")
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if len(events) >= MAX_CODEX_EVENTS:
            raise AdvisoryError("Codex returned too many events", code="codex_events_too_large")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdvisoryError("Codex returned invalid JSON events", code="codex_invalid_events") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise AdvisoryError("Codex returned invalid events", code="codex_invalid_events")
        events.append(event)
    if not events:
        raise AdvisoryError("Codex returned no events", code="codex_invalid_events")
    reported_models: set[str] = set()
    for event in events:
        event_type = event["type"]
        if event_type in {"error", "turn.failed"}:
            raise AdvisoryError("Codex reported a failed turn", code="codex_failed")
        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "error":
                if item.get("message") == _CODEX_SKILL_BUDGET_WARNING:
                    continue
                raise AdvisoryError("Codex reported a failed item", code="codex_failed")
            if item_type in _CODEX_TOOL_ITEM_TYPES:
                raise AdvisoryError("Codex attempted a disabled tool", code="codex_tool_attempted")
            if event_type.startswith("item.") and item_type not in _CODEX_ALLOWED_ITEM_TYPES:
                raise AdvisoryError("Codex returned an unexpected item", code="codex_invalid_events")
        for candidate in (event.get("model"), event.get("response", {}).get("model") if isinstance(event.get("response"), dict) else None):
            if isinstance(candidate, str):
                reported_models.add(candidate)
    thread_events = [event for event in events if event["type"] == "thread.started"]
    completed_events = [event for event in events if event["type"] == "turn.completed"]
    if len(thread_events) != 1 or len(completed_events) != 1:
        raise AdvisoryError("Codex did not return one completed turn", code="codex_invalid_events")
    run_id = thread_events[0].get("thread_id")
    if not isinstance(run_id, str) or not run_id or len(run_id) > 200:
        raise AdvisoryError("Codex thread identifier is invalid", code="codex_invalid_events")
    if len(reported_models) > 1:
        raise AdvisoryError("Codex reported inconsistent models", code="model_mismatch")
    reported_model = next(iter(reported_models), None)
    return events, run_id, reported_model


def _read_codex_output(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AdvisoryError("Codex output file is missing", code="codex_output_missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise AdvisoryError("Codex output file is invalid", code="codex_output_invalid")
    if metadata.st_size <= 0 or metadata.st_size > MAX_CODEX_OUTPUT_BYTES:
        raise AdvisoryError("Codex output size is invalid", code="codex_output_invalid")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AdvisoryError("Codex output file is unreadable", code="codex_output_invalid") from exc
    return _parse_advisory_json(content)


def _parse_advisory_json(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AdvisoryError("structured advisory is not valid JSON", code="invalid_advisory_json") from exc
    if not isinstance(payload, dict):
        raise AdvisoryError("structured advisory must be an object", code="invalid_advisory")
    return payload


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace one local state file durably without exposing a partial JSON body."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_case_boundary(case: dict[str, Any]) -> None:
    if not isinstance(case, dict) or case.get("schema_version") != "closeproof-case-v1":
        raise AdvisoryError("expected a BalanceDocket v1 case", code="invalid_case")
    safety = case.get("safety")
    if not isinstance(safety, dict) or safety.get("synthetic_only") is not True:
        raise AdvisoryError(
            "GPT-5.6 is restricted to the bundled synthetic case", code="non_synthetic_case"
        )
    if safety.get("erp_writes") is not False:
        raise AdvisoryError("the advisory case must forbid ERP writes", code="erp_writes_not_forbidden")
    snapshot = case.get("snapshot_sha256")
    if not isinstance(snapshot, str) or len(snapshot) != 64:
        raise AdvisoryError("case snapshot is invalid", code="invalid_case")
    try:
        validate_golden_case_snapshot(case)
    except ValueError as exc:
        raise AdvisoryError(str(exc), code="synthetic_case_not_approved") from exc
    try:
        int(snapshot, 16)
    except ValueError as exc:
        raise AdvisoryError("case snapshot is invalid", code="invalid_case") from exc
    if not isinstance(case.get("case_id"), str) or not case["case_id"]:
        raise AdvisoryError("case identifier is invalid", code="invalid_case")
    if not isinstance(case.get("period"), dict):
        raise AdvisoryError("case period is invalid", code="invalid_case")
    finding = case.get("finding")
    if not isinstance(finding, dict):
        raise AdvisoryError("case finding is invalid", code="invalid_case")
    if any(not isinstance(finding.get(field), str) for field in ("title", "summary")):
        raise AdvisoryError("case finding is invalid", code="invalid_case")
    calculation = finding.get("calculation")
    calculation_fields = {
        "currency",
        "service_start",
        "service_end",
        "service_days",
        "current_period_days",
        "current_period_expense_ore",
        "prepaid_asset_ore",
        "formula",
    }
    if not isinstance(calculation, dict) or not calculation_fields.issubset(calculation):
        raise AdvisoryError("case calculation is invalid", code="invalid_case")
    citations = finding.get("citations")
    if (
        not isinstance(citations, list)
        or len(citations) < 2
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("source_id"), str)
            or not isinstance(item.get("text"), str)
            for item in citations
        )
    ):
        raise AdvisoryError("case citations are invalid", code="invalid_case")


def _model_matches(model: str) -> bool:
    return bool(model == MODEL_ID or re.fullmatch(r"gpt-5\.6-\d{4}-\d{2}-\d{2}", model))


def _codex_model_matches(model: str) -> bool:
    return bool(
        model == CODEX_MODEL_ID
        or re.fullmatch(r"gpt-5\.6-sol-\d{4}-\d{2}-\d{2}", model)
    )


def _api_model_matches(model: str) -> bool:
    """Accept the GPT-5.6 alias, Sol concrete IDs, or dated API snapshots only."""

    return bool(
        model == MODEL_ID
        or _codex_model_matches(model)
        or re.fullmatch(r"gpt-5\.6-\d{4}-\d{2}-\d{2}", model)
    )


def _reported_model_matches(provider: str, model: str) -> bool:
    if provider == PROVIDER_CODEX_SUBSCRIPTION:
        return _codex_model_matches(model)
    if provider == PROVIDER_OPENAI_API:
        return _api_model_matches(model)
    return _model_matches(model)


def _requested_model_for_provider(provider: str) -> str:
    return CODEX_MODEL_ID if provider == PROVIDER_CODEX_SUBSCRIPTION else MODEL_ID


def _failure_status(code: str) -> str:
    invalid_codes = {
        "approval_authority_claimed",
        "codex_invalid_events",
        "codex_output_invalid",
        "codex_output_missing",
        "codex_tool_attempted",
        "deterministic_amount_changed",
        "invalid_advisory",
        "invalid_advisory_json",
        "invalid_citations",
        "invalid_import",
        "invalid_output",
        "model_mismatch",
    }
    return "invalid" if code in invalid_codes else "unavailable"


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
