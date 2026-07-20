from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from datetime import date
from pathlib import Path

from accounting_agent.bank_reconciliation import BankReconciliationPipeline
from accounting_agent.agentic import agentic_platform_summary
from accounting_agent.db import LocalQueue
from accounting_agent.fake_client_dry_run import (
    DEFAULT_FAKE_CLIENT_OUTPUT,
    DEFAULT_FAKE_CLIENT_REPORT,
    FakeClientDryRunError,
    run_fake_client_dry_run,
)
from accounting_agent.intake import IntakeSourceType, LocalIntakeProcessor, SQLiteIntakeStore
from accounting_agent.erp import erp_registry_summary
from accounting_agent.jurisdictions import jurisdiction_registry_summary
from accounting_agent.local_demo import (
    DEFAULT_DEMO_OUTPUT,
    DEMO_EVALUATION_DATE,
    LocalDemoError,
    run_supplier_invoice_autopilot_demo,
)
from accounting_agent.operations_cockpit import (
    DEFAULT_OUTPUT_PATH as DEFAULT_OPERATIONS_COCKPIT_OUTPUT,
    DEFAULT_PUBLIC_PREVIEW_DIR,
    build_operations_cockpit,
    build_public_preview,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.v1 import build_v1_platform_summary, run_v1_synthetic_system_check
from accounting_agent.closeproof import (
    DEFAULT_CLOSEPROOF_FIXTURE,
    DEFAULT_CLOSEPROOF_OUTPUT,
    CODEX_MODEL_ID,
    MODEL_ID,
    PROVIDER_CODEX_SUBSCRIPTION,
    PROVIDER_OPENAI_API,
    AdvisoryError,
    build_closeproof_demo,
    failed_advisory_envelope,
    import_advisory,
    invoke_codex_subscription_advisory,
    invoke_gpt56_advisory,
    prepare_advisory,
    prepared_advisory_envelope,
    validate_advisory_envelope,
    write_live_advisory,
)
from accounting_agent.closeproof.server import CloseProofServerError, serve_closeproof


DEFAULT_FIXTURES = Path("fixtures/supplier_invoices")
DEFAULT_BANK_FIXTURES = Path("fixtures/bank_reconciliation")
DEFAULT_M365_FIXTURES = Path("fixtures/microsoft365_intake")
DEFAULT_DB = Path(".local/accounting_agent.sqlite")
DEFAULT_OUTPUT = Path(".local/approval_packets")
DEFAULT_BANK_OUTPUT = Path(".local/bank_reconciliation_packets")
DEFAULT_INTAKE_STORAGE = Path(".local/intake_documents")
DEFAULT_CLOSEPROOF_CASE = DEFAULT_CLOSEPROOF_OUTPUT / "case.json"
DEFAULT_CLOSEPROOF_EVENTS = DEFAULT_CLOSEPROOF_OUTPUT / "decision-events.jsonl"
DEFAULT_CLOSEPROOF_WEB = Path("apps/closeproof-web/dist")
DEFAULT_CLOSEPROOF_ADVISORY_REQUEST = DEFAULT_CLOSEPROOF_OUTPUT / "advisory-request.json"
DEFAULT_CLOSEPROOF_ADVISORY_OUTPUT = DEFAULT_CLOSEPROOF_OUTPUT / "advisory-output.json"


def _load_bounded_json(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError("JSON input must be a regular file")
    with path.open("rb") as handle:
        content = handle.read(maximum_bytes + 1)
    if not 1 <= len(content) <= maximum_bytes:
        raise ValueError("JSON input size is invalid")
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be an object")
    return payload


def _paths_alias(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return left.expanduser().resolve(strict=False) == right.expanduser().resolve(
            strict=False
        )


def _atomic_write_private_json(path: Path, value: dict[str, object]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Accounting Agent local operator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    process = subparsers.add_parser(
        "process-fixtures",
        help="Process supplier invoice sample fixtures into approval packets.",
    )
    process.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    process.add_argument("--db", type=Path, default=DEFAULT_DB)
    process.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    process.add_argument(
        "--client-id",
        default="fixture_client",
        help="Exact synthetic tenant/client scope for this fixture run.",
    )
    process.add_argument(
        "--entity-id",
        default="fixture_entity",
        help="Exact synthetic legal-entity scope for this fixture run.",
    )
    process.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=DEMO_EVALUATION_DATE,
        help="Evaluation date for deterministic fixture risk review (YYYY-MM-DD).",
    )

    reconcile = subparsers.add_parser(
        "reconcile-bank-fixtures",
        help="Process sample bank transactions into reconciliation proposals.",
    )
    reconcile.add_argument("--fixtures", type=Path, default=DEFAULT_BANK_FIXTURES)
    reconcile.add_argument("--output", type=Path, default=DEFAULT_BANK_OUTPUT)

    intake = subparsers.add_parser(
        "scan-intake-folder",
        help="Scan a local/mock Microsoft 365 folder into normalized intake cases.",
    )
    intake.add_argument("--folder", type=Path, default=DEFAULT_M365_FIXTURES)
    intake.add_argument("--db", type=Path, default=DEFAULT_DB)
    intake.add_argument("--storage", type=Path, default=DEFAULT_INTAKE_STORAGE)
    intake.add_argument(
        "--source-type",
        choices=[source_type.value for source_type in IntakeSourceType],
        default=IntakeSourceType.ONEDRIVE_FOLDER_FILE.value,
    )

    demo = subparsers.add_parser(
        "demo-supplier-invoice-autopilot",
        help="Run the complete local Supplier Invoice Autopilot demo.",
    )
    demo.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    demo.add_argument("--output", type=Path, default=DEFAULT_DEMO_OUTPUT)
    demo.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=DEMO_EVALUATION_DATE,
        help="Evaluation date for deterministic fixture risk review (YYYY-MM-DD).",
    )

    fake_client = subparsers.add_parser(
        "fake-client-dry-run",
        help="Run a full synthetic Swedish fake-client month through the local MVP.",
    )
    fake_client.add_argument("--output", type=Path, default=DEFAULT_FAKE_CLIENT_OUTPUT)
    fake_client.add_argument("--report", type=Path, default=DEFAULT_FAKE_CLIENT_REPORT)

    cockpit = subparsers.add_parser(
        "build-operations-cockpit",
        help="Build a read-only static local operations cockpit from repo artifacts.",
    )
    cockpit.add_argument("--output", type=Path, default=DEFAULT_OPERATIONS_COCKPIT_OUTPUT)

    public_preview = subparsers.add_parser(
        "build-public-preview",
        help="Build a deployable cockpit from built-in synthetic examples only.",
    )
    public_preview.add_argument("--output", type=Path, default=DEFAULT_PUBLIC_PREVIEW_DIR)

    platform_status = subparsers.add_parser(
        "platform-status",
        help="Show jurisdiction, ERP capability, computer-use, role, and specialist boundaries.",
    )
    platform_status.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete machine-readable platform declaration.",
    )

    v1_check = subparsers.add_parser(
        "v1-system-check",
        help="Exercise every v1 control-plane seam with deterministic synthetic data.",
    )
    v1_check.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete machine-readable system-check result.",
    )

    closeproof_demo = subparsers.add_parser(
        "closeproof-demo",
        help="Build the deterministic synthetic BalanceDocket golden case.",
    )
    closeproof_demo.add_argument("--fixture", type=Path, default=DEFAULT_CLOSEPROOF_FIXTURE)
    closeproof_demo.add_argument("--output", type=Path, default=DEFAULT_CLOSEPROOF_OUTPUT)

    closeproof_advisory = subparsers.add_parser(
        "closeproof-advisory",
        help="Prepare, import, or explicitly invoke one provider-neutral advisory.",
    )
    advisory_commands = closeproof_advisory.add_subparsers(dest="advisory_command")
    advisory_status = advisory_commands.add_parser(
        "status", help="Show the current provider/provenance advisory envelope."
    )
    advisory_status.add_argument("--case", type=Path, default=DEFAULT_CLOSEPROOF_CASE)
    advisory_prepare = advisory_commands.add_parser(
        "prepare", help="Write a provider-neutral request for manual/offline use."
    )
    advisory_prepare.add_argument("--case", type=Path, default=DEFAULT_CLOSEPROOF_CASE)
    advisory_prepare.add_argument(
        "--output", type=Path, default=DEFAULT_CLOSEPROOF_ADVISORY_REQUEST
    )
    advisory_import = advisory_commands.add_parser(
        "import", help="Validate and import a manually produced advisory output."
    )
    advisory_import.add_argument("--case", type=Path, default=DEFAULT_CLOSEPROOF_CASE)
    advisory_import.add_argument(
        "--input", type=Path, default=DEFAULT_CLOSEPROOF_ADVISORY_OUTPUT
    )
    advisory_import.add_argument("--reported-model")
    advisory_import.add_argument("--run-id")
    advisory_import.add_argument("--response-id")
    advisory_codex = advisory_commands.add_parser(
        "codex", help="Use GPT-5.6 Sol through the local ChatGPT-authenticated Codex CLI."
    )
    advisory_codex.add_argument("--case", type=Path, default=DEFAULT_CLOSEPROOF_CASE)
    advisory_codex.add_argument(
        "--confirm-use-codex-allowance",
        action="store_true",
        help="Required confirmation that this run consumes the user's Codex/ChatGPT allowance.",
    )
    advisory_codex.add_argument("--timeout", type=float, default=120.0)
    advisory_api = advisory_commands.add_parser(
        "api", help="Use the optional OPENAI_API_KEY Responses API path."
    )
    advisory_api.add_argument("--case", type=Path, default=DEFAULT_CLOSEPROOF_CASE)
    advisory_api.add_argument(
        "--enable-network-advisory",
        action="store_true",
        help="Required opt-in for the synthetic GPT-5.6 Responses API call.",
    )

    closeproof_serve = subparsers.add_parser(
        "closeproof-serve",
        help="Serve the built BalanceDocket reviewer on loopback only.",
    )
    closeproof_serve.add_argument("--case", type=Path, default=DEFAULT_CLOSEPROOF_CASE)
    closeproof_serve.add_argument("--events", type=Path, default=DEFAULT_CLOSEPROOF_EVENTS)
    closeproof_serve.add_argument("--web", type=Path, default=DEFAULT_CLOSEPROOF_WEB)
    closeproof_serve.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    closeproof_serve.add_argument("--port", type=int, default=4173)
    closeproof_serve.add_argument("--socket-fd", type=int, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == "process-fixtures":
        pipeline = SupplierInvoicePipeline(
            db_path=args.db,
            output_dir=args.output,
            client_id=args.client_id,
            entity_id=args.entity_id,
            evaluation_date=args.as_of,
        )
        packets = pipeline.process_fixture_dir(args.fixtures)
        queue = LocalQueue(args.db)
        print(f"Processed {len(packets)} supplier invoice fixtures")
        print(f"Approval packets: {args.output}")
        print(f"SQLite queue: {args.db}")
        print(f"Stored approval packets: {queue.count('approval_packets')}")
        print(f"Evaluation date: {args.as_of.isoformat()}")
        for packet in packets:
            print(
                f"- {packet['case']['fixture_name']}: "
                f"{packet['policy_decision']['mode']} / "
                f"{packet['risk']['level']} risk -> {packet['packet_path']}"
            )
        return 0

    if args.command == "reconcile-bank-fixtures":
        pipeline = BankReconciliationPipeline(output_dir=args.output)
        proposals = pipeline.process_fixture_dir(args.fixtures)
        packet_count = sum(1 for proposal in proposals if proposal.get("approval_packet_path"))
        print(f"Processed {len(proposals)} bank transaction fixtures")
        print(f"Approval packets: {args.output}")
        print(f"Approval packets generated: {packet_count}")
        for proposal in proposals:
            selected = proposal["selected_candidate"]
            target = selected["target_id"] if selected else "unmatched"
            packet_path = proposal.get("approval_packet_path", "")
            suffix = f" -> {packet_path}" if packet_path else ""
            print(
                f"- {proposal['transaction']['transaction_id']}: "
                f"{target} / {proposal['policy_decision']['mode']} / "
                f"{proposal['confidence']:.2f} confidence{suffix}"
            )
        return 0

    if args.command == "scan-intake-folder":
        store = SQLiteIntakeStore(args.db)
        processor = LocalIntakeProcessor(store=store, storage_root=args.storage)
        cases = processor.scan_folder(
            args.folder,
            source_type=IntakeSourceType(args.source_type),
        )
        tasks = store.list_extraction_tasks()
        print(f"Scanned {len(cases)} local intake files")
        print(f"SQLite queue: {args.db}")
        print(f"Stored documents: {args.storage}")
        print(f"Extraction tasks queued: {len(tasks)}")
        for case in cases:
            duplicate = (
                f" duplicate_of={case.duplicate_of_case_id} reasons={','.join(case.duplicate_reasons)}"
                if case.duplicate_reasons
                else ""
            )
            print(f"- {case.file_name}: {case.case_id} client={case.client_id}{duplicate}")
        return 0

    if args.command == "demo-supplier-invoice-autopilot":
        try:
            manifest = run_supplier_invoice_autopilot_demo(
                supplier_fixture_dir=args.fixtures,
                output_dir=args.output,
                evaluation_date=args.as_of,
            )
        except LocalDemoError as exc:
            print(f"Demo failed: {exc}", file=sys.stderr)
            return 1
        summary = manifest["summary"]
        print("Supplier Invoice Autopilot local demo complete")
        print(f"Output folder: {summary['output_dir']}")
        print(f"Normalized intake cases: {summary['normalized_intake_cases']}")
        print(f"Approval packets: {summary['approval_packets']}")
        print(f"Execution permits issued: {summary['execution_permits_issued']}")
        print(f"Evaluation date: {summary['evaluation_date']}")
        print("Live Fortnox calls: 0")
        print("Live Microsoft 365 calls: 0")
        print("Emails/payments/filings: 0")
        print(f"Summary: {args.output / 'summary.json'}")
        print(f"Manifest: {args.output / 'manifest.json'}")
        return 0

    if args.command == "fake-client-dry-run":
        try:
            manifest = run_fake_client_dry_run(
                output_dir=args.output,
                report_path=args.report,
            )
        except (FakeClientDryRunError, LocalDemoError) as exc:
            print(f"Fake-client dry run failed: {exc}", file=sys.stderr)
            return 1
        metrics = manifest["metrics"]
        print("Fake-client accounting MVP dry run complete")
        print(f"Output folder: {manifest['run']['output_dir']}")
        print(f"Report: {manifest['run']['report_path']}")
        print(
            "Sample data: "
            f"{metrics['sample_counts']['supplier_invoices_or_receipts']} supplier invoices/receipts, "
            f"{metrics['sample_counts']['customer_invoices']} customer invoices, "
            f"{metrics['sample_counts']['bank_transactions']} bank transactions"
        )
        print(f"Primary policy decisions: {metrics['primary_case_decision_counts']}")
        print(f"Observed policy decisions: {metrics['observed_policy_decision_counts']}")
        print(f"False positives: {len(metrics['false_positives'])}")
        print(f"Unsafe misses: {len(metrics['unsafe_misses'])}")
        print(f"Unclear outputs: {len(metrics['unclear_outputs'])}")
        print(f"Policy alignment warnings: {len(metrics['policy_alignment_warnings'])}")
        print("Live Fortnox calls: 0")
        print("Live Microsoft 365 calls: 0")
        print("Emails/payments/filings/final postings: 0")
        return 0

    if args.command == "build-operations-cockpit":
        try:
            result = build_operations_cockpit(output_path=args.output)
        except (OSError, ValueError) as exc:
            print(f"Operations cockpit build failed: {exc}", file=sys.stderr)
            return 1
        print("Operations cockpit built")
        print(f"Output: {result.output_path}")
        print(f"Links checked: {result.link_targets_checked}")
        print(f"Broken links: {len(result.broken_links)}")
        print("Live Fortnox calls: 0")
        print("Live Microsoft 365 calls: 0")
        print("Emails/payments/filings/final postings: 0")
        if result.broken_links:
            for path in result.broken_links:
                print(f"- broken link target: {path}")
            return 1
        return 0

    if args.command == "build-public-preview":
        try:
            result = build_public_preview(output_dir=args.output)
        except (OSError, ValueError) as exc:
            print(f"Public preview build failed: {exc}", file=sys.stderr)
            return 1
        print("Synthetic public preview built")
        print(f"Output: {result.output_path}")
        print(f"Manifest: {result.output_path.parent / 'preview-manifest.json'}")
        print(f"Links checked: {result.link_targets_checked}")
        print(f"Broken links: {len(result.broken_links)}")
        print(
            "Source artifact links: 0; builder network/hosted-model/ERP-write "
            "capabilities: unavailable"
        )
        if result.broken_links:
            for path in result.broken_links:
                print(f"- broken link target: {path}")
            return 1
        return 0

    if args.command == "platform-status":
        payload = {
            "v1": build_v1_platform_summary(),
            "jurisdictions": jurisdiction_registry_summary(),
            "erp": erp_registry_summary(),
            "agentic": agentic_platform_summary(),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        print("Accounting Agent v1 platform boundary")
        print("Default jurisdiction: se-2026 (foundation only, no filing claim)")
        print("ERP profiles:")
        for profile in payload["erp"]["profiles"]:
            print(f"- {profile['display_name']}: {profile['connection_status']}")
        print("External post/approve/send/pay/file/delete/settings: forbidden")
        print("Computer use: supervised observation and evidence only")
        print(
            "Bounded specialists: "
            f"{len(payload['agentic']['specialists'])}; human decision gate required"
        )
        return 0

    if args.command == "v1-system-check":
        result = run_v1_synthetic_system_check()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("Accounting Agent v1 synthetic system check")
            for check, passed in result["checks"].items():
                print(f"- {check}: {'pass' if passed else 'fail'}")
            print(f"Autonomy terminal: {result['autonomy_terminal']}")
            print(f"Close terminal: {result['close_terminal']}")
            print("External calls / hosted model calls / ERP writes: 0 / 0 / 0")
        return 0 if result["passed"] else 1

    if args.command == "closeproof-demo":
        try:
            case = build_closeproof_demo(fixture_dir=args.fixture, output_dir=args.output)
        except (OSError, ValueError) as exc:
            print(f"BalanceDocket demo failed: {exc}", file=sys.stderr)
            return 1
        calculation = case["finding"]["calculation"]
        print("BalanceDocket synthetic golden case built")
        print(f"Output: {args.output}")
        print(f"Outcome: {case['outcome']}")
        print(f"Snapshot SHA-256: {case['snapshot_sha256']}")
        print(f"June expense: {calculation['current_period_expense_label']}")
        print(f"Prepaid asset: {calculation['prepaid_asset_label']}")
        print("External calls / hosted model calls / ERP writes: 0 / 0 / 0")
        return 0

    if args.command == "closeproof-advisory":
        advisory_command = args.advisory_command
        if advisory_command is None:
            print(
                "BalanceDocket advisory requires a command: status, prepare, import, codex, or api",
                file=sys.stderr,
            )
            return 2
        case: dict[str, object] | None = None
        try:
            case = _load_bounded_json(args.case, maximum_bytes=1_000_000)
            if advisory_command == "status":
                advisory = case.get("advisory")
                validate_advisory_envelope(case, advisory)
                print(json.dumps(advisory, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
            if advisory_command == "prepare":
                if _paths_alias(args.case, args.output):
                    raise AdvisoryError(
                        "advisory request output must differ from the case input",
                        code="invalid_output",
                    )
                request = prepare_advisory(case)
                _atomic_write_private_json(args.output, request)
                advisory = prepared_advisory_envelope(case)
                write_live_advisory(args.case, advisory)
                print("BalanceDocket provider-neutral advisory request prepared")
                print(f"Output: {args.output}")
                print(f"Evidence snapshot SHA-256: {case['snapshot_sha256']}")
                return 0
            if advisory_command == "import":
                payload = _load_bounded_json(args.input, maximum_bytes=100_000)
                advisory = import_advisory(
                    case,
                    payload,
                    reported_model=args.reported_model,
                    run_id=args.run_id,
                    response_id=args.response_id,
                )
            elif advisory_command == "codex":
                advisory = invoke_codex_subscription_advisory(
                    case,
                    allow_subscription_advisory=args.confirm_use_codex_allowance,
                    timeout=args.timeout,
                )
            elif advisory_command == "api":
                if not args.enable_network_advisory:
                    print(
                        "BalanceDocket advisory blocked: pass --enable-network-advisory for the bundled synthetic case",
                        file=sys.stderr,
                    )
                    return 2
                advisory = invoke_gpt56_advisory(
                    case, api_key=os.environ.get("OPENAI_API_KEY", "")
                )
            else:
                raise AdvisoryError("unsupported advisory command", code="unsupported_command")
            write_live_advisory(args.case, advisory)
        except AdvisoryError as exc:
            if case is not None and advisory_command in {"codex", "api"}:
                provider = (
                    PROVIDER_CODEX_SUBSCRIPTION
                    if advisory_command == "codex"
                    else PROVIDER_OPENAI_API
                )
                transport = (
                    "codex_cli_chatgpt" if advisory_command == "codex" else "responses_api"
                )
                try:
                    write_live_advisory(
                        args.case,
                        failed_advisory_envelope(
                            case,
                            provider=provider,
                            transport=transport,
                            requested_model=(
                                CODEX_MODEL_ID
                                if advisory_command == "codex"
                                else MODEL_ID
                            ),
                            safe_error_code=exc.code,
                        ),
                    )
                except (OSError, AdvisoryError):
                    pass
            print(f"BalanceDocket advisory failed: {exc.code}", file=sys.stderr)
            return 1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            print("BalanceDocket advisory failed: invalid_or_unreadable_file", file=sys.stderr)
            return 1
        print("BalanceDocket GPT-5.6 advisory validated")
        print(f"Provider: {advisory['provider']}")
        print(f"Provider payload SHA-256: {advisory['provenance']['payload_sha256']}")
        print(
            "Controlled display SHA-256: "
            f"{advisory['provenance']['controlled_display_sha256']}"
        )
        print("Authority: advisory only; no approval, posting, lock, or ERP write")
        return 0

    if args.command == "closeproof-serve":
        try:
            serve_closeproof(
                case_path=args.case,
                web_root=args.web,
                events_path=args.events,
                host=args.host,
                port=args.port,
                socket_fd=args.socket_fd,
            )
        except (OSError, ValueError, CloseProofServerError) as exc:
            print(f"BalanceDocket server failed: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
