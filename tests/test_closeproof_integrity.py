from __future__ import annotations

import copy
import json
import stat
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from accounting_agent.closeproof.advisory import (
    AdvisoryError,
    import_advisory,
    prepare_advisory,
    write_live_advisory,
)
from accounting_agent.closeproof.case import build_closeproof_demo
from accounting_agent.closeproof.decisions import CloseProofDecisionStore, DecisionError
from accounting_agent.closeproof.integrity import (
    compute_case_snapshot_sha256,
    refresh_review_context,
)
from accounting_agent.closeproof.server import (
    CloseProofRequestPolicy,
    CloseProofService,
    CloseProofServerError,
)
from accounting_agent.evidence import HashChainedEventLog


class CloseProofReviewIntegrityTests(unittest.TestCase):
    def test_modified_case_cannot_be_decided_or_sent_as_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            tampered = copy.deepcopy(case)
            tampered["finding"]["calculation"]["current_period_expense_ore"] = 1
            refresh_review_context(tampered)
            with self.assertRaisesRegex(DecisionError, "snapshot"):
                CloseProofDecisionStore(
                    tampered,
                    Path(output) / "decision-events.jsonl",
                )

            relabelled = copy.deepcopy(case)
            relabelled["finding"]["citations"][0]["text"] = "REAL CLIENT SECRET"
            relabelled["snapshot_sha256"] = compute_case_snapshot_sha256(relabelled)
            refresh_review_context(relabelled)
            with self.assertRaises(AdvisoryError) as caught:
                prepare_advisory(relabelled)
            self.assertEqual("synthetic_case_not_approved", caught.exception.code)

    def test_local_only_case_is_truthful_and_exportable_after_human_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            store = CloseProofDecisionStore(
                case,
                Path(output) / "decision-events.jsonl",
            )

            self.assertEqual("not_requested", case["advisory"]["status"])
            self.assertEqual("none", case["advisory"]["provider"])
            self.assertIsNone(case["advisory"]["output"])
            self.assertEqual(
                "Synthetic demo · Local controls · No ERP writes · Advisory optional",
                case["safety"]["strip"],
            )

            decision = store.record(
                action="approve_treatment",
                rationale="The exact local controls and cited evidence support this treatment.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )
            workpaper = store.workpaper()

            self.assertFalse(decision["stale"])
            self.assertEqual("not_requested", workpaper["advisory"]["status"])
            self.assertEqual(
                case["review_context_sha256"],
                workpaper["review_context_sha256"],
            )

    def test_advisory_change_makes_an_existing_decision_stale(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            store = CloseProofDecisionStore(
                case,
                Path(output) / "decision-events.jsonl",
            )
            store.record(
                action="request_evidence",
                rationale="Confirm that the synthetic policy applies before final review.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )
            prior_review_context = case["review_context_sha256"]

            case["advisory"] = {
                "status": "completed",
                "provider": "codex_session",
                "output": {
                    "conclusion": "Use the deterministic allocation, subject to human review.",
                    "rationale": "The cited service period extends beyond June and the control owns arithmetic.",
                    "citation_ids": [
                        "INV-4821:p1:L8",
                        "POLICY-ACCRUAL-01:L6-L10",
                    ],
                    "uncertainty": "low",
                    "missing_evidence": [],
                    "current_period_expense_ore": 526027,
                    "prepaid_asset_ore": 11473973,
                    "cannot_approve": True,
                },
                "provenance": {
                    "transport": "codex_skill",
                    "requested_model": "gpt-5.6",
                    "reported_model": None,
                    "model_attestation": "codex_requested",
                    "run_id": "local-test-run",
                    "response_id": None,
                    "schema_validated": True,
                    "payload_sha256": "a" * 64,
                    "controlled_display_sha256": "b" * 64,
                    "evidence_snapshot_sha256": case["snapshot_sha256"],
                },
                "safe_error_code": None,
            }
            refresh_review_context(case)

            self.assertNotEqual(prior_review_context, case["review_context_sha256"])
            self.assertTrue(store.latest()["stale"])
            with self.assertRaisesRegex(DecisionError, "stale"):
                store.workpaper()

    def test_current_context_accepts_only_one_human_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            store = CloseProofDecisionStore(
                case,
                Path(output) / "decision-events.jsonl",
            )
            first = store.record(
                action="approve_treatment",
                rationale="The exact controls and cited evidence support this treatment.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )

            with self.assertRaisesRegex(DecisionError, "already exists"):
                store.record(
                    action="reject",
                    rationale="A second disposition must not replace the current human decision.",
                    snapshot_sha256=case["snapshot_sha256"],
                    review_context_sha256=case["review_context_sha256"],
                    finding_id=case["finding_id"],
                )

            self.assertEqual(1, store.log.verify().event_count)
            self.assertEqual(first["event_sha256"], store.latest()["event_sha256"])

    def test_concurrent_stores_atomically_accept_only_one_current_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            events = Path(output) / "decision-events.jsonl"
            barrier = threading.Barrier(2)

            class RacingStore(CloseProofDecisionStore):
                def latest(self) -> dict[str, object] | None:
                    result = super().latest()
                    if result is None:
                        barrier.wait(timeout=5)
                    return result

            stores = [RacingStore(case, events), RacingStore(case, events)]

            def decide(store: CloseProofDecisionStore, action: str) -> object:
                try:
                    return store.record(
                        action=action,
                        rationale=f"The exact evidence supports this {action} review decision.",
                        snapshot_sha256=case["snapshot_sha256"],
                        review_context_sha256=case["review_context_sha256"],
                        finding_id=case["finding_id"],
                    )
                except DecisionError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(decide, stores[0], "approve_treatment"),
                    executor.submit(decide, stores[1], "reject"),
                ]
                results = [future.result(timeout=10) for future in futures]

            self.assertEqual(1, sum(isinstance(result, dict) for result in results))
            errors = [result for result in results if isinstance(result, DecisionError)]
            self.assertEqual(1, len(errors))
            self.assertIn("already exists", str(errors[0]))
            self.assertEqual(1, stores[0].log.verify().event_count)

    def test_decision_artifacts_are_private_to_the_local_account(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            events = Path(output) / "decision-events.jsonl"
            workpaper = Path(output) / "workpaper.json"
            store = CloseProofDecisionStore(case, events)
            store.record(
                action="request_evidence",
                rationale="The exact evidence still requires one synthetic supporting total.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )
            store.write_workpaper(workpaper)

            for path in (
                events,
                events.with_suffix(events.suffix + ".head.json"),
                events.with_suffix(events.suffix + ".lock"),
                workpaper,
            ):
                with self.subTest(path=path.name):
                    self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_workpaper_rejects_hash_valid_but_semantically_unbound_event(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            events = Path(output) / "decision-events.jsonl"
            HashChainedEventLog(events).append(
                client_id="different-client",
                event_type="closeproof_reject",
                actor_id="not-the-controller",
                object_id="different-finding",
                details={
                    "action": "approve_treatment",
                    "rationale_chunks": [
                        "This valid-chain event is deliberately bound to the wrong proof."
                    ],
                    "snapshot_sha256": "0" * 64,
                    "review_context_sha256": case["review_context_sha256"],
                    "advisory_payload_sha256": None,
                    "controlled_display_sha256": None,
                    "accounting_action_performed": True,
                    "erp_write_performed": True,
                },
            )
            store = CloseProofDecisionStore(case, events)

            self.assertTrue(store.log.verify().valid)
            with self.assertRaisesRegex(DecisionError, "persisted decision"):
                store.workpaper()

    def test_workpaper_scopes_semantic_validation_to_the_current_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            events = Path(output) / "decision-events.jsonl"
            HashChainedEventLog(events).append(
                client_id=case["entity"]["id"],
                event_type="closeproof_request_evidence",
                actor_id="demo-controller",
                object_id=case["finding_id"],
                details={
                    "action": "request_evidence",
                    "rationale_chunks": [
                        "This fabricated stale context must not gain a broad semantic claim."
                    ],
                    "snapshot_sha256": case["snapshot_sha256"],
                    "review_context_sha256": "0" * 64,
                    "advisory_payload_sha256": "1" * 64,
                    "controlled_display_sha256": "2" * 64,
                    "accounting_action_performed": False,
                    "erp_write_performed": False,
                },
            )
            store = CloseProofDecisionStore(case, events)
            current = store.record(
                action="approve_treatment",
                rationale="The exact local controls and cited evidence support this treatment.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )

            workpaper = store.workpaper()

            self.assertEqual(2, workpaper["event_chain"]["event_count"])
            self.assertTrue(workpaper["event_chain"]["valid"])
            self.assertEqual(
                "current_decision",
                workpaper["event_chain"]["semantic_validation_scope"],
            )
            self.assertEqual(
                current["event_sha256"],
                workpaper["event_chain"]["semantically_validated_event_sha256"],
            )
            self.assertEqual(
                current["event_sequence"],
                workpaper["event_chain"]["semantically_validated_event_sequence"],
            )

    def test_service_fails_closed_for_malformed_decision_event_state(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            build_closeproof_demo(output_dir=output)
            events = Path(output) / "decision-events.jsonl"
            events.write_text("{not-json}\n", encoding="utf-8")
            service = CloseProofService(
                case_path=Path(output) / "case.json",
                events_path=events,
            )

            with self.assertRaisesRegex(CloseProofServerError, "decision state"):
                service.case_payload()

    def test_failed_workpaper_validation_preserves_previous_export(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            events = Path(output) / "decision-events.jsonl"
            workpaper = Path(output) / "workpaper.json"
            store = CloseProofDecisionStore(case, events)
            store.record(
                action="approve_treatment",
                rationale="The exact controls and cited evidence support this treatment.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )
            store.write_workpaper(workpaper)
            previous_export = workpaper.read_bytes()

            envelope = import_advisory(
                case,
                {
                    "conclusion": "Use the deterministic allocation, subject to human review.",
                    "rationale": "The cited invoice and policy support the exact local allocation while retaining human authority.",
                    "citation_ids": [
                        "INV-4821:p1:L8",
                        "POLICY-ACCRUAL-01:L6-L10",
                    ],
                    "uncertainty": "low",
                    "missing_evidence": [],
                    "current_period_expense_ore": 526027,
                    "prepaid_asset_ore": 11473973,
                    "cannot_approve": True,
                },
            )
            updated = write_live_advisory(case_path, envelope)
            stale_store = CloseProofDecisionStore(updated, events)

            with self.assertRaisesRegex(DecisionError, "stale"):
                stale_store.write_workpaper(workpaper)

            self.assertEqual(previous_export, workpaper.read_bytes())

    def test_long_rationale_round_trips_without_silent_truncation(self) -> None:
        for length in (241, 1000):
            with self.subTest(length=length), tempfile.TemporaryDirectory() as output:
                case = build_closeproof_demo(output_dir=output)
                store = CloseProofDecisionStore(
                    case,
                    Path(output) / "decision-events.jsonl",
                )
                rationale = "R" * length

                recorded = store.record(
                    action="request_evidence",
                    rationale=rationale,
                    snapshot_sha256=case["snapshot_sha256"],
                    review_context_sha256=case["review_context_sha256"],
                    finding_id=case["finding_id"],
                )

                self.assertEqual(rationale, recorded["rationale"])
                self.assertEqual(rationale, store.latest()["rationale"])
                self.assertEqual(rationale, store.workpaper()["human_decision"]["rationale"])

    def test_fresh_demo_resets_event_body_and_head_for_the_next_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            events = Path(output) / "decision-events.jsonl"
            case = build_closeproof_demo(output_dir=output)
            store = CloseProofDecisionStore(case, events)
            store.record(
                action="approve_treatment",
                rationale="The exact controls and cited evidence support this treatment.",
                snapshot_sha256=case["snapshot_sha256"],
                review_context_sha256=case["review_context_sha256"],
                finding_id=case["finding_id"],
            )
            head = events.with_suffix(events.suffix + ".head.json")
            self.assertTrue(events.exists())
            self.assertTrue(head.exists())

            fresh = build_closeproof_demo(output_dir=output)
            self.assertFalse(events.exists())
            self.assertFalse(head.exists())
            next_store = CloseProofDecisionStore(fresh, events)
            decision = next_store.record(
                action="request_evidence",
                rationale="Confirm the synthetic policy scope before final human review.",
                snapshot_sha256=fresh["snapshot_sha256"],
                review_context_sha256=fresh["review_context_sha256"],
                finding_id=fresh["finding_id"],
            )
            self.assertEqual(1, decision["event_sequence"])

    def test_service_rejects_unknown_or_unbound_decision_fields(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            service = CloseProofService(
                case_path=Path(output) / "case.json",
                events_path=Path(output) / "decision-events.jsonl",
            )
            base = {
                "action": "approve_treatment",
                "rationale": "The exact controls and cited evidence support this treatment.",
                "snapshot_sha256": case["snapshot_sha256"],
                "review_context_sha256": case["review_context_sha256"],
                "finding_id": case["finding_id"],
            }

            with self.assertRaisesRegex(DecisionError, "unknown fields"):
                service.record_decision({**base, "prompt": "do something else"})
            with self.assertRaisesRegex(DecisionError, "missing required"):
                service.record_decision(
                    {key: value for key, value in base.items() if key != "review_context_sha256"}
                )

            recorded = service.record_decision_and_case(base)
            self.assertEqual(recorded["decision"], recorded["case"]["decision"])
            self.assertFalse(recorded["case"]["decision"]["stale"])

    def test_service_reloads_external_advisory_before_read_or_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            service = CloseProofService(
                case_path=case_path,
                events_path=Path(output) / "decision-events.jsonl",
            )
            old_context = case["review_context_sha256"]
            envelope = import_advisory(
                case,
                {
                    "conclusion": "Use the deterministic allocation, subject to human review.",
                    "rationale": "The cited invoice and policy show service beyond June while controls retain authority for the exact allocation.",
                    "citation_ids": [
                        "INV-4821:p1:L8",
                        "POLICY-ACCRUAL-01:L6-L10",
                    ],
                    "uncertainty": "low",
                    "missing_evidence": [],
                    "current_period_expense_ore": 526027,
                    "prepaid_asset_ore": 11473973,
                    "cannot_approve": True,
                },
            )
            updated = write_live_advisory(case_path, envelope)

            refreshed = service.case_payload()

            self.assertEqual("completed", refreshed["advisory"]["status"])
            self.assertEqual(updated["review_context_sha256"], refreshed["review_context_sha256"])
            self.assertNotEqual(old_context, refreshed["review_context_sha256"])
            with self.assertRaisesRegex(DecisionError, "review context changed"):
                service.record_decision(
                    {
                        "action": "approve_treatment",
                        "rationale": "The old context supported this treatment before the advisory changed.",
                        "snapshot_sha256": case["snapshot_sha256"],
                        "review_context_sha256": old_context,
                        "finding_id": case["finding_id"],
                    }
                )
    def test_manual_import_refreshes_context_and_stales_prior_decision(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            service = CloseProofService(
                case_path=case_path,
                events_path=Path(output) / "decision-events.jsonl",
            )
            service.record_decision(
                {
                    "action": "approve_treatment",
                    "rationale": "The exact controls and cited evidence support this treatment.",
                    "snapshot_sha256": case["snapshot_sha256"],
                    "review_context_sha256": case["review_context_sha256"],
                    "finding_id": case["finding_id"],
                }
            )
            previous_context = case["review_context_sha256"]

            updated = service.import_manual_advisory(
                {
                    "payload": {
                        "conclusion": "Use the deterministic allocation, subject to human review.",
                        "rationale": "The cited annual service period crosses the close date and agrees with the exact local control calculation.",
                        "citation_ids": [
                            "INV-4821:p1:L8",
                            "POLICY-ACCRUAL-01:L6-L10",
                        ],
                        "uncertainty": "low",
                        "missing_evidence": [],
                        "current_period_expense_ore": 526027,
                        "prepaid_asset_ore": 11473973,
                        "cannot_approve": True,
                    }
                }
            )

            self.assertEqual("chatgpt_manual", updated["advisory"]["provider"])
            self.assertEqual("unverified", updated["advisory"]["provenance"]["model_attestation"])
            self.assertNotEqual(previous_context, updated["review_context_sha256"])
            self.assertTrue(updated["decision"]["stale"])
            self.assertEqual(
                updated["review_context_sha256"],
                json.loads(case_path.read_text(encoding="utf-8"))["review_context_sha256"],
            )
            with self.assertRaisesRegex(DecisionError, "stale"):
                service.decisions.workpaper()

    def test_service_rejects_tampered_advisory_even_with_refreshed_context(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case = build_closeproof_demo(output_dir=output)
            case_path = Path(output) / "case.json"
            service = CloseProofService(
                case_path=case_path,
                events_path=Path(output) / "decision-events.jsonl",
            )
            updated = service.import_manual_advisory(
                {
                    "payload": {
                        "conclusion": "Use the deterministic allocation, subject to human review.",
                        "rationale": "The cited annual service period crosses the close date and agrees with the exact local control calculation.",
                        "citation_ids": [
                            "INV-4821:p1:L8",
                            "POLICY-ACCRUAL-01:L6-L10",
                        ],
                        "uncertainty": "low",
                        "missing_evidence": [],
                        "current_period_expense_ore": 526027,
                        "prepaid_asset_ore": 11473973,
                        "cannot_approve": True,
                    }
                }
            )
            tampered = {key: value for key, value in updated.items() if key != "decision"}
            tampered["advisory"]["output"]["conclusion"] = "Tampered but long enough to pass superficial validation."
            refresh_review_context(tampered)
            case_path.write_text(json.dumps(tampered), encoding="utf-8")

            with self.assertRaisesRegex(CloseProofServerError, "integrity"):
                CloseProofService(
                    case_path=case_path,
                    events_path=Path(output) / "next-decision-events.jsonl",
                )

    def test_loopback_policy_requires_exact_host_origin_and_capability(self) -> None:
        policy = CloseProofRequestPolicy(
            allowed_host="127.0.0.1:4173",
            allowed_origin="http://127.0.0.1:4173",
            csrf_token="synthetic-capability",
        )
        allowed = {
            "Host": "127.0.0.1:4173",
            "Origin": "http://127.0.0.1:4173",
            "Sec-Fetch-Site": "same-origin",
            "X-CloseProof-CSRF": "synthetic-capability",
        }

        self.assertTrue(policy.host_is_allowed(allowed))
        self.assertTrue(policy.mutation_is_allowed(allowed))
        for key, value in (
            ("Host", "attacker.invalid"),
            ("Origin", "https://attacker.invalid"),
            ("Sec-Fetch-Site", "cross-site"),
            ("X-CloseProof-CSRF", "wrong"),
        ):
            blocked = {**allowed, key: value}
            with self.subTest(header=key):
                self.assertFalse(policy.mutation_is_allowed(blocked))

    def test_server_rejects_oversized_case_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            case_path = Path(output) / "oversized-case.json"
            case_path.write_bytes(b"{" + b" " * 1_000_000 + b"}")

            with self.assertRaisesRegex(CloseProofServerError, "could not be loaded"):
                CloseProofService(
                    case_path=case_path,
                    events_path=Path(output) / "decision-events.jsonl",
                )


if __name__ == "__main__":
    unittest.main()
