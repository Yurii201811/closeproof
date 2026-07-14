from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

import accounting_agent
from accounting_agent.cli import main
from accounting_agent.v1 import build_v1_platform_summary, run_v1_synthetic_system_check


class V1IntegrationTests(unittest.TestCase):
    def test_release_version_is_v1(self) -> None:
        self.assertEqual(accounting_agent.__version__, "1.0.0")

    def test_platform_summary_is_explicit_about_supported_and_declared_capabilities(self) -> None:
        summary = build_v1_platform_summary()

        self.assertEqual(summary["release"], "1.0.0")
        self.assertEqual(summary["market_focus"], "Sweden-first, international foundation")
        self.assertEqual(summary["autonomy"]["terminal_state"], "awaiting_human_decision")
        self.assertEqual(summary["external_writes"], "forbidden")
        connector_states = {
            item["provider_id"]: item["lifecycle"] for item in summary["connectors"]
        }
        self.assertEqual(connector_states["fortnox"], "guarded_read_only")
        self.assertEqual(connector_states["netsuite"], "declaration_only")
        self.assertEqual(connector_states["oracle_fusion"], "declaration_only")
        self.assertEqual(connector_states["sap_s4hana"], "declaration_only")
        hosted = {
            item["provider_id"]: item["enabled_by_default"]
            for item in summary["model_providers"]
        }
        self.assertFalse(hosted["openai"])
        self.assertFalse(hosted["anthropic"])
        self.assertFalse(hosted["gemini"])

    def test_synthetic_system_check_exercises_every_v1_control_plane(self) -> None:
        result = run_v1_synthetic_system_check()

        self.assertEqual(result["release"], "1.0.0")
        self.assertTrue(result["passed"])
        self.assertIn("proposal_entity_binding", result["checks"])
        self.assertIn("connector_read_gateway", result["checks"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["autonomy_terminal"], "awaiting_human_decision")
        self.assertEqual(result["close_terminal"], "ready_for_human_lock")
        self.assertEqual(result["external_calls"], 0)
        self.assertEqual(result["hosted_model_calls"], 0)
        self.assertEqual(result["erp_writes"], 0)

    def test_v1_system_check_cli_emits_machine_readable_result(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["v1-system-check", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["external_calls"], 0)


if __name__ == "__main__":
    unittest.main()
