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
from .strategies import resolve_goals, humidity_opportunity


def dew_point(temperature: float, humidity: float) -> float:
    if not 0 < humidity <= 100:
        raise ValueError("Invalid relative humidity")
    a = log(humidity / 100) + 17.62 * temperature / (243.12 + temperature)
    return 243.12 * a / (17.62 - a)


def sleeping(house: House, snapshot: Snapshot) -> bool:
    """Whether local time lies in a sleep period.

    The evening of a calendar day (Friday and Saturday use the weekend night
    start) owns the hours that spill past midnight, so a night starting after
    00:00 is not cut short or lengthened when the weekday class changes.
    """
    local = snapshot.now.astimezone(ZoneInfo(house.timezone))
    clock = local.hour * 60 + local.minute

    def bounds(day_weekday: int) -> tuple[int, int]:
        weekend = day_weekday >= 5
        return (
            minute(house.weekend_day_start if weekend else house.day_start),
            minute(
                house.weekend_night_start
                if day_weekday in (4, 5)
                else house.night_start
            ),
        )

    start, stop = bounds(local.weekday())
    if start < stop:
        awake = start <= clock < stop
    else:
        awake = clock >= start
    if not awake and clock < start:
        # Spill-over of the previous evening, with that evening's own start.
        previous_start, previous_stop = bounds((local.weekday() - 1) % 7)
        awake = previous_start >= previous_stop and clock < previous_stop
    return not awake


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
    memory: Memory, now: float, floor: float, target: float, maximum_s: int,
    *, start_temperature: float | None = None, dew_target: float | None = None,
) -> None:
    """Explicit intent acceptance hook for a future executor/simulator, never observer adoption."""
    reservation = Memory(dry_start_temperature=start_temperature, dry_dew_target=dew_target)
    memory.dry_active = True
    memory.dry_start = now
    memory.dry_until = now + maximum_s if maximum_s else 0
    memory.dry_floor = floor
    memory.dry_target = target
    memory.last_attempt = now
    memory.attempts += 1
    memory.low_since = 0
    memory.dry_start_temperature = reservation.dry_start_temperature
    memory.dry_dew_target = reservation.dry_dew_target


def dry_reservation_unsafe(zone, temperature, start_temperature, dew_target):
    """Required reservation metadata is never reconstructed from current telemetry."""
    return (
        zone.dry_max_temperature_drop is not None and (
            start_temperature is None
            or temperature < start_temperature - zone.dry_max_temperature_drop
        )
        or zone.dry_dewpoint_completion and dew_target is None
    )


def independent_drying(zone, obs, memory, decision, snap, house, high, rh_ok, prices):
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
        or zone.drying_availability != "always"
        and (
            snap.occupied is not True
            or (sleeping(house, snap) and not zone.night_allowed)
        )
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
        memory.last_attempt + zone.dehumidifier_cooldown_s
        if p.dry_budget_enabled else 0,
    )
    if now < until:
        return replace(decision, stage="waiting", reason="minimum_off", next_at=until)
    if house.strategy != "legacy" and not decision.urgent:
        wait = humidity_opportunity(
            house, zone, snap, prices, memory, (zone.dehumidifier_max_s or zone.dehumidifier_min_s)
        )
        if wait is not None:
            return replace(
                decision,
                stage="waiting",
                reason="cheaper_complete_window",
                next_at=wait,
            )
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
        if z.humidity_basis == "home_max":
            o = replace(o, humidity=snap.home_humidity)
        m = memories.setdefault(z.id, Memory())
        if m.day != day:
            m.day = day
            if p.dry_budget_enabled:
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
        goals = resolve_goals(house, z, o, snap, prices, m, sleep, heat, cool)
        heat, cool = goals.heat, goals.cool
        # The opt-in common floor has no separate start/rearm margin. External
        # configuration remains fail-closed, and no session clock is renewed.
        common_floor = None
        if p.dry_heat_offset is not None:
            common_floor = p.dry_floor_sleep if sleep else p.dry_floor_day
            if z.dry_floor_entity:
                common_floor = (
                    o.dry_floor.value
                    if o.dry_floor.fresh(now, p.temperature_fresh_s)
                    and 10 <= o.dry_floor.value <= 30
                    else None
                )
            if common_floor is not None:
                common_floor = max(common_floor, heat + p.dry_heat_offset)
        d = Decision(
            z.id,
            "idle",
            "within_band",
            None,
            heat,
            cool,
            z.humidity_start_targets.get(band.name, band.humidity_start),
            z.humidity_stop_targets.get(band.name, band.humidity_stop),
            strategy=house.strategy,
            strategy_reason=goals.reason,
            preferred_heat=goals.preferred_heat,
            preferred_cool=goals.preferred_cool,
            activity=o.activity,
        )
        temp_ok = o.temperature.fresh(now, p.temperature_fresh_s)
        thermal_occupied = (
            snap.occupied if o.thermal_occupied is None else o.thermal_occupied
        )
        eligible = (
            o.automatic
            and z.enabled
            and temp_ok
            and not snap.paused
            and o.permitted
            and (not sleep or z.night_allowed)
            and thermal_occupied is True
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
            or (p.humidity_debt_urgency and m.debt_since > 0
                and now - m.debt_since >= p.humidity_deadline_s)
            or (m.severe_since > 0 and now - m.severe_since >= p.severe_stable_s)
        )
        d = replace(d, urgent=urgent)
        if not o.automatic:
            m.dry_active = False
            m.dry_start = 0
            m.dry_until = 0
            m.low_since = 0
            result[z.id] = replace(d, stage="manual", reason="manual_authority")
            continue
        # An explicit owned session has independent maximum/floor exits even paused.
        if m.dry_active or m.dry_until:
            m.low_since = (
                (m.low_since or now)
                if rh_ok and temp_ok and o.humidity.value <= m.dry_target
                and (not z.dry_dewpoint_completion or (
                    m.dry_dew_target is not None
                    and dew_point(o.temperature.value, o.humidity.value) <= m.dry_dew_target
                ))
                else 0
            )
            stop = (
                (m.dry_until > 0 and now >= m.dry_until)
                or not temp_ok
                or not rh_ok
                or dry_reservation_unsafe(z, o.temperature.value,
                                          m.dry_start_temperature, m.dry_dew_target)
                or (p.dry_heat_offset is not None and common_floor is None)
                or o.temperature.value < (common_floor if common_floor is not None else m.dry_floor)
                or (snap.paused and z.dry_pause_action == "stop")
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
            if o.mode in ("heat", "cool", "fan_only") and now >= m.dry_start + 80:
                # The unit left dry without an owned command: the reservation
                # no longer describes reality and must not suppress thermal
                # control or protections. Manual is handled before this point.
                m.dry_active = False
                m.dry_start = 0
                m.dry_until = 0
                m.low_since = 0
            elif o.mode == "off" and now >= m.dry_start + 80:
                if z.independent_drying:
                    m.dry_episode_blocked = True
                m.dry_active = False
                m.dry_start = 0
                m.dry_until = 0
                m.low_since = 0
            elif stop or recovered:
                if z.independent_drying and m.dry_until > 0 and now >= m.dry_until:
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
            independent = independent_drying(
                z, o, m, d, snap, house, high, rh_ok, prices
            )
            if independent.mode == "dry":
                wanted[z.id] = ("dry", z.priority + (10 if urgent else 0), independent)
            else:
                result[z.id] = independent
            continue
        if not z.enabled:
            result[z.id] = replace(d, stage="paused", reason="zone_disabled")
            continue
        mode_permission_lost = (o.mode == "heat" and not o.heat_allowed) or (
            o.mode == "cool" and not o.cool_allowed
        )
        # Explicit stop policy, not a new default or an implicit ownership grant.
        # Revoking a running mode needs neither a valid goal nor fresh feedback.
        # Manual, a global pause and unowned drying keep their existing guards.
        if (
            z.mode_permission_loss_action == "stop"
            and mode_permission_lost
            and not snap.paused
            and o.permitted
            and "off" in o.supported_modes
        ):
            result[z.id] = replace(
                d, stage="protect", reason="mode_permission_lost", mode="off"
            )
            continue
        # Optional, explicit fail-safe for installations whose automatic thermal
        # operation must stop without its reference. Never seize Manual, stop an
        # unowned dry cycle, or turn a global pause into a thermal shutdown.
        feedback_lost = (
            not temp_ok
            or (
                z.require_internal_feedback
                and not o.internal.fresh(now, p.internal_fresh_s)
            )
            or (z.bias_entity and not o.bias.fresh(now, p.temperature_fresh_s))
        )
        if (
            z.feedback_loss_action == "stop"
            and feedback_lost
            and not snap.paused
            and o.permitted
            and o.mode in ["heat", "cool"]
            and "off" in o.supported_modes
        ):
            result[z.id] = replace(
                d, stage="protect", reason="thermal_feedback_lost", mode="off"
            )
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
        if (
            sleep
            and not z.night_allowed
            and not snap.paused
            and o.permitted
            and o.mode in ("heat", "cool")
            and "off" in o.supported_modes
        ):
            # An automatic zone excluded from the sleep period must not keep
            # running unattended: stop it once, never reclaim Manual or pauses.
            result[z.id] = replace(
                d, stage="protect", reason="night_not_allowed", mode="off"
            )
            continue
        if snap.paused or not o.permitted or (sleep and not z.night_allowed):
            result[z.id] = replace(d, stage="paused", reason="pause_or_schedule")
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
        # An ordinary mode veto must not hide an already-observed overshoot.
        if mode_permission_lost:
            result[z.id] = replace(
                d, stage="blocked", reason="external_mode_permission"
            )
            continue
        if thermal_occupied is not True:
            result[z.id] = replace(d, stage="waiting", reason="occupancy_unconfirmed")
            continue
        if goals.until is not None and o.mode == "off":
            result[z.id] = replace(
                d, stage="waiting", reason="cheaper_thermal_window", next_at=goals.until
            )
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
            if z.dry_floor_entity:
                if not o.dry_floor.fresh(now, p.temperature_fresh_s) or not (
                    10 <= o.dry_floor.value <= 30
                ):
                    result[z.id] = replace(
                        d, stage="blocked", reason="dry_floor_missing"
                    )
                    continue
                floor = o.dry_floor.value
            if not z.allow_dry or not o.dry_allowed or "dry" not in o.supported_modes:
                result[z.id] = replace(
                    d, stage="blocked", reason="no_drying_capability"
                )
                continue
            if p.dry_heat_offset is not None:
                if common_floor is None:
                    result[z.id] = replace(d, stage="blocked", reason="dry_floor_missing")
                    continue
                floor = common_floor
            if t < floor + (p.dry_margin if p.dry_heat_offset is None else 0):
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
            if p.dry_budget_enabled and (
                now - m.last_attempt < p.dry_cooldown_s
                or m.attempts >= p.dry_attempts
            ):
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
            windows = opportunities(prices, snap.now, (p.dry_max_s or p.dry_min_s), p.lookahead_s)
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
            if house.strategy != "legacy":
                # Humidity is independent of thermal occupancy concessions.
                # Missing prices only removes economic waiting, never service.
                wait = humidity_opportunity(house, z, snap, prices, m, (p.dry_max_s or p.dry_min_s))
                cheaper = {"start": wait} if wait is not None else None
                present = present or {"start": now}
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
                replace(
                    d,
                    stage="dry_ready",
                    reason="humidity_service",
                    mode="dry",
                    session_floor=floor,
                ),
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
            elif mode == "dry" and dry_selected and not p.dry_concurrent:
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
        if p.dry_concurrent:
            # Apply the band after all independent eligibility checks. A head
            # waiting for OFF/reversal/power cannot reserve healthy heads' band.
            eligible = [
                z for z in members
                if z.id in result and result[z.id].mode == "dry"
                and (snap.home_humidity if z.humidity_basis == "home_max" else snap.zones[z.id].humidity).fresh(now, p.humidity_fresh_s)
            ]
            reference = max(
                ((snap.home_humidity if z.humidity_basis == "home_max" else snap.zones[z.id].humidity).value for z in eligible), default=None
            )
            for z in eligible:
                d = result[z.id]
                humidity = snap.home_humidity if z.humidity_basis == "home_max" else snap.zones[z.id].humidity
                if (
                    d.stage != "drying" and reference is not None
                    and humidity.value < reference - p.dry_humidity_band
                ):
                    result[z.id] = replace(
                        d, stage="waiting", reason="dry_humidity_band",
                        mode=None, next_at=None,
                    )
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
    for zone in house.zones:
        obs, decision = snap.zones[zone.id], result[zone.id]
        # A display-only update is not a start or a stop. It requires an explicit
        # source and already-observed OFF, and never overrides a thermal demand.
        # Missing display data cannot become a fallback thermal policy.
        if (
            zone.off_goal_entity
            and not zone.independent_drying
            and zone.enabled
            and obs.automatic
            and obs.permitted
            and not snap.paused
            and obs.mode == "off"
            and "off" in obs.supported_modes
            and decision.mode is None
            and obs.off_goal.fresh(now, p.temperature_fresh_s)
            and obs.minimum <= obs.off_goal.value <= obs.maximum
        ):
            target = (
                obs.minimum
                + round((obs.off_goal.value - obs.minimum) / obs.step) * obs.step
            )
            result[zone.id] = replace(
                decision,
                stage="off_display",
                reason="external_off_display_goal",
                mode="off",
                physical_target=max(obs.minimum, min(obs.maximum, target)),
                target_only=True,
            )
    return result
