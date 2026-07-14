from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from accounting_agent import LocalGnubokShadowLedgerAdapter, ShadowLedgerUnavailable
from accounting_agent.db import LOCAL_QUEUE_SCHEMA_VERSION, LocalQueue, QueueSchemaError
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.supplier_invoice.extraction import extract_invoice_fields
from accounting_agent.supplier_invoice.pipeline import build_invoice_signature


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "supplier_invoices"


class SupplierInvoicePipelineTests(unittest.TestCase):
    def test_pipeline_requires_explicit_legal_entity(self) -> None:
        with self.assertRaises(TypeError):
            SupplierInvoicePipeline(db_path=None, output_dir=None)

    def run_pipeline(self) -> tuple[list[dict], Path, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        db_path = root / "queue.sqlite"
        output_dir = root / "packets"
        pipeline = SupplierInvoicePipeline(
            db_path=db_path,
            output_dir=output_dir,
            entity_id="fixture-entity",
            evaluation_date=date(2026, 5, 16),
        )
        packets = pipeline.process_fixture_dir(FIXTURES)
        return packets, db_path, output_dir

    def test_processes_all_sample_fixtures_into_approval_packets(self) -> None:
        packets, db_path, output_dir = self.run_pipeline()

        self.assertEqual(5, len(packets))
        self.assertEqual(5, len(list(output_dir.glob("*.approval_packet.json"))))
        self.assertEqual(5, table_count(db_path, "approval_packets"))
        self.assertEqual(5, table_count(db_path, "accounting_proposals"))
        self.assertGreaterEqual(table_count(db_path, "audit_events"), 10)

        for packet in packets:
            self.assertEqual("supplier_invoice_autopilot_mvp1.v1", packet["packet_version"])
            self.assertTrue(packet["case"]["file_hash"])
            self.assertEqual("local_fixture", packet["case"]["created_from"])
            self.assertIn("entries", packet["accounting_proposal"])
            self.assertIn("flags", packet["risk"])
            self.assertIn(
                packet["policy_decision"]["mode"],
                {"draft_only", "approval_required", "escalation_required"},
            )
            self.assertIn("risk_findings", packet)
            self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])
            self.assertFalse(packet["next_action"]["live_api_call"])
            self.assertTrue(packet["required_human_decision"])
            self.assertIn("shadow_ledger_comparison", packet)
            self.assertEqual("fortnox", packet["shadow_ledger_comparison"]["source_of_truth"])
            self.assertIn(
                packet["shadow_ledger_comparison"]["status"],
                {"mirrored", "mirrored_with_warnings"},
            )

    def test_normal_swedish_invoice_is_draft_only_with_bas_and_vat_proposal(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "normal_swedish_25_vat")

        self.assertEqual("draft_only", packet["policy_decision"]["mode"])
        self.assertEqual("low", packet["risk"]["level"])
        self.assertEqual([], packet["risk"]["flags"])
        self.assertEqual("matched", packet["supplier_match"]["status"])
        self.assertEqual("6110", packet["accounting_proposal"]["bas_account"])
        self.assertEqual("2641", packet["vat_proposal"]["input_vat_account"])
        self.assertEqual("2440", packet["accounting_proposal"]["entries"][2]["account"])
        self.assertEqual("mirrored", packet["shadow_ledger_comparison"]["status"])
        self.assertEqual([], packet["shadow_ledger_comparison"]["differences"])
        self.assertEqual(
            packet["fortnox_draft_payload"]["accounting_rows"],
            packet["shadow_ledger_comparison"]["fortnox_payload"]["accounting_rows"],
        )

    def test_duplicate_invoice_is_blocked_for_human_review(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "possible_duplicate_invoice")

        self.assertEqual("possible_duplicate", packet["duplicate_check"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertIn("possible_duplicate", flag_codes(packet))
        self.assertEqual("none_until_duplicate_reviewed", packet["next_action"]["action"])

    def test_unknown_supplier_requires_review_but_still_gets_accounting_proposal(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "unknown_supplier")

        self.assertEqual("unknown", packet["supplier_match"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertIn("unknown_supplier", flag_codes(packet))
        self.assertEqual("6991", packet["accounting_proposal"]["bas_account"])
        self.assertEqual("none_until_supplier_created_or_matched", packet["next_action"]["action"])

    def test_changed_bank_details_blocks_supplier_master_update(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "changed_bank_details")

        self.assertEqual("changed", packet["supplier_match"]["bank_details_status"])
        self.assertIn("changed_bank_details", flag_codes(packet))
        self.assertEqual("escalation_required", packet["policy_decision"]["mode"])
        self.assertIn("security_review", packet["policy_decision"]["required_reviews"])
        self.assertIn("update_supplier_bank_details", packet["policy_decision"]["blocked_actions"])
        self.assertEqual("none_until_bank_details_verified", packet["next_action"]["action"])

    def test_uncertain_vat_and_extraction_requires_manual_review(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "uncertain_vat_extraction")

        codes = flag_codes(packet)
        self.assertIn("low_extraction_confidence", codes)
        self.assertIn("missing_required_fields", codes)
        self.assertIn("vat_amount_mismatch", codes)
        self.assertEqual("manual_review", packet["vat_proposal"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertEqual("none_until_extraction_and_vat_reviewed", packet["next_action"]["action"])
        self.assertIn(
            "vat_amount_differs_from_rate:expected_30000:actual_12500",
            packet["shadow_ledger_comparison"]["warnings"],
        )

    def test_shadow_ledger_fail_soft_keeps_supplier_invoice_pipeline_working(self) -> None:
        class UnavailableAdapter(LocalGnubokShadowLedgerAdapter):
            def get_or_create_company_context(self, **kwargs):  # type: ignore[no-untyped-def]
                raise ShadowLedgerUnavailable("gnubok_not_configured")

        pipeline = SupplierInvoicePipeline(
            db_path=None,
            output_dir=None,
            entity_id="fixture-entity",
            shadow_ledger_adapter=UnavailableAdapter(),
        )

        packet = pipeline.process_fixture(FIXTURES / "01_normal_25_vat.json")

        self.assertEqual("shadow_unavailable", packet["shadow_ledger_comparison"]["status"])
        self.assertEqual("fortnox", packet["shadow_ledger_comparison"]["source_of_truth"])
        self.assertIn("main_pipeline_unaffected", packet["shadow_ledger_comparison"]["warnings"])
        self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])

    def test_pipeline_keeps_client_and_legal_entity_bindings_distinct(self) -> None:
        try:
            pipeline = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                client_id="accounting-firm",
                entity_id="legal-entity-se-1",
                evaluation_date=date(2026, 5, 16),
            )
        except TypeError as exc:
            self.fail(f"Pipeline must accept an explicit legal entity: {exc}")

        packet = pipeline.process_fixture(FIXTURES / "01_normal_25_vat.json")

        self.assertNotEqual(
            packet["run_context"]["client_id"],
            packet["run_context"]["entity_id"],
        )
        self.assertEqual("accounting-firm", packet["case"]["client_id"])
        self.assertEqual("legal-entity-se-1", packet["case"]["entity_id"])
        self.assertEqual("accounting-firm", packet["journal_binding"]["client_id"])
        self.assertEqual("legal-entity-se-1", packet["journal_binding"]["entity_id"])
        self.assertEqual("accounting-firm", packet["fortnox_draft_payload"]["client_id"])
        self.assertEqual(
            "legal-entity-se-1",
            packet["fortnox_draft_payload"]["entity_id"],
        )
        shadow_proposal = packet["shadow_ledger_comparison"]["accounting_proposal"]
        self.assertEqual("accounting-firm", shadow_proposal["client_id"])
        self.assertEqual("legal-entity-se-1", shadow_proposal["entity_id"])
        shadow_fortnox = packet["shadow_ledger_comparison"]["fortnox_payload"]
        self.assertEqual("accounting-firm", shadow_fortnox["client_id"])
        self.assertEqual("legal-entity-se-1", shadow_fortnox["entity_id"])

    def test_same_fixture_is_isolated_across_clients_in_one_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            first = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "Client-A",
                client_id="Client-A",
                entity_id="fixture-entity",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            second = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-a",
                client_id="client-a",
                entity_id="fixture-entity",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            intake_count = table_count(db_path, "intake_cases")
            document_count = table_count(db_path, "documents")

        self.assertNotEqual(first["case"]["case_id"], second["case"]["case_id"])
        self.assertEqual("Client-A", first["case"]["client_id"])
        self.assertEqual("client-a", second["case"]["client_id"])
        self.assertEqual("unique", second["duplicate_check"]["status"])
        self.assertEqual(2, intake_count)
        self.assertEqual(2, document_count)

    def test_same_client_entities_are_isolated_across_all_queue_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            entity_a = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "entity-a",
                client_id="shared-accounting-firm",
                entity_id="legal-entity-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            entity_b = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "entity-b",
                client_id="shared-accounting-firm",
                entity_id="legal-entity-b",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)

            self.assertNotEqual(entity_a["case"]["case_id"], entity_b["case"]["case_id"])
            self.assertEqual("unique", entity_b["duplicate_check"]["status"])
            for table_name, expected_count in {
                "intake_cases": 2,
                "documents": 2,
                "extracted_fields": 2,
                "accounting_proposals": 2,
                "policy_decisions": 2,
                "approval_packets": 2,
                "audit_events": 4,
            }.items():
                with self.subTest(table_name=table_name):
                    self.assertEqual(expected_count, table_count(db_path, table_name))
                    self.assertEqual(
                        {
                            ("shared-accounting-firm", "legal-entity-a"),
                            ("shared-accounting-firm", "legal-entity-b"),
                        },
                        table_identity_pairs(db_path, table_name),
                    )

    def test_queue_refuses_case_id_rebinding_to_another_entity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            entity_a = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                client_id="shared-accounting-firm",
                entity_id="legal-entity-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            entity_b = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                client_id="shared-accounting-firm",
                entity_id="legal-entity-b",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            entity_b["case"]["case_id"] = entity_a["case"]["case_id"]
            queue = LocalQueue(db_path)
            queue.store_pipeline_result(entity_a, Path(""))

            with self.assertRaises(Exception) as captured:
                queue.store_pipeline_result(entity_b, Path(""))
            self.assertIsInstance(captured.exception, QueueSchemaError)

            self.assertEqual(
                {("shared-accounting-firm", "legal-entity-a")},
                table_identity_pairs(db_path, "intake_cases"),
            )
            self.assertEqual(1, table_count(db_path, "documents"))

    def test_v01_unscoped_duplicate_fails_closed_without_leaking_legacy_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "legacy-queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            seed_v01_queue(db_path, fixture)

            packet = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-a",
                client_id="client-a",
                entity_id="entity-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)

            self.assertEqual(LOCAL_QUEUE_SCHEMA_VERSION, LocalQueue(db_path).schema_version())

        duplicate = packet["duplicate_check"]
        self.assertEqual("possible_duplicate", duplicate["status"])
        self.assertEqual("legacy_unscoped_review", duplicate["scope_status"])
        self.assertIsNone(duplicate["duplicate_of_case_id"])
        self.assertIsNone(duplicate["duplicate_source_path"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertNotIn("legacy-case", json.dumps(duplicate))
        self.assertNotIn("legacy/private/path", json.dumps(duplicate))

    def test_client_only_legacy_mapping_is_refused_without_entity_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "legacy-queue.sqlite"
            seed_v01_queue(db_path, FIXTURES / "01_normal_25_vat.json")

            with self.assertRaises(QueueSchemaError):
                LocalQueue(db_path).map_legacy_rows_to_client("client-a")

            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "SELECT client_id, entity_id, identity_scope_version FROM documents"
                ).fetchone()

        self.assertEqual((None, None, 1), row)

    def test_v2_migration_adds_entity_scope_without_assigning_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "v2-queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            seed_v02_queue(db_path, fixture)

            queue = LocalQueue(db_path)
            self.assertEqual(LOCAL_QUEUE_SCHEMA_VERSION, queue.schema_version())
            for table_name in (
                "intake_cases",
                "documents",
                "extracted_fields",
                "accounting_proposals",
                "policy_decisions",
                "approval_packets",
                "audit_events",
            ):
                with self.subTest(table_name=table_name):
                    self.assertTrue(
                        {"client_id", "entity_id", "identity_scope_version"}.issubset(
                            table_columns(db_path, table_name)
                        )
                    )
                    self.assertEqual({None}, table_entity_values(db_path, table_name))

            packet = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "entity-a",
                client_id="client-a",
                entity_id="entity-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)

        duplicate = packet["duplicate_check"]
        self.assertEqual("possible_duplicate", duplicate["status"])
        self.assertEqual("legacy_unscoped_review", duplicate["scope_status"])
        self.assertIsNone(duplicate["duplicate_of_case_id"])
        self.assertNotIn("legacy-case", json.dumps(duplicate))

    def test_explicit_v01_mapping_restores_exact_client_entity_match_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "legacy-queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            seed_v01_queue(db_path, fixture)
            queue = LocalQueue(db_path)

            try:
                mapped = queue.map_legacy_rows_to_entity(
                    client_id="client-a",
                    entity_id="entity-a",
                )
            except AttributeError as exc:
                self.fail(f"Explicit client/entity migration API is required: {exc}")
            self.assertEqual(1, mapped)
            client_b = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-b",
                client_id="client-b",
                entity_id="entity-b",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            other_entity = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "entity-other",
                client_id="client-a",
                entity_id="entity-other",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            client_a = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-a",
                client_id="client-a",
                entity_id="entity-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)

        self.assertEqual("unique", client_b["duplicate_check"]["status"])
        self.assertEqual("unique", other_entity["duplicate_check"]["status"])
        self.assertEqual("possible_duplicate", client_a["duplicate_check"]["status"])
        self.assertEqual("legacy-case", client_a["duplicate_check"]["duplicate_of_case_id"])

    def test_queue_refuses_unknown_newer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "future-queue.sqlite"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    f"PRAGMA user_version = {LOCAL_QUEUE_SCHEMA_VERSION + 1}"
                )
            with self.assertRaises(QueueSchemaError):
                LocalQueue(db_path).initialize()

    def test_cli_one_command_processes_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "queue.sqlite"
            output_dir = root / "packets"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "process-fixtures",
                    "--fixtures",
                    str(FIXTURES),
                    "--db",
                    str(db_path),
                    "--output",
                    str(output_dir),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("Processed 5 supplier invoice fixtures", result.stdout)

    def test_cli_fixture_run_accepts_explicit_client_and_entity_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "queue.sqlite"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "process-fixtures",
                    "--fixtures",
                    str(FIXTURES),
                    "--db",
                    str(db_path),
                    "--output",
                    str(root / "packets"),
                    "--client-id",
                    "accounting-firm",
                    "--entity-id",
                    "legal-entity-se-1",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                {("accounting-firm", "legal-entity-se-1")},
                table_identity_pairs(db_path, "approval_packets"),
            )


def by_scenario(packets: list[dict], scenario: str) -> dict:
    for packet in packets:
        if packet["case"]["fixture_name"] == scenario:
            return packet
    raise AssertionError(f"Missing packet for scenario {scenario}")


def flag_codes(packet: dict) -> set[str]:
    return {flag["code"] for flag in packet["risk"]["flags"]}


def table_count(db_path: Path, table_name: str) -> int:
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    return int(row[0])


def table_identity_pairs(db_path: Path, table_name: str) -> set[tuple[str, str]]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            f"SELECT DISTINCT client_id, entity_id FROM {table_name}"
        ).fetchall()
    return {(str(row[0]), str(row[1])) for row in rows}


def table_columns(db_path: Path, table_name: str) -> set[str]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def table_entity_values(db_path: Path, table_name: str) -> set[str | None]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(f"SELECT entity_id FROM {table_name}").fetchall()
    return {row[0] for row in rows}


def seed_v01_queue(db_path: Path, fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    extracted = extract_invoice_fields(fixture)
    scoped_signature = build_invoice_signature(
        extracted,
        client_id="client-a",
        entity_id="legacy-placeholder-entity",
    )
    legacy_signature = scoped_signature.split("|", 2)[2]
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            PRAGMA user_version = 1;
            PRAGMA foreign_keys = ON;
            CREATE TABLE intake_cases (
                case_id TEXT PRIMARY KEY,
                fixture_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE documents (
                doc_hash TEXT PRIMARY KEY,
                case_id TEXT NOT NULL UNIQUE REFERENCES intake_cases(case_id),
                source_path TEXT NOT NULL,
                invoice_signature TEXT NOT NULL,
                supplier_name TEXT,
                supplier_org_number TEXT,
                invoice_number TEXT,
                invoice_date TEXT,
                gross_amount TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO intake_cases (
                case_id, fixture_name, source_path, file_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-case",
                "legacy_fixture",
                "legacy/private/path",
                "legacy-file-hash",
                "approval_packet_ready",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents (
                doc_hash, case_id, source_path, invoice_signature,
                supplier_name, supplier_org_number, invoice_number,
                invoice_date, gross_amount, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-document-hash",
                "legacy-case",
                "legacy/private/path",
                legacy_signature,
                extracted.get("supplier_name"),
                extracted.get("supplier_org_number"),
                extracted.get("invoice_number"),
                extracted.get("invoice_date"),
                extracted["amounts"].get("gross"),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()


def seed_v02_queue(db_path: Path, fixture_path: Path) -> None:
    seed_v01_queue(db_path, fixture_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    extracted = extract_invoice_fields(fixture)
    current_signature = build_invoice_signature(
        extracted,
        client_id="client-a",
        entity_id="placeholder-entity",
    )
    signature_parts = current_signature.split("|")
    v2_signature = "|".join((signature_parts[0], *signature_parts[2:]))
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            ALTER TABLE intake_cases ADD COLUMN client_id TEXT;
            ALTER TABLE intake_cases
                ADD COLUMN identity_scope_version INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE documents ADD COLUMN client_id TEXT;
            ALTER TABLE documents
                ADD COLUMN identity_scope_version INTEGER NOT NULL DEFAULT 1;
            CREATE TABLE extracted_fields (
                case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE accounting_proposals (
                case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
                proposal_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE policy_decisions (
                case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
                decision_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE approval_packets (
                case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
                packet_json TEXT NOT NULL,
                packet_path TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT REFERENCES intake_cases(case_id),
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "UPDATE intake_cases SET client_id = ?, identity_scope_version = 2",
            ("client-a",),
        )
        connection.execute(
            """
            UPDATE documents
            SET client_id = ?, identity_scope_version = 2, invoice_signature = ?
            """,
            ("client-a", v2_signature),
        )
        for table_name, json_column in (
            ("extracted_fields", "payload_json"),
            ("accounting_proposals", "proposal_json"),
            ("policy_decisions", "decision_json"),
        ):
            connection.execute(
                f"INSERT INTO {table_name} (case_id, {json_column}, updated_at) "
                "VALUES (?, ?, ?)",
                ("legacy-case", "{}", "2026-01-01T00:00:00+00:00"),
            )
        connection.execute(
            """
            INSERT INTO approval_packets (
                case_id, packet_json, packet_path, status, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "legacy-case",
                "{}",
                "legacy/private/packet.json",
                "pending_human_review",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_events (case_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "legacy-case",
                "legacy.event",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()


if __name__ == "__main__":
    unittest.main()
