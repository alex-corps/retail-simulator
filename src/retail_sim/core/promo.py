from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Постоянная эластичность: выручка дня растёт как f^(1-E), штуки — как f^(-E).
ELASTICITY = Decimal("1.5")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_KOPECK = Decimal("0.01")
_FACTOR_QUANT = Decimal("0.0001")


class InvalidPriceFactorError(ValueError):
    def __init__(self, price_factor: Decimal) -> None:
        self.price_factor = price_factor
        super().__init__("price_factor must be greater than 0 and less than 1")


def normalize_price_factor(price_factor: Decimal) -> Decimal:
    factor = price_factor.quantize(_FACTOR_QUANT, rounding=ROUND_HALF_UP)
    if factor <= 0 or factor >= _ONE:
        raise InvalidPriceFactorError(price_factor)
    return factor


def revenue_multiplier(price_factor: Decimal) -> Decimal:
    return price_factor ** (_ONE - ELASTICITY)


def scale_day_revenue(revenue_kop: int, price_factor: Decimal) -> int:
    scaled = Decimal(revenue_kop) * revenue_multiplier(price_factor)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def sale_price(retail_price: Decimal, price_factor: Decimal) -> Decimal:
    return (retail_price * price_factor).quantize(_KOPECK, rounding=ROUND_HALF_UP)


def discount_percent(price_factor: Decimal) -> Decimal:
    return ((_ONE - price_factor) * _HUNDRED).quantize(_KOPECK, rounding=ROUND_HALF_UP)
