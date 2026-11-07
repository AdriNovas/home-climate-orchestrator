"""Bounded tariff opportunities over one common protected engine.

No thermal model: this is a price opportunity policy, not an optimizer claiming
euros saved. No opportunistic preheating and no invented forecast coverage.
"""

from dataclasses import dataclass, replace
from copy import deepcopy
from .tariffs import opportunities


@dataclass(frozen=True)
class ResolvedGoals:
    heat: float
    cool: float
    preferred_heat: float
    preferred_cool: float
    reason: str
    until: float | None = None


def resolve_goals(
    house, zone, obs, snap, prices, memory, sleep, legacy_heat, legacy_cool
):
    strategy = house.strategy
    if strategy == "legacy":
        return ResolvedGoals(
            legacy_heat, legacy_cool, legacy_heat, legacy_cool, "legacy_tables"
        )
    policy, pref = house.policy, zone.preferences
    now = snap.now.timestamp()
    base = next(
        (b for b in policy.bands if b.name == "normal"),
        policy.bands[len(policy.bands) // 2],
    )
    phase = "sleep" if sleep else "day"
    heat_table = zone.heat_sleep_targets if sleep else zone.heat_targets
    cool_table = zone.cool_sleep_targets if sleep else zone.cool_targets
    heat = getattr(pref, f"heat_{phase}")
    cool = getattr(pref, f"cool_{phase}")
    heat = (
        heat_table.get(base.name, getattr(base, f"heat_{phase}"))
        if heat is None
        else heat
    )
    cool = (
        cool_table.get(base.name, getattr(base, f"cool_{phase}"))
        if cool is None
        else cool
    )
    # Explicit external goals remain authoritative, not a knob for new profiles.
    if zone.heat_goal_entity or zone.cool_goal_entity:
        return ResolvedGoals(
            legacy_heat, legacy_cool, legacy_heat, legacy_cool, "external_targets"
        )
    if obs.activity == "vacant":
        heat = max(pref.minimum_heat, heat - pref.vacancy_heat_delta)
        cool = min(pref.maximum_cool, cool + pref.vacancy_cool_delta)
    preferred_heat, preferred_cool = heat, cool
    if not obs.temperature.fresh(now, policy.temperature_fresh_s):
        return ResolvedGoals(heat, cool, heat, cool, "temperature_unavailable")
    t = obs.temperature.value
    deficit = max(heat - t, t - cool, 0)
    mode = (
        "heat"
        if t <= heat - policy.start_delta
        else "cool"
        if t >= cool + policy.start_delta
        else None
    )
    if deficit == 0:
        memory.thermal_wait_since = memory.thermal_wait_until = 0
        memory.thermal_wait_mode = None
        memory.discomfort_degree_minutes = 0
    # Integrate only distinct, ordered measured reports with bounded gaps.
    if obs.temperature.at > memory.comfort_last_report:
        elapsed = now - memory.comfort_last_at
        if memory.comfort_last_at and 0 < elapsed <= policy.thermal_sample_gap_s:
            memory.discomfort_degree_minutes += deficit * elapsed / 60
        memory.comfort_last_at = now
        memory.comfort_last_report = obs.temperature.at
    enabled = (
        obs.automatic
        and zone.enabled
        and obs.permitted
        and not snap.paused
        and (not sleep or zone.night_allowed)
        and obs.goals_valid
        and (snap.occupied if obs.thermal_occupied is None else obs.thermal_occupied)
        is True
    )
    if mode and enabled and (obs.heat_allowed if mode == "heat" else obs.cool_allowed):
        if memory.thermal_wait_mode != mode:
            # A new direction has a new demand, not a continuation of the old one.
            memory.thermal_wait_since = now
            memory.thermal_wait_until = 0
            memory.thermal_wait_mode = mode
    fraction = 1 if strategy == "price" else 0.5
    flex_heat = max(pref.minimum_heat, heat - pref.heat_flex * fraction)
    flex_cool = min(pref.maximum_cool, cool + pref.cool_flex * fraction)
    limit = pref.price_wait_s if strategy == "price" else pref.balanced_wait_s
    if (
        strategy == "comfort"
        or not mode
        or not enabled
        or obs.mode != "off"
        or not limit
    ):
        return ResolvedGoals(heat, cool, heat, cool, "preferred_targets")
    if mode not in obs.supported_modes:
        return ResolvedGoals(heat, cool, heat, cool, "unsupported_mode")
    if not (flex_heat < t < flex_cool):
        return ResolvedGoals(heat, cool, heat, cool, "flexibility_exhausted")
    if memory.discomfort_degree_minutes >= pref.discomfort_degree_minutes:
        return ResolvedGoals(heat, cool, heat, cool, "discomfort_budget")
    deadline = memory.thermal_wait_since + limit
    if memory.thermal_wait_until:
        deadline = min(deadline, memory.thermal_wait_until)
    plant = next(p for p in house.plants if p.id == zone.plant)
    windows = opportunities(
        prices,
        snap.now,
        max(1, plant.minimum_on_s),
        max(1, min(limit, policy.lookahead_s)),
    )
    current = next((w for w in windows if abs(w["start"] - now) < 1), None)
    cheaper = next(
        (
            w
            for w in windows
            if current
            and now < w["start"] <= deadline
            and w["average"] < current["average"] - policy.improvement
        ),
        None,
    )
    if now >= deadline:
        return ResolvedGoals(heat, cool, heat, cool, "maximum_wait_reached")
    if not cheaper:
        return ResolvedGoals(heat, cool, heat, cool, "no_complete_cheaper_window")
    # Freeze or shorten a lease. Profile changes cannot renew an existing wait.
    until = min(deadline, cheaper["start"])
    memory.thermal_wait_until = until
    return ResolvedGoals(
        flex_heat,
        flex_cool,
        preferred_heat,
        preferred_cool,
        "cheaper_thermal_window",
        until,
    )


def preview(house, snap, prices, memories, plants):
    """Counterfactual outputs have no access to live journals or accounting."""
    from .engine import evaluate

    return {
        name: evaluate(
            replace(house, strategy=name),
            snap,
            prices,
            deepcopy(memories),
            deepcopy(plants),
        )
        for name in ("price", "balanced", "comfort")
    }


def humidity_opportunity(house, zone, snap, prices, memory, duration):
    """Optional economic wait only; all thermal/equipment guards stay upstream."""
    strategy = house.strategy
    limit = (
        zone.preferences.price_wait_s
        if strategy == "price"
        else zone.preferences.balanced_wait_s
        if strategy == "balanced"
        else 0
    )
    if not limit:
        return None
    now = snap.now.timestamp()
    clocks = [at for at in (memory.high_since, memory.debt_since) if at > 0]
    since = min(clocks) if clocks else now
    deadline = since + min(limit, house.policy.humidity_deadline_s)
    if now >= deadline:
        return None
    windows = opportunities(
        prices, snap.now, duration, min(limit, house.policy.lookahead_s)
    )
    current = next((w for w in windows if abs(w["start"] - now) < 1), None)
    return next(
        (
            w["start"]
            for w in windows
            if current
            and now < w["start"] <= deadline
            and w["average"] < current["average"] - house.policy.improvement
        ),
        None,
    )
