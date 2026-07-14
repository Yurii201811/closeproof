from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from accounting_agent.adapters.fortnox import FortnoxAdapter, FortnoxConfig
from accounting_agent.audit import JsonlAuditLog
from accounting_agent.hermes import (
    ApprovalPacket,
    ProposedAccountingEntry,
    write_approval_packet,
)
from accounting_agent.intake import (
    ClientMapper,
    ClientMappingRule,
    IntakeCase,
    IntakeSourceType,
    LocalIntakeProcessor,
    SQLiteIntakeStore,
)
from accounting_agent.permits import PermitIssuer, SQLitePermitStore
from accounting_agent.policy import (
    ActionType,
    PermissionMode,
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.risk_review import findings_from_dicts
from accounting_agent.supplier_invoice.pipeline import (
    build_supplier_invoice_policy_context,
    minor_amount,
)


DEFAULT_DEMO_OUTPUT = Path(".local/demo_supplier_invoice_autopilot")
DEMO_OUTPUT_MARKER = ".accounting_agent_demo_output"
DEMO_EVALUATION_DATE = date(2026, 5, 16)


class LocalDemoError(RuntimeError):
    """Raised when the local demo cannot be run safely or usefully."""


class DeterministicIdFactory:
    """Small stable id factory for repeatable local demo artifacts."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def __call__(self, prefix: str) -> str:
        self._counts[prefix] += 1
        return f"{prefix}_demo_{self._counts[prefix]:03d}"


def run_supplier_invoice_autopilot_demo(
    *,
    supplier_fixture_dir: str | Path = Path("fixtures/supplier_invoices"),
    output_dir: str | Path = DEFAULT_DEMO_OUTPUT,
    client_id: str = "fixture_client",
    entity_id: str = "fixture_entity",
    evaluation_date: date = DEMO_EVALUATION_DATE,
) -> dict[str, Any]:
    """Run the complete local supplier-invoice demo and write stage artifacts."""

    fixture_dir = Path(supplier_fixture_dir)
    output = Path(output_dir)
    fixture_paths = _fixture_paths(fixture_dir)
    paths = _prepare_output_tree(output)
    fixture_index = _load_fixture_index(fixture_paths)

    generated_intake_files = _write_intake_exports(
        fixture_index=fixture_index,
        intake_exports_dir=paths["intake_exports"],
    )
    intake_cases = _run_local_intake(
        intake_exports_dir=paths["intake_exports"],
        db_path=paths["db"],
        storage_root=paths["intake_storage"],
        client_id=client_id,
    )
    _write_json(paths["normalized_intake_cases"], [_jsonable(case) for case in intake_cases])

    pipeline = SupplierInvoicePipeline(
        db_path=paths["db"],
        output_dir=paths["approval_packets_json"],
        client_id=client_id,
        entity_id=entity_id,
        evaluation_date=evaluation_date,
    )
    packets = pipeline.process_fixture_dir(fixture_dir)

    audit_log = JsonlAuditLog(paths["audit_log"])
    permit_store = SQLitePermitStore(paths["db"])
    case_artifacts: list[dict[str, Any]] = []
    permits_issued = 0

    for packet in packets:
        case_id = str(packet["case"]["case_id"])
        scenario = _safe_name(str(packet["case"]["fixture_name"]))
        policy_context = _policy_context_from_packet(packet, client_id=client_id)
        gate_decision = evaluate_policy(policy_context)
        hermes_packet = _build_hermes_packet(packet, gate_decision, client_id=client_id)
        markdown_packet_path = write_approval_packet(
            hermes_packet,
            paths["approval_packets_markdown"],
        )
        fortnox_record = _build_fortnox_dry_run_record(
            packet=packet,
            policy_context=policy_context,
            policy_decision=gate_decision,
            permit_store=permit_store,
            upstream_policy_mode=str(packet["policy_decision"]["mode"]),
        )
        if fortnox_record["execution_permit"]["status"] == "issued":
            permits_issued += 1

        artifact_paths = {
            "extracted_invoice_json": paths["extracted"] / f"{scenario}.json",
            "accounting_proposal": paths["accounting"] / f"{scenario}.json",
            "risk_findings": paths["risk"] / f"{scenario}.json",
            "policy_decision": paths["policy"] / f"{scenario}.json",
            "execution_permit": paths["permits"] / f"{scenario}.json",
            "approval_packet_markdown": markdown_packet_path,
            "approval_packet_json": Path(packet["packet_path"]),
            "fortnox_dry_run_payload": paths["fortnox"] / f"{scenario}.json",
            "gnubok_shadow_output": paths["gnubok"] / f"{scenario}.json",
        }
        _write_json(
            artifact_paths["extracted_invoice_json"],
            {
                "case_id": case_id,
                "scenario": scenario,
                "extracted_fields": packet["extracted_fields"],
            },
        )
        _write_json(
            artifact_paths["accounting_proposal"],
            {
                "case_id": case_id,
                "scenario": scenario,
                "accounting_proposal": packet["accounting_proposal"],
                "vat_proposal": packet["vat_proposal"],
            },
        )
        _write_json(
            artifact_paths["risk_findings"],
            {
                "case_id": case_id,
                "scenario": scenario,
                "risk": packet["risk"],
                "risk_findings": packet["risk_findings"],
                "duplicate_check": packet["duplicate_check"],
                "supplier_match": packet["supplier_match"],
            },
        )
        _write_json(
            artifact_paths["policy_decision"],
            {
                "case_id": case_id,
                "scenario": scenario,
                "pipeline_policy_decision": packet["policy_decision"],
                "execution_gate_decision": _policy_decision_to_dict(gate_decision),
                "policy_alignment": {
                    "pipeline_mode": packet["policy_decision"]["mode"],
                    "execution_gate_mode": gate_decision.permission_mode.value,
                    "aligned": packet["policy_decision"]["mode"]
                    == gate_decision.permission_mode.value,
                },
            },
        )
        _write_json(
            artifact_paths["execution_permit"],
            fortnox_record["execution_permit"],
        )
        _write_json(artifact_paths["fortnox_dry_run_payload"], fortnox_record)
        _write_json(
            artifact_paths["gnubok_shadow_output"],
            {
                "case_id": case_id,
                "scenario": scenario,
                "shadow_ledger_comparison": packet["shadow_ledger_comparison"],
            },
        )
        audit_event = audit_log.append_event(
            event_type="local_demo_case_processed",
            case_id=case_id,
            client_id=policy_context.client_id,
            actor="local_demo",
            action="process_fixture_to_approval_packet",
            details={
                "scenario": scenario,
                "risk_level": packet["risk"]["level"],
                "policy_mode": gate_decision.permission_mode.value,
                "permit_status": fortnox_record["execution_permit"]["status"],
                "fortnox_live_api_call": False,
                "microsoft365_live_call": False,
                "email_sent": False,
                "approval_packet_markdown": str(markdown_packet_path),
            },
        )
        case_artifacts.append(
            {
                "case_id": case_id,
                "scenario": scenario,
                "source_filename": packet["document"]["source_filename"],
                "normalized_intake_case_id": _find_intake_case_id(
                    intake_cases,
                    packet["document"]["source_filename"],
                ),
                "risk_level": packet["risk"]["level"],
                "pipeline_policy_mode": packet["policy_decision"]["mode"],
                "execution_gate_mode": gate_decision.permission_mode.value,
                "permit_status": fortnox_record["execution_permit"]["status"],
                "fortnox_adapter_payload_status": fortnox_record["adapter_payload_status"],
                "gnubok_status": packet["shadow_ledger_comparison"]["status"],
                "audit_event_created_at": audit_event.created_at.isoformat(),
                "artifacts": {
                    key: _relative_to_output(value, output)
                    for key, value in artifact_paths.items()
                },
            }
        )

    summary = {
        "demo": "supplier_invoice_autopilot_local_demo",
        "status": "complete",
        "output_dir": str(output),
        "database": str(paths["db"]),
        "supplier_fixture_count": len(fixture_paths),
        "generated_intake_source_files": len(generated_intake_files),
        "normalized_intake_cases": len(intake_cases),
        "approval_packets": len(packets),
        "execution_permits_issued": permits_issued,
        "fortnox_live_api_calls": 0,
        "microsoft365_live_calls": 0,
        "email_sends": 0,
        "payments_or_filings": 0,
        "gnubok_mode": "local_shadow_stub",
        "evaluation_date": evaluation_date.isoformat(),
        "risk_levels": dict(Counter(packet["risk"]["level"] for packet in packets)),
        "policy_modes": dict(
            Counter(packet["policy_decision"]["mode"] for packet in packets)
        ),
        "artifacts": {
            "normalized_intake_cases": _relative_to_output(
                paths["normalized_intake_cases"],
                output,
            ),
            "approval_packets_json": _relative_to_output(
                paths["approval_packets_json"],
                output,
            ),
            "approval_packets_markdown": _relative_to_output(
                paths["approval_packets_markdown"],
                output,
            ),
            "audit_log": _relative_to_output(paths["audit_log"], output),
            "summary": "summary.json",
            "manifest": "manifest.json",
        },
    }
    manifest = {
        "summary": summary,
        "run_context": {
            "evaluation_date": evaluation_date.isoformat(),
            "evaluation_date_source": "explicit_synthetic_scenario_date",
            "client_id": client_id,
            "entity_id": entity_id,
            "jurisdiction_pack": "se-2026",
        },
        "cases": case_artifacts,
        "safety": {
            "uses_sample_fixtures_only": True,
            "live_fortnox_calls": False,
            "live_microsoft365_calls": False,
            "emails_sent": False,
            "payments_or_filings": False,
            "final_bookkeeping": False,
        },
    }
    _write_json(paths["summary"], summary)
    _write_json(paths["manifest"], manifest)
    return manifest


def _fixture_paths(fixture_dir: Path) -> list[Path]:
    if not fixture_dir.exists():
        raise LocalDemoError(
            f"Supplier invoice fixture folder does not exist: {fixture_dir}. "
            "Use the repo sample fixtures or pass --fixtures to a folder with .json samples."
        )
    if not fixture_dir.is_dir():
        raise LocalDemoError(
            f"Supplier invoice fixture path is not a folder: {fixture_dir}."
        )
    fixture_paths = sorted(fixture_dir.glob("*.json"))
    if not fixture_paths:
        raise LocalDemoError(
            f"No supplier invoice .json fixtures found in {fixture_dir}. "
            "Add synthetic fixtures before running the local demo."
        )
    return fixture_paths


def _prepare_output_tree(output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "db": output / "demo.sqlite",
        "intake_exports": output / "intake_source_exports",
        "intake_storage": output / "stored_intake_documents",
        "normalized_intake_cases": output / "normalized_intake_cases.json",
        "extracted": output / "extracted_invoice_json",
        "accounting": output / "accounting_proposals",
        "risk": output / "risk_findings",
        "policy": output / "policy_decisions",
        "permits": output / "execution_permits",
        "approval_packets_json": output / "approval_packets" / "json",
        "approval_packets_markdown": output / "approval_packets" / "markdown",
        "fortnox": output / "fortnox_dry_run_payloads",
        "gnubok": output / "gnubok_shadow_outputs",
        "audit_log": output / "audit_log.jsonl",
        "summary": output / "summary.json",
        "manifest": output / "manifest.json",
    }
    _ensure_demo_output_can_be_cleared(output, paths)
    _replace_text(
        output / DEMO_OUTPUT_MARKER,
        "managed by accounting_agent local supplier invoice demo\n",
    )
    for folder_key in (
        "intake_exports",
        "intake_storage",
        "extracted",
        "accounting",
        "risk",
        "policy",
        "permits",
        "approval_packets_json",
        "approval_packets_markdown",
        "fortnox",
        "gnubok",
    ):
        _clear_generated_files(paths[folder_key])
    for file_key in (
        "db",
        "normalized_intake_cases",
        "audit_log",
        "summary",
        "manifest",
    ):
        _unlink_if_exists(paths[file_key])
    for sqlite_suffix in ("-shm", "-wal", "-journal"):
        _unlink_if_exists(Path(f"{paths['db']}{sqlite_suffix}"))
    paths["audit_log"].parent.mkdir(parents=True, exist_ok=True)
    _replace_text(paths["audit_log"], "")
    return paths


def _ensure_demo_output_can_be_cleared(output: Path, paths: dict[str, Path]) -> None:
    if (output / DEMO_OUTPUT_MARKER).exists() or _looks_like_previous_demo_output(output):
        return

    existing_generated_paths = []
    for key, path in paths.items():
        if key in {"summary", "manifest", "audit_log", "normalized_intake_cases", "db"}:
            if path.exists():
                existing_generated_paths.append(path)
            continue
        if path.exists() and (path.is_file() or any(path.iterdir())):
            existing_generated_paths.append(path)

    if existing_generated_paths:
        preview = ", ".join(str(path) for path in existing_generated_paths[:3])
        raise LocalDemoError(
            "Refusing to clear an unmarked output folder. Choose an empty folder, "
            f"use the default .local demo path, or remove/mark the existing demo output first: {preview}"
        )


def _looks_like_previous_demo_output(output: Path) -> bool:
    manifest_path = output / "manifest.json"
    summary_path = output / "summary.json"
    try:
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                isinstance(manifest, dict)
                and isinstance(manifest.get("summary"), dict)
                and manifest["summary"].get("demo") == "supplier_invoice_autopilot_local_demo"
            ):
                return True
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if (
                isinstance(summary, dict)
                and summary.get("demo") == "supplier_invoice_autopilot_local_demo"
            ):
                return True
    except json.JSONDecodeError:
        return False
    return False


def _clear_generated_files(folder: Path) -> None:
    if folder.exists():
        for path in sorted(folder.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
    folder.mkdir(parents=True, exist_ok=True)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _load_fixture_index(fixture_paths: list[Path]) -> dict[Path, dict[str, Any]]:
    fixtures: dict[Path, dict[str, Any]] = {}
    for fixture_path in fixture_paths:
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LocalDemoError(
                f"Fixture {fixture_path} is not valid JSON: {exc.msg}."
            ) from exc
        if not isinstance(fixture, dict):
            raise LocalDemoError(f"Fixture {fixture_path} must contain a JSON object.")
        if "mock_extraction" not in fixture:
            raise LocalDemoError(
                f"Fixture {fixture_path} is missing mock_extraction. "
                "The local demo does not call paid OCR or live document AI."
            )
        fixtures[fixture_path] = fixture
    return fixtures


def _write_intake_exports(
    *,
    fixture_index: dict[Path, dict[str, Any]],
    intake_exports_dir: Path,
) -> list[Path]:
    written: list[Path] = []
    for fixture_path, fixture in fixture_index.items():
        source_filename = Path(
            str(fixture.get("source_filename") or f"{fixture_path.stem}.txt")
        ).name
        target = intake_exports_dir / source_filename
        _replace_text(target, _render_intake_export(fixture))
        written.append(target)
    return written


def _render_intake_export(fixture: dict[str, Any]) -> str:
    extracted = dict(fixture["mock_extraction"])
    amounts = extracted.get("amounts") or {}
    gross = amounts.get("gross") or ""
    currency = extracted.get("currency") or "SEK"
    return "\n".join(
        [
            f"Supplier: {extracted.get('supplier_name') or ''}",
            f"Invoice number: {extracted.get('invoice_number') or ''}",
            f"Invoice date: {extracted.get('invoice_date') or ''}",
            f"Amount: {gross} {currency}".strip(),
            f"Scenario: {fixture.get('scenario') or 'unnamed_fixture'}",
            "",
            "Synthetic OCR text from repo fixture:",
            fixture.get("ocr_text") or "",
            "",
        ]
    )


def _run_local_intake(
    *,
    intake_exports_dir: Path,
    db_path: Path,
    storage_root: Path,
    client_id: str,
) -> tuple[IntakeCase, ...]:
    store = SQLiteIntakeStore(db_path)
    store.add_client_mapping_rule(
        ClientMappingRule(
            rule_id="local-demo-folder",
            match_type="folder",
            pattern="intake_source_exports",
            client_id=client_id,
            priority=10,
        )
    )
    processor = LocalIntakeProcessor(
        store=store,
        storage_root=storage_root,
        client_mapper=ClientMapper.from_store(store),
        id_factory=DeterministicIdFactory(),
    )
    return processor.scan_folder(
        intake_exports_dir,
        source_type=IntakeSourceType.ONEDRIVE_FOLDER_FILE,
    )


def _policy_context_from_packet(
    packet: dict[str, Any],
    *,
    client_id: str,
) -> PolicyContext:
    return build_supplier_invoice_policy_context(
        client_id=client_id,
        extracted=packet["extracted_fields"],
        supplier_match=packet["supplier_match"],
        duplicate_check=packet["duplicate_check"],
        vat_proposal=packet["vat_proposal"],
        risk_findings=findings_from_dicts(packet.get("risk_findings", ())),
    )


def _build_hermes_packet(
    packet: dict[str, Any],
    policy_decision: PolicyDecision,
    *,
    client_id: str,
) -> ApprovalPacket:
    extracted = packet["extracted_fields"]
    return ApprovalPacket(
        case_id=packet["case"]["case_id"],
        client_id=client_id,
        source_document=packet["document"]["source_filename"],
        extracted_fields=extracted,
        proposed_entries=tuple(
            ProposedAccountingEntry(
                account=str(entry["account"]),
                description=str(entry.get("description") or ""),
                debit_minor=minor_amount(entry.get("debit")),
                credit_minor=minor_amount(entry.get("credit")),
                vat_code=entry.get("vat_code"),
                evidence=packet["document"]["source_filename"],
            )
            for entry in packet["accounting_proposal"]["entries"]
        ),
        confidence_scores={
            "extraction": float(extracted.get("extraction_confidence") or 0.0),
            "supplier_match": float(packet["supplier_match"].get("confidence") or 0.0),
            "accounting_proposal": float(
                packet["accounting_proposal"].get("confidence") or 0.0
            ),
            "vat": 1.0 if packet["vat_proposal"].get("status") == "normal" else 0.5,
        },
        risk_flags=tuple(flag["code"] for flag in packet["risk"]["flags"]),
        policy_decision=policy_decision,
        proposed_fortnox_action=(
            f"{packet['next_action']['action']}: {packet['next_action']['reason']}"
        ),
        fortnox_payload_summary={
            "target_adapter": packet["fortnox_draft_payload"]["target_adapter"],
            "dry_run": True,
            "live_api_call": False,
            "supplier_id": packet["fortnox_draft_payload"].get("supplier_id"),
            "invoice_number": packet["fortnox_draft_payload"].get("invoice_number"),
            "total": packet["fortnox_draft_payload"].get("total"),
            "currency": packet["fortnox_draft_payload"].get("currency"),
        },
        risk_findings=tuple(packet.get("risk_findings", ())),
    )


def _build_fortnox_dry_run_record(
    *,
    packet: dict[str, Any],
    policy_context: PolicyContext,
    policy_decision: PolicyDecision,
    permit_store: SQLitePermitStore,
    upstream_policy_mode: str,
) -> dict[str, Any]:
    adapter = FortnoxAdapter(config=FortnoxConfig(dry_run=True))
    record: dict[str, Any] = {
        "case_id": packet["case"]["case_id"],
        "scenario": packet["case"]["fixture_name"],
        "status": "dry_run_only",
        "external_system_contacted": False,
        "live_api_call": False,
        "pipeline_payload": packet["fortnox_draft_payload"],
        "adapter_payload_status": "not_prepared",
        "adapter_payload": None,
        "adapter_dry_run_result": None,
        "execution_permit": {
            "status": "not_issued",
            "reason": "adapter_payload_not_prepared",
        },
        "safety": {
            "booked": False,
            "payment_pending": False,
            "email_sent": False,
            "final_bookkeeping": False,
        },
    }
    try:
        adapter_payload = _prepare_fortnox_adapter_payload(adapter, packet)
    except ValueError as exc:
        record["adapter_payload_error"] = str(exc)
        record["actionable_next_step"] = (
            "Fix the extraction or reviewer-supplied fields, then rerun the demo. "
            "The local demo will not fabricate Fortnox-required fields."
        )
        return record

    record["adapter_payload"] = adapter_payload
    record["adapter_payload_status"] = (
        "prepared"
        if policy_decision.permission_mode is PermissionMode.DRAFT_ONLY
        else "prepared_but_review_blocked"
    )

    if policy_decision.permission_mode.value != upstream_policy_mode:
        record["execution_permit"] = {
            "status": "not_issued_policy_disagreement",
            "pipeline_mode": upstream_policy_mode,
            "execution_gate_mode": policy_decision.permission_mode.value,
            "reason": "Policy disagreement is a hard stop; neither result may issue a permit.",
        }
        record["adapter_payload_status"] = "prepared_but_policy_disagreement"
        return record

    if (
        policy_decision.permission_mode is not PermissionMode.DRAFT_ONLY
        or policy_decision.required_reviews
    ):
        status = (
            "not_issued_forbidden"
            if policy_decision.permission_mode is PermissionMode.FORBIDDEN
            else "not_issued_review_required"
        )
        record["execution_permit"] = {
            "status": status,
            "permission_mode": policy_decision.permission_mode.value,
            "required_reviews": list(policy_decision.required_reviews),
            "reasons": list(policy_decision.reasons),
            "actionable_next_step": (
                "Resolve the review reasons before issuing any future external-write permit."
            ),
        }
        return record

    issuer = PermitIssuer(
        permit_store,
        id_factory=lambda: f"permit_{packet['case']['case_id']}",
    )
    permit = issuer.issue(
        decision=policy_decision,
        context=policy_context,
        case_id=packet["case"]["case_id"],
        entity_id=packet["case"]["entity_id"],
        payload=adapter_payload,
    )
    dry_run_result = adapter.create_supplier_invoice_draft(
        case_id=packet["case"]["case_id"],
        entity_id=packet["case"]["entity_id"],
        payload=adapter_payload,
        permit=permit,
    )
    record["execution_permit"] = {
        "status": "issued",
        "permit": _jsonable(permit),
        "scope": "local_dry_run_supplier_invoice_draft_only",
    }
    record["adapter_dry_run_result"] = _jsonable(dry_run_result)
    return record


def _prepare_fortnox_adapter_payload(
    adapter: FortnoxAdapter,
    packet: dict[str, Any],
) -> dict[str, Any]:
    extracted = packet["extracted_fields"]
    missing = [
        field
        for field in ("invoice_number", "invoice_date", "due_date")
        if not extracted.get(field)
    ]
    amounts = extracted.get("amounts") or {}
    missing.extend(
        f"amounts.{field}" for field in ("gross", "vat") if not amounts.get(field)
    )
    if missing:
        raise ValueError(
            "Cannot prepare Fortnox-shaped supplier invoice payload for "
            f"{packet['case']['case_id']} because required fields are missing: "
            + ", ".join(missing)
        )

    supplier_number = packet["supplier_match"].get("supplier_id")
    if not supplier_number:
        supplier_number = "unknown_supplier_review_required"
    return adapter.prepare_supplier_invoice_draft_payload(
        supplier_number=str(supplier_number),
        invoice_number=str(extracted["invoice_number"]),
        invoice_date=str(extracted["invoice_date"]),
        due_date=str(extracted["due_date"]),
        total=str(amounts["gross"]),
        vat=str(amounts["vat"]),
        currency=str(extracted.get("currency") or "SEK"),
        rows=_fortnox_rows_from_accounting(packet["accounting_proposal"]["entries"]),
        comments=(
            "LOCAL DEMO DRY RUN ONLY. No live Fortnox call, approval, payment, "
            f"or posting. Case {packet['case']['case_id']}."
        ),
        our_reference="Accounting Agent local demo",
    )


def _fortnox_rows_from_accounting(
    accounting_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in accounting_entries:
        row = {
            "account": entry["account"],
            "description": entry.get("description") or "",
        }
        if minor_amount(entry.get("debit")):
            row["debit"] = entry.get("debit")
        if minor_amount(entry.get("credit")):
            row["credit"] = entry.get("credit")
        rows.append(row)
    return rows


def _policy_decision_to_dict(decision: PolicyDecision) -> dict[str, Any]:
    return {
        "action_type": decision.action_type.value,
        "client_id": decision.client_id,
        "permission_mode": decision.permission_mode.value,
        "policy_version": decision.policy_version,
        "amount_thresholds": asdict(decision.amount_thresholds),
        "required_reviews": list(decision.required_reviews),
        "reasons": list(decision.reasons),
        "is_external_write": decision.is_external_write,
    }


def _find_intake_case_id(intake_cases: tuple[IntakeCase, ...], file_name: str) -> str | None:
    for case in intake_cases:
        if case.file_name == file_name:
            return case.case_id
    return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace_text(
        path,
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _replace_text(path: Path, text: str) -> None:
    """Write generated text without opening stale offloaded placeholders."""

    path.parent.mkdir(parents=True, exist_ok=True)
    _unlink_if_exists(path)
    path.write_text(text, encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__") and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


def _relative_to_output(path: Path, output: Path) -> str:
    try:
        return str(path.relative_to(output))
    except ValueError:
        return str(path)
