from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from retail_sim.core.promo import InvalidPriceFactorError, normalize_price_factor


class FormError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DateRangeForm:
    date_from: date
    date_to: date


@dataclass(frozen=True, slots=True)
class PromoForm:
    date_from: date
    date_to: date
    price_factor: Decimal
    all_stores: bool
    store_ids: tuple[int, ...]


def parse_date(value: str, field: str) -> date:
    text = value.strip()
    if not text:
        raise FormError(f"Укажите поле «{field}»")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise FormError(f"Некорректная дата в поле «{field}»") from exc


def parse_date_range(date_from: str, date_to: str) -> DateRangeForm:
    start = parse_date(date_from, "дата начала")
    end = parse_date(date_to, "дата окончания")
    if start > end:
        raise FormError("Дата начала позже даты окончания")
    return DateRangeForm(date_from=start, date_to=end)


def parse_price_factor(value: str) -> Decimal:
    # Допустима десятичная запятая или точка.
    text = value.strip().replace(",", ".")
    if not text:
        raise FormError("Укажите коэффициент цены")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise FormError("Некорректный коэффициент цены") from exc
    try:
        return normalize_price_factor(parsed)
    except InvalidPriceFactorError as exc:
        raise FormError("Коэффициент должен быть больше 0 и меньше 1") from exc


def parse_store_ids(value: str) -> tuple[int, ...]:
    chunks = value.replace(";", " ").replace(",", " ").split()
    if not chunks:
        return ()
    store_ids: list[int] = []
    seen: set[int] = set()
    for chunk in chunks:
        try:
            store_id = int(chunk)
        except ValueError as exc:
            raise FormError(f"Некорректный id магазина: {chunk}") from exc
        if store_id <= 0:
            raise FormError(f"Некорректный id магазина: {chunk}")
        if store_id not in seen:
            seen.add(store_id)
            store_ids.append(store_id)
    return tuple(store_ids)


def parse_promo_form(
    date_from: str,
    date_to: str,
    factor: str,
    store_ids_text: str,
    *,
    all_stores: bool,
) -> PromoForm:
    period = parse_date_range(date_from, date_to)
    price_factor = parse_price_factor(factor)
    store_ids = parse_store_ids(store_ids_text)
    if all_stores and store_ids:
        raise FormError("Укажите либо список магазинов, либо «все магазины»")
    if not all_stores and not store_ids:
        raise FormError("Укажите магазины или отметьте «все магазины»")
    return PromoForm(
        date_from=period.date_from,
        date_to=period.date_to,
        price_factor=price_factor,
        all_stores=all_stores,
        store_ids=store_ids,
    )
