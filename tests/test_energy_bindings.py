"""Portable measurements, shared scopes and supply continuity boundaries."""

from dataclasses import replace
from test_domain import fixture, NOW
from domain.energy import Meter, normalize, meters_from_profile
from domain.models import Reading
from domain.safety import SupplyProtection, supply_cut
from domain.engine import evaluate
import unittest


class EnergyTests(unittest.TestCase):
    def test_negative_power_noise_is_explicit_unit_aware_and_bounded(self):
        for value, unit in [(-1.5, "W"), (-0.0015, "kW"), (-5, "W")]:
            with self.subTest(value=value, unit=unit):
                self.assertEqual(
                    normalize(value, unit, "power", negative_power_tolerance_w=5), 0
                )
        for value in [-0.01, -5.01, -100]:
            with self.assertRaises(ValueError):
                normalize(
                    value,
                    "W",
                    "power",
                    negative_power_tolerance_w=0 if value == -0.01 else 5,
                )
        self.assertEqual(
            normalize(100, "W", "power", negative_power_tolerance_w=5), 100
        )

    def test_noise_tolerance_never_changes_energy_or_hides_export(self):
        with self.assertRaises(ValueError):
            normalize(-1, "kWh", "energy", negative_power_tolerance_w=5)
        for tolerance in [True, -1, 21, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                Meter(
                    "m",
                    "Meter",
                    power_entity="sensor.power",
                    negative_power_tolerance_w=tolerance,
                )
        with self.assertRaises(ValueError):
            Meter(
                "m",
                "Energy only",
                energy_entity="sensor.energy",
                negative_power_tolerance_w=5,
            )
        self.assertEqual(
            Meter("m", "Meter", power_entity="sensor.power").negative_power_tolerance_w,
            0,
        )

    def test_units_are_explicit_and_distinct(self):
        for value, unit, kind, result in [
            (1.2, "kW", "power", 1200),
            (900, "Wh", "energy", 0.9),
            (1.5, "MWh", "energy", 1500),
            (12, "kWh", "energy", 12),
        ]:
            self.assertEqual(normalize(value, unit, kind), result)
        for unit in ["VA", "kVA", "W", ""]:
            with self.assertRaises(ValueError):
                normalize(1, unit, "energy")
        for value in [True, float("nan"), float("inf"), -1]:
            with self.assertRaises(ValueError):
                normalize(value, "W", "power")

    def test_shared_meter_not_allocated_twice(self):
        h, *_ = fixture(2)
        rows = [
            {
                "id": "a",
                "name": "Shared",
                "scope": "plant",
                "target": "plant",
                "power_entity": "sensor.shared",
            }
        ]
        self.assertEqual(meters_from_profile({"meters": rows}, h)[0].scope, "plant")
        with self.assertRaises(ValueError):
            meters_from_profile(
                {
                    "meters": rows
                    + [{**rows[0], "id": "b", "scope": "zone", "target": "0"}]
                },
                h,
            )

    def test_unknown_scopes_and_missing_sources_rejected(self):
        with self.assertRaises(ValueError):
            Meter("a", "Meter")
        h, *_ = fixture()
        with self.assertRaises(ValueError):
            meters_from_profile(
                {
                    "meters": [
                        {
                            "id": "a",
                            "name": "Meter",
                            "scope": "zone",
                            "target": "missing",
                            "energy_entity": "sensor.energy",
                        }
                    ]
                },
                h,
            )

    def test_supply_needs_distinct_reports_and_sustained_recovery(self):
        p, m = SupplyProtection(7000, 120, 5800, 120), {}
        t = NOW.timestamp()
        self.assertFalse(supply_cut(m, Reading(8000, t), t, 120, p, False, False))
        self.assertFalse(supply_cut(m, Reading(8000, t), t + 120, 120, p, False, False))
        self.assertTrue(
            supply_cut(m, Reading(8000, t + 120), t + 120, 120, p, False, False)
        )
        self.assertTrue(supply_cut(m, Reading(None), t + 121, 120, p, True, False))
        self.assertTrue(
            supply_cut(m, Reading(100, t + 130), t + 130, 120, p, True, False)
        )
        self.assertFalse(
            supply_cut(m, Reading(100, t + 250), t + 250, 120, p, True, False)
        )

    def test_report_gap_and_clock_regression_reset_persistence(self):
        p, m = SupplyProtection(7000, 720, 5800, 120), {}
        t = NOW.timestamp()
        for offset in [0, 600, 500, 900]:
            self.assertFalse(
                supply_cut(
                    m, Reading(8000, t + offset), t + offset, 120, p, False, False
                )
            )

    def test_external_cut_requires_known_release(self):
        p, m = SupplyProtection(), {}
        self.assertTrue(supply_cut(m, None, 100, 120, p, False, True))
        self.assertTrue(supply_cut(m, None, 101, 120, p, True, None))
        self.assertFalse(supply_cut(m, None, 102, 120, p, True, False))

    def test_external_goals_and_compensation_override_defaults(self):
        h, s, prices, memory, plants = fixture()
        t = NOW.timestamp()
        s.zones["0"] = replace(
            s.zones["0"], heat_goal=Reading(22, t), bias=Reading(3, t)
        )
        d = evaluate(h, s, prices, memory, plants)["0"]
        self.assertEqual(d.heat_goal, 22)
        self.assertEqual(d.physical_target, 26)

    def test_configured_broken_goal_never_silently_uses_default(self):
        h, s, prices, memory, plants = fixture()
        s.zones["0"] = replace(s.zones["0"], goals_valid=False)
        d = evaluate(h, s, prices, memory, plants)["0"]
        self.assertIsNone(d.mode)
        self.assertEqual(d.reason, "external_goal_unavailable")

    def test_external_mode_permission_and_room_pause_are_enforced(self):
        h, s, prices, memory, plants = fixture()
        for changes in [{"heat_allowed": False}, {"permitted": False}]:
            with self.subTest(changes=changes):
                s.zones["0"] = replace(s.zones["0"], **changes)
                self.assertIsNone(evaluate(h, s, prices, memory, plants)["0"].mode)


if __name__ == "__main__":
    unittest.main()
