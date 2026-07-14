from __future__ import annotations

import json
import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from importlib import resources
from pathlib import Path

from accounting_agent.cli import main as cli_main
from accounting_agent.operations_cockpit import (
    build_operations_cockpit,
    build_public_preview,
    collect_operations_cockpit_data,
    verify_generated_links,
)


class OperationsCockpitTests(unittest.TestCase):
    def test_cli_reports_out_of_root_build_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for command in ("build-operations-cockpit", "build-public-preview"):
                with self.subTest(command=command):
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        result = cli_main(
                            [command, "--output", str(Path(temp_dir) / command)]
                        )

                    self.assertEqual(1, result)
                    self.assertIn("must stay under repo root", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_packaged_tokens_are_available_for_clean_installs(self) -> None:
        packaged = resources.files("accounting_agent").joinpath("static", "tokens.css")
        packaged_icon = resources.files("accounting_agent").joinpath("static", "favicon.svg")
        packaged_icon_license = resources.files("accounting_agent").joinpath(
            "static", "LICENSE.lucide.txt"
        )

        self.assertTrue(packaged.is_file())
        self.assertTrue(packaged_icon.is_file())
        self.assertTrue(packaged_icon_license.is_file())
        self.assertEqual(
            (Path(__file__).resolve().parents[1] / "tokens.css").read_text(encoding="utf-8"),
            packaged.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (Path(__file__).resolve().parents[1] / "favicon.svg").read_text(encoding="utf-8"),
            packaged_icon.read_text(encoding="utf-8"),
        )

    def test_builds_static_cockpit_from_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_cockpit_fixture(root)

            result = build_operations_cockpit(repo_root=root)
            html = result.output_path.read_text(encoding="utf-8")
            data = result.data
            queues = {queue.key: queue.count for queue in data.review_queues}

            self.assertTrue(result.output_path.exists())
            self.assertEqual(0, len(result.broken_links))
            self.assertGreater(result.link_targets_checked, 0)
            self.assertEqual([], verify_generated_links(result.output_path, root))
            self.assertEqual("local_fake_client_dry_run_complete", data.local_readiness)
            self.assertEqual("supplier_invoice_demo_complete", data.demo_readiness)
            self.assertEqual(0, data.live_counters["live_fortnox_calls"])
            self.assertEqual(0, data.live_counters["live_microsoft365_calls"])
            self.assertGreaterEqual(queues["approval_required"], 2)
            self.assertEqual(1, queues["escalation_required"])
            self.assertEqual(1, queues["forbidden"])
            self.assertEqual(1, queues["duplicate_risk"])
            self.assertEqual(1, queues["changed_bank_details"])
            self.assertEqual(1, queues["uncertain_vat"])
            self.assertEqual(1, queues["policy_alignment_warnings"])
            self.assertIn("Accounting Agent v1", html)
            self.assertIn("Observe and review only", html)
            self.assertIn("python3 -m accounting_agent.cli build-operations-cockpit", html)
            self.assertIn("Fortnox dry-run", html)
            self.assertIn("Bank reconciliation", html)
            self.assertIn('data-view="guided"', html)
            self.assertIn('id="command-dialog"', html)
            self.assertIn('id="review-search"', html)
            self.assertIn("NetSuite", html)
            self.assertIn("Oracle Fusion", html)
            self.assertIn("SAP S/4HANA", html)
            self.assertIn("Supervised computer use", html)
            self.assertIn("Bounded specialist-agent pipeline", html)
            self.assertIn("Agents never self-approve", html)
            self.assertIn('id="setup"', html)
            self.assertIn('id="close"', html)
            self.assertIn('id="automation"', html)
            self.assertIn("Evidence completeness", html)
            self.assertIn("Assemble review packet", html)
            self.assertIn("Ollama on this device", html)
            self.assertIn("Anthropic API", html)
            self.assertIn("Google Gemini API", html)
            self.assertIn("The agent prepares. People decide.", html)
            self.assertIn('data-sv="Manifest för testkund"', html)
            self.assertIn('data-sv="full syntetisk månadskörning"', html)
            self.assertIn('data-sv="senaste lokala filen"', html)
            self.assertEqual(5, html.count('class="attention-row"'))
            self.assertNotIn("more items not shown", html)
            self.assertNotIn(str(root), html)
            self.assertNotIn("SECRET_VALUE", html)
            self.assertTrue((root / "tokens.css").exists())
            self.assertTrue((root / "favicon.svg").exists())
            tokens = (root / "tokens.css").read_text(encoding="utf-8")
            self.assertTrue(
                tokens.startswith(
                    "/* Hallmark · genre: modern-minimal · macrostructure: Narrative Workflow · theme: Coral"
                )
            )
            page_css = re.search(r"<style>\s*(.*?)\s*</style>", html, re.DOTALL)
            self.assertIsNotNone(page_css)
            assert page_css is not None
            self.assertTrue(
                page_css.group(1).startswith(
                    "/* Hallmark · genre: modern-minimal · macrostructure: Narrative Workflow"
                )
            )
            self.assertIsNone(re.search(r"#[0-9a-f]{3,8}|(?:rgb|hsl|oklch)\(", page_css.group(1), re.IGNORECASE))
            self.assertNotIn("@media (max-width", page_css.group(1))
            self.assertIn("@media (min-width: 40rem)", page_css.group(1))
            self.assertIn("@media (hover: hover) and (pointer: fine)", page_css.group(1))
            self.assertRegex(
                page_css.group(1),
                r"\.wordmark \{\s*display: inline-flex;\s*min-width: 2\.75rem;\s*min-height: 2\.75rem;",
            )
            self.assertRegex(
                page_css.group(1),
                r"\.section-nav a \{\s*display: inline-flex;\s*flex: 0 0 auto;\s*min-width: 2\.75rem;\s*min-height: 2\.75rem;",
            )
            self.assertRegex(
                page_css.group(1),
                r"\.attention-copy details summary \{[^}]*min-height: 2\.75rem;",
            )
            _assert_offline_local_only(self, html)

    def test_missing_artifacts_build_with_empty_states_and_no_dead_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs").mkdir()
            (root / "docs" / "accounting_agent_architecture.md").write_text(
                "# Architecture\n",
                encoding="utf-8",
            )

            result = build_operations_cockpit(repo_root=root)
            html = result.output_path.read_text(encoding="utf-8")

            self.assertTrue(result.output_path.exists())
            self.assertEqual(0, len(result.broken_links))
            self.assertEqual("not_ready_no_fake_client_run", result.data.local_readiness)
            self.assertEqual("not_ready_no_demo_run", result.data.demo_readiness)
            self.assertIn("No current items found in local artifacts.", html)
            self.assertIn(
                'data-sv="Inga lokala SQLite-köantal har hittats ännu."',
                html,
            )
            self.assertEqual([], verify_generated_links(result.output_path, root))
            self.assertNotIn(str(root), html)
            _assert_offline_local_only(self, html)

    def test_nonzero_live_counter_is_rendered_as_danger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_cockpit_fixture(root)
            manifest_path = root / ".local" / "fake_client_dry_run" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["safety"]["live_fortnox_calls"] = 2
            _write_json(manifest_path, manifest)

            result = build_operations_cockpit(repo_root=root)
            html = result.output_path.read_text(encoding="utf-8")

            self.assertEqual(2, result.data.live_counters["live_fortnox_calls"])
            self.assertRegex(
                html,
                r'<div class="stat" data-tone="danger">\s*<dt[^>]*>Live ERP calls</dt>\s*<dd[^>]*>2</dd>',
            )
            self.assertIn("safety violation, never a success state", html)
            _assert_offline_local_only(self, html)

    def test_collect_uses_read_only_sqlite_counts_without_initializing_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = collect_operations_cockpit_data(repo_root=root)
            self.assertEqual({}, data.queue_counts)
            self.assertFalse((root / ".local" / "accounting_agent.sqlite").exists())

    def test_public_preview_is_self_contained_and_synthetic_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / ".local" / "fake_client_dry_run"
            private.mkdir(parents=True)
            (private / "SECRET_VALUE.json").write_text(
                '{"client": "REAL-CLIENT-NAME"}', encoding="utf-8"
            )

            result = build_public_preview(repo_root=root, output_dir="dist/preview")
            bundle = result.output_path.parent
            markup = result.output_path.read_text(encoding="utf-8")
            manifest = json.loads(
                (bundle / "preview-manifest.json").read_text(encoding="utf-8")
            )

            self.assertEqual((), result.broken_links)
            self.assertEqual([], verify_generated_links(result.output_path, bundle))
            self.assertEqual(
                {
                    "LICENSE.lucide.txt",
                    "favicon.svg",
                    "index.html",
                    "preview-manifest.json",
                    "tokens.css",
                },
                {path.name for path in bundle.iterdir() if path.is_file()},
            )
            self.assertTrue(manifest["synthetic_data_only"])
            self.assertEqual(0, manifest["source_artifact_links"])
            self.assertEqual(
                {
                    "reads_local_workflow_artifacts": False,
                    "network_invocation_available": False,
                    "hosted_model_invocation_available": False,
                    "erp_write_invocation_available": False,
                },
                manifest["build_contract"],
            )
            self.assertIn("SYN-INV-003", markup)
            for marker in (
                str(root),
                "SECRET_VALUE",
                "REAL-CLIENT-NAME",
                ".local/",
                "Downloads/",
                "kursstart",
                "e427o-bokforing2",
                "e428o-bokforing3",
            ):
                self.assertNotIn(marker, markup)
            _assert_offline_local_only(self, markup)

    def test_public_preview_refuses_unexpected_files_in_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "dist" / "preview"
            target.mkdir(parents=True)
            (target / "private-notes.txt").write_text("do not deploy", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unexpected files"):
                build_public_preview(repo_root=root, output_dir="dist/preview")

    def test_public_preview_refuses_allowed_name_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "dist" / "preview"
            target.mkdir(parents=True)
            outside = root / "outside.css"
            outside.write_text("must not be overwritten", encoding="utf-8")
            (target / "tokens.css").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "unexpected files"):
                build_public_preview(repo_root=root, output_dir="dist/preview")
            self.assertEqual("must not be overwritten", outside.read_text(encoding="utf-8"))


def _write_cockpit_fixture(root: Path) -> None:
    fake_root = root / ".local" / "fake_client_dry_run"
    supplier_root = fake_root / "supplier_invoice_autopilot"
    demo_root = root / ".local" / "demo_supplier_invoice_autopilot"
    docs_root = root / "docs"
    for folder in (
        supplier_root / "approval_packets" / "json",
        supplier_root / "approval_packets" / "markdown",
        supplier_root / "fortnox_dry_run_payloads",
        supplier_root / "gnubok_shadow_outputs",
        supplier_root / "extracted_invoice_json",
        supplier_root / "accounting_proposals",
        supplier_root / "policy_decisions",
        supplier_root / "execution_permits",
        supplier_root / "risk_findings",
        fake_root / "bank_reconciliation_packets",
        demo_root,
        docs_root,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    cases = [
        _supplier_case(
            supplier_root,
            case_id="si_approval",
            scenario="duplicate_invoice",
            mode="approval_required",
            duplicate=True,
        ),
        _supplier_case(
            supplier_root,
            case_id="si_escalation",
            scenario="changed_bank_details",
            mode="escalation_required",
            changed_bank_details=True,
        ),
        _supplier_case(
            supplier_root,
            case_id="si_forbidden",
            scenario="uncertain_vat_locked_period",
            mode="forbidden",
            uncertain_vat=True,
        ),
    ]

    _write_json(supplier_root / "normalized_intake_cases.json", [{"case_id": "case_1"}])
    _write_json(supplier_root / "manifest.json", {"summary": {"status": "complete"}})
    _write_json(
        supplier_root / "summary.json",
        {
            "status": "complete",
            "approval_packets": 3,
            "execution_permits_issued": 1,
            "output_dir": str(supplier_root),
        },
    )
    for folder_name in (
        "extracted_invoice_json",
        "accounting_proposals",
        "policy_decisions",
        "execution_permits",
        "fortnox_dry_run_payloads",
        "gnubok_shadow_outputs",
    ):
        _write_json(supplier_root / folder_name / "evidence.json", {"ok": True})
    (fake_root / "audit_log.jsonl").write_text(
        '{"event_type":"fixture"}\n',
        encoding="utf-8",
    )
    _write_json(
        fake_root / "bank_reconciliation_proposals.json",
        [
            {
                "case": {"case_id": "br_missing"},
                "selected_candidate": None,
                "risk": {
                    "flags": [
                        {"code": "unknown_transaction", "severity": "high"}
                    ]
                },
                "policy_decision": {"mode": "approval_required"},
                "required_human_decision": "Classify transaction.",
                "approval_packet_path": str(
                    fake_root / "bank_reconciliation_packets" / "br_missing.bank_reconciliation_packet.json"
                ),
            }
        ],
    )
    _write_json(
        fake_root / "bank_reconciliation_packets" / "br_missing.bank_reconciliation_packet.json",
        {"case": {"case_id": "br_missing"}},
    )
    _write_json(
        fake_root / "manifest.json",
        {
            "run": {
                "status": "complete",
                "generated_at": "2026-05-16T09:00:00+00:00",
            },
            "safety": {
                "fake_data_only": True,
                "real_client_data_used": False,
                "live_fortnox_calls": 0,
                "live_microsoft365_calls": 0,
                "emails_sent": 0,
                "payments_or_filings": 0,
                "final_voucher_postings": 0,
                "internal_note": "SECRET_VALUE",
            },
            "metrics": {
                "audit_events": 1,
                "primary_case_decision_counts": {
                    "approval_required": 2,
                    "escalation_required": 1,
                    "forbidden": 1,
                },
                "policy_alignment_warnings": [
                    {
                        "item_id": "si_alignment",
                        "reason": "pipeline_and_execution_gate_modes_differ",
                    }
                ],
            },
            "supplier_invoice_autopilot": {
                "summary": {
                    "status": "complete",
                    "approval_packets": 3,
                    "output_dir": str(supplier_root),
                },
                "cases": cases,
            },
        },
    )
    _write_json(
        fake_root / "summary.json",
        {
            "status": "complete",
            "sample_counts": {"supplier_invoices_or_receipts": 3},
            "primary_case_decision_counts": {
                "approval_required": 2,
                "escalation_required": 1,
                "forbidden": 1,
            },
        },
    )
    _write_json(
        demo_root / "manifest.json",
        {"summary": {"status": "complete"}},
    )
    _write_json(demo_root / "summary.json", {"status": "complete"})
    for doc_name in (
        "fake_client_dry_run_report.md",
        "accounting_agent_architecture.md",
        "fortnox_adapter.md",
        "gnubok_shadow_ledger.md",
        "bank_reconciliation_autopilot.md",
        "local_demo_supplier_invoice_autopilot.md",
    ):
        (docs_root / doc_name).write_text(f"# {doc_name}\n", encoding="utf-8")


def _supplier_case(
    supplier_root: Path,
    *,
    case_id: str,
    scenario: str,
    mode: str,
    duplicate: bool = False,
    changed_bank_details: bool = False,
    uncertain_vat: bool = False,
) -> dict[str, object]:
    packet_path = supplier_root / "approval_packets" / "json" / f"{case_id}.approval_packet.json"
    packet = {
        "case": {"case_id": case_id, "fixture_name": scenario},
        "supplier_match": {
            "status": "matched",
            "bank_details_status": "changed" if changed_bank_details else "matched",
        },
        "duplicate_check": {
            "status": "possible_duplicate" if duplicate else "unique",
        },
        "vat_proposal": {
            "status": "uncertain" if uncertain_vat else "normal",
        },
        "risk": {
            "flags": [
                {"code": code, "severity": "high"}
                for code in (
                    ["duplicate_risk"] if duplicate else []
                )
                + (["changed_bank_details"] if changed_bank_details else [])
                + (["uncertain_vat"] if uncertain_vat else [])
            ]
        },
        "policy_decision": {
            "mode": mode,
            "openclaw_risk_reasons": [scenario],
        },
        "required_human_decision": f"Review {scenario}.",
    }
    _write_json(packet_path, packet)
    markdown_path = supplier_root / "approval_packets" / "markdown" / f"{case_id}.md"
    markdown_path.write_text(f"# {case_id}\n", encoding="utf-8")
    return {
        "case_id": case_id,
        "scenario": scenario,
        "execution_gate_mode": mode,
        "pipeline_policy_mode": mode,
        "risk_level": "high" if mode != "approval_required" else "medium",
        "permit_status": "not_issued_review_required",
        "fortnox_adapter_payload_status": "prepared_but_review_blocked",
        "gnubok_status": "mirrored",
        "artifacts": {
            "approval_packet_json": f"approval_packets/json/{packet_path.name}",
            "approval_packet_markdown": f"approval_packets/markdown/{markdown_path.name}",
        },
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_offline_local_only(test_case: unittest.TestCase, markup: str) -> None:
    self_closing_links = re.findall(r"<link\b[^>]*>", markup, re.IGNORECASE)
    test_case.assertEqual(2, len(self_closing_links))
    test_case.assertRegex(
        markup,
        re.compile(
            r'<link\s+rel="icon"\s+type="image/svg\+xml"\s+href="(?:\.\./)*favicon\.svg">',
            re.IGNORECASE,
        ),
    )
    test_case.assertRegex(
        markup,
        re.compile(
            r'<link\s+rel="stylesheet"\s+href="(?:\.\./)*tokens\.css">',
            re.IGNORECASE,
        ),
    )
    test_case.assertRegex(
        markup,
        re.compile(r"<script>.*</script>", re.IGNORECASE | re.DOTALL),
    )
    test_case.assertIsNone(
        re.search(
            r"https?://|\bsrc\s*=|href\s*=\s*[\"'](?:https?:|//|data:|javascript:)",
            markup,
            re.IGNORECASE,
        )
    )
    test_case.assertIsNone(
        re.search(
            r"\bfetch\s*\(|XMLHttpRequest|\beval\s*\(|sendBeacon|new\s+WebSocket",
            markup,
            re.IGNORECASE,
        )
    )


if __name__ == "__main__":
    unittest.main()
