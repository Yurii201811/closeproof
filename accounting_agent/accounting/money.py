"""Currency-safe money primitives for the v1 accounting control plane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit

from accounting_agent.jurisdictions import get_currency_spec


class CurrencyAmountError(ValueError):
    """Raised when money or exchange-rate evidence is ambiguous or invalid."""


def _currency_code(value: str) -> str:
    code = str(value).strip().upper()
    try:
        get_currency_spec(code)
    except ValueError as exc:
        raise CurrencyAmountError(str(exc)) from exc
    return code


@dataclass(frozen=True)
class ExchangeRateEvidence:
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: str
    source_uri: str
    source_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_currency", _currency_code(self.base_currency))
        object.__setattr__(self, "quote_currency", _currency_code(self.quote_currency))
        if self.base_currency == self.quote_currency:
            raise CurrencyAmountError("exchange-rate currencies must differ")
        if not isinstance(self.rate, Decimal) or not self.rate.is_finite() or self.rate <= 0:
            raise CurrencyAmountError("exchange rate must be a positive finite Decimal")
        try:
            date.fromisoformat(self.rate_date)
        except ValueError as exc:
            raise CurrencyAmountError("exchange-rate date must be ISO YYYY-MM-DD") from exc
        parsed = urlsplit(self.source_uri)
        if parsed.scheme not in {"https", "http", "evidence"} or not (
            parsed.netloc or parsed.path.strip("/")
        ):
            raise CurrencyAmountError("exchange-rate evidence requires an absolute source URI")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.source_sha256):
            raise CurrencyAmountError("exchange-rate evidence requires a SHA-256 digest")
        object.__setattr__(self, "source_sha256", self.source_sha256.lower())


@dataclass(frozen=True)
class Money:
    """An exact amount bound to an explicit ISO-style currency precision."""

    minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise CurrencyAmountError("money minor amount must be an integer")
        object.__setattr__(self, "currency", _currency_code(self.currency))

    @classmethod
    def from_major(cls, value: str | int | Decimal, currency: str) -> "Money":
        if isinstance(value, bool) or isinstance(value, float):
            raise CurrencyAmountError("major amounts must use str, int, or Decimal, never float")
        code = _currency_code(currency)
        try:
            amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise CurrencyAmountError("major amount is not a valid decimal") from exc
        if not amount.is_finite():
            raise CurrencyAmountError("major amount must be finite")
        factor = Decimal(10) ** get_currency_spec(code).minor_units
        minor = int((amount * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cls(minor=minor, currency=code)

    @property
    def major(self) -> Decimal:
        factor = Decimal(10) ** get_currency_spec(self.currency).minor_units
        return Decimal(self.minor) / factor

    def convert(
        self,
        evidence: ExchangeRateEvidence,
        *,
        transaction_date: str,
        max_rate_age_days: int = 3,
    ) -> "Money":
        if self.currency != evidence.base_currency:
            raise CurrencyAmountError("exchange-rate base currency does not match the amount")
        try:
            transaction = date.fromisoformat(transaction_date)
        except (TypeError, ValueError) as exc:
            raise CurrencyAmountError("transaction date must be ISO YYYY-MM-DD") from exc
        if (
            isinstance(max_rate_age_days, bool)
            or not isinstance(max_rate_age_days, int)
            or max_rate_age_days < 0
            or max_rate_age_days > 31
        ):
            raise CurrencyAmountError("max_rate_age_days must be an integer from 0 to 31")
        rate_date = date.fromisoformat(evidence.rate_date)
        age_days = (transaction - rate_date).days
        if age_days < 0:
            raise CurrencyAmountError("exchange-rate evidence cannot be dated after the transaction")
        if age_days > max_rate_age_days:
            raise CurrencyAmountError("exchange-rate evidence is stale for the transaction date")
        return Money.from_major(self.major * evidence.rate, evidence.quote_currency)

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.minor - other.minor, self.currency)

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyAmountError("money arithmetic requires matching currencies")
