"""Optional accepted-reservation exits; all readings and clocks are synthetic."""
from dataclasses import asdict, replace
from datetime import timedelta
import unittest

from test_domain import fixture, NOW
from domain.engine import evaluate, begin_dry, dew_point
from domain.models import Memory, Reading, house_from_dict


class DryReservationTests(unittest.TestCase):
    def case(self, drop=None, dew=False):
        h, s, prices, m, pm = fixture()
        h = replace(h, zones=(replace(h.zones[0], dry_max_temperature_drop=drop,
                                      dry_dewpoint_completion=dew),),
                    policy=replace(h.policy, dry_max_s=0, humidity_recovery_s=300))
        s.zones['0'] = replace(s.zones['0'], mode='dry',
                               temperature=Reading(23, NOW.timestamp()),
                               humidity=Reading(70, NOW.timestamp()))
        m['0'] = Memory()
        begin_dry(m['0'], NOW.timestamp()-1800, 20, 60, 0,
                  start_temperature=23, dew_target=round(dew_point(20, 60), 3) if dew else None)
        return h, s, prices, m, pm

    def test_strict_drop_boundary_and_missing_start_are_protective(self):
        h, s, prices, m, pm = self.case(drop=.7)
        for temperature, mode in [(22.3, 'dry'), (22.299, 'off')]:
            s.zones['0'] = replace(s.zones['0'], temperature=Reading(temperature, NOW.timestamp()))
            self.assertEqual(evaluate(h, s, prices, m, pm)['0'].mode, mode)
        m['0'].dry_start_temperature = None
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].mode, 'off')

    def test_disabled_new_guards_keep_legacy_session_compatible(self):
        h, s, prices, m, pm = self.case()
        m['0'].dry_start_temperature = None
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].mode, 'dry')
        h = replace(h, zones=(replace(h.zones[0], dry_dewpoint_completion=True),))
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].mode, 'off')

    def test_humidity_alone_does_not_start_recovery_timer_with_dew_enabled(self):
        h, s, prices, m, pm = self.case(dew=True)
        s.zones['0'] = replace(s.zones['0'], humidity=Reading(59, NOW.timestamp()))
        self.assertGreater(dew_point(23, 59), m['0'].dry_dew_target)
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].mode, 'dry')
        self.assertEqual(m['0'].low_since, 0)
        # Both conditions now hold, then must persist for the complete interval.
        s.zones['0'] = replace(s.zones['0'], temperature=Reading(20, NOW.timestamp()))
        self.assertEqual(evaluate(h, s, prices, m, pm)['0'].mode, 'dry')
        self.assertEqual(m['0'].low_since, NOW.timestamp())
        later = replace(s, now=NOW+timedelta(seconds=299))
        self.assertEqual(evaluate(h, later, prices, m, pm)['0'].mode, 'dry')
        later = replace(s, now=NOW+timedelta(seconds=300))
        self.assertEqual(evaluate(h, later, prices, m, pm)['0'].mode, 'off')

    def test_recovery_break_and_roundtrip_do_not_renew_reservation(self):
        h, s, prices, m, pm = self.case(dew=True)
        before = (m['0'].dry_start, m['0'].dry_dew_target)
        s.zones['0'] = replace(s.zones['0'], temperature=Reading(20, NOW.timestamp()),
                               humidity=Reading(59, NOW.timestamp()))
        evaluate(h, s, prices, m, pm)
        m['0'] = Memory(**asdict(m['0']))
        self.assertEqual(m['0'].low_since, NOW.timestamp())
        # A tariff target change cannot change the frozen target or original start.
        h = replace(h, zones=(replace(h.zones[0], humidity_stop_targets={'normal': 50}),))
        s.zones['0'] = replace(s.zones['0'], temperature=Reading(23, NOW.timestamp()))
        evaluate(h, s, prices, m, pm)
        self.assertEqual(m['0'].low_since, 0)
        self.assertEqual((m['0'].dry_start, m['0'].dry_dew_target), before)

    def test_debt_toggle_changes_urgency_not_persisted_debt_or_real_thresholds(self):
        h, s, prices, m, pm = fixture()
        s.zones['0'] = replace(s.zones['0'], temperature=Reading(23, NOW.timestamp()),
                               humidity=Reading(70, NOW.timestamp()))
        m['0'] = Memory(debt_since=NOW.timestamp()-15000)
        self.assertTrue(evaluate(h, s, prices, m, pm)['0'].urgent)
        h = replace(h, policy=replace(h.policy, humidity_debt_urgency=False))
        self.assertFalse(evaluate(h, s, prices, m, pm)['0'].urgent)
        self.assertEqual(m['0'].debt_since, NOW.timestamp()-15000)
        # Independent high/severe criteria remain operative when debt is disabled.
        for rh, field, seconds in [(75, 'urgent_since', 1800), (80, 'severe_since', 900)]:
            s.zones['0'] = replace(s.zones['0'], humidity=Reading(rh, NOW.timestamp()))
            setattr(m['0'], field, NOW.timestamp()-seconds)
            self.assertTrue(evaluate(h, s, prices, m, pm)['0'].urgent)

    def test_legacy_defaults_roundtrip_and_invalid_configuration(self):
        h, *_ = fixture()
        self.assertTrue(h.policy.humidity_debt_urgency)
        self.assertIsNone(h.zones[0].dry_max_temperature_drop)
        self.assertFalse(h.zones[0].dry_dewpoint_completion)
        for value in [True, -.1, 10.1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                replace(h.zones[0], dry_max_temperature_drop=value)
        for value in [1, 'false']:
            with self.assertRaises(ValueError):
                replace(h.zones[0], dry_dewpoint_completion=value)
            with self.assertRaises(ValueError):
                replace(h.policy, humidity_debt_urgency=value)
        h = replace(h, zones=(replace(h.zones[0], dry_max_temperature_drop=.7,
                                      dry_dewpoint_completion=True),))
        self.assertEqual(house_from_dict(asdict(h)), h)
        for field in ['dry_start_temperature', 'dry_dew_target']:
            for value in [True, float('nan'), float('inf')]:
                with self.assertRaises(ValueError):
                    Memory(**{field: value})
