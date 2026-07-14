from __future__ import annotations

import importlib
import importlib.util
import unittest

import accounting_agent.close as close


class PeriodCloseV1Tests(unittest.TestCase):
    def test_all_satisfied_controls_are_ready_for_a_human_lock_decision_only(self) -> None:
        self.assertTrue(hasattr(close, "evaluate_period_close"))
        if not hasattr(close, "evaluate_period_close"):
            return

        snapshot = self._snapshot()
        assessment = close.evaluate_period_close(
            snapshot,
            verification=self._verification(snapshot),
        )

        self.assertEqual(close.CloseOutcome.READY_FOR_HUMAN_LOCK, assessment.outcome)
        self.assertTrue(assessment.ready_for_human_lock)
        self.assertEqual(snapshot.identity, assessment.identity)
        self.assertEqual(snapshot.evidence_bundle_hash, assessment.evidence_bundle_hash)
        self.assertEqual(snapshot.policy_hash, assessment.policy_hash)
        self.assertEqual(
            [close.CloseStageStatus.COMPLETE] * len(close.CLOSE_STAGE_ORDER),
            [stage.status for stage in assessment.stages],
        )
        self.assertEqual((), assessment.stages[0].depends_on)
        for index, stage in enumerate(assessment.stages[1:], start=1):
            self.assertEqual((close.CLOSE_STAGE_ORDER[index - 1],), stage.depends_on)
        self.assertEqual((), assessment.blockers)
        self.assertEqual((), assessment.external_actions_performed)
        self.assertFalse(assessment.lock_performed)

    def test_close_stages_follow_the_required_dependency_order(self) -> None:
        spec = importlib.util.find_spec("accounting_agent.close")
        self.assertIsNotNone(spec)
        if spec is None:  # Keep a missing module as an assertion failure, not an import error.
            return
        from accounting_agent.close import CLOSE_STAGE_ORDER, CloseStage

        self.assertEqual(
            (
                CloseStage.EVIDENCE_COMPLETENESS,
                CloseStage.BANK_RECONCILIATION,
                CloseStage.SUBLEDGERS,
                CloseStage.ADJUSTMENTS,
                CloseStage.BALANCED_TRIAL_BALANCE,
                CloseStage.VAT_CONTROL,
                CloseStage.PREPARER_REVIEW,
                CloseStage.INDEPENDENT_SIGNOFF,
                CloseStage.LOCK_READINESS,
            ),
            CLOSE_STAGE_ORDER,
        )

    def test_close_control_uses_explicit_immutable_facts_and_statuses(self) -> None:
        close = importlib.import_module("accounting_agent.close")
        required_names = {
            "CloseAssessment",
            "CloseBlocker",
            "CloseFact",
            "CloseFactStatus",
            "CloseOutcome",
            "CloseSnapshot",
            "CloseStageAssessment",
            "CloseStageStatus",
            "PeriodCloseIdentity",
            "CloseVerificationContext",
            "compute_close_evidence_bundle_hash",
        }
        missing = sorted(name for name in required_names if not hasattr(close, name))
        self.assertEqual([], missing)
        if missing:
            return

        identity = close.PeriodCloseIdentity("client-a", "entity-1", "2026-06")
        fact = close.CloseFact(
            stage="evidence_completeness",
            status="satisfied",
            evidence_hashes=["a" * 64],
            summary=" Source population reconciled. ",
        )
        snapshot = close.CloseSnapshot(
            identity=identity,
            evidence_bundle_hash="b" * 64,
            policy_hash="c" * 64,
            facts=[fact],
        )

        self.assertEqual("client-a", identity.client_id)
        self.assertEqual("entity-1", identity.entity_id)
        self.assertEqual(close.CloseStage.EVIDENCE_COMPLETENESS, fact.stage)
        self.assertEqual(close.CloseFactStatus.SATISFIED, fact.status)
        self.assertEqual(("a" * 64,), fact.evidence_hashes)
        self.assertEqual("Source population reconciled.", fact.summary)
        self.assertIsInstance(snapshot.facts, tuple)

    def test_identity_requires_client_entity_and_a_real_year_month(self) -> None:
        invalid_identities = (
            ("", "entity-1", "2026-06"),
            ("client-a", " ", "2026-06"),
            (" client-a", "entity-1", "2026-06"),
            ("client-a", "entity-1 ", "2026-06"),
            ("client-a", "entity-1", "2026-6"),
            ("client-a", "entity-1", "2026-00"),
            ("client-a", "entity-1", "2026-13"),
        )

        for client_id, entity_id, period in invalid_identities:
            with self.subTest(client_id=client_id, entity_id=entity_id, period=period):
                with self.assertRaises(ValueError):
                    close.PeriodCloseIdentity(client_id, entity_id, period)

    def test_missing_or_malformed_snapshot_hashes_block_the_close(self) -> None:
        snapshot = self._snapshot(evidence_bundle_hash=None, policy_hash="not-a-sha256")
        assessment = close.evaluate_period_close(
            snapshot,
            verification=self._verification(snapshot),
        )

        self.assertEqual(close.CloseOutcome.BLOCKED, assessment.outcome)
        self.assertFalse(assessment.ready_for_human_lock)
        self.assertEqual(
            {"evidence_bundle_hash_missing", "policy_hash_invalid"},
            {blocker.code for blocker in assessment.blockers},
        )
        self.assertEqual(close.CloseStageStatus.BLOCKED, assessment.stages[0].status)
        self.assertEqual(close.CloseStageStatus.WAITING, assessment.stages[1].status)

    def test_missing_fact_blocks_its_stage_and_waits_downstream_dependencies(self) -> None:
        assessment = self._assess(
            self._snapshot(omitted=frozenset({close.CloseStage.BANK_RECONCILIATION}))
        )
        bank_stage = assessment.stages[1]

        self.assertEqual(close.CloseOutcome.BLOCKED, assessment.outcome)
        self.assertEqual(close.CloseStageStatus.BLOCKED, bank_stage.status)
        self.assertEqual(["fact_missing"], [item.code for item in bank_stage.blockers])
        self.assertEqual(close.CloseStageStatus.WAITING, assessment.stages[2].status)
        self.assertEqual((close.CloseStage.BANK_RECONCILIATION,), assessment.stages[2].depends_on)

    def test_unknown_or_failed_close_facts_block_instead_of_defaulting_safe(self) -> None:
        cases = (
            (
                close.CloseStage.SUBLEDGERS,
                close.CloseFactStatus.UNKNOWN,
                "fact_unknown",
            ),
            (
                close.CloseStage.BALANCED_TRIAL_BALANCE,
                close.CloseFactStatus.FAILED,
                "fact_failed",
            ),
        )

        for stage, fact_status, expected_code in cases:
            with self.subTest(stage=stage, fact_status=fact_status):
                assessment = self._assess(
                    self._snapshot(statuses={stage: fact_status})
                )
                index = close.CLOSE_STAGE_ORDER.index(stage)

                self.assertEqual(close.CloseOutcome.BLOCKED, assessment.outcome)
                self.assertEqual(close.CloseStageStatus.BLOCKED, assessment.stages[index].status)
                self.assertEqual(
                    [expected_code],
                    [item.code for item in assessment.stages[index].blockers],
                )
                if index + 1 < len(assessment.stages):
                    self.assertEqual(
                        close.CloseStageStatus.WAITING,
                        assessment.stages[index + 1].status,
                    )

    def test_explicit_review_fact_pauses_the_close_without_claiming_failure(self) -> None:
        assessment = self._assess(
            self._snapshot(
                statuses={
                    close.CloseStage.VAT_CONTROL: close.CloseFactStatus.REVIEW_REQUIRED
                }
            )
        )
        vat_index = close.CLOSE_STAGE_ORDER.index(close.CloseStage.VAT_CONTROL)

        self.assertEqual(close.CloseOutcome.REVIEW_REQUIRED, assessment.outcome)
        self.assertFalse(assessment.ready_for_human_lock)
        self.assertEqual(
            close.CloseStageStatus.REVIEW_REQUIRED,
            assessment.stages[vat_index].status,
        )
        self.assertEqual(
            ["fact_requires_review"],
            [item.code for item in assessment.stages[vat_index].blockers],
        )
        self.assertEqual(
            close.CloseStageStatus.WAITING,
            assessment.stages[vat_index + 1].status,
        )

    def test_satisfied_facts_require_valid_supporting_evidence_hashes(self) -> None:
        cases = (
            (close.CloseStage.EVIDENCE_COMPLETENESS, (), "fact_evidence_missing"),
            (close.CloseStage.ADJUSTMENTS, ("not-a-hash",), "fact_evidence_hash_invalid"),
        )

        for stage, evidence_hashes, expected_code in cases:
            with self.subTest(stage=stage):
                assessment = self._assess(
                    self._snapshot(fact_evidence={stage: evidence_hashes})
                )
                index = close.CLOSE_STAGE_ORDER.index(stage)

                self.assertEqual(close.CloseOutcome.BLOCKED, assessment.outcome)
                self.assertEqual(close.CloseStageStatus.BLOCKED, assessment.stages[index].status)
                self.assertEqual(
                    [expected_code],
                    [item.code for item in assessment.stages[index].blockers],
                )

    def test_duplicate_stage_facts_block_ambiguous_close_evidence(self) -> None:
        snapshot = self._snapshot()
        duplicate_facts = snapshot.facts + (snapshot.facts[0],)
        duplicate = close.CloseSnapshot(
            identity=snapshot.identity,
            evidence_bundle_hash=close.compute_close_evidence_bundle_hash(
                snapshot.identity,
                duplicate_facts,
            ),
            policy_hash=snapshot.policy_hash,
            facts=duplicate_facts,
        )

        assessment = self._assess(duplicate)

        self.assertEqual(close.CloseOutcome.BLOCKED, assessment.outcome)
        self.assertEqual(close.CloseStageStatus.BLOCKED, assessment.stages[0].status)
        self.assertEqual(
            ["fact_duplicate"],
            [item.code for item in assessment.stages[0].blockers],
        )
        self.assertEqual(close.CloseStageStatus.WAITING, assessment.stages[1].status)

    def test_preparer_and_independent_signoff_require_distinct_human_identities(self) -> None:
        cases = (
            (
                None,
                "controller-1",
                close.CloseStage.PREPARER_REVIEW,
                "preparer_identity_missing",
            ),
            (
                "accountant-1",
                None,
                close.CloseStage.INDEPENDENT_SIGNOFF,
                "independent_signoff_identity_missing",
            ),
            (
                "accountant-1",
                "accountant-1",
                close.CloseStage.INDEPENDENT_SIGNOFF,
                "signoff_not_independent",
            ),
        )

        for preparer_id, signoff_id, stage, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                assessment = self._assess(
                    self._snapshot(preparer_id=preparer_id, signoff_id=signoff_id)
                )
                index = close.CLOSE_STAGE_ORDER.index(stage)

                self.assertEqual(close.CloseOutcome.BLOCKED, assessment.outcome)
                self.assertEqual(close.CloseStageStatus.BLOCKED, assessment.stages[index].status)
                self.assertEqual(
                    [expected_code],
                    [item.code for item in assessment.stages[index].blockers],
                )

    def test_close_requires_verified_evidence_policy_bundle_and_signoff(self) -> None:
        snapshot = self._snapshot()

        missing_context = close.evaluate_period_close(snapshot)
        bad_evidence = close.evaluate_period_close(
            snapshot,
            verification=self._verification(snapshot, evidence=False),
        )
        bad_policy = close.evaluate_period_close(
            snapshot,
            verification=self._verification(snapshot, policy=False),
        )
        bad_signoff = close.evaluate_period_close(
            snapshot,
            verification=self._verification(snapshot, signoff=False),
        )
        mismatched_bundle_snapshot = close.CloseSnapshot(
            identity=snapshot.identity,
            evidence_bundle_hash="f" * 64,
            policy_hash=snapshot.policy_hash,
            facts=snapshot.facts,
        )
        mismatched_bundle = close.evaluate_period_close(
            mismatched_bundle_snapshot,
            verification=self._verification(mismatched_bundle_snapshot),
        )

        self.assertIn("verification_context_missing", {b.code for b in missing_context.blockers})
        self.assertIn("fact_evidence_unverified", {b.code for b in bad_evidence.blockers})
        self.assertIn("policy_hash_unverified", {b.code for b in bad_policy.blockers})
        self.assertIn("signoff_approval_unverified", {b.code for b in bad_signoff.blockers})
        self.assertIn("evidence_bundle_hash_mismatch", {b.code for b in mismatched_bundle.blockers})
        for assessment in (
            missing_context,
            bad_evidence,
            bad_policy,
            bad_signoff,
            mismatched_bundle,
        ):
            self.assertFalse(assessment.ready_for_human_lock)

    def _assess(self, snapshot: close.CloseSnapshot) -> close.CloseAssessment:
        try:
            return close.evaluate_period_close(
                snapshot,
                verification=self._verification(snapshot),
            )
        except Exception as exc:  # pragma: no cover - explicit TDD failure message.
            self.fail(f"period-close evaluation raised instead of failing closed: {exc!r}")

    @staticmethod
    def _snapshot(
        *,
        statuses: dict[close.CloseStage, close.CloseFactStatus] | None = None,
        fact_evidence: dict[close.CloseStage, tuple[str, ...]] | None = None,
        omitted: frozenset[close.CloseStage] = frozenset(),
        evidence_bundle_hash: str | None = "auto",
        policy_hash: str | None = "c" * 64,
        preparer_id: str | None = "accountant-1",
        signoff_id: str | None = "controller-1",
    ) -> close.CloseSnapshot:
        statuses = statuses or {}
        fact_evidence = fact_evidence or {}
        facts = []
        for index, stage in enumerate(close.CLOSE_STAGE_ORDER):
            if stage in omitted:
                continue
            actor_id = None
            if stage is close.CloseStage.PREPARER_REVIEW:
                actor_id = preparer_id
            elif stage is close.CloseStage.INDEPENDENT_SIGNOFF:
                actor_id = signoff_id
            facts.append(
                close.CloseFact(
                    stage=stage,
                    status=statuses.get(stage, close.CloseFactStatus.SATISFIED),
                    evidence_hashes=fact_evidence.get(
                        stage,
                        (f"{index + 1:x}" * 64,),
                    ),
                    summary=f"Synthetic {stage.value} control.",
                    actor_id=actor_id,
                )
            )
        identity = close.PeriodCloseIdentity("client-a", "entity-1", "2026-06")
        facts_tuple = tuple(facts)
        bundle_hash = (
            close.compute_close_evidence_bundle_hash(identity, facts_tuple)
            if evidence_bundle_hash == "auto"
            else evidence_bundle_hash
        )
        return close.CloseSnapshot(
            identity=identity,
            evidence_bundle_hash=bundle_hash,
            policy_hash=policy_hash,
            facts=facts_tuple,
        )

    @staticmethod
    def _verification(
        snapshot: close.CloseSnapshot,
        *,
        evidence: bool = True,
        policy: bool = True,
        signoff: bool = True,
    ) -> close.CloseVerificationContext:
        known_evidence = {
            digest
            for fact in snapshot.facts
            for digest in fact.evidence_hashes
        }
        return close.CloseVerificationContext(
            evidence_exists=lambda identity, digest: (
                evidence and identity == snapshot.identity and digest in known_evidence
            ),
            policy_is_current=lambda identity, digest: (
                policy
                and identity == snapshot.identity
                and digest == snapshot.policy_hash
            ),
            signoff_is_authorized=lambda identity, preparer, reviewer, digest, bundle, action: (
                signoff
                and identity == snapshot.identity
                and preparer == "accountant-1"
                and reviewer == "controller-1"
                and digest == snapshot.policy_hash
                and bundle == snapshot.evidence_bundle_hash
                and action == "period_close_ready_for_human_lock"
            ),
        )


if __name__ == "__main__":
    unittest.main()
