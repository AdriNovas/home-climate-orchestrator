"""Measured supply protection; missing/stale data cannot release a latched cut."""

from dataclasses import dataclass
from .models import bounded


@dataclass(frozen=True)
class SupplyProtection:
    critical_w: float = 7000
    critical_s: int = 720
    release_w: float = 5800
    release_s: int = 120

    def __post_init__(self):
        for key in ["critical_w", "release_w"]:
            object.__setattr__(self, key, bounded(getattr(self, key), key, 100, 100000))
        for key in ["critical_s", "release_s"]:
            object.__setattr__(
                self, key, int(bounded(getattr(self, key), key, 1, 3600))
            )
        if self.release_w >= self.critical_w:
            raise ValueError("Supply protection needs positive release hysteresis")


def supply_cut(memory, reading, now, maximum_age, policy, active=False, external=None):
    if external is True:
        memory.clear()
        return True
    if external is False and reading is None:
        return False
    if reading is None or not reading.fresh(now, maximum_age) or reading.value < 0:
        memory.clear()
        return active
    last = memory.get("last", 0)
    if last > reading.at or last and reading.at - last > maximum_age:
        memory.clear()
    if reading.at != memory.get("last"):
        memory["last"] = reading.at
        high, low = (
            reading.value >= policy.critical_w,
            reading.value <= policy.release_w,
        )
        memory["high"] = memory.get("high", reading.at) if high else 0
        memory["low"] = memory.get("low", reading.at) if low else 0
        if high and not memory["high"]:
            memory["high"] = reading.at
        if low and not memory["low"]:
            memory["low"] = reading.at
    if memory.get("high") and reading.at - memory["high"] >= policy.critical_s:
        return True
    if (
        active
        and memory.get("low")
        and reading.at - memory["low"] >= policy.release_s
        and external is not None
    ):
        return False
    return active
