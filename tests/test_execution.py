"""Adversarial execution protocol tests: synthetic states and a fake emitter."""

import asyncio
import copy
from dataclasses import replace
import pathlib
import sys
import time
import unittest

sys.path.insert(
    0,
    str(
        pathlib.Path(__file__).resolve().parents[1]
        / "custom_components/climate_orchestrator"
    ),
)
from execution import Executor
from test_domain import fixture
from domain.engine import evaluate


class Store:
    def __init__(self):
        self.data = None
        self.saves = []
        self.hook = None

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)
        self.saves.append(self.data)
        if self.hook:
            hook, self.hook = self.hook, None
            await hook()


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.house, self.snap, self.prices, self.memory, self.plants = fixture(2)
        self.store, self.calls = Store(), []
        self.executor = Executor(
            self.house, self.store, self.fresh, self.emit, time.time, True, 0.05
        )
        await self.executor.restore()
        self.zone = self.house.zones[0]

    async def asyncTearDown(self):
        await self.executor.close()

    def fresh(self, _=None):
        return self.snap, evaluate(
            self.house, self.snap, self.prices, self.memory, self.plants
        )

    async def emit(self, zone, service, data, token):
        assert self.store.data["pending"][zone.id]["phase"] == "sending"
        self.calls.append((zone.id, service, data, token))
        old = self.snap.zones[zone.id]
        new = replace(
            old,
            mode=data.get("hvac_mode", old.mode),
            setpoint=data.get("temperature", old.setpoint),
        )
        self.snap.zones[zone.id] = new
        self.executor.observe(zone.id, new.mode, new.setpoint, old.mode, old.setpoint)

    async def run_zone(self):
        return await self.executor.execute(self.zone, self.fresh()[1][self.zone.id])

    async def test_target_is_persisted_and_acked_before_mode(self):
        self.assertEqual(await self.run_zone(), "acked")
        self.assertEqual(
            [c[1] for c in self.calls], ["set_temperature", "set_hvac_mode"]
        )
        self.assertEqual(self.store.data["pending"][self.zone.id]["phase"], "acked")
        self.assertTrue(self.executor.is_automatic(self.zone.id))

    async def test_shadow_has_zero_emission(self):
        self.executor.enabled = False
        self.assertEqual(await self.run_zone(), "revoked")
        self.assertFalse(self.calls)

    async def test_pause_while_waiting_for_plant_revokes_certificate(self):
        lock = self.executor.locks[self.zone.plant]
        await lock.acquire()
        task = asyncio.create_task(self.run_zone())
        await asyncio.sleep(0)
        self.executor.invalidate()
        lock.release()
        self.assertEqual(await task, "revoked")
        self.assertFalse(self.calls)

    async def test_authority_race_during_intent_persistence(self):
        async def pause():
            self.executor.invalidate()

        self.store.hook = pause
        self.assertEqual(await self.run_zone(), "revoked")
        self.assertFalse(self.calls)

    async def test_authority_race_during_budget_persistence(self):
        async def accepted(zone, decision):
            self.executor.invalidate()

        result = await self.executor.execute(
            self.zone, self.fresh()[1][self.zone.id], accepted
        )
        self.assertEqual(result, "revoked")
        self.assertFalse(self.calls)

    async def test_timeout_latches_manual_and_is_not_retried(self):
        async def no_echo(zone, service, data, token):
            self.calls.append(service)

        self.executor.emit = no_echo
        self.assertEqual(await self.run_zone(), "unconfirmed")
        self.assertFalse(self.executor.is_automatic(self.zone.id))
        before = len(self.calls)
        await self.run_zone()
        self.assertEqual(len(self.calls), before)

    async def test_pause_between_target_ack_and_start_prevents_start(self):
        async def emit_pause(zone, service, data, token):
            await self.emit(zone, service, data, token)
            self.snap = replace(self.snap, paused=True)
            self.executor.invalidate()

        self.executor.emit = emit_pause
        self.assertEqual(await self.run_zone(), "revoked_after_send")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.snap.zones[self.zone.id].mode, "off")

    async def test_explicit_user_exact_echo_is_not_ack(self):
        await self.run_zone()
        o = self.snap.zones[self.zone.id]
        self.executor.observe(
            self.zone.id, o.mode, o.setpoint, o.mode, o.setpoint, True
        )
        self.assertFalse(self.executor.is_automatic(self.zone.id))

    async def test_old_echo_does_not_clear_new_manual(self):
        await self.run_zone()
        row = self.executor.state["pending"][self.zone.id]
        self.executor.manual(self.zone.id)
        echo = row["expected"][0]
        self.executor.observe(self.zone.id, echo["mode"], echo["target"], "heat", 16)
        self.assertFalse(self.executor.is_automatic(self.zone.id))

    async def test_old_echo_lease_not_extended_by_new_command(self):
        await self.run_zone()
        row = self.executor.state["pending"][self.zone.id]
        row["expected"][0]["until"] = time.time() - 1
        echo = row["expected"][0]
        self.executor.observe(self.zone.id, echo["mode"], echo["target"], "heat", 16)
        self.assertFalse(self.executor.is_automatic(self.zone.id))

    async def test_restart_never_replays_ambiguous_start(self):
        row = {
            "binding": self.zone.climate_entity,
            "phase": "sending",
            "expected": [],
            "expires": time.time() + 30,
        }
        self.executor.state["pending"][self.zone.id] = row
        await self.executor.save()
        other = Executor(self.house, self.store, self.fresh, self.emit, time.time, True)
        await other.restore()
        self.assertEqual(other.state["manual"][self.zone.id], "restart_unconfirmed")
        await other.execute(self.zone, self.fresh()[1][self.zone.id])
        self.assertFalse(self.calls)
        await other.close()

    async def test_corrupt_journal_stops_control(self):
        self.store.data = {"generation": 1}
        with self.assertRaises(ValueError):
            await self.executor.restore()
        self.assertFalse(self.calls)

    async def test_critical_off_bypasses_blocked_plant_and_manual(self):
        lock = self.executor.locks[self.zone.plant]
        await lock.acquire()
        self.snap.zones[self.zone.id] = replace(
            self.snap.zones[self.zone.id], mode="heat"
        )
        self.executor.manual(self.zone.id)
        await self.executor.critical(True)
        await asyncio.gather(*list(self.executor.off_tasks.values()))
        self.assertEqual(self.snap.zones[self.zone.id].mode, "off")
        self.assertTrue(self.store.data["critical"])
        lock.release()

    async def test_release_does_not_refresh_old_certificate(self):
        lock = self.executor.locks[self.zone.plant]
        await lock.acquire()
        task = asyncio.create_task(self.run_zone())
        await asyncio.sleep(0)
        await self.executor.critical(True)
        await self.executor.critical(False)
        lock.release()
        self.assertEqual(await task, "revoked")
        self.assertFalse(self.calls)

    async def test_late_energizing_echo_after_cut_is_reconciled_off(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(zone, service, data, token):
            if data.get("hvac_mode") == "heat":
                started.set()
                await release.wait()
            await self.emit(zone, service, data, token)

        self.executor.emit = delayed
        task = asyncio.create_task(self.run_zone())
        await started.wait()
        await self.executor.critical(True)
        release.set()
        self.assertEqual(await task, "revoked_after_send")
        self.assertEqual(self.snap.zones[self.zone.id].mode, "off")

    async def test_unknown_recovery_is_not_human_manual(self):
        self.executor.observe(self.zone.id, "unavailable", None, "off", 19.5)
        self.executor.observe(self.zone.id, "off", 19.5, "unavailable", None)
        self.assertTrue(self.executor.is_automatic(self.zone.id))

    async def test_critical_release_during_persistence_cancels_stale_off(self):
        self.snap.zones[self.zone.id] = replace(
            self.snap.zones[self.zone.id], mode="heat"
        )
        self.executor.state["critical"] = True

        async def release():
            self.executor.state["critical"] = False
            self.executor.invalidate()

        self.store.hook = release
        await self.executor._off(self.zone)
        self.assertFalse(self.calls)

    async def test_owned_expiry_has_independent_lane_but_cannot_stop_new_manual(self):
        self.snap.zones[self.zone.id] = replace(
            self.snap.zones[self.zone.id], mode="dry"
        )
        self.executor.state["owned"][self.zone.id] = {
            "id": "owned-session",
            "mode": "dry",
            "binding": self.zone.climate_entity,
        }
        self.executor.manual(self.zone.id, "unconfirmed_command")
        lock = self.executor.locks[self.zone.plant]
        await lock.acquire()
        await self.executor.stop_owned(self.zone)
        await asyncio.gather(*list(self.executor.off_tasks.values()))
        lock.release()
        self.assertEqual(self.snap.zones[self.zone.id].mode, "off")
        self.assertNotIn(self.zone.id, self.executor.state["owned"])
        self.executor.state["owned"][self.zone.id] = {
            "id": "old",
            "mode": "dry",
            "binding": self.zone.climate_entity,
        }
        self.executor.manual(self.zone.id)
        before = len(self.calls)
        await self.executor._off(self.zone, "old")
        self.assertEqual(len(self.calls), before)

    async def test_invalid_store_is_not_overwritten_on_failed_setup_close(self):
        self.store.data = {"corrupt": True}
        with self.assertRaises(ValueError):
            await self.executor.restore()
        await self.executor.close()
        self.assertEqual(self.store.data, {"corrupt": True})

    async def test_persistent_manual_can_be_explicitly_rearmed(self):
        self.executor.manual(self.zone.id)
        await self.executor.save()
        await self.executor.resume(self.zone.id)
        self.assertEqual(await self.run_zone(), "acked")

    async def test_owned_dry_deadline_can_stop_during_global_pause(self):
        decision = replace(
            self.fresh()[1][self.zone.id],
            mode="off",
            stage="dry_stop",
            physical_target=None,
        )
        self.snap.zones[self.zone.id] = replace(
            self.snap.zones[self.zone.id], mode="dry"
        )
        self.snap = replace(self.snap, paused=True)
        self.executor.state["owned"][self.zone.id] = {
            "mode": "dry",
            "binding": self.zone.climate_entity,
        }
        self.executor.fresh = lambda _: (self.snap, {self.zone.id: decision})
        self.assertEqual(await self.executor.execute(self.zone, decision), "acked")
        self.assertEqual(self.calls[0][2], {"hvac_mode": "off"})


if __name__ == "__main__":
    unittest.main()
