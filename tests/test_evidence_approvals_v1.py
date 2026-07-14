from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from accounting_agent.approvals import (
    ApprovalBinding,
    ApprovalConflict,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalValidationError,
    ReviewerIdentity,
    ReviewerRole,
    SQLiteApprovalStore,
)
from accounting_agent.evidence import (
    ContentAddressedEvidenceStore,
    EvidenceIntegrityError,
    EvidenceScopeError,
    FieldProvenance,
    HashChainedEventLog,
)


NOW = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)


def digest(value: bytes | str) -> str:
    material = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(material).hexdigest()


class EvidenceAndApprovalsV1Tests(unittest.TestCase):
    def test_v1_evidence_and_approval_modules_exist(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("accounting_agent.evidence"))
        self.assertIsNotNone(importlib.util.find_spec("accounting_agent.approvals"))

    def test_evidence_is_content_addressed_deduplicated_and_client_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ContentAddressedEvidenceStore(directory, clock=lambda: NOW)
            first = store.put(
                client_id="client-a",
                content=b"synthetic invoice",
                media_type="application/pdf",
            )
            second = store.put(
                client_id="client-a",
                content=b"synthetic invoice",
                media_type="application/pdf",
            )

            self.assertEqual(first, second)
            self.assertEqual(first.content_sha256, digest(b"synthetic invoice"))
            self.assertNotIn("invoice", first.storage_key)
            self.assertEqual(store.read(client_id="client-a", record=first), b"synthetic invoice")
            self.assertTrue(store.verify(client_id="client-a", record=first))
            with self.assertRaises(EvidenceScopeError):
                store.read(client_id="client-b", record=first)

    def test_evidence_mutation_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ContentAddressedEvidenceStore(directory, clock=lambda: NOW)
            record = store.put(
                client_id="client-a",
                content=b"original synthetic evidence",
                media_type="text/plain",
            )
            store.path_for(client_id="client-a", record=record).write_bytes(b"tampered")

            with self.assertRaises(EvidenceIntegrityError):
                store.read(client_id="client-a", record=record)
            self.assertFalse(store.verify(client_id="client-a", record=record))

    def test_field_provenance_requires_hash_and_location(self) -> None:
        provenance = FieldProvenance(
            source_hash=digest("source"),
            field_path="invoice.total",
            extractor="deterministic-fixture",
            extractor_version="1.0.0",
            page=2,
            span="Total 125.00",
            transformation_chain=("ocr", "normalize_decimal"),
        )
        self.assertEqual(provenance.page, 2)
        with self.assertRaises(ValueError):
            FieldProvenance(
                source_hash="not-a-sha",
                field_path="invoice.total",
                extractor="fixture",
                extractor_version="1",
            )

    def test_hash_chained_event_log_verifies_and_redacts_sensitive_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = HashChainedEventLog(Path(directory) / "events.jsonl", clock=lambda: NOW)
            first = log.append(
                client_id="client-a",
                event_type="evidence.received",
                actor_id="system",
                object_id="case-1",
                details={"status": "received", "bank_account": "SECRET-123"},
            )
            second = log.append(
                client_id="client-a",
                event_type="proposal.created",
                actor_id="agent",
                object_id="case-1",
                details={"proposal_hash": digest("proposal")},
            )

            verification = log.verify()
            self.assertTrue(verification.valid)
            self.assertEqual(verification.event_count, 2)
            self.assertEqual(second.previous_hash, first.event_hash)
            self.assertEqual(log.read()[0].details["bank_account"], "[redacted]")

            lines = log.path.read_text(encoding="utf-8").splitlines()
            mutated = json.loads(lines[0])
            mutated["details"]["status"] = "changed"
            lines[0] = json.dumps(mutated, sort_keys=True, separators=(",", ":"))
            log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertFalse(log.verify().valid)

    def test_hash_chain_detects_tail_deletion_against_separate_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = HashChainedEventLog(Path(directory) / "events.jsonl", clock=lambda: NOW)
            for sequence in range(2):
                log.append(
                    client_id="client-a",
                    event_type="test",
                    actor_id="system",
                    object_id=f"case-{sequence}",
                    details={},
                )
            first_line = log.path.read_text(encoding="utf-8").splitlines()[0]
            log.path.write_text(first_line + "\n", encoding="utf-8")
            self.assertFalse(log.verify().valid)

    def test_hash_chain_serializes_concurrent_appenders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            logs = (
                HashChainedEventLog(path, clock=lambda: NOW),
                HashChainedEventLog(path, clock=lambda: NOW),
            )

            def append(index: int) -> int:
                event = logs[index % 2].append(
                    client_id="client-a",
                    event_type="synthetic.concurrent",
                    actor_id=f"worker-{index % 2}",
                    object_id=f"case-{index}",
                    details={"index": index},
                )
                return event.sequence

            with ThreadPoolExecutor(max_workers=8) as pool:
                sequences = tuple(pool.map(append, range(24)))

            verification = logs[0].verify()
            self.assertTrue(verification.valid)
            self.assertEqual(24, verification.event_count)
            self.assertEqual(set(range(1, 25)), set(sequences))

    def test_identity_bound_approval_requires_independent_verified_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="controller-1",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="auditor-1",
                    client_id="client-a",
                    roles=(ReviewerRole.AUDITOR,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            request = self._approval_request()
            store.create_request(request)

            pending = store.verify(request, now=NOW)
            self.assertFalse(pending.valid)
            self.assertEqual(
                pending.missing_roles,
                (ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR),
            )
            store.record_decision(
                request_id=request.request_id,
                reviewer_id="controller-1",
                role=ReviewerRole.CONTROLLER,
                outcome=ApprovalOutcome.APPROVE,
                reason="Synthetic control checks passed.",
                decided_at=NOW,
            )
            store.record_decision(
                request_id=request.request_id,
                reviewer_id="auditor-1",
                role=ReviewerRole.AUDITOR,
                outcome=ApprovalOutcome.APPROVE,
                reason="Synthetic evidence is complete.",
                decided_at=NOW,
            )

            result = store.verify(request, now=NOW)
            self.assertTrue(result.valid)
            self.assertEqual(result.missing_roles, ())
            self.assertEqual(len(result.decision_ids), 2)

    def test_approval_binding_is_exact_and_records_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            request = self._approval_request()
            store.create_request(request)
            with self.assertRaises(ApprovalConflict):
                store.create_request(request)

            changed = ApprovalBinding(
                client_id=request.binding.client_id,
                entity_id=request.binding.entity_id,
                case_id=request.binding.case_id,
                proposal_hash=digest("changed proposal"),
                evidence_hashes=request.binding.evidence_hashes,
                policy_hash=request.binding.policy_hash,
                provider_id=request.binding.provider_id,
                environment=request.binding.environment,
            )
            result = store.verify(replace(request, binding=changed), now=NOW)
            self.assertFalse(result.valid)
            self.assertIn("approval_request_mismatch", result.errors)

    def test_rejected_exact_scope_can_be_reissued_as_new_immutable_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="controller-1",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            first = self._approval_request()
            store.create_request(first)
            store.record_decision(
                request_id=first.request_id,
                reviewer_id="controller-1",
                role=ReviewerRole.CONTROLLER,
                outcome=ApprovalOutcome.REJECT,
                reason="Synthetic correction required.",
                decided_at=NOW,
            )
            retry = replace(
                first,
                request_id="approval-2",
                created_at=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=2),
            )

            store.create_request(retry)

            self.assertFalse(store.verify(retry, now=retry.created_at).valid)
            self.assertEqual(
                retry.required_roles,
                store.verify(retry, now=retry.created_at).missing_roles,
            )

    def test_expired_exact_scope_can_be_reissued_but_active_scope_is_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            original = replace(
                self._approval_request(),
                created_at=NOW - timedelta(hours=2),
                expires_at=NOW - timedelta(hours=1),
            )
            store.create_request(original)
            retry = replace(
                original,
                request_id="approval-2",
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )

            store.create_request(retry)

            overlapping = replace(
                retry,
                request_id="approval-3",
                created_at=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=2),
            )
            with self.assertRaises(ApprovalConflict):
                store.create_request(overlapping)

    def test_concurrent_exact_scope_requests_keep_one_active_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            base = self._approval_request()
            requests = (
                base,
                replace(base, request_id="approval-concurrent-2"),
            )

            def create(request: ApprovalRequest) -> str:
                try:
                    store.create_request(request)
                    return "created"
                except ApprovalConflict:
                    return "conflict"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = tuple(pool.map(create, requests))

            self.assertEqual(1, outcomes.count("created"))
            self.assertEqual(1, outcomes.count("conflict"))

    def test_legacy_unique_binding_schema_migrates_without_inventing_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy-approvals.sqlite"
            original = replace(
                self._approval_request(),
                created_at=NOW - timedelta(hours=2),
                expires_at=NOW - timedelta(hours=1),
            )
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE approval_requests (
                        request_id TEXT PRIMARY KEY,
                        binding_digest TEXT NOT NULL UNIQUE,
                        binding_json TEXT NOT NULL,
                        action TEXT NOT NULL,
                        requestor_id TEXT NOT NULL,
                        required_roles TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO approval_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        original.request_id,
                        original.binding.digest,
                        json.dumps(
                            original.binding.to_dict(),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        original.action,
                        original.requestor_id,
                        json.dumps([role.value for role in original.required_roles]),
                        original.created_at.isoformat(),
                        original.expires_at.isoformat(),
                    ),
                )

            store = SQLiteApprovalStore(database)
            retry = replace(
                original,
                request_id="approval-migrated-retry",
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )

            store.create_request(retry)

            with closing(sqlite3.connect(database)) as connection, connection:
                unique_binding_indexes = [
                    row
                    for row in connection.execute(
                        "PRAGMA index_list(approval_requests)"
                    ).fetchall()
                    if bool(row[2])
                    and tuple(
                        item[2]
                        for item in connection.execute(
                            f"PRAGMA index_info({json.dumps(row[1])})"
                        ).fetchall()
                    )
                    == ("binding_digest",)
                ]
            self.assertEqual([], unique_binding_indexes)

    def test_approval_verification_binds_action_roles_requestor_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="controller-1",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            low_risk = replace(
                self._approval_request(),
                action="view_report",
                required_roles=(ReviewerRole.CONTROLLER,),
            )
            store.create_request(low_risk)
            store.record_decision(
                request_id=low_risk.request_id,
                reviewer_id="controller-1",
                role=ReviewerRole.CONTROLLER,
                outcome=ApprovalOutcome.APPROVE,
                reason="Synthetic report reviewed.",
                decided_at=NOW,
            )

            for expected in (
                replace(low_risk, action="final_close_signoff"),
                replace(
                    low_risk,
                    required_roles=(ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR),
                ),
                replace(low_risk, requestor_id="different-requestor"),
                replace(low_risk, expires_at=low_risk.expires_at + timedelta(hours=1)),
            ):
                with self.subTest(expected=expected):
                    result = store.verify(expected, now=NOW)
                    self.assertFalse(result.valid)
                    self.assertIn("approval_request_mismatch", result.errors)

    def test_approval_rejects_self_wrong_scope_role_identity_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            for identity in (
                ReviewerIdentity(
                    reviewer_id="requestor-1",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                ),
                ReviewerIdentity(
                    reviewer_id="wrong-client",
                    client_id="client-b",
                    roles=(ReviewerRole.CONTROLLER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                ),
                ReviewerIdentity(
                    reviewer_id="inactive",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=False,
                ),
            ):
                store.register_reviewer(identity)
            request = self._approval_request()
            store.create_request(request)

            attempts = (
                ("requestor-1", ReviewerRole.CONTROLLER, NOW),
                ("wrong-client", ReviewerRole.CONTROLLER, NOW),
                ("inactive", ReviewerRole.CONTROLLER, NOW),
                ("missing-reviewer", ReviewerRole.CONTROLLER, NOW),
                ("requestor-1", ReviewerRole.AUDITOR, NOW),
                ("requestor-1", ReviewerRole.CONTROLLER, request.expires_at),
                (
                    "requestor-1",
                    ReviewerRole.CONTROLLER,
                    request.created_at - timedelta(microseconds=1),
                ),
            )
            for reviewer_id, role, decided_at in attempts:
                with self.subTest(reviewer_id=reviewer_id, role=role, at=decided_at):
                    with self.assertRaises(ApprovalValidationError):
                        store.record_decision(
                            request_id=request.request_id,
                            reviewer_id=reviewer_id,
                            role=role,
                            outcome=ApprovalOutcome.APPROVE,
                            reason="Should be rejected.",
                            decided_at=decided_at,
                        )

    def test_one_reviewer_cannot_fill_two_required_roles_or_replace_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="dual-role",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            request = self._approval_request()
            store.create_request(request)
            store.record_decision(
                request_id=request.request_id,
                reviewer_id="dual-role",
                role=ReviewerRole.CONTROLLER,
                outcome=ApprovalOutcome.APPROVE,
                reason="First role.",
                decided_at=NOW,
            )
            with self.assertRaises(ApprovalValidationError):
                store.record_decision(
                    request_id=request.request_id,
                    reviewer_id="dual-role",
                    role=ReviewerRole.AUDITOR,
                    outcome=ApprovalOutcome.APPROVE,
                    reason="Second role by same person.",
                    decided_at=NOW,
                )
            with self.assertRaises(ApprovalConflict):
                store.record_decision(
                    request_id=request.request_id,
                    reviewer_id="dual-role",
                    role=ReviewerRole.CONTROLLER,
                    outcome=ApprovalOutcome.REJECT,
                    reason="Attempted replacement.",
                    decided_at=NOW,
                )

    def test_concurrent_dual_role_decisions_cannot_bypass_segregation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="dual-role",
                    client_id="client-a",
                    roles=(ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            request = self._approval_request()
            store.create_request(request)

            def decide(role: ReviewerRole) -> str:
                try:
                    store.record_decision(
                        request_id=request.request_id,
                        reviewer_id="dual-role",
                        role=role,
                        outcome=ApprovalOutcome.APPROVE,
                        reason=f"Synthetic {role.value} decision.",
                        decided_at=NOW,
                    )
                    return "accepted"
                except (ApprovalConflict, ApprovalValidationError):
                    return "rejected"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = tuple(
                    pool.map(decide, (ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR))
                )
            self.assertEqual(1, outcomes.count("accepted"))
            self.assertEqual(1, outcomes.count("rejected"))

    def test_client_scope_is_stored_in_unicode_nfc(self) -> None:
        decomposed = "client-e\u0301"
        normalized = "client-é"
        identity = ReviewerIdentity(
            reviewer_id="reviewer-1",
            client_id=decomposed,
            roles=(ReviewerRole.CONTROLLER,),
            identity_provider="local-test-registry",
            verified=True,
            active=True,
        )
        binding = replace(self._approval_request().binding, client_id=decomposed)

        self.assertEqual(normalized, identity.client_id)
        self.assertEqual(normalized, binding.client_id)

    @staticmethod
    def _approval_request() -> ApprovalRequest:
        return ApprovalRequest(
            request_id="approval-1",
            binding=ApprovalBinding(
                client_id="client-a",
                entity_id="entity-se-1",
                case_id="case-1",
                proposal_hash=digest("proposal"),
                evidence_hashes=(digest("evidence-1"), digest("evidence-2")),
                policy_hash=digest("policy-v1"),
                provider_id="fortnox-dry-run",
                environment="preview",
            ),
            action="final_close_signoff",
            requestor_id="requestor-1",
            required_roles=(ReviewerRole.CONTROLLER, ReviewerRole.AUDITOR),
            created_at=NOW,
            expires_at=NOW + timedelta(hours=4),
        )


if __name__ == "__main__":
    unittest.main()
