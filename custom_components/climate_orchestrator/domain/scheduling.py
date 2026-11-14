"""Scheduling helpers separating slow planning from live safety guards."""

from __future__ import annotations

from math import isfinite
from typing import Iterable


def plan_review_due(
    last_review_at: float | None,
    now: float,
    interval_s: int,
    *,
    immediate: bool = False,
) -> bool:
    """Return whether a full plan may be refreshed now.

    An absent/invalid clock fails open to an initial refresh. Routine source
    events are coalesced for ``interval_s``; safety and explicit commands use
    their own paths and can request an immediate review.
    """
    if immediate or last_review_at is None or not isfinite(last_review_at):
        return True
    return now - last_review_at >= interval_s


def immediate_review_required(
    old_state: str | None,
    new_state: str | None,
    *,
    urgent_entity: bool = False,
    actuator_changed: bool = False,
    user_action: bool = False,
) -> bool:
    """Keep authority/actuator changes and source loss/recovery out of the slow queue."""
    if old_state is None or new_state is None:
        return True
    if new_state in {"unknown", "unavailable"}:
        return True
    # A source coming back is as relevant as one going away: otherwise a plan
    # computed while it was missing stays blind until the periodic review.
    if old_state in {"unknown", "unavailable"} and old_state != new_state:
        return True
    if urgent_entity and old_state != new_state:
        return True
    return actuator_changed or user_action


def next_deadline_within(
    decisions: Iterable[object], now: float, horizon_s: int
) -> float | None:
    """Return the earliest valid decision deadline before the periodic wake."""
    candidates = []
    for decision in decisions:
        value = getattr(decision, "next_at", None)
        if (
            isinstance(value, (int, float))
            and isfinite(value)
            and now < value < now + horizon_s
        ):
            candidates.append(float(value))
    return min(candidates) if candidates else None
