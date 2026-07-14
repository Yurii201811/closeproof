from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


REQUIRED_FIELDS = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "amounts",
)


def extract_invoice_fields(fixture: dict[str, Any]) -> dict[str, Any]:
    """Return structured invoice fields from fixture JSON.

    MVP extraction accepts a mocked extraction payload. A tiny text fallback is
    present only to keep the interface honest until real OCR/parser work lands.
    """

    if "mock_extraction" in fixture:
        extracted = dict(fixture["mock_extraction"])
        extracted["source_kind"] = "mock_extraction"
    else:
        extracted = _extract_from_text(fixture.get("ocr_text", ""))
        extracted["source_kind"] = "ocr_text_regex_stub"

    extracted.setdefault("supplier_org_number", None)
    extracted.setdefault("due_date", None)
    extracted.setdefault("description", fixture.get("description", "Supplier invoice"))
    extracted.setdefault("bankgiro", None)
    extracted.setdefault("iban", None)
    extracted.setdefault("vat_rate", None)
    extracted.setdefault("extraction_confidence", 0.5)
    extracted.setdefault("field_confidence", {})
    extracted["supplier_org_number"] = normalize_org_number(extracted.get("supplier_org_number"))
    extracted["bankgiro"] = normalize_bankgiro(extracted.get("bankgiro"))
    extracted["amounts"] = normalize_amounts(extracted.get("amounts", {}))
    extracted["missing_required_fields"] = missing_required_fields(extracted)
    extracted["ocr_text_excerpt"] = (fixture.get("ocr_text") or "")[:500]
    return extracted


def normalize_org_number(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def normalize_bankgiro(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", "", value)


def normalize_amounts(amounts: dict[str, Any]) -> dict[str, str | None]:
    return {
        "net": money(amounts.get("net")),
        "vat": money(amounts.get("vat")),
        "gross": money(amounts.get("gross")),
    }


def missing_required_fields(extracted: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        if not extracted.get(field):
            missing.append(field)
    amounts = extracted.get("amounts") or {}
    for amount_field in ("net", "vat", "gross"):
        if not amounts.get(amount_field):
            missing.append(f"amounts.{amount_field}")
    return missing


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def money(value: Any) -> str | None:
    decimal_value = as_decimal(value)
    if decimal_value is None:
        return None
    return str(decimal_value.quantize(Decimal("0.01")))


def _extract_from_text(text: str) -> dict[str, Any]:
    invoice_number = _match(text, r"(?:Faktura|Invoice)\s*[:#]?\s*([A-Z0-9-]+)")
    invoice_date = _match(text, r"(?:Fakturadatum|Invoice date)\s*:?\s*(\d{4}-\d{2}-\d{2})")
    gross = _match(text, r"(?:Att betala|Total)\s*:?\s*([0-9]+(?:[,.][0-9]{2})?)")
    vat = _match(text, r"(?:Moms|VAT)\s*(?:25%)?\s*:?\s*([0-9]+(?:[,.][0-9]{2})?)")
    net = _match(text, r"(?:Netto|Net)\s*:?\s*([0-9]+(?:[,.][0-9]{2})?)")
    supplier_name = _match(text, r"(?:Leverantor|Supplier)\s*:?\s*(.+)")
    org_number = _match(text, r"(?:Org\.nr|Org nr)\s*:?\s*([0-9 -]+)")
    return {
        "supplier_name": supplier_name,
        "supplier_org_number": org_number,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": None,
        "currency": "SEK",
        "amounts": {"net": net, "vat": vat, "gross": gross},
        "vat_rate": 25,
        "description": "Regex-extracted supplier invoice",
        "extraction_confidence": 0.45,
    }


def _match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()
