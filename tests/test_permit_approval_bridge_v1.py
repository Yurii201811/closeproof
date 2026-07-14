from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import accounting_agent.permits as permits
import accounting_agent
from accounting_agent.approvals import (
    ApprovalOutcome,
    ApprovalValidationError,
    ReviewerIdentity,
    ReviewerRole,
    SQLiteApprovalStore,
)
from accounting_agent.policy import ActionType, PolicyContext, evaluate_policy


NOW = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PermitApprovalBridgeV1Tests(unittest.TestCase):
    def test_bridge_api_is_available(self) -> None:
        for name in (
            "PermitApprovalReceipt",
            "TrustedApprovalAuthority",
            "build_permit_approval_request",
            "canonical_policy_decision_hash",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(permits, name))
                self.assertTrue(hasattr(accounting_agent, name))

    def test_verified_store_approval_issues_exact_receipt_bound_permit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, request, context, decision, payload = self._approved_request(directory)
            permit_store = permits.SQLitePermitStore(
                Path(directory) / "permits.sqlite"
            )
            issuer = permits.PermitIssuer(
                permit_store,
                approval_authority=store,
                clock=lambda: NOW,
                id_factory=lambda: "permit_verified",
            )

            permit = issuer.issue(
                decision=decision,
                context=context,
                case_id="case-1",
                entity_id="entity-se-1",
                payload=payload,
                approval_request=request,
            )

            self.assertEqual("entity-se-1", permit.entity_id)
            self.assertEqual((), permit.approved_reviews)
            self.assertIsNotNone(permit.approval_receipt)
            assert permit.approval_receipt is not None
            self.assertEqual(request.request_id, permit.approval_receipt.request_id)
            self.assertEqual(request.digest, permit.approval_receipt.request_digest)
            self.assertEqual(request.binding.digest, permit.approval_receipt.binding_digest)
            self.assertEqual("client-a", permit.approval_receipt.client_id)
            self.assertEqual("entity-se-1", permit.approval_receipt.entity_id)
            self.assertEqual("case-1", permit.approval_receipt.case_id)
            self.assertEqual(
                ActionType.DRAFT_SUPPLIER_INVOICE.value,
                permit.approval_receipt.action,
            )
            self.assertEqual(
                permits.canonical_payload_hash(payload),
                permit.approval_receipt.payload_hash,
            )
            self.assertEqual(
                permits.canonical_policy_decision_hash(decision),
                permit.approval_receipt.policy_hash,
            )
            self.assertEqual(1, len(permit.approval_receipt.decision_ids))
            self.assertEqual(NOW, permit.approval_receipt.verified_at)

            permits.PermitValidator(
                permit_store=permit_store,
                approval_authority=store,
                clock=lambda: NOW,
            ).require_valid(
                permit=permit,
                case_id="case-1",
                entity_id="entity-se-1",
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                payload=payload,
            )

            tampered = replace(
                permit,
                approval_receipt=replace(
                    permit.approval_receipt,
                    case_id="case-other",
                ),
            )
            with self.assertRaisesRegex(permits.PermitValidationError, "receipt scope"):
                permits.PermitValidator(
                    permit_store=permit_store,
                    approval_authority=store,
                    clock=lambda: NOW,
                ).require_valid(
                    permit=tampered,
                    case_id="case-1",
                    entity_id="entity-se-1",
                    action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                    payload=payload,
                )

    def test_reviewed_permit_requires_exact_trusted_store_record_at_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approval_store, request, context, decision, payload = self._approved_request(
                directory
            )
            permit_store = permits.SQLitePermitStore(
                Path(directory) / "permits.sqlite"
            )
            permit = permits.PermitIssuer(
                permit_store,
                approval_authority=approval_store,
                clock=lambda: NOW,
            ).issue(
                decision=decision,
                context=context,
                case_id="case-1",
                entity_id="entity-se-1",
                payload=payload,
                approval_request=request,
            )

            for validator, candidate in (
                (permits.PermitValidator(clock=lambda: NOW), permit),
                (
                    permits.PermitValidator(
                        permit_store=permit_store,
                        clock=lambda: NOW,
                    ),
                    replace(permit, permit_id="forged-permit-id"),
                ),
                (
                    permits.PermitValidator(
                        permit_store=permit_store,
                        clock=lambda: NOW,
                    ),
                    replace(
                        permit,
                        approval_receipt=replace(
                            permit.approval_receipt,
                            decision_ids=("forged-decision-id",),
                        ),
                    ),
                ),
            ):
                with self.subTest(candidate=candidate.permit_id):
                    with self.assertRaisesRegex(
                        permits.PermitValidationError,
                        "trusted permit store",
                    ):
                        validator.require_valid(
                            permit=candidate,
                            case_id="case-1",
                            entity_id="entity-se-1",
                            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                            payload=payload,
                        )

            forged = replace(
                permit,
                approval_receipt=replace(
                    permit.approval_receipt,
                    request_id="forged-approval-request",
                    decision_ids=("forged-decision-id",),
                ),
            )
            permit_store.save(forged)
            with self.assertRaisesRegex(
                permits.PermitValidationError,
                "trusted approval authority",
            ):
                permits.PermitValidator(
                    permit_store=permit_store,
                    approval_authority=approval_store,
                    clock=lambda: NOW,
                ).require_valid(
                    permit=forged,
                    case_id="case-1",
                    entity_id="entity-se-1",
                    action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                    payload=payload,
                )

    def test_future_dated_approval_cannot_issue_before_request_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(
                Path(directory) / "approvals.sqlite",
                clock=lambda: NOW + timedelta(hours=2),
            )
            context = PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client-a",
                currency_code="SEK",
                amount_minor=50_000_00,
                risk_evidence_complete=True,
            )
            decision = evaluate_policy(context)
            payload = {"supplier_id": "supplier-1", "amount_minor": 50_000_00}
            request = permits.build_permit_approval_request(
                request_id="approval-future",
                decision=decision,
                case_id="case-future",
                entity_id="entity-se-1",
                payload=payload,
                evidence_hashes=(digest("future-evidence"),),
                provider_id="fortnox-dry-run",
                environment="preview",
                requestor_id="requestor-1",
                created_at=NOW + timedelta(hours=1),
                expires_at=NOW + timedelta(hours=2),
            )
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="reviewer-future",
                    client_id="client-a",
                    roles=(ReviewerRole.REVIEWER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            store.create_request(request)
            store.record_decision(
                request_id=request.request_id,
                reviewer_id="reviewer-future",
                role=ReviewerRole.REVIEWER,
                outcome=ApprovalOutcome.APPROVE,
                reason="Future-dated synthetic decision.",
                decided_at=NOW + timedelta(hours=1, minutes=1),
            )

            with self.assertRaisesRegex(permits.PermitReviewRequired, "not valid"):
                permits.PermitIssuer(
                    permits.InMemoryPermitStore(),
                    approval_authority=store,
                    clock=lambda: NOW,
                ).issue(
                    decision=decision,
                    context=context,
                    case_id="case-future",
                    entity_id="entity-se-1",
                    payload=payload,
                    approval_request=request,
                )

    def test_approval_store_rejects_future_decision_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(
                Path(directory) / "approvals.sqlite",
                clock=lambda: NOW,
            )
            store.register_reviewer(
                ReviewerIdentity(
                    reviewer_id="reviewer-1",
                    client_id="client-a",
                    roles=(ReviewerRole.REVIEWER,),
                    identity_provider="local-test-registry",
                    verified=True,
                    active=True,
                )
            )
            context = PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client-a",
                currency_code="SEK",
                amount_minor=50_000_00,
                risk_evidence_complete=True,
            )
            payload = {"amount_minor": 50_000_00}
            request = permits.build_permit_approval_request(
                request_id="approval-future-decision",
                decision=evaluate_policy(context),
                case_id="case-future-decision",
                entity_id="entity-se-1",
                payload=payload,
                evidence_hashes=(digest("future-decision-evidence"),),
                provider_id="fortnox-dry-run",
                environment="preview",
                requestor_id="requestor-1",
                created_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=2),
            )
            store.create_request(request)

            with self.assertRaisesRegex(
                ApprovalValidationError,
                "future",
            ):
                store.record_decision(
                    request_id=request.request_id,
                    reviewer_id="reviewer-1",
                    role=ReviewerRole.REVIEWER,
                    outcome=ApprovalOutcome.APPROVE,
                    reason="Future decision must fail.",
                    decided_at=NOW + timedelta(minutes=1),
                )

    def test_issuer_rejects_scope_drift_after_human_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, request, context, decision, payload = self._approved_request(directory)
            issuer = permits.PermitIssuer(
                permits.InMemoryPermitStore(),
                approval_authority=store,
                clock=lambda: NOW,
            )

            mismatches = (
                {
                    "case_id": "case-other",
                    "entity_id": "entity-se-1",
                    "payload": payload,
                    "approval_request": request,
                },
                {
                    "case_id": "case-1",
                    "entity_id": "entity-other",
                    "payload": payload,
                    "approval_request": request,
                },
                {
                    "case_id": "case-1",
                    "entity_id": "entity-se-1",
                    "payload": {**payload, "amount_minor": 50_000_01},
                    "approval_request": request,
                },
                {
                    "case_id": "case-1",
                    "entity_id": "entity-se-1",
                    "payload": payload,
                    "approval_request": replace(request, action="send_email"),
                },
                {
                    "case_id": "case-1",
                    "entity_id": "entity-se-1",
                    "payload": payload,
                    "approval_request": replace(
                        request,
                        binding=replace(request.binding, policy_hash=digest("wrong-policy")),
                    ),
                },
                {
                    "case_id": "case-1",
                    "entity_id": "entity-se-1",
                    "payload": payload,
                    "approval_request": replace(
                        request,
                        binding=replace(request.binding, client_id="client-other"),
                    ),
                },
            )
            for arguments in mismatches:
                with self.subTest(arguments=arguments):
                    with self.assertRaisesRegex(permits.PermitReviewRequired, "scope"):
                        issuer.issue(
                            decision=decision,
                            context=context,
                            **arguments,
                        )

    def test_expired_or_rejected_approval_cannot_issue_permit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, request, context, decision, payload = self._approval_request(
                directory,
                outcome=ApprovalOutcome.REJECT,
            )
            issuer = permits.PermitIssuer(
                permits.InMemoryPermitStore(),
                approval_authority=store,
                clock=lambda: NOW,
            )
            with self.assertRaisesRegex(permits.PermitReviewRequired, "not valid"):
                issuer.issue(
                    decision=decision,
                    context=context,
                    case_id="case-1",
                    entity_id="entity-se-1",
                    payload=payload,
                    approval_request=request,
                )

        with tempfile.TemporaryDirectory() as directory:
            store, request, context, decision, payload = self._approved_request(directory)
            issuer = permits.PermitIssuer(
                permits.InMemoryPermitStore(),
                approval_authority=store,
                clock=lambda: request.expires_at,
            )
            with self.assertRaisesRegex(permits.PermitReviewRequired, "not valid"):
                issuer.issue(
                    decision=decision,
                    context=context,
                    case_id="case-1",
                    entity_id="entity-se-1",
                    payload=payload,
                    approval_request=request,
                )

    def test_reviewed_direct_permit_with_caller_labels_is_rejected(self) -> None:
        payload = {"amount_minor": 50_000_00}
        permit = permits.ExecutionPermit(
            permit_id="permit_direct_forged",
            case_id="case-1",
            client_id="client-a",
            allowed_action=ActionType.DRAFT_SUPPLIER_INVOICE,
            payload_hash=permits.canonical_payload_hash(payload),
            policy_version="accounting-policy-v1",
            required_reviews=("accountant_review",),
            permission_mode=permits.PermissionMode.APPROVAL_REQUIRED,
            expires_at=NOW + timedelta(minutes=30),
            idempotency_key="forged",
            issued_at=NOW,
            entity_id="entity-se-1",
            policy_decision_hash=digest("forged-policy-decision"),
            approved_reviews=("accountant_review",),
        )

        with self.assertRaisesRegex(permits.PermitValidationError, "caller-supplied"):
            permits.PermitValidator(clock=lambda: NOW).require_valid(
                permit=permit,
                case_id="case-1",
                entity_id="entity-se-1",
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                payload=payload,
            )

    def test_zero_review_permit_requires_explicit_entity_without_approval_authority(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client-a",
            currency_code="SEK",
            amount_minor=1_000_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)

        with self.assertRaisesRegex(permits.PermitValidationError, "entity_id"):
            permits.PermitIssuer(clock=lambda: NOW).issue(
                decision=decision,
                context=context,
                case_id="case-low-risk",
                payload={"amount_minor": 1_000_00},
            )

        permit = permits.PermitIssuer(clock=lambda: NOW).issue(
            decision=decision,
            context=context,
            case_id="case-low-risk",
            entity_id="entity-se-1",
            payload={"amount_minor": 1_000_00},
        )

        self.assertEqual((), permit.required_reviews)
        self.assertIsNone(permit.approval_receipt)
        self.assertEqual("entity-se-1", permit.entity_id)

    def test_permit_validator_rejects_cross_entity_reuse(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client-a",
            currency_code="SEK",
            amount_minor=1_000_00,
            risk_evidence_complete=True,
        )
        payload = {"amount_minor": 1_000_00}
        permit = permits.PermitIssuer(clock=lambda: NOW).issue(
            decision=evaluate_policy(context),
            context=context,
            case_id="case-low-risk",
            entity_id="entity-se-1",
            payload=payload,
        )

        with self.assertRaisesRegex(permits.PermitValidationError, "entity_id"):
            permits.PermitValidator(clock=lambda: NOW).require_valid(
                permit=permit,
                case_id="case-low-risk",
                entity_id="entity-other",
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                payload=payload,
            )

    def test_entity_scope_changes_permit_idempotency_key(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client-a",
            currency_code="SEK",
            amount_minor=1_000_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        payload = {"amount_minor": 1_000_00}

        permits_by_entity = tuple(
            permits.PermitIssuer(clock=lambda: NOW).issue(
                decision=decision,
                context=context,
                case_id="case-low-risk",
                entity_id=entity_id,
                payload=payload,
            )
            for entity_id in ("entity-se-1", "entity-se-2")
        )

        self.assertNotEqual(
            permits_by_entity[0].idempotency_key,
            permits_by_entity[1].idempotency_key,
        )

    def test_client_scope_changes_permit_idempotency_key(self) -> None:
        payload = {"amount_minor": 1_000_00}
        permits_by_client = []
        for client_id in ("client-a", "client-b"):
            context = PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id=client_id,
                currency_code="SEK",
                amount_minor=1_000_00,
                risk_evidence_complete=True,
            )
            permits_by_client.append(
                permits.PermitIssuer(clock=lambda: NOW).issue(
                    decision=evaluate_policy(context),
                    context=context,
                    case_id="case-low-risk",
                    entity_id="entity-se-1",
                    payload=payload,
                )
            )

        self.assertNotEqual(
            permits_by_client[0].idempotency_key,
            permits_by_client[1].idempotency_key,
        )

    def test_forged_policy_metadata_cannot_become_approval_scope(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client-a",
            currency_code="SEK",
            amount_minor=1_000_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)

        with self.assertRaisesRegex(permits.PermitValidationError, "reasons"):
            permits.PermitIssuer(clock=lambda: NOW).issue(
                decision=replace(decision, reasons=("forged-policy-narrative",)),
                context=context,
                case_id="case-low-risk",
                entity_id="entity-se-1",
                payload={"amount_minor": 1_000_00},
            )

    def test_escalation_policy_reviews_map_to_distinct_exact_roles(self) -> None:
        context = PolicyContext(
            action_type=ActionType.UPDATE_SUPPLIER_BANK_DETAILS,
            client_id="client-a",
            currency_code="SEK",
            bank_details_changed=True,
            risk_evidence_complete=True,
        )
        request = permits.build_permit_approval_request(
            request_id="approval-bank-change",
            decision=evaluate_policy(context),
            case_id="case-bank-change",
            entity_id="entity-se-1",
            payload={"bank_details_changed": True},
            evidence_hashes=(digest("bank-change-evidence"),),
            provider_id="fortnox-dry-run",
            environment="preview",
            requestor_id="requestor-1",
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )

        self.assertEqual(
            ("reviewer", "controller", "security_reviewer"),
            tuple(role.value for role in request.required_roles),
        )

    def test_sqlite_permit_store_round_trips_verified_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approval_store, request, context, decision, payload = self._approved_request(
                directory
            )
            permit_store = permits.SQLitePermitStore(Path(directory) / "permits.sqlite")
            permit = permits.PermitIssuer(
                permit_store,
                approval_authority=approval_store,
                clock=lambda: NOW,
                id_factory=lambda: "permit_persisted_receipt",
            ).issue(
                decision=decision,
                context=context,
                case_id="case-1",
                entity_id="entity-se-1",
                payload=payload,
                approval_request=request,
            )

            self.assertEqual(permit, permit_store.get(permit.permit_id))

    def test_sqlite_permit_store_migrates_legacy_receipt_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy-permits.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE execution_permits (
                        permit_id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        allowed_action TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        required_reviews TEXT NOT NULL,
                        permission_mode TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        issued_at TEXT NOT NULL,
                        approved_reviews TEXT NOT NULL
                    )
                    """
                )

            permits.SQLitePermitStore(database)

            with closing(sqlite3.connect(database)) as connection, connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(execution_permits)"
                    ).fetchall()
                }
            self.assertIn("entity_id", columns)
            self.assertIn("approval_receipt", columns)
            self.assertIn("policy_decision_hash", columns)

    def test_sqlite_permit_store_rejects_rows_without_entity(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client-a",
            currency_code="SEK",
            amount_minor=1_000_00,
            risk_evidence_complete=True,
        )
        permit = permits.PermitIssuer(clock=lambda: NOW).issue(
            decision=evaluate_policy(context),
            context=context,
            case_id="case-low-risk",
            entity_id="entity-se-1",
            payload={"amount_minor": 1_000_00},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = permits.SQLitePermitStore(Path(directory) / "permits.sqlite")
            with self.assertRaisesRegex(permits.PermitValidationError, "entity_id"):
                store.save(replace(permit, entity_id=None))

    @staticmethod
    def _approved_request(directory: str):
        return PermitApprovalBridgeV1Tests._approval_request(
            directory,
            outcome=ApprovalOutcome.APPROVE,
        )

    @staticmethod
    def _approval_request(directory: str, *, outcome: ApprovalOutcome):
        store = SQLiteApprovalStore(
            Path(directory) / "approvals.sqlite",
            clock=lambda: NOW,
        )
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client-a",
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        payload = {"supplier_id": "supplier-1", "amount_minor": 50_000_00}
        request = permits.build_permit_approval_request(
            request_id="approval-permit-1",
            decision=decision,
            case_id="case-1",
            entity_id="entity-se-1",
            payload=payload,
            evidence_hashes=(digest("synthetic-evidence"),),
            provider_id="fortnox-dry-run",
            environment="preview",
            requestor_id="requestor-1",
            created_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(hours=1),
        )
        store.register_reviewer(
            ReviewerIdentity(
                reviewer_id="reviewer-1",
                client_id="client-a",
                roles=(ReviewerRole.REVIEWER,),
                identity_provider="local-test-registry",
                verified=True,
                active=True,
            )
        )
        store.create_request(request)
        store.record_decision(
            request_id=request.request_id,
            reviewer_id="reviewer-1",
            role=ReviewerRole.REVIEWER,
            outcome=outcome,
            reason="Synthetic exact-scope review.",
            decided_at=NOW,
        )
        return store, request, context, decision, payload


if __name__ == "__main__":
    unittest.main()
