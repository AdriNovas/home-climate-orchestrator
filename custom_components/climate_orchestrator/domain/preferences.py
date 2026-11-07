"""Optional product preferences, never equipment protections or authority."""

from dataclasses import dataclass
from math import isfinite

STRATEGIES = ("legacy", "price", "balanced", "comfort")


def checked(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: numeric value required")
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: expected {low}..{high}")
    return value


@dataclass(frozen=True)
class Preferences:
    # None inherits the user's normal-band table, never the current tariff band.
    heat_day: float | None = None
    cool_day: float | None = None
    heat_sleep: float | None = None
    cool_sleep: float | None = None
    heat_flex: float = 0
    cool_flex: float = 0
    minimum_heat: float = 5
    maximum_cool: float = 35
    price_wait_s: int = 2700
    balanced_wait_s: int = 900
    discomfort_degree_minutes: float = 30
    vacancy_heat_delta: float = 0
    vacancy_cool_delta: float = 0

    def __post_init__(self):
        for name in ("heat_day", "cool_day", "heat_sleep", "cool_sleep"):
            if getattr(self, name) is not None:
                checked(getattr(self, name), name, 5, 35)
        for name in (
            "heat_flex",
            "cool_flex",
            "vacancy_heat_delta",
            "vacancy_cool_delta",
        ):
            checked(getattr(self, name), name, 0, 5)
        checked(self.minimum_heat, "minimum_heat", 5, 35)
        checked(self.maximum_cool, "maximum_cool", 5, 35)
        if self.minimum_heat >= self.maximum_cool:
            raise ValueError("Reversed preference limits")
        for name in ("price_wait_s", "balanced_wait_s"):
            value = checked(getattr(self, name), name, 0, 86400)
            if int(value) != value:
                raise ValueError("Wait duration must be whole seconds")
        if self.balanced_wait_s > self.price_wait_s:
            raise ValueError("Balanced waiting cannot exceed price waiting")
        checked(self.discomfort_degree_minutes, "discomfort_degree_minutes", 0, 1440)


@dataclass(frozen=True)
class ActivityBinding:
    entity: str
    kind: str = "motion"
    active_states: tuple[str, ...] = ("on",)
    inactive_states: tuple[str, ...] = ("off",)
    hold_s: int = 900
    vacancy_s: int = 300
    maximum_age_s: int = 0

    def __post_init__(self):
        if not isinstance(self.entity, str) or len(self.entity.split(".")) != 2:
            raise ValueError("Activity requires a native entity binding")
        if self.kind not in ("presence", "motion", "activity"):
            raise ValueError("Unknown activity semantics")
        for name in ("active_states", "inactive_states"):
            states = getattr(self, name)
            if (
                not isinstance(states, (list, tuple))
                or not states
                or any(
                    not isinstance(s, str) or not s or s in ("unknown", "unavailable")
                    for s in states
                )
            ):
                raise ValueError("Explicit available activity states required")
            object.__setattr__(self, name, tuple(states))
        if set(self.active_states) & set(self.inactive_states):
            raise ValueError("Active/inactive states must be disjoint")
        for name, low in (("hold_s", 1), ("vacancy_s", 0), ("maximum_age_s", 0)):
            value = checked(getattr(self, name), name, low, 86400)
            if int(value) != value:
                raise ValueError("Activity durations must be whole seconds")
