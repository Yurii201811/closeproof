from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from accounting_agent.accounting.proposals import AccountingEntry, SupplierInvoiceProposal
from accounting_agent.accounting.money import Money
from accounting_agent.adapters.gnubok import (
    ShadowLedgerAdapter,
    mirror_supplier_invoice_proposal_to_shadow,
)
from accounting_agent.client_identity import (
    canonical_client_id,
    client_storage_key,
)
from accounting_agent.db import LocalQueue, scoped_entity_identity_hash
from accounting_agent.ledger import JournalDraft, JournalValidation, JournalValidationPolicy
from accounting_agent.policy import (
    ActionType,
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
)
from accounting_agent.risk_review import (
    AccountingCase,
    InvoiceHistoryEntry,
    RiskFinding,
    findings_to_dicts,
    review_accounting_case,
)

from .extraction import as_decimal, extract_invoice_fields
from .rules import (
    SE_PREVIEW_SUPPLIER_ACCOUNTS,
    SE_PREVIEW_SUPPLIER_CHART_ID,
    decide_policy,
    match_supplier,
    propose_accounting,
    propose_vat,
    score_risk,
)


class SupplierInvoicePipeline:
    """Fixture-driven supplier invoice pipeline for MVP 1."""

    def __init__(
        self,
        db_path: str | Path | None = ".local/accounting_agent.sqlite",
        output_dir: str | Path | None = ".local/approval_packets",
        *,
        client_id: str = "fixture_client",
        entity_id: str,
        shadow_ledger_adapter: ShadowLedgerAdapter | None = None,
        enable_shadow_ledger: bool = True,
        evaluation_date: date | None = None,
    ) -> None:
        self.client_id = canonical_client_id(client_id)
        self.entity_id = canonical_client_id(entity_id)
        self.queue = LocalQueue(db_path) if db_path else None
        self.output_dir = Path(output_dir) if output_dir else None
        self.shadow_ledger_adapter = shadow_ledger_adapter
        self.enable_shadow_ledger = enable_shadow_ledger
        self.evaluation_date = evaluation_date
        self._seen_signatures: dict[str, dict[str, Any]] = {}

    def process_fixture_dir(self, fixtures_dir: str | Path) -> list[dict[str, Any]]:
        fixture_paths = sorted(Path(fixtures_dir).glob("*.json"))
        return [self.process_fixture(path) for path in fixture_paths]

    def process_fixture(self, fixture_path: str | Path) -> dict[str, Any]:
        path = Path(fixture_path)
        fixture = json.loads(path.read_text(encoding="utf-8"))
        file_hash = sha256_file(path)
        now = utc_now()
        scoped_case_hash = scoped_entity_identity_hash(
            self.client_id,
            self.entity_id,
            file_hash,
        )
        case_id = f"si_{scoped_case_hash[:12]}"
        extracted = extract_invoice_fields(fixture)
        invoice_signature = build_invoice_signature(
            extracted,
            client_id=self.client_id,
            entity_id=self.entity_id,
        )
        case = {
            "case_id": case_id,
            "client_id": self.client_id,
            "entity_id": self.entity_id,
            "fixture_name": fixture.get("scenario", path.stem),
            "source_path": str(path),
            "file_hash": file_hash,
            "status": "approval_packet_ready",
            "created_from": "local_fixture",
        }
        document = {
            "file_hash": file_hash,
            "invoice_signature": invoice_signature,
            "source_kind": extracted["source_kind"],
            "source_filename": fixture.get("source_filename", path.name),
        }

        supplier_match = match_supplier(extracted)
        duplicate_check = self._check_duplicate(invoice_signature, case_id)
        vat_proposal = propose_vat(extracted)
        accounting_proposal = propose_accounting(extracted, supplier_match, vat_proposal)
        risk = score_risk(
            supplier_match.get("flags", []),
            duplicate_check.get("flags", []),
            vat_proposal.get("flags", []),
        )
        risk_findings = build_openclaw_risk_findings(
            case=case,
            client_id=self.client_id,
            document=document,
            extracted=extracted,
            supplier_match=supplier_match,
            duplicate_check=duplicate_check,
            vat_proposal=vat_proposal,
            today=self.evaluation_date,
        )
        policy_decision = decide_policy(risk)
        policy_decision = apply_openclaw_findings_to_policy_decision(
            policy_decision,
            risk_findings,
        )
        canonical_context = build_supplier_invoice_policy_context(
            client_id=self.client_id,
            extracted=extracted,
            supplier_match=supplier_match,
            duplicate_check=duplicate_check,
            vat_proposal=vat_proposal,
            risk_findings=risk_findings,
        )
        canonical_decision = evaluate_policy(canonical_context)
        policy_decision = apply_canonical_policy_decision(
            policy_decision,
            canonical_decision,
        )
        canonical_proposal = build_shadow_supplier_invoice_proposal(
            case=case,
            client_id=self.client_id,
            entity_id=self.entity_id,
            extracted=extracted,
            supplier_match=supplier_match,
            vat_proposal=vat_proposal,
            accounting_proposal=accounting_proposal,
        )
        journal_draft = canonical_proposal.to_journal_draft(
            period_locked=bool(extracted.get("period_locked", False))
        )
        journal_validation = journal_draft.validate(
            JournalValidationPolicy(
                chart_id=SE_PREVIEW_SUPPLIER_CHART_ID,
                allowed_accounts=SE_PREVIEW_SUPPLIER_ACCOUNTS,
                require_line_evidence=True,
            )
        )
        policy_decision = apply_journal_validation_to_policy(
            policy_decision,
            journal_validation,
        )
        fortnox_payload = build_fortnox_payload(
            case,
            extracted,
            supplier_match,
            accounting_proposal,
            policy_decision,
            client_id=self.client_id,
            entity_id=self.entity_id,
        )
        shadow_ledger_comparison = build_shadow_ledger_comparison(
            case=case,
            client_id=self.client_id,
            entity_id=self.entity_id,
            extracted=extracted,
            supplier_match=supplier_match,
            vat_proposal=vat_proposal,
            accounting_proposal=accounting_proposal,
            adapter=self.shadow_ledger_adapter,
            enabled=self.enable_shadow_ledger,
        )
        packet = build_approval_packet(
            now=now,
            case=case,
            document=document,
            extracted=extracted,
            supplier_match=supplier_match,
            duplicate_check=duplicate_check,
            vat_proposal=vat_proposal,
            accounting_proposal=accounting_proposal,
            risk=risk,
            risk_findings=risk_findings,
            policy_decision=policy_decision,
            fortnox_payload=fortnox_payload,
            journal_draft=journal_draft,
            journal_validation=journal_validation,
            shadow_ledger_comparison=shadow_ledger_comparison,
        )
        packet["run_context"] = {
            "evaluation_date": (
                self.evaluation_date.isoformat() if self.evaluation_date else None
            ),
            "evaluation_date_source": (
                "explicit" if self.evaluation_date else "system_clock"
            ),
            "client_id": self.client_id,
            "entity_id": self.entity_id,
            "jurisdiction_pack": "se-2026",
        }

        packet_path = self._write_packet(packet)
        packet["packet_path"] = str(packet_path)
        if self.queue:
            self.queue.store_pipeline_result(packet, packet_path)
        self._seen_signatures.setdefault(
            invoice_signature,
            {
                "case_id": case_id,
                "source_path": str(path),
                "invoice_number": extracted.get("invoice_number"),
                "gross_amount": extracted["amounts"].get("gross"),
            },
        )
        return packet

    def _check_duplicate(self, invoice_signature: str, case_id: str) -> dict[str, Any]:
        duplicate: dict[str, Any] | None = None
        if self.queue:
            duplicate = self.queue.find_duplicate_signature(
                invoice_signature,
                case_id,
                client_id=self.client_id,
                entity_id=self.entity_id,
            )
        if duplicate is None:
            duplicate = self._seen_signatures.get(invoice_signature)

        if duplicate and duplicate.get("scope_status") == "legacy_unscoped_review":
            return {
                "status": "possible_duplicate",
                "scope_status": "legacy_unscoped_review",
                "duplicate_of_case_id": None,
                "duplicate_source_path": None,
                "flags": [
                    {
                        "code": "possible_duplicate",
                        "severity": "high",
                        "message": (
                            "A matching legacy queue row has no verified legal-entity "
                            "owner. Map both client and entity explicitly before continuing."
                        ),
                    }
                ],
            }

        if duplicate and duplicate.get("case_id") != case_id:
            return {
                "status": "possible_duplicate",
                "duplicate_of_case_id": duplicate.get("case_id"),
                "duplicate_source_path": duplicate.get("source_path"),
                "flags": [
                    {
                        "code": "possible_duplicate",
                        "severity": "high",
                        "message": "Supplier, invoice number, date, and gross amount match an existing case.",
                    }
                ],
            }
        return {
            "status": "unique",
            "duplicate_of_case_id": None,
            "duplicate_source_path": None,
            "flags": [],
        }

    def _write_packet(self, packet: dict[str, Any]) -> Path:
        if not self.output_dir:
            return Path("")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        scenario = packet["case"]["fixture_name"].replace(" ", "_")
        packet_path = self.output_dir / f"{packet['case']['case_id']}_{scenario}.approval_packet.json"
        packet_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return packet_path


def build_approval_packet(
    *,
    now: str,
    case: dict[str, Any],
    document: dict[str, Any],
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    duplicate_check: dict[str, Any],
    vat_proposal: dict[str, Any],
    accounting_proposal: dict[str, Any],
    risk: dict[str, Any],
    risk_findings: tuple[RiskFinding, ...],
    policy_decision: dict[str, Any],
    fortnox_payload: dict[str, Any],
    journal_draft: JournalDraft,
    journal_validation: JournalValidation,
    shadow_ledger_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document_summary = {
        "supplier": extracted.get("supplier_name"),
        "invoice_number": extracted.get("invoice_number"),
        "invoice_date": extracted.get("invoice_date"),
        "due_date": extracted.get("due_date"),
        "currency": extracted.get("currency"),
        "gross_amount": extracted["amounts"].get("gross"),
        "description": extracted.get("description"),
    }
    return {
        "packet_version": "supplier_invoice_autopilot_mvp1.v1",
        "generated_at": now,
        "case": case,
        "document": document,
        "document_summary": document_summary,
        "extracted_fields": extracted,
        "supplier_match": supplier_match,
        "duplicate_check": duplicate_check,
        "vat_proposal": vat_proposal,
        "accounting_proposal": accounting_proposal,
        "risk": risk,
        "risk_findings": findings_to_dicts(risk_findings),
        "policy_decision": policy_decision,
        "journal_binding": {
            "journal_id": journal_draft.journal_id,
            "client_id": journal_draft.client_id,
            "entity_id": journal_draft.entity_id,
        },
        "journal_validation": journal_validation_to_dict(journal_validation),
        "required_human_decision": policy_decision["required_human_decision"],
        "next_action": policy_decision["exact_proposed_external_action"],
        "fortnox_draft_payload": fortnox_payload,
        "shadow_ledger_comparison": shadow_ledger_comparison
        or {
            "status": "disabled",
            "source_of_truth": "fortnox",
            "warnings": ["shadow_ledger_not_requested"],
        },
        "audit_events": [
            {
                "event_type": "intake_case_created",
                "created_at": now,
                "payload": {
                    "case_id": case["case_id"],
                    "file_hash": case["file_hash"],
                    "source": "local_fixture",
                },
            },
            {
                "event_type": "approval_packet_generated",
                "created_at": now,
                "payload": {
                    "case_id": case["case_id"],
                    "policy_mode": policy_decision["mode"],
                    "risk_level": risk["level"],
                    "risk_flags": [flag["code"] for flag in risk["flags"]],
                    "risk_findings": findings_to_dicts(risk_findings),
                    "journal_valid": journal_validation.is_valid,
                    "journal_error_codes": journal_validation.error_codes,
                    "shadow_ledger_status": (
                        shadow_ledger_comparison or {"status": "disabled"}
                    )["status"],
                },
            },
        ],
    }


PIPELINE_MODE_SEVERITY = {
    "draft_only": 1,
    "approval_required": 2,
    "escalation_required": 3,
    "forbidden": 4,
}


def apply_openclaw_findings_to_policy_decision(
    policy_decision: dict[str, Any],
    risk_findings: tuple[RiskFinding, ...],
) -> dict[str, Any]:
    decision = dict(policy_decision)
    reasons = list(decision.get("openclaw_risk_reasons", []))
    required_reviews = set(decision.get("required_reviews", ()))
    for finding in risk_findings:
        impact = finding.policy_impact
        impact_mode = impact.minimum_permission_mode
        if PIPELINE_MODE_SEVERITY.get(impact_mode, 0) > PIPELINE_MODE_SEVERITY.get(
            str(decision["mode"]),
            0,
        ):
            decision["mode"] = impact_mode
            if impact_mode == "forbidden":
                decision["decision"] = "blocked_by_policy"
                decision["required_human_decision"] = (
                    "Stop this case and resolve the blocking Openclaw risk finding before any draft or live external action."
                )
            elif impact_mode == "escalation_required":
                decision["decision"] = "blocked_until_escalation_review"
                decision["required_human_decision"] = (
                    "Senior or specialist review is required before any Fortnox draft may be created later."
                )
            else:
                decision["decision"] = "blocked_until_human_review"
        if impact.reason:
            reasons.append(impact.reason)
        required_reviews.update(impact.required_reviews)

    decision["openclaw_risk_reasons"] = tuple(dict.fromkeys(reasons))
    decision["required_reviews"] = tuple(sorted(required_reviews))
    return decision


def apply_canonical_policy_decision(
    policy_decision: dict[str, Any],
    canonical_decision: PolicyDecision,
) -> dict[str, Any]:
    """Make the typed policy engine the single authority for action mode."""

    decision = dict(policy_decision)
    mode = canonical_decision.permission_mode.value
    decision["mode"] = mode
    decision["policy_version"] = canonical_decision.policy_version
    decision["canonical_policy_reasons"] = canonical_decision.reasons
    decision["required_reviews"] = canonical_decision.required_reviews
    if mode == "draft_only":
        decision["decision"] = "local_packet_ready"
        decision["required_human_decision"] = (
            "Confirm the accounting proposal before any future ERP draft or posting step."
        )
    elif mode == "approval_required":
        decision["decision"] = "blocked_until_human_review"
        decision["required_human_decision"] = (
            "An accountant must resolve the policy reasons before any future ERP draft."
        )
    elif mode == "escalation_required":
        decision["decision"] = "blocked_until_escalation_review"
        decision["required_human_decision"] = (
            "Senior or specialist review is required before any future ERP draft."
        )
    else:
        decision["decision"] = "blocked_by_policy"
        decision["required_human_decision"] = (
            "Stop this case and resolve the blocking policy finding; no permit may be issued."
        )
    exact_action = dict(decision.get("exact_proposed_external_action") or {})
    if mode != "draft_only" and exact_action.get("action", "").startswith("prepare_"):
        exact_action = {
            "action": "none_until_policy_reviewed",
            "reason": "The canonical policy gate requires review before any ERP-shaped draft.",
            "live_api_call": False,
        }
    decision["exact_proposed_external_action"] = exact_action
    return decision


def apply_journal_validation_to_policy(
    policy_decision: dict[str, Any],
    validation: JournalValidation,
) -> dict[str, Any]:
    """Block every downstream draft when canonical double-entry controls fail."""

    decision = dict(policy_decision)
    decision["journal_error_codes"] = validation.error_codes
    if validation.is_valid:
        return decision
    decision["mode"] = "forbidden"
    decision["decision"] = "blocked_by_journal_validation"
    decision["required_reviews"] = ()
    decision["required_human_decision"] = (
        "Correct the journal and supporting evidence before any ERP-shaped draft is prepared."
    )
    decision["exact_proposed_external_action"] = {
        "action": "none_until_journal_corrected",
        "reason": "Canonical double-entry validation failed.",
        "live_api_call": False,
    }
    return decision


def journal_validation_to_dict(validation: JournalValidation) -> dict[str, Any]:
    return {
        "journal_id": validation.journal_id,
        "is_valid": validation.is_valid,
        "error_codes": validation.error_codes,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "line_index": issue.line_index,
            }
            for issue in validation.issues
        ],
        "currency": (
            validation.debit_total.currency if validation.debit_total is not None else None
        ),
        "debit_total_minor": (
            validation.debit_total.minor if validation.debit_total is not None else None
        ),
        "credit_total_minor": (
            validation.credit_total.minor if validation.credit_total is not None else None
        ),
    }


def build_openclaw_risk_findings(
    *,
    case: dict[str, Any],
    client_id: str = "fixture_client",
    document: dict[str, Any],
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    duplicate_check: dict[str, Any],
    vat_proposal: dict[str, Any],
    today: date | None = None,
) -> tuple[RiskFinding, ...]:
    currency = str(extracted.get("currency") or "SEK")
    return review_accounting_case(
        AccountingCase(
            case_id=str(case["case_id"]),
            client_id=client_id,
            amount_minor=minor_amount(extracted["amounts"].get("gross"), currency),
            currency=currency,
            supplier_id=supplier_match.get("supplier_id"),
            supplier_name=extracted.get("supplier_name"),
            supplier_known=supplier_match.get("status") == "matched",
            invoice_number=extracted.get("invoice_number"),
            invoice_date=parse_date(extracted.get("invoice_date")),
            source_document_id=str(document.get("source_filename") or document["file_hash"]),
            source_document_hash=str(document["file_hash"]),
            has_source_document=True,
            ocr_confidence=float(extracted.get("extraction_confidence", 1.0)),
            vat_confidence=1.0 if vat_proposal.get("status") == "normal" else 0.5,
            vat_amount_minor=minor_amount(extracted["amounts"].get("vat"), currency),
            accounting_period=extracted.get("accounting_period"),
            period_locked=bool(extracted.get("period_locked", False)),
            known_supplier_bank_account=supplier_match.get("known_bankgiro"),
            stated_supplier_bank_account=supplier_match.get("invoice_bankgiro"),
            bank_details_changed=supplier_match.get("bank_details_status") == "changed",
            business_purpose=extracted.get("description"),
            description=extracted.get("description"),
            prior_invoices=prior_invoices_from_duplicate_check(
                extracted,
                supplier_match,
                duplicate_check,
            ),
        ),
        today=today,
    )


def build_supplier_invoice_policy_context(
    *,
    client_id: str,
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    duplicate_check: dict[str, Any],
    vat_proposal: dict[str, Any],
    risk_findings: tuple[RiskFinding, ...],
) -> PolicyContext:
    currency = str(extracted.get("currency") or "SEK")
    return PolicyContext(
        action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
        client_id=client_id,
        currency_code=currency,
        amount_minor=minor_amount(extracted["amounts"].get("gross"), currency),
        supplier_known=supplier_match.get("status") == "matched",
        bank_details_changed=supplier_match.get("bank_details_status") == "changed",
        duplicate_risk=(
            1.0 if duplicate_check.get("status") == "possible_duplicate" else 0.0
        ),
        vat_confidence=1.0 if vat_proposal.get("status") == "normal" else 0.5,
        ocr_confidence=float(extracted.get("extraction_confidence") or 0.0),
        period_locked=bool(extracted.get("period_locked", False)),
        risk_findings=risk_findings,
        risk_evidence_complete=True,
    )


def prior_invoices_from_duplicate_check(
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    duplicate_check: dict[str, Any],
) -> tuple[InvoiceHistoryEntry, ...]:
    if duplicate_check.get("status") != "possible_duplicate":
        return ()
    duplicate_case_id = duplicate_check.get("duplicate_of_case_id") or "unknown_duplicate"
    return (
        InvoiceHistoryEntry(
            case_id=str(duplicate_case_id),
            supplier_id=supplier_match.get("supplier_id"),
            supplier_name=extracted.get("supplier_name"),
            invoice_number=extracted.get("invoice_number"),
            amount_minor=minor_amount(
                extracted["amounts"].get("gross"),
                str(extracted.get("currency") or "SEK"),
            ),
            invoice_date=parse_date(extracted.get("invoice_date")),
        ),
    )


def build_fortnox_payload(
    case: dict[str, Any],
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    accounting_proposal: dict[str, Any],
    policy_decision: dict[str, Any],
    *,
    client_id: str,
    entity_id: str,
) -> dict[str, Any]:
    return {
        "target_adapter": "fortnox_supplier_invoice_draft",
        "dry_run": True,
        "live_api_call": False,
        "idempotency_key": f"fortnox-draft:{case['case_id']}",
        "policy_mode": policy_decision["mode"],
        "client_id": canonical_client_id(client_id),
        "entity_id": canonical_client_id(entity_id),
        "supplier_id": supplier_match.get("supplier_id"),
        "supplier_name": extracted.get("supplier_name"),
        "supplier_org_number": extracted.get("supplier_org_number"),
        "invoice_number": extracted.get("invoice_number"),
        "invoice_date": extracted.get("invoice_date"),
        "due_date": extracted.get("due_date"),
        "currency": extracted.get("currency"),
        "total": extracted["amounts"].get("gross"),
        "bankgiro_from_invoice": extracted.get("bankgiro"),
        "bankgiro_matches_known": supplier_match.get("bank_details_status") == "matched",
        "accounting_rows": build_fortnox_accounting_rows(
            accounting_proposal["entries"],
            str(extracted.get("currency") or "SEK"),
        ),
        "blocked_from_live_use": True,
        "blocked_reason": "MVP is dry-run only. A human approval and future guarded adapter are required before live Fortnox use.",
    }


def build_fortnox_accounting_rows(
    accounting_entries: list[dict[str, Any]],
    currency: str = "SEK",
) -> list[dict[str, Any]]:
    return [
        {
            "account": str(entry["account"]),
            "debit_minor": minor_amount(entry.get("debit"), currency),
            "credit_minor": minor_amount(entry.get("credit"), currency),
            "vat_code": entry.get("vat_code"),
            "description": str(entry.get("description") or ""),
        }
        for entry in accounting_entries
    ]


def build_shadow_ledger_comparison(
    *,
    case: dict[str, Any],
    client_id: str = "fixture_client",
    entity_id: str,
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    vat_proposal: dict[str, Any],
    accounting_proposal: dict[str, Any],
    adapter: ShadowLedgerAdapter | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "disabled",
            "source_of_truth": "fortnox",
            "fortnox_payload": None,
            "accounting_proposal": accounting_proposal,
            "shadow_proposal": None,
            "differences": [],
            "warnings": ["shadow_ledger_not_requested"],
            "validations": [],
        }

    proposal = build_shadow_supplier_invoice_proposal(
        case=case,
        client_id=client_id,
        entity_id=entity_id,
        extracted=extracted,
        supplier_match=supplier_match,
        vat_proposal=vat_proposal,
        accounting_proposal=accounting_proposal,
    )
    comparison = mirror_supplier_invoice_proposal_to_shadow(
        proposal,
        adapter=adapter,
    )
    return comparison.to_dict()


def build_shadow_supplier_invoice_proposal(
    *,
    case: dict[str, Any],
    client_id: str = "fixture_client",
    entity_id: str,
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    vat_proposal: dict[str, Any],
    accounting_proposal: dict[str, Any],
) -> SupplierInvoiceProposal:
    amounts = extracted["amounts"]
    currency = extracted.get("currency") or "SEK"
    return SupplierInvoiceProposal(
        proposal_id=f"proposal:{case['case_id']}",
        case_id=case["case_id"],
        client_id=client_id,
        entity_id=entity_id,
        supplier_id=supplier_match.get("supplier_id") or "unknown_supplier",
        supplier_name=extracted.get("supplier_name") or "Unknown supplier",
        invoice_number=extracted.get("invoice_number") or case["case_id"],
        invoice_date=extracted.get("invoice_date") or utc_now()[:10],
        due_date=extracted.get("due_date") or extracted.get("invoice_date") or utc_now()[:10],
        currency=currency,
        net_amount_minor=minor_amount(amounts.get("net"), currency),
        vat_amount_minor=minor_amount(amounts.get("vat"), currency),
        gross_amount_minor=minor_amount(amounts.get("gross"), currency),
        vat_rate_percent=int(as_decimal(extracted.get("vat_rate")) or Decimal("0")),
        expense_account=accounting_proposal["bas_account"],
        vat_account=vat_proposal.get("input_vat_account") or "2641",
        payable_account="2440",
        description=extracted.get("description") or "Supplier invoice",
        confidence=float(accounting_proposal.get("confidence", 0.0)),
        source_document_hash=str(case.get("file_hash") or ""),
        entries=tuple(
            AccountingEntry(
                account=str(entry["account"]),
                debit_minor=minor_amount(entry.get("debit"), currency),
                credit_minor=minor_amount(entry.get("credit"), currency),
                description=str(entry.get("description") or ""),
                vat_code=entry.get("vat_code"),
            )
            for entry in accounting_proposal.get("entries", ())
        ),
    )


def minor_amount(value: Any, currency: str = "SEK") -> int:
    decimal_value = as_decimal(value)
    if decimal_value is None:
        return 0
    return Money.from_major(decimal_value, currency).minor


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def build_invoice_signature(
    extracted: dict[str, Any],
    *,
    client_id: str = "fixture_client",
    entity_id: str,
) -> str:
    supplier_key = extracted.get("supplier_org_number") or extracted.get("supplier_name") or "unknown"
    parts = [
        client_storage_key(canonical_client_id(client_id)),
        client_storage_key(canonical_client_id(entity_id)),
        str(supplier_key).casefold(),
        str(extracted.get("invoice_number") or "").casefold(),
        str(extracted.get("invoice_date") or ""),
        str(extracted["amounts"].get("gross") or ""),
    ]
    return "|".join(parts)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
