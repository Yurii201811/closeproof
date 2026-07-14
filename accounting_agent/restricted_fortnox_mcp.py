"""Restricted Fortnox MCP facade with fail-closed policy enforcement.

The objects in this module are intentionally local mocks. They model the
agent-facing tool boundary without connecting to Fortnox or exposing raw write
tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .external_writes import FortnoxWriteAdapter
from .permits import ExecutionPermit, PermitValidationError, canonical_payload_hash
from .policy import ActionType, PermissionMode, PolicyContext, evaluate_policy


FORTNOX_SYSTEM = "fortnox"
EXECUTION_PERMIT_REQUIRED = "execution_permit"
NO_PERMIT_ISSUABLE = "not_issuable"
WRITE_RISK_EVIDENCE_FIELDS = (
    "amount_minor",
    "currency",
    "supplier_known",
    "customer_known",
    "bank_details_changed",
    "duplicate_risk",
    "vat_confidence",
    "ocr_confidence",
    "period_locked",
    "new_supplier",
    "destructive_action",
    "external_communication",
    "tax_filing_payment",
)


class MCPPermissionMode(str, Enum):
    READ_SAFE = "read_safe"
    DRAFT_ONLY = "draft_only"
    APPROVAL_REQUIRED = "approval_required"
    ESCALATION_REQUIRED = "escalation_required"
    FORBIDDEN = "forbidden"


class RestrictedMCPError(Exception):
    """Base error for restricted MCP tool failures."""


class UnknownRestrictedTool(RestrictedMCPError):
    """Raised when a tool is not present in the restricted registry."""


class RestrictedToolForbidden(RestrictedMCPError):
    """Raised when a registered tool is forbidden or intentionally hidden."""


class RestrictedToolPermitError(RestrictedMCPError):
    """Raised when a write-like tool is missing a valid execution permit."""


@dataclass(frozen=True)
class RestrictedToolMetadata:
    tool_name: str
    external_system: str
    action_type: ActionType
    permission_mode: MCPPermissionMode
    required_permit: str | None
    forbidden_conditions: tuple[str, ...]
    exposed_to_agents: bool = True

    @property
    def is_write_like(self) -> bool:
        return self.permission_mode is not MCPPermissionMode.READ_SAFE

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "external_system": self.external_system,
            "action_type": self.action_type.value,
            "permission_mode": self.permission_mode.value,
            "required_permit": self.required_permit,
            "forbidden_conditions": list(self.forbidden_conditions),
            "exposed_to_agents": self.exposed_to_agents,
        }


@dataclass(frozen=True)
class ToolCallLogEntry:
    sequence: int
    tool_name: str
    external_system: str
    action_type: str
    permission_mode: str
    status: str
    case_id: str | None
    client_id: str | None
    permit_id: str | None
    payload_hash: str
    reason: str | None = None


@dataclass
class ToolCallAuditLog:
    """In-memory audit sink for the mocked MCP facade."""

    entries: list[ToolCallLogEntry] = field(default_factory=list)

    def record(
        self,
        *,
        metadata: RestrictedToolMetadata,
        payload: Mapping[str, Any],
        status: str,
        case_id: str | None,
        permit: ExecutionPermit | None,
        reason: str | None = None,
    ) -> None:
        self.entries.append(
            ToolCallLogEntry(
                sequence=len(self.entries) + 1,
                tool_name=metadata.tool_name,
                external_system=metadata.external_system,
                action_type=metadata.action_type.value,
                permission_mode=metadata.permission_mode.value,
                status=status,
                case_id=case_id,
                client_id=_optional_text(payload.get("client_id")),
                permit_id=permit.permit_id if permit is not None else None,
                payload_hash=canonical_payload_hash(payload),
                reason=reason,
            )
        )


RESTRICTED_FORTNOX_TOOL_REGISTRY: dict[str, RestrictedToolMetadata] = {
    "fortnox_get_supplier": RestrictedToolMetadata(
        tool_name="fortnox_get_supplier",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.READ_ANALYSIS,
        permission_mode=MCPPermissionMode.READ_SAFE,
        required_permit=None,
        forbidden_conditions=(
            "must not mutate Fortnox state",
            "must not expose secrets or credentials",
        ),
    ),
    "fortnox_list_accounts": RestrictedToolMetadata(
        tool_name="fortnox_list_accounts",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.READ_ANALYSIS,
        permission_mode=MCPPermissionMode.READ_SAFE,
        required_permit=None,
        forbidden_conditions=(
            "must not mutate Fortnox state",
            "must not expose secrets or credentials",
        ),
    ),
    "fortnox_prepare_supplier_invoice_draft": RestrictedToolMetadata(
        tool_name="fortnox_prepare_supplier_invoice_draft",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
        permission_mode=MCPPermissionMode.DRAFT_ONLY,
        required_permit=EXECUTION_PERMIT_REQUIRED,
        forbidden_conditions=(
            "missing or invalid execution permit",
            "locked accounting period",
            "attempt to approve, send, post, pay, file tax, or finalize bookkeeping",
        ),
    ),
    "fortnox_prepare_voucher_draft": RestrictedToolMetadata(
        tool_name="fortnox_prepare_voucher_draft",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.DRAFT_VOUCHER,
        permission_mode=MCPPermissionMode.DRAFT_ONLY,
        required_permit=EXECUTION_PERMIT_REQUIRED,
        forbidden_conditions=(
            "missing or invalid execution permit",
            "locked accounting period",
            "attempt to post, approve, pay, file tax, or finalize bookkeeping",
        ),
    ),
    "fortnox_update_supplier": RestrictedToolMetadata(
        tool_name="fortnox_update_supplier",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.UPDATE_SUPPLIER,
        permission_mode=MCPPermissionMode.APPROVAL_REQUIRED,
        required_permit=EXECUTION_PERMIT_REQUIRED,
        forbidden_conditions=(
            "not exposed to LLM agents",
            "missing accountant review execution permit",
        ),
        exposed_to_agents=False,
    ),
    "fortnox_update_supplier_bank_details": RestrictedToolMetadata(
        tool_name="fortnox_update_supplier_bank_details",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.UPDATE_SUPPLIER_BANK_DETAILS,
        permission_mode=MCPPermissionMode.ESCALATION_REQUIRED,
        required_permit=EXECUTION_PERMIT_REQUIRED,
        forbidden_conditions=(
            "not exposed to LLM agents",
            "missing senior accountant and security review execution permit",
        ),
        exposed_to_agents=False,
    ),
    "fortnox_approve_supplier_invoice": RestrictedToolMetadata(
        tool_name="fortnox_approve_supplier_invoice",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.APPROVE_SUPPLIER_INVOICE,
        permission_mode=MCPPermissionMode.FORBIDDEN,
        required_permit=NO_PERMIT_ISSUABLE,
        forbidden_conditions=(
            "supplier invoice approval is not allowed through the agent MCP layer",
        ),
        exposed_to_agents=False,
    ),
    "fortnox_delete_supplier": RestrictedToolMetadata(
        tool_name="fortnox_delete_supplier",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.DELETE_RECORD,
        permission_mode=MCPPermissionMode.FORBIDDEN,
        required_permit=NO_PERMIT_ISSUABLE,
        forbidden_conditions=("supplier deletion is forbidden",),
        exposed_to_agents=False,
    ),
    "fortnox_start_payment": RestrictedToolMetadata(
        tool_name="fortnox_start_payment",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.START_PAYMENT,
        permission_mode=MCPPermissionMode.FORBIDDEN,
        required_permit=NO_PERMIT_ISSUABLE,
        forbidden_conditions=("payments are forbidden in the agent MCP layer",),
        exposed_to_agents=False,
    ),
    "fortnox_send_invoice": RestrictedToolMetadata(
        tool_name="fortnox_send_invoice",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.SEND_INVOICE,
        permission_mode=MCPPermissionMode.FORBIDDEN,
        required_permit=NO_PERMIT_ISSUABLE,
        forbidden_conditions=("invoice sending is forbidden in the agent MCP layer",),
        exposed_to_agents=False,
    ),
    "fortnox_file_tax_return": RestrictedToolMetadata(
        tool_name="fortnox_file_tax_return",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.FILE_TAX_RETURN,
        permission_mode=MCPPermissionMode.FORBIDDEN,
        required_permit=NO_PERMIT_ISSUABLE,
        forbidden_conditions=("tax filing is forbidden in the agent MCP layer",),
        exposed_to_agents=False,
    ),
    "fortnox_post_voucher": RestrictedToolMetadata(
        tool_name="fortnox_post_voucher",
        external_system=FORTNOX_SYSTEM,
        action_type=ActionType.POST_VOUCHER,
        permission_mode=MCPPermissionMode.FORBIDDEN,
        required_permit=NO_PERMIT_ISSUABLE,
        forbidden_conditions=("bookkeeping finalization is forbidden in the agent MCP layer",),
        exposed_to_agents=False,
    ),
}


class RestrictedFortnoxMCP:
    """Agent-facing restricted Fortnox MCP facade backed by local mocks."""

    def __init__(
        self,
        *,
        registry: Mapping[str, RestrictedToolMetadata] | None = None,
        audit_log: ToolCallAuditLog | None = None,
        fortnox_adapter: FortnoxWriteAdapter | None = None,
    ) -> None:
        self.registry = dict(registry or RESTRICTED_FORTNOX_TOOL_REGISTRY)
        self.audit_log = audit_log or ToolCallAuditLog()
        self.fortnox_adapter = fortnox_adapter or FortnoxWriteAdapter()

    def available_tools(self) -> tuple[RestrictedToolMetadata, ...]:
        """Return the tools an LLM agent may see."""

        return tuple(
            metadata
            for metadata in self.registry.values()
            if metadata.exposed_to_agents
            and metadata.permission_mode
            in {MCPPermissionMode.READ_SAFE, MCPPermissionMode.DRAFT_ONLY}
        )

    def tool_registry(self) -> tuple[RestrictedToolMetadata, ...]:
        """Return the complete classified registry for operator inspection."""

        return tuple(self.registry.values())

    def call_tool(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        case_id: str | None = None,
        permit: ExecutionPermit | None = None,
    ) -> dict[str, Any]:
        payload_dict = dict(payload)
        try:
            metadata = self._metadata_for(tool_name)
        except UnknownRestrictedTool as exc:
            metadata = RestrictedToolMetadata(
                tool_name=tool_name,
                external_system=FORTNOX_SYSTEM,
                action_type=ActionType.READ_ANALYSIS,
                permission_mode=MCPPermissionMode.FORBIDDEN,
                required_permit=NO_PERMIT_ISSUABLE,
                forbidden_conditions=("tool is not in the restricted Fortnox registry",),
                exposed_to_agents=False,
            )
            self.audit_log.record(
                metadata=metadata,
                payload=payload_dict,
                status="denied",
                case_id=case_id,
                permit=permit,
                reason=str(exc),
            )
            raise

        try:
            self._ensure_tool_is_exposed(metadata)
            if metadata.permission_mode is MCPPermissionMode.READ_SAFE:
                result = self._call_read_tool(metadata, payload_dict)
            else:
                result = self._call_write_like_tool(
                    metadata,
                    payload_dict,
                    case_id=case_id,
                    permit=permit,
                )
        except Exception as exc:
            self.audit_log.record(
                metadata=metadata,
                payload=payload_dict,
                status="denied",
                case_id=case_id,
                permit=permit,
                reason=str(exc),
            )
            raise

        self.audit_log.record(
            metadata=metadata,
            payload=payload_dict,
            status="allowed",
            case_id=case_id,
            permit=permit,
        )
        return result

    def _metadata_for(self, tool_name: str) -> RestrictedToolMetadata:
        try:
            return self.registry[tool_name]
        except KeyError as exc:
            raise UnknownRestrictedTool(f"unknown restricted Fortnox tool: {tool_name}") from exc

    def _ensure_tool_is_exposed(self, metadata: RestrictedToolMetadata) -> None:
        if metadata.permission_mode is MCPPermissionMode.FORBIDDEN:
            raise RestrictedToolForbidden(
                f"{metadata.tool_name} is forbidden: "
                + "; ".join(metadata.forbidden_conditions)
            )
        if not metadata.exposed_to_agents:
            raise RestrictedToolForbidden(
                f"{metadata.tool_name} is classified as {metadata.permission_mode.value} "
                "and is not exposed to LLM agents"
            )

    def _call_read_tool(
        self,
        metadata: RestrictedToolMetadata,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        client_id = _required_text(payload, "client_id")
        if metadata.tool_name == "fortnox_get_supplier":
            supplier_id = _required_text(payload, "supplier_id")
            return {
                "tool": metadata.tool_name,
                "external_system": metadata.external_system,
                "permission_mode": metadata.permission_mode.value,
                "supplier": {
                    "client_id": client_id,
                    "supplier_id": supplier_id,
                    "name": "Mock Supplier AB",
                    "status": "mock_read_only",
                },
            }
        if metadata.tool_name == "fortnox_list_accounts":
            return {
                "tool": metadata.tool_name,
                "external_system": metadata.external_system,
                "permission_mode": metadata.permission_mode.value,
                "accounts": [
                    {"account": "1930", "name": "Business bank account"},
                    {"account": "2440", "name": "Supplier liabilities"},
                    {"account": "2641", "name": "Input VAT"},
                ],
                "client_id": client_id,
            }
        raise UnknownRestrictedTool(f"no read mock implemented for {metadata.tool_name}")

    def _call_write_like_tool(
        self,
        metadata: RestrictedToolMetadata,
        payload: Mapping[str, Any],
        *,
        case_id: str | None,
        permit: ExecutionPermit | None,
    ) -> dict[str, Any]:
        if case_id is None or not case_id.strip():
            raise RestrictedToolPermitError("write-like tools require a case_id")
        entity_id = payload.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise RestrictedToolPermitError("write-like tools require an explicit entity_id")
        context = _policy_context_from_payload(metadata.action_type, payload)
        decision = evaluate_policy(context)
        if decision.permission_mode is PermissionMode.FORBIDDEN:
            raise RestrictedToolForbidden(
                "policy forbids this tool call: " + ", ".join(decision.reasons)
            )
        if permit is None:
            raise RestrictedToolPermitError(
                f"{metadata.tool_name} requires a valid execution permit"
            )
        if permit.client_id != context.client_id:
            raise RestrictedToolPermitError("execution permit client_id does not match payload")
        if permit.entity_id != entity_id:
            raise RestrictedToolPermitError("execution permit entity_id does not match payload")
        if permit.permission_mode is not decision.permission_mode:
            raise RestrictedToolPermitError(
                "execution permit permission mode does not match current policy decision"
            )
        if permit.required_reviews != decision.required_reviews:
            raise RestrictedToolPermitError(
                "execution permit required reviews do not match current policy decision"
            )

        adapter_result = self.fortnox_adapter.execute(
            action_type=metadata.action_type,
            case_id=case_id,
            entity_id=entity_id,
            payload=payload,
            permit=permit,
        )
        return self._mock_draft_result(
            metadata=metadata,
            payload=payload,
            case_id=case_id,
            policy_mode=decision.permission_mode,
            adapter_status=adapter_result.status,
            idempotency_key=adapter_result.idempotency_key,
        )

    def _mock_draft_result(
        self,
        *,
        metadata: RestrictedToolMetadata,
        payload: Mapping[str, Any],
        case_id: str,
        policy_mode: PermissionMode,
        adapter_status: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if metadata.tool_name == "fortnox_prepare_supplier_invoice_draft":
            return {
                "tool": metadata.tool_name,
                "external_system": metadata.external_system,
                "status": "supplier_invoice_draft_prepared_no_live_write",
                "adapter_status": adapter_status,
                "case_id": case_id,
                "idempotency_key": idempotency_key,
                "policy": {"permission_mode": policy_mode.value},
                "draft": {
                    "supplier_id": payload.get("supplier_id"),
                    "amount_minor": payload.get("amount_minor", 0),
                    "currency": payload.get("currency", "SEK"),
                },
            }
        if metadata.tool_name == "fortnox_prepare_voucher_draft":
            return {
                "tool": metadata.tool_name,
                "external_system": metadata.external_system,
                "status": "voucher_draft_prepared_no_live_write",
                "adapter_status": adapter_status,
                "case_id": case_id,
                "idempotency_key": idempotency_key,
                "policy": {"permission_mode": policy_mode.value},
                "draft": {
                    "voucher_date": payload.get("voucher_date"),
                    "rows": list(payload.get("rows", ())),
                },
            }
        raise UnknownRestrictedTool(f"no draft mock implemented for {metadata.tool_name}")


def _policy_context_from_payload(
    action_type: ActionType,
    payload: Mapping[str, Any],
) -> PolicyContext:
    _require_write_risk_evidence(payload)
    return PolicyContext(
        action_type=action_type,
        client_id=_required_text(payload, "client_id"),
        currency_code=_required_text(payload, "currency"),
        amount_minor=_required_int(payload, "amount_minor"),
        supplier_known=_required_bool(payload, "supplier_known"),
        customer_known=_required_bool(payload, "customer_known"),
        bank_details_changed=_required_bool(payload, "bank_details_changed"),
        duplicate_risk=_required_float(payload, "duplicate_risk"),
        vat_confidence=_required_float(payload, "vat_confidence"),
        ocr_confidence=_required_float(payload, "ocr_confidence"),
        period_locked=_required_bool(payload, "period_locked"),
        new_supplier=_required_bool(payload, "new_supplier"),
        destructive_action=_required_bool(payload, "destructive_action"),
        external_communication=_required_bool(payload, "external_communication"),
        tax_filing_payment=_required_bool(payload, "tax_filing_payment"),
        risk_evidence_complete=True,
    )


def _require_write_risk_evidence(payload: Mapping[str, Any]) -> None:
    missing = [field for field in WRITE_RISK_EVIDENCE_FIELDS if field not in payload]
    if missing:
        raise RestrictedToolPermitError(
            "write-like tools require explicit risk evidence fields: " + ", ".join(missing)
        )


def _required_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _required_bool(payload: Mapping[str, Any], field_name: str) -> bool:
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _required_int(payload: Mapping[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_float(payload: Mapping[str, Any], field_name: str) -> float:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number")
    return float(value)


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
