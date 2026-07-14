from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from accounting_agent.cli import main as cli_main
from accounting_agent.closeproof.advisory import (
    CODEX_MODEL_ID,
    CONTROLLED_DISPLAY_CONCLUSION,
    CONTROLLED_DISPLAY_RATIONALE,
    CONTROLLED_MISSING_EVIDENCE,
    MODEL_ID,
    PROVIDER_CODEX_SUBSCRIPTION,
    PROVIDER_MANUAL_IMPORT,
    PROVIDER_OPENAI_API,
    AdvisoryError,
    build_advisory_request,
    completed_advisory_envelope,
    import_advisory,
    invoke_codex_subscription_advisory,
    invoke_gpt56_advisory,
    prepare_advisory,
    validate_advisory_envelope,
    validate_advisory_response,
    write_live_advisory,
)
from accounting_agent.closeproof.case import (
    DEFAULT_CLOSEPROOF_FIXTURE,
    build_closeproof_demo,
)
from accounting_agent.closeproof.decisions import (
    CloseProofDecisionStore,
    DecisionError,
)
from accounting_agent.closeproof.pdf import (
    SyntheticPdfError,
    build_text_pdf,
    extract_fixture_pdf_lines,
)
from accounting_agent.closeproof.server import CloseProofService


class CloseProofTests(unittest.TestCase):
    def test_text_pdf_round_trips_only_the_synthetic_fixture_shape(self) -> None:
        lines = (
            "SYNTHETIC DEMO DOCUMENT - NOT A REAL INVOICE",
            "Invoice number: INV-4821",
            "Service period: 2026-06-15 to 2027-06-14",
        )
        content = build_text_pdf(lines)

        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertTrue(content.rstrip().endswith(b"%%EOF"))
        self.assertEqual(lines, extract_fixture_pdf_lines(content))
        with self.assertRaises(SyntheticPdfError):
            extract_fixture_pdf_lines(build_text_pdf(("Invoice number: real",)))

    def test_golden_case_is_stable_exact_and_dependency_aware(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            case = build_closeproof_demo(
                fixture_dir=DEFAULT_CLOSEPROOF_FIXTURE,
                output_dir=first,
            )
            repeated = build_closeproof_demo(
                fixture_dir=DEFAULT_CLOSEPROOF_FIXTURE,
                output_dir=second,
            )

            self.assertEqual(case["snapshot_sha256"], repeated["snapshot_sha256"])
            self.assertEqual("review_required", case["outcome"])
            self.assertEqual(
                [
                    "complete",
                    "complete",
                    "complete",
                    "review_required",
                    "waiting",
                    "waiting",
                    "waiting",
                    "waiting",
                    "waiting",
                ],
                [stage["status"] for stage in case["stages"]],
            )
            calculation = case["finding"]["calculation"]
            self.assertEqual(365, calculation["service_days"])
            self.assertEqual(16, calculation["current_period_days"])
            self.assertEqual(526027, calculation["current_period_expense_ore"])
            self.assertEqual(11473973, calculation["prepaid_asset_ore"])
            self.assertEqual(0, json.loads((Path(first) / "manifest.json").read_text())["external_calls"])
            self.assertTrue((Path(first) / "invoice_INV-4821.pdf").is_file())

    def test_advisory_request_is_exact_structured_and_network_off_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        request = build_advisory_request(case)

        self.assertEqual("gpt-5.6", request["model"])
        self.assertFalse(request["store"])
        self.assertEqual("json_schema", request["text"]["format"]["type"])
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertNotIn("OPENAI_API_KEY", json.dumps(request))
        self.assertNotIn("Authorization", json.dumps(request))
        self.assertEqual(
            [526027],
            request["text"]["format"]["schema"]["properties"]["current_period_expense_ore"]["enum"],
        )
        self.assertNotIn('"const"', json.dumps(request["text"]["format"]["schema"]))

    def test_live_advisory_accepts_only_cited_non_authoritative_exact_amounts(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        advisory = self._valid_advisory(case)
        envelope = self._response_envelope(advisory)

        result = validate_advisory_response(case, envelope)

        self.assertEqual("completed", result["status"])
        self.assertEqual(PROVIDER_OPENAI_API, result["provider"])
        self.assertTrue(result["output"]["cannot_approve"])
        self.assertEqual("resp_closeproof_test", result["provenance"]["response_id"])
        self.assertEqual("api_response", result["provenance"]["model_attestation"])
        self.assertEqual(64, len(result["provenance"]["payload_sha256"]))
        self.assertEqual(64, len(result["provenance"]["controlled_display_sha256"]))

        changed_amount = {**advisory, "prepaid_asset_ore": advisory["prepaid_asset_ore"] + 1}
        with self.assertRaisesRegex(AdvisoryError, "changed the deterministic prepaid"):
            validate_advisory_response(case, self._response_envelope(changed_amount))
        unknown_citation = {**advisory, "citation_ids": ["UNKNOWN", "CTRL-ALLOC-v1"]}
        with self.assertRaisesRegex(AdvisoryError, "citations"):
            validate_advisory_response(case, self._response_envelope(unknown_citation))
        claimed_authority = {**advisory, "cannot_approve": False}
        with self.assertRaisesRegex(AdvisoryError, "approval authority"):
            validate_advisory_response(case, self._response_envelope(claimed_authority))
        textual_authority = {
            **advisory,
            "conclusion": "I approve this treatment and have posted it to the ERP ledger.",
            "rationale": "I exercised approval authority and locked the close after reviewing the cited evidence.",
        }
        normalized = validate_advisory_response(case, self._response_envelope(textual_authority))
        self.assertEqual(CONTROLLED_DISPLAY_CONCLUSION, normalized["output"]["conclusion"])
        self.assertEqual(CONTROLLED_DISPLAY_RATIONALE, normalized["output"]["rationale"])
        self.assertNotIn("ERP", json.dumps(normalized["output"]))
        opposite = {
            **advisory,
            "conclusion": "Do not recognize the proposed treatment because the evidence is insufficient.",
            "rationale": "The available source excerpts do not resolve the policy question, so the accounting treatment remains uncertain for human review.",
        }
        opposite_result = validate_advisory_response(case, self._response_envelope(opposite))
        self.assertEqual(CONTROLLED_DISPLAY_CONCLUSION, opposite_result["output"]["conclusion"])
        self.assertNotIn("supports recognizing", opposite_result["output"]["conclusion"].lower())
        self.assertNotEqual(
            result["provenance"]["payload_sha256"],
            opposite_result["provenance"]["payload_sha256"],
        )
        self.assertEqual(
            result["provenance"]["controlled_display_sha256"],
            opposite_result["provenance"]["controlled_display_sha256"],
        )
        high_uncertainty_result = validate_advisory_response(
            case,
            self._response_envelope(
                {**opposite, "uncertainty": "high", "missing_evidence": ["Policy support"]}
            ),
        )
        self.assertEqual(CONTROLLED_DISPLAY_CONCLUSION, high_uncertainty_result["output"]["conclusion"])
        self.assertEqual("high", high_uncertainty_result["output"]["uncertainty"])
        for authority_claim in (
            "I authorized the journal entry after reviewing the cited evidence and policy.",
            "The journal entry was booked and the close was finalized after review.",
            "We released payment after checking the cited evidence and exact amounts.",
            "Approved. Proceed with posting this treatment to the ERP.",
            "This has been approved and may now be posted to the ledger.",
            "Approval granted; proceed with the proposed journal entry now.",
            "I hereby grant approval after reviewing the cited evidence.",
            "The reviewer has approved this treatment.",
            "Go ahead and post the proposed journal entry.",
            "Approval is hereby granted.",
            "I cannot assess tax, but I approve this treatment.",
            "The reviewer gave approval for this treatment.",
            "You are cleared to post the journal entry.",
            "Approval confirmed after reviewing the evidence.",
            "The decision is final and binding.",
            "We signed off on the proposed treatment.",
            "I cannot assess tax and I approve this treatment.",
            "Without further evidence I approve this treatment for posting.",
            "I cannot assess tax although I approve this treatment.",
            "I endorse this treatment.",
            "I accept this treatment as the final accounting decision.",
            "The treatment has my sign-off.",
            "I gave the treatment the green light.",
            "I emailed Finance the proposed journal entry outside CloseProof.",
            "I notified Finance of the proposed journal entry outside CloseProof.",
            "I transmitted the proposed journal entry outside CloseProof.",
            "I certify this treatment.",
            "I consent to the proposed treatment.",
            "The treatment has my signoff.",
            "I gave the treatment the go-ahead.",
            "I shared a message with Finance outside CloseProof.",
            "I uploaded the journal entry in the ERP.",
            "I wrote the journal entry in the ERP.",
            "I saved the journal entry in the ERP.",
            "The journal entry was recorded in Fortnox and the treatment was sanctioned.",
            "The return was lodged with Skatteverket.",
            "The workpaper was delivered to the controller outside the review interface.",
            "The journal entry was imported into Fortnox.",
            "The tax return was mailed to Skatteverket.",
            "The workpaper was transferred to the controller.",
            "The journal entry was synchronized into the accounting system.",
            "Fortnox now contains the journal entry.",
            "The journal entry went live in Fortnox.",
            "The controller got the workpaper.",
            "The treatment was adopted by the reviewer.",
            "The workpaper was mailed after completion.",
            "The journal entry went live.",
        ):
            with self.subTest(authority_claim=authority_claim):
                normalized = validate_advisory_response(
                    case,
                    self._response_envelope({**advisory, "conclusion": authority_claim}),
                )
                self.assertEqual(
                    CONTROLLED_DISPLAY_CONCLUSION, normalized["output"]["conclusion"]
                )
                self.assertNotIn(authority_claim, json.dumps(normalized["output"]))
        negated_authority = {
            **advisory,
            "conclusion": (
                "I cannot approve or post this treatment. No approval was granted; "
                "the reviewer has not approved it and a human decision remains required."
            ),
        }
        self.assertEqual(
            "completed",
            validate_advisory_response(case, self._response_envelope(negated_authority))["status"],
        )
        for safe_authority_reference in (
            "Approval has not been granted; a human decision remains required.",
            "Reviewer approval is pending.",
            "Only the human reviewer can approve this treatment.",
            "Approval cannot be granted by this advisory.",
            "This advisory is not authorized to approve this treatment.",
            "Please don't post or approve this treatment.",
            "Communication has not occurred outside CloseProof.",
            "The model cannot email or notify anyone.",
            "The advisory neither emailed nor notified Finance.",
            "The general ledger contains one expense-side match and requires human review.",
            "Finance review remains required before any action may occur.",
            "The journal entry was not recorded in Fortnox.",
            "No journal entry was recorded in Fortnox.",
            "The general ledger posting date requires human review.",
            "Payment evidence is missing.",
            "The journal entry remains unrecorded in Fortnox.",
            "The journal entry is reconciled in Fortnox and requires human review.",
            "Neither journal entry was recorded in Fortnox.",
            "The proposed posting recommendation requires human review.",
            "The payment classification requires human review.",
            "Booking the annual invoice as prepaid is recommended for human review.",
        ):
            with self.subTest(safe_authority_reference=safe_authority_reference):
                self.assertEqual(
                    "completed",
                    validate_advisory_response(
                        case,
                        self._response_envelope(
                            {**advisory, "conclusion": safe_authority_reference}
                        ),
                    )["status"],
                )
        normalized_missing = validate_advisory_response(
            case,
            self._response_envelope(
                {
                    **advisory,
                    "missing_evidence": ["I approved and posted the entry in the ERP."],
                }
            )
        )
        self.assertEqual(
            [CONTROLLED_MISSING_EVIDENCE], normalized_missing["output"]["missing_evidence"]
        )
        self.assertNotIn("ERP", json.dumps(normalized_missing["output"]))
        non_authority_completion = {
            **advisory,
            "conclusion": "The evidence analysis has been completed; human approval remains required.",
        }
        self.assertEqual(
            "completed",
            validate_advisory_response(
                case, self._response_envelope(non_authority_completion)
            )["status"],
        )
        rerouted = self._response_envelope(advisory)
        rerouted["model"] = "gpt-5.6-terra"
        with self.assertRaisesRegex(AdvisoryError, "does not match"):
            validate_advisory_response(case, rerouted)
        arbitrary_suffix = self._response_envelope(advisory)
        arbitrary_suffix["model"] = "gpt-5.6-sol-not-a-date"
        with self.assertRaisesRegex(AdvisoryError, "does not match"):
            validate_advisory_response(case, arbitrary_suffix)

    def test_network_adapter_sends_the_bounded_request_and_never_returns_raw_key(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        advisory = self._valid_advisory(case)
        response_bytes = json.dumps(self._response_envelope(advisory)).encode("utf-8")
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return response_bytes

        def opener(request, *, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse()

        result = invoke_gpt56_advisory(
            case,
            api_key="synthetic-test-key",
            timeout=3.0,
            opener=opener,
        )

        self.assertEqual("https://api.openai.com/v1/responses", captured["url"])
        self.assertEqual("gpt-5.6", captured["body"]["model"])
        self.assertFalse(captured["body"]["store"])
        self.assertEqual(3.0, captured["timeout"])
        self.assertNotIn("synthetic-test-key", json.dumps(result))

    def test_prepare_and_manual_import_share_schema_validation_and_refresh_context(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            initial_context = case["review_context_sha256"]

            prepared = prepare_advisory(case)
            self.assertEqual("closeproof-advisory-request-v1", prepared["schema_version"])
            self.assertEqual(MODEL_ID, prepared["requested_model"])
            self.assertEqual(case["snapshot_sha256"], prepared["evidence_snapshot_sha256"])
            self.assertFalse(prepared["output_schema"]["additionalProperties"])

            imported = import_advisory(
                case,
                {
                    "schema_version": "closeproof-advisory-import-v1",
                    "output": self._valid_advisory(case),
                    "provenance": {
                        "reported_model": "gpt-5.6-2026-07-13",
                        "run_id": "manual-run-1",
                    },
                },
            )
            self.assertEqual(PROVIDER_MANUAL_IMPORT, imported["provider"])
            self.assertEqual("completed", imported["status"])
            self.assertEqual("user_declared", imported["provenance"]["model_attestation"])
            self.assertTrue(imported["provenance"]["schema_validated"])
            self.assertIsNone(imported["safe_error_code"])

            persisted = write_live_advisory(case_path, imported)
            self.assertNotEqual(initial_context, persisted["review_context_sha256"])
            self.assertEqual(imported, persisted["advisory"])

            with self.assertRaisesRegex(AdvisoryError, "does not match"):
                import_advisory(case, self._valid_advisory(case), reported_model="other-model")

    def test_advisory_envelope_rejects_incoherent_provider_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        envelope = import_advisory(case, self._valid_advisory(case))
        validate_advisory_envelope(case, envelope)

        tampered = json.loads(json.dumps(envelope))
        tampered["provenance"]["transport"] = "responses_api"
        tampered["provenance"]["model_attestation"] = "api_response"
        with self.assertRaisesRegex(AdvisoryError, "transport"):
            validate_advisory_envelope(case, tampered)

        unnormalized = json.loads(json.dumps(envelope))
        unnormalized["output"]["conclusion"] = "The journal entry went live."
        unnormalized["provenance"]["payload_sha256"] = hashlib.sha256(
            json.dumps(
                unnormalized["output"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(AdvisoryError, "not normalized"):
            validate_advisory_envelope(case, unnormalized)

        unsafe_identifier = json.loads(json.dumps(envelope))
        unsafe_identifier["provenance"]["run_id"] = "I approved and posted the journal entry"
        with self.assertRaisesRegex(AdvisoryError, "provenance is invalid"):
            validate_advisory_envelope(case, unsafe_identifier)
        with self.assertRaisesRegex(AdvisoryError, "provenance is invalid"):
            import_advisory(
                case,
                {
                    "schema_version": "closeproof-advisory-import-v1",
                    "output": self._valid_advisory(case),
                    "provenance": {
                        "run_id": "I approved and posted the journal entry",
                    },
                },
            )

        codex = completed_advisory_envelope(
            case,
            self._valid_advisory(case),
            provider=PROVIDER_CODEX_SUBSCRIPTION,
            transport="codex_cli_chatgpt",
            requested_model=CODEX_MODEL_ID,
            reported_model=None,
            model_attestation="codex_requested",
            run_id="thread-closeproof-test",
            response_id=None,
        )
        codex["provenance"]["run_id"] = None
        with self.assertRaisesRegex(AdvisoryError, "provenance is incomplete"):
            validate_advisory_envelope(case, codex)

    def test_nested_cli_prepare_import_and_status_use_safe_default_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            request_path = Path(output) / "request.json"
            import_path = Path(output) / "import.json"
            stdout = StringIO()
            stderr = StringIO()

            with redirect_stderr(stderr):
                result = cli_main(["closeproof-advisory"])
            self.assertEqual(2, result)
            self.assertIn("requires a command", stderr.getvalue())
            stderr = StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli_main(
                    [
                        "closeproof-advisory",
                        "prepare",
                        "--case",
                        str(case_path),
                        "--output",
                        str(request_path),
                    ]
                )
            self.assertEqual(0, result)
            self.assertEqual("", stderr.getvalue())
            prepared_case = json.loads(case_path.read_text(encoding="utf-8"))
            self.assertEqual("running", prepared_case["advisory"]["status"])
            self.assertEqual(PROVIDER_MANUAL_IMPORT, prepared_case["advisory"]["provider"])
            self.assertTrue(request_path.is_file())
            self.assertEqual(0o600, request_path.stat().st_mode & 0o777)

            import_path.write_text(
                json.dumps(self._valid_advisory(case)), encoding="utf-8"
            )
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli_main(
                    [
                        "closeproof-advisory",
                        "import",
                        "--case",
                        str(case_path),
                        "--input",
                        str(import_path),
                    ]
                )
            self.assertEqual(0, result)
            imported_case = json.loads(case_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", imported_case["advisory"]["status"])
            self.assertEqual("unverified", imported_case["advisory"]["provenance"]["model_attestation"])
            status_stdout = StringIO()
            with redirect_stdout(status_stdout):
                result = cli_main(
                    ["closeproof-advisory", "status", "--case", str(case_path)]
                )
            self.assertEqual(0, result)
            self.assertEqual(imported_case["advisory"], json.loads(status_stdout.getvalue()))

            tampered_status_case = json.loads(case_path.read_text(encoding="utf-8"))
            tampered_status_case["advisory"]["provenance"]["transport"] = "responses_api"
            tampered_status_path = Path(output) / "tampered-status-case.json"
            tampered_status_path.write_text(
                json.dumps(tampered_status_case), encoding="utf-8"
            )
            tampered_status_stderr = StringIO()
            with redirect_stderr(tampered_status_stderr):
                result = cli_main(
                    [
                        "closeproof-advisory",
                        "status",
                        "--case",
                        str(tampered_status_path),
                    ]
                )
            self.assertEqual(1, result)
            self.assertIn("invalid_envelope", tampered_status_stderr.getvalue())

            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli_main(
                        ["closeproof-advisory", "--case", str(case_path), "status"]
                    )
            self.assertEqual(2, caught.exception.code)

            oversized = Path(output) / "oversized-case.json"
            oversized.write_bytes(b"{" + b" " * 1_000_000 + b"}")
            bounded_stderr = StringIO()
            with redirect_stderr(bounded_stderr):
                result = cli_main(
                    ["closeproof-advisory", "status", "--case", str(oversized)]
                )
            self.assertEqual(1, result)
            self.assertIn("invalid_or_unreadable_file", bounded_stderr.getvalue())

    def test_advisory_prepare_rejects_case_output_alias_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            original_case = case_path.read_bytes()
            stderr = StringIO()

            with redirect_stderr(stderr):
                result = cli_main(
                    [
                        "closeproof-advisory",
                        "prepare",
                        "--case",
                        str(case_path),
                        "--output",
                        str(case_path),
                    ]
                )

            self.assertEqual(1, result)
            self.assertIn("invalid_output", stderr.getvalue())
            self.assertEqual(original_case, case_path.read_bytes())

    def test_codex_subscription_adapter_is_isolated_exact_and_provenance_bound(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        advisory = self._valid_advisory(case)
        calls = []

        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs))
            self.assertIsInstance(argv, list)
            self.assertNotIn("shell", kwargs)
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            self.assertEqual(0o700, os.stat(kwargs["cwd"]).st_mode & 0o777)
            if argv[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT\n", "")
            output_path = Path(argv[argv.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(advisory), encoding="utf-8")
            events = "\n".join(
                json.dumps(event)
                for event in (
                    {"type": "thread.started", "thread_id": "thread-closeproof-1"},
                    {"type": "turn.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "error",
                            "message": (
                                "Skill descriptions were shortened to fit the 2% skills context "
                                "budget. Codex can still see every skill, but some descriptions "
                                "are shorter. Disable unused skills or plugins to leave more room "
                                "for the rest."
                            ),
                        },
                    },
                    {"type": "item.completed", "item": {"type": "reasoning"}},
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": json.dumps(advisory)},
                    },
                    {"type": "turn.completed", "model": CODEX_MODEL_ID},
                )
            )
            return subprocess.CompletedProcess(argv, 0, events, "")

        result = invoke_codex_subscription_advisory(
            case,
            allow_subscription_advisory=True,
            timeout=9,
            runner=runner,
            environ={
                "PATH": "/synthetic/bin",
                "HOME": "/synthetic/home",
                "CODEX_HOME": "/synthetic/codex-home",
                "OPENAI_API_KEY": "must-not-pass",
                "UNRELATED_PRIVATE_VALUE": "must-not-pass",
            },
        )

        self.assertEqual(2, len(calls))
        argv, invocation = calls[1]
        self.assertEqual(["codex", "exec"], argv[:2])
        self.assertEqual(CODEX_MODEL_ID, argv[argv.index("--model") + 1])
        self.assertEqual("read-only", argv[argv.index("--sandbox") + 1])
        self.assertIn('approval_policy="never"', argv)
        for flag in (
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "--output-schema",
            "--output-last-message",
            "--json",
        ):
            self.assertIn(flag, argv)
        disabled = {argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--disable"}
        self.assertTrue(
            {
                "apps",
                "browser_use",
                "computer_use",
                "hooks",
                "image_generation",
                "multi_agent",
                "plugins",
                "shell_tool",
                "standalone_web_search",
                "unified_exec",
            }.issubset(disabled)
        )
        self.assertNotIn(case["case_id"], " ".join(argv))
        self.assertIn('web_search="disabled"', argv)
        self.assertIn('shell_environment_policy.inherit="none"', argv)
        self.assertIn(case["case_id"], invocation["input"])
        self.assertEqual(9.0, invocation["timeout"])
        self.assertEqual("completed", result["status"])
        self.assertEqual(PROVIDER_CODEX_SUBSCRIPTION, result["provider"])
        self.assertEqual("codex_cli_chatgpt", result["provenance"]["transport"])
        self.assertEqual(CODEX_MODEL_ID, result["provenance"]["requested_model"])
        self.assertEqual("thread-closeproof-1", result["provenance"]["run_id"])
        self.assertEqual("codex_requested", result["provenance"]["model_attestation"])

    def test_codex_subscription_requires_allowance_and_chatgpt_not_api_key_login(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        calls = []

        def should_not_run(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("runner should not be called")

        with self.assertRaisesRegex(AdvisoryError, "explicit allowance") as caught:
            invoke_codex_subscription_advisory(case, runner=should_not_run)
        self.assertEqual("codex_allowance_required", caught.exception.code)
        self.assertEqual([], calls)

        def api_key_login(argv, **_kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "Logged in using an API key\n", "")

        with self.assertRaisesRegex(AdvisoryError, "refuses API-key login") as caught:
            invoke_codex_subscription_advisory(
                case,
                allow_subscription_advisory=True,
                runner=api_key_login,
                environ={"PATH": "/synthetic/bin", "HOME": "/synthetic/home"},
            )
        self.assertEqual("codex_api_key_login_blocked", caught.exception.code)
        self.assertEqual(1, len(calls))

    def test_codex_subscription_rejects_bad_events_tools_models_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
        advisory = self._valid_advisory(case)

        invalid_streams = (
            ("codex_invalid_events", "not-json", 0),
            ("codex_failed", "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "t1"}),
                    json.dumps({"type": "error", "message": "private provider failure"}),
                )
            ), 1),
            ("codex_failed", "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "t1"}),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "error", "message": "Model rerouted"},
                        }
                    ),
                    json.dumps({"type": "turn.completed"}),
                )
            ), 0),
            ("codex_tool_attempted", "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "t1"}),
                    json.dumps(
                        {"type": "item.completed", "item": {"type": "command_execution"}}
                    ),
                    json.dumps({"type": "turn.completed"}),
                )
            ), 0),
            ("model_mismatch", "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "t1"}),
                    json.dumps({"type": "turn.completed", "model": "gpt-5.6-terra"}),
                )
            ), 0),
        )
        for expected_code, stream, return_code in invalid_streams:
            with self.subTest(expected_code=expected_code):
                run_count = 0

                def runner(argv, **_kwargs):
                    nonlocal run_count
                    run_count += 1
                    if argv[1:3] == ["login", "status"]:
                        return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
                    output_path = Path(argv[argv.index("--output-last-message") + 1])
                    output_path.write_text(json.dumps(advisory), encoding="utf-8")
                    return subprocess.CompletedProcess(
                        argv,
                        return_code,
                        stream,
                        "private stderr",
                    )

                with self.assertRaises(AdvisoryError) as caught:
                    invoke_codex_subscription_advisory(
                        case,
                        allow_subscription_advisory=True,
                        runner=runner,
                        environ={"PATH": "/synthetic/bin", "HOME": "/synthetic/home"},
                    )
                self.assertEqual(expected_code, caught.exception.code)
                self.assertNotIn("private stderr", str(caught.exception))
                self.assertEqual(2, run_count, "the adapter must never auto-retry")

        def missing_output(argv, **_kwargs):
            if argv[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
            stream = "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "t1"}),
                    json.dumps({"type": "turn.completed"}),
                )
            )
            return subprocess.CompletedProcess(argv, 0, stream, "")

        with self.assertRaises(AdvisoryError) as caught:
            invoke_codex_subscription_advisory(
                case,
                allow_subscription_advisory=True,
                runner=missing_output,
                environ={"PATH": "/synthetic/bin", "HOME": "/synthetic/home"},
            )
        self.assertEqual("codex_output_missing", caught.exception.code)

    def test_codex_subscription_enforces_timeout_and_stream_size_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)

        calls = 0

        def times_out(argv, **_kwargs):
            nonlocal calls
            calls += 1
            if argv[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
            raise subprocess.TimeoutExpired(argv, 3)

        with self.assertRaises(AdvisoryError) as caught:
            invoke_codex_subscription_advisory(
                case,
                allow_subscription_advisory=True,
                timeout=3,
                runner=times_out,
                environ={"PATH": "/synthetic/bin", "HOME": "/synthetic/home"},
            )
        self.assertEqual("codex_timeout", caught.exception.code)
        self.assertEqual(2, calls)

        calls = 0

        def oversized_events(argv, **_kwargs):
            nonlocal calls
            calls += 1
            if argv[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
            return subprocess.CompletedProcess(argv, 0, "x" * 1_000_001, "")

        with self.assertRaises(AdvisoryError) as caught:
            invoke_codex_subscription_advisory(
                case,
                allow_subscription_advisory=True,
                runner=oversized_events,
                environ={"PATH": "/synthetic/bin", "HOME": "/synthetic/home"},
            )
        self.assertEqual("codex_events_too_large", caught.exception.code)
        self.assertEqual(2, calls)

    def test_decision_requires_current_snapshot_rationale_and_preserves_event_chain(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            events = Path(output) / "decision-events.jsonl"
            store = CloseProofDecisionStore(case, events)

            with self.assertRaisesRegex(DecisionError, "12 to 1000"):
                store.record(
                    action="approve_treatment",
                    rationale="too short",
                    snapshot_sha256=case["snapshot_sha256"],
                    review_context_sha256=case["review_context_sha256"],
                    finding_id=case["finding_id"],
                )
            with self.assertRaisesRegex(DecisionError, "snapshot changed"):
                store.record(
                    action="approve_treatment",
                    rationale="The exact daily allocation agrees with the cited evidence.",
                    snapshot_sha256="0" * 64,
                    review_context_sha256=case["review_context_sha256"],
                    finding_id=case["finding_id"],
                )

            decision = store.record(
                action="approve_treatment",
                rationale="The exact daily allocation agrees with the cited evidence and policy.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )
            workpaper = store.workpaper()

            self.assertTrue(decision["event_chain_valid"])
            self.assertFalse(decision["accounting_action_performed"])
            self.assertFalse(decision["erp_write_performed"])
            self.assertEqual("approve_treatment", workpaper["human_decision"]["action"])
            self.assertTrue(workpaper["event_chain"]["valid"])
            self.assertEqual(
                "current_decision",
                workpaper["event_chain"]["semantic_validation_scope"],
            )
            self.assertEqual(
                decision["event_sha256"],
                workpaper["event_chain"]["semantically_validated_event_sha256"],
            )
            self.assertEqual([], workpaper["external_actions_performed"])

    def test_service_rehydrates_latest_decision_without_mutating_the_case(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            events = Path(output) / "decision-events.jsonl"
            service = CloseProofService(case_path=case_path, events_path=events)
            decision = service.record_decision(
                {
                    "action": "request_evidence",
                    "rationale": "Confirm that the synthetic accrual policy applies to this contract.",
                    "snapshot_sha256": case["snapshot_sha256"],
                    "review_context_sha256": case["review_context_sha256"],
                    "finding_id": case["finding_id"],
                }
            )

            self.assertEqual("request_evidence", decision["action"])
            self.assertEqual(decision["event_sha256"], service.case_payload()["decision"]["event_sha256"])
            self.assertIsNone(json.loads(case_path.read_text())["decision"])

    @staticmethod
    def _valid_advisory(case):
        calculation = case["finding"]["calculation"]
        return {
            "conclusion": "Recognize the exact June service received as expense and retain the balance as prepaid, subject to reviewer approval.",
            "rationale": "The invoice and policy citations show service beyond June, while the deterministic control fixes the amount and remains authoritative for arithmetic.",
            "citation_ids": ["INV-4821:p1:L8", "POLICY-ACCRUAL-01:L6-L10", "CTRL-ALLOC-v1"],
            "uncertainty": "low",
            "missing_evidence": ["Reviewer confirmation that the synthetic policy applies"],
            "current_period_expense_ore": calculation["current_period_expense_ore"],
            "prepaid_asset_ore": calculation["prepaid_asset_ore"],
            "cannot_approve": True,
        }

    @staticmethod
    def _response_envelope(advisory):
        return {
            "id": "resp_closeproof_test",
            "status": "completed",
            "model": "gpt-5.6-2026-07-13",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(advisory),
                        }
                    ],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
