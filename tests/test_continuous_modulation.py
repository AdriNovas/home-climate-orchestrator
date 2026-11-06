"""Comfort continuity and non-additive shared-plant feedback boundaries."""

from dataclasses import asdict, replace
from datetime import timedelta
import unittest

from test_domain import fixture, NOW
from domain.models import Reading, Policy, PlantMemory, house_from_dict
from domain.engine import evaluate, hardware_target
from domain.modulation import observe_shared_load, observe_room


def configuration(count=1, power=100, **changes):
    house, snap, prices, memory, plants = fixture(
        zones=count,
        continuous_hold=True,
        shared_load_management=True,
        overshoot_delta=2,
        proportional_gain=1,
    )
    stamp = snap.now.timestamp()
    obs = {
        key: replace(
            value,
            mode="heat",
            temperature=Reading(19.6, stamp),
            internal=Reading(24, stamp),
            setpoint=19,
            **changes,
        )
        for key, value in snap.zones.items()
    }
    return (
        house,
        replace(snap, zones=obs, plant_power={"plant": Reading(power, stamp)}),
        prices,
        memory,
        plants,
    )


class ContinuousTests(unittest.TestCase):
    def test_four_zone_tables_inherit_and_override_independently(self):
        h, s, p, m, plants = configuration()
        z = replace(
            h.zones[0],
            heat_targets={"normal": 21},
            cool_targets={"normal": 28},
            heat_sleep_targets={"normal": 18},
            cool_sleep_targets={"normal": 29},
            night_allowed=True,
        )
        h = house_from_dict(asdict(replace(h, zones=(z,))))
        day = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual((day.heat_goal, day.cool_goal), (21, 28))
        night = replace(s, now=NOW.replace(hour=22))
        d = evaluate(h, night, p, m, plants)["0"]
        self.assertEqual((d.heat_goal, d.cool_goal), (18, 29))
        inherited = replace(h, zones=(replace(z, cool_sleep_targets={}),))
        self.assertEqual(
            evaluate(inherited, night, p, m, plants)["0"].cool_goal,
            h.policy.band(None).cool_sleep
            if h.policy.band(None)
            else h.policy.bands[3].cool_sleep,
        )

    def test_price_band_and_phase_conflicts_are_rejected_per_zone(self):
        h, *_ = configuration()
        for tables in [
            {"cool_targets": {"missing": 27}},
            {
                "heat_sleep_targets": {"normal": 29},
                "cool_sleep_targets": {"normal": 28},
            },
            {"heat_targets": {"normal": 29}, "cool_targets": {"normal": 28}},
        ]:
            with self.assertRaises(ValueError):
                replace(h, zones=(replace(h.zones[0], **tables),))

    def test_day_long_low_load_has_no_hold_timeout(self):
        h, s, p, m, plants = configuration()
        h = replace(h, zones=tuple(replace(z, night_allowed=True) for z in h.zones))
        for minutes in range(0, 24 * 60 + 1, 5):
            stamp = NOW.timestamp() + minutes * 60
            zone = replace(
                s.zones["0"],
                temperature=Reading(19.6, stamp),
                internal=Reading(24, stamp),
                heat_goal=Reading(19.5, stamp),
            )
            snap = replace(
                s,
                now=NOW + timedelta(minutes=minutes),
                zones={"0": zone},
                plant_power={"plant": Reading(100, stamp)},
                power=Reading(100, stamp),
            )
            d = evaluate(h, snap, p, m, plants)["0"]
            self.assertEqual((d.stage, d.mode), ("holding", "heat"))
            self.assertIsNone(d.next_at)

    def test_small_excess_relaxes_and_large_excess_stops(self):
        h, s, p, m, plants = configuration()
        for excess, expected in [
            (0.2, "heat"),
            (0.7, "heat"),
            (1.9, "heat"),
            (2, "off"),
        ]:
            o = replace(
                s.zones["0"], temperature=Reading(19.5 + excess, NOW.timestamp())
            )
            d = evaluate(h, replace(s, zones={"0": o}), p, m, plants)["0"]
            self.assertEqual(d.mode, expected)
            if expected == "heat":
                self.assertLess(d.physical_target, 19.5)

    def test_cooling_is_symmetric(self):
        h, s, p, m, plants = configuration()
        for excess, expected in [
            (0.2, "cool"),
            (0.7, "cool"),
            (1.9, "cool"),
            (2, "off"),
        ]:
            o = replace(
                s.zones["0"],
                mode="cool",
                temperature=Reading(26 - excess, NOW.timestamp()),
                internal=Reading(25, NOW.timestamp()),
                setpoint=27,
            )
            self.assertEqual(
                evaluate(h, replace(s, zones={"0": o}), p, m, plants)["0"].mode,
                expected,
            )

    def test_internal_mismatch_does_not_redefine_comfort_goal(self):
        h, s, *_ = configuration()
        z = replace(h.zones[0], bias=2)
        cold = replace(
            s.zones["0"],
            temperature=Reading(20, NOW.timestamp()),
            internal=Reading(24, NOW.timestamp()),
        )
        self.assertGreater(hardware_target(z, cold, 22, "heat", h, NOW.timestamp()), 24)
        warm = replace(cold, temperature=Reading(22.2, NOW.timestamp()))
        self.assertLess(hardware_target(z, warm, 22, "heat", h, NOW.timestamp()), 24)

    def test_validated_trim_never_uses_a_foreign_or_old_goal(self):
        h, s, *_ = configuration()
        z = replace(h.zones[0], response_entity="input_text.response")
        o = s.zones["0"]
        now = NOW.timestamp()
        base = hardware_target(z, o, 19.5, "heat", h, now)
        for record in [
            {"at": now - 900, "m": "heat", "g": 19.5, "h": 2},
            {"at": now, "m": "cool", "g": 19.5, "h": 2},
            {"at": now, "m": "heat", "g": 22, "h": 2},
        ]:
            self.assertEqual(
                hardware_target(z, replace(o, response=record), 19.5, "heat", h, now),
                base,
            )
        self.assertLess(
            hardware_target(
                z,
                replace(o, response={"at": now, "m": "heat", "g": 19.5, "h": 2}),
                19.5,
                "heat",
                h,
                now,
            ),
            base,
        )

    def test_no_start_to_create_idle_and_no_house_meter_substitute(self):
        h, s, p, m, plants = configuration(power=900)
        s = replace(s, zones={"0": replace(s.zones["0"], mode="off")}, plant_power={})
        self.assertIsNone(evaluate(h, s, p, m, plants)["0"].mode)
        self.assertIsNone(plants["plant"].modulation.get("r"))


class SharedLoadTests(unittest.TestCase):
    def setup_case(self, count=5):
        self.h, self.s, *_ = configuration(count=count, power=900)
        self.now = NOW.timestamp()
        self.goals = {key: 19.5 for key in self.s.zones}

    def sample(
        self, state, seconds=0, power=900, zones=None, permitted=True, report=True
    ):
        stamp = self.now + seconds
        observations = {
            key: replace(
                o,
                temperature=Reading(o.temperature.value, stamp if report else self.now),
                internal=Reading(o.internal.value, stamp),
            )
            for key, o in (zones or self.s.zones).items()
        }
        return observe_shared_load(
            observations,
            self.goals,
            Reading(power, stamp),
            state,
            stamp,
            self.h.policy,
            1200,
            permitted,
        )

    def test_one_or_many_heads_one_staged_intent_after_measured_episode(self):
        for count in [1, 5]:
            self.setup_case(count)
            state = {}
            for t in range(0, 1200, 300):
                state = self.sample(state, t)
                self.assertIsNone(state["r"])
            state = self.sample(state, 1200)
            self.assertIn(state["r"], self.s.zones)
            self.assertEqual(len(state["c"]), 1)
            lease = self.sample(state, 1210)
            self.assertEqual(lease["r"], state["r"])
            self.assertIsNone(self.sample(state, 1291)["r"])

    def test_aggregate_baselines_are_configuration_observations_not_allocations(self):
        self.setup_case()
        state = self.sample({}, power=100)
        self.assertEqual(state["b"], {"5": 100})
        self.assertNotIn("zone_power", state)
        for t in range(300, 3900, 300):
            state = self.sample(state, t, power=100)
            self.assertIsNone(state["r"])

    def test_manual_new_demand_conflict_and_pause_cancel_lease(self):
        self.setup_case()
        state = {}
        for t in range(0, 1201, 300):
            state = self.sample(state, t)
        for change in [
            {"automatic": False},
            {"temperature": Reading(18, self.now + 1210)},
            {"mode": "dry"},
            {"internal": Reading(None)},
        ]:
            obs = dict(self.s.zones)
            obs["0"] = replace(obs["0"], **change)
            self.assertIsNone(self.sample(state, 1210, zones=obs)["r"])
        self.assertIsNone(self.sample(state, 1210, permitted=False)["r"])

    def test_frozen_thermal_reports_and_gaps_do_not_manufacture_evidence(self):
        self.setup_case()
        state = {}
        for t in range(0, 3601, 300):
            state = self.sample(state, t, report=False)
            self.assertIsNone(state["r"])
        state = self.sample(state, 5000)
        self.assertEqual(state["s"], self.now + 5000)
        self.assertIsNone(state["r"])

    def test_meter_loss_restarts_episode_and_retains_retry_budget(self):
        self.setup_case()
        state = {}
        for t in range(0, 1201, 300):
            state = self.sample(state, t)
        candidate = state["r"]
        missing = observe_shared_load(
            self.s.zones,
            self.goals,
            Reading(None),
            state,
            self.now + 1500,
            self.h.policy,
            1200,
        )
        self.assertEqual(missing["s"], 0)
        self.assertEqual(missing["c"][candidate], state["c"][candidate])
        restored = PlantMemory(**asdict(PlantMemory(modulation=missing)))
        self.assertEqual(restored.modulation, missing)

    def test_effect_is_an_observed_aggregate_delta_not_head_power(self):
        self.setup_case()
        state = {}
        for t in range(0, 1201, 300):
            state = self.sample(state, t)
        obs = dict(self.s.zones)
        obs[state["r"]] = replace(obs[state["r"]], mode="off")
        after = self.sample(state, 1500, power=100, zones=obs)
        self.assertEqual(after["delta"], -800)
        self.assertIsNone(after["r"])

    def test_new_cheap_hour_goal_invalidates_coasting(self):
        self.setup_case()
        state = {}
        for t in range(0, 1201, 300):
            state = self.sample(state, t)
        self.goals = {key: 22 for key in self.s.zones}
        self.assertIsNone(self.sample(state, 1210)["r"])

    def test_configuration_rejects_ambiguous_enablement_and_thresholds(self):
        for kwargs in [
            {"continuous_hold": 1},
            {"shared_load_management": True},
            {"shared_load_idle_w": 300, "shared_load_high_w": 250},
            {"shared_load_observe_s": 10},
        ]:
            with self.assertRaises(ValueError):
                Policy(**kwargs)


class RoomFeedbackTests(unittest.TestCase):
    def test_stalled_demand_builds_bounded_effort_from_distinct_reports(self):
        h, s, *_ = configuration()
        now = NOW.timestamp()
        state = {}
        for i in range(10):
            stamp = now + i * 300
            o = replace(
                s.zones["0"],
                temperature=Reading(18, stamp),
                internal=Reading(24, stamp),
            )
            state = observe_room(
                o, 19.5, Reading(100, stamp), state, stamp, h.policy, True
            )
            self.assertLessEqual(state["b"], 2.5)
        self.assertEqual(state["b"], 2.5)
        self.assertEqual(state["h"], 0)

    def test_low_high_missing_power_only_corroborate_room_drift(self):
        h, s, *_ = configuration()
        now = NOW.timestamp()
        old = {
            "at": now - 300,
            "m": "heat",
            "g": 19.5,
            "t": 19.5,
            "qa": now - 300,
            "s": 0,
            "b": 0,
            "h": 0,
        }
        for watts, expected in [(100, 0), (900, 0.5), (None, 0)]:
            o = replace(
                s.zones["0"], temperature=Reading(19.7, now), internal=Reading(24, now)
            )
            state = observe_room(o, 19.5, Reading(watts, now), old, now, h.policy, True)
            self.assertEqual(state["h"], expected)
            # Repeated planner calls/report timestamps cannot add more trim.
            self.assertEqual(
                observe_room(
                    o, 19.5, Reading(watts, now), state, now + 30, h.policy, True
                )["h"],
                expected,
            )

    def test_manual_pause_sensor_loss_and_goal_change_reset_feedback(self):
        h, s, *_ = configuration()
        now = NOW.timestamp()
        old = {
            "at": now - 300,
            "m": "heat",
            "g": 19.5,
            "t": 19.5,
            "qa": now - 300,
            "b": 2,
            "h": 2,
        }
        for changes, allowed in [
            ({"automatic": False}, True),
            ({}, False),
            ({"temperature": Reading(None)}, True),
        ]:
            self.assertEqual(
                observe_room(
                    replace(s.zones["0"], **changes),
                    19.5,
                    Reading(900, now),
                    old,
                    now,
                    h.policy,
                    allowed,
                ),
                {},
            )
        state = observe_room(
            s.zones["0"], 22, Reading(900, now), old, now, h.policy, True
        )
        self.assertEqual((state["h"], state["b"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
