"""Bound full planning while preserving urgent events and absolute deadlines."""

from types import SimpleNamespace
import unittest

from domain.scheduling import (
    immediate_review_required,
    next_deadline_within,
    plan_review_due,
)


class ReviewCadenceTests(unittest.TestCase):
    def test_ordinary_plan_is_coalesced_for_five_minutes(self):
        last = 1_000.0
        self.assertFalse(plan_review_due(last, last + 299, 300))
        self.assertTrue(plan_review_due(last, last + 300, 300))
        self.assertTrue(plan_review_due(last, last + 1, 300, immediate=True))
        self.assertTrue(plan_review_due(None, last, 300))

    def test_authority_actuator_and_source_loss_bypass_coalescing(self):
        self.assertTrue(
            immediate_review_required("off", "on", urgent_entity=True)
        )
        self.assertTrue(
            immediate_review_required(
                "heat", "heat", actuator_changed=True
            )
        )
        self.assertTrue(
            immediate_review_required("21", "unavailable")
        )
        self.assertTrue(immediate_review_required("unavailable", "21"))
        self.assertTrue(immediate_review_required("unknown", "21.1"))
        self.assertFalse(
            immediate_review_required("21.0", "21.1")
        )
        self.assertFalse(
            immediate_review_required("off", "off", urgent_entity=True)
        )

    def test_deadlines_wake_before_periodic_review(self):
        now = 2_000.0
        decisions = [
            SimpleNamespace(next_at=now + 240),
            SimpleNamespace(next_at=now + 90),
            SimpleNamespace(next_at=now - 1),
            SimpleNamespace(next_at=None),
        ]
        self.assertEqual(next_deadline_within(decisions, now, 300), now + 90)
        self.assertIsNone(
            next_deadline_within(
                [SimpleNamespace(next_at=now + 300)], now, 300
            )
        )
        self.assertIsNone(
            next_deadline_within(
                [SimpleNamespace(next_at=float("inf"))], now, 300
            )
        )


if __name__ == "__main__":
    unittest.main()
