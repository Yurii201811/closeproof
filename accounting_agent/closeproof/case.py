"""Build the deterministic CloseProof golden case from synthetic fixtures."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
import tempfile
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from accounting_agent.close import (
    CLOSE_STAGE_ORDER,
    CloseFact,
    CloseFactStatus,
    CloseSnapshot,
    CloseStage,
    CloseVerificationContext,
    PeriodCloseIdentity,
    compute_close_evidence_bundle_hash,
    evaluate_period_close,
)
from accounting_agent.evidence import HashChainedEventLog

from .pdf import build_text_pdf, extract_fixture_pdf_lines
from .integrity import (
    GOLDEN_CLOSEPROOF_SNAPSHOT_SHA256,
    default_advisory_envelope,
    refresh_review_context,
    validate_golden_case_snapshot,
)


DEFAULT_CLOSEPROOF_FIXTURE = Path(
    "fixtures/closeproof/nordix_services_june_2026"
)
DEFAULT_CLOSEPROOF_OUTPUT = Path(".local/closeproof-demo")
OUTPUT_OWNER_FILENAME = ".closeproof-output.json"
OUTPUT_OWNER_SCHEMA_VERSION = "closeproof-output-owner-v1"
_GOLDEN_CASE_ID = "cp_nordix_2026_06_inv_4821"
_MANAGED_OUTPUT_FILENAMES = (
    OUTPUT_OWNER_FILENAME,
    "case.json",
    "manifest.json",
    "invoice_INV-4821.pdf",
    "decision-events.jsonl",
    "decision-events.jsonl.head.json",
    "decision-events.jsonl.lock",
    "advisory-request.json",
    "advisory-output.json",
    "workpaper.json",
)

_STAGE_TITLES = {
    CloseStage.EVIDENCE_COMPLETENESS: "Evidence completeness",
    CloseStage.BANK_RECONCILIATION: "Bank reconciliation",
    CloseStage.SUBLEDGERS: "Subledgers",
    CloseStage.ADJUSTMENTS: "Adjustments",
    CloseStage.BALANCED_TRIAL_BALANCE: "Balanced trial balance",
    CloseStage.VAT_CONTROL: "VAT control",
    CloseStage.PREPARER_REVIEW: "Preparer review",
    CloseStage.INDEPENDENT_SIGNOFF: "Independent sign-off",
    CloseStage.LOCK_READINESS: "Lock readiness",
}
_OWNERS = ("A. Lind", "M. Chen", "J. Eriksson", "M. Chen", "A. Lind", "M. Chen", "K. Patel", "J. Eriksson", "A. Lind")
_EVIDENCE_COUNTS = (3, 2, 3, 2, 0, 0, 0, 0, 0)


class CloseProofCaseError(ValueError):
    """Raised when the fixture cannot produce an evidence-bound case."""


def build_closeproof_demo(
    *,
    fixture_dir: str | Path = DEFAULT_CLOSEPROOF_FIXTURE,
    output_dir: str | Path = DEFAULT_CLOSEPROOF_OUTPUT,
) -> dict[str, Any]:
    fixture = Path(fixture_dir)
    output = Path(output_dir)
    validate_closeproof_output_directory(output)
    invoice_text_path = fixture / "invoice_INV-4821.txt"
    ledger_path = fixture / "general_ledger.csv"
    policy_path = fixture / "policy.txt"
    for path in (invoice_text_path, ledger_path, policy_path):
        if not path.is_file():
            raise CloseProofCaseError(f"required synthetic fixture is missing: {path}")

    invoice_lines = tuple(
        line
        for line in invoice_text_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not invoice_lines or not invoice_lines[0].startswith("SYNTHETIC DEMO DOCUMENT"):
        raise CloseProofCaseError("invoice fixture is not marked as synthetic")
    pdf_bytes = build_text_pdf(invoice_lines)
    parsed_lines = extract_fixture_pdf_lines(pdf_bytes)
    invoice = _parse_invoice(parsed_lines)
    ledger_bytes = ledger_path.read_bytes()
    policy_bytes = policy_path.read_bytes()
    ledger_rows = _parse_ledger(ledger_bytes)

    if invoice["customer"] != "Nordix Services AB":
        raise CloseProofCaseError("the golden fixture customer is not recognized")
    if invoice["invoice_number"] != "INV-4821":
        raise CloseProofCaseError("the golden fixture invoice identity changed")

    period = "2026-06"
    allocation = _calculate_allocation(
        amount_ore=_sek_to_ore(invoice["amount_sek"]),
        service_start=date.fromisoformat(invoice["service_start"]),
        service_end=date.fromisoformat(invoice["service_end"]),
        period=period,
    )
    checks = _run_controls(invoice=invoice, ledger_rows=ledger_rows, period=period, allocation=allocation)

    evidence_hashes = {
        "invoice_pdf": hashlib.sha256(pdf_bytes).hexdigest(),
        "general_ledger": hashlib.sha256(ledger_bytes).hexdigest(),
        "close_policy": hashlib.sha256(policy_bytes).hexdigest(),
    }
    identity = PeriodCloseIdentity("nordix-demo", "nordix-services-ab", period)
    facts = tuple(
        CloseFact(
            stage=stage,
            status=(
                CloseFactStatus.REVIEW_REQUIRED
                if stage is CloseStage.ADJUSTMENTS
                else CloseFactStatus.SATISFIED
            ),
            evidence_hashes=(
                evidence_hashes["invoice_pdf"],
                evidence_hashes["general_ledger"],
            ),
            summary=(
                "Annual software invoice spans 12 months."
                if stage is CloseStage.ADJUSTMENTS
                else f"{_STAGE_TITLES[stage]} control is supported by the synthetic pack."
            ),
            actor_id=(
                "preparer-demo"
                if stage is CloseStage.PREPARER_REVIEW
                else "reviewer-demo"
                if stage is CloseStage.INDEPENDENT_SIGNOFF
                else None
            ),
        )
        for stage in CLOSE_STAGE_ORDER
    )
    bundle_hash = compute_close_evidence_bundle_hash(identity, facts)
    snapshot = CloseSnapshot(
        identity=identity,
        evidence_bundle_hash=bundle_hash,
        policy_hash=evidence_hashes["close_policy"],
        facts=facts,
    )
    known_hashes = frozenset(evidence_hashes.values())
    verification = CloseVerificationContext(
        evidence_exists=lambda _identity, digest: digest in known_hashes,
        policy_is_current=lambda _identity, digest: digest == evidence_hashes["close_policy"],
        signoff_is_authorized=lambda *_args: True,
    )
    assessment = evaluate_period_close(snapshot, verification=verification)
    stages = []
    for index, stage_assessment in enumerate(assessment.stages):
        is_adjustment = stage_assessment.stage is CloseStage.ADJUSTMENTS
        is_waiting = stage_assessment.status.value == "waiting"
        stages.append(
            {
                "number": index + 1,
                "id": stage_assessment.stage.value,
                "title": _STAGE_TITLES[stage_assessment.stage],
                "status": stage_assessment.status.value,
                "status_label": _status_label(stage_assessment.status.value),
                "owner": _OWNERS[index],
                "evidence_count": _EVIDENCE_COUNTS[index],
                "blocker": (
                    "Annual software invoice spans 12 months"
                    if is_adjustment
                    else "Waiting on Adjustments"
                    if is_waiting
                    else None
                ),
                "next_action": (
                    "Validate prepaid allocation treatment"
                    if is_adjustment
                    else "Await completion of Adjustments"
                    if is_waiting
                    else "No action"
                ),
                "depends_on": [item.value for item in stage_assessment.depends_on],
            }
        )

    source_citations = [
        {
            "source_id": "INV-4821:p1:L8",
            "label": "Invoice service period",
            "text": "Service period: 2026-06-15 to 2027-06-14",
            "evidence_sha256": evidence_hashes["invoice_pdf"],
        },
        {
            "source_id": "POLICY-ACCRUAL-01:L6-L10",
            "label": "Synthetic close policy",
            "text": "Services extending beyond the reporting period require a documented allocation and human review.",
            "evidence_sha256": evidence_hashes["close_policy"],
        },
        {
            "source_id": "CTRL-ALLOC-v1",
            "label": "Deterministic allocation",
            "text": "Inclusive daily allocation through the June 2026 period end.",
            "evidence_sha256": bundle_hash,
        },
    ]
    core_case: dict[str, Any] = {
        "schema_version": "closeproof-case-v1",
        "case_id": _GOLDEN_CASE_ID,
        "finding_id": "finding_prepaid_inv_4821",
        "entity": {"id": identity.entity_id, "name": "Nordix Services AB"},
        "period": {"id": period, "label": "June 2026"},
        "title": "June close — Review required",
        "subtitle": "Evidence-linked controller review across close dependencies",
        "outcome": assessment.outcome.value,
        "selected_stage": CloseStage.ADJUSTMENTS.value,
        "stages": stages,
        "checks": checks,
        "finding": {
            "title": "Prepaid service period",
            "amount_ore": allocation["total_invoice_ore"],
            "amount_label": _format_ore(allocation["total_invoice_ore"]),
            "severity": "review_required",
            "summary": "Annual software invoice spans 12 months.",
            "source": {
                "document_id": "INV-4821",
                "supplier": invoice["supplier"],
                "invoice_date": invoice["invoice_date"],
                "page": 1,
                "line_range": "L8",
                "citation": source_citations[0],
            },
            "calculation": {
                **allocation,
                "label": "Calculated by controls",
                "method": "inclusive_daily_allocation",
                "current_period_expense_label": _format_ore(allocation["current_period_expense_ore"]),
                "prepaid_asset_label": _format_ore(allocation["prepaid_asset_ore"]),
            },
            "citations": source_citations,
        },
        "evidence": {
            "bundle_sha256": bundle_hash,
            "sources": evidence_hashes,
        },
        "safety": {
            "synthetic_only": True,
            "sweden_first": True,
            "erp_writes": False,
            "model_authority": "advisory_only",
            "strip": "Synthetic demo · Local controls · No ERP writes · Advisory optional",
        },
    }
    snapshot_sha = _canonical_hash(core_case)
    if snapshot_sha != GOLDEN_CLOSEPROOF_SNAPSHOT_SHA256:
        raise CloseProofCaseError(
            "golden synthetic fixture changed; review and pin the new snapshot before use"
        )
    case = {
        **core_case,
        "snapshot_sha256": snapshot_sha,
        "advisory": default_advisory_envelope(snapshot_sha),
        "decision": None,
    }
    refresh_review_context(case)
    manifest = {
        "schema_version": "closeproof-demo-manifest-v1",
        "case_id": case["case_id"],
        "snapshot_sha256": snapshot_sha,
        "review_context_sha256": case["review_context_sha256"],
        "inputs": {
            "general_ledger": str(ledger_path),
            "invoice_text": str(invoice_text_path),
            "policy": str(policy_path),
        },
        "outputs": {
            "case": str(output / "case.json"),
            "invoice_pdf": str(output / "invoice_INV-4821.pdf"),
        },
        "external_calls": 0,
        "erp_writes": 0,
        "advisory_status": "not_requested",
    }
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        output.chmod(0o700)
    except OSError as exc:
        raise CloseProofCaseError(
            "BalanceDocket output directory permissions could not be secured"
        ) from exc
    # `closeproof-demo` is an explicit fresh-demo command. A prior human
    # decision must never leak into the next golden run.
    events_path = output / "decision-events.jsonl"
    HashChainedEventLog(events_path).reset()
    _atomic_write_private(output / "invoice_INV-4821.pdf", pdf_bytes)
    _write_json(output / "case.json", case)
    _write_json(output / "manifest.json", manifest)
    _write_json(
        output / OUTPUT_OWNER_FILENAME,
        {
            "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
            "application": "closeproof",
            "case_id": _GOLDEN_CASE_ID,
        },
    )
    return case


def validate_closeproof_output_directory(output_dir: str | Path) -> Path:
    """Reject existing directories that CloseProof cannot prove it owns."""

    output = Path(output_dir)
    if output.is_symlink():
        raise CloseProofCaseError("BalanceDocket output directory must not be a symlink")
    if not output.exists():
        return output
    if not output.is_dir():
        raise CloseProofCaseError("BalanceDocket output must name a directory")
    try:
        entries = tuple(output.iterdir())
    except OSError as exc:
        raise CloseProofCaseError("BalanceDocket output directory could not be inspected") from exc
    if not entries:
        return output
    for name in _MANAGED_OUTPUT_FILENAMES:
        path = output / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CloseProofCaseError("BalanceDocket managed output could not be inspected") from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise CloseProofCaseError("BalanceDocket managed output must be a regular file")

    marker_path = output / OUTPUT_OWNER_FILENAME
    if marker_path.is_file():
        marker = _read_owned_json(marker_path)
        if marker != {
            "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
            "application": "closeproof",
            "case_id": _GOLDEN_CASE_ID,
        }:
            raise CloseProofCaseError("existing output is not an owned BalanceDocket demo")
        if _has_valid_owned_case_and_manifest(output):
            return output
        raise CloseProofCaseError("existing output is not an owned BalanceDocket demo")

    # Adopt exact legacy CloseProof outputs created before the ownership marker
    # existed, while rejecting arbitrary nonempty directories.
    if _has_valid_owned_case_and_manifest(output):
        return output
    raise CloseProofCaseError("existing output is not an owned BalanceDocket demo")


def _has_valid_owned_case_and_manifest(output: Path) -> bool:
    case_path = output / "case.json"
    manifest_path = output / "manifest.json"
    if not case_path.is_file() or not manifest_path.is_file():
        return False
    case = _read_owned_json(case_path)
    manifest = _read_owned_json(manifest_path)
    try:
        validate_golden_case_snapshot(case)
    except ValueError:
        return False
    return (
        case.get("schema_version") == "closeproof-case-v1"
        and case.get("case_id") == _GOLDEN_CASE_ID
        and manifest.get("schema_version") == "closeproof-demo-manifest-v1"
        and manifest.get("case_id") == _GOLDEN_CASE_ID
        and manifest.get("snapshot_sha256") == GOLDEN_CLOSEPROOF_SNAPSHOT_SHA256
        and manifest.get("external_calls") == 0
        and manifest.get("erp_writes") == 0
    )


def _parse_invoice(lines: tuple[str, ...]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        fields[label.strip().lower().replace(" ", "_")] = value.strip()
    required = ("supplier", "customer", "invoice_number", "invoice_date", "amount_sek", "service_period")
    missing = [field for field in required if not fields.get(field)]
    if missing:
        raise CloseProofCaseError(f"invoice fields are missing: {', '.join(missing)}")
    service_parts = fields["service_period"].split(" to ")
    if len(service_parts) != 2:
        raise CloseProofCaseError("service period must contain one 'to' separator")
    date.fromisoformat(fields["invoice_date"])
    date.fromisoformat(service_parts[0])
    date.fromisoformat(service_parts[1])
    Decimal(fields["amount_sek"])
    fields["service_start"], fields["service_end"] = service_parts
    return fields


def _parse_ledger(content: bytes) -> tuple[dict[str, str], ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CloseProofCaseError("ledger must be UTF-8") from exc
    rows = tuple(csv.DictReader(text.splitlines()))
    if not rows:
        raise CloseProofCaseError("ledger must contain rows")
    expected = {"posting_date", "account", "description", "reference", "debit_sek", "credit_sek"}
    if not expected.issubset(rows[0]):
        raise CloseProofCaseError("ledger schema is missing required columns")
    for row in rows:
        date.fromisoformat(row["posting_date"])
        Decimal(row["debit_sek"])
        Decimal(row["credit_sek"])
    return rows


def _run_controls(
    *,
    invoice: dict[str, str],
    ledger_rows: tuple[dict[str, str], ...],
    period: str,
    allocation: dict[str, Any],
) -> list[dict[str, Any]]:
    expense_matches = [
        row
        for row in ledger_rows
        if row["reference"] == invoice["invoice_number"]
        and Decimal(row["debit_sek"]) > 0
    ]
    duplicate_passed = len(expense_matches) == 1
    period_start, period_end = _period_bounds(period)
    posting_dates = [date.fromisoformat(row["posting_date"]) for row in expense_matches]
    cutoff_passed = bool(posting_dates) and all(period_start <= value <= period_end for value in posting_dates)
    return [
        {
            "id": "duplicate_invoice_identity",
            "label": "Duplicate identity",
            "status": "verified" if duplicate_passed else "review_required",
            "result": f"{len(expense_matches)} expense-side GL match for {invoice['invoice_number']}",
            "calculated_by": "controls",
        },
        {
            "id": "posting_cutoff",
            "label": "Posting cutoff",
            "status": "verified" if cutoff_passed else "review_required",
            "result": "Posting date is inside June 2026" if cutoff_passed else "Posting date is outside June 2026",
            "calculated_by": "controls",
        },
        {
            "id": "prepaid_service_period",
            "label": "Prepaid service period",
            "status": "review_required" if allocation["prepaid_asset_ore"] else "verified",
            "result": f"{allocation['service_days']} service days; {allocation['current_period_days']} in the current period",
            "calculated_by": "controls",
        },
    ]


def _calculate_allocation(
    *, amount_ore: int, service_start: date, service_end: date, period: str
) -> dict[str, Any]:
    if amount_ore <= 0:
        raise CloseProofCaseError("invoice amount must be positive")
    if service_end < service_start:
        raise CloseProofCaseError("service end must not precede service start")
    period_start, period_end = _period_bounds(period)
    service_days = (service_end - service_start).days + 1
    overlap_start = max(service_start, period_start)
    overlap_end = min(service_end, period_end)
    current_period_days = max(0, (overlap_end - overlap_start).days + 1)
    current = int(
        (Decimal(amount_ore) * Decimal(current_period_days) / Decimal(service_days)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return {
        "currency": "SEK",
        "total_invoice_ore": amount_ore,
        "service_start": service_start.isoformat(),
        "service_end": service_end.isoformat(),
        "service_days": service_days,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "current_period_days": current_period_days,
        "current_period_expense_ore": current,
        "prepaid_asset_ore": amount_ore - current,
        "formula": f"{amount_ore} × {current_period_days} ÷ {service_days}",
    }


def _status_label(status: str) -> str:
    return {
        "complete": "Verified",
        "review_required": "Review required",
        "blocked": "Blocked",
        "waiting": "Waiting on Adjustments",
    }[status]


def _period_bounds(period: str) -> tuple[date, date]:
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _sek_to_ore(value: str) -> int:
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def _format_ore(value: int) -> str:
    return f"SEK {Decimal(value) / Decimal(100):,.2f}"


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_private(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _read_owned_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            content = handle.read(1_000_001)
        if not 1 <= len(content) <= 1_000_000:
            raise ValueError("owned output size is invalid")
        value = json.loads(content.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("owned output must be an object")
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CloseProofCaseError("existing output is not an owned BalanceDocket demo") from exc


def _atomic_write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
