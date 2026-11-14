"""Observed thermal posture of a unit: demand, maintenance or off.

The classification describes what the room needs relative to its goal while
the unit runs. It is derived from measured state and the current plan, never
from compressor activity or electrical power, and it cannot issue commands.
"""

from __future__ import annotations

from .models import Decision, House, Observation

LEVELS = {"off": 0, "maintain": 1, "stopping": 1, "demand": 2}
STATES = ("off", "maintain", "demand", "stopping", "unmanaged", "drying")
HOUSE_STATES = (
    "off",
    "heat_maintain",
    "heat_demand",
    "cool_maintain",
    "cool_demand",
    "mixed",
)


def thermal_demand(
    house: House, decision: Decision | None, obs: Observation | None, now: float
) -> dict:
    """Return the posture and the temperature deficit that justifies it.

    ``maintain`` means the unit runs without acting: the room is at (or beyond)
    its goal, or the appliance setpoint is already less demanding than the
    temperature the unit measures, so it only stays on to avoid cycling. ``demand``
    means the room still needs heating or cooling. The classification follows
    the room and the unit, not whether the planner could issue a command now:
    a waiting or blocked plan does not change what a running unit is doing.
    """
    empty = {"state": "off", "level": 0, "deficit": None, "goal": None, "mode": None}
    if decision is None or obs is None:
        return {**empty, "state": "unmanaged", "level": None}
    policy = house.policy
    running = obs.mode if obs.mode in ("heat", "cool") else None
    wanted = decision.mode if decision.mode in ("heat", "cool") else None
    if obs.mode == "dry":
        return {**empty, "state": "drying"}
    mode = running or wanted
    if mode is None:
        if obs.mode in ("off", "fan_only"):
            return empty
        return {**empty, "state": "unmanaged", "level": None}
    goal = decision.heat_goal if mode == "heat" else decision.cool_goal
    if not obs.temperature.fresh(now, policy.temperature_fresh_s):
        return {"state": "unmanaged", "level": None, "deficit": None, "goal": goal, "mode": mode}
    temperature = obs.temperature.value
    deficit = round(goal - temperature if mode == "heat" else temperature - goal, 2)
    base = {"deficit": deficit, "goal": goal, "mode": mode}
    if running and decision.mode == "off":
        return {**base, "state": "stopping", "level": LEVELS["stopping"]}
    if running is None:
        # Planned start: the room needs the unit.
        return {**base, "state": "demand", "level": LEVELS["demand"]}
    threshold = 0.3 if policy.continuous_hold else policy.hold_delta
    # The appliance has the last word on whether it is working: when its own
    # setpoint is already less demanding than the temperature it measures, it
    # is kept on without acting, even if the room sits slightly off its goal.
    relaxed = (
        obs.setpoint is not None
        and obs.internal.fresh(now, policy.internal_fresh_s)
        and (
            obs.setpoint <= obs.internal.value - obs.step / 2
            if mode == "heat"
            else obs.setpoint >= obs.internal.value + obs.step / 2
        )
    )
    state = "demand" if deficit > threshold and not relaxed else "maintain"
    return {**base, "state": state, "level": LEVELS[state], "appliance_relaxed": relaxed}


def house_posture(postures) -> dict:
    """Combine room postures into one chartable house state.

    Any room that still needs conditioning makes the house ``*_demand``; units
    that only keep an already satisfied room are ``*_maintain``. Opposite
    directions at the same time are ``mixed`` and rooms without data are ignored.
    """
    running = [p for p in postures if p["state"] in ("maintain", "demand", "stopping")]
    demanding = [p for p in running if p["state"] == "demand"]
    pool = demanding or running
    modes = {p["mode"] for p in pool if p.get("mode")}
    if not pool or not modes:
        return {"state": "off", "level": 0, "demanding": 0, "maintaining": 0}
    kind = "demand" if demanding else "maintain"
    state = "mixed" if len(modes) > 1 else f"{next(iter(modes))}_{kind}"
    return {
        "state": state,
        "level": 2 if demanding else 1,
        "demanding": len(demanding),
        "maintaining": len(running) - len(demanding),
    }
