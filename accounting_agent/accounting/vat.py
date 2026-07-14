"""Local VAT mapping checks for supplier-invoice draft proposals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PurchaseVATMapping:
    vat_rate_percent: int
    vat_code: str
    input_vat_account: str | None
    description: str


PURCHASE_VAT_MAPPINGS: dict[int, PurchaseVATMapping] = {
    25: PurchaseVATMapping(
        vat_rate_percent=25,
        vat_code="INPUT_SE_25",
        input_vat_account="2641",
        description="Swedish input VAT, 25 percent",
    ),
    12: PurchaseVATMapping(
        vat_rate_percent=12,
        vat_code="INPUT_SE_12",
        input_vat_account="2641",
        description="Swedish input VAT, 12 percent",
    ),
    6: PurchaseVATMapping(
        vat_rate_percent=6,
        vat_code="INPUT_SE_6",
        input_vat_account="2641",
        description="Swedish input VAT, 6 percent",
    ),
    0: PurchaseVATMapping(
        vat_rate_percent=0,
        vat_code="INPUT_SE_0",
        input_vat_account=None,
        description="No Swedish input VAT expected",
    ),
}


def expected_purchase_vat_mapping(vat_rate_percent: int) -> PurchaseVATMapping | None:
    return PURCHASE_VAT_MAPPINGS.get(int(vat_rate_percent))


def expected_vat_amount_minor(net_amount_minor: int, vat_rate_percent: int) -> int:
    return round(net_amount_minor * int(vat_rate_percent) / 100)
