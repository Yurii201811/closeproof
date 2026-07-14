"""Provider-neutral capability declarations with a fail-closed write boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ErpProvider(str, Enum):
    FORTNOX = "fortnox"
    NETSUITE = "netsuite"
    ORACLE_FUSION = "oracle_fusion"
    SAP_S4HANA = "sap_s4hana"
    GENERIC_EXCHANGE = "generic_exchange"
    SUPERVISED_COMPUTER_USE = "supervised_computer_use"


class ErpCapability(str, Enum):
    DISCOVER_SCHEMA = "discover_schema"
    DISCOVER_CAPABILITIES = "discover_capabilities"
    READ_MASTER_DATA = "read_master_data"
    READ_TRANSACTIONS = "read_transactions"
    READ_PERIOD_LOCKS = "read_period_locks"
    IMPORT_STAGED = "import_staged"
    EXPORT_RAW = "export_raw"
    VALIDATE_LOCAL = "validate_local"
    PREPARE_LOCAL_DRAFT = "prepare_local_draft"
    SIMULATE_LOCAL = "simulate_local"
    CREATE_EXTERNAL_DRAFT = "create_external_draft"
    POST = "post"
    APPROVE = "approve"
    SEND = "send"
    PAY = "pay"
    FILE_TAX = "file_tax"
    DELETE = "delete"
    CHANGE_SETTINGS = "change_settings"


class CapabilityMode(str, Enum):
    LOCAL_ONLY = "local_only"
    GUARDED_READ_ONLY = "guarded_read_only"
    DECLARED_NOT_CONNECTED = "declared_not_connected"
    FORBIDDEN = "forbidden"


DANGEROUS_CAPABILITIES = (
    ErpCapability.CREATE_EXTERNAL_DRAFT,
    ErpCapability.POST,
    ErpCapability.APPROVE,
    ErpCapability.SEND,
    ErpCapability.PAY,
    ErpCapability.FILE_TAX,
    ErpCapability.DELETE,
    ErpCapability.CHANGE_SETTINGS,
)


@dataclass(frozen=True)
class CapabilityDeclaration:
    capability: ErpCapability
    mode: CapabilityMode
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability.value,
            "mode": self.mode.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ErpProfile:
    provider: ErpProvider
    display_name: str
    transport: str
    connection_status: str
    capabilities: tuple[CapabilityDeclaration, ...]
    source_urls: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def capability(self, capability: ErpCapability) -> CapabilityDeclaration:
        for declaration in self.capabilities:
            if declaration.capability is capability:
                return declaration
        return CapabilityDeclaration(
            capability,
            CapabilityMode.FORBIDDEN,
            "Unknown or undeclared capabilities fail closed.",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "display_name": self.display_name,
            "transport": self.transport,
            "connection_status": self.connection_status,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "source_urls": list(self.source_urls),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ComputerUseBoundary:
    status: str
    allowed_tasks: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    forbidden_tasks: tuple[str, ...]
    requires_active_supervision: bool = True
    credential_access_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _declarations(
    *,
    read_mode: CapabilityMode,
    local_import: bool = False,
    observation_only: bool = False,
) -> tuple[CapabilityDeclaration, ...]:
    local_reason = "Runs on local evidence only; it grants no provider authority."
    declared_reason = "Profile declared, but no connector or credential is configured."
    read_reason = (
        "Read-only capability requires a separately approved least-privilege adapter."
        if read_mode is CapabilityMode.GUARDED_READ_ONLY
        else declared_reason
    )
    modes: dict[ErpCapability, tuple[CapabilityMode, str]] = {
        ErpCapability.DISCOVER_SCHEMA: (CapabilityMode.LOCAL_ONLY, local_reason),
        ErpCapability.DISCOVER_CAPABILITIES: (CapabilityMode.LOCAL_ONLY, local_reason),
        ErpCapability.READ_MASTER_DATA: (read_mode, read_reason),
        ErpCapability.READ_TRANSACTIONS: (read_mode, read_reason),
        ErpCapability.READ_PERIOD_LOCKS: (read_mode, read_reason),
        ErpCapability.IMPORT_STAGED: (
            CapabilityMode.LOCAL_ONLY if local_import else CapabilityMode.DECLARED_NOT_CONNECTED,
            local_reason if local_import else declared_reason,
        ),
        ErpCapability.EXPORT_RAW: (CapabilityMode.LOCAL_ONLY, local_reason),
        ErpCapability.VALIDATE_LOCAL: (CapabilityMode.LOCAL_ONLY, local_reason),
        ErpCapability.PREPARE_LOCAL_DRAFT: (CapabilityMode.LOCAL_ONLY, local_reason),
        ErpCapability.SIMULATE_LOCAL: (CapabilityMode.LOCAL_ONLY, local_reason),
    }
    if observation_only:
        for capability in tuple(modes):
            if capability not in {
                ErpCapability.DISCOVER_CAPABILITIES,
                ErpCapability.EXPORT_RAW,
                ErpCapability.VALIDATE_LOCAL,
            }:
                modes[capability] = (
                    CapabilityMode.FORBIDDEN,
                    "Computer use is limited to supervised observation and evidence capture.",
                )
    for capability in DANGEROUS_CAPABILITIES:
        modes[capability] = (
            CapabilityMode.FORBIDDEN,
            "External writes and consequential accounting actions are forbidden in this phase.",
        )
    return tuple(
        CapabilityDeclaration(capability, *modes[capability])
        for capability in ErpCapability
    )


ERP_PROFILES: dict[ErpProvider, ErpProfile] = {
    ErpProvider.FORTNOX: ErpProfile(
        ErpProvider.FORTNOX,
        "Fortnox",
        "REST / OAuth2",
        "mocked_dry_run_only",
        _declarations(read_mode=CapabilityMode.GUARDED_READ_ONLY),
        ("https://apps.fortnox.se/apidocs",),
        ("The existing adapter may shape payloads locally; external writes are quarantined.",),
    ),
    ErpProvider.NETSUITE: ErpProfile(
        ErpProvider.NETSUITE,
        "Oracle NetSuite",
        "REST / SuiteQL / OAuth2",
        "manifest_only",
        _declarations(read_mode=CapabilityMode.DECLARED_NOT_CONNECTED),
        (
            "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_157769826287.html",
            "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_156257799794.html",
        ),
    ),
    ErpProvider.ORACLE_FUSION: ErpProfile(
        ErpProvider.ORACLE_FUSION,
        "Oracle Fusion Cloud Financials",
        "Versioned Financials REST",
        "manifest_only",
        _declarations(read_mode=CapabilityMode.DECLARED_NOT_CONNECTED),
        ("https://docs.oracle.com/en/cloud/saas/financials/26a/farfa/api-invoices.html",),
    ),
    ErpProvider.SAP_S4HANA: ErpProfile(
        ErpProvider.SAP_S4HANA,
        "SAP S/4HANA Cloud",
        "OData / SOAP services",
        "manifest_only",
        _declarations(read_mode=CapabilityMode.DECLARED_NOT_CONNECTED),
        (
            "https://help.sap.com/docs/SAP_S4HANA_CLOUD/"
            "b978f98fc5884ff2aeb10c8fdeb8a43b/f5c8d0579212c525e10000000a4450e5.html",
        ),
    ),
    ErpProvider.GENERIC_EXCHANGE: ErpProfile(
        ErpProvider.GENERIC_EXCHANGE,
        "Generic accounting exchange",
        "Local CSV / JSON / SIE / Peppol",
        "local_fixture_path",
        _declarations(read_mode=CapabilityMode.LOCAL_ONLY, local_import=True),
        (),
    ),
    ErpProvider.SUPERVISED_COMPUTER_USE: ErpProfile(
        ErpProvider.SUPERVISED_COMPUTER_USE,
        "Supervised computer use",
        "Visible user interface",
        "observation_only_fallback",
        _declarations(
            read_mode=CapabilityMode.FORBIDDEN,
            observation_only=True,
        ),
        (
            "https://openai.com/index/computer-using-agent/",
            "https://openai.com/safety/prompt-injections/",
        ),
    ),
}


COMPUTER_USE_BOUNDARY = ComputerUseBoundary(
    status="observation_and_evidence_only",
    allowed_tasks=(
        "local_app_ui_testing",
        "whitelisted_erp_observation",
        "screenshot_and_evidence_capture",
        "human_readable_action_plan_preparation",
    ),
    stop_conditions=(
        "credential_request",
        "prompt_injection_indicator",
        "unexpected_domain_or_navigation",
        "submit_or_autosave_risk",
        "task_scope_or_budget_exceeded",
    ),
    forbidden_tasks=(
        "type_into_remote_erp_form",
        "submit_post_approve_send_pay_file_delete_or_change_settings",
        "tax_filing",
        "client_communication",
        "handle_credentials_or_secrets",
    ),
)


def list_erp_profiles() -> tuple[ErpProfile, ...]:
    return tuple(ERP_PROFILES[key] for key in ErpProvider)


def get_erp_profile(provider: ErpProvider | str) -> ErpProfile:
    key = ErpProvider(provider)
    return ERP_PROFILES[key]


def assert_fail_closed_registry() -> None:
    for profile in list_erp_profiles():
        for capability in DANGEROUS_CAPABILITIES:
            declaration = profile.capability(capability)
            if declaration.mode is not CapabilityMode.FORBIDDEN:
                raise RuntimeError(
                    f"Unsafe capability exposure: {profile.provider.value}/{capability.value}"
                )


def erp_registry_summary() -> dict[str, Any]:
    assert_fail_closed_registry()
    return {
        "profiles": [profile.to_dict() for profile in list_erp_profiles()],
        "computer_use_boundary": COMPUTER_USE_BOUNDARY.to_dict(),
        "external_write_capabilities": [item.value for item in DANGEROUS_CAPABILITIES],
        "external_write_mode": CapabilityMode.FORBIDDEN.value,
    }
