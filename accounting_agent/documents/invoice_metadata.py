"""Best-effort invoice metadata extraction for local fixtures.

This is intentionally conservative. It recognizes simple text labels in local
fixtures and leaves OCR/PDF extraction to a later integration layer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from accounting_agent.client_identity import canonical_client_id
from accounting_agent.jurisdictions import get_currency_spec


_LABELS = {
    "invoice_number": re.compile(
        r"(?im)^\s*(invoice\s*(number|no\.?)|fakturanummer|faktura\s*nr)\s*[:#-]\s*(?P<value>.+?)\s*$"
    ),
    "supplier": re.compile(
        r"(?im)^\s*(supplier|vendor|leverantor)\s*[:#-]\s*(?P<value>.+?)\s*$"
    ),
    "invoice_date": re.compile(
        r"(?im)^\s*(invoice\s*date|date|fakturadatum)\s*[:#-]\s*(?P<value>\d{4}-\d{2}-\d{2})\s*$"
    ),
    "amount": re.compile(
        r"(?im)^\s*(amount|total|summa)\s*[:#-]\s*(?P<value>.+?)\s*$"
    ),
}


@dataclass(frozen=True)
class InvoiceMetadata:
    invoice_number: str | None = None
    supplier: str | None = None
    invoice_date: str | None = None
    amount_minor: int | None = None
    currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def duplicate_key(self, *, client_id: str) -> str | None:
        """Return a deterministic metadata key when enough fields are present."""

        if not self.invoice_number or not self.supplier:
            return None
        parts = [
            canonical_client_id(client_id),
            _normalize(self.supplier),
            _normalize(self.invoice_number),
            _normalize(self.invoice_date or ""),
            str(self.amount_minor or ""),
            _normalize(self.currency or ""),
        ]
        return "|".join(parts)


def extract_invoice_metadata(path: str | Path) -> InvoiceMetadata:
    """Extract simple invoice fields from text-like local files."""

    text = _read_small_text(Path(path))
    if not text:
        return InvoiceMetadata()

    raw_amount = _first_match(text, "amount")
    amount_minor, currency = _parse_amount(raw_amount)
    return InvoiceMetadata(
        invoice_number=_first_match(text, "invoice_number"),
        supplier=_first_match(text, "supplier"),
        invoice_date=_first_match(text, "invoice_date"),
        amount_minor=amount_minor,
        currency=currency,
    )


def _read_small_text(path: Path, *, limit: int = 256_000) -> str:
    try:
        data = path.read_bytes()[:limit]
    except OSError:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _first_match(text: str, field: str) -> str | None:
    match = _LABELS[field].search(text)
    if match is None:
        return None
    value = " ".join(match.group("value").strip().split())
    return value or None


def _parse_amount(value: str | None) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    match = re.search(r"(?P<amount>-?\d[\d\s.,]*)\s*(?P<currency>[A-Za-z]{3})?", value)
    if match is None:
        return None, None

    currency = _currency(match)
    if currency is None:
        return None, None
    try:
        exponent = get_currency_spec(currency).minor_units
    except ValueError:
        # Keep the extracted currency code for review, but never guess its
        # monetary precision.  Unknown ISO records fail closed.
        return None, currency
    amount = _normalize_decimal_text(match.group("amount"), decimal_places=exponent)
    if amount is None:
        # A lone separator followed by three digits is ambiguous for
        # three-decimal currencies: it may be either a decimal mark or a
        # thousands grouping mark.  Without locale evidence, fail closed.
        return None, currency

    try:
        decimal_amount = Decimal(amount)
    except InvalidOperation:
        return None, currency

    factor = Decimal(10) ** exponent
    minor = int((decimal_amount * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return minor, currency


def _normalize_decimal_text(value: str, *, decimal_places: int = 2) -> str | None:
    """Normalize common Swedish and international thousands/decimal styles."""

    amount = value.replace(" ", "").replace("\u00a0", "")
    separators = [separator for separator in (",", ".") if separator in amount]
    if len(separators) == 2:
        decimal_separator = max(separators, key=amount.rfind)
        thousands_separator = "," if decimal_separator == "." else "."
        return amount.replace(thousands_separator, "").replace(decimal_separator, ".")

    if not separators:
        return amount

    separator = separators[0]
    pieces = amount.split(separator)
    if len(pieces) > 2:
        if all(len(piece) == 3 for piece in pieces[1:]):
            return "".join(pieces)
        return "".join(pieces[:-1]) + "." + pieces[-1]

    whole, fraction = pieces
    # A single three-digit suffix is more likely a grouping mark than decimals.
    if len(fraction) == 3 and decimal_places == 3:
        return None
    if len(fraction) == 3:
        return whole + fraction
    return whole + "." + fraction


def _currency(match: re.Match[str]) -> str | None:
    currency = match.group("currency")
    return currency.upper() if currency else None


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())
