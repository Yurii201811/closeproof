"""ERP-neutral connector declarations and fail-closed v1 conformance checks.

This module does not implement transport, authentication, or provider setup. It
defines the information an adapter must expose, the provenance envelope
returned by a read, and the preview safety boundary. Static conformance never
calls an adapter. The explicit guarded-read gateway invokes a supplied adapter
once, after preflight checks, and validates its returned envelope.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ConnectorContractError(ValueError):
    """Raised when connector metadata violates the v1 contract."""


class ConnectorWriteForbidden(ConnectorContractError):
    """Raised when any external-write capability is requested in v1 preview."""


class ProviderLifecycle(str, Enum):
    GUARDED_READ_ONLY = "guarded_read_only"
    LOCAL_SUPPORTED = "local_supported"
    DECLARATION_ONLY = "declaration_only"


class ConnectorEnvironment(str, Enum):
    """Closed deployment environment vocabulary for connector scope binding."""

    LOCAL = "local"
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class ConnectorCapability(str, Enum):
    DISCOVER_SCHEMA = "discover_schema"
    READ_MASTER_DATA = "read_master_data"
    READ_TRANSACTIONS = "read_transactions"
    READ_PERIOD_LOCKS = "read_period_locks"
    IMPORT_LOCAL = "import_local"
    EXPORT_RAW = "export_raw"
    VALIDATE_LOCAL = "validate_local"
    CREATE_EXTERNAL_DRAFT = "create_external_draft"
    POST_JOURNAL = "post_journal"
    APPROVE_TRANSACTION = "approve_transaction"
    SEND_DOCUMENT = "send_document"
    START_PAYMENT = "start_payment"
    FILE_TAX = "file_tax"
    DELETE_RECORD = "delete_record"
    CHANGE_SETTINGS = "change_settings"


WRITE_CAPABILITIES = (
    ConnectorCapability.CREATE_EXTERNAL_DRAFT,
    ConnectorCapability.POST_JOURNAL,
    ConnectorCapability.APPROVE_TRANSACTION,
    ConnectorCapability.SEND_DOCUMENT,
    ConnectorCapability.START_PAYMENT,
    ConnectorCapability.FILE_TAX,
    ConnectorCapability.DELETE_RECORD,
    ConnectorCapability.CHANGE_SETTINGS,
)

_READ_PAGE_CAPABILITIES = (
    ConnectorCapability.READ_MASTER_DATA,
    ConnectorCapability.READ_TRANSACTIONS,
    ConnectorCapability.READ_PERIOD_LOCKS,
)


class CapabilityMode(str, Enum):
    LOCAL_ONLY = "local_only"
    READ_ONLY = "read_only"
    DECLARED = "declared_not_connected"
    FORBIDDEN = "forbidden"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    DECLARED_ONLY = "declared_only"


class PaginationMode(str, Enum):
    NONE = "none"
    CURSOR = "cursor"
    PAGE_NUMBER = "page_number"
    OFFSET = "offset"


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AUTH_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_INLINE_SECRET_MARKERS = (
    "bearer ",
    "access_token=",
    "client_secret=",
    "password=",
    "-----begin private key-----",
)
_AUTH_REFERENCE_SCHEMES = (
    "connection-ref:",
    "env-ref:",
    "keychain-ref:",
    "oauth-ref:",
    "vault-ref:",
)


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ConnectorContractError(
            f"{label} must be a non-blank, single-line opaque identifier."
        )


def _require_version(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConnectorContractError(f"{label} must be a non-blank version identifier.")


@dataclass(frozen=True)
class AuthReference:
    """An opaque lookup reference; credential values are never part of the contract."""

    reference_id: str

    def __post_init__(self) -> None:
        lowered = self.reference_id.lower() if isinstance(self.reference_id, str) else ""
        if any(marker in lowered for marker in _INLINE_SECRET_MARKERS):
            raise ConnectorContractError(
                "auth reference appears to contain inline credential material"
            )
        if not lowered.startswith(_AUTH_REFERENCE_SCHEMES):
            raise ConnectorContractError(
                "auth reference must use an explicit reference scheme, never inline credentials"
            )
        if not isinstance(self.reference_id, str) or not _AUTH_REFERENCE_PATTERN.fullmatch(
            self.reference_id
        ):
            raise ConnectorContractError(
                "auth reference must be an opaque lookup identifier, never a secret value"
            )


@dataclass(frozen=True)
class ConnectorBinding:
    """Exact tenant/company/environment scope for every health check and data page."""

    tenant_id: str
    company_id: str
    environment: ConnectorEnvironment
    auth_reference: AuthReference | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.tenant_id, "tenant_id")
        _require_identifier(self.company_id, "company_id")
        try:
            environment = ConnectorEnvironment(self.environment)
        except (TypeError, ValueError) as error:
            raise ConnectorContractError(
                "environment must be a ConnectorEnvironment value: local, sandbox, or production"
            ) from error
        object.__setattr__(self, "environment", environment)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "environment": self.environment.value,
            "auth_reference": (
                self.auth_reference.reference_id if self.auth_reference is not None else None
            ),
        }


@dataclass(frozen=True)
class ConnectorGuard:
    """Non-overridable safety posture for the public v1 preview."""

    dry_run_only: bool = True
    read_only: bool = True

    def require(self, capability: ConnectorCapability) -> None:
        if capability in WRITE_CAPABILITIES:
            raise ConnectorWriteForbidden(
                f"{capability.value} is forbidden in the v1 preview; "
                "configuration, approval, or credentials cannot enable it"
            )
        if not self.dry_run_only or not self.read_only:
            raise ConnectorContractError(
                "connector guard must remain dry-run-only and read-only in v1 preview"
            )


@dataclass(frozen=True)
class CapabilityDeclaration:
    capability: ConnectorCapability
    mode: CapabilityMode
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability.value,
            "mode": self.mode.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PaginationContract:
    mode: PaginationMode
    cursor_parameter: str | None = None
    next_cursor_field: str | None = None
    max_page_size: int = 1000

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_page_size, bool)
            or not isinstance(self.max_page_size, int)
            or self.max_page_size <= 0
        ):
            raise ConnectorContractError("max_page_size must be a positive integer")
        cursor_fields = (self.cursor_parameter, self.next_cursor_field)
        if self.mode is PaginationMode.NONE:
            if any(item is not None for item in cursor_fields):
                raise ConnectorContractError(
                    "non-paginated connectors cannot declare cursor fields"
                )
            return
        if not all(isinstance(item, str) and item.strip() for item in cursor_fields):
            raise ConnectorContractError(
                "paginated connectors require cursor_parameter and next_cursor_field"
            )

    @property
    def uses_cursor(self) -> bool:
        return self.mode is not PaginationMode.NONE

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "mode": self.mode.value,
            "cursor_parameter": self.cursor_parameter,
            "next_cursor_field": self.next_cursor_field,
            "max_page_size": self.max_page_size,
        }


@dataclass(frozen=True)
class ConnectorManifest:
    provider_id: str
    display_name: str
    lifecycle: ProviderLifecycle
    schema_version: str
    mapping_version: str
    pagination: PaginationContract
    capabilities: tuple[CapabilityDeclaration, ...]
    guard: ConnectorGuard = field(default_factory=ConnectorGuard)
    implementation_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.provider_id, "provider_id")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ConnectorContractError("display_name must be non-blank")
        _require_version(self.schema_version, "schema_version")
        _require_version(self.mapping_version, "mapping_version")

    def capability(self, capability: ConnectorCapability) -> CapabilityDeclaration:
        for declaration in self.capabilities:
            if declaration.capability is capability:
                return declaration
        return CapabilityDeclaration(
            capability,
            CapabilityMode.FORBIDDEN,
            "Undeclared capabilities fail closed.",
        )

    def require_capability(self, capability: ConnectorCapability) -> None:
        self.guard.require(capability)
        declaration = self.capability(capability)
        if declaration.mode not in {CapabilityMode.LOCAL_ONLY, CapabilityMode.READ_ONLY}:
            raise ConnectorContractError(
                f"{self.provider_id}/{capability.value} is not available: "
                f"{declaration.mode.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "lifecycle": self.lifecycle.value,
            "schema_version": self.schema_version,
            "mapping_version": self.mapping_version,
            "pagination": self.pagination.to_dict(),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "guard": {
                "dry_run_only": self.guard.dry_run_only,
                "read_only": self.guard.read_only,
            },
            "implementation_notes": list(self.implementation_notes),
        }


@dataclass(frozen=True)
class ConnectorHealth:
    provider_id: str
    binding: ConnectorBinding
    status: HealthStatus
    checked_at: datetime
    detail_code: str

    def __post_init__(self) -> None:
        _require_identifier(self.provider_id, "provider_id")
        if (
            not isinstance(self.checked_at, datetime)
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ConnectorContractError("health checked_at must be timezone-aware")
        _require_identifier(self.detail_code, "detail_code")


@dataclass(frozen=True)
class RetryMetadata:
    attempt_number: int
    max_attempts: int
    transient: bool
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.attempt_number, bool)
            or isinstance(self.max_attempts, bool)
            or not isinstance(self.attempt_number, int)
            or not isinstance(self.max_attempts, int)
            or self.attempt_number < 1
            or self.max_attempts < 1
            or self.attempt_number > self.max_attempts
        ):
            raise ConnectorContractError(
                "retry attempt_number must be between 1 and max_attempts"
            )
        if not isinstance(self.transient, bool):
            raise ConnectorContractError("retry transient must be a boolean")
        if self.retry_after_seconds is not None:
            if (
                isinstance(self.retry_after_seconds, bool)
                or not isinstance(self.retry_after_seconds, (int, float))
                or not math.isfinite(self.retry_after_seconds)
                or self.retry_after_seconds < 0
            ):
                raise ConnectorContractError(
                    "retry_after_seconds must be a finite non-negative number"
                )


@dataclass(frozen=True)
class ConnectorReadRequest:
    binding: ConnectorBinding
    resource: str
    cursor: str | None = None
    page_size: int = 100

    def __post_init__(self) -> None:
        _require_identifier(self.resource, "resource")
        if (
            isinstance(self.page_size, bool)
            or not isinstance(self.page_size, int)
            or self.page_size <= 0
        ):
            raise ConnectorContractError("page_size must be a positive integer")
        if self.cursor is not None and (not isinstance(self.cursor, str) or not self.cursor):
            raise ConnectorContractError("cursor must be non-blank when supplied")


@dataclass(frozen=True)
class ConnectorPage:
    """Read envelope preserving source identity and transformation versions."""

    provider_id: str
    binding: ConnectorBinding
    resource: str
    schema_version: str
    mapping_version: str
    raw_snapshot_hash: str
    records: tuple[Mapping[str, Any], ...]
    source_cursor: str | None
    next_cursor: str | None
    retry: RetryMetadata

    def __post_init__(self) -> None:
        _require_identifier(self.provider_id, "provider_id")
        _require_identifier(self.resource, "resource")
        _require_version(self.schema_version, "schema_version")
        _require_version(self.mapping_version, "mapping_version")
        if not isinstance(self.raw_snapshot_hash, str) or not _SHA256_PATTERN.fullmatch(
            self.raw_snapshot_hash
        ):
            raise ConnectorContractError("raw_snapshot_hash must be a SHA-256 hex digest")
        if self.source_cursor is not None and not isinstance(self.source_cursor, str):
            raise ConnectorContractError("source_cursor must be text or None")
        if self.next_cursor is not None and not isinstance(self.next_cursor, str):
            raise ConnectorContractError("next_cursor must be text or None")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, Mapping) for record in self.records
        ):
            raise ConnectorContractError("records must be a tuple of mappings")


def raw_snapshot_sha256(payload: bytes | bytearray | memoryview) -> str:
    """Hash exact source bytes before parsing or mapping."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("raw snapshot payload must be bytes-like")
    return hashlib.sha256(bytes(payload)).hexdigest()


@runtime_checkable
class ConnectorAdapter(Protocol):
    """Read-only adapter surface; intentionally contains no write operation."""

    @property
    def provider_id(self) -> str:
        ...

    @property
    def binding(self) -> ConnectorBinding:
        ...

    @property
    def manifest(self) -> ConnectorManifest:
        ...

    def check_health(self) -> ConnectorHealth:
        ...

    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        ...


def _guarded_read_context(
    adapter: ConnectorAdapter,
    request: ConnectorReadRequest,
    *,
    capability: ConnectorCapability = ConnectorCapability.READ_TRANSACTIONS,
) -> tuple[str, ConnectorBinding, ConnectorManifest]:
    """Validate and capture the immutable context for one guarded read."""

    if not isinstance(adapter, ConnectorAdapter):
        raise ConnectorContractError("adapter does not satisfy ConnectorAdapter")
    if not isinstance(request, ConnectorReadRequest):
        raise TypeError("request must be a ConnectorReadRequest")
    manifest = adapter.manifest
    binding = adapter.binding
    provider_id = adapter.provider_id
    if not isinstance(manifest, ConnectorManifest):
        raise ConnectorContractError("adapter manifest must be a ConnectorManifest")
    if not isinstance(binding, ConnectorBinding):
        raise ConnectorContractError("adapter binding must be a ConnectorBinding")
    if provider_id != manifest.provider_id:
        raise ConnectorContractError(
            "adapter provider_id does not match its connector manifest"
        )
    if request.binding != binding:
        raise ConnectorContractError(
            "read request binding does not match the adapter "
            "tenant/company/environment binding"
        )
    try:
        requested_capability = ConnectorCapability(capability)
    except (TypeError, ValueError) as error:
        raise ConnectorContractError("unknown connector capability") from error
    manifest.require_capability(requested_capability)
    if requested_capability not in _READ_PAGE_CAPABILITIES:
        raise ConnectorContractError(
            f"{requested_capability.value} cannot be executed through the read-page gateway"
        )
    if request.page_size > manifest.pagination.max_page_size:
        raise ConnectorContractError(
            "read request page_size exceeds the connector manifest maximum"
        )
    if request.cursor is not None and not request.cursor.strip():
        raise ConnectorContractError("read request cursor must be non-blank")
    if (
        manifest.pagination.mode is PaginationMode.NONE
        and request.cursor is not None
    ):
        raise ConnectorContractError(
            "non-paginated connectors cannot accept a read cursor"
        )
    return provider_id, binding, manifest


def require_guarded_read_request(
    adapter: ConnectorAdapter,
    request: ConnectorReadRequest,
    *,
    capability: ConnectorCapability = ConnectorCapability.READ_TRANSACTIONS,
) -> None:
    """Validate exact scope and pagination before any adapter read is called."""

    _guarded_read_context(adapter, request, capability=capability)


def read_connector_page_guarded(
    adapter: ConnectorAdapter,
    request: ConnectorReadRequest,
    *,
    capability: ConnectorCapability = ConnectorCapability.READ_TRANSACTIONS,
) -> ConnectorPage:
    """Execute one read and reject any response outside the preflight contract."""

    expected_provider, expected_binding, expected_manifest = _guarded_read_context(
        adapter,
        request,
        capability=capability,
    )

    page = adapter.read_page(request)

    if (
        adapter.provider_id != expected_provider
        or adapter.binding != expected_binding
        or adapter.manifest != expected_manifest
    ):
        raise ConnectorContractError(
            "adapter provider, tenant/company/environment binding, or manifest "
            "changed during the guarded read"
        )
    if not isinstance(page, ConnectorPage):
        raise ConnectorContractError("adapter read_page must return a ConnectorPage")
    if page.provider_id != expected_provider:
        raise ConnectorContractError(
            "returned page provider_id does not match the guarded adapter"
        )
    if page.binding != expected_binding or page.binding != request.binding:
        raise ConnectorContractError(
            "returned page tenant/company/environment binding does not match "
            "the guarded read request"
        )
    if page.resource != request.resource:
        raise ConnectorContractError(
            "returned page resource does not match the guarded read request"
        )
    if page.schema_version != expected_manifest.schema_version:
        raise ConnectorContractError(
            "returned page schema_version does not match the connector manifest"
        )
    if page.mapping_version != expected_manifest.mapping_version:
        raise ConnectorContractError(
            "returned page mapping_version does not match the connector manifest"
        )
    if page.source_cursor != request.cursor:
        raise ConnectorContractError(
            "returned page source_cursor does not match the read request cursor"
        )
    if len(page.records) > request.page_size:
        raise ConnectorContractError(
            "returned page contains more records than the guarded request page_size"
        )
    if page.next_cursor is not None and not page.next_cursor.strip():
        raise ConnectorContractError(
            "returned page next_cursor must be non-blank when supplied"
        )
    if (
        expected_manifest.pagination.mode is PaginationMode.NONE
        and page.next_cursor is not None
    ):
        raise ConnectorContractError(
            "non-paginated connectors cannot return a next cursor"
        )
    if page.next_cursor is not None and page.next_cursor == page.source_cursor:
        raise ConnectorContractError(
            "returned page next_cursor must advance beyond the source cursor"
        )
    return page


@dataclass(frozen=True)
class ConformanceIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ConformanceReport:
    provider_id: str
    issues: tuple[ConformanceIssue, ...]

    @property
    def conformant(self) -> bool:
        return not self.issues

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


def _declarations(
    lifecycle: ProviderLifecycle,
) -> tuple[CapabilityDeclaration, ...]:
    declarations: list[CapabilityDeclaration] = []
    for capability in ConnectorCapability:
        if capability in WRITE_CAPABILITIES:
            declarations.append(
                CapabilityDeclaration(
                    capability,
                    CapabilityMode.FORBIDDEN,
                    "External writes and consequential accounting actions are forbidden in v1.",
                )
            )
        elif lifecycle is ProviderLifecycle.DECLARATION_ONLY:
            declarations.append(
                CapabilityDeclaration(
                    capability,
                    CapabilityMode.DECLARED,
                    "Contract declared; no connector is implemented or configured.",
                )
            )
        elif lifecycle is ProviderLifecycle.LOCAL_SUPPORTED:
            declarations.append(
                CapabilityDeclaration(
                    capability,
                    CapabilityMode.LOCAL_ONLY,
                    "Operates only on user-supplied local exchange data.",
                )
            )
        else:
            mode = (
                CapabilityMode.READ_ONLY
                if capability
                in {
                    ConnectorCapability.READ_MASTER_DATA,
                    ConnectorCapability.READ_TRANSACTIONS,
                    ConnectorCapability.READ_PERIOD_LOCKS,
                }
                else CapabilityMode.LOCAL_ONLY
            )
            declarations.append(
                CapabilityDeclaration(
                    capability,
                    mode,
                    "Guarded least-privilege read or local validation only.",
                )
            )
    return tuple(declarations)


def _manifest(
    provider_id: str,
    display_name: str,
    lifecycle: ProviderLifecycle,
    pagination: PaginationContract,
    *,
    schema_version: str,
    mapping_version: str,
    notes: tuple[str, ...] = (),
) -> ConnectorManifest:
    return ConnectorManifest(
        provider_id=provider_id,
        display_name=display_name,
        lifecycle=lifecycle,
        schema_version=schema_version,
        mapping_version=mapping_version,
        pagination=pagination,
        capabilities=_declarations(lifecycle),
        implementation_notes=notes,
    )


_CURSOR_PAGINATION = PaginationContract(
    PaginationMode.CURSOR,
    cursor_parameter="cursor",
    next_cursor_field="next_cursor",
    max_page_size=1000,
)
_PAGE_PAGINATION = PaginationContract(
    PaginationMode.PAGE_NUMBER,
    cursor_parameter="page",
    next_cursor_field="next_page",
    max_page_size=500,
)
_OFFSET_PAGINATION = PaginationContract(
    PaginationMode.OFFSET,
    cursor_parameter="offset",
    next_cursor_field="next_offset",
    max_page_size=1000,
)
_NO_PAGINATION = PaginationContract(PaginationMode.NONE, max_page_size=100_000)


CONNECTOR_MANIFESTS: dict[str, ConnectorManifest] = {
    "fortnox": _manifest(
        "fortnox",
        "Fortnox",
        ProviderLifecycle.GUARDED_READ_ONLY,
        _PAGE_PAGINATION,
        schema_version="1",
        mapping_version="bas-v1",
        notes=(
            "Existing adapter support is read/dry-run only; "
            "manifest and static conformance checks perform no network call.",
        ),
    ),
    "netsuite": _manifest(
        "netsuite",
        "Oracle NetSuite",
        ProviderLifecycle.DECLARATION_ONLY,
        _CURSOR_PAGINATION,
        schema_version="2026.1",
        mapping_version="canonical-v1",
    ),
    "oracle_fusion": _manifest(
        "oracle_fusion",
        "Oracle Fusion Cloud Financials",
        ProviderLifecycle.DECLARATION_ONLY,
        _OFFSET_PAGINATION,
        schema_version="26a",
        mapping_version="canonical-v1",
    ),
    "sap_s4hana": _manifest(
        "sap_s4hana",
        "SAP S/4HANA",
        ProviderLifecycle.DECLARATION_ONLY,
        _CURSOR_PAGINATION,
        schema_version="v1",
        mapping_version="canonical-v1",
    ),
    "odoo": _manifest(
        "odoo",
        "Odoo",
        ProviderLifecycle.DECLARATION_ONLY,
        _OFFSET_PAGINATION,
        schema_version="v1",
        mapping_version="canonical-v1",
    ),
    "sie": _manifest(
        "sie",
        "SIE accounting exchange",
        ProviderLifecycle.DECLARATION_ONLY,
        _NO_PAGINATION,
        schema_version="sie-v4",
        mapping_version="bas-v1",
        notes=("SIE parsing is declared for future conformance work and is not implemented.",),
    ),
    "csv": _manifest(
        "csv",
        "CSV accounting exchange",
        ProviderLifecycle.DECLARATION_ONLY,
        _NO_PAGINATION,
        schema_version="csv-v1",
        mapping_version="canonical-v1",
        notes=("CSV mapping is declared but no generic connector is implemented.",),
    ),
}


def list_connector_manifests() -> tuple[ConnectorManifest, ...]:
    return tuple(CONNECTOR_MANIFESTS.values())


def get_connector_manifest(provider_id: str) -> ConnectorManifest:
    try:
        return CONNECTOR_MANIFESTS[provider_id]
    except KeyError as error:
        raise ConnectorContractError(f"unknown connector provider: {provider_id}") from error


def assert_v1_preview_registry_safe() -> None:
    """Raise if a declaration could imply external-write authority."""

    for manifest in list_connector_manifests():
        if not manifest.guard.dry_run_only or not manifest.guard.read_only:
            raise ConnectorContractError(
                f"unsafe connector guard: {manifest.provider_id}"
            )
        declared = [item.capability for item in manifest.capabilities]
        if len(declared) != len(set(declared)) or set(declared) != set(ConnectorCapability):
            raise ConnectorContractError(
                f"incomplete or duplicate capabilities: {manifest.provider_id}"
            )
        for capability in WRITE_CAPABILITIES:
            if manifest.capability(capability).mode is not CapabilityMode.FORBIDDEN:
                raise ConnectorContractError(
                    f"unsafe write capability: {manifest.provider_id}/{capability.value}"
                )


def evaluate_connector_conformance(
    adapter: ConnectorAdapter,
    *,
    health: ConnectorHealth | None = None,
    sample_page: ConnectorPage | None = None,
) -> ConformanceReport:
    """Statically evaluate declarations and supplied evidence without calling the adapter."""

    issues: list[ConformanceIssue] = []
    provider_id = getattr(adapter, "provider_id", "unknown")

    if not isinstance(adapter, ConnectorAdapter):
        return ConformanceReport(
            str(provider_id),
            (
                ConformanceIssue(
                    "adapter_protocol_mismatch",
                    "Adapter does not expose the complete read-only ConnectorAdapter protocol.",
                ),
            ),
        )

    manifest = adapter.manifest
    binding = adapter.binding
    if provider_id != manifest.provider_id:
        issues.append(
            ConformanceIssue(
                "adapter_provider_mismatch",
                "Adapter provider_id does not match its manifest.",
            )
        )
    if not manifest.guard.dry_run_only or not manifest.guard.read_only:
        issues.append(
            ConformanceIssue(
                "unsafe_guard",
                "Adapter manifest is not dry-run-only and read-only.",
            )
        )

    declared = [item.capability for item in manifest.capabilities]
    if len(declared) != len(set(declared)) or set(declared) != set(ConnectorCapability):
        issues.append(
            ConformanceIssue(
                "capability_manifest_incomplete",
                "Every capability must be declared exactly once.",
            )
        )
    for capability in WRITE_CAPABILITIES:
        if manifest.capability(capability).mode is not CapabilityMode.FORBIDDEN:
            issues.append(
                ConformanceIssue(
                    "write_capability_exposed",
                    f"{capability.value} must remain forbidden.",
                )
            )

    if health is not None:
        if health.provider_id != provider_id:
            issues.append(
                ConformanceIssue(
                    "health_provider_mismatch",
                    "Health evidence belongs to a different provider.",
                )
            )
        if health.binding != binding:
            issues.append(
                ConformanceIssue(
                    "health_binding_mismatch",
                    "Health evidence belongs to a different "
                    "tenant/company/environment binding.",
                )
            )

    if sample_page is not None:
        if sample_page.provider_id != provider_id:
            issues.append(
                ConformanceIssue(
                    "page_provider_mismatch",
                    "Sample page belongs to a different provider.",
                )
            )
        if sample_page.binding != binding:
            issues.append(
                ConformanceIssue(
                    "page_binding_mismatch",
                    "Sample page belongs to a different "
                    "tenant/company/environment binding.",
                )
            )
        if sample_page.schema_version != manifest.schema_version:
            issues.append(
                ConformanceIssue(
                    "schema_version_mismatch",
                    "Sample page schema version does not match the manifest.",
                )
            )
        if sample_page.mapping_version != manifest.mapping_version:
            issues.append(
                ConformanceIssue(
                    "mapping_version_mismatch",
                    "Sample page mapping version does not match the manifest.",
                )
            )
        if (
            manifest.pagination.mode is PaginationMode.NONE
            and sample_page.next_cursor is not None
        ):
            issues.append(
                ConformanceIssue(
                    "unexpected_next_cursor",
                    "A non-paginated connector returned a next cursor.",
                )
            )

    return ConformanceReport(str(provider_id), tuple(issues))


assert_v1_preview_registry_safe()


__all__ = [
    "CONNECTOR_MANIFESTS",
    "WRITE_CAPABILITIES",
    "AuthReference",
    "CapabilityDeclaration",
    "CapabilityMode",
    "ConformanceIssue",
    "ConformanceReport",
    "ConnectorAdapter",
    "ConnectorBinding",
    "ConnectorCapability",
    "ConnectorContractError",
    "ConnectorEnvironment",
    "ConnectorGuard",
    "ConnectorHealth",
    "ConnectorManifest",
    "ConnectorPage",
    "ConnectorReadRequest",
    "ConnectorWriteForbidden",
    "HealthStatus",
    "PaginationContract",
    "PaginationMode",
    "ProviderLifecycle",
    "RetryMetadata",
    "assert_v1_preview_registry_safe",
    "evaluate_connector_conformance",
    "get_connector_manifest",
    "list_connector_manifests",
    "raw_snapshot_sha256",
    "read_connector_page_guarded",
    "require_guarded_read_request",
]
