"""Synthetic homes only; no network, tokens, HA instance or actuator services."""

import ast
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import pathlib
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "custom_components/climate_orchestrator"))
from domain.models import (
    House,
    Plant,
    Zone,
    Policy,
    PolicyValidationError,
    PriceInterval,
    Reading,
    Observation,
    Snapshot,
    Memory,
    house_from_dict,
)
from domain.tariffs import (
    normalize,
    current_price,
    pvpc_intervals,
    generic_intervals,
    FixedPeriod,
    validate_fixed,
    fixed_intervals,
    opportunities,
)
from domain.engine import evaluate, hardware_target, begin_dry, dew_point

UTC = timezone.utc
NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def fixture(zones=1, **policy):
    house = House(
        "Fictional home",
        "Europe/Madrid",
        (Plant("plant", "Shared outdoor"),),
        tuple(
            Zone(
                str(i),
                f"Zone {i}",
                "plant",
                f"sensor.room_{i}_temperature",
                f"climate.unit_{i}",
                f"sensor.room_{i}_humidity",
                allow_dry=True,
            )
            for i in range(zones)
        ),
        Policy(**policy),
    )
    t = NOW.timestamp()
    observations = {
        z.id: Observation(
            Reading(18, t),
            Reading(80, t),
            Reading(20, t),
            "off",
            t - 4000,
            19.5,
            ("off", "heat", "cool", "dry", "fan_only"),
        )
        for z in house.zones
    }
    snap = Snapshot(
        NOW, observations, True, False, Reading(13, t), Reading(100, t), True
    )
    prices = (PriceInterval(NOW - timedelta(hours=1), NOW + timedelta(hours=3), 0.15),)
    return house, snap, prices, {}, {}


class ConfigurationTests(unittest.TestCase):
    def test_public_manifest_matches_native_diagnostic_version(self):
        component = ROOT / 'custom_components/climate_orchestrator'
        constants = ast.parse((component / 'const.py').read_text())
        version = next(ast.literal_eval(node.value) for node in constants.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'VERSION'
                               for target in node.targets))
        self.assertEqual(version, json.loads((component / 'manifest.json').read_text())['version'])

    def test_relational_errors_identify_fields_without_changing_validation(self):
        for settings, code, names in [
            ({"shared_load_idle_w": 300}, "policy_load_order", {"shared_load_idle_w", "shared_load_high_w"}),
            ({"shared_load_management": True}, "policy_requires_hold", {"continuous_hold", "shared_load_management"}),
            ({"extreme_price_hysteresis": 0.5}, "policy_price_margin", {"extreme_price", "extreme_price_hysteresis"}),
            ({"hold_delta": 1}, "policy_hysteresis", {"hold_delta", "start_delta", "overshoot_delta"}),
            ({"overshoot_delta": 0.1}, "policy_overshoot", {"hold_delta", "overshoot_delta"}),
            ({"dry_max_s": 60}, "policy_dry_duration", {"dry_min_s", "dry_max_s"}),
        ]:
            with self.subTest(settings=settings):
                with self.assertRaises(PolicyValidationError) as caught:
                    Policy(**settings)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(set(caught.exception.fields), names)
        self.assertEqual(Policy(dry_max_s=0).dry_max_s, 0)

    def test_roundtrip_preserves_ids_and_overrides(self):
        h, *_ = fixture()
        self.assertEqual(house_from_dict(asdict(h)), h)

    def test_invalid_numbers_and_hysteresis(self):
        for value in [float("nan"), float("inf"), True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Reading(value)
        for kwargs in [
            {"hold_delta": 1},
            {"dry_max_s": 60},
            {"correction_limit": float("nan")},
            {"dry_attempts": 0},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Policy(**kwargs)

    def test_duplicate_binding_and_unknown_plant(self):
        h, *_ = fixture(2)
        with self.assertRaises(ValueError):
            replace(
                h,
                zones=(
                    h.zones[0],
                    replace(h.zones[1], climate_entity=h.zones[0].climate_entity),
                ),
            )
        with self.assertRaises(ValueError):
            replace(h, zones=(replace(h.zones[0], plant="missing"),))

    def test_core_has_no_homeassistant_or_wallclock_io(self):
        for file in (ROOT / "custom_components/climate_orchestrator/domain").glob(
            "*.py"
        ):
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("homeassistant"))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(
                        node.func.attr, ["utcnow", "now", "urlopen", "async_call"]
                    )


class TariffTests(unittest.TestCase):
    def test_negative_zero_and_boundaries(self):
        p = Policy()
        for price, name in [
            (-0.01, "negative"),
            (0, "very_low"),
            (0.05, "low"),
            (0.1, "normal"),
            (0.2, "high"),
            (0.3, "very_high"),
        ]:
            self.assertEqual(p.band(price).name, name)
        self.assertIsNone(p.band(None))

    def test_overlap_naive_and_unknown_units_rejected(self):
        with self.assertRaises(ValueError):
            PriceInterval(NOW.replace(tzinfo=None), NOW, 0.2)
        with self.assertRaises(ValueError):
            normalize(
                [
                    PriceInterval(NOW, NOW + timedelta(hours=2), 0.1),
                    PriceInterval(
                        NOW + timedelta(hours=1), NOW + timedelta(hours=3), 0.2
                    ),
                ]
            )
        with self.assertRaises(ValueError):
            generic_intervals({"intervals": []}, "W")

    def test_pvpc_gap_stops_without_reusing_tomorrow(self):
        attrs = {"price_13h": 0.15, "price_15h": 0.01, "price_next_day_00h": -0.01}
        rows = pvpc_intervals(attrs, 0.15, NOW, "Europe/Madrid")
        self.assertEqual(len(rows), 1)
        with self.assertRaises(ValueError):
            pvpc_intervals(attrs, 0.1, NOW, "Europe/Madrid")

    def test_pvpc_dst_23_and_25_hours(self):
        for month, day, count in [(3, 29, 23), (10, 25, 25)]:
            now = datetime(2026, month, day, 0, tzinfo=ZoneInfo("Europe/Madrid"))
            attrs = {f"price_{h:02d}h": 0.1 for h in range(24)}
            attrs["price_02h_d"] = 0.2
            rows = pvpc_intervals(attrs, 0.1, now, "Europe/Madrid")
            self.assertEqual(len(rows), count)
            if count == 25:
                self.assertEqual(sum(x.price == 0.2 for x in rows), 1)

    def test_fixed_overnight_weekend_exception_and_dst(self):
        periods = (
            FixedPeriod(tuple(range(7)), "22:00", "06:00", 0.05),
            FixedPeriod(tuple(range(7)), "06:00", "22:00", 0.2),
            FixedPeriod(tuple(range(7)), "00:00", "00:00", -0.01, "2026-11-05"),
        )
        validate_fixed(periods, "Europe/Madrid")
        rows = fixed_intervals(periods, NOW, "Europe/Madrid", 24)
        self.assertEqual(current_price(rows, NOW), -0.01)
        for month, day, hours in [(3, 29, 23), (10, 25, 25)]:
            local = datetime(2026, month, day, tzinfo=ZoneInfo("Europe/Madrid"))
            nextday = local + timedelta(days=1)
            result = fixed_intervals(periods, local, "Europe/Madrid", 26)
            total = sum(
                (
                    min(x.end, nextday.astimezone(UTC))
                    - max(x.start, local.astimezone(UTC))
                ).total_seconds()
                for x in result
                if x.start < nextday.astimezone(UTC)
            )
            self.assertEqual(total / 3600, hours)

    def test_fixed_overlaps_and_gaps(self):
        with self.assertRaises(ValueError):
            validate_fixed((FixedPeriod((0,), "01:00", "02:00", 0.1),), "Europe/Madrid")
        with self.assertRaises(ValueError):
            validate_fixed(
                (FixedPeriod(tuple(range(7)), "00:00", "00:00", 0.1),) * 2,
                "Europe/Madrid",
            )

    def test_complete_window_prices_every_interval(self):
        rows = normalize(
            [
                PriceInterval(NOW, NOW + timedelta(minutes=10), -0.1),
                PriceInterval(
                    NOW + timedelta(minutes=10), NOW + timedelta(hours=1), 0.4
                ),
            ]
        )
        windows = opportunities(rows, NOW, 1800, 3600)
        present = next(w for w in windows if w["start"] == NOW.timestamp())
        self.assertAlmostEqual(present["average"], (-0.1 * 10 + 0.4 * 20) / 30)
        gap = normalize(
            [
                rows[0],
                PriceInterval(
                    NOW + timedelta(minutes=20), NOW + timedelta(hours=1), 0.4
                ),
            ]
        )
        self.assertFalse(
            any(
                w["start"] == NOW.timestamp()
                for w in opportunities(gap, NOW, 1800, 3600)
            )
        )


class EngineTests(unittest.TestCase):
    def decide(self, fx):
        return evaluate(*fx)

    def test_heating_works_without_forecast_and_with_unknown_price(self):
        f = fixture()
        d = self.decide(f)["0"]
        self.assertEqual(d.mode, "heat")
        h, s, _, m, p = f
        self.assertEqual(evaluate(h, s, (), m, p)["0"].mode, "heat")

    def test_maintenance_not_same_as_new_command(self):
        h, s, prices, m, pm = fixture()
        o = replace(
            s.zones["0"],
            mode="heat",
            setpoint=19.5,
            temperature=Reading(19.4, NOW.timestamp()),
        )
        d = evaluate(h, replace(s, zones={"0": o}), prices, m, pm)["0"]
        self.assertEqual(
            (d.stage, d.mode, d.reason), ("maintaining", "heat", "already_satisfied")
        )

    def test_start_minimum_off_overshoot_and_minimum_run(self):
        h, s, prices, m, pm = fixture()
        t = NOW.timestamp()
        d = evaluate(
            h,
            replace(s, zones={"0": replace(s.zones["0"], mode_since=t - 10)}),
            prices,
            m,
            pm,
        )["0"]
        self.assertEqual(d.reason, "minimum_off")
        hot = replace(
            s.zones["0"], mode="heat", mode_since=t - 10, temperature=Reading(20.1, t)
        )
        d = evaluate(h, replace(s, zones={"0": hot}), prices, {}, {})["0"]
        self.assertEqual((d.reason, d.mode), ("temperature_overshoot", "off"))
        hot = replace(hot, temperature=Reading(19.8, t))
        d = evaluate(h, replace(s, zones={"0": hot}), prices, {}, {})["0"]
        self.assertEqual(d.stage, "settling")

    def test_stale_one_zone_does_not_stop_healthy_zone(self):
        h, s, prices, m, pm = fixture(2)
        obs = dict(s.zones)
        obs["0"] = replace(obs["0"], temperature=Reading(18, NOW.timestamp() - 8000))
        d = evaluate(h, replace(s, zones=obs), prices, m, pm)
        self.assertEqual(d["0"].reason, "temperature_stale")
        self.assertEqual(d["1"].mode, "heat")

    def test_manual_and_unknown_occupancy(self):
        h, s, prices, m, pm = fixture()
        o = replace(s.zones["0"], automatic=False)
        self.assertEqual(
            evaluate(h, replace(s, zones={"0": o}), prices, m, pm)["0"].stage, "manual"
        )
        self.assertEqual(
            evaluate(h, replace(s, occupied=None), prices, {}, {})["0"].reason,
            "occupancy_unconfirmed",
        )

    def test_power_loss_blocks_increase_but_allows_reduction(self):
        h, s, prices, m, pm = fixture()
        s = replace(s, power=Reading(None))
        self.assertEqual(
            evaluate(h, s, prices, m, pm)["0"].reason, "power_data_or_budget"
        )
        o = replace(
            s.zones["0"],
            mode="heat",
            setpoint=24,
            temperature=Reading(19.4, NOW.timestamp()),
        )
        self.assertEqual(
            evaluate(h, replace(s, zones={"0": o}), prices, {}, {})["0"].mode, "heat"
        )
        self.assertEqual(
            evaluate(h, replace(s, require_power=False), prices, {}, {})["0"].mode,
            "heat",
        )

    def test_hardware_bias_boost_relaxation_and_limits(self):
        h, s, *_ = fixture()
        z = replace(h.zones[0], bias=3)
        o = s.zones["0"]
        now = NOW.timestamp()
        self.assertGreater(hardware_target(z, o, 20, "heat", h, now), 20)
        near = replace(o, temperature=Reading(20, now), internal=Reading(23, now))
        self.assertLess(
            hardware_target(z, near, 20, "heat", h, now),
            hardware_target(z, o, 20, "heat", h, now),
        )
        limited = replace(o, maximum=21)
        self.assertLessEqual(hardware_target(z, limited, 22, "heat", h, now), 21)

    def humidity_fixture(self):
        h, s, prices, m, pm = fixture()
        o = replace(s.zones["0"], temperature=Reading(21.2, NOW.timestamp()))
        s = replace(s, zones={"0": o})
        m["0"] = Memory(day="2026-11-05", high_since=NOW.timestamp() - 1000)
        return h, s, prices, m, pm

    def test_drying_floor_is_independent_of_economic_heat_goal(self):
        h, s, _, m, pm = self.humidity_fixture()
        bands = tuple(
            replace(b, heat_day=22) if b.name == "negative" else b
            for b in h.policy.bands
        )
        h = replace(h, policy=replace(h.policy, bands=bands))
        o = replace(s.zones["0"], temperature=Reading(22.1, NOW.timestamp()))
        d = evaluate(
            h,
            replace(s, zones={"0": o}),
            (PriceInterval(NOW, NOW + timedelta(hours=2), -0.01),),
            m,
            pm,
        )["0"]
        self.assertEqual(d.mode, "dry")

    def test_cheaper_complete_window_wait_and_urgent_override(self):
        h, s, _, m, pm = self.humidity_fixture()
        prices = (
            PriceInterval(NOW, NOW + timedelta(hours=1), 0.19),
            PriceInterval(NOW + timedelta(hours=1), NOW + timedelta(hours=3), -0.01),
        )
        self.assertEqual(
            evaluate(h, s, prices, m, pm)["0"].reason, "cheaper_complete_window"
        )
        m["0"].urgent_since = NOW.timestamp() - 1900
        self.assertEqual(evaluate(h, s, prices, m, pm)["0"].mode, "dry")

    def test_cold_room_does_not_dry_and_heat_still_has_priority(self):
        h, s, prices, m, pm = self.humidity_fixture()
        o = replace(s.zones["0"], temperature=Reading(20.2, NOW.timestamp()))
        self.assertEqual(
            evaluate(h, replace(s, zones={"0": o}), prices, m, pm)["0"].reason,
            "insufficient_thermal_margin",
        )
        h, s, prices, m, pm = fixture(2)
        obs = dict(s.zones)
        obs["0"] = replace(obs["0"], temperature=Reading(21.2, NOW.timestamp()))
        m["0"] = Memory(day="2026-11-05", high_since=NOW.timestamp() - 1000)
        d = evaluate(h, replace(s, zones=obs), prices, m, pm)
        self.assertEqual(d["1"].mode, "heat")
        self.assertEqual(d["0"].reason, "plant_mode_reserved")

    def test_owned_dry_maximum_survives_pause_and_unknown_sensor(self):
        h, s, prices, m, pm = self.humidity_fixture()
        begin_dry(m["0"], NOW.timestamp() - 1900, 20, 60, 1800)
        o = replace(s.zones["0"], mode="dry", temperature=Reading(None))
        s = replace(s, zones={"0": o}, paused=True)
        d = evaluate(h, s, prices, m, pm)["0"]
        self.assertEqual((d.stage, d.mode), ("dry_stop", "off"))
        self.assertGreater(m["0"].dry_until, 0)

    def test_no_adoption_of_unowned_dry(self):
        h, s, prices, m, pm = self.humidity_fixture()
        o = replace(s.zones["0"], mode="dry")
        self.assertEqual(
            evaluate(h, replace(s, zones={"0": o}), prices, m, pm)["0"].reason,
            "unowned_drying",
        )

    def test_dry_pending_echo_and_daily_budget_persist(self):
        h, s, prices, m, pm = self.humidity_fixture()
        begin_dry(m["0"], NOW.timestamp() - 1, 20, 60, 1800)
        d = evaluate(h, s, prices, m, pm)["0"]
        self.assertEqual(d.reason, "dry_ack_pending")
        self.assertEqual(m["0"].attempts, 1)
        m["0"].dry_until = 0
        m["0"].dry_active = False  # explicit end; until=0 alone now means unlimited
        m["0"].attempts = 2
        d = evaluate(h, s, prices, m, pm)["0"]
        self.assertEqual(d.reason, "dry_budget")
        self.assertGreater(d.next_at, NOW.timestamp())

    def test_price_change_does_not_erase_service_debt(self):
        h, s, prices, m, pm = self.humidity_fixture()
        bands = tuple(
            replace(b, humidity_start=70, humidity_stop=65) if b.name == "high" else b
            for b in h.policy.bands
        )
        h = replace(h, policy=replace(h.policy, bands=bands))
        o = replace(s.zones["0"], humidity=Reading(68, NOW.timestamp()))
        m["0"].debt_since = NOW.timestamp() - 15000
        d = evaluate(
            h,
            replace(s, zones={"0": o}),
            (PriceInterval(NOW, NOW + timedelta(hours=1), 0.25),),
            m,
            pm,
        )["0"]
        self.assertTrue(d.urgent)
        self.assertEqual(d.mode, "dry")

    def test_dew_point_distinguishes_heating_from_removal(self):
        self.assertGreater(dew_point(20, 80), dew_point(20, 60))
        with self.assertRaises(ValueError):
            dew_point(20, 0)


class PersistenceAndAuthorityTests(unittest.TestCase):
    def test_corrupt_memory_is_rejected(self):
        for values in [{"dry_until": "wrong"}, {"attempts": -1}, {"day": "not-a-date"}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                Memory(**values)

    def test_zone_disabled_never_requests_a_start(self):
        h, s, prices, m, pm = fixture()
        h = replace(h, zones=(replace(h.zones[0], enabled=False),))
        d = evaluate(h, s, prices, m, pm)["0"]
        self.assertEqual((d.stage, d.mode), ("paused", None))

    def test_manual_cancels_owned_intent_without_erasing_budget(self):
        h, s, prices, m, pm = fixture()
        m["0"] = Memory(day="2026-11-05")
        begin_dry(m["0"], NOW.timestamp() - 60, 20, 60, 1800)
        s = replace(s, zones={"0": replace(s.zones["0"], mode="dry", automatic=False)})
        d = evaluate(h, s, prices, m, pm)["0"]
        self.assertEqual((d.stage, d.mode), ("manual", None))
        self.assertEqual(m["0"].dry_until, 0)
        self.assertEqual(m["0"].attempts, 1)

    def test_independent_plants_do_not_share_direction_lock(self):
        h, s, prices, m, pm = fixture(2)
        h = replace(
            h,
            plants=(Plant("plant", "Heat"), Plant("other", "Cool")),
            zones=(h.zones[0], replace(h.zones[1], plant="other")),
        )
        obs = dict(s.zones)
        obs["1"] = replace(obs["1"], temperature=Reading(28, NOW.timestamp()))
        decisions = evaluate(h, replace(s, zones=obs), prices, m, pm)
        self.assertEqual(decisions["0"].mode, "heat")
        self.assertEqual(decisions["1"].mode, "cool")

    def test_daytime_override_survives_profile_roundtrip(self):
        h, s, prices, m, pm = fixture()
        h = house_from_dict(
            asdict(
                replace(h, zones=(replace(h.zones[0], heat_targets={"normal": 22}),))
            )
        )
        self.assertEqual(evaluate(h, s, prices, m, pm)["0"].heat_goal, 22)


if __name__ == "__main__":
    unittest.main()
