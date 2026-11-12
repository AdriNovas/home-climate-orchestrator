"""Opt-in concurrent admissions; synthetic inputs and no actuator calls."""

from dataclasses import asdict, replace
from datetime import timedelta
import unittest

from test_domain import fixture, NOW
from test_humidity_strategy import dryer_fixture
from domain.engine import evaluate, begin_dry
from domain.models import Memory, Reading, house_from_dict


class DryAdmissionTests(unittest.TestCase):
    def case(self, concurrent=True, budget=False):
        h, s, prices, m, pm = fixture(5)
        h = replace(h, policy=replace(h.policy, dry_concurrent=concurrent,
                                     dry_budget_enabled=budget))
        for key, rh in zip(s.zones, [80, 77, 75, 74, 70]):
            s.zones[key] = replace(s.zones[key], temperature=Reading(23, NOW.timestamp()),
                                   humidity=Reading(rh, NOW.timestamp()))
            m[key] = Memory(high_since=NOW.timestamp() - 1800)
        return h, s, prices, m, pm

    def dry_ids(self, result):
        return {k for k, d in result.items() if d.mode == 'dry'}

    def test_legacy_keeps_single_admission(self):
        self.assertEqual(self.dry_ids(evaluate(*self.case(concurrent=False))), {'0'})

    def test_band_includes_boundary_and_excludes_lower_humidity(self):
        h, s, prices, m, pm = self.case()
        d = evaluate(h, s, prices, m, pm)
        self.assertEqual(self.dry_ids(d), {'0', '1', '2'})
        self.assertEqual(d['3'].reason, 'dry_humidity_band')
        self.assertEqual(d['4'].reason, 'dry_humidity_band')
        h = replace(h, policy=replace(h.policy, dry_humidity_band=0))
        self.assertEqual(self.dry_ids(evaluate(h, s, prices, m, pm)), {'0'})

    def test_existing_owner_sets_band_without_restarting_or_being_stopped(self):
        h, s, prices, m, pm = self.case()
        begin_dry(m['0'], NOW.timestamp()-1800, 20, 60, 0)
        s.zones['0'] = replace(s.zones['0'], mode='dry')
        before = (m['0'].dry_start, m['0'].dry_until, m['0'].attempts)
        self.assertEqual(self.dry_ids(evaluate(h, s, prices, m, pm)), {'0', '1', '2'})
        self.assertEqual((m['0'].dry_start, m['0'].dry_until, m['0'].attempts), before)
        # New high demand can join, but does not terminate an existing lower owner.
        s.zones['1'] = replace(s.zones['1'], humidity=Reading(90, NOW.timestamp()))
        d = evaluate(h, s, prices, m, pm)
        self.assertEqual(self.dry_ids(d), {'0', '1'})
        self.assertEqual(d['0'].stage, 'drying')

    def test_stale_manual_and_revoked_heads_cannot_set_reference(self):
        for kwargs in [dict(automatic=False), dict(dry_allowed=False),
                       dict(humidity=Reading(99, NOW.timestamp()-7201))]:
            h, s, prices, m, pm = self.case()
            s.zones['0'] = replace(s.zones['0'], **kwargs)
            d = evaluate(h, s, prices, m, pm)
            self.assertEqual(self.dry_ids(d), {'1', '2', '3'})

    def test_withdrawn_permission_is_rechecked_before_new_admission(self):
        h, s, prices, m, pm = self.case()
        self.assertEqual(self.dry_ids(evaluate(h, s, prices, m, pm)), {'0', '1', '2'})
        for k in ['0', '1', '2']:
            s.zones[k] = replace(s.zones[k], dry_allowed=False)
        self.assertEqual(self.dry_ids(evaluate(h, s, prices, m, pm)), {'3', '4'})

    def test_unlimited_budget_keeps_history_across_day_and_restore(self):
        h, s, prices, m, pm = self.case()
        for key in m:
            m[key].last_attempt = NOW.timestamp()-1
            m[key].attempts = 100
            m[key].day = (NOW-timedelta(days=1)).date().isoformat()
            m[key].debt_since = NOW.timestamp()-15000
            m[key] = Memory(**asdict(m[key]))
        self.assertEqual(self.dry_ids(evaluate(h, s, prices, m, pm)), {'0', '1', '2'})
        self.assertEqual(m['0'].attempts, 100)
        self.assertEqual(m['0'].last_attempt, NOW.timestamp()-1)
        self.assertEqual(m['0'].debt_since, NOW.timestamp()-15000)
        # Re-enabling legacy budgeting uses preserved history, not a fresh allowance.
        h = replace(h, policy=replace(h.policy, dry_budget_enabled=True))
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].reason, 'dry_budget')

    def test_budget_disabled_preserves_real_off_and_plant_conflict_guards(self):
        h, s, prices, m, pm = self.case()
        s.zones['0'] = replace(s.zones['0'], mode_since=NOW.timestamp()-1)
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].reason, 'minimum_off')
        self.assertEqual(self.dry_ids(evaluate(h, s, prices, m, pm)), {'1', '2', '3'})
        s.zones['0'] = replace(s.zones['0'], mode='heat', automatic=False)
        self.assertFalse(self.dry_ids(evaluate(h, s, prices, m, pm)))

    def test_independent_dryer_bypasses_service_cooldown_not_failure_latch(self):
        h, s, prices, m, pm = dryer_fixture()
        h = replace(h, policy=replace(h.policy, dry_budget_enabled=False))
        m['dryer'].last_attempt = NOW.timestamp()-1
        self.assertEqual(evaluate(h, s, prices, m, pm)['dryer'].mode, 'dry')
        m['dryer'].dry_episode_blocked = True
        self.assertEqual(evaluate(h, s, prices, m, pm)['dryer'].reason,
                         'dry_episode_recovery_required')
        h = replace(h, policy=replace(h.policy, dry_budget_enabled=True))
        m['dryer'].dry_episode_blocked = False
        self.assertEqual(evaluate(h, s, prices, m, pm)['dryer'].reason, 'minimum_off')

    def test_policies_roundtrip_defaults_and_invalid_inputs(self):
        h, *_ = self.case()
        self.assertEqual(house_from_dict(asdict(h)), h)
        legacy, *_ = fixture()
        self.assertFalse(legacy.policy.dry_concurrent)
        self.assertTrue(legacy.policy.dry_budget_enabled)
        for field in ['dry_concurrent', 'dry_budget_enabled']:
            with self.assertRaises(ValueError):
                replace(h.policy, **{field: 1})
        for value in [True, -1, 101, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                replace(h.policy, dry_humidity_band=value)


class ConcurrentExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_plant_emits_serially_and_revokes_waiting_permission(self):
        import asyncio
        from execution import Executor
        from test_execution import Store
        h, s, prices, m, pm = DryAdmissionTests().case()
        calls, concurrent = [], []

        def fresh(_=None):
            return s, evaluate(h, s, prices, m, pm)

        async def accepted(zone, decision):
            begin_dry(m[zone.id], NOW.timestamp(), decision.session_floor,
                      decision.humidity_stop, 0)

        async def emit(zone, service, data, token):
            concurrent.append(executor.inflight)
            await asyncio.sleep(0)
            old = s.zones[zone.id]
            new = replace(old, mode=data.get('hvac_mode', old.mode),
                          setpoint=data.get('temperature', old.setpoint))
            s.zones[zone.id] = new
            calls.append(zone.id)
            executor.observe(zone.id, new.mode, new.setpoint, old.mode, old.setpoint)
            # A queued request must not inherit authority when a permission changes.
            if zone.id == '0':
                s.zones['2'] = replace(s.zones['2'], dry_allowed=False)

        executor = Executor(h, Store(), fresh, emit, lambda: NOW.timestamp(), True, .1)
        try:
            await executor.restore()
            plans = fresh()[1]
            results = await asyncio.gather(*[
                executor.execute(z, plans[z.id], accepted) for z in h.zones[:3]])
            self.assertEqual(results, ['acked', 'acked', 'revoked'])
            self.assertEqual(calls, ['0', '1'])
            self.assertEqual(concurrent, [1, 1])
            self.assertEqual(m['2'].attempts, 0)
        finally:
            await executor.close()

    async def test_no_budget_does_not_retry_ambiguous_send(self):
        from execution import Executor
        from test_execution import Store
        h, s, prices, m, pm = DryAdmissionTests().case()
        calls = []

        def fresh(_=None):
            return s, evaluate(h, s, prices, m, pm)

        async def no_echo(*args):
            calls.append(args)

        executor = Executor(h, Store(), fresh, no_echo, lambda: NOW.timestamp(), True, .01)
        try:
            await executor.restore()
            z = h.zones[0]
            self.assertEqual(await executor.execute(z, fresh()[1][z.id]), 'unconfirmed')
            self.assertFalse(executor.is_automatic(z.id))
            self.assertEqual(await executor.execute(z, fresh()[1][z.id]), 'revoked')
            self.assertEqual(len(calls), 1)
        finally:
            await executor.close()
