"""Normalize price providers without reusing yesterday or inventing missing slots."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from .models import PriceInterval, aware, finite, minute

UTC = timezone.utc


def normalize(rows: list[PriceInterval]) -> tuple[PriceInterval, ...]:
    result = tuple(sorted(rows, key=lambda r: r.start))
    for left, right in zip(result, result[1:]):
        if left.end > right.start:
            raise ValueError("Overlapping price intervals")
    return result


def current_price(rows: tuple[PriceInterval, ...], now: datetime) -> float | None:
    now = aware(now).astimezone(UTC)
    return next((x.price for x in rows if x.start <= now < x.end), None)


def pvpc_intervals(
    attributes: dict, current: object, now: datetime, tz: str
) -> tuple[PriceInterval, ...]:
    """Native HA PVPC price_XXh / price_next_day_XXh / repeated-hour _d."""
    now = aware(now).astimezone(UTC)
    local = now.astimezone(ZoneInfo(tz))
    start = now.replace(minute=0, second=0, microsecond=0)
    actual = finite(current, "PVPC current price")
    result = []
    for offset in range(36):
        begin = start + timedelta(hours=offset)
        clock = begin.astimezone(ZoneInfo(tz))
        days = (clock.date() - local.date()).days
        if days not in [0, 1]:
            break
        key = (
            ("price_" if days == 0 else "price_next_day_")
            + f"{clock.hour:02d}h"
            + ("_d" if clock.fold else "")
        )
        value = attributes.get(key)
        if value is None:
            break
        result.append(
            PriceInterval(begin, begin + timedelta(hours=1), finite(value, key))
        )
    if not result or abs(result[0].price - actual) > 1e-5:
        raise ValueError("PVPC current value does not match a published interval")
    return normalize(result)


def generic_intervals(attributes: dict, unit: str) -> tuple[PriceInterval, ...]:
    factor = {"EUR/kWh": 1, "€/kWh": 1, "EUR/MWh": 0.001, "€/MWh": 0.001}.get(unit)
    if factor is None:
        raise ValueError("Unsupported or ambiguous price unit")
    rows = attributes.get("intervals")
    if not isinstance(rows, list):
        raise ValueError("Generic provider requires intervals")
    return normalize(
        [
            PriceInterval(
                datetime.fromisoformat(x["start"]),
                datetime.fromisoformat(x["end"]),
                finite(x["price"], "price") * factor,
            )
            for x in rows
        ]
    )


@dataclass(frozen=True)
class FixedPeriod:
    weekdays: tuple[int, ...]
    start: str
    end: str
    price: float
    on_date: str | None = None

    def __post_init__(self) -> None:
        minute(self.start)
        minute(self.end)
        finite(self.price, "fixed price")
        if not self.weekdays or any(d not in range(7) for d in self.weekdays):
            raise ValueError("Invalid weekdays")
        if self.on_date:
            date.fromisoformat(self.on_date)

    def matches(self, local: datetime) -> bool:
        clock = local.hour * 60 + local.minute
        start = minute(self.start)
        end = minute(self.end)
        anchor = local.date()
        if start < end:
            if not start <= clock < end:
                return False
        else:
            if clock < end or (start == end and clock < start):
                anchor -= timedelta(days=1)
            elif clock < start:
                return False
        return (
            (anchor.isoformat() == self.on_date)
            if self.on_date
            else anchor.weekday() in self.weekdays
        )


def fixed_price(periods: tuple[FixedPeriod, ...], local: datetime) -> float | None:
    rows = [x for x in periods if x.matches(local)]
    exceptions = [x for x in rows if x.on_date]
    rows = exceptions or [x for x in rows if not x.on_date]
    if len(rows) > 1:
        raise ValueError("Overlapping fixed-tariff periods")
    return finite(rows[0].price, "fixed price") if rows else None


def validate_fixed(periods: tuple[FixedPeriod, ...], tz: str) -> None:
    if not periods:
        raise ValueError("Empty fixed tariff")
    # All local quarter-hours plus every configured boundary catch even a
    # one-minute gap/overlap. Exceptions override regular days only where given.
    base = date(2026, 1, 5)
    for offset in range(7):
        for m in range(1440):
            local = datetime.combine(
                base + timedelta(days=offset), datetime.min.time(), ZoneInfo(tz)
            ) + timedelta(minutes=m)
            if fixed_price(periods, local) is None:
                raise ValueError("Fixed tariff has uncovered weekly minutes")
    for d in {x.on_date for x in periods if x.on_date}:
        for m in range(1440):
            fixed_price(
                periods,
                datetime.combine(
                    date.fromisoformat(d), datetime.min.time(), ZoneInfo(tz)
                )
                + timedelta(minutes=m),
            )


def fixed_intervals(
    periods: tuple[FixedPeriod, ...], now: datetime, tz: str, hours: int = 36
) -> tuple[PriceInterval, ...]:
    """Walk UTC minutes: DST days naturally contain 23/25 hours, without fabrication."""
    start = aware(now).astimezone(UTC).replace(second=0, microsecond=0)
    result = []
    for index in range(hours * 60):
        begin = start + timedelta(minutes=index)
        price = fixed_price(periods, begin.astimezone(ZoneInfo(tz)))
        if price is None:
            break
        end = begin + timedelta(minutes=1)
        if result and result[-1].price == price:
            result[-1] = PriceInterval(result[-1].start, end, price)
        else:
            result.append(PriceInterval(begin, end, price))
    return normalize(result)


def opportunities(
    rows: tuple[PriceInterval, ...], now: datetime, duration_s: int, horizon_s: int
) -> list[dict]:
    """Price complete useful blocks, including expensive intervals inside the block."""
    now = aware(now).astimezone(UTC)
    starts = sorted(
        {now}
        | {
            x.start
            for x in rows
            if now <= x.start <= now + timedelta(seconds=horizon_s)
        }
    )
    result = []
    for start in starts:
        end = start + timedelta(seconds=duration_s)
        cursor = start
        cost = 0
        for row in rows:
            if row.end <= cursor:
                continue
            if row.start > cursor:
                break
            finish = min(end, row.end)
            cost += row.price * (finish - cursor).total_seconds()
            cursor = finish
            if cursor >= end:
                break
        if cursor == end:
            result.append(
                {
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "average": cost / duration_s,
                }
            )
    return sorted(result, key=lambda x: (x["average"], x["start"]))
