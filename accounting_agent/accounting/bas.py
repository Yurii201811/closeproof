"""Small local BAS account-plan subset for draft validation.

The full BAS plan changes over time and should eventually be loaded from
versioned rules data. This subset is deliberately narrow and fixture-oriented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class BasAccount:
    number: str
    name: str
    account_type: str
    vat_supported: bool = False


DEFAULT_BAS_ACCOUNT_PLAN: dict[str, BasAccount] = {
    "2440": BasAccount(
        number="2440",
        name="Leverantorsskulder",
        account_type="liability",
    ),
    "2641": BasAccount(
        number="2641",
        name="Debiterad ingaende moms",
        account_type="asset",
        vat_supported=True,
    ),
    "4010": BasAccount(
        number="4010",
        name="Inkop av material och varor",
        account_type="expense",
        vat_supported=True,
    ),
    "5010": BasAccount(
        number="5010",
        name="Lokalhyra",
        account_type="expense",
        vat_supported=True,
    ),
    "5060": BasAccount(
        number="5060",
        name="Stadning och renhallning",
        account_type="expense",
        vat_supported=True,
    ),
    "5410": BasAccount(
        number="5410",
        name="Forbrukningsinventarier",
        account_type="expense",
        vat_supported=True,
    ),
    "6110": BasAccount(
        number="6110",
        name="Kontorsmaterial",
        account_type="expense",
        vat_supported=True,
    ),
    "6540": BasAccount(
        number="6540",
        name="IT-tjänster",
        account_type="expense",
        vat_supported=True,
    ),
    "6212": BasAccount(
        number="6212",
        name="Mobiltelefon",
        account_type="expense",
        vat_supported=True,
    ),
    "6310": BasAccount(
        number="6310",
        name="Foretagsforsakringar",
        account_type="expense",
        vat_supported=False,
    ),
    "6570": BasAccount(
        number="6570",
        name="Bankkostnader",
        account_type="expense",
        vat_supported=False,
    ),
}


class AccountPlan:
    """Read-only account lookup used by the local shadow-ledger adapter."""

    def __init__(self, accounts: Mapping[str, BasAccount] | None = None) -> None:
        self._accounts = dict(accounts or DEFAULT_BAS_ACCOUNT_PLAN)

    def lookup(self, account_number: str) -> BasAccount | None:
        return self._accounts.get(_normalise_account(account_number))

    def require(self, account_number: str) -> BasAccount:
        account = self.lookup(account_number)
        if account is None:
            raise KeyError(f"unknown BAS account: {account_number}")
        return account

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {
            number: {
                "number": account.number,
                "name": account.name,
                "account_type": account.account_type,
                "vat_supported": account.vat_supported,
            }
            for number, account in sorted(self._accounts.items())
        }


def _normalise_account(account_number: str) -> str:
    return str(account_number).strip()
