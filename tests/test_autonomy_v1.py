from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from accounting_agent.autonomy import (
    AUTONOMY_LADDER,
    AutonomyPlan,
    AutonomyRunState,
    AutonomyStage,
    CheckpointedAutonomyRunner,
    ProcessorResult,
    SQLiteAutonomyStore,
    StageState,
    trusted_preparation_processor,
)


NOW = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def trusted_processors(processor):
    trusted = trusted_preparation_processor(processor, environment="preview")
    return {stage: trusted for stage in AUTONOMY_LADDER}


class AutonomyV1Tests(unittest.TestCase):
    def test_plan_is_synthetic_preparation_only(self) -> None:
        plan = self._plan()
        self.assertEqual(plan.stages, AUTONOMY_LADDER)
        self.assertEqual(
            tuple(stage.value for stage in plan.stages),
            (
                "collect",
                "extract",
                "validate",
                "match",
                "request_missing_evidence",
                "draft",
                "explain",
                "assemble_review_packet",
            ),
        )
        self.assertFalse(
            {"approve", "post", "pay", "file", "send", "delete"}.intersection(
                plan.permission_ceiling
            )
        )
        with self.assertRaises(ValueError):
            AutonomyPlan(
                plan_id="unsafe-plan",
                client_id="client-a",
                entity_id="entity-a",
                case_id="case-a",
                environment="production",
                data_classification="confidential_accounting",
                evidence_hashes=(sha("evidence"),),
            )
        with self.assertRaises(ValueError):
            trusted_preparation_processor(
                lambda context: ProcessorResult("unsafe", {"ok": False}),
                environment="production",
            )

    def test_plan_stores_canonical_nfc_client_id(self) -> None:
        plan = AutonomyPlan(
            plan_id="unicode-client-plan",
            client_id="client-e\u0301",
            entity_id="entity-a",
            case_id="case-a",
            environment="preview",
            data_classification="synthetic",
            evidence_hashes=(sha("unicode-evidence"),),
        )

        self.assertEqual(plan.client_id, "client-é")
        self.assertEqual(plan.to_dict()["client_id"], "client-é")

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            run_id = store.create(plan, created_at=NOW)
            self.assertEqual(store.load_plan(run_id).client_id, "client-é")

    def test_runner_checkpoints_and_finishes_at_human_decision(self) -> None:
        calls: list[AutonomyStage] = []

        def processor(context):
            calls.append(context.stage)
            return ProcessorResult(
                summary=f"{context.stage.value} complete",
                output={"stage": context.stage.value, "synthetic": True},
            )

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(self._plan())
            report = runner.run(run_id=run_id, client_id="client-a")

            self.assertEqual(report.state, AutonomyRunState.AWAITING_HUMAN_DECISION)
            self.assertEqual(calls, list(AUTONOMY_LADDER))
            self.assertTrue(all(item.state is StageState.COMPLETED for item in report.stages))
            self.assertTrue(all(item.output_hash for item in report.stages))
            self.assertEqual(report.next_stage, None)

            repeated = runner.run(run_id=run_id, client_id="client-a")
            self.assertEqual(repeated, report)
            self.assertEqual(calls, list(AUTONOMY_LADDER))

    def test_crash_resume_does_not_repeat_completed_stages(self) -> None:
        calls: Counter[AutonomyStage] = Counter()

        def processor(context):
            calls[context.stage] += 1
            if context.stage is AutonomyStage.VALIDATE and calls[context.stage] == 1:
                raise RuntimeError("synthetic worker interruption")
            return ProcessorResult(
                summary="checkpointed",
                output={"stage": context.stage.value},
            )

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(self._plan())
            failed = runner.run(run_id=run_id, client_id="client-a")
            self.assertEqual(failed.state, AutonomyRunState.INTERRUPTED)
            self.assertEqual(failed.next_stage, AutonomyStage.VALIDATE)
            self.assertEqual(calls[AutonomyStage.COLLECT], 1)
            self.assertEqual(calls[AutonomyStage.EXTRACT], 1)

            completed = runner.run(run_id=run_id, client_id="client-a")
            self.assertEqual(completed.state, AutonomyRunState.AWAITING_HUMAN_DECISION)
            self.assertEqual(calls[AutonomyStage.COLLECT], 1)
            self.assertEqual(calls[AutonomyStage.EXTRACT], 1)
            self.assertEqual(calls[AutonomyStage.VALIDATE], 2)

    def test_review_or_blocked_result_stops_downstream_work(self) -> None:
        calls: list[AutonomyStage] = []

        def processor(context):
            calls.append(context.stage)
            if context.stage is AutonomyStage.VALIDATE:
                return ProcessorResult(
                    summary="VAT evidence conflicts",
                    output={"issue": "uncertain_vat"},
                    requires_review=True,
                )
            return ProcessorResult(summary="complete", output={"ok": True})

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(self._plan())
            report = runner.run(run_id=run_id, client_id="client-a")
            self.assertEqual(report.state, AutonomyRunState.REVIEW_REQUIRED)
            self.assertEqual(report.next_stage, AutonomyStage.VALIDATE)
            self.assertEqual(
                calls,
                [AutonomyStage.COLLECT, AutonomyStage.EXTRACT, AutonomyStage.VALIDATE],
            )
            self.assertEqual(report.stages[-1].state, StageState.REVIEW_REQUIRED)

    def test_cancel_propagates_and_client_scope_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(
                    lambda context: ProcessorResult("ok", {"ok": True})
                ),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(self._plan())
            runner.cancel(run_id=run_id, client_id="client-a", reason="Operator stop")
            report = runner.run(run_id=run_id, client_id="client-a")
            self.assertEqual(report.state, AutonomyRunState.CANCELLED)
            self.assertTrue(all(stage.state is StageState.CANCELLED for stage in report.stages))
            with self.assertRaises(PermissionError):
                runner.run(run_id=run_id, client_id="client-b")

    def test_cancel_wins_against_an_in_flight_stage(self) -> None:
        processor_started = threading.Event()
        release_processor = threading.Event()
        calls: list[AutonomyStage] = []
        reports = []

        def processor(context):
            calls.append(context.stage)
            processor_started.set()
            self.assertTrue(release_processor.wait(timeout=2))
            return ProcessorResult(
                summary="late result that must not overwrite cancellation",
                output={"stage": context.stage.value},
            )

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(self._plan())
            worker = threading.Thread(
                target=lambda: reports.append(
                    runner.run(run_id=run_id, client_id="client-a")
                )
            )
            worker.start()
            self.assertTrue(processor_started.wait(timeout=2))

            runner.cancel(
                run_id=run_id,
                client_id="client-a",
                reason="Operator cancelled while collect was running",
            )
            release_processor.set()
            worker.join(timeout=2)

            self.assertFalse(worker.is_alive())
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0].state, AutonomyRunState.CANCELLED)
            self.assertEqual(calls, [AutonomyStage.COLLECT])
            self.assertTrue(
                all(stage.state is StageState.CANCELLED for stage in reports[0].stages)
            )

    def test_two_concurrent_runners_share_one_execution_and_final_report(self) -> None:
        first_stage_started = threading.Event()
        release_first_stage = threading.Event()
        contender_denied = threading.Event()
        calls: Counter[AutonomyStage] = Counter()
        reports = []
        errors = []

        class ObservedStore(SQLiteAutonomyStore):
            def acquire_execution_lease(self, *args, **kwargs):
                acquired = super().acquire_execution_lease(*args, **kwargs)
                if not acquired:
                    contender_denied.set()
                return acquired

        def processor(context):
            calls[context.stage] += 1
            if context.stage is AutonomyStage.COLLECT:
                first_stage_started.set()
                self.assertTrue(release_first_stage.wait(timeout=2))
            return ProcessorResult(
                summary=f"{context.stage.value} complete",
                output={"stage": context.stage.value},
            )

        def invoke(runner, run_id):
            try:
                reports.append(runner.run(run_id=run_id, client_id="client-a"))
            except Exception as exc:  # pragma: no cover - assertion reports details
                errors.append(exc)

        with tempfile.TemporaryDirectory() as directory:
            store = ObservedStore(Path(directory) / "runs.sqlite")
            runner_a = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            runner_b = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            run_id = runner_a.create_run(self._plan())
            worker_a = threading.Thread(target=invoke, args=(runner_a, run_id))
            worker_b = threading.Thread(target=invoke, args=(runner_b, run_id))

            worker_a.start()
            self.assertTrue(first_stage_started.wait(timeout=2))
            worker_b.start()
            self.assertTrue(contender_denied.wait(timeout=2))
            release_first_stage.set()
            worker_a.join(timeout=2)
            worker_b.join(timeout=2)

            self.assertFalse(worker_a.is_alive())
            self.assertFalse(worker_b.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(reports), 2)
            self.assertEqual(reports[0], reports[1])
            self.assertEqual(
                reports[0].state, AutonomyRunState.AWAITING_HUMAN_DECISION
            )
            self.assertEqual(calls, Counter({stage: 1 for stage in AUTONOMY_LADDER}))

    def test_expired_execution_lease_is_recovered(self) -> None:
        calls: Counter[AutonomyStage] = Counter()

        def processor(context):
            calls[context.stage] += 1
            return ProcessorResult(
                summary=f"{context.stage.value} recovered",
                output={"stage": context.stage.value},
            )

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW + timedelta(seconds=41),
            )
            run_id = store.create(self._plan(), created_at=NOW)
            self.assertTrue(
                store.acquire_execution_lease(
                    run_id,
                    lease_token="dead-worker",
                    updated_at=NOW,
                    expires_at=NOW + timedelta(seconds=30),
                )
            )
            self.assertTrue(
                store.heartbeat_execution_lease(
                    run_id,
                    lease_token="dead-worker",
                    updated_at=NOW + timedelta(seconds=10),
                    expires_at=NOW + timedelta(seconds=40),
                )
            )
            self.assertFalse(
                store.acquire_execution_lease(
                    run_id,
                    lease_token="too-early-contender",
                    updated_at=NOW + timedelta(seconds=31),
                    expires_at=NOW + timedelta(seconds=61),
                )
            )

            report = runner.run(run_id=run_id, client_id="client-a")

            self.assertEqual(report.state, AutonomyRunState.AWAITING_HUMAN_DECISION)
            self.assertEqual(calls, Counter({stage: 1 for stage in AUTONOMY_LADDER}))
            self.assertFalse(
                store.execution_lease_is_owned(run_id, "dead-worker", now=report.updated_at)
            )

    def test_raw_malicious_processor_is_rejected_without_being_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "processor-side-effect.txt"

            def malicious_processor(context):
                marker.write_text("must never be written", encoding="utf-8")
                return ProcessorResult(summary="pretended success", output={"ok": True})

            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            with self.assertRaisesRegex(TypeError, "external OS sandbox"):
                CheckpointedAutonomyRunner(
                    store,
                    processors={
                        stage: malicious_processor for stage in AUTONOMY_LADDER
                    },
                    clock=lambda: NOW,
                )

            self.assertFalse(marker.exists())

    def test_trusted_processor_context_denies_non_preparation_capabilities(self) -> None:
        def processor(context):
            context.capabilities.require("erp_write")
            return ProcessorResult(summary="unreachable", output={"ok": True})

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runs.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=trusted_processors(processor),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(self._plan())
            report = runner.run(run_id=run_id, client_id="client-a")

            self.assertEqual(report.state, AutonomyRunState.INTERRUPTED)
            self.assertEqual(report.next_stage, AutonomyStage.COLLECT)
            self.assertIn("ProcessorCapabilityDenied", report.stages[-1].error or "")

    def test_processor_outputs_are_json_and_hash_bound(self) -> None:
        with self.assertRaises(TypeError):
            ProcessorResult(summary="bad", output={"not_json": object()})

    @staticmethod
    def _plan() -> AutonomyPlan:
        return AutonomyPlan(
            plan_id="autonomy-plan-1",
            client_id="client-a",
            entity_id="entity-a",
            case_id="case-a",
            environment="preview",
            data_classification="synthetic",
            evidence_hashes=(sha("evidence-1"), sha("evidence-2")),
        )


if __name__ == "__main__":
    unittest.main()
