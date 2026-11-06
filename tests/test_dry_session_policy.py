"""Optional configuration floor and owned-session pause semantics, synthetic only."""

from dataclasses import asdict, replace
import unittest
from test_domain import fixture, NOW
from domain.models import Memory, Reading, house_from_dict
from domain.engine import evaluate, begin_dry


class DrySessionPolicyTests(unittest.TestCase):
    def case(self, binding=True):
        h, s, p, m, plants = fixture()
        h = replace(
            h,
            zones=(
                replace(
                    h.zones[0],
                    dry_floor_entity="number.demo_floor" if binding else None,
                ),
            ),
        )
        s.zones["0"] = replace(
            s.zones["0"],
            temperature=Reading(22.5, NOW.timestamp()),
            heat_goal=Reading(21, NOW.timestamp()),
            cool_goal=Reading(27, NOW.timestamp()),
            dry_floor=Reading(23, NOW.timestamp()),
        )
        m["0"] = Memory(high_since=NOW.timestamp() - 1800)
        return h, s, p, m, plants

    def test_external_floor_blocks_warm_start_without_changing_default(self):
        for binding, wanted in [(True, None), (False, "dry")]:
            h, s, p, m, plants = self.case(binding)
            d = evaluate(h, s, p, m, plants)["0"]
            self.assertEqual(d.mode, wanted)
            if wanted:
                self.assertEqual(d.session_floor, 20)
            else:
                self.assertEqual(d.reason, "insufficient_thermal_margin")

    def test_ready_freezes_the_selected_configuration_floor(self):
        h, s, p, m, plants = self.case()
        s.zones["0"] = replace(s.zones["0"], temperature=Reading(24.1, NOW.timestamp()))
        d = evaluate(h, s, p, m, plants)["0"]
        self.assertEqual((d.mode, d.session_floor), ("dry", 23))
        begin_dry(
            m["0"],
            NOW.timestamp(),
            d.session_floor,
            d.humidity_stop,
            h.policy.dry_max_s,
        )
        self.assertEqual(Memory(**asdict(m["0"])).dry_floor, 23)
        s.zones["0"] = replace(
            s.zones["0"],
            mode="dry",
            dry_floor=Reading(None),
            temperature=Reading(22.9, NOW.timestamp()),
        )
        self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, "off")
        self.assertEqual(m["0"].dry_floor, 23)

    def test_invalid_or_missing_bound_floor_has_no_fallback_start(self):
        for value, at in [
            (None, 0),
            (9, NOW.timestamp()),
            (31, NOW.timestamp()),
            (23, NOW.timestamp() - 7201),
        ]:
            h, s, p, m, plants = self.case()
            s.zones["0"] = replace(s.zones["0"], dry_floor=Reading(value, at))
            d = evaluate(h, s, p, m, plants)["0"]
            self.assertEqual((d.mode, d.reason), (None, "dry_floor_missing"))

    def owned(self, action="retain_owned"):
        h, s, p, m, plants = self.case()
        h = replace(h, zones=(replace(h.zones[0], dry_pause_action=action),))
        s = replace(s, paused=True)
        s.zones["0"] = replace(
            s.zones["0"], mode="dry", temperature=Reading(24, NOW.timestamp())
        )
        m["0"] = Memory(
            high_since=NOW.timestamp() - 1800,
            dry_start=NOW.timestamp() - 1300,
            dry_until=NOW.timestamp() + 500,
            dry_floor=23,
            dry_target=60,
        )
        return h, s, p, m, plants

    def test_default_pause_still_stops_owned_dry(self):
        h, s, p, m, plants = self.owned("stop")
        self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, "off")

    def test_opt_in_pause_retains_only_an_existing_session(self):
        h, s, p, m, plants = self.owned()
        until = m["0"].dry_until
        self.assertEqual(evaluate(h, s, p, m, plants)["0"].mode, "dry")
        self.assertEqual(m["0"].dry_until, until)
        m.clear()
        s.zones["0"] = replace(s.zones["0"], mode="off")
        self.assertNotEqual(evaluate(h, s, p, m, plants)["0"].mode, "dry")

    def test_pause_never_hides_max_floor_data_permission_or_manual(self):
        for case in [
            "maximum",
            "floor",
            "temperature",
            "humidity",
            "permission",
            "dry_permission",
            "disabled",
            "manual",
        ]:
            h, s, p, m, plants = self.owned()
            o = s.zones["0"]
            if case == "maximum":
                m["0"].dry_until = NOW.timestamp() - 1
            if case == "floor":
                o = replace(o, temperature=Reading(22.9, NOW.timestamp()))
            if case == "temperature":
                o = replace(o, temperature=Reading(None))
            if case == "humidity":
                o = replace(o, humidity=Reading(None))
            if case == "permission":
                o = replace(o, permitted=False)
            if case == "dry_permission":
                o = replace(o, dry_allowed=False)
            if case == "disabled":
                h = replace(h, zones=(replace(h.zones[0], enabled=False),))
            if case == "manual":
                o = replace(o, automatic=False)
            s.zones["0"] = o
            d = evaluate(h, s, p, m, plants)["0"]
            self.assertEqual(d.mode, None if case == "manual" else "off", case)

    def test_pause_action_is_validated_and_roundtrips(self):
        h, *_ = self.case()
        with self.assertRaises(ValueError):
            replace(h.zones[0], dry_pause_action="ignore_limits")
        h = replace(h, zones=(replace(h.zones[0], dry_pause_action="retain_owned"),))
        self.assertEqual(house_from_dict(asdict(h)), h)


class DryFloorExecutionFenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_floor_after_reservation_cancels_send_but_keeps_attempt(self):
        from test_execution import Store
        from execution import Executor

        h, s, p, m, plants = DrySessionPolicyTests().case()
        s.zones["0"] = replace(s.zones["0"], temperature=Reading(24.1, NOW.timestamp()))
        calls = []

        def fresh(_=None):
            return s, evaluate(h, s, p, m, plants)

        async def emit(*args):
            calls.append(args)

        async def accept(zone, decision):
            begin_dry(
                m[zone.id],
                NOW.timestamp(),
                decision.session_floor,
                decision.humidity_stop,
                h.policy.dry_max_s,
            )
            s.zones[zone.id] = replace(
                s.zones[zone.id], dry_floor=Reading(24, NOW.timestamp())
            )

        executor = Executor(
            h, Store(), fresh, emit, lambda: NOW.timestamp(), True, 0.01
        )
        try:
            await executor.restore()
            decision = fresh()[1]["0"]
            self.assertEqual((decision.mode, decision.session_floor), ("dry", 23))
            self.assertEqual(
                await executor.execute(h.zones[0], decision, accept), "revoked"
            )
            self.assertEqual(calls, [])
            self.assertEqual((m["0"].attempts, m["0"].dry_floor), (1, 23))
            self.assertEqual(executor.state["pending"]["0"]["phase"], "cancelled")
        finally:
            await executor.close()
