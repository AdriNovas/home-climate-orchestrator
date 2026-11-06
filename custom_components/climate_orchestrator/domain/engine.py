"""Deterministic recommendations. This module cannot issue Home Assistant actions."""

from __future__ import annotations
from dataclasses import replace
from datetime import timezone, datetime, timedelta
from math import log
from zoneinfo import ZoneInfo
from .models import (
    Decision,
    House,
    Memory,
    Observation,
    PlantMemory,
    PriceInterval,
    Snapshot,
    Zone,
    minute,
)
from .tariffs import current_price, opportunities
from .thermal import observe_stability, extreme_price, relaxed_target
from .provenance import number
from .modulation import soft_correction, observe_shared_load, observe_room
from .models import Reading


def dew_point(temperature: float, humidity: float) -> float:
    if not 0 < humidity <= 100:
        raise ValueError("Invalid relative humidity")
    a = log(humidity / 100) + 17.62 * temperature / (243.12 + temperature)
    return 243.12 * a / (17.62 - a)


def sleeping(house: House, snapshot: Snapshot) -> bool:
    local = snapshot.now.astimezone(ZoneInfo(house.timezone))
    weekend = local.weekday() >= 5
    start = minute(house.weekend_day_start if weekend else house.day_start)
    stop = minute(
        house.weekend_night_start if local.weekday() in [4, 5] else house.night_start
    )
    clock = local.hour * 60 + local.minute
    return not (start <= clock < stop) if start < stop else stop <= clock < start


def hardware_target(
    zone: Zone, obs: Observation, goal: float, mode: str, house: House, now: float
) -> float:
    p = house.policy
    deficit = (
        goal - obs.temperature.value if mode == "heat" else obs.temperature.value - goal
    )
    effort = (
        min(p.boost_limit, max(0, deficit * p.proportional_gain))
        if deficit > 0.3
        else 0
    )
    response = obs.response
    extra_effort, trim = 0, 0
    # Compact measured-response v1. A stale or mismatched response adds no effort;
    # it does not replace the independent environmental reference or base bias.
    if (
        (zone.response_entity or p.continuous_hold)
        and deficit > 0.3
        and isinstance(response, dict)
    ):
        at, extra = response.get("at"), response.get("b")
        if (
            response.get("m") == mode
            and response.get("g") == goal
            and number(at)
            and 0 <= now - at <= 660
            and number(extra)
            and 0 <= extra <= 2.5
        ):
            effort += extra
            extra_effort = extra
    if (
        isinstance(response, dict)
        and response.get("m") == mode
        and response.get("g") == goal
        and number(response.get("at"))
        and 0 <= now - response["at"] <= 660
        and number(response.get("h"))
    ):
        trim = max(0, min(2.5, response["h"]))
    correction = max(
        -p.correction_limit,
        min(
            p.correction_limit,
            (
                obs.bias.value
                if obs.bias.fresh(now, p.temperature_fresh_s)
                else zone.bias
            )
            + (effort if mode == "heat" else -effort),
        ),
    )
    target = goal + correction
    if p.continuous_hold:
        bias = (
            obs.bias.value if obs.bias.fresh(now, p.temperature_fresh_s) else zone.bias
        )
        target = goal + soft_correction(deficit, bias, mode, extra_effort, trim, p)
    if deficit <= (0.3 if p.continuous_hold else p.hold_delta) and obs.internal.fresh(
        now, p.internal_fresh_s
    ):
        target = (
            min(target, obs.internal.value - 0.5)
            if mode == "heat"
            else max(target, obs.internal.value + 0.5)
        )
    step = obs.step if obs.step > 0 else 0.5
    return max(
        obs.minimum,
        min(obs.maximum, obs.minimum + round((target - obs.minimum) / step) * step),
    )


def begin_dry(
    memory: Memory, now: float, floor: float, target: float, maximum_s: int
) -> None:
    """Explicit intent acceptance hook for a future executor/simulator, never observer adoption."""
    memory.dry_start = now
    memory.dry_until = now + maximum_s
    memory.dry_floor = floor
    memory.dry_target = target
    memory.last_attempt = now
    memory.attempts += 1
    memory.low_since = 0


def independent_drying(zone, obs, memory, decision, snap, house, high, rh_ok):
    """Standalone refrigerant dryer: no inversion or thermal preheating cycle."""
    p, now = house.policy, snap.now.timestamp()
    if not zone.enabled or snap.paused or not obs.permitted:
        return replace(decision, stage="paused", reason="pause_or_schedule")
    if not obs.temperature.fresh(now, p.temperature_fresh_s) or not rh_ok:
        return replace(
            decision, stage="blocked", reason="humidity_or_temperature_stale"
        )
    if obs.mode == "dry":
        return replace(decision, stage="external", reason="unowned_drying")
    if obs.mode != "off" or "dry" not in obs.supported_modes:
        return replace(decision, stage="blocked", reason="dehumidifier_unavailable")
    if (
        not zone.allow_dry
        or not obs.dry_allowed
        or snap.occupied is not True
        or (sleeping(house, snap) and not zone.night_allowed)
    ):
        return replace(decision, stage="waiting", reason="dry_permission_or_occupancy")
    if (
        not zone.dehumidifier_min_temperature
        <= obs.temperature.value
        <= zone.dehumidifier_max_temperature
    ):
        return replace(
            decision, stage="blocked", reason="dehumidifier_temperature_limit"
        )
    if memory.dry_episode_blocked:
        return replace(
            decision, stage="waiting", reason="dry_episode_recovery_required"
        )
    if not obs.minimum <= decision.humidity_stop <= obs.maximum:
        return replace(
            decision, stage="blocked", reason="humidity_target_outside_actuator"
        )
    if not decision.urgent and not (
        high and now - memory.high_since >= p.humidity_stable_s
    ):
        return decision
    until = max(
        obs.mode_since
        + next(x for x in house.plants if x.id == zone.plant).minimum_off_s,
        memory.last_attempt + zone.dehumidifier_cooldown_s,
    )
    if now < until:
        return replace(decision, stage="waiting", reason="minimum_off", next_at=until)
    return replace(
        decision,
        stage="dry_ready",
        reason="independent_humidity_demand",
        mode="dry",
        physical_target=decision.humidity_stop,
    )


def evaluate(
    house: House,
    snap: Snapshot,
    prices: tuple[PriceInterval, ...],
    memories: dict[str, Memory],
    plants: dict[str, PlantMemory],
) -> dict[str, Decision]:
    now = snap.now.astimezone(timezone.utc).timestamp()
    p = house.policy
    price = current_price(prices, snap.now)
    band = p.band(price) or next(
        (b for b in p.bands if b.name == "normal"), p.bands[len(p.bands) // 2]
    )
    sleep = sleeping(house, snap)
    day = snap.now.astimezone(ZoneInfo(house.timezone)).date().isoformat()
    result = {}
    wanted = {}
    for z in house.zones:
        o = snap.zones[z.id]
        m = memories.setdefault(z.id, Memory())
        if m.day != day:
            m.day = day
            m.attempts = 0
        heat = (
            z.heat_sleep_targets.get(band.name, band.heat_sleep)
            if sleep
            else z.heat_targets.get(band.name, band.heat_day)
        )
        cool = (
            z.cool_sleep_targets.get(band.name, band.cool_sleep)
            if sleep
            else z.cool_targets.get(band.name, band.cool_day)
        )
        if o.heat_goal.fresh(now, p.temperature_fresh_s):
            heat = o.heat_goal.value
        if o.cool_goal.fresh(now, p.temperature_fresh_s):
            cool = o.cool_goal.value
        d = Decision(
            z.id,
            "idle",
            "within_band",
            None,
            heat,
            cool,
            z.humidity_start_targets.get(band.name, band.humidity_start),
            z.humidity_stop_targets.get(band.name, band.humidity_stop),
        )
        temp_ok = o.temperature.fresh(now, p.temperature_fresh_s)
        eligible = (
            o.automatic
            and z.enabled
            and temp_ok
            and not snap.paused
            and o.permitted
            and (not sleep or z.night_allowed)
            and snap.occupied is True
            and o.mode in ["off", "heat", "cool"]
        )
        stable = observe_stability(m, o, p, now, eligible)
        if p.continuous_hold and not z.response_entity:
            m.regulation = observe_room(
                o,
                heat if o.mode == "heat" else cool,
                snap.zone_power.get(z.id, snap.plant_power.get(z.plant, Reading(None))),
                m.regulation,
                now,
                p,
                eligible,
            )
            o = replace(o, response=m.regulation)
        expensive = extreme_price(m, p, price)
        if not eligible or o.mode != m.hold_mode or m.hold_since > now:
            m.hold_since = 0
            m.hold_mode = None
        rh_ok = (
            o.humidity.fresh(now, p.humidity_fresh_s) and 0 < o.humidity.value <= 100
        )
        high = rh_ok and o.humidity.value >= d.humidity_start
        if rh_ok and o.humidity.value <= d.humidity_stop:
            m.dry_episode_blocked = False
        m.high_since = (m.high_since or now) if high else 0
        m.urgent_since = (
            (m.urgent_since or now)
            if rh_ok and o.humidity.value >= p.urgent_humidity
            else 0
        )
        m.debt_since = (
            (m.debt_since or now)
            if rh_ok and o.humidity.value >= p.service_humidity
            else 0
        )
        m.severe_since = (
            (m.severe_since or now)
            if rh_ok and o.humidity.value >= p.severe_humidity
            else 0
        )
        urgent = (
            (m.urgent_since > 0 and now - m.urgent_since >= p.urgent_stable_s)
            or (m.debt_since > 0 and now - m.debt_since >= p.humidity_deadline_s)
            or (m.severe_since > 0 and now - m.severe_since >= p.severe_stable_s)
        )
        d = replace(d, urgent=urgent)
        if not o.automatic:
            m.dry_start = 0
            m.dry_until = 0
            m.low_since = 0
            result[z.id] = replace(d, stage="manual", reason="manual_authority")
            continue
        # An explicit owned session has independent maximum/floor exits even paused.
        if m.dry_until:
            m.low_since = (
                (m.low_since or now)
                if rh_ok and o.humidity.value <= m.dry_target
                else 0
            )
            stop = (
                now >= m.dry_until
                or not temp_ok
                or not rh_ok
                or o.temperature.value < m.dry_floor
                or snap.paused
                or not o.permitted
                or not o.dry_allowed
                or not z.enabled
                or (
                    z.independent_drying
                    and o.temperature.value > z.dehumidifier_max_temperature
                )
            )
            recovered = (
                m.low_since > 0
                and now - m.low_since >= p.humidity_recovery_s
                and now - m.dry_start
                >= (z.dehumidifier_min_s if z.independent_drying else p.dry_min_s)
            )
            if o.mode == "off" and now >= m.dry_start + 80:
                if z.independent_drying:
                    m.dry_episode_blocked = True
                m.dry_start = 0
                m.dry_until = 0
                m.low_since = 0
            elif stop or recovered:
                if z.independent_drying and now >= m.dry_until:
                    m.dry_episode_blocked = True
                result[z.id] = replace(
                    d, stage="dry_stop", reason="session_limit_or_recovery", mode="off"
                )
                continue
            elif o.mode == "dry":
                result[z.id] = replace(
                    d,
                    stage="drying",
                    reason="owned_session",
                    mode="dry",
                    physical_target=m.dry_target if z.independent_drying else None,
                    next_at=m.dry_until,
                )
                continue
            else:
                result[z.id] = replace(
                    d,
                    stage="waiting",
                    reason="dry_ack_pending",
                    next_at=m.dry_start + 80,
                )
                continue
        if z.independent_drying:
            independent = independent_drying(z, o, m, d, snap, house, high, rh_ok)
            if independent.mode == "dry":
                wanted[z.id] = ("dry", z.priority + (10 if urgent else 0), independent)
            else:
                result[z.id] = independent
            continue
        if not z.enabled:
            result[z.id] = replace(d, stage="paused", reason="zone_disabled")
            continue
        if not o.goals_valid or heat >= cool:
            result[z.id] = replace(
                d, stage="blocked", reason="external_goal_unavailable"
            )
            continue
        if not temp_ok:
            result[z.id] = replace(d, stage="blocked", reason="temperature_stale")
            continue
        if o.mode == "dry":
            result[z.id] = replace(d, stage="external", reason="unowned_drying")
            continue
        if snap.paused or not o.permitted or (sleep and not z.night_allowed):
            result[z.id] = replace(d, stage="paused", reason="pause_or_schedule")
            continue
        if (o.mode == "heat" and not o.heat_allowed) or (
            o.mode == "cool" and not o.cool_allowed
        ):
            result[z.id] = replace(
                d, stage="blocked", reason="external_mode_permission"
            )
            continue
        t = o.temperature.value
        excess = (o.mode == "heat" and t >= heat + p.overshoot_delta) or (
            o.mode == "cool" and t <= cool - p.overshoot_delta
        )
        if excess:
            result[z.id] = replace(
                d, stage="protect", reason="temperature_overshoot", mode="off"
            )
            continue
        if snap.occupied is not True:
            result[z.id] = replace(d, stage="waiting", reason="occupancy_unconfirmed")
            continue
        plant = next(x for x in house.plants if x.id == z.plant)
        near_goal = (
            o.mode == "heat" and heat - p.hold_delta <= t < heat + p.overshoot_delta
        ) or (o.mode == "cool" and cool - p.overshoot_delta < t <= cool + p.hold_delta)
        target = (
            relaxed_target(
                o,
                hardware_target(
                    z, o, heat if o.mode == "heat" else cool, o.mode, house, now
                ),
                now,
                p,
            )
            if near_goal and o.mode in o.supported_modes
            else None
        )
        economic_coast = (
            expensive and stable and heat - p.hold_delta <= t <= cool + p.hold_delta
        )
        if economic_coast:
            if o.mode in ["heat", "cool"] and now - o.mode_since < plant.minimum_on_s:
                wanted[z.id] = (
                    o.mode,
                    z.priority,
                    replace(
                        d,
                        stage="settling",
                        reason="economic_minimum_run",
                        mode=o.mode,
                        physical_target=target,
                        next_at=o.mode_since + plant.minimum_on_s,
                    ),
                )
            else:
                result[z.id] = replace(
                    d, stage="coasting", reason="extreme_price_stable", mode="off"
                )
            continue
        if p.continuous_hold and near_goal:
            # A thermostat may have to raise its physical setpoint again when
            # the coil cools; continuity is not restricted to monotonic commands.
            target = hardware_target(
                z, o, heat if o.mode == "heat" else cool, o.mode, house, now
            )
        if (p.modulated_hold_s or p.continuous_hold) and target is not None:
            if not m.hold_since:
                m.hold_since, m.hold_mode = now, o.mode
            until = m.hold_since + p.modulated_hold_s
            if (
                p.continuous_hold
                or now < until
                or now - o.mode_since < plant.minimum_on_s
            ):
                wanted[z.id] = (
                    o.mode,
                    z.priority,
                    replace(
                        d,
                        stage="holding"
                        if p.continuous_hold or now < until
                        else "settling",
                        reason="continuous_modulation"
                        if p.continuous_hold
                        else "modulated_hold"
                        if now < until
                        else "minimum_run",
                        mode=o.mode,
                        physical_target=target,
                        next_at=None
                        if p.continuous_hold
                        else max(until, o.mode_since + plant.minimum_on_s),
                    ),
                )
            else:
                result[z.id] = replace(
                    d, stage="coasting", reason="hold_budget_expired", mode="off"
                )
            continue
        m.hold_since, m.hold_mode = 0, None
        heat_needed = t <= heat - p.start_delta or (
            o.mode == "heat" and t < heat + p.hold_delta
        )
        cool_needed = t >= cool + p.start_delta or (
            o.mode == "cool" and t > cool - p.hold_delta
        )
        desired = "heat" if heat_needed else "cool" if cool_needed else None
        if desired:
            if not (o.heat_allowed if desired == "heat" else o.cool_allowed):
                result[z.id] = replace(
                    d, stage="blocked", reason="external_mode_permission"
                )
                continue
            goal = heat if desired == "heat" else cool
            if desired not in o.supported_modes:
                result[z.id] = replace(d, stage="blocked", reason="unsupported_mode")
                continue
            target = hardware_target(z, o, goal, desired, house, now)
            stage = "maintaining" if abs(t - goal) <= p.start_delta else "recovering"
            wanted[z.id] = (
                desired,
                abs(t - goal) * z.priority,
                replace(
                    d,
                    stage=stage,
                    reason="local_temperature_demand",
                    mode=desired,
                    physical_target=target,
                ),
            )
        elif o.mode in ["heat", "cool"]:
            plant = next(x for x in house.plants if x.id == z.plant)
            if now - o.mode_since < plant.minimum_on_s:
                target = hardware_target(
                    z, o, heat if o.mode == "heat" else cool, o.mode, house, now
                )
                result[z.id] = replace(
                    d,
                    stage="settling",
                    reason="minimum_run",
                    mode=o.mode,
                    physical_target=target,
                    next_at=o.mode_since + plant.minimum_on_s,
                )
            else:
                result[z.id] = replace(
                    d, stage="coasting", reason="temperature_satisfied", mode="off"
                )
        elif (high and now - m.high_since >= p.humidity_stable_s) or urgent:
            floor = p.dry_floor_sleep if sleep else p.dry_floor_day
            if not z.allow_dry or not o.dry_allowed or "dry" not in o.supported_modes:
                result[z.id] = replace(
                    d, stage="blocked", reason="no_drying_capability"
                )
                continue
            if t < floor + p.dry_margin:
                result[z.id] = replace(
                    d, stage="blocked", reason="insufficient_thermal_margin"
                )
                continue
            if (
                not snap.outdoor.fresh(now, p.temperature_fresh_s)
                or snap.outdoor.value < p.dry_min_outdoor
            ):
                result[z.id] = replace(d, stage="blocked", reason="dry_outdoor_limit")
                continue
            if now - m.last_attempt < p.dry_cooldown_s or m.attempts >= p.dry_attempts:
                midnight = datetime.combine(
                    snap.now.astimezone(ZoneInfo(house.timezone)).date()
                    + timedelta(days=1),
                    datetime.min.time(),
                    ZoneInfo(house.timezone),
                ).timestamp()
                next_at = max(
                    m.last_attempt + p.dry_cooldown_s,
                    midnight if m.attempts >= p.dry_attempts else 0,
                )
                result[z.id] = replace(
                    d, stage="waiting", reason="dry_budget", next_at=next_at
                )
                continue
            windows = opportunities(prices, snap.now, p.dry_max_s, p.lookahead_s)
            present = next((w for w in windows if abs(w["start"] - now) < 1), None)
            cheaper = next(
                (
                    w
                    for w in windows
                    if w["start"] > now
                    and present
                    and w["average"] <= present["average"] - p.improvement
                ),
                None,
            )
            if not urgent and not present:
                result[z.id] = replace(
                    d, stage="waiting", reason="published_window_missing"
                )
                continue
            if not urgent and cheaper:
                result[z.id] = replace(
                    d,
                    stage="waiting",
                    reason="cheaper_complete_window",
                    next_at=cheaper["start"],
                )
                continue
            wanted[z.id] = (
                "dry",
                z.priority * (10 if urgent else 0.1),
                replace(d, stage="dry_ready", reason="humidity_service", mode="dry"),
            )
        else:
            result[z.id] = d

    # Remove a failed zone before arbitration, so missing local feedback cannot
    # reserve the shared plant against an otherwise healthy zone.
    for zone in house.zones:
        demand = wanted.get(zone.id)
        if (
            demand
            and demand[0] in ("heat", "cool")
            and zone.require_internal_feedback
            and not snap.zones[zone.id].internal.fresh(now, p.internal_fresh_s)
        ):
            wanted.pop(zone.id)
            result[zone.id] = replace(
                demand[2],
                stage="blocked",
                reason="internal_feedback_stale",
                mode=None,
                physical_target=None,
            )
    for plant in house.plants:
        members = [z for z in house.zones if z.plant == plant.id]
        pm = plants.setdefault(plant.id, PlantMemory())
        if p.shared_load_management:
            observations = {z.id: snap.zones[z.id] for z in members}
            goals = {
                z.id: (result.get(z.id) or wanted[z.id][2]).heat_goal
                if observations[z.id].mode == "heat"
                else (result.get(z.id) or wanted[z.id][2]).cool_goal
                for z in members
            }
            measured = snap.plant_power.get(
                plant.id,
                snap.zone_power.get(members[0].id, Reading(None))
                if len(members) == 1
                else Reading(None),
            )
            pm.modulation = observe_shared_load(
                observations,
                goals,
                measured,
                pm.modulation,
                now,
                p,
                plant.minimum_on_s,
                permitted=not snap.paused and snap.occupied is True,
            )
            candidate = pm.modulation.get("r")
            if candidate in wanted and wanted[candidate][2].stage == "holding":
                demand = wanted.pop(candidate)[2]
                result[candidate] = replace(
                    demand,
                    stage="coasting",
                    reason="shared_load_staged_withdrawal",
                    mode="off",
                    physical_target=None,
                )
        active = {
            snap.zones[z.id].mode
            for z in members
            if snap.zones[z.id].mode in ["heat", "cool", "dry"]
        }
        manual = {
            snap.zones[z.id].mode
            for z in members
            if not snap.zones[z.id].automatic
            and snap.zones[z.id].mode in ["heat", "cool", "dry"]
        }
        candidates = [(z, wanted[z.id]) for z in members if z.id in wanted]
        if not candidates:
            continue
        selected = (
            next(iter(manual))
            if len(manual) == 1
            else max(candidates, key=lambda x: x[1][1])[1][0]
        )
        if len(manual) > 1:
            selected = "conflict"
        if plant.shared_mode and "dry" == selected:
            thermal = [x for x in candidates if x[1][0] in ["heat", "cool"]]
            if thermal:
                selected = max(thermal, key=lambda x: x[1][1])[1][0]
        dry_selected = False
        for z, (mode, _, d) in candidates:
            o = snap.zones[z.id]
            reason = None
            until = None
            if o.mode in ["heat", "cool", "dry", "fan_only"] and o.mode != mode:
                result[z.id] = replace(
                    d,
                    stage="reversing"
                    if now - o.mode_since >= plant.minimum_on_s
                    else "settling",
                    reason="stop_before_reversal",
                    mode="off" if now - o.mode_since >= plant.minimum_on_s else None,
                    next_at=o.mode_since + plant.minimum_on_s,
                )
                continue
            if plant.shared_mode and mode != selected:
                reason = "plant_mode_reserved"
            elif plant.shared_mode and any(
                snap.zones[x.id].mode not in ["off", "fan_only", "heat", "cool", "dry"]
                for x in members
                if x.actuator_entity
            ):
                reason = "plant_state_unknown"
            elif plant.shared_mode and active - {mode}:
                reason = "plant_mode_conflict"
            elif mode == "dry" and dry_selected:
                reason = "dry_session_reserved"
            elif o.mode != mode and now - o.mode_since < plant.minimum_off_s:
                reason = "minimum_off"
                until = o.mode_since + plant.minimum_off_s
            elif plant.shared_mode and pm.direction and pm.direction != mode:
                until = max(
                    pm.last_transition + plant.minimum_off_s,
                    pm.since + plant.direction_hold_s,
                    pm.last_flip + plant.reversal_gap_s,
                )
                if now < until:
                    reason = "plant_reversal_wait"
            if not reason and mode == "heat" and pm.direction in ["cool", "dry"]:
                # A minimum off/drain interval is not proof that the coil is dry.
                # Preserve the longer configured plant guards and never fan-purge.
                until = max(until or 0, pm.last_transition + plant.coil_drain_s)
                if now < until:
                    reason = "wet_coil_drain_wait"
            reduction = (
                o.mode == mode
                and d.physical_target is not None
                and o.setpoint is not None
                and (
                    (mode == "heat" and d.physical_target <= o.setpoint)
                    or (mode == "cool" and d.physical_target >= o.setpoint)
                )
            )
            if (
                not reason
                and not reduction
                and (
                    (snap.require_power and not snap.power.fresh(now, p.power_fresh_s))
                    or (
                        snap.power.fresh(now, p.power_fresh_s)
                        and snap.power.value >= p.power_limit
                    )
                )
            ):
                reason = "power_data_or_budget"
            if (
                not reason
                and d.physical_target is not None
                and o.mode == mode
                and o.setpoint is not None
                and abs(o.setpoint - d.physical_target) < o.step / 2
            ):
                if d.reason == "local_temperature_demand":
                    d = replace(d, reason="already_satisfied")
            elif not reason and now - memories[z.id].last_sent < p.command_interval:
                reason = "command_cadence"
                until = memories[z.id].last_sent + p.command_interval
            if reason:
                d = replace(d, stage="waiting", reason=reason, mode=None, next_at=until)
            elif mode == "dry":
                dry_selected = True
            result[z.id] = d
    # A capability-specific feedback requirement restricts thermal emissions,
    # never off-only protection or unaffected zones. Recheck in fresh_plan too.
    for zone in house.zones:
        decision = result[zone.id]
        if (
            zone.require_internal_feedback
            and decision.mode in ("heat", "cool")
            and not snap.zones[zone.id].internal.fresh(now, p.internal_fresh_s)
        ):
            result[zone.id] = replace(
                decision,
                stage="blocked",
                reason="internal_feedback_stale",
                mode=None,
                physical_target=None,
            )
    return result
