"""Tri-state room evidence. A quiet PIR is not proof of vacancy."""

from dataclasses import dataclass, field
from .preferences import ActivityBinding


@dataclass(frozen=True)
class ActivitySample:
    state: str | None
    changed_at: float = 0
    received_at: float = 0


@dataclass(frozen=True)
class ActivityResult:
    state: str = "unknown"
    reason: str = "not_configured"
    next_at: float | None = None
    last_positive: dict[str, float] = field(default_factory=dict)


def resolve_activity(
    bindings: tuple[ActivityBinding, ...], samples, now, previous=None
):
    """OR positive evidence; vacancy needs every configured presence source off.

    Motion/activity hold is based on the positive transition, not polling or a
    cache report. Persistent evidence expires at the original absolute deadline.
    Unknown/lost presence never grants a vacancy setback. No I/O or global clock.
    """
    if not bindings:
        return ActivityResult()
    saved = previous or {}
    positive = {}
    untils = []
    occupied = False
    presence_count = 0
    vacant_count = 0
    vacancy_pending = False
    for binding in bindings:
        sample = samples.get(binding.entity, ActivitySample(None))
        last = saved.get(binding.entity, 0)
        if not isinstance(last, (int, float)) or not 0 <= last <= now:
            last = 0
        valid = sample.state not in (None, "unknown", "unavailable")
        valid = (
            valid and 0 <= sample.changed_at <= now and 0 <= sample.received_at <= now
        )
        if binding.maximum_age_s:
            valid = valid and now - sample.received_at <= binding.maximum_age_s
        if valid and sample.state in binding.active_states:
            last = max(last, sample.changed_at)
            if binding.kind == "presence":
                occupied = True
        if last > 0:
            positive[binding.entity] = last
            until = last + binding.hold_s
            if now < until:
                occupied = True
                untils.append(until)
        if binding.kind == "presence":
            presence_count += 1
            if valid and sample.state in binding.inactive_states:
                at = sample.changed_at + binding.vacancy_s
                if now >= at:
                    vacant_count += 1
                else:
                    vacancy_pending = True
                    untils.append(at)
    state = (
        "occupied"
        if occupied
        else "vacant"
        if presence_count and vacant_count == presence_count
        else "unknown"
    )
    reason = (
        "positive_evidence"
        if occupied
        else "confirmed_vacancy"
        if state == "vacant"
        else "vacancy_delay"
        if vacancy_pending
        else "no_positive_evidence"
    )
    return ActivityResult(state, reason, min(untils) if untils else None, positive)
