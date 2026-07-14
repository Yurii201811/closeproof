"""External write adapters that are guarded by execution permits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .permits import ExecutionPermit, PermitValidator
from .policy import ActionType, EXTERNAL_WRITE_ACTIONS, POLICY_VERSION


@dataclass(frozen=True)
class ExternalWriteResult:
    adapter: str
    action_type: ActionType
    case_id: str
    idempotency_key: str
    status: str
    external_reference: str | None = None


class ExternalWriteAdapter:
    adapter_name = "external"

    def __init__(self, permit_validator: PermitValidator | None = None) -> None:
        self.permit_validator = permit_validator or PermitValidator(
            accepted_policy_version=POLICY_VERSION
        )

    def execute(
        self,
        *,
        action_type: ActionType,
        case_id: str,
        entity_id: str,
        payload: Any,
        permit: ExecutionPermit | None,
    ) -> ExternalWriteResult:
        action_type = ActionType(action_type)
        if action_type not in EXTERNAL_WRITE_ACTIONS:
            raise ValueError(f"{action_type.value} is not an external write action")
        self.permit_validator.require_valid(
            permit=permit,
            case_id=case_id,
            entity_id=entity_id,
            action_type=action_type,
            payload=payload,
        )
        return self._execute_with_valid_permit(
            action_type=action_type,
            case_id=case_id,
            payload=payload,
            permit=permit,
        )

    def _execute_with_valid_permit(
        self,
        *,
        action_type: ActionType,
        case_id: str,
        payload: Any,
        permit: ExecutionPermit,
    ) -> ExternalWriteResult:
        raise NotImplementedError


class FortnoxWriteAdapter(ExternalWriteAdapter):
    """Permit-guarded Fortnox adapter stub.

    This intentionally does not connect to Fortnox yet. It proves the local
    execution boundary and returns a local placeholder result.
    """

    adapter_name = "fortnox"

    def _execute_with_valid_permit(
        self,
        *,
        action_type: ActionType,
        case_id: str,
        payload: Any,
        permit: ExecutionPermit,
    ) -> ExternalWriteResult:
        return ExternalWriteResult(
            adapter=self.adapter_name,
            action_type=action_type,
            case_id=case_id,
            idempotency_key=permit.idempotency_key,
            status="permit_validated_no_live_write",
        )


class EmailWriteAdapter(ExternalWriteAdapter):
    """Permit-guarded email adapter stub with no send capability."""

    adapter_name = "email"

    def _execute_with_valid_permit(
        self,
        *,
        action_type: ActionType,
        case_id: str,
        payload: Any,
        permit: ExecutionPermit,
    ) -> ExternalWriteResult:
        if action_type is not ActionType.SEND_EMAIL:
            raise ValueError("EmailWriteAdapter only accepts send_email actions")
        return ExternalWriteResult(
            adapter=self.adapter_name,
            action_type=action_type,
            case_id=case_id,
            idempotency_key=permit.idempotency_key,
            status="permit_validated_no_email_sent",
        )
