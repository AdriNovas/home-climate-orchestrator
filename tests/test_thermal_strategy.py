"""Synthetic acceptance boundaries for optional economic and inverter proposals."""

from dataclasses import asdict, replace
from datetime import timedelta
import unittest

from test_domain import fixture, NOW
from domain.models import Memory, Policy, Reading, PriceInterval
from domain.engine import evaluate


def observed(snapshot, *, seconds=0, temperature=19.6, mode="heat", fresh=True):
    now = snapshot.now + timedelta(seconds=seconds)
    stamp = now.timestamp() if fresh else snapshot.zones["0"].temperature.at
    return replace(
        snapshot,
        now=now,
        zones={
            "0": replace(
                snapshot.zones["0"],
                temperature=Reading(temperature, stamp),
                internal=Reading(24, now.timestamp()),
                mode=mode,
            )
        },
        power=Reading(100, now.timestamp()),
    )


def priced(value):
    return (PriceInterval(NOW - timedelta(hours=1), NOW + timedelta(hours=5), value),)


class HoldTests(unittest.TestCase):
    def test_defaults_leave_existing_maintenance_unchanged(self):
        h, s, p, m, plants = fixture()
        self.assertEqual(
            evaluate(h, observed(s), p, m, plants)["0"].stage, "maintaining"
        )

    def test_heating_hold_reduces_same_mode_target(self):
        h, s, p, m, plants = fixture(modulated_hold_s=1800)
        s = observed(s)
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual((d.stage, d.mode), ("holding", "heat"))
        self.assertLessEqual(d.physical_target, s.zones["0"].setpoint)
        self.assertEqual(m["0"].hold_since, s.now.timestamp())

    def test_cooling_hold_increases_setpoint_without_reversal(self):
        h, s, p, m, plants = fixture(modulated_hold_s=1800)
        s = observed(s, temperature=26, mode="cool")
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual((d.stage, d.mode), ("holding", "cool"))
        self.assertGreaterEqual(d.physical_target, s.zones["0"].setpoint)

    def test_no_start_just_to_enter_hold(self):
        h, s, p, m, plants = fixture(modulated_hold_s=1800)
        d = evaluate(h, observed(s, mode="off"), p, m, plants)["0"]
        self.assertEqual((d.stage, d.mode), ("idle", None))

    def test_expiry_stops_without_restarting_budget(self):
        h, s, p, m, plants = fixture(modulated_hold_s=60)
        s = observed(s)
        evaluate(h, s, p, m, plants)
        start = m["0"].hold_since
        d = evaluate(h, observed(s, seconds=60), p, m, plants)["0"]
        self.assertEqual((d.reason, d.mode), ("hold_budget_expired", "off"))
        self.assertEqual(m["0"].hold_since, start)
        self.assertEqual(
            evaluate(h, observed(s, seconds=61), p, m, plants)["0"].mode, "off"
        )

    def test_expiry_respects_minimum_run(self):
        h, s, p, m, plants = fixture(modulated_hold_s=60)
        s = observed(s)
        s = replace(s, zones={"0": replace(s.zones["0"], mode_since=s.now.timestamp())})
        evaluate(h, s, p, m, plants)
        d = evaluate(h, observed(s, seconds=60), p, m, plants)["0"]
        self.assertEqual((d.stage, d.mode), ("settling", "heat"))
        self.assertEqual(d.next_at, s.now.timestamp() + 1200)

    def test_real_deficit_exits_hold_and_resumes_regulation(self):
        h, s, p, m, plants = fixture(modulated_hold_s=60)
        s = observed(s)
        evaluate(h, s, p, m, plants)
        d = evaluate(h, observed(s, seconds=90, temperature=18.8), p, m, plants)["0"]
        self.assertEqual((d.stage, d.mode), ("recovering", "heat"))
        self.assertEqual(m["0"].hold_since, 0)

    def test_overshoot_protection_does_not_wait_for_hold(self):
        h, s, p, m, plants = fixture(modulated_hold_s=1800)
        d = evaluate(h, observed(s, temperature=20), p, m, plants)["0"]
        self.assertEqual((d.reason, d.mode), ("temperature_overshoot", "off"))

    def test_stale_internal_or_incapable_actuator_cannot_claim_hold(self):
        for changes in [
            {"internal": Reading(24, 0)},
            {"supported_modes": ("off",)},
            {"setpoint": 2},
        ]:
            with self.subTest(changes=changes):
                h, s, p, m, plants = fixture(modulated_hold_s=1800)
                s = observed(s)
                s = replace(s, zones={"0": replace(s.zones["0"], **changes)})
                self.assertNotEqual(evaluate(h, s, p, m, plants)["0"].stage, "holding")

    def test_future_stored_hold_clock_cannot_extend_budget(self):
        h, s, p, m, plants = fixture(modulated_hold_s=900)
        s = observed(s)
        m["0"] = Memory(hold_mode="heat", hold_since=NOW.timestamp() + 50000)
        evaluate(h, s, p, m, plants)
        self.assertEqual(m["0"].hold_since, NOW.timestamp())

    def test_pause_or_manual_discards_hold_clock(self):
        for manual in [False, True]:
            h, s, p, m, plants = fixture(modulated_hold_s=1800)
            s = observed(s)
            evaluate(h, s, p, m, plants)
            s = replace(
                s,
                paused=not manual,
                zones={"0": replace(s.zones["0"], automatic=not manual)},
            )
            d = evaluate(h, s, p, m, plants)["0"]
            self.assertEqual(d.stage, "manual" if manual else "paused")
            self.assertIsNone(d.mode)
            self.assertEqual(m["0"].hold_since, 0)

    def test_persistent_hold_survives_reload_without_new_budget(self):
        h, s, p, m, plants = fixture(modulated_hold_s=900)
        s = observed(s)
        evaluate(h, s, p, m, plants)
        restored = {"0": Memory(**asdict(m["0"]))}
        d = evaluate(h, observed(s, seconds=900), p, restored, plants)["0"]
        self.assertEqual(d.reason, "hold_budget_expired")

    def test_hold_cannot_increase_demand_when_power_is_missing(self):
        h, s, p, m, plants = fixture(modulated_hold_s=900)
        s = observed(s)
        s = replace(s, power=Reading(None))
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual(d.stage, "holding")
        self.assertLessEqual(d.physical_target, s.zones["0"].setpoint)

    def test_hold_remains_subject_to_shared_outdoor_conflicts(self):
        h, s, p, m, plants = fixture(zones=2, modulated_hold_s=900)
        first = replace(
            s.zones["0"],
            mode="heat",
            temperature=Reading(19.6, NOW.timestamp()),
            internal=Reading(24, NOW.timestamp()),
        )
        second = replace(s.zones["1"], mode="cool", automatic=False)
        s = replace(s, zones={"0": first, "1": second})
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual(d.reason, "plant_mode_reserved")
        self.assertIsNone(d.mode)


class EconomicTests(unittest.TestCase):
    def setup_case(self, **policy):
        h, s, _, m, plants = fixture(extreme_price_enabled=True, **policy)
        # A tariff crossing can change goals independently; hold those fixed here
        # to isolate the price latch rather than accidentally testing a deficit.
        h = replace(
            h,
            policy=replace(
                h.policy, bands=tuple(replace(b, heat_day=19.5) for b in h.policy.bands)
            ),
        )
        return h, observed(s), m, plants

    def test_one_sample_does_not_prove_stability(self):
        h, s, m, plants = self.setup_case()
        d = evaluate(h, s, priced(0.35), m, plants)["0"]
        self.assertNotEqual(d.reason, "extreme_price_stable")

    def test_new_stable_reports_allow_economic_shutdown(self):
        h, s, m, plants = self.setup_case()
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(h, observed(s, seconds=900), priced(0.35), m, plants)["0"]
        self.assertEqual((d.reason, d.mode), ("extreme_price_stable", "off"))

    def test_repeated_old_report_does_not_mature_stability(self):
        h, s, m, plants = self.setup_case()
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(h, observed(s, seconds=900, fresh=False), priced(0.35), m, plants)[
            "0"
        ]
        self.assertNotEqual(d.reason, "extreme_price_stable")

    def test_scheduler_gap_or_source_gap_resets_evidence(self):
        h, s, m, plants = self.setup_case()
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(h, observed(s, seconds=1201), priced(0.35), m, plants)["0"]
        self.assertNotEqual(d.reason, "extreme_price_stable")

    def test_temperature_drift_resets_stability(self):
        h, s, m, plants = self.setup_case(thermal_stability_delta=0.1)
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(
            h, observed(s, seconds=900, temperature=19.4), priced(0.35), m, plants
        )["0"]
        self.assertNotEqual(d.reason, "extreme_price_stable")

    def test_price_exit_uses_hysteresis_and_missing_price_releases(self):
        h, s, m, plants = self.setup_case()
        evaluate(h, s, priced(0.35), m, plants)
        for seconds, value, coasting in [
            (900, 0.29, True),
            (960, 0.27, False),
            (1020, 0.29, False),
            (1080, 0.35, True),
        ]:
            d = evaluate(h, observed(s, seconds=seconds), priced(value), m, plants)["0"]
            self.assertEqual(d.reason == "extreme_price_stable", coasting)
        d = evaluate(h, observed(s, seconds=1140), (), m, plants)["0"]
        self.assertNotEqual(d.reason, "extreme_price_stable")
        self.assertFalse(m["0"].extreme_active)

    def test_comfort_deficit_overrides_economic_cut(self):
        h, s, m, plants = self.setup_case()
        s = observed(s, temperature=18.8)
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(
            h, observed(s, seconds=900, temperature=18.8), priced(0.35), m, plants
        )["0"]
        self.assertEqual((d.stage, d.mode), ("recovering", "heat"))

    def test_price_alone_cannot_bypass_minimum_run(self):
        h, s, m, plants = self.setup_case(thermal_stable_s=60)
        s = replace(s, zones={"0": replace(s.zones["0"], mode_since=s.now.timestamp())})
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(h, observed(s, seconds=60), priced(0.35), m, plants)["0"]
        self.assertEqual((d.reason, d.mode), ("economic_minimum_run", "heat"))

    def test_off_during_extreme_stays_off_without_claiming_a_start(self):
        h, s, m, plants = self.setup_case()
        s = observed(s, mode="off")
        evaluate(h, s, priced(0.35), m, plants)
        d = evaluate(h, observed(s, seconds=900, mode="off"), priced(0.35), m, plants)[
            "0"
        ]
        self.assertEqual((d.stage, d.mode), ("coasting", "off"))

    def test_safety_configuration_is_bounded_and_typed(self):
        for values in [
            {"modulated_hold_s": -1},
            {"modulated_hold_s": 7201},
            {"extreme_price_enabled": "true"},
            {"extreme_price": float("nan")},
            {"extreme_price_hysteresis": 0.30},
            {"thermal_stable_s": 0},
            {"thermal_stability_delta": 0},
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                Policy(**values)
