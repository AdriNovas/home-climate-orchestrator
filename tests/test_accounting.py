"""Tariff boundaries, true calendar periods, gaps and no double-counting."""

from datetime import datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from test_domain import fixture
from domain.accounting import Accounting, bounds
from domain.models import PriceInterval
from domain.energy import meters_from_profile

UTC = timezone.utc


class AccountingTests(unittest.TestCase):
    def test_tariff_change_is_not_current_price_times_old_energy(self):
        start = datetime(2026, 11, 5, 12, tzinfo=UTC)
        rows = (
            PriceInterval(start, start + timedelta(minutes=30), 0.1),
            PriceInterval(
                start + timedelta(minutes=30), start + timedelta(hours=1), 0.3
            ),
        )
        ledger = Accounting("UTC")
        ledger.observe(start, 1000, start.timestamp(), 3600, rows)
        ledger.observe(
            start + timedelta(hours=1),
            0,
            (start + timedelta(hours=1)).timestamp(),
            3600,
            (),
        )
        row = ledger.view(start + timedelta(hours=1), "today")
        self.assertAlmostEqual(row["energy"], 1)
        self.assertAlmostEqual(row["cost"], 0.2)
        self.assertFalse(row["energy_complete"])

    def test_negative_prices_and_price_gap_preserve_energy(self):
        start = datetime(2026, 11, 5, tzinfo=UTC)
        rows = (PriceInterval(start, start + timedelta(minutes=30), -0.1),)
        ledger = Accounting("UTC")
        ledger.observe(start, 1000, start.timestamp(), 3600, rows)
        end = start + timedelta(hours=1)
        ledger.observe(end, 0, end.timestamp(), 3600, ())
        r = ledger.view(end, "today")
        self.assertEqual(r["energy"], 1)
        self.assertEqual(r["cost"], -0.05)
        self.assertEqual(r["unpriced_energy"], 0.5)
        self.assertTrue(r["energy_complete"])
        self.assertFalse(r["cost_complete"])

    def test_stale_power_is_not_extrapolated(self):
        start = datetime(2026, 11, 5, tzinfo=UTC)
        ledger = Accounting("UTC")
        ledger.observe(start, 3000, start.timestamp(), 120, ())
        end = start + timedelta(hours=2)
        ledger.observe(end, 0, end.timestamp(), 120, ())
        r = ledger.view(end, "today")
        self.assertAlmostEqual(r["energy"], 0.1)
        self.assertEqual(r["energy_coverage_s"], 120)
        self.assertIsNone(r["cost"])

    def test_restart_never_bridges_unknown_downtime(self):
        start = datetime(2026, 11, 5, tzinfo=UTC)
        ledger = Accounting("UTC")
        ledger.observe(start, 1000, start.timestamp(), 3600, ())
        at = start + timedelta(hours=1)
        ledger.observe(at, 1000, at.timestamp(), 3600, ())
        restored = Accounting("UTC", ledger.saved())
        at += timedelta(hours=2)
        restored.observe(at, 1000, at.timestamp(), 3600, ())
        at += timedelta(minutes=1)
        restored.observe(at, 1000, at.timestamp(), 3600, ())
        self.assertAlmostEqual(restored.view(at, "today")["energy"], 1 + 1 / 60)
        self.assertEqual(restored.view(at, "today")["energy_coverage_s"], 3660)

    def test_day_boundary_and_yesterday_unknown_not_zero(self):
        start = datetime(2026, 11, 5, 22, 30, tzinfo=UTC)  # 23:30 local
        end = start + timedelta(hours=1)
        ledger = Accounting("Europe/Madrid")
        ledger.observe(start, 1000, start.timestamp(), 3600, ())
        self.assertIsNone(ledger.view(start, "yesterday")["energy"])
        ledger.observe(end, 0, end.timestamp(), 3600, ())
        self.assertEqual(ledger.view(end, "today")["energy"], 0.5)
        self.assertEqual(ledger.view(end, "yesterday")["energy"], 0.5)

    def test_dst_days_have_23_and_25_hours(self):
        for day, hours in [
            (datetime(2026, 3, 30, tzinfo=ZoneInfo("Europe/Madrid")), 23),
            (datetime(2026, 10, 26, tzinfo=ZoneInfo("Europe/Madrid")), 25),
        ]:
            begin, end = bounds(day, "Europe/Madrid", "yesterday")
            self.assertEqual((end - begin).total_seconds(), hours * 3600)
            ledger = Accounting("Europe/Madrid")
            ledger.observe(begin, 1000, begin.timestamp(), 86400, ())
            middle = begin + (end - begin) / 2
            ledger.observe(middle, 1000, middle.timestamp(), 86400, ())
            ledger.observe(end, 0, end.timestamp(), 86400, ())
            self.assertEqual(ledger.view(end, "yesterday")["energy"], hours)

    def test_week_month_year_and_source_unavailable(self):
        at = datetime(2027, 1, 1, 12, tzinfo=UTC)
        self.assertEqual(bounds(at, "UTC", "week")[0].date().isoformat(), "2026-12-28")
        for period in ["month", "year"]:
            self.assertEqual(
                bounds(at, "UTC", period)[0].date().isoformat(), "2027-01-01"
            )
        ledger = Accounting("UTC")
        ledger.observe(at, None, 0, 120, ())
        self.assertIsNone(ledger.view(at, "today")["energy"])
        self.assertIsNone(ledger.first)

    def test_overlapping_scopes_rejected_but_can_be_excluded(self):
        house, *_ = fixture()
        parent = {
            "id": "parent",
            "name": "Shared meter",
            "scope": "plant",
            "target": "plant",
            "power_entity": "sensor.plant",
        }
        child = {
            "id": "child",
            "name": "Head meter",
            "scope": "zone",
            "target": "0",
            "power_entity": "sensor.head",
        }
        with self.assertRaises(ValueError):
            meters_from_profile({"meters": [parent, child]}, house)
        self.assertEqual(
            len(
                meters_from_profile(
                    {"meters": [parent, {**child, "include_in_system": False}]}, house
                )
            ),
            2,
        )
        with self.assertRaises(ValueError):
            meters_from_profile(
                {"meters": [parent, {**child, "scope": "house", "target": ""}]}, house
            )

    def test_backward_duplicate_and_invalid_measurements(self):
        at = datetime(2026, 11, 5, tzinfo=UTC)
        ledger = Accounting("UTC")
        ledger.observe(at, 1000, at.timestamp(), 120, ())
        before = ledger.saved().copy()
        ledger.observe(at, 2000, at.timestamp(), 120, ())
        self.assertEqual(before, ledger.saved())
        for value in [-1, True, float("nan")]:
            with self.assertRaises(ValueError):
                ledger.observe(
                    at + timedelta(seconds=1), value, at.timestamp(), 120, ()
                )
        with self.assertRaises(ValueError):
            Accounting("UTC", {"version": 99})
