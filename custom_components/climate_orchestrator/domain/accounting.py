"""Coverage-aware integration of measured active W, never fabricated history.

Left-step quadrature ends at source freshness. No interpolation across restarts.
Variable energy charge only, using the published price of each UTC interval.
Original cumulative meters and their Recorder statistics are never changed.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import finite

PERIODS = ("today", "yesterday", "week", "month", "year")
UTC = timezone.utc


def bounds(now, zone, period):
    local = now.astimezone(ZoneInfo(zone))
    day = local.date()
    start = day
    if period == "yesterday":
        start -= timedelta(days=1)
    elif period == "week":
        start -= timedelta(days=day.weekday())
    elif period == "month":
        start = day.replace(day=1)
    elif period == "year":
        start = day.replace(month=1, day=1)
    elif period != "today":
        raise ValueError("Unknown accounting period")
    begin = datetime.combine(start, time.min, local.tzinfo).astimezone(UTC)
    end = (
        datetime.combine(day, time.min, local.tzinfo).astimezone(UTC)
        if period == "yesterday"
        else now.astimezone(UTC)
    )
    return begin, end


class Accounting:
    def __init__(self, timezone_name, saved=None):
        self.timezone = timezone_name
        ZoneInfo(timezone_name)
        self.days = {}
        self.first = None
        self.last = None
        self.sample = None
        if saved:
            if saved.get("version") != 1 or saved.get("timezone") != timezone_name:
                raise ValueError(
                    "Incompatible accounting store; preserve it for review"
                )
            self.first = (
                finite(saved["first"], "accounting first")
                if saved.get("first") is not None
                else None
            )
            self.last = (
                finite(saved["last"], "accounting last")
                if saved.get("last") is not None
                else None
            )
            for key, row in saved.get("days", {}).items():
                date.fromisoformat(key)
                self.days[key] = {
                    k: finite(row[k], k)
                    for k in ["energy", "cost", "energy_s", "cost_s", "unpriced_energy"]
                }
                if any(v < 0 for k, v in self.days[key].items() if k != "cost"):
                    raise ValueError("Invalid accounting ledger")

    def saved(self):
        return {
            "version": 1,
            "timezone": self.timezone,
            "first": self.first,
            "last": self.last,
            "days": self.days,
        }

    def observe(self, now, watts, reported_at, fresh_s, prices):
        at = now.timestamp()
        if self.last is not None and at <= self.last:
            return
        if watts is not None:
            watts = finite(watts, "measured active power")
            if watts < 0:
                raise ValueError("Consumption power cannot be negative")
        if self.first is None and watts is not None:
            self.first = at
        if self.sample is not None:
            left = self.last
            power, report, previous_prices = self.sample
            right = at
            known_end = (
                min(right, report + fresh_s)
                if power is not None and report <= left
                else left
            )
            # Preserve the previously captured price across a tariff boundary.
            rows = tuple(previous_prices) + tuple(prices)
            points = {left, right, max(left, known_end)}
            local_day = (
                datetime.fromtimestamp(left, UTC)
                .astimezone(ZoneInfo(self.timezone))
                .date()
            )
            midnight = datetime.combine(
                local_day + timedelta(days=1), time.min, ZoneInfo(self.timezone)
            ).timestamp()
            while midnight < right:
                points.add(midnight)
                local_day += timedelta(days=1)
                midnight = datetime.combine(
                    local_day + timedelta(days=1), time.min, ZoneInfo(self.timezone)
                ).timestamp()
            for row in rows:
                for edge in [row.start.timestamp(), row.end.timestamp()]:
                    if left < edge < right:
                        points.add(edge)
            points = sorted(points)
            for start, end in zip(points, points[1:]):
                key = (
                    datetime.fromtimestamp(start, UTC)
                    .astimezone(ZoneInfo(self.timezone))
                    .date()
                    .isoformat()
                )
                bucket = self.days.setdefault(
                    key,
                    {
                        "energy": 0.0,
                        "cost": 0.0,
                        "energy_s": 0.0,
                        "cost_s": 0.0,
                        "unpriced_energy": 0.0,
                    },
                )
                if power is None or end > known_end:
                    continue
                seconds = end - start
                energy = power * seconds / 3_600_000
                bucket["energy"] += energy
                bucket["energy_s"] += seconds
                middle = (start + end) / 2
                price = next(
                    (
                        row.price
                        for row in rows
                        if row.start.timestamp() <= middle < row.end.timestamp()
                    ),
                    None,
                )
                if price is None:
                    bucket["unpriced_energy"] += energy
                else:
                    bucket["cost"] += energy * price
                    bucket["cost_s"] += seconds
        self.last = at
        self.sample = (watts, reported_at, tuple(prices))
        earliest = (
            now.astimezone(ZoneInfo(self.timezone)).date() - timedelta(days=400)
        ).isoformat()
        self.days = {k: v for k, v in self.days.items() if k >= earliest}

    def view(self, now, period):
        start, end = bounds(now, self.timezone, period)
        begin_day = start.astimezone(ZoneInfo(self.timezone)).date().isoformat()
        # Yesterday ends at midnight; do not include today's bucket.
        final_day = (
            (end - timedelta(microseconds=1))
            .astimezone(ZoneInfo(self.timezone))
            .date()
            .isoformat()
        )
        rows = [v for k, v in self.days.items() if begin_day <= k <= final_day]
        energy_s = sum(x["energy_s"] for x in rows)
        cost_s = sum(x["cost_s"] for x in rows)
        expected = max(0, (end - start).total_seconds())
        return {
            "energy": sum(x["energy"] for x in rows) if energy_s else None,
            "cost": sum(x["cost"] for x in rows) if cost_s else None,
            "energy_coverage_s": energy_s,
            "cost_coverage_s": cost_s,
            "expected_s": expected,
            "energy_complete": energy_s > 0 and abs(energy_s - expected) < 1,
            "cost_complete": cost_s > 0 and abs(cost_s - expected) < 1,
            "unpriced_energy": sum(x["unpriced_energy"] for x in rows),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "tracking_since": datetime.fromtimestamp(self.first, UTC).isoformat()
            if self.first is not None
            else None,
            "method": "left-step integration of measured W; no restart interpolation",
        }
