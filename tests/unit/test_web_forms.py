from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from retail_sim.web.forms import (
    FormError,
    parse_date_range,
    parse_price_factor,
    parse_promo_form,
    parse_store_ids,
)


def test_parse_price_factor_accepts_comma_and_dot() -> None:
    assert parse_price_factor("0,8") == Decimal("0.8000")
    assert parse_price_factor("0.8") == Decimal("0.8000")


@pytest.mark.parametrize("value", ["", "0", "1", "1,0", "abc", "-0.2"])
def test_parse_price_factor_rejects_values_outside_the_open_interval(value: str) -> None:
    with pytest.raises(FormError):
        parse_price_factor(value)


def test_parse_date_range_rejects_an_inverted_range() -> None:
    with pytest.raises(FormError, match="позже"):
        parse_date_range("2026-06-03", "2026-06-01")


def test_parse_date_range_rejects_a_blank_date() -> None:
    with pytest.raises(FormError, match="дата начала"):
        parse_date_range("  ", "2026-06-01")


def test_parse_store_ids_splits_commas_spaces_and_semicolons() -> None:
    assert parse_store_ids("3, 8\n12; 3") == (3, 8, 12)


def test_parse_store_ids_rejects_garbage_and_non_positive_ids() -> None:
    with pytest.raises(FormError, match="магазин"):
        parse_store_ids("3, x")
    with pytest.raises(FormError, match="магазин"):
        parse_store_ids("0")
    assert parse_store_ids("   ") == ()


def test_parse_promo_form_all_stores_excludes_an_id_list() -> None:
    with pytest.raises(FormError, match="либо"):
        parse_promo_form(
            "2026-06-01",
            "2026-06-07",
            "0,8",
            "3, 8",
            all_stores=True,
        )


def test_parse_promo_form_requires_stores() -> None:
    with pytest.raises(FormError, match="все магазины"):
        parse_promo_form("2026-06-01", "2026-06-07", "0.8", "", all_stores=False)


def test_parse_promo_form_all_stores() -> None:
    form = parse_promo_form("2026-06-01", "2026-06-07", "0,8", "", all_stores=True)
    assert form.date_from == date(2026, 6, 1)
    assert form.date_to == date(2026, 6, 7)
    assert form.price_factor == Decimal("0.8000")
    assert form.all_stores is True
    assert form.store_ids == ()


def test_parse_promo_form_store_list() -> None:
    form = parse_promo_form("2026-06-01", "2026-06-02", "0.5", "8, 3", all_stores=False)
    assert form.store_ids == (8, 3)
    assert form.all_stores is False
