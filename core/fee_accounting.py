"""Block 5E: pure fee-currency classification against venue instrument rules.

This module owns exactly one decision: whether a component-reported fee is
denominated in the one currency this settlement path can account for
exactly - the instrument's quote asset - or must be refused before it
reaches durable settlement. It carries no fee-rate policy, no fee schedule,
and no FX conversion; none of those exist anywhere in this repository, and
none are invented here. A base-asset fee, a third-asset fee (e.g. BNB), and
an undeclared nonzero fee currency are all rejected the same way: fail
closed, never assumed to be quote currency.

``FeeNormalizer`` is used by ``ExecutionManager`` only. It has no authority
over sizing (``PositionSizingService``), approval (``RiskEngine``), or
durable financial state (``ExecutionPortfolioFoundation``) - it only tells
the caller whether the fee already carried on an ``ExecutionResult`` may be
settled as-is.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from core.instrument_rules import InstrumentRules


class FeeRejectionReason(str, Enum):
    UNDECLARED_FEE_CURRENCY = "UNDECLARED_FEE_CURRENCY"
    BASE_ASSET_FEE_UNSUPPORTED = "BASE_ASSET_FEE_UNSUPPORTED"
    THIRD_ASSET_FEE_UNSUPPORTED = "THIRD_ASSET_FEE_UNSUPPORTED"
    INVALID_FEE_AMOUNT = "INVALID_FEE_AMOUNT"


@dataclass(frozen=True, slots=True)
class NormalizedFee:
    """A fee this settlement path is authorized to account for.

    Always quote-asset denominated: that is the only currency 5E settles
    exactly, so nothing downstream needs to re-check the denomination.
    """

    quote_amount: Decimal
    currency: str


class FeeRejected(ValueError):
    """Raised when a reported fee cannot be settled exactly today."""

    def __init__(
        self,
        reason: FeeRejectionReason,
        *,
        fee_amount: Decimal | None,
        fee_currency: str | None,
    ) -> None:
        self.reason = reason
        self.fee_amount = fee_amount
        self.fee_currency = fee_currency
        super().__init__(reason.value)


class FeeNormalizer:
    """Classifies one reported fee against one instrument's declared assets."""

    @staticmethod
    def normalize(
        *,
        fee_amount: Decimal,
        fee_currency: str | None,
        instrument: InstrumentRules,
    ) -> NormalizedFee:
        if not isinstance(fee_amount, Decimal) or not fee_amount.is_finite() or fee_amount < 0:
            raise FeeRejected(
                FeeRejectionReason.INVALID_FEE_AMOUNT,
                fee_amount=fee_amount if isinstance(fee_amount, Decimal) else None,
                fee_currency=fee_currency,
            )

        # A zero fee needs no currency at all - this mirrors
        # ``ExecutionResult.validate_financial_evidence``'s existing rule
        # that only a *non-zero* fee requires a declared denomination.
        if fee_amount == 0:
            return NormalizedFee(Decimal("0"), instrument.quote_asset)

        currency = str(fee_currency).strip().upper() if fee_currency else ""
        if not currency:
            raise FeeRejected(
                FeeRejectionReason.UNDECLARED_FEE_CURRENCY,
                fee_amount=fee_amount,
                fee_currency=fee_currency,
            )

        if currency == instrument.quote_asset:
            return NormalizedFee(fee_amount, currency)

        if currency == instrument.base_asset:
            raise FeeRejected(
                FeeRejectionReason.BASE_ASSET_FEE_UNSUPPORTED,
                fee_amount=fee_amount,
                fee_currency=currency,
            )

        raise FeeRejected(
            FeeRejectionReason.THIRD_ASSET_FEE_UNSUPPORTED,
            fee_amount=fee_amount,
            fee_currency=currency,
        )
