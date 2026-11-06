"""Observed thermal continuity and soft setpoints, never actuator acceptance."""

from .models import Memory, Observation, Policy


def observe_stability(
    memory: Memory, observation: Observation, policy: Policy, now: float, valid: bool
) -> bool:
    """Require distinct source reports; repeated evaluations do not create evidence."""
    reading = observation.temperature
    if not valid:
        memory.thermal_stable_since = 0
        memory.thermal_last_report = 0
        memory.thermal_last_seen = 0
        return False
    previous = memory.thermal_last_report
    discontinuity = (
        not memory.thermal_stable_since
        or now < memory.thermal_last_seen
        or now - memory.thermal_last_seen > policy.thermal_sample_gap_s
        or reading.at < previous
        or reading.at - previous > policy.thermal_sample_gap_s
    )
    if discontinuity:
        # Begin at observation time: never backdate stability to an old sample.
        memory.thermal_stable_since = now
        memory.thermal_low = memory.thermal_high = reading.value
    elif reading.at > previous:
        low = min(memory.thermal_low, reading.value)
        high = max(memory.thermal_high, reading.value)
        if high - low > policy.thermal_stability_delta:
            memory.thermal_stable_since = now
            memory.thermal_low = memory.thermal_high = reading.value
        else:
            memory.thermal_low, memory.thermal_high = low, high
    memory.thermal_last_report = reading.at
    memory.thermal_last_seen = now
    return reading.at - memory.thermal_stable_since >= policy.thermal_stable_s


def extreme_price(memory: Memory, policy: Policy, price: float | None) -> bool:
    """Schmitt trigger for a known price, not permission to withdraw comfort."""
    if not policy.extreme_price_enabled or price is None:
        memory.extreme_active = False
    elif price >= policy.extreme_price:
        memory.extreme_active = True
    elif price < policy.extreme_price - policy.extreme_price_hysteresis:
        memory.extreme_active = False
    return memory.extreme_active


def relaxed_target(observation: Observation, target: float, now: float, policy: Policy):
    """A same-direction reduction relative to both the last target and internal sensor.

    This describes thermostat demand only; it never promises a compressor stop,
    electrical power reduction or a manufacturer-specific standby mode.
    """
    o = observation
    if (
        o.setpoint is None
        or not o.minimum <= o.setpoint <= o.maximum
        or not o.internal.fresh(now, policy.internal_fresh_s)
    ):
        return None
    if o.mode == "heat":
        target = min(target, o.setpoint)
        return target if target <= o.internal.value - o.step / 2 else None
    if o.mode == "cool":
        target = max(target, o.setpoint)
        return target if target >= o.internal.value + o.step / 2 else None
    return None
