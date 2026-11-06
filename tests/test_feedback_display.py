"""Opt-in protective exits and OFF display updates are distinct actuator intents."""

from dataclasses import replace
import time
import unittest

from test_domain import fixture, NOW
from test_execution import Store
from domain.models import Reading
from domain.engine import evaluate
from execution import Executor


class FeedbackDisplayTests(unittest.TestCase):
    def case(self, **zone_changes):
        h, s, p, m, plants = fixture(2, continuous_hold=True, overshoot_delta=2)
        h = replace(h, zones=(replace(h.zones[0], **zone_changes), h.zones[1]))
        return h, s, p, m, plants

    def test_feedback_stop_requires_deliberate_configuration(self):
        for changes, expected in [
            ({}, None),
            ({"feedback_loss_action": "stop"}, "off"),
        ]:
            h, s, p, m, plants = self.case(**changes)
            s.zones["0"] = replace(s.zones["0"], mode="heat", temperature=Reading(None))
            self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, expected)

    def test_each_thermal_feedback_source_can_stop_heat_and_cool(self):
        for mode in ["heat", "cool"]:
            for change in [
                {"temperature": Reading(None)},
                {"internal": Reading(None)},
                {"bias": Reading(None)},
                {"internal": Reading(20, NOW.timestamp() - 601)},
            ]:
                h, s, p, m, plants = self.case(
                    feedback_loss_action="stop",
                    require_internal_feedback=True,
                    bias_entity="input_number.demo_bias",
                )
                obs = replace(
                    s.zones["0"],
                    **{"mode": mode, "bias": Reading(0, NOW.timestamp()), **change},
                )
                s.zones["0"] = obs
                d = evaluate(h, s, p, m, plants)
                self.assertEqual(
                    (d["0"].mode, d["0"].reason), ("off", "thermal_feedback_lost")
                )
                if mode == "heat":
                    self.assertEqual(d["1"].mode, "heat")
                else:
                    self.assertEqual(d["1"].reason, "plant_mode_conflict")

    def test_feedback_stop_never_seizes_manual_pause_or_unowned_dry(self):
        h, s, p, m, plants = self.case(
            feedback_loss_action="stop", require_internal_feedback=True
        )
        base = replace(s.zones["0"], mode="heat", internal=Reading(None))
        for changes, paused in [
            ({"automatic": False}, False),
            ({"permitted": False}, False),
            ({}, True),
            ({"mode": "off"}, False),
            ({"mode": "dry"}, False),
            ({"mode": "unknown"}, False),
            ({"mode": "unavailable"}, False),
        ]:
            s.zones["0"] = replace(base, **changes)
            self.assertNotEqual(
                evaluate(h, replace(s, paused=paused), p, m, plants)["0"].mode, "off"
            )

    def test_invalid_feedback_policy_is_rejected_not_truthy(self):
        h, *_ = fixture()
        for value in [True, "on", None, "shutdown"]:
            with self.assertRaises(ValueError):
                replace(h.zones[0], feedback_loss_action=value)

    def test_display_update_is_not_a_thermal_start(self):
        h, s, p, m, plants = self.case(off_goal_entity="number.demo_display")
        s.zones["0"] = replace(
            s.zones["0"],
            temperature=Reading(22, NOW.timestamp()),
            off_goal=Reading(20, NOW.timestamp()),
        )
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual(
            (d.stage, d.mode, d.physical_target, d.target_only),
            ("off_display", "off", 20, True),
        )
        s.zones["0"] = replace(s.zones["0"], temperature=Reading(18, NOW.timestamp()))
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual(d.mode, "heat")
        self.assertFalse(d.target_only)

    def test_display_during_minimum_off_preserves_the_thermal_deadline(self):
        h, s, p, m, plants = self.case(off_goal_entity="number.demo_display")
        s.zones["0"] = replace(
            s.zones["0"],
            mode_since=NOW.timestamp() - 1,
            off_goal=Reading(20, NOW.timestamp()),
        )
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertTrue(d.target_only)
        self.assertEqual(d.next_at, s.zones["0"].mode_since + h.plants[0].minimum_off_s)

    def test_display_needs_available_bounded_source_and_authority(self):
        h, s, p, m, plants = self.case(off_goal_entity="number.demo_display")
        base = replace(
            s.zones["0"],
            temperature=Reading(22, NOW.timestamp()),
            off_goal=Reading(20, NOW.timestamp()),
        )
        for changes, paused in [
            ({"off_goal": Reading(None)}, False),
            ({"off_goal": Reading(20, NOW.timestamp() - 7201)}, False),
            ({"off_goal": Reading(20, NOW.timestamp() + 1)}, False),
            ({"off_goal": Reading(31, NOW.timestamp())}, False),
            ({"automatic": False}, False),
            ({"permitted": False}, False),
            ({}, True),
            ({"mode": "unknown"}, False),
        ]:
            s.zones["0"] = replace(base, **changes)
            self.assertFalse(
                evaluate(h, replace(s, paused=paused), p, m, plants)["0"].target_only
            )

    def test_missing_off_source_does_not_replace_thermal_policy(self):
        h, s, p, m, plants = self.case(off_goal_entity="number.demo_display")
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual(d.mode, "heat")
        self.assertFalse(d.target_only)


class DisplayExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h, self.s, self.p, self.m, self.plants = fixture()
        self.h = replace(
            self.h,
            zones=(replace(self.h.zones[0], off_goal_entity="number.demo_display"),),
        )
        self.z = self.h.zones[0]
        self.s.zones["0"] = replace(
            self.s.zones["0"],
            temperature=Reading(22, NOW.timestamp()),
            off_goal=Reading(20, NOW.timestamp()),
        )
        self.store, self.calls = Store(), []
        self.x = Executor(
            self.h, self.store, self.fresh, self.emit, time.time, True, 0.02
        )
        await self.x.restore()

    async def asyncTearDown(self):
        await self.x.close()

    def fresh(self, _=None):
        return self.s, evaluate(self.h, self.s, self.p, self.m, self.plants)

    async def emit(self, zone, service, data, token):
        self.assertEqual(self.store.data["pending"][zone.id]["phase"], "sending")
        self.calls.append((service, data))
        old = self.s.zones[zone.id]
        new = replace(
            old,
            mode=data.get("hvac_mode", old.mode),
            setpoint=data.get("temperature", old.setpoint),
        )
        self.s.zones[zone.id] = new
        self.x.observe(zone.id, new.mode, new.setpoint, old.mode, old.setpoint)

    async def run_zone(self):
        return await self.x.execute(self.z, self.fresh()[1][self.z.id])

    async def test_off_display_emits_only_target_and_never_acquires_thermal_ownership(
        self,
    ):
        since = self.s.zones["0"].mode_since
        self.assertEqual(await self.run_zone(), "acked")
        self.assertEqual(self.calls, [("set_temperature", {"temperature": 20})])
        self.assertEqual(self.s.zones["0"].mode, "off")
        self.assertEqual(self.s.zones["0"].mode_since, since)
        self.assertNotIn("0", self.x.state["owned"])
        self.assertTrue(self.x.is_automatic("0"))
        self.assertEqual(await self.run_zone(), "already_satisfied")
        self.assertEqual(len(self.calls), 1)

    async def test_mode_change_during_persistence_revokes_display_intent(self):
        async def change():
            self.s.zones["0"] = replace(self.s.zones["0"], mode="heat")

        self.store.hook = change
        self.assertEqual(await self.run_zone(), "revoked")
        self.assertFalse(self.calls)

    async def test_goal_change_during_persistence_revokes_old_display(self):
        async def change():
            self.s.zones["0"] = replace(
                self.s.zones["0"], off_goal=Reading(21, NOW.timestamp())
            )

        self.store.hook = change
        self.assertEqual(await self.run_zone(), "revoked")
        self.assertFalse(self.calls)

    async def test_lost_ack_is_quarantined_without_mode_retry(self):
        async def no_echo(zone, service, data, token):
            self.calls.append((service, data))

        self.x.emit = no_echo
        self.assertEqual(await self.run_zone(), "unconfirmed")
        self.assertFalse(self.x.is_automatic("0"))
        await self.run_zone()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.s.zones["0"].mode, "off")

    async def test_explicit_person_identical_to_display_is_not_an_automatic_echo(self):
        await self.run_zone()
        self.x.observe("0", "off", 20, "off", 19.5, user=True)
        self.assertFalse(self.x.is_automatic("0"))

    async def test_feedback_protective_stop_works_without_thermal_feedback(self):
        self.h = replace(
            self.h,
            zones=(
                replace(
                    self.z, require_internal_feedback=True, feedback_loss_action="stop"
                ),
            ),
        )
        self.z = self.h.zones[0]
        self.x.house = self.h
        self.s.zones["0"] = replace(
            self.s.zones["0"], mode="heat", internal=Reading(None)
        )
        self.assertEqual(await self.run_zone(), "acked")
        self.assertEqual(self.calls, [("set_hvac_mode", {"hvac_mode": "off"})])
