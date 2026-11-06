"""A mode veto and an off-only protective exit have different semantics."""

from dataclasses import replace
import time
import unittest

from test_domain import fixture, NOW
from test_execution import Store
from domain.models import Reading
from domain.engine import evaluate
from execution import Executor


class ModePermissionLossTests(unittest.TestCase):
    def case(self, mode="heat", action="stop"):
        h, s, p, m, plants = fixture(2, continuous_hold=True, overshoot_delta=2)
        h = replace(
            h,
            zones=(replace(h.zones[0], mode_permission_loss_action=action), h.zones[1]),
        )
        s.zones["0"] = replace(
            s.zones["0"],
            mode=mode,
            temperature=Reading(18 if mode == "heat" else 28, NOW.timestamp()),
            heat_allowed=False,
            cool_allowed=False,
        )
        return h, s, p, m, plants

    def test_existing_profiles_keep_hold_as_default(self):
        h, s, p, m, plants = self.case(action="hold")
        self.assertEqual(h.zones[1].mode_permission_loss_action, "hold")
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual((d.mode, d.reason), (None, "external_mode_permission"))

    def test_selected_running_heat_and_cool_emit_only_off(self):
        for mode in ["heat", "cool"]:
            with self.subTest(mode=mode):
                h, s, p, m, plants = self.case(mode)
                d = evaluate(h, s, p, m, plants)["0"]
                self.assertEqual(
                    (d.stage, d.reason, d.mode),
                    ("protect", "mode_permission_lost", "off"),
                )
                self.assertIsNone(d.physical_target)

    def test_lost_goals_or_feedback_do_not_prevent_the_requested_exit(self):
        for change in [
            {"temperature": Reading(None)},
            {"goals_valid": False},
            {"internal": Reading(None)},
        ]:
            with self.subTest(change=change):
                h, s, p, m, plants = self.case()
                s.zones["0"] = replace(s.zones["0"], **change)
                self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, "off")

    def test_manual_pause_and_room_permission_never_gain_authority(self):
        for change, paused in [
            ({"automatic": False}, False),
            ({"permitted": False}, False),
            ({}, True),
        ]:
            with self.subTest(change=change, paused=paused):
                h, s, p, m, plants = self.case()
                s.zones["0"] = replace(s.zones["0"], **change)
                self.assertNotEqual(
                    evaluate(h, replace(s, paused=paused), p, m, plants)["0"].mode,
                    "off",
                )

    def test_no_stop_of_off_unknown_fan_or_unowned_dry(self):
        for mode in ["off", "unknown", "unavailable", "fan_only", "dry"]:
            with self.subTest(mode=mode):
                h, s, p, m, plants = self.case(mode)
                self.assertNotEqual(
                    evaluate(h, s, p, m, plants)["0"].reason, "mode_permission_lost"
                )

    def test_a_different_mode_veto_does_not_revoke_current_cooling(self):
        h, s, p, m, plants = self.case("cool")
        s.zones["0"] = replace(s.zones["0"], cool_allowed=True)
        self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, "cool")

    def test_missing_off_capability_is_not_fabricated(self):
        h, s, p, m, plants = self.case()
        s.zones["0"] = replace(s.zones["0"], supported_modes=("heat", "cool"))
        self.assertIsNone(evaluate(h, s, p, m, plants)["0"].mode)

    def test_one_failed_zone_does_not_reserve_the_whole_shared_plant(self):
        h, s, p, m, plants = self.case()
        result = evaluate(h, s, p, m, plants)
        self.assertEqual(result["0"].mode, "off")
        self.assertEqual(result["1"].mode, "heat")

    def test_default_mode_veto_does_not_hide_protective_overshoot(self):
        for mode, temp in [("heat", 26), ("cool", 20)]:
            with self.subTest(mode=mode):
                h, s, p, m, plants = self.case(mode, "hold")
                s.zones["0"] = replace(
                    s.zones["0"], temperature=Reading(temp, NOW.timestamp())
                )
                d = evaluate(h, s, p, m, plants)["0"]
                self.assertEqual((d.mode, d.reason), ("off", "temperature_overshoot"))

    def test_invalid_policy_and_dryer_binding_are_rejected(self):
        h, *_ = fixture()
        for value in [True, None, "off", "shutdown"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(h.zones[0], mode_permission_loss_action=value)
        with self.assertRaises(ValueError):
            replace(
                h.zones[0],
                climate_entity=None,
                humidifier_entity="humidifier.demo",
                mode_permission_loss_action="stop",
            )


class ModePermissionExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h, self.s, self.p, self.m, self.plants = fixture(
            continuous_hold=True, overshoot_delta=2
        )
        self.h = replace(
            self.h,
            zones=(replace(self.h.zones[0], mode_permission_loss_action="stop"),),
        )
        self.z = self.h.zones[0]
        self.s.zones["0"] = replace(self.s.zones["0"], mode="heat", heat_allowed=False)
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
        new = replace(old, mode=data.get("hvac_mode", old.mode))
        self.s.zones[zone.id] = new
        self.x.observe(zone.id, new.mode, new.setpoint, old.mode, old.setpoint)

    async def execute(self):
        return await self.x.execute(self.z, self.fresh()[1][self.z.id])

    async def test_real_executor_journals_and_acknowledges_only_off(self):
        self.assertEqual(await self.execute(), "acked")
        self.assertEqual(self.calls, [("set_hvac_mode", {"hvac_mode": "off"})])
        self.assertTrue(self.x.is_automatic("0"))

    async def test_permission_recovery_during_persistence_revokes_old_stop(self):
        async def recover():
            self.s.zones["0"] = replace(self.s.zones["0"], heat_allowed=True)

        self.store.hook = recover
        self.assertEqual(await self.execute(), "revoked")
        self.assertFalse(self.calls)

    async def test_new_manual_during_persistence_revokes_old_stop(self):
        async def manual():
            self.s.zones["0"] = replace(self.s.zones["0"], automatic=False)

        self.store.hook = manual
        self.assertEqual(await self.execute(), "revoked")
        self.assertFalse(self.calls)


class ThermalOccupancyTests(unittest.TestCase):
    def test_unconfigured_profiles_inherit_the_household_presence(self):
        h, s, p, m, plants = fixture()
        self.assertEqual(
            evaluate(h, replace(s, occupied=False), p, m, plants)["0"].reason,
            "occupancy_unconfirmed",
        )
        self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, "heat")

    def test_explicit_thermal_occupancy_can_serve_only_one_returning_zone(self):
        h, s, p, m, plants = fixture(2)
        s.zones["0"] = replace(s.zones["0"], thermal_occupied=True)
        result = evaluate(h, replace(s, occupied=False), p, m, plants)
        self.assertEqual(result["0"].mode, "heat")
        self.assertEqual(result["1"].reason, "occupancy_unconfirmed")

    def test_explicit_denial_does_not_fall_back_to_household_presence(self):
        h, s, p, m, plants = fixture()
        s.zones["0"] = replace(s.zones["0"], thermal_occupied=False)
        self.assertEqual(
            evaluate(h, s, p, m, plants)["0"].reason, "occupancy_unconfirmed"
        )

    def test_thermal_return_never_authorizes_drying_in_an_empty_house(self):
        h, s, p, m, plants = fixture()
        s.zones["0"] = replace(
            s.zones["0"],
            temperature=Reading(24, NOW.timestamp()),
            thermal_occupied=True,
        )
        self.assertNotEqual(
            evaluate(h, replace(s, occupied=False), p, m, plants)["0"].mode, "dry"
        )

    def test_thermal_return_does_not_acquire_manual_authority(self):
        h, s, p, m, plants = fixture()
        s.zones["0"] = replace(s.zones["0"], thermal_occupied=True, automatic=False)
        self.assertNotEqual(
            evaluate(h, replace(s, occupied=False), p, m, plants)["0"].mode, "heat"
        )

    def test_occupancy_is_not_truthiness_and_dryers_cannot_bind_thermal_presence(self):
        h, s, *_ = fixture()
        for value in [1, "on", [], {}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(s.zones["0"], thermal_occupied=value)
        with self.assertRaises(ValueError):
            replace(
                h.zones[0],
                climate_entity=None,
                humidifier_entity="humidifier.demo",
                thermal_presence_entity="binary_sensor.demo_return",
            )
