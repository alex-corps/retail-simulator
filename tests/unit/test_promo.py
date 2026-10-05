from __future__ import annotations

from decimal import Decimal

import pytest

from retail_sim.core.promo import (
    ELASTICITY,
    InvalidPriceFactorError,
    discount_percent,
    normalize_price_factor,
    revenue_multiplier,
    sale_price,
    scale_day_revenue,
)


def test_revenue_multiplier_is_price_factor_to_one_minus_elasticity() -> None:
    factor = Decimal("0.8")
    assert revenue_multiplier(factor) == factor ** (1 - ELASTICITY)


def test_scale_day_revenue_rounds_half_up() -> None:
    assert scale_day_revenue(100_000, Decimal("0.8")) == 111_803


def test_sale_price_and_discount_round_half_up() -> None:
    assert sale_price(Decimal("99.99"), Decimal("0.8")) == Decimal("79.99")
    assert sale_price(Decimal("1.00"), Decimal("0.005")) == Decimal("0.01")
    assert discount_percent(Decimal("0.8")) == Decimal("20.00")
    assert discount_percent(Decimal("0.33333")) == Decimal("66.67")


def test_normalize_price_factor_quantizes_to_four_places() -> None:
    assert normalize_price_factor(Decimal("0.8")) == Decimal("0.8000")
    assert normalize_price_factor(Decimal("0.12345")) == Decimal("0.1235")


def test_normalize_price_factor_rejects_bounds() -> None:
    rejected = (
        Decimal("0"),
        Decimal("1"),
        Decimal("-0.1"),
        Decimal("1.5"),
        Decimal("0.99996"),
    )
    for factor in rejected:
        with pytest.raises(InvalidPriceFactorError):
            normalize_price_factor(factor)
