"""Compatibility records are bounded evidence, never authority or silence windows."""

import copy
from dataclasses import replace
import unittest
from test_domain import fixture
from domain.engine import hardware_target, evaluate
from domain.provenance import transition_echo, critical_echo, cut_record, journal_echo
from domain.models import Reading

NOW = 1000


class ProvenanceTests(unittest.TestCase):
    def test_partial_and_final_automatic_echoes(self):
        ledger = {"q": [[0, 19, 1, 22, NOW + 20, 0]]}
        self.assertTrue(transition_echo(ledger, "off", 22, "off", 19, NOW))
        self.assertTrue(transition_echo(ledger, "heat", 22, "off", 22, NOW))
        self.assertFalse(transition_echo(ledger, "cool", 22, "off", 19, NOW))
        self.assertFalse(transition_echo(ledger, "heat", 23, "off", 19, NOW))

    def test_explicit_person_always_wins_even_for_matching_pending(self):
        for ack in (0, 1):
            self.assertFalse(
                transition_echo(
                    {"q": [[0, 19, 1, 22, NOW + 20, ack]]},
                    "heat",
                    22,
                    "off",
                    19,
                    NOW,
                    True,
                )
            )

    def test_expired_and_unbounded_leases_are_not_silence_windows(self):
        for until in (NOW - 0.01, NOW + 61, float("inf"), float("nan"), True):
            self.assertFalse(
                transition_echo(
                    {"q": [[0, 19, 1, 22, until, 0]]}, "heat", 22, "off", 19, NOW
                )
            )

    def test_acknowledged_ledger_accepts_only_its_exact_final_state(self):
        ledger = {"q": [[0, 19, 1, 22, NOW + 20, 1]]}
        self.assertTrue(transition_echo(ledger, "heat", 22, "off", 22, NOW))
        self.assertFalse(transition_echo(ledger, "off", 22, "off", 19, NOW))

    def test_malformed_and_availability_transitions_are_not_provenance(self):
        for ledger in (
            None,
            "unavailable",
            "[]",
            {"q": [None]},
            {"q": [[0, 19, 1, 22, NOW + 20, True]]},
            {"q": [[-1, 19, 1, 22, NOW + 20, 0]]},
        ):
            self.assertFalse(transition_echo(ledger, "heat", 22, "off", 19, NOW))
        self.assertFalse(
            transition_echo(
                {"q": [[0, 19, 1, 22, NOW + 20, 0]]}, "heat", 22, "unavailable", 19, NOW
            )
        )

    def test_cut_unknown_is_distinct_from_initialized_empty(self):
        self.assertEqual(cut_record("{}"), {"active": False, "at": 0, "released": 0})
        for value in (
            "unavailable",
            "[]",
            {"active": "false"},
            {"at": float("nan")},
            {"released": -1},
        ):
            self.assertIsNone(cut_record(value))

    def test_critical_echo_is_bound_to_cut_generation_not_current_mode_alone(self):
        cut = {"active": True, "at": 990, "released": 0}
        ledger = {"at": 990, "until": 1020, "late": 1030, "old": [[1, 22]]}
        self.assertTrue(critical_echo(ledger, cut, "off", 19, NOW))
        self.assertTrue(critical_echo(ledger, cut, "heat", 22, NOW))
        self.assertFalse(critical_echo(ledger, {**cut, "at": 991}, "off", 19, NOW))
        self.assertFalse(
            critical_echo(ledger, {**cut, "active": False}, "heat", 22, NOW)
        )
        self.assertFalse(critical_echo(ledger, cut, "off", 19, NOW, True))

    def test_journal_consumer_rejects_unpublished_or_wrong_actuator(self):
        journal = {
            "schema_version": 1,
            "actuator": "climate.demo",
            "execution_mode": "control",
            "temperature_unit": "°C",
            "phase": "sending",
            "expected": [{"mode": "heat", "target": 22, "until": 1020}],
        }
        self.assertTrue(journal_echo(journal, "climate.demo", "heat", 22, NOW))
        self.assertFalse(journal_echo(journal, "climate.other", "heat", 22, NOW))
        self.assertFalse(journal_echo(journal, "climate.demo", "heat", 23, NOW))
        self.assertFalse(journal_echo(journal, "climate.demo", "heat", 22, NOW, True))
        for key, value in (
            ("schema_version", 2),
            ("phase", "prepared"),
            ("phase", "cancelled"),
            ("execution_mode", "shadow"),
        ):
            self.assertFalse(
                journal_echo({**journal, key: value}, "climate.demo", "heat", 22, NOW)
            )


class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.house, self.snap, *_ = fixture(proportional_gain=1, boost_limit=1)
        self.zone = replace(
            self.house.zones[0], response_entity="input_text.demo_response"
        )
        self.at = self.snap.now.timestamp()

    def target(
        self,
        mode="heat",
        extra=2,
        age=0,
        goal=21,
        temperature=18,
        bias=1,
        response_mode=None,
        response_goal=None,
    ):
        obs = replace(
            self.snap.zones["0"],
            temperature=Reading(temperature, self.at),
            bias=Reading(bias, self.at),
            response={
                "m": response_mode or mode,
                "g": response_goal or goal,
                "b": extra,
                "at": self.at - age,
            },
        )
        return hardware_target(self.zone, obs, goal, mode, self.house, self.at)

    def test_measured_extra_effort_in_both_directions(self):
        self.assertEqual(self.target(), 25)
        self.assertEqual(self.target("cool", temperature=24, bias=-1), 17)

    def test_stale_wrong_mode_or_wrong_goal_adds_no_effort(self):
        for kwargs in ({"age": 661}, {"response_mode": "cool"}, {"response_goal": 20}):
            self.assertEqual(self.target(**kwargs), 23)
        self.assertEqual(self.target(age=660), 25)

    def test_future_nonfinite_negative_and_excessive_response_are_ignored(self):
        for value in (float("nan"), float("inf"), True, -1, 3):
            self.assertEqual(self.target(extra=value), 23)
        self.assertEqual(self.target(age=-1), 23)

    def test_missing_response_preserves_base_feedback(self):
        obs = replace(self.snap.zones["0"], bias=Reading(1, self.at))
        self.assertEqual(
            hardware_target(self.zone, obs, 21, "heat", self.house, self.at), 23
        )

    def test_near_goal_relaxes_and_hardware_limits_hold(self):
        self.assertEqual(self.target(goal=21, temperature=21), 19.5)
        self.assertEqual(self.target(goal=29, temperature=18, bias=4), 30)

    def test_response_inputs_are_not_mutated(self):
        obs = replace(
            self.snap.zones["0"], response={"at": self.at, "m": "heat", "g": 21, "b": 2}
        )
        before = copy.deepcopy(obs.response)
        hardware_target(self.zone, obs, 21, "heat", self.house, self.at)
        self.assertEqual(obs.response, before)


class RequiredFeedbackTests(unittest.TestCase):
    def test_stale_internal_feedback_cannot_start_a_required_feedback_device(self):
        house, snap, prices, memories, plants = fixture()
        house = replace(
            house, zones=(replace(house.zones[0], require_internal_feedback=True),)
        )
        snap.zones["0"] = replace(snap.zones["0"], internal=Reading(None))
        decision = evaluate(house, snap, prices, memories, plants)["0"]
        self.assertIsNone(decision.mode)
        self.assertEqual(decision.reason, "internal_feedback_stale")

    def test_failed_zone_does_not_reserve_the_shared_plant(self):
        house, snap, prices, memories, plants = fixture(2)
        house = replace(
            house,
            zones=(
                replace(house.zones[0], require_internal_feedback=True),
                house.zones[1],
            ),
        )
        now = snap.now.timestamp()
        snap.zones["0"] = replace(
            snap.zones["0"], temperature=Reading(10, now), internal=Reading(None)
        )
        snap.zones["1"] = replace(snap.zones["1"], temperature=Reading(29, now))
        decisions = evaluate(house, snap, prices, memories, plants)
        self.assertIsNone(decisions["0"].mode)
        self.assertEqual(decisions["1"].mode, "cool")

    def test_off_only_excess_protection_does_not_need_internal_feedback(self):
        house, snap, prices, memories, plants = fixture()
        house = replace(
            house, zones=(replace(house.zones[0], require_internal_feedback=True),)
        )
        snap.zones["0"] = replace(
            snap.zones["0"],
            mode="heat",
            temperature=Reading(25, snap.now.timestamp()),
            internal=Reading(None),
        )
        self.assertEqual(
            evaluate(house, snap, prices, memories, plants)["0"].mode, "off"
        )

    def test_feedback_requirement_is_explicit_and_strictly_boolean(self):
        house, snap, prices, memories, plants = fixture()
        snap.zones["0"] = replace(snap.zones["0"], internal=Reading(None))
        self.assertEqual(
            evaluate(house, snap, prices, memories, plants)["0"].mode, "heat"
        )
        with self.assertRaises(ValueError):
            replace(house.zones[0], require_internal_feedback="false")
