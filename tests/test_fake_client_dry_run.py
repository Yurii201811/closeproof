from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakeClientDryRunTests(unittest.TestCase):
    def test_one_command_runs_fake_client_month_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "fake_client_dry_run"
            report_path = Path(temp_dir) / "fake_client_report.md"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "fake-client-dry-run",
                    "--output",
                    str(output_dir),
                    "--report",
                    str(report_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Fake-client accounting MVP dry run complete", result.stdout)
            self.assertTrue(report_path.exists())
            manifest = _read_json(output_dir / "manifest.json")
            summary = _read_json(output_dir / "summary.json")
            coverage = _read_json(output_dir / "sample_data" / "coverage.json")

            self.assertEqual("complete", manifest["run"]["status"])
            self.assertTrue(manifest["safety"]["fake_data_only"])
            self.assertFalse(manifest["safety"]["real_client_data_used"])
            self.assertEqual(0, manifest["safety"]["live_fortnox_calls"])
            self.assertEqual(0, manifest["safety"]["live_microsoft365_calls"])
            self.assertEqual(0, manifest["safety"]["emails_sent"])
            self.assertEqual(0, manifest["safety"]["payments_or_filings"])
            self.assertEqual(15, coverage["supplier_invoice_or_receipt_count"])
            self.assertEqual(5, coverage["customer_invoice_count"])
            self.assertEqual(20, coverage["bank_transaction_count"])
            self.assertEqual(3, coverage["ambiguous_edge_cases"])
            self.assertEqual(2, coverage["duplicate_risk_cases"])
            self.assertEqual(1, coverage["changed_bank_details_cases"])
            self.assertEqual(1, coverage["uncertain_vat_cases"])
            self.assertEqual(1, coverage["old_locked_period_cases"])

            self.assertEqual(
                15,
                manifest["supplier_invoice_autopilot"]["summary"]["approval_packets"],
            )
            self.assertEqual(20, manifest["bank_reconciliation"]["proposal_count"])
            self.assertGreater(
                summary["primary_case_decision_counts"]["draft_only"],
                0,
            )
            self.assertGreater(
                summary["primary_case_decision_counts"]["approval_required"],
                0,
            )
            self.assertGreater(
                summary["primary_case_decision_counts"]["escalation_required"],
                0,
            )
            self.assertGreater(summary["primary_case_decision_counts"]["forbidden"], 0)
            self.assertGreater(
                summary["observed_policy_decision_counts"]["auto_allowed"],
                0,
            )
            self.assertEqual(0, summary["unsafe_miss_count"])
            self.assertEqual(0, summary["unclear_output_count"])
            self.assertEqual(0, summary["policy_alignment_warning_count"])
            self.assertIn(
                "python3 -m accounting_agent.cli fake-client-dry-run",
                report_path.read_text(encoding="utf-8"),
            )

    def test_marked_fake_client_output_can_be_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "fake_client_dry_run"
            report_path = Path(temp_dir) / "fake_client_report.md"
            command = [
                sys.executable,
                "-m",
                "accounting_agent.cli",
                "fake-client-dry-run",
                "--output",
                str(output_dir),
                "--report",
                str(report_path),
            ]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)

            stale_sample = output_dir / "sample_data" / "stale.json"
            stale_packet = (
                output_dir
                / "supplier_invoice_autopilot"
                / "approval_packets"
                / "json"
                / "stale.json"
            )
            stale_sample.write_text("stale", encoding="utf-8")
            stale_packet.write_text("stale", encoding="utf-8")
            (output_dir / "manifest.json").write_text("stale", encoding="utf-8")
            report_path.write_text("stale", encoding="utf-8")

            result = subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Fake-client accounting MVP dry run complete", result.stdout)
            self.assertFalse(stale_sample.exists())
            self.assertFalse(stale_packet.exists())
            manifest = _read_json(output_dir / "manifest.json")
            self.assertEqual("complete", manifest["run"]["status"])
            self.assertEqual(
                15,
                manifest["supplier_invoice_autopilot"]["summary"]["approval_packets"],
            )
            self.assertIn(
                "python3 -m accounting_agent.cli fake-client-dry-run",
                report_path.read_text(encoding="utf-8"),
            )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
