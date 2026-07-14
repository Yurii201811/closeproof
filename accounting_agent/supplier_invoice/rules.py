from __future__ import annotations

from decimal import Decimal
from typing import Any

from .extraction import as_decimal, normalize_bankgiro, normalize_org_number


SUPPLIERS: dict[str, dict[str, Any]] = {
    "5566778899": {
        "supplier_id": "SUP-001",
        "name": "Nordic Office Supplies AB",
        "bankgiro": "123-4567",
        "default_bas_account": "6110",
        "default_bas_name": "Kontorsmateriel",
    },
    "5599001122": {
        "supplier_id": "SUP-002",
        "name": "Svea IT Konsult AB",
        "bankgiro": "987-6543",
        "default_bas_account": "6540",
        "default_bas_name": "IT-tjanster",
    },
    "5590011101": {
        "supplier_id": "SUP-FIK-001",
        "name": "Fiktiv Kontorspartner AB",
        "bankgiro": "111-1101",
        "default_bas_account": "6110",
        "default_bas_name": "Kontorsmateriel",
    },
    "5590011102": {
        "supplier_id": "SUP-FIK-002",
        "name": "Fiktiv IT Support AB",
        "bankgiro": "111-1102",
        "default_bas_account": "6540",
        "default_bas_name": "IT-tjanster",
    },
    "5590011103": {
        "supplier_id": "SUP-FIK-003",
        "name": "Fiktiv Lokalhyra AB",
        "bankgiro": "111-1103",
        "default_bas_account": "5010",
        "default_bas_name": "Lokalhyra",
    },
    "5590011104": {
        "supplier_id": "SUP-FIK-004",
        "name": "Fiktiv Studioverktyg AB",
        "bankgiro": "111-1104",
        "default_bas_account": "5410",
        "default_bas_name": "Forbrukningsinventarier",
    },
    "5590011105": {
        "supplier_id": "SUP-FIK-005",
        "name": "Fiktiv Mobiloperator AB",
        "bankgiro": "111-1105",
        "default_bas_account": "6212",
        "default_bas_name": "Mobiltelefon",
    },
    "5590011106": {
        "supplier_id": "SUP-FIK-006",
        "name": "Fiktiv Stadservice AB",
        "bankgiro": "111-1106",
        "default_bas_account": "5060",
        "default_bas_name": "Stadning och renhallning",
    },
    "5590011107": {
        "supplier_id": "SUP-FIK-007",
        "name": "Fiktiv Forsakring AB",
        "bankgiro": "111-1107",
        "default_bas_account": "6310",
        "default_bas_name": "Foretagsforsakringar",
    },
    "5590011108": {
        "supplier_id": "SUP-FIK-008",
        "name": "Fiktiv Bokforing Online AB",
        "bankgiro": "111-1108",
        "default_bas_account": "6540",
        "default_bas_name": "IT-tjanster",
    },
}

BAS_FALLBACKS = {
    "office": ("6110", "Kontorsmateriel"),
    "kontor": ("6110", "Kontorsmateriel"),
    "it": ("6540", "IT-tjanster"),
    "konsult": ("6540", "IT-tjanster"),
    "event": ("6991", "Ovriga externa kostnader, avdragsgilla"),
}

SE_PREVIEW_SUPPLIER_CHART_ID = "se-bas-supplier-preview-2026-v1"
SE_PREVIEW_SUPPLIER_ACCOUNTS = frozenset(
    {"2440", "2641"}
    | {str(supplier["default_bas_account"]) for supplier in SUPPLIERS.values()}
    | {account for account, _name in BAS_FALLBACKS.values()}
)

FLAG_WEIGHTS = {
    "possible_duplicate": 35,
    "unknown_supplier": 30,
    "changed_bank_details": 45,
    "low_extraction_confidence": 20,
    "missing_required_fields": 20,
    "vat_amount_mismatch": 30,
    "gross_amount_mismatch": 20,
    "unsupported_or_missing_vat_rate": 20,
}

VALID_SWEDISH_VAT_RATES = {Decimal("0"), Decimal("6"), Decimal("12"), Decimal("25")}


def match_supplier(extracted: dict[str, Any]) -> dict[str, Any]:
    org_number = normalize_org_number(extracted.get("supplier_org_number"))
    supplier = SUPPLIERS.get(org_number or "")
    if not supplier:
        supplier = _match_supplier_by_name(extracted.get("supplier_name"))

    if not supplier:
        return {
            "status": "unknown",
            "supplier_id": None,
            "matched_name": None,
            "confidence": 0.25,
            "bank_details_status": "unknown",
            "flags": [
                {
                    "code": "unknown_supplier",
                    "severity": "medium",
                    "message": "Supplier is not present in the local supplier registry placeholder.",
                }
            ],
        }

    invoice_bankgiro = normalize_bankgiro(extracted.get("bankgiro"))
    known_bankgiro = normalize_bankgiro(supplier.get("bankgiro"))
    flags: list[dict[str, str]] = []
    bank_status = "matched"
    confidence = 0.97
    if invoice_bankgiro and known_bankgiro and invoice_bankgiro != known_bankgiro:
        bank_status = "changed"
        confidence = 0.76
        flags.append(
            {
                "code": "changed_bank_details",
                "severity": "high",
                "message": "Invoice bankgiro differs from the known supplier bankgiro.",
            }
        )

    return {
        "status": "matched",
        "supplier_id": supplier["supplier_id"],
        "matched_name": supplier["name"],
        "confidence": confidence,
        "bank_details_status": bank_status,
        "known_bankgiro": supplier.get("bankgiro"),
        "invoice_bankgiro": invoice_bankgiro,
        "default_bas_account": supplier["default_bas_account"],
        "default_bas_name": supplier["default_bas_name"],
        "flags": flags,
    }


def propose_vat(extracted: dict[str, Any]) -> dict[str, Any]:
    amounts = extracted["amounts"]
    net = as_decimal(amounts.get("net"))
    vat = as_decimal(amounts.get("vat"))
    gross = as_decimal(amounts.get("gross"))
    vat_rate = as_decimal(extracted.get("vat_rate"))
    flags: list[dict[str, str]] = []

    if float(extracted.get("extraction_confidence", 0)) < 0.75:
        flags.append(
            {
                "code": "low_extraction_confidence",
                "severity": "medium",
                "message": "Extraction confidence is below the MVP review threshold.",
            }
        )

    if extracted.get("missing_required_fields"):
        flags.append(
            {
                "code": "missing_required_fields",
                "severity": "medium",
                "message": "One or more required invoice fields are missing.",
            }
        )

    if vat_rate is None or vat_rate not in VALID_SWEDISH_VAT_RATES:
        flags.append(
            {
                "code": "unsupported_or_missing_vat_rate",
                "severity": "medium",
                "message": "VAT rate is missing or outside the standard Swedish VAT set.",
            }
        )
    elif net is not None and vat is not None:
        expected_vat = (net * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        if abs(expected_vat - vat) > Decimal("1.00"):
            flags.append(
                {
                    "code": "vat_amount_mismatch",
                    "severity": "high",
                    "message": f"VAT amount {vat} does not match expected {expected_vat} at {vat_rate}%.",
                }
            )

    if net is not None and vat is not None and gross is not None:
        expected_gross = (net + vat).quantize(Decimal("0.01"))
        if abs(expected_gross - gross) > Decimal("1.00"):
            flags.append(
                {
                    "code": "gross_amount_mismatch",
                    "severity": "medium",
                    "message": f"Gross amount {gross} does not match net plus VAT {expected_gross}.",
                }
            )

    return {
        "status": "normal" if not flags else "manual_review",
        "vat_rate": str(vat_rate) if vat_rate is not None else None,
        "input_vat_account": "2641",
        "deductible_vat": amounts.get("vat"),
        "flags": flags,
    }


def propose_accounting(
    extracted: dict[str, Any],
    supplier_match: dict[str, Any],
    vat_proposal: dict[str, Any],
) -> dict[str, Any]:
    bas_account, bas_name, basis = _choose_bas_account(extracted, supplier_match)
    amounts = extracted["amounts"]
    confidence = Decimal("0.86")
    if supplier_match["status"] != "matched":
        confidence -= Decimal("0.20")
    if supplier_match.get("bank_details_status") == "changed":
        confidence -= Decimal("0.15")
    if vat_proposal["status"] != "normal":
        confidence -= Decimal("0.20")
    if float(extracted.get("extraction_confidence", 0)) < 0.75:
        confidence -= Decimal("0.10")
    confidence = max(Decimal("0.15"), confidence)

    entries = [
        {
            "account": bas_account,
            "account_name": bas_name,
            "debit": amounts.get("net"),
            "credit": "0.00",
            "vat_code": "input_vat_25" if vat_proposal.get("vat_rate") == "25" else "input_vat_review",
            "description": extracted.get("description"),
        }
    ]
    if (as_decimal(amounts.get("vat")) or Decimal("0")) != 0:
        entries.append(
            {
                "account": "2641",
                "account_name": "Debiterad ingaende moms",
                "debit": amounts.get("vat"),
                "credit": "0.00",
                "vat_code": "input_vat",
                "description": "Input VAT from supplier invoice",
            }
        )
    entries.append(
        {
            "account": "2440",
            "account_name": "Leverantorsskulder",
            "debit": "0.00",
            "credit": amounts.get("gross"),
            "vat_code": None,
            "description": "Supplier invoice payable, draft only",
        }
    )

    return {
        "proposal_type": "supplier_invoice_accounting_proposal",
        "bas_account": bas_account,
        "bas_account_name": bas_name,
        "bas_basis": basis,
        "entries": entries,
        "confidence": float(confidence),
        "rationale": "Draft BAS/VAT coding only. Human approval is required before any external posting.",
    }


def score_risk(*flag_groups: list[dict[str, str]]) -> dict[str, Any]:
    flags = [flag for group in flag_groups for flag in group]
    score = min(100, sum(FLAG_WEIGHTS.get(flag["code"], 10) for flag in flags))
    if score >= 60 or any(flag.get("severity") == "high" for flag in flags):
        level = "high"
    elif score >= 25:
        level = "medium"
    else:
        level = "low"
    return {
        "score": score,
        "level": level,
        "flags": flags,
    }


def decide_policy(risk: dict[str, Any]) -> dict[str, Any]:
    flag_codes = {flag["code"] for flag in risk["flags"]}
    blocked_actions = [
        "post_to_fortnox",
        "approve_supplier_invoice",
        "start_or_approve_payment",
        "send_supplier_or_client_email",
        "file_tax_or_vat_return",
    ]
    if "changed_bank_details" in flag_codes:
        blocked_actions.append("update_supplier_bank_details")

    if flag_codes:
        mode = "approval_required"
        decision = "blocked_until_human_review"
        required_human_decision = (
            "Review risk flags, confirm supplier/invoice/VAT treatment, and decide whether a Fortnox draft may be created later."
        )
    else:
        mode = "draft_only"
        decision = "local_packet_ready"
        required_human_decision = (
            "Confirm the accounting proposal before any future Fortnox draft or posting step."
        )

    return {
        "mode": mode,
        "decision": decision,
        "allowed_local_actions": [
            "store_intake_case",
            "store_extracted_fields",
            "store_accounting_proposal",
            "store_approval_packet",
            "prepare_dry_run_fortnox_payload",
        ],
        "blocked_actions": blocked_actions,
        "required_human_decision": required_human_decision,
        "exact_proposed_external_action": _external_action_for_flags(flag_codes),
    }


def _choose_bas_account(
    extracted: dict[str, Any], supplier_match: dict[str, Any]
) -> tuple[str, str, str]:
    if supplier_match.get("default_bas_account"):
        return (
            supplier_match["default_bas_account"],
            supplier_match["default_bas_name"],
            "matched_supplier_default",
        )

    text = " ".join(
        str(part or "").lower()
        for part in (extracted.get("supplier_name"), extracted.get("description"))
    )
    for keyword, account in BAS_FALLBACKS.items():
        if keyword in text:
            return account[0], account[1], f"keyword:{keyword}"
    return "6991", "Ovriga externa kostnader, avdragsgilla", "fallback_unknown_supplier"


def _match_supplier_by_name(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    normalized = name.casefold().strip()
    for supplier in SUPPLIERS.values():
        if supplier["name"].casefold() == normalized:
            return supplier
    return None


def _external_action_for_flags(flag_codes: set[str]) -> dict[str, Any]:
    if "possible_duplicate" in flag_codes:
        action = "none_until_duplicate_reviewed"
        reason = "Possible duplicate invoice detected."
    elif "changed_bank_details" in flag_codes:
        action = "none_until_bank_details_verified"
        reason = "Invoice payment details differ from known supplier data."
    elif "unknown_supplier" in flag_codes:
        action = "none_until_supplier_created_or_matched"
        reason = "Supplier is unknown to the local registry placeholder."
    elif flag_codes:
        action = "none_until_extraction_and_vat_reviewed"
        reason = "Invoice extraction or VAT treatment needs human review."
    else:
        action = "prepare_fortnox_supplier_invoice_draft_payload_only"
        reason = "Low-risk local proposal. Live Fortnox calls remain disabled."

    return {
        "target": "fortnox",
        "action": action,
        "reason": reason,
        "live_api_call": False,
        "posts_bookkeeping": False,
        "sends_email": False,
        "starts_payment": False,
        "requires_human_approval_before_live_use": True,
    }
