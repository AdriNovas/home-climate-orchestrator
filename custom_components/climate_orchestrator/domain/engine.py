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
    correction = max(
        -p.correction_limit,
        min(p.correction_limit, zone.bias + (effort if mode == "heat" else -effort)),
    )
    target = goal + correction
    if deficit <= p.hold_delta and obs.internal.fresh(now, p.internal_fresh_s):
        target = (
            min(target, obs.internal.value - 0.5)
            if mode == "heat"
            else max(target, obs.internal.value + 0.5)
        )
    step = obs.step if obs.step > 0 else 0.5
    return max(obs.minimum, min(obs.maximum, round(target / step) * step))


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
            band.heat_sleep if sleep else z.heat_targets.get(band.name, band.heat_day)
        )
        cool = band.cool_sleep if sleep else band.cool_day
        d = Decision(
            z.id,
            "idle",
            "within_band",
            None,
            heat,
            cool,
            band.humidity_start,
            band.humidity_stop,
        )
        temp_ok = o.temperature.fresh(now, p.temperature_fresh_s)
        rh_ok = (
            o.humidity.fresh(now, p.humidity_fresh_s) and 0 < o.humidity.value <= 100
        )
        high = rh_ok and o.humidity.value >= band.humidity_start
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
            )
            recovered = (
                m.low_since > 0
                and now - m.low_since >= p.humidity_recovery_s
                and now - m.dry_start >= p.dry_min_s
            )
            if o.mode == "off" and now >= m.dry_start + 80:
                m.dry_start = 0
                m.dry_until = 0
                m.low_since = 0
            elif stop or recovered:
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
        if not z.enabled:
            result[z.id] = replace(d, stage="paused", reason="zone_disabled")
            continue
        if not temp_ok:
            result[z.id] = replace(d, stage="blocked", reason="temperature_stale")
            continue
        if o.mode == "dry":
            result[z.id] = replace(d, stage="external", reason="unowned_drying")
            continue
        if snap.paused or (sleep and not z.night_allowed):
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
        if snap.occupied is not True:
            result[z.id] = replace(d, stage="waiting", reason="occupancy_unconfirmed")
            continue
        heat_needed = t <= heat - p.start_delta or (
            o.mode == "heat" and t < heat + p.hold_delta
        )
        cool_needed = t >= cool + p.start_delta or (
            o.mode == "cool" and t > cool - p.hold_delta
        )
        desired = "heat" if heat_needed else "cool" if cool_needed else None
        if desired:
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
            if not z.allow_dry or "dry" not in o.supported_modes:
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

    for plant in house.plants:
        members = [z for z in house.zones if z.plant == plant.id]
        pm = plants.setdefault(plant.id, PlantMemory())
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
                if x.climate_entity
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
                d = replace(d, reason="already_satisfied")
            elif not reason and now - memories[z.id].last_sent < p.command_interval:
                reason = "command_cadence"
                until = memories[z.id].last_sent + p.command_interval
            if reason:
                d = replace(d, stage="waiting", reason=reason, mode=None, next_at=until)
            elif mode == "dry":
                dry_selected = True
            result[z.id] = d
    return result
