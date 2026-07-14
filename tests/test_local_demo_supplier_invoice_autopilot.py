from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LocalSupplierInvoiceDemoTests(unittest.TestCase):
    def test_one_command_writes_complete_local_demo_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "supplier_invoice_demo"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "demo-supplier-invoice-autopilot",
                    "--output",
                    str(output_dir),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn(
                "Supplier Invoice Autopilot local demo complete",
                result.stdout,
            )
            summary = _read_json(output_dir / "summary.json")
            manifest = _read_json(output_dir / "manifest.json")
            normalized_cases = _read_json(output_dir / "normalized_intake_cases.json")
            normal_permit = _read_json(
                output_dir / "execution_permits" / "normal_swedish_25_vat.json"
            )
            normal_fortnox = _read_json(
                output_dir
                / "fortnox_dry_run_payloads"
                / "normal_swedish_25_vat.json"
            )
            uncertain_fortnox = _read_json(
                output_dir
                / "fortnox_dry_run_payloads"
                / "uncertain_vat_extraction.json"
            )

            self.assertEqual("complete", summary["status"])
            self.assertEqual(5, summary["normalized_intake_cases"])
            self.assertEqual(5, summary["approval_packets"])
            self.assertEqual(1, summary["execution_permits_issued"])
            self.assertEqual(0, summary["fortnox_live_api_calls"])
            self.assertEqual(0, summary["microsoft365_live_calls"])
            self.assertEqual(0, summary["email_sends"])
            self.assertEqual(5, len(normalized_cases))
            self.assertEqual(5, len(manifest["cases"]))
            self.assertEqual("fixture_client", manifest["run_context"]["client_id"])
            self.assertIn("entity_id", manifest["run_context"])
            self.assertEqual("fixture_entity", manifest["run_context"]["entity_id"])
            self.assertTrue(manifest["safety"]["uses_sample_fixtures_only"])
            self.assertFalse(manifest["safety"]["live_fortnox_calls"])
            self.assertFalse(manifest["safety"]["live_microsoft365_calls"])
            self.assertFalse(manifest["safety"]["emails_sent"])

            self.assertEqual("issued", normal_permit["status"])
            self.assertEqual(
                "dry_run_draft_not_created",
                normal_fortnox["adapter_dry_run_result"]["status"],
            )
            self.assertFalse(normal_fortnox["live_api_call"])
            self.assertFalse(
                normal_fortnox["adapter_payload"]["SupplierInvoice"]["Booked"]
            )
            self.assertFalse(
                normal_fortnox["adapter_payload"]["SupplierInvoice"]["PaymentPending"]
            )
            self.assertEqual("not_prepared", uncertain_fortnox["adapter_payload_status"])
            self.assertIn("due_date", uncertain_fortnox["adapter_payload_error"])
            self.assertIn("actionable_next_step", uncertain_fortnox)

            self.assertEqual(
                5,
                len(list((output_dir / "approval_packets" / "json").glob("*.json"))),
            )
            self.assertEqual(
                5,
                len(list((output_dir / "approval_packets" / "markdown").glob("*.md"))),
            )
            self.assertEqual(
                5,
                len(list((output_dir / "gnubok_shadow_outputs").glob("*.json"))),
            )
            audit_lines = (output_dir / "audit_log.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(5, len(audit_lines))

    def test_missing_fixture_folder_fails_with_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "demo-supplier-invoice-autopilot",
                    "--fixtures",
                    str(Path(temp_dir) / "missing"),
                    "--output",
                    str(Path(temp_dir) / "output"),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("Demo failed:", result.stderr)
            self.assertIn("fixture folder does not exist", result.stderr)
            self.assertIn("--fixtures", result.stderr)

    def test_demo_refuses_to_clear_unmarked_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "existing"
            existing_file = output_dir / "approval_packets" / "json" / "keep.txt"
            existing_file.parent.mkdir(parents=True)
            existing_file.write_text("do not delete", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "demo-supplier-invoice-autopilot",
                    "--output",
                    str(output_dir),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("Refusing to clear an unmarked output folder", result.stderr)
            self.assertEqual("do not delete", existing_file.read_text(encoding="utf-8"))

    def test_marked_demo_output_can_be_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "supplier_invoice_demo"
            command = [
                sys.executable,
                "-m",
                "accounting_agent.cli",
                "demo-supplier-invoice-autopilot",
                "--output",
                str(output_dir),
            ]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)

            stale_packet = output_dir / "approval_packets" / "json" / "stale.json"
            stale_packet.write_text("stale", encoding="utf-8")
            (output_dir / "summary.json").write_text("stale", encoding="utf-8")

            result = subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Supplier Invoice Autopilot local demo complete", result.stdout)
            self.assertFalse(stale_packet.exists())
            summary = _read_json(output_dir / "summary.json")
            self.assertEqual("complete", summary["status"])
            self.assertEqual(5, summary["approval_packets"])
            self.assertEqual(
                5,
                len(list((output_dir / "approval_packets" / "json").glob("*.json"))),
            )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
