"""Validated configuration and immutable observations for the planning engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

MODES = {"off", "heat", "cool", "dry", "fan_only"}


def finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: boolean is not a measurement")
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name}: numeric value required") from err
    if not isfinite(number):
        raise ValueError(f"{name}: finite value required")
    return number


def bounded(value: Any, name: str, low: float, high: float) -> float:
    number = finite(value, name)
    if not low <= number <= high:
        raise ValueError(f"{name}: expected {low}..{high}")
    return number


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value


@dataclass(frozen=True)
class PriceInterval:
    start: datetime
    end: datetime
    price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", aware(self.start).astimezone(timezone.utc))
        object.__setattr__(self, "end", aware(self.end).astimezone(timezone.utc))
        if self.end <= self.start:
            raise ValueError("Empty or reversed price interval")
        object.__setattr__(self, "price", finite(self.price, "price"))


@dataclass(frozen=True)
class PriceBand:
    name: str
    upper: float | None
    heat_day: float
    heat_sleep: float
    cool_day: float
    cool_sleep: float
    humidity_start: float = 65
    humidity_stop: float = 60

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Price band name is required")
        if self.upper is not None:
            object.__setattr__(self, "upper", finite(self.upper, "price boundary"))
        for name in ["heat_day", "heat_sleep", "cool_day", "cool_sleep"]:
            object.__setattr__(self, name, bounded(getattr(self, name), name, 5, 35))
        if self.heat_day >= self.cool_day or self.heat_sleep >= self.cool_sleep:
            raise ValueError("Heating target must remain below cooling target")
        object.__setattr__(
            self, "humidity_stop", bounded(self.humidity_stop, "humidity_stop", 30, 70)
        )
        object.__setattr__(
            self,
            "humidity_start",
            bounded(self.humidity_start, "humidity_start", 35, 90),
        )
        if self.humidity_stop >= self.humidity_start:
            raise ValueError("Humidity hysteresis must be positive")


def default_bands() -> tuple[PriceBand, ...]:
    return tuple(
        PriceBand(*row)
        for row in [
            ("negative", 0, 21, 19.5, 24, 25),
            ("very_low", 0.05, 21, 19.5, 24, 25),
            ("low", 0.10, 20.5, 19, 25, 26),
            ("normal", 0.20, 19.5, 18.5, 26, 27),
            ("high", 0.30, 19, 18, 27, 28),
            ("very_high", None, 18.5, 18, 28, 28),
        ]
    )


@dataclass(frozen=True)
class Policy:
    bands: tuple[PriceBand, ...] = field(default_factory=default_bands)
    start_delta: float = 0.5
    hold_delta: float = 0.2
    overshoot_delta: float = 0.5
    proportional_gain: float = 0.7
    boost_limit: float = 1
    correction_limit: float = 6
    command_interval: int = 300
    temperature_fresh_s: int = 7200
    humidity_fresh_s: int = 7200
    internal_fresh_s: int = 600
    dry_floor_day: float = 20
    dry_floor_sleep: float = 19
    dry_margin: float = 1
    dry_min_outdoor: float = 10
    dry_min_s: int = 1200
    dry_max_s: int = 1800
    dry_cooldown_s: int = 14400
    dry_attempts: int = 2
    humidity_stable_s: int = 900
    humidity_recovery_s: int = 600
    humidity_deadline_s: int = 14400
    service_humidity: float = 65
    severe_humidity: float = 80
    severe_stable_s: int = 900
    urgent_humidity: float = 75
    urgent_stable_s: int = 1800
    lookahead_s: int = 5400
    improvement: float = 0.04
    power_limit: float = 6000
    power_fresh_s: int = 120
    modulated_hold_s: int = 0
    continuous_hold: bool = False
    shared_load_management: bool = False
    relaxation_limit: float = 3.5
    shared_load_idle_w: float = 150
    shared_load_high_w: float = 250
    shared_load_observe_s: int = 1200
    shared_load_retry_s: int = 7200
    extreme_price_enabled: bool = False
    extreme_price: float = 0.30
    extreme_price_hysteresis: float = 0.02
    thermal_stable_s: int = 900
    thermal_stability_delta: float = 0.3
    thermal_sample_gap_s: int = 1200

    def __post_init__(self) -> None:
        for name in ["continuous_hold", "shared_load_management"]:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        for name, low, high in [
            ("relaxation_limit", 0.5, 6),
            ("shared_load_idle_w", 0, 5000),
            ("shared_load_high_w", 1, 20000),
            ("shared_load_observe_s", 600, 86400),
            ("shared_load_retry_s", 1200, 86400),
        ]:
            object.__setattr__(
                self, name, bounded(getattr(self, name), name, low, high)
            )
        if self.shared_load_idle_w >= self.shared_load_high_w:
            raise ValueError("Shared-load high threshold must exceed idle reference")
        if self.shared_load_management and not self.continuous_hold:
            raise ValueError("Shared-load management requires continuous holding")
        if type(self.extreme_price_enabled) is not bool:
            raise ValueError("extreme_price_enabled must be a boolean")
        object.__setattr__(
            self,
            "modulated_hold_s",
            int(bounded(self.modulated_hold_s, "modulated_hold_s", 0, 7200)),
        )
        for name, low, high in [
            ("extreme_price", 0.01, 10),
            ("extreme_price_hysteresis", 0, 10),
            ("thermal_stability_delta", 0.01, 2),
        ]:
            object.__setattr__(
                self, name, bounded(getattr(self, name), name, low, high)
            )
        if self.extreme_price_hysteresis >= self.extreme_price:
            raise ValueError("Price exit hysteresis must be below its entry threshold")
        if not self.bands or self.bands[-1].upper is not None:
            raise ValueError("Last price band must be unbounded")
        limits = [b.upper for b in self.bands[:-1]]
        if any(x is None for x in limits) or limits != sorted(set(limits)):
            raise ValueError("Price boundaries must be strictly increasing")
        if len({b.name for b in self.bands}) != len(self.bands):
            raise ValueError("Duplicate price band names")
        for name in [
            "start_delta",
            "hold_delta",
            "overshoot_delta",
            "proportional_gain",
            "boost_limit",
            "correction_limit",
            "dry_margin",
            "improvement",
        ]:
            object.__setattr__(self, name, bounded(getattr(self, name), name, 0, 10))
        if not 0 < self.hold_delta < self.start_delta <= self.overshoot_delta + 1:
            raise ValueError("Invalid start/hold hysteresis")
        if self.overshoot_delta <= self.hold_delta:
            raise ValueError("Overshoot threshold must exceed hold tolerance")
        for name in [
            "command_interval",
            "temperature_fresh_s",
            "humidity_fresh_s",
            "internal_fresh_s",
            "dry_min_s",
            "dry_max_s",
            "dry_cooldown_s",
            "dry_attempts",
            "humidity_stable_s",
            "humidity_recovery_s",
            "humidity_deadline_s",
            "urgent_stable_s",
            "severe_stable_s",
            "lookahead_s",
            "power_fresh_s",
            "thermal_stable_s",
            "thermal_sample_gap_s",
        ]:
            object.__setattr__(
                self, name, int(bounded(getattr(self, name), name, 1, 86400))
            )
        if self.dry_max_s < self.dry_min_s:
            raise ValueError("Maximum drying time is below minimum")
        for name, lo, hi in [
            ("power_limit", 100, 100000),
            ("dry_floor_day", 10, 30),
            ("dry_floor_sleep", 10, 30),
            ("dry_min_outdoor", -20, 35),
            ("urgent_humidity", 60, 95),
        ]:
            object.__setattr__(self, name, bounded(getattr(self, name), name, lo, hi))
        object.__setattr__(
            self,
            "service_humidity",
            bounded(self.service_humidity, "service_humidity", 50, 75),
        )
        object.__setattr__(
            self,
            "severe_humidity",
            bounded(self.severe_humidity, "severe_humidity", 70, 95),
        )

    def band(self, price: float | None) -> PriceBand | None:
        if price is None:
            return None
        price = finite(price, "price")
        return next(b for b in self.bands if b.upper is None or price < b.upper)


@dataclass(frozen=True)
class Plant:
    id: str
    name: str
    shared_mode: bool = True
    minimum_off_s: int = 1200
    minimum_on_s: int = 1200
    direction_hold_s: int = 3600
    reversal_gap_s: int = 7200
    coil_drain_s: int = 300

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("Plant identity required")
        for name in [
            "minimum_off_s",
            "minimum_on_s",
            "direction_hold_s",
            "reversal_gap_s",
            "coil_drain_s",
        ]:
            object.__setattr__(
                self, name, int(bounded(getattr(self, name), name, 0, 86400))
            )


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    plant: str
    temperature_entity: str
    climate_entity: str | None = None
    humidity_entity: str | None = None
    authority_entity: str | None = None
    area: str | None = None
    labels: tuple[str, ...] = ()
    priority: float = 1
    bias: float = 0
    allow_dry: bool = False
    night_allowed: bool = True
    enabled: bool = True
    heat_targets: dict[str, float] = field(default_factory=dict)
    authority_states: tuple[str, ...] = ("on",)
    heat_goal_entity: str | None = None
    cool_goal_entity: str | None = None
    bias_entity: str | None = None
    internal_entity: str | None = None
    permission_entity: str | None = None
    heat_permission_entity: str | None = None
    cool_permission_entity: str | None = None
    dry_permission_entity: str | None = None
    response_entity: str | None = None
    expected_ledger_entity: str | None = None
    critical_ledger_entity: str | None = None
    require_internal_feedback: bool = False
    cool_targets: dict[str, float] = field(default_factory=dict)
    heat_sleep_targets: dict[str, float] = field(default_factory=dict)
    cool_sleep_targets: dict[str, float] = field(default_factory=dict)
    humidity_start_targets: dict[str, float] = field(default_factory=dict)
    humidity_stop_targets: dict[str, float] = field(default_factory=dict)
    humidifier_entity: str | None = None
    dehumidifier_min_s: int = 600
    dehumidifier_max_s: int = 5400
    dehumidifier_cooldown_s: int = 1200
    dehumidifier_min_temperature: float = 10
    dehumidifier_max_temperature: float = 32
    feedback_loss_action: str = "hold"
    off_goal_entity: str | None = None
    mode_permission_loss_action: str = "hold"
    thermal_presence_entity: str | None = None

    @property
    def actuator_entity(self):
        return self.humidifier_entity or self.climate_entity

    @property
    def independent_drying(self):
        return self.humidifier_entity is not None

    def __post_init__(self) -> None:
        if not all([self.id, self.name, self.plant, self.temperature_entity]):
            raise ValueError("Zone identity, plant and temperature source required")
        object.__setattr__(self, "bias", bounded(self.bias, "bias", -4, 4))
        object.__setattr__(
            self, "priority", bounded(self.priority, "priority", 0.1, 10)
        )
        for table in [
            self.heat_targets,
            self.cool_targets,
            self.heat_sleep_targets,
            self.cool_sleep_targets,
        ]:
            for value in table.values():
                bounded(value, "zone temperature target", 5, 35)
        for table, low, high in [
            (self.humidity_start_targets, 35, 90),
            (self.humidity_stop_targets, 30, 70),
        ]:
            for value in table.values():
                bounded(value, "zone humidity target", low, high)
        if self.climate_entity and self.humidifier_entity:
            raise ValueError("One actuator per regulation zone")
        if self.feedback_loss_action not in ["hold", "stop"]:
            raise ValueError("Unknown feedback-loss action")
        if self.mode_permission_loss_action not in ["hold", "stop"]:
            raise ValueError("Unknown mode-permission-loss action")
        if self.humidifier_entity and (
            self.off_goal_entity
            or self.feedback_loss_action != "hold"
            or self.mode_permission_loss_action != "hold"
            or self.thermal_presence_entity
        ):
            raise ValueError(
                "Thermal feedback/display/permission settings require a climate actuator"
            )
        if self.humidifier_entity and not self.humidity_entity:
            raise ValueError("Independent drying requires an external humidity sensor")
        for name in [
            "dehumidifier_min_s",
            "dehumidifier_max_s",
            "dehumidifier_cooldown_s",
        ]:
            object.__setattr__(
                self, name, int(bounded(getattr(self, name), name, 180, 86400))
            )
        if self.dehumidifier_max_s < self.dehumidifier_min_s:
            raise ValueError("Drying maximum must cover minimum run")
        for name in ["dehumidifier_min_temperature", "dehumidifier_max_temperature"]:
            object.__setattr__(self, name, bounded(getattr(self, name), name, 0, 40))
        if self.dehumidifier_min_temperature >= self.dehumidifier_max_temperature:
            raise ValueError("Invalid dehumidifier working temperature range")
        if not self.authority_states or any(
            not isinstance(x, str) or not x or x in ["unknown", "unavailable"]
            for x in self.authority_states
        ):
            raise ValueError("Explicit available automatic-authority states required")
        object.__setattr__(self, "authority_states", tuple(self.authority_states))
        if type(self.require_internal_feedback) is not bool:
            raise ValueError("require_internal_feedback must be boolean")


@dataclass(frozen=True)
class House:
    name: str
    timezone: str
    plants: tuple[Plant, ...]
    zones: tuple[Zone, ...]
    policy: Policy = field(default_factory=Policy)
    day_start: str = "07:00"
    night_start: str = "22:00"
    weekend_day_start: str = "09:00"
    weekend_night_start: str = "23:00"

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if not self.name or not self.plants or not self.zones:
            raise ValueError("House, plant and zone required")
        ids = [p.id for p in self.plants]
        if len(ids) != len(set(ids)) or len({z.id for z in self.zones}) != len(
            self.zones
        ):
            raise ValueError("Duplicate IDs")
        bindings = [z.actuator_entity for z in self.zones if z.actuator_entity]
        if len(bindings) != len(set(bindings)):
            raise ValueError("Actuator assigned to several zones")
        bands = {b.name for b in self.policy.bands}
        for zone in self.zones:
            if zone.plant not in ids or any(
                not set(table) <= bands
                for table in [
                    zone.heat_targets,
                    zone.cool_targets,
                    zone.heat_sleep_targets,
                    zone.cool_sleep_targets,
                    zone.humidity_start_targets,
                    zone.humidity_stop_targets,
                ]
            ):
                raise ValueError("Unknown plant or price band")
            if zone.independent_drying and (
                next(p for p in self.plants if p.id == zone.plant).shared_mode
                or sum(z.plant == zone.plant for z in self.zones) != 1
            ):
                raise ValueError(
                    "A standalone dehumidifier needs its own independent plant"
                )
            for band in self.policy.bands:
                if zone.humidity_stop_targets.get(
                    band.name, band.humidity_stop
                ) >= zone.humidity_start_targets.get(band.name, band.humidity_start):
                    raise ValueError("Zone humidity stop must be below start")
                if zone.heat_targets.get(
                    band.name, band.heat_day
                ) >= zone.cool_targets.get(
                    band.name, band.cool_day
                ) or zone.heat_sleep_targets.get(
                    band.name, band.heat_sleep
                ) >= zone.cool_sleep_targets.get(band.name, band.cool_sleep):
                    raise ValueError(
                        "Zone heating target conflicts with cooling target"
                    )
        for name in [
            "day_start",
            "night_start",
            "weekend_day_start",
            "weekend_night_start",
        ]:
            minute(getattr(self, name))


def minute(clock: str) -> int:
    parts = clock.split(":")
    if len(parts) not in [2, 3] or (len(parts) == 3 and int(parts[2]) != 0):
        raise ValueError("Use hour and minute, without seconds")
    hour, mins = map(int, parts[:2])
    if not 0 <= hour <= 23 or not 0 <= mins < 60:
        raise ValueError("Invalid local time")
    return hour * 60 + mins


@dataclass(frozen=True)
class Reading:
    value: float | None
    at: float = 0

    def __post_init__(self) -> None:
        if self.value is not None:
            object.__setattr__(self, "value", finite(self.value, "reading"))
        object.__setattr__(self, "at", finite(self.at, "report timestamp"))

    def fresh(self, now: float, maximum: int) -> bool:
        return (
            self.value is not None
            and isfinite(self.value)
            and 0 <= now - self.at <= maximum
        )


@dataclass(frozen=True)
class Observation:
    temperature: Reading
    humidity: Reading = field(default_factory=lambda: Reading(None))
    internal: Reading = field(default_factory=lambda: Reading(None))
    mode: str = "unknown"
    mode_since: float = 0
    setpoint: float | None = None
    supported_modes: tuple[str, ...] = ()
    minimum: float = 16
    maximum: float = 30
    step: float = 0.5
    automatic: bool = True
    heat_goal: Reading = field(default_factory=lambda: Reading(None))
    cool_goal: Reading = field(default_factory=lambda: Reading(None))
    bias: Reading = field(default_factory=lambda: Reading(None))
    heat_allowed: bool = True
    cool_allowed: bool = True
    dry_allowed: bool = True
    goals_valid: bool = True
    permitted: bool = True
    response: dict | None = None
    off_goal: Reading = field(default_factory=lambda: Reading(None))
    thermal_occupied: bool | None = None

    def __post_init__(self) -> None:
        if (
            self.thermal_occupied is not None
            and type(self.thermal_occupied) is not bool
        ):
            raise ValueError("thermal_occupied must be boolean or inherited")
        for name in ["minimum", "maximum", "step", "mode_since"]:
            object.__setattr__(self, name, finite(getattr(self, name), name))
        if self.minimum >= self.maximum or not 0 < self.step <= 10:
            raise ValueError("Invalid actuator temperature range/step")
        if self.setpoint is not None:
            object.__setattr__(self, "setpoint", finite(self.setpoint, "setpoint"))


@dataclass(frozen=True)
class Snapshot:
    now: datetime
    zones: dict[str, Observation]
    occupied: bool | None = True
    paused: bool = False
    outdoor: Reading = field(default_factory=lambda: Reading(None))
    power: Reading = field(default_factory=lambda: Reading(None))
    require_power: bool = False
    external_fence: tuple | None = None
    plant_power: dict[str, Reading] = field(default_factory=dict)
    zone_power: dict[str, Reading] = field(default_factory=dict)

    def __post_init__(self) -> None:
        aware(self.now)


@dataclass
class Memory:
    regulation: dict = field(default_factory=dict)
    high_since: float = 0
    urgent_since: float = 0
    low_since: float = 0
    last_attempt: float = 0
    attempts: int = 0
    day: str = ""
    dry_start: float = 0
    dry_until: float = 0
    dry_floor: float = 0
    dry_target: float = 60
    last_sent: float = 0
    debt_since: float = 0
    severe_since: float = 0
    hold_since: float = 0
    hold_mode: str | None = None
    thermal_stable_since: float = 0
    thermal_low: float = 0
    thermal_high: float = 0
    thermal_last_report: float = 0
    thermal_last_seen: float = 0
    extreme_active: bool = False
    dry_episode_blocked: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.regulation, dict):
            raise ValueError("Stored room regulation must be a mapping")
        for name in [
            "high_since",
            "urgent_since",
            "low_since",
            "last_attempt",
            "dry_start",
            "dry_until",
            "last_sent",
            "debt_since",
            "severe_since",
            "hold_since",
            "thermal_stable_since",
            "thermal_last_report",
            "thermal_last_seen",
        ]:
            setattr(self, name, bounded(getattr(self, name), name, 0, 100000000000))
        if self.hold_mode not in [None, "heat", "cool"]:
            raise ValueError("Unknown stored hold direction")
        if type(self.extreme_active) is not bool:
            raise ValueError("Stored extreme-price latch must be boolean")
        if type(self.dry_episode_blocked) is not bool:
            raise ValueError("Stored humidity episode latch must be boolean")
        self.thermal_low = bounded(self.thermal_low, "thermal_low", -100, 100)
        self.thermal_high = bounded(self.thermal_high, "thermal_high", -100, 100)
        if self.thermal_low > self.thermal_high:
            raise ValueError("Reversed thermal stability range")
        self.attempts = int(bounded(self.attempts, "attempts", 0, 100000))
        self.dry_floor = bounded(self.dry_floor, "dry_floor", 0, 40)
        self.dry_target = bounded(self.dry_target, "dry_target", 0, 100)
        if self.day:
            from datetime import date

            date.fromisoformat(self.day)


@dataclass
class PlantMemory:
    direction: str | None = None
    since: float = 0
    last_flip: float = 0
    last_transition: float = 0
    modulation: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.modulation, dict):
            raise ValueError("Stored plant modulation must be a mapping")
        if self.direction not in [None, "heat", "cool", "dry"]:
            raise ValueError("Unknown stored plant direction")
        for name in ["since", "last_flip", "last_transition"]:
            setattr(self, name, bounded(getattr(self, name), name, 0, 100000000000))


@dataclass(frozen=True)
class Decision:
    zone: str
    stage: str
    reason: str
    mode: str | None
    heat_goal: float
    cool_goal: float
    humidity_start: float
    humidity_stop: float
    physical_target: float | None = None
    next_at: float | None = None
    urgent: bool = False
    target_only: bool = False


def house_from_dict(data: dict[str, Any]) -> House:
    policy = dict(data.get("policy", {}))
    if "bands" in policy:
        policy["bands"] = tuple(PriceBand(**row) for row in policy["bands"])
    return House(
        **{k: v for k, v in data.items() if k not in ["policy", "plants", "zones"]},
        plants=tuple(Plant(**p) for p in data["plants"]),
        zones=tuple(
            Zone(**{**z, "labels": tuple(z.get("labels", []))}) for z in data["zones"]
        ),
        policy=Policy(**policy),
    )
