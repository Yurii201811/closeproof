from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from inspect import Parameter, signature

import accounting_agent
import accounting_agent.connector_contract as connector_contract

from accounting_agent.connector_contract import (
    CONNECTOR_MANIFESTS,
    WRITE_CAPABILITIES,
    AuthReference,
    CapabilityDeclaration,
    CapabilityMode,
    ConnectorAdapter,
    ConnectorBinding,
    ConnectorCapability,
    ConnectorContractError,
    ConnectorEnvironment,
    ConnectorGuard,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorPage,
    ConnectorReadRequest,
    ConnectorWriteForbidden,
    HealthStatus,
    PaginationContract,
    PaginationMode,
    ProviderLifecycle,
    RetryMetadata,
    assert_v1_preview_registry_safe,
    evaluate_connector_conformance,
    get_connector_manifest,
    list_connector_manifests,
    raw_snapshot_sha256,
    read_connector_page_guarded,
    require_guarded_read_request,
)


class _ConformingFixtureAdapter:
    def __init__(self, provider_id: str, binding: ConnectorBinding) -> None:
        self.provider_id = provider_id
        self.binding = binding
        self.manifest = get_connector_manifest(provider_id)
        self.health_calls = 0
        self.read_calls = 0

    def check_health(self) -> ConnectorHealth:
        self.health_calls += 1
        return ConnectorHealth(
            provider_id=self.provider_id,
            binding=self.binding,
            status=HealthStatus.HEALTHY,
            checked_at=datetime.now(UTC),
            detail_code="fixture_ok",
        )

    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        self.read_calls += 1
        raw = b'{"records": []}'
        return ConnectorPage(
            provider_id=self.provider_id,
            binding=request.binding,
            resource=request.resource,
            schema_version=self.manifest.schema_version,
            mapping_version=self.manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(raw),
            records=(),
            source_cursor=request.cursor,
            next_cursor=None,
            retry=RetryMetadata(attempt_number=1, max_attempts=3, transient=False),
        )


class _AdversarialPageAdapter(_ConformingFixtureAdapter):
    def __init__(
        self,
        adapter_provider_id: str,
        adapter_binding: ConnectorBinding,
        **page_changes: object,
    ) -> None:
        super().__init__(adapter_provider_id, adapter_binding)
        self.page_changes = page_changes

    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        valid_page = super().read_page(request)
        return replace(valid_page, **self.page_changes)


class _WrongReturnTypeAdapter(_ConformingFixtureAdapter):
    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        self.read_calls += 1
        return object()  # type: ignore[return-value]


class _BindingDriftAdapter(_ConformingFixtureAdapter):
    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        page = super().read_page(request)
        self.binding = ConnectorBinding(
            "tenant-switched",
            "company-switched",
            ConnectorEnvironment.SANDBOX,
        )
        return page


class _EnvironmentDriftAdapter(_ConformingFixtureAdapter):
    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        page = super().read_page(request)
        self.binding = replace(
            self.binding,
            environment=ConnectorEnvironment.PRODUCTION,
        )
        return page


class ConnectorRegistryTests(unittest.TestCase):
    def test_v1_registry_declares_required_provider_manifests(self) -> None:
        self.assertEqual(
            {"fortnox", "netsuite", "oracle_fusion", "sap_s4hana", "odoo", "sie", "csv"},
            set(CONNECTOR_MANIFESTS),
        )
        self.assertEqual(
            ProviderLifecycle.GUARDED_READ_ONLY,
            get_connector_manifest("fortnox").lifecycle,
        )
        for provider_id in (
            "netsuite",
            "oracle_fusion",
            "sap_s4hana",
            "odoo",
            "sie",
            "csv",
        ):
            self.assertEqual(
                ProviderLifecycle.DECLARATION_ONLY,
                get_connector_manifest(provider_id).lifecycle,
            )
        self.assertEqual(7, len(list_connector_manifests()))

    def test_every_external_write_is_forbidden_for_every_provider(self) -> None:
        assert_v1_preview_registry_safe()

        for manifest in list_connector_manifests():
            self.assertTrue(manifest.guard.dry_run_only)
            self.assertTrue(manifest.guard.read_only)
            for capability in WRITE_CAPABILITIES:
                self.assertEqual(
                    CapabilityMode.FORBIDDEN,
                    manifest.capability(capability).mode,
                    f"{manifest.provider_id}/{capability.value}",
                )
                with self.assertRaises(ConnectorWriteForbidden):
                    manifest.require_capability(capability)

    def test_manifest_serialization_is_declarative_and_contains_no_auth_material(self) -> None:
        payload = get_connector_manifest("netsuite").to_dict()

        self.assertEqual("netsuite", payload["provider_id"])
        self.assertNotIn("auth_reference", payload)
        self.assertNotIn("access_token", str(payload).lower())
        self.assertNotIn("client_secret", str(payload).lower())


class ConnectorBindingTests(unittest.TestCase):
    def test_contract_exposes_closed_environment_vocabulary(self) -> None:
        self.assertTrue(
            hasattr(connector_contract, "ConnectorEnvironment"),
            "connector bindings need an explicit closed environment vocabulary",
        )

    def test_package_exports_connector_binding_and_environment(self) -> None:
        self.assertIs(ConnectorBinding, getattr(accounting_agent, "ConnectorBinding", None))
        self.assertIs(
            ConnectorEnvironment,
            getattr(accounting_agent, "ConnectorEnvironment", None),
        )

    def test_binding_requires_an_explicit_environment(self) -> None:
        parameters = signature(ConnectorBinding).parameters

        self.assertIn("environment", parameters)
        self.assertIs(Parameter.empty, parameters["environment"].default)

    def test_binding_keeps_tenant_company_and_opaque_auth_reference_together(self) -> None:
        binding = ConnectorBinding(
            tenant_id="tenant-se-01",
            company_id="company-556677",
            environment=ConnectorEnvironment.SANDBOX,
            auth_reference=AuthReference("vault-ref:fortnox/company-556677"),
        )

        self.assertEqual("tenant-se-01", binding.tenant_id)
        self.assertEqual("company-556677", binding.company_id)
        self.assertIs(ConnectorEnvironment.SANDBOX, binding.environment)
        self.assertEqual("vault-ref:fortnox/company-556677", binding.auth_reference.reference_id)
        self.assertEqual(
            {
                "tenant_id": "tenant-se-01",
                "company_id": "company-556677",
                "environment": "sandbox",
                "auth_reference": "vault-ref:fortnox/company-556677",
            },
            binding.to_dict(),
        )

    def test_binding_normalizes_a_valid_environment_value_to_the_closed_enum(self) -> None:
        binding = ConnectorBinding(
            "tenant-a",
            "company-a",
            "sandbox",  # type: ignore[arg-type]
        )

        self.assertIs(ConnectorEnvironment.SANDBOX, binding.environment)

    def test_binding_rejects_unknown_or_missing_environments(self) -> None:
        for environment in ("prod", "", None, 1):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(
                    ConnectorContractError,
                    "ConnectorEnvironment",
                ):
                    ConnectorBinding(
                        "tenant-a",
                        "company-a",
                        environment,  # type: ignore[arg-type]
                    )

    def test_binding_environment_is_immutable(self) -> None:
        binding = ConnectorBinding(
            "tenant-a",
            "company-a",
            ConnectorEnvironment.SANDBOX,
        )

        with self.assertRaises(FrozenInstanceError):
            binding.environment = ConnectorEnvironment.PRODUCTION  # type: ignore[misc]

    def test_auth_reference_rejects_obvious_inline_secrets(self) -> None:
        for unsafe in (
            "Bearer live-token",
            "access_token=live-token",
            "client_secret=live-secret",
            "password=do-not-store",
            "-----BEGIN PRIVATE KEY-----",
            "sk-proj-this-is-a-secret-not-a-reference",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ConnectorContractError):
                    AuthReference(unsafe)

    def test_binding_rejects_blank_or_unsafe_identifiers(self) -> None:
        for tenant_id, company_id in (("", "company"), ("tenant", ""), ("tenant\n2", "company")):
            with self.subTest(tenant_id=tenant_id, company_id=company_id):
                with self.assertRaises(ConnectorContractError):
                    ConnectorBinding(tenant_id, company_id, ConnectorEnvironment.SANDBOX)


class ConnectorDataEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = ConnectorBinding(
            "tenant-a",
            "company-a",
            ConnectorEnvironment.SANDBOX,
        )
        self.manifest = get_connector_manifest("fortnox")

    def test_page_carries_source_integrity_versions_cursor_and_retry_metadata(self) -> None:
        raw = b'{"Accounts":[{"Number":2440}]}'
        page = ConnectorPage(
            provider_id="fortnox",
            binding=self.binding,
            resource="accounts",
            schema_version=self.manifest.schema_version,
            mapping_version=self.manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(raw),
            records=({"Number": 2440},),
            source_cursor="page:1",
            next_cursor="page:2",
            retry=RetryMetadata(
                attempt_number=2,
                max_attempts=4,
                transient=True,
                retry_after_seconds=1.5,
            ),
        )

        self.assertEqual(64, len(page.raw_snapshot_hash))
        self.assertEqual("page:2", page.next_cursor)
        self.assertEqual("accounts", page.resource)
        self.assertEqual(2, page.retry.attempt_number)
        self.assertEqual("1", page.schema_version)
        self.assertEqual("bas-v1", page.mapping_version)

    def test_page_rejects_invalid_snapshot_hash(self) -> None:
        with self.assertRaises(ConnectorContractError):
            ConnectorPage(
                provider_id="fortnox",
                binding=self.binding,
                resource="accounts",
                schema_version="1",
                mapping_version="bas-v1",
                raw_snapshot_hash="not-a-sha256",
                records=(),
                source_cursor=None,
                next_cursor=None,
                retry=RetryMetadata(1, 1, False),
            )

    def test_page_rejects_non_tuple_or_non_mapping_records(self) -> None:
        raw_hash = raw_snapshot_sha256(b"[]")
        for records in ([], ("not-a-record",)):
            with self.subTest(records=records):
                with self.assertRaisesRegex(ConnectorContractError, "tuple of mappings"):
                    ConnectorPage(
                        provider_id="fortnox",
                        binding=self.binding,
                        resource="accounts",
                        schema_version="1",
                        mapping_version="bas-v1",
                        raw_snapshot_hash=raw_hash,
                        records=records,  # type: ignore[arg-type]
                        source_cursor=None,
                        next_cursor=None,
                        retry=RetryMetadata(1, 1, False),
                    )

    def test_retry_metadata_is_bounded_and_explicit(self) -> None:
        for retry in (
            (0, 3, False, None),
            (4, 3, True, 1.0),
            (1, 0, False, None),
            (1, 3, True, -0.1),
        ):
            with self.subTest(retry=retry):
                with self.assertRaises(ConnectorContractError):
                    RetryMetadata(*retry)
        with self.assertRaises(ConnectorContractError):
            RetryMetadata(1, 3, "yes")  # type: ignore[arg-type]

    def test_pagination_contract_requires_coherent_cursor_metadata(self) -> None:
        cursor = PaginationContract(
            mode=PaginationMode.CURSOR,
            cursor_parameter="cursor",
            next_cursor_field="next_cursor",
            max_page_size=1000,
        )
        self.assertTrue(cursor.uses_cursor)

        with self.assertRaises(ConnectorContractError):
            PaginationContract(mode=PaginationMode.CURSOR, max_page_size=100)
        with self.assertRaises(ConnectorContractError):
            PaginationContract(
                mode=PaginationMode.NONE,
                cursor_parameter="cursor",
                max_page_size=100,
            )
        with self.assertRaises(ConnectorContractError):
            PaginationContract(  # type: ignore[arg-type]
                mode=PaginationMode.NONE,
                max_page_size=1.5,
            )


class ConnectorGuardTests(unittest.TestCase):
    def test_guard_forbids_write_even_if_a_custom_manifest_declares_it(self) -> None:
        base = get_connector_manifest("fortnox")
        declarations = tuple(
            CapabilityDeclaration(item.capability, CapabilityMode.READ_ONLY)
            if item.capability is ConnectorCapability.POST_JOURNAL
            else item
            for item in base.capabilities
        )
        unsafe = replace(base, capabilities=declarations)

        with self.assertRaises(ConnectorWriteForbidden):
            unsafe.require_capability(ConnectorCapability.POST_JOURNAL)

    def test_guard_defaults_are_fail_closed(self) -> None:
        guard = ConnectorGuard()

        self.assertTrue(guard.dry_run_only)
        self.assertTrue(guard.read_only)
        with self.assertRaises(ConnectorWriteForbidden):
            guard.require(ConnectorCapability.START_PAYMENT)


class ConnectorAdapterConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = ConnectorBinding(
            "tenant-a",
            "company-a",
            ConnectorEnvironment.SANDBOX,
        )
        self.adapter = _ConformingFixtureAdapter("fortnox", self.binding)

    def test_fixture_adapter_satisfies_protocol(self) -> None:
        self.assertIsInstance(self.adapter, ConnectorAdapter)

    def test_evaluator_is_static_and_does_not_trigger_external_or_fixture_calls(self) -> None:
        report = evaluate_connector_conformance(self.adapter)

        self.assertTrue(report.conformant, report.issues)
        self.assertEqual((), report.issues)
        self.assertEqual(0, self.adapter.health_calls)
        self.assertEqual(0, self.adapter.read_calls)

    def test_read_guard_binds_scope_capability_cursor_and_page_limit(self) -> None:
        valid = ConnectorReadRequest(
            self.binding,
            resource="transactions",
            cursor="page:1",
            page_size=100,
        )
        require_guarded_read_request(self.adapter, valid)

        invalid_requests = (
            ConnectorReadRequest(
                ConnectorBinding(
                    "tenant-other",
                    "company-other",
                    ConnectorEnvironment.SANDBOX,
                ),
                resource="transactions",
            ),
            ConnectorReadRequest(
                self.binding,
                resource="transactions",
                page_size=self.adapter.manifest.pagination.max_page_size + 1,
            ),
        )
        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaises(ConnectorContractError):
                    require_guarded_read_request(self.adapter, request)

        local_adapter = _ConformingFixtureAdapter("sie", self.binding)
        with self.assertRaises(ConnectorContractError):
            require_guarded_read_request(
                local_adapter,
                ConnectorReadRequest(
                    self.binding,
                    resource="transactions",
                    cursor="not-allowed",
                ),
            )

    def test_guarded_read_gateway_calls_the_adapter_once_and_returns_its_page(self) -> None:
        request = ConnectorReadRequest(
            self.binding,
            resource="transactions",
            cursor="page:1",
            page_size=self.adapter.manifest.pagination.max_page_size,
        )

        page = read_connector_page_guarded(self.adapter, request)

        self.assertEqual(1, self.adapter.read_calls)
        self.assertEqual("fortnox", page.provider_id)
        self.assertEqual(self.binding, page.binding)
        self.assertEqual("page:1", page.source_cursor)

    def test_guarded_read_rejects_request_environment_mismatch_before_adapter_call(
        self,
    ) -> None:
        production_binding = replace(
            self.binding,
            environment=ConnectorEnvironment.PRODUCTION,
        )

        with self.assertRaisesRegex(ConnectorContractError, "environment"):
            read_connector_page_guarded(
                self.adapter,
                ConnectorReadRequest(production_binding, resource="transactions"),
            )

        self.assertEqual(0, self.adapter.read_calls)

    def test_guarded_read_gateway_rejects_invalid_preflight_without_calling_adapter(
        self,
    ) -> None:
        wrong_provider = _ConformingFixtureAdapter("fortnox", self.binding)
        wrong_provider.provider_id = "netsuite"
        wrong_binding = _ConformingFixtureAdapter("fortnox", self.binding)
        excessive_page = _ConformingFixtureAdapter("fortnox", self.binding)
        declaration_only = _ConformingFixtureAdapter("netsuite", self.binding)
        non_read_capability = _ConformingFixtureAdapter("fortnox", self.binding)
        write_capability = _ConformingFixtureAdapter("fortnox", self.binding)
        blank_cursor = _ConformingFixtureAdapter("fortnox", self.binding)
        cases = (
            (
                wrong_provider,
                ConnectorReadRequest(self.binding, resource="transactions"),
                ConnectorCapability.READ_TRANSACTIONS,
                ConnectorContractError,
            ),
            (
                wrong_binding,
                ConnectorReadRequest(
                    ConnectorBinding(
                        "tenant-other",
                        "company-other",
                        ConnectorEnvironment.SANDBOX,
                    ),
                    resource="transactions",
                ),
                ConnectorCapability.READ_TRANSACTIONS,
                ConnectorContractError,
            ),
            (
                excessive_page,
                ConnectorReadRequest(
                    self.binding,
                    resource="transactions",
                    page_size=excessive_page.manifest.pagination.max_page_size + 1,
                ),
                ConnectorCapability.READ_TRANSACTIONS,
                ConnectorContractError,
            ),
            (
                declaration_only,
                ConnectorReadRequest(self.binding, resource="transactions"),
                ConnectorCapability.READ_TRANSACTIONS,
                ConnectorContractError,
            ),
            (
                non_read_capability,
                ConnectorReadRequest(self.binding, resource="transactions"),
                ConnectorCapability.IMPORT_LOCAL,
                ConnectorContractError,
            ),
            (
                write_capability,
                ConnectorReadRequest(self.binding, resource="transactions"),
                ConnectorCapability.POST_JOURNAL,
                ConnectorWriteForbidden,
            ),
            (
                blank_cursor,
                ConnectorReadRequest(
                    self.binding,
                    resource="transactions",
                    cursor="   ",
                ),
                ConnectorCapability.READ_TRANSACTIONS,
                ConnectorContractError,
            ),
        )

        for adapter, request, capability, expected_error in cases:
            with self.subTest(
                provider=adapter.provider_id,
                capability=capability,
                page_size=request.page_size,
            ):
                with self.assertRaises(expected_error):
                    read_connector_page_guarded(
                        adapter,
                        request,
                        capability=capability,
                    )
                self.assertEqual(0, adapter.read_calls)

    def test_guarded_read_gateway_rejects_adversarial_returned_pages(self) -> None:
        request = ConnectorReadRequest(
            self.binding,
            resource="transactions",
            cursor="page:1",
        )
        cases = (
            (
                "provider",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    provider_id="netsuite",
                ),
            ),
            (
                "binding",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    binding=ConnectorBinding(
                        "tenant-other",
                        "company-other",
                        ConnectorEnvironment.SANDBOX,
                    ),
                ),
            ),
            (
                "resource",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    resource="accounts",
                ),
            ),
            (
                "schema",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    schema_version="99",
                ),
            ),
            (
                "mapping",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    mapping_version="other-map",
                ),
            ),
            (
                "source_cursor",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    source_cursor="page:other",
                ),
            ),
            (
                "too_many_records",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    records=tuple({"id": index} for index in range(101)),
                ),
            ),
            (
                "blank_next_cursor",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    next_cursor="",
                ),
            ),
            (
                "non_advancing_cursor",
                _AdversarialPageAdapter(
                    "fortnox",
                    self.binding,
                    next_cursor="page:1",
                ),
            ),
        )

        for label, adapter in cases:
            with self.subTest(label=label):
                with self.assertRaises(ConnectorContractError):
                    read_connector_page_guarded(adapter, request)
                self.assertEqual(1, adapter.read_calls)

    def test_guarded_read_gateway_rejects_invalid_return_type_and_none_cursor(self) -> None:
        wrong_type = _WrongReturnTypeAdapter("fortnox", self.binding)
        with self.assertRaises(ConnectorContractError):
            read_connector_page_guarded(
                wrong_type,
                ConnectorReadRequest(self.binding, resource="transactions"),
            )
        self.assertEqual(1, wrong_type.read_calls)

        unexpected_cursor = _AdversarialPageAdapter(
            "fortnox",
            self.binding,
            next_cursor="unexpected",
        )
        unexpected_cursor.manifest = replace(
            unexpected_cursor.manifest,
            pagination=PaginationContract(PaginationMode.NONE),
        )
        with self.assertRaises(ConnectorContractError):
            read_connector_page_guarded(
                unexpected_cursor,
                ConnectorReadRequest(self.binding, resource="transactions"),
            )
        self.assertEqual(1, unexpected_cursor.read_calls)

    def test_guarded_read_gateway_rejects_adapter_scope_drift_during_read(self) -> None:
        adapter = _BindingDriftAdapter("fortnox", self.binding)

        with self.assertRaises(ConnectorContractError):
            read_connector_page_guarded(
                adapter,
                ConnectorReadRequest(self.binding, resource="transactions"),
            )

        self.assertEqual(1, adapter.read_calls)

    def test_guarded_read_gateway_rejects_environment_drift_during_read(self) -> None:
        adapter = _EnvironmentDriftAdapter("fortnox", self.binding)

        with self.assertRaisesRegex(ConnectorContractError, "environment"):
            read_connector_page_guarded(
                adapter,
                ConnectorReadRequest(self.binding, resource="transactions"),
            )

        self.assertEqual(1, adapter.read_calls)

    def test_guarded_read_gateway_rejects_returned_page_environment_mismatch(
        self,
    ) -> None:
        production_binding = replace(
            self.binding,
            environment=ConnectorEnvironment.PRODUCTION,
        )
        adapter = _AdversarialPageAdapter(
            "fortnox",
            self.binding,
            binding=production_binding,
        )

        with self.assertRaisesRegex(ConnectorContractError, "environment"):
            read_connector_page_guarded(
                adapter,
                ConnectorReadRequest(self.binding, resource="transactions"),
            )

        self.assertEqual(1, adapter.read_calls)

    def test_evaluator_accepts_matching_health_and_sample_page(self) -> None:
        health = ConnectorHealth(
            provider_id="fortnox",
            binding=self.binding,
            status=HealthStatus.HEALTHY,
            checked_at=datetime.now(UTC),
            detail_code="fixture_ok",
        )
        page = self.adapter.read_page(
            ConnectorReadRequest(self.binding, resource="accounts", cursor="page:1", page_size=50)
        )

        report = evaluate_connector_conformance(self.adapter, health=health, sample_page=page)

        self.assertTrue(report.conformant, report.issues)

    def test_evaluator_reports_provider_binding_and_version_mismatches(self) -> None:
        raw = b'{"records": []}'
        page = ConnectorPage(
            provider_id="netsuite",
            binding=ConnectorBinding(
                "tenant-other",
                "company-other",
                ConnectorEnvironment.SANDBOX,
            ),
            resource="accounts",
            schema_version="99",
            mapping_version="other-map",
            raw_snapshot_hash=raw_snapshot_sha256(raw),
            records=(),
            source_cursor=None,
            next_cursor=None,
            retry=RetryMetadata(1, 1, False),
        )

        report = evaluate_connector_conformance(self.adapter, sample_page=page)

        self.assertFalse(report.conformant)
        self.assertEqual(
            {
                "page_provider_mismatch",
                "page_binding_mismatch",
                "schema_version_mismatch",
                "mapping_version_mismatch",
            },
            set(report.issue_codes),
        )

    def test_health_timestamp_must_be_timezone_aware(self) -> None:
        with self.assertRaises(ConnectorContractError):
            ConnectorHealth(
                provider_id="fortnox",
                binding=self.binding,
                status=HealthStatus.HEALTHY,
                checked_at=datetime(2026, 7, 10, 12, 0),
                detail_code="invalid_time",
            )
        with self.assertRaises(ConnectorContractError):
            ConnectorHealth(
                provider_id="fortnox",
                binding=self.binding,
                status=HealthStatus.HEALTHY,
                checked_at="2026-07-10T12:00:00Z",  # type: ignore[arg-type]
                detail_code="invalid_type",
            )


if __name__ == "__main__":
    unittest.main()
