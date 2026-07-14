"""Versioned jurisdiction metadata for the local accounting platform.

These declarations describe evidence and review requirements. They are not a
tax engine and do not make a country-compliance claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class CurrencySpec:
    code: str
    minor_units: int
    name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaxRuleMetadata:
    rule_id: str
    label: str
    rate_basis_points: int | None
    effective_from: str
    effective_to: str | None
    scope_note: str
    source_url: str
    human_review_required: bool = True

    def __post_init__(self) -> None:
        date.fromisoformat(self.effective_from)
        if self.effective_to:
            date.fromisoformat(self.effective_to)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JurisdictionPack:
    pack_id: str
    name: str
    country_code: str | None
    functional_currency: str | None
    locales: tuple[str, ...]
    chart_of_accounts: str | None
    chart_version: str | None
    interoperability_formats: tuple[str, ...]
    retention_years: int | None
    storage_default_country: str | None
    tax_rules: tuple[TaxRuleMetadata, ...]
    human_review_triggers: tuple[str, ...]
    compliance_status: str
    compliance_note: str
    source_urls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tax_rules"] = [rule.to_dict() for rule in self.tax_rules]
        return payload


CURRENCY_SPECS: dict[str, CurrencySpec] = {
    item.code: item
    for item in (
        CurrencySpec("SEK", 2, "Swedish krona"),
        CurrencySpec("EUR", 2, "Euro"),
        CurrencySpec("USD", 2, "US dollar"),
        CurrencySpec("GBP", 2, "Pound sterling"),
        CurrencySpec("JPY", 0, "Japanese yen"),
        CurrencySpec("KWD", 3, "Kuwaiti dinar"),
        CurrencySpec("BHD", 3, "Bahraini dinar"),
    )
}


SWEDEN_2026 = JurisdictionPack(
    pack_id="se-2026",
    name="Sweden 2026",
    country_code="SE",
    functional_currency="SEK",
    locales=("sv-SE", "en-GB"),
    chart_of_accounts="BAS",
    chart_version="2026",
    interoperability_formats=(
        "SIE 4C",
        "Peppol BIS Billing 3",
        "EN 16931",
        "UBL 2.1",
    ),
    retention_years=7,
    storage_default_country="SE",
    tax_rules=(
        TaxRuleMetadata(
            rule_id="se-food-vat-2026-04-01",
            label="Food VAT from 1 April 2026",
            rate_basis_points=600,
            effective_from="2026-04-01",
            effective_to=None,
            scope_note=(
                "Food and takeaway classification only; restaurant/cafe service remains "
                "a separate 12% classification and mixed supplies need review."
            ),
            source_url=(
                "https://www.skatteverket.se/foretag/moms/saljavarorochtjanster/"
                "momssatserochundantagfranmoms.4.58d555751259e4d66168000409.html"
            ),
            human_review_required=True,
        ),
    ),
    human_review_triggers=(
        "uncertain_vat",
        "vat_exemption",
        "reverse_charge",
        "import_vat",
        "oss_or_cross_border_vat",
        "mixed_supply",
        "unknown_tax_point",
    ),
    compliance_status="foundation_only",
    compliance_note=(
        "Sweden-first metadata and review boundaries. This local fixture runtime is not "
        "a compliant archive, tax engine, filing service, or substitute for accountant review."
    ),
    source_urls=(
        "https://www.riksdagen.se/sv/dokument-och-lagar/dokument/"
        "svensk-forfattningssamling/bokforingslag-19991078_sfs-1999-1078/",
        "https://www.bfn.se/redovisningsregler/beslutade-redovisningsregler/",
        "https://www.bas.se/kontoplaner/",
        "https://sie.se/wp-content/uploads/2026/02/SIE_filformat_ver_4C_2025-08-06.pdf",
        "https://docs.peppol.eu/poac/docs/pintdocs/pint/guide/",
    ),
)


INTERNATIONAL_CORE = JurisdictionPack(
    pack_id="international-core",
    name="International schema core",
    country_code=None,
    functional_currency=None,
    locales=("en-GB",),
    chart_of_accounts=None,
    chart_version=None,
    interoperability_formats=(
        "ISO 3166",
        "ISO 4217",
        "BCP 47",
        "ISO 20022 extension point",
        "Peppol PINT extension point",
    ),
    retention_years=None,
    storage_default_country=None,
    tax_rules=(),
    human_review_triggers=(
        "jurisdiction_pack_missing",
        "tax_rule_missing_or_expired",
        "cross_border_transaction",
        "currency_conversion_missing",
        "tax_registration_unknown",
    ),
    compliance_status="schema_only",
    compliance_note=(
        "Common country, currency, locale, evidence, tax-point, exchange-rate, "
        "dimension, and posting-book primitives. No country tax compliance is implied."
    ),
)


JURISDICTION_PACKS: dict[str, JurisdictionPack] = {
    SWEDEN_2026.pack_id: SWEDEN_2026,
    INTERNATIONAL_CORE.pack_id: INTERNATIONAL_CORE,
}


def list_jurisdiction_packs() -> tuple[JurisdictionPack, ...]:
    return tuple(JURISDICTION_PACKS[key] for key in sorted(JURISDICTION_PACKS))


def get_jurisdiction_pack(pack_id: str) -> JurisdictionPack:
    try:
        return JURISDICTION_PACKS[pack_id]
    except KeyError as exc:
        raise ValueError(f"Unknown jurisdiction pack: {pack_id}") from exc


def get_currency_spec(code: str) -> CurrencySpec:
    normalized = code.upper()
    try:
        return CURRENCY_SPECS[normalized]
    except KeyError as exc:
        raise ValueError(f"Currency requires an explicit ISO 4217 minor-unit record: {code}") from exc


def jurisdiction_registry_summary() -> dict[str, Any]:
    return {
        "default_pack": SWEDEN_2026.pack_id,
        "packs": [pack.to_dict() for pack in list_jurisdiction_packs()],
        "currencies": [
            CURRENCY_SPECS[code].to_dict() for code in sorted(CURRENCY_SPECS)
        ],
        "compliance_claim": "none_until_a_versioned_country_pack_is_validated",
    }
