from __future__ import annotations

import unittest

from accounting_agent.agentic import (
    AgentBudget,
    EvidenceReference,
    InterfaceMode,
    SPECIALISTS,
    SpecialistId,
    build_agentic_work_plan,
    list_role_profiles,
)
from accounting_agent.erp import (
    COMPUTER_USE_BOUNDARY,
    DANGEROUS_CAPABILITIES,
    CapabilityMode,
    ErpCapability,
    ErpProvider,
    assert_fail_closed_registry,
    get_erp_profile,
    list_erp_profiles,
)
from accounting_agent.jurisdictions import (
    get_currency_spec,
    get_jurisdiction_pack,
    list_jurisdiction_packs,
)


class PlatformFoundationTests(unittest.TestCase):
    def test_sweden_pack_is_effective_dated_and_human_reviewed(self) -> None:
        pack = get_jurisdiction_pack("se-2026")

        self.assertEqual("SE", pack.country_code)
        self.assertEqual("SEK", pack.functional_currency)
        self.assertEqual("2026", pack.chart_version)
        self.assertEqual(7, pack.retention_years)
        self.assertEqual("SE", pack.storage_default_country)
        self.assertIn("SIE 4C", pack.interoperability_formats)
        self.assertIn("Peppol BIS Billing 3", pack.interoperability_formats)
        food_rule = next(rule for rule in pack.tax_rules if rule.rule_id == "se-food-vat-2026-04-01")
        self.assertEqual("2026-04-01", food_rule.effective_from)
        self.assertEqual(600, food_rule.rate_basis_points)
        self.assertTrue(food_rule.human_review_required)
        self.assertIn("restaurant", food_rule.scope_note)

    def test_international_core_makes_no_tax_compliance_claim(self) -> None:
        pack = get_jurisdiction_pack("international-core")

        self.assertEqual("schema_only", pack.compliance_status)
        self.assertEqual((), pack.tax_rules)
        self.assertIsNone(pack.functional_currency)
        self.assertIn("jurisdiction_pack_missing", pack.human_review_triggers)
        self.assertEqual(2, len(list_jurisdiction_packs()))

    def test_currency_minor_units_are_explicit(self) -> None:
        self.assertEqual(0, get_currency_spec("jpy").minor_units)
        self.assertEqual(2, get_currency_spec("SEK").minor_units)
        self.assertEqual(3, get_currency_spec("KWD").minor_units)
        self.assertEqual(3, get_currency_spec("BHD").minor_units)
        with self.assertRaises(ValueError):
            get_currency_spec("ZZZ")

    def test_all_provider_profiles_forbid_external_writes(self) -> None:
        assert_fail_closed_registry()
        self.assertEqual(set(ErpProvider), {profile.provider for profile in list_erp_profiles()})
        for profile in list_erp_profiles():
            for capability in DANGEROUS_CAPABILITIES:
                self.assertEqual(CapabilityMode.FORBIDDEN, profile.capability(capability).mode)

    def test_provider_profiles_exist_without_claiming_connections(self) -> None:
        self.assertEqual(
            "mocked_dry_run_only",
            get_erp_profile(ErpProvider.FORTNOX).connection_status,
        )
        for provider in (
            ErpProvider.NETSUITE,
            ErpProvider.ORACLE_FUSION,
            ErpProvider.SAP_S4HANA,
        ):
            profile = get_erp_profile(provider)
            self.assertEqual("manifest_only", profile.connection_status)
            self.assertEqual(
                CapabilityMode.DECLARED_NOT_CONNECTED,
                profile.capability(ErpCapability.READ_TRANSACTIONS).mode,
            )

    def test_computer_use_is_observation_only_and_stops_on_injection(self) -> None:
        self.assertTrue(COMPUTER_USE_BOUNDARY.requires_active_supervision)
        self.assertFalse(COMPUTER_USE_BOUNDARY.credential_access_allowed)
        self.assertIn("prompt_injection_indicator", COMPUTER_USE_BOUNDARY.stop_conditions)
        self.assertIn("type_into_remote_erp_form", COMPUTER_USE_BOUNDARY.forbidden_tasks)

    def test_bounded_plan_has_parallel_specialists_and_human_gate(self) -> None:
        plan = build_agentic_work_plan(
            entity_id="client-a",
            jurisdiction_pack="se-2026",
            provider=ErpProvider.NETSUITE,
            role_id="financial_controller",
            evidence_refs=(
                EvidenceReference("client-a", "evidence://invoice/1"),
                EvidenceReference("client-a", "evidence://bank/1"),
            ),
        )

        self.assertEqual(InterfaceMode.EXPERT, plan.interface_mode)
        self.assertTrue(any(stage.parallel for stage in plan.stages))
        self.assertEqual("human_decision", plan.stages[-1].stage_id)
        self.assertTrue(plan.stages[-1].requires_human)
        self.assertNotIn("post", plan.permission_ceiling)
        self.assertIn("post", plan.blocked_capabilities)
        self.assertIn("policy_disagreement", plan.stop_conditions)

    def test_specialists_cannot_self_approve_or_elevate(self) -> None:
        self.assertEqual(set(SpecialistId), set(SPECIALISTS))
        for specialist in SPECIALISTS.values():
            self.assertFalse(specialist.can_approve)
            self.assertFalse(specialist.can_elevate_permissions)
        self.assertTrue(all(not role.can_approve for role in list_role_profiles()))

    def test_plan_requires_entity_scoped_evidence_and_enforces_budget(self) -> None:
        with self.assertRaises(ValueError):
            build_agentic_work_plan(
                entity_id="",
                evidence_refs=(EvidenceReference("client-a", "evidence://1"),),
            )
        with self.assertRaises(ValueError):
            build_agentic_work_plan(entity_id="client-a", evidence_refs=())
        with self.assertRaises(TypeError):
            build_agentic_work_plan(  # type: ignore[arg-type]
                entity_id="client-a",
                evidence_refs=("evidence://invoice/1",),
            )
        with self.assertRaises(ValueError):
            build_agentic_work_plan(
                entity_id="client-a",
                evidence_refs=(EvidenceReference("client-b", "evidence://invoice/1"),),
            )
        with self.assertRaises(ValueError):
            build_agentic_work_plan(
                entity_id="client-a",
                evidence_refs=(
                    EvidenceReference("client-a", "evidence://invoice/1"),
                    EvidenceReference("client-a", "evidence://invoice/2"),
                ),
                budget=AgentBudget(max_evidence_items=1),
            )
        with self.assertRaises(ValueError):
            AgentBudget(max_specialists=9)

    def test_evidence_references_validate_integrity_metadata(self) -> None:
        reference = EvidenceReference(
            "client-a",
            "evidence://invoice/1",
            "A" * 64,
        )
        self.assertEqual("a" * 64, reference.sha256)
        with self.assertRaises(ValueError):
            EvidenceReference("client-a", "relative/path")
        with self.assertRaises(ValueError):
            EvidenceReference("client-a", "evidence://user:secret@invoice/1")
        with self.assertRaises(ValueError):
            EvidenceReference("client-a", "evidence://invoice/1", "not-a-hash")


if __name__ == "__main__":
    unittest.main()
