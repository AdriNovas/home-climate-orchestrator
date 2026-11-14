"""Observed thermal posture of a unit: demand, maintenance or off.

The classification describes what the room needs relative to its goal while
the unit runs. It is derived from measured state and the current plan, never
from compressor activity or electrical power, and it cannot issue commands.
"""

from __future__ import annotations

from .models import Decision, House, Observation

LEVELS = {"off": 0, "maintain": 1, "stopping": 1, "demand": 2}
STATES = ("off", "maintain", "demand", "stopping", "unmanaged", "drying")


def thermal_demand(
    house: House, decision: Decision | None, obs: Observation | None, now: float
) -> dict:
    """Return the posture and the temperature deficit that justifies it.

    ``maintain`` means the unit runs while the room is already at (or beyond)
    its goal, so the setpoint only keeps the appliance from cycling. ``demand``
    means the room still needs heating or cooling.
    """
    empty = {"state": "off", "level": 0, "deficit": None, "goal": None}
    if decision is None or obs is None:
        return {**empty, "state": "unmanaged", "level": None}
    policy = house.policy
    running = obs.mode if obs.mode in ("heat", "cool") else None
    wanted = decision.mode if decision.mode in ("heat", "cool") else None
    if obs.mode == "dry" or decision.stage in ("drying", "dry_ready"):
        return {**empty, "state": "drying"}
    mode = running or wanted
    if mode is None:
        if obs.mode in ("off", "fan_only"):
            return empty
        return {**empty, "state": "unmanaged", "level": None}
    goal = decision.heat_goal if mode == "heat" else decision.cool_goal
    if not obs.temperature.fresh(now, policy.temperature_fresh_s):
        return {"state": "unmanaged", "level": None, "deficit": None, "goal": goal}
    temperature = obs.temperature.value
    deficit = round(goal - temperature if mode == "heat" else temperature - goal, 2)
    base = {"deficit": deficit, "goal": goal}
    if running and decision.mode == "off":
        return {**base, "state": "stopping", "level": LEVELS["stopping"]}
    if running and decision.mode not in ("heat", "cool"):
        return {**base, "state": "unmanaged", "level": None}
    if running is None:
        # Planned start: the room needs the unit.
        return {**base, "state": "demand", "level": LEVELS["demand"]}
    threshold = 0.3 if policy.continuous_hold else policy.hold_delta
    state = "demand" if deficit > threshold else "maintain"
    return {**base, "state": state, "level": LEVELS[state]}
