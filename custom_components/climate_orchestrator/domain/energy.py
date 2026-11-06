"""Explicit meter scopes and normalized measurements, never allocated estimates."""

from dataclasses import dataclass
from .models import bounded, finite


@dataclass(frozen=True)
class Meter:
    id: str
    name: str
    scope: str = "house"
    target: str = ""
    power_entity: str | None = None
    energy_entity: str | None = None
    fresh_s: int = 120
    energy_fresh_s: int = 86400
    negative_power_tolerance_w: float = 0
    include_in_system: bool = True

    def __post_init__(self):
        if type(self.include_in_system) is not bool:
            raise ValueError("Explicit system accounting selection required")
        if not self.id or not self.name or self.scope not in ["house", "plant", "zone"]:
            raise ValueError("Meter identity and scope required")
        if (self.scope == "house") != (not self.target):
            raise ValueError("Only a plant/zone meter needs a target")
        if not self.power_entity and not self.energy_entity:
            raise ValueError("Assign at least one measured source")
        object.__setattr__(
            self, "fresh_s", int(bounded(self.fresh_s, "meter freshness", 10, 86400))
        )
        object.__setattr__(
            self,
            "energy_fresh_s",
            int(bounded(self.energy_fresh_s, "energy freshness", 10, 604800)),
        )
        object.__setattr__(
            self,
            "negative_power_tolerance_w",
            bounded(
                self.negative_power_tolerance_w, "negative power noise tolerance", 0, 20
            ),
        )
        if self.negative_power_tolerance_w and not self.power_entity:
            raise ValueError("Negative power noise tolerance requires a power source")


def normalize(value, unit, kind, *, negative_power_tolerance_w=0):
    value = finite(value, kind)
    factors = {
        "power": {"W": 1, "kW": 1000},
        "energy": {"Wh": 0.001, "kWh": 1, "MWh": 1000},
    }
    if kind not in factors or unit not in factors[kind]:
        raise ValueError("Unsupported or ambiguous electrical unit")
    value *= factors[kind][unit]
    if kind == "power":
        tolerance = bounded(
            negative_power_tolerance_w, "negative power noise tolerance", 0, 20
        )
        if -tolerance <= value < 0:
            return 0.0
    if value < 0:
        raise ValueError(
            "Consumption source must be non-negative; use import, not net power"
        )
    return value


def meters_from_profile(profile, house):
    meters = tuple(Meter(**row) for row in profile.get("meters", []))
    if len({m.id for m in meters}) != len(meters):
        raise ValueError("Duplicate meter identity")
    bindings = []
    for m in meters:
        if m.scope == "plant" and m.target not in {p.id for p in house.plants}:
            raise ValueError("Unknown meter plant")
        if m.scope == "zone" and m.target not in {z.id for z in house.zones}:
            raise ValueError("Unknown meter zone")
        bindings.extend(x for x in [m.power_entity, m.energy_entity] if x)
    if len(set(bindings)) != len(bindings):
        raise ValueError("A shared meter must have one scope, not several allocations")
    included = [m for m in meters if m.include_in_system]
    for index, left in enumerate(included):
        for right in included[index + 1 :]:
            if (
                left.scope == "house"
                or right.scope == "house"
                or (left.scope == right.scope and left.target == right.target)
            ):
                raise ValueError(
                    "Overlapping system meters would double-count consumption"
                )
            parent, child = (left, right) if left.scope == "plant" else (right, left)
            if (
                parent.scope == "plant"
                and child.scope == "zone"
                and next(z for z in house.zones if z.id == child.target).plant
                == parent.target
            ):
                raise ValueError("Do not sum a plant with its nested zone meter")
    return meters
