"""Continuous thermostat demand and measured shared-load feedback, with no I/O.

A mode is not compressor work. A shared meter is not per-head consumption.
The plant loop therefore observes a complete configuration and makes at most
one bounded withdrawal proposal, never a proportional allocation of watts.
"""

from .provenance import number


def soft_correction(deficit, bias, mode, effort, trim, policy):
    """Demand uses the room reference; only relaxation may follow the internal sensor."""
    boost = (
        min(policy.boost_limit, max(0, deficit * policy.proportional_gain))
        if deficit > 0.3
        else 0
    )
    boost += max(0, min(2.5, effort)) if deficit > 0.3 else 0
    relax = (
        min(
            policy.relaxation_limit, 0.5 + 2 * max(0, -deficit) + max(0, min(2.5, trim))
        )
        if deficit <= 0.3
        else 0
    )
    return max(
        -policy.correction_limit,
        min(
            policy.correction_limit,
            bias + (boost - relax if mode == "heat" else relax - boost),
        ),
    )


def observe_room(o, goal, power, previous, now, policy, permitted):
    """Bounded own feedback for installations without an external response source.

    Demand/effort follows distinct environmental reports, not repeated planner
    ticks. Aggregate power only corroborates continued drift near the goal;
    it never estimates the watts of this head. External response bindings keep
    their existing owner and are never rewritten by this observer.
    """
    previous = previous if isinstance(previous, dict) else {}
    valid = (
        permitted
        and o.automatic
        and o.permitted
        and o.goals_valid
        and o.mode in ("heat", "cool")
        and (o.heat_allowed if o.mode == "heat" else o.cool_allowed)
        and o.temperature.fresh(now, policy.temperature_fresh_s)
        and o.internal.fresh(now, policy.internal_fresh_s)
    )
    if not valid:
        return {}
    elapsed = now - previous.get("at", 0) if number(previous.get("at")) else 1e20
    compatible = (
        0 <= elapsed <= 660
        and previous.get("m") == o.mode
        and previous.get("g") == goal
    )
    if compatible and elapsed < 240:
        return previous
    paired = (
        compatible
        and number(previous.get("t"))
        and number(previous.get("qa"))
        and o.temperature.at > previous["qa"]
    )
    deficit = (
        goal - o.temperature.value if o.mode == "heat" else o.temperature.value - goal
    )
    progress = (
        (
            (o.temperature.value - previous["t"])
            if o.mode == "heat"
            else (previous["t"] - o.temperature.value)
        )
        if paired
        else 0
    )
    stalls = (
        min(3, int(previous.get("s", 0)) + 1)
        if paired and deficit > 0.3 and progress < 0.1
        else 0
    )
    effort = previous.get("b", 0) if compatible and number(previous.get("b")) else 0
    if deficit <= 0.3 or not paired:
        effort = 0
    elif stalls >= 2:
        effort = min(2.5, effort + 0.5)
    elif progress >= 0.1:
        effort = max(0, effort - 0.5)
    trim = (
        max(0, min(2.5, previous.get("h", 0)))
        if compatible and number(previous.get("h")) and deficit <= 0.3
        else 0
    )
    if (
        paired
        and deficit <= 0.2
        and progress >= 0.1
        and power.fresh(now, policy.power_fresh_s)
        and power.value > policy.shared_load_idle_w
    ):
        trim = min(2.5, trim + 0.5)
    return {
        "at": now,
        "m": o.mode,
        "g": goal,
        "t": o.temperature.value,
        "qa": o.temperature.at,
        "s": stalls,
        "b": effort,
        "h": trim,
    }


def observe_shared_load(
    observations, goals, power, previous, now, policy, minimum_on_s, permitted=True
):
    """Observe before changing service; return a persistent, lease-bounded intent.

    Baselines are whole-plant observations indexed by active-head count, not
    additive head estimates. Cheap hours can increase the independent comfort
    goals; real demand always cancels this optional coast proposal. A failed
    proposal still consumes its per-head retry budget. Repeated evaluations,
    stale meters, unavailable heads, Manual and changing goals cannot prove a
    high-load episode. A restart with a long sample gap starts evidence anew.
    """
    previous = previous if isinstance(previous, dict) else {}
    valid_clock = number(previous.get("at")) and 0 <= now - previous["at"] <= 660
    old = previous if valid_clock else {}
    cut_times = (
        {
            k: v
            for k, v in previous.get("c", {}).items()
            if k in observations and number(v) and 0 <= v <= now
        }
        if isinstance(previous.get("c", {}), dict)
        else {}
    )
    baselines = (
        {
            k: v
            for k, v in previous.get("b", {}).items()
            if isinstance(k, str) and number(v) and 0 <= v <= policy.shared_load_high_w
        }
        if isinstance(previous.get("b", {}), dict)
        else {}
    )
    active = {k: o for k, o in observations.items() if o.mode in ("heat", "cool")}
    signature = [[k, o.mode, goals.get(k)] for k, o in sorted(active.items())]
    known = all(
        o.mode in ("off", "fan_only", "heat", "cool") for o in observations.values()
    )
    direction = {o.mode for o in active.values()}
    safe = bool(
        permitted
        and known
        and active
        and len(direction) == 1
        and power.fresh(now, policy.power_fresh_s)
        and power.value >= 0
    )
    temperatures = {}
    excesses = {}
    for key, o in active.items():
        goal = goals.get(key)
        if not (
            number(goal)
            and o.automatic
            and o.permitted
            and o.goals_valid
            and (o.heat_allowed if o.mode == "heat" else o.cool_allowed)
            and o.temperature.fresh(now, policy.temperature_fresh_s)
            and o.internal.fresh(now, policy.internal_fresh_s)
            and o.setpoint is not None
        ):
            safe = False
            continue
        excess = (
            o.temperature.value - goal
            if o.mode == "heat"
            else goal - o.temperature.value
        )
        temperatures[key] = o.temperature.value
        excesses[key] = excess
        # Do not withdraw a room that still needs heat/cooling, even at high W.
        safe = (
            safe
            and 0 <= excess < policy.overshoot_delta
            and (
                o.setpoint <= o.internal.value - o.step / 2
                if o.mode == "heat"
                else o.setpoint >= o.internal.value + o.step / 2
            )
        )
    same = safe and old.get("k") == signature
    before_t = old.get("t", {})
    stable = (
        same
        and isinstance(before_t, dict)
        and all(
            number(before_t.get(k))
            and abs(t - before_t[k]) <= policy.thermal_stability_delta
            for k, t in temperatures.items()
        )
    )
    # The previous lease remains actionable only against the identical snapshot
    # class and fresh guard data. Planning twice must not consume two budgets.
    if valid_clock and now - old["at"] < 240:
        result = dict(old)
        if not (safe and same and now - old["at"] <= 90):
            result["r"] = None
        return result
    count = str(len(active))
    if safe and power.value <= policy.shared_load_high_w:
        baselines[count] = round(
            0.8 * baselines.get(count, power.value) + 0.2 * power.value
        )
    high = max(
        policy.shared_load_high_w, 1.5 * baselines.get(count, policy.shared_load_idle_w)
    )
    rising_load = safe and stable and power.value > high
    since = (
        old.get("s", 0)
        if rising_load and number(old.get("s")) and 0 < old["s"] <= now
        else 0
    )
    if safe and power.value > high and not since:
        since = now
    # Source reports, not an elapsed wall clock alone, must cross the start.
    new_reports = since > 0 and all(o.temperature.at > since for o in active.values())
    candidates = [
        k
        for k, o in active.items()
        if safe
        and now - o.mode_since >= minimum_on_s
        and now - cut_times.get(k, 0) >= policy.shared_load_retry_s
    ]
    candidate = None
    if (
        rising_load
        and since
        and now - since >= policy.shared_load_observe_s
        and new_reports
        and candidates
    ):
        candidate = max(candidates, key=lambda k: (excesses[k], k))
        cut_times[candidate] = now
        since = now  # wait for the effect before even proposing a second head
    if not safe or power.value <= high:
        since = 0
    delta = None
    prior_candidate = old.get("r")
    if (
        isinstance(prior_candidate, str)
        and prior_candidate in observations
        and observations[prior_candidate].mode == "off"
        and number(old.get("w"))
        and power.fresh(now, policy.power_fresh_s)
    ):
        delta = round(
            power.value - old["w"]
        )  # observed aggregate delta, not causal head power
    return {
        "v": 1,
        "at": now,
        "s": since,
        "k": signature,
        "t": temperatures,
        "r": candidate,
        "c": cut_times,
        "b": baselines,
        "w": round(power.value) if power.fresh(now, policy.power_fresh_s) else None,
        "delta": delta,
    }
