"""Regression tests for the 0.2.0a14 coherence audit (synthetic homes only)."""

import asyncio
import datetime as D
import pathlib
import sys
import unittest
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "custom_components/climate_orchestrator"))
sys.path.append(str(ROOT / "tests"))
from domain.models import Memory, Reading
from domain.engine import evaluate, begin_dry, sleeping
from domain.demand import thermal_demand
from test_domain import fixture, NOW
import test_execution as TE

T0 = NOW.timestamp()


def local(day, hh, mm):
    base = D.datetime(2026, 11, 9) + D.timedelta(days=day)  # Monday
    return D.datetime(base.year, base.month, base.day, hh, mm, tzinfo=ZoneInfo("Europe/Madrid"))


class SleepBoundaryTests(unittest.TestCase):
    def sleeps(self, house, snap, when):
        return sleeping(house, replace(snap, now=when))

    def test_default_schedule_unchanged(self):
        house, snap, *_ = fixture()
        expected = {(3, 22, 30): True, (4, 22, 30): False, (4, 23, 30): True,
                    (5, 8, 30): True, (5, 9, 30): False, (6, 21, 30): False,
                    (6, 22, 30): True, (0, 6, 30): True, (0, 7, 30): False}
        for (day, h, m), value in expected.items():
            self.assertEqual(self.sleeps(house, snap, local(day, h, m)), value, (day, h, m))

    def test_post_midnight_night_belongs_to_its_evening(self):
        house, snap, *_ = fixture()
        house = replace(house, night_start="00:30", weekend_night_start="01:30")
        # Saturday night runs to 01:30 even though Sunday uses the weekday class.
        self.assertFalse(self.sleeps(house, snap, local(6, 0, 45)))
        self.assertTrue(self.sleeps(house, snap, local(6, 1, 45)))
        # Thursday night (weekday start 00:30) is already asleep at 01:00 Friday.
        self.assertTrue(self.sleeps(house, snap, local(4, 1, 0)))
        self.assertFalse(self.sleeps(house, snap, local(4, 0, 15)))


class StuckSessionTests(unittest.TestCase):
    def test_session_ends_when_unit_leaves_dry_without_manual(self):
        for mode, temp in (("heat", 20), ("cool", 25)):
            house, snap, prices, mem, pl = fixture()
            mem["0"] = Memory()
            begin_dry(mem["0"], T0 - 300, 17, 60, 0)
            o = snap.zones["0"]
            s = replace(snap, zones={"0": replace(o, mode=mode, mode_since=T0 - 200,
                                                   temperature=Reading(temp, T0),
                                                   humidity=Reading(80, T0))})
            result = evaluate(house, s, prices, mem, pl)["0"]
            self.assertFalse(mem["0"].dry_active, mode)
            self.assertNotEqual(result.reason, "dry_ack_pending", mode)

    def test_ack_window_still_waits(self):
        house, snap, prices, mem, pl = fixture()
        mem["0"] = Memory()
        begin_dry(mem["0"], T0 - 10, 17, 60, 0)
        o = snap.zones["0"]
        s = replace(snap, zones={"0": replace(o, mode="heat", mode_since=T0 - 200,
                                               temperature=Reading(20, T0))})
        self.assertEqual(evaluate(house, s, prices, mem, pl)["0"].reason, "dry_ack_pending")


class NightPolicyTests(unittest.TestCase):
    def test_excluded_zone_is_stopped_not_left_running(self):
        house, snap, prices, mem, pl = fixture()
        house = replace(house, zones=(replace(house.zones[0], night_allowed=False),))
        when = local(1, 23, 30)
        t = when.timestamp()
        o = snap.zones["0"]
        for mode, temp in (("heat", 25), ("cool", 15)):
            s = replace(snap, now=when, outdoor=Reading(13, t), power=Reading(100, t),
                        zones={"0": replace(o, mode=mode, mode_since=t - 4000,
                                            temperature=Reading(temp, t),
                                            humidity=Reading(50, t), internal=Reading(temp, t))})
            r = evaluate(house, s, prices, {}, {})["0"]
            self.assertEqual((r.reason, r.mode), ("night_not_allowed", "off"), mode)

    def test_pause_and_off_unit_stay_untouched(self):
        house, snap, prices, mem, pl = fixture()
        house = replace(house, zones=(replace(house.zones[0], night_allowed=False),))
        when = local(1, 23, 30)
        t = when.timestamp()
        o = snap.zones["0"]
        s = replace(snap, now=when, paused=True,
                    zones={"0": replace(o, mode="heat", mode_since=t - 4000,
                                        temperature=Reading(25, t), humidity=Reading(50, t))})
        self.assertIsNone(evaluate(house, s, prices, {}, {})["0"].mode)
        s = replace(snap, now=when, zones={"0": replace(o, mode="off", temperature=Reading(25, t))})
        self.assertIsNone(evaluate(house, s, prices, {}, {})["0"].mode)


class UncertainRowTests(TE.ExecutionTests):
    async def test_resume_reopens_command_path(self):
        async def silent(zone, service, data, token):
            self.calls.append((service, data))
        self.executor.emit = silent
        self.assertEqual(await self.run_zone(), "unconfirmed")
        await self.executor.resume(self.zone.id)
        self.executor.emit = self.emit
        self.assertEqual(await self.run_zone(), "acked")

    async def test_expired_uncertain_row_does_not_veto_forever(self):
        async def silent(zone, service, data, token):
            pass
        self.executor.emit = silent
        await self.run_zone()
        self.executor.state["manual"].pop(self.zone.id)
        self.executor.state["pending"][self.zone.id]["expires"] = 0
        self.executor.emit = self.emit
        self.assertEqual(await self.run_zone(), "acked")

    async def test_in_flight_uncertain_row_still_blocks(self):
        async def silent(zone, service, data, token):
            pass
        self.executor.emit = silent
        await self.run_zone()
        self.executor.state["manual"].pop(self.zone.id)
        self.executor.emit = self.emit
        self.assertEqual(await self.run_zone(), "unconfirmed_previous")

    async def test_stale_dry_ownership_can_be_released(self):
        self.executor.state["owned"][self.zone.id] = {
            "id": "x", "binding": self.zone.actuator_entity, "mode": "dry"}
        await self.executor.release_owned(self.zone)
        self.assertNotIn(self.zone.id, self.executor.state["owned"])


class DemandPostureTests(unittest.TestCase):
    def posture(self, mode, temp, **policy):
        house, snap, prices, mem, pl = fixture(**policy)
        o = snap.zones["0"]
        s = replace(snap, zones={"0": replace(o, mode=mode, mode_since=T0 - 4000,
                                               temperature=Reading(temp, T0),
                                               internal=Reading(temp, T0))})
        d = evaluate(house, s, prices, mem, pl)["0"]
        return thermal_demand(house, d, s.zones["0"], T0), d

    def test_cold_room_running_is_demand(self):
        p, _ = self.posture("heat", 16)
        self.assertEqual((p["state"], p["level"]), ("demand", 2))

    def test_room_at_goal_running_is_maintain(self):
        p, d = self.posture("heat", 19.6)
        self.assertEqual(p["state"], "maintain")
        self.assertEqual(p["level"], 1)

    def test_off_unit_is_off(self):
        p, _ = self.posture("off", 21)
        self.assertEqual((p["state"], p["level"]), ("off", 0))

    def test_planned_start_is_demand(self):
        p, d = self.posture("off", 16)
        self.assertEqual(d.mode, "heat")
        self.assertEqual(p["state"], "demand")


if __name__ == "__main__":
    unittest.main()
