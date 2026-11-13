"""Validated configuration and immutable observations for the planning engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo
from .preferences import Preferences, ActivityBinding, STRATEGIES

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


# Shared scalar bounds: forms and domain must accept the same individual ranges.
POLICY_NUMERIC_BOUNDS = {
    "boost_limit": (0, 10),
    "command_interval": (1, 86400),
    "correction_limit": (0, 10),
    "dry_attempts": (1, 86400),
    "dry_cooldown_s": (1, 86400),
    "dry_floor_day": (10, 30),
    "dry_floor_sleep": (10, 30),
    "dry_heat_offset": (-5, 5),
    "dry_humidity_band": (0, 100),
    "dry_margin": (0, 10),
    "dry_max_s": (0, 86400),
    "dry_min_outdoor": (-20, 35),
    "dry_min_s": (1, 86400),
    "extreme_price": (0.01, 10),
    "extreme_price_hysteresis": (0, 10),
    "hold_delta": (0, 10),
    "humidity_deadline_s": (1, 86400),
    "humidity_fresh_s": (1, 86400),
    "humidity_recovery_s": (1, 86400),
    "humidity_stable_s": (1, 86400),
    "improvement": (0, 10),
    "internal_fresh_s": (1, 86400),
    "lookahead_s": (1, 86400),
    "modulated_hold_s": (0, 7200),
    "overshoot_delta": (0, 10),
    "power_fresh_s": (1, 86400),
    "power_limit": (100, 100000),
    "proportional_gain": (0, 10),
    "relaxation_limit": (0.5, 6),
    "service_humidity": (50, 75),
    "severe_humidity": (70, 95),
    "severe_stable_s": (1, 86400),
    "shared_load_high_w": (1, 20000),
    "shared_load_idle_w": (0, 5000),
    "shared_load_observe_s": (600, 86400),
    "shared_load_retry_s": (1200, 86400),
    "start_delta": (0, 10),
    "temperature_fresh_s": (1, 86400),
    "thermal_sample_gap_s": (1, 86400),
    "thermal_stability_delta": (0.01, 2),
    "thermal_stable_s": (1, 86400),
    "urgent_humidity": (60, 95),
    "urgent_stable_s": (1, 86400),
}
POLICY_INTEGER_FIELDS = frozenset(
    {
        "command_interval",
        "dry_attempts",
        "dry_cooldown_s",
        "dry_max_s",
        "dry_min_s",
        "humidity_deadline_s",
        "humidity_fresh_s",
        "humidity_recovery_s",
        "humidity_stable_s",
        "internal_fresh_s",
        "lookahead_s",
        "modulated_hold_s",
        "power_fresh_s",
        "severe_stable_s",
        "temperature_fresh_s",
        "thermal_sample_gap_s",
        "thermal_stable_s",
        "urgent_stable_s",
    }
)


class PolicyValidationError(ValueError):
    """A policy relationship with stable field/error identifiers for native UI."""

    def __init__(self, message: str, code: str, *fields: str):
        super().__init__(message)
        self.code = code
        self.fields = fields


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
    # Opt-in: one admission/continuation floor relative to the ambient heat goal.
    dry_heat_offset: float | None = None
    dry_min_outdoor: float = 10
    dry_min_s: int = 1200
    dry_max_s: int = 1800
    dry_cooldown_s: int = 14400
    dry_attempts: int = 2
    # Opt-in concurrency; service budgets are independent from fault/ACK guards.
    dry_concurrent: bool = False
    dry_humidity_band: float = 5
    dry_budget_enabled: bool = True
    humidity_stable_s: int = 900
    humidity_recovery_s: int = 600
    humidity_deadline_s: int = 14400
    humidity_debt_urgency: bool = True
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
        for name in ["continuous_hold", "shared_load_management", "dry_concurrent", "dry_budget_enabled", "humidity_debt_urgency", "extreme_price_enabled"]:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        for name, (low, high) in POLICY_NUMERIC_BOUNDS.items():
            value = getattr(self, name)
            if name == "dry_heat_offset" and value is None:
                continue
            value = bounded(value, name, low, high)
            object.__setattr__(self, name, int(value) if name in POLICY_INTEGER_FIELDS else value)
        if self.shared_load_idle_w >= self.shared_load_high_w:
            raise PolicyValidationError(
                "Shared-load high threshold must exceed idle reference",
                "policy_load_order", "shared_load_idle_w", "shared_load_high_w",
            )
        if self.shared_load_management and not self.continuous_hold:
            raise PolicyValidationError(
                "Shared-load management requires continuous holding",
                "policy_requires_hold", "shared_load_management", "continuous_hold",
            )
        if self.extreme_price_hysteresis >= self.extreme_price:
            raise PolicyValidationError(
                "Price exit hysteresis must be below its entry threshold",
                "policy_price_margin", "extreme_price_hysteresis", "extreme_price",
            )
        if not self.bands or self.bands[-1].upper is not None:
            raise ValueError("Last price band must be unbounded")
        limits = [b.upper for b in self.bands[:-1]]
        if any(x is None for x in limits) or limits != sorted(set(limits)):
            raise ValueError("Price boundaries must be strictly increasing")
        if len({b.name for b in self.bands}) != len(self.bands):
            raise ValueError("Duplicate price band names")
        if not 0 < self.hold_delta < self.start_delta <= self.overshoot_delta + 1:
            raise PolicyValidationError(
                "Invalid start/hold hysteresis", "policy_hysteresis",
                "hold_delta", "start_delta", "overshoot_delta",
            )
        if self.overshoot_delta <= self.hold_delta:
            raise PolicyValidationError(
                "Overshoot threshold must exceed hold tolerance",
                "policy_overshoot", "overshoot_delta", "hold_delta",
            )
        if self.dry_max_s and self.dry_max_s < self.dry_min_s:
            raise PolicyValidationError(
                "Maximum drying time is below minimum", "policy_dry_duration",
                "dry_max_s", "dry_min_s",
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
    dry_floor_entity: str | None = None
    dry_pause_action: str = "stop"
    dry_max_temperature_drop: float | None = None
    dry_dewpoint_completion: bool = False
    preferences: Preferences = field(default_factory=Preferences)
    activity_bindings: tuple[ActivityBinding, ...] = ()
    # Appended to preserve the positional constructor contract for existing profiles.
    humidity_basis: str = "room"
    drying_availability: str = "occupied"

    @property
    def actuator_entity(self):
        return self.humidifier_entity or self.climate_entity

    @property
    def independent_drying(self):
        return self.humidifier_entity is not None

    def __post_init__(self) -> None:
        if not isinstance(self.night_allowed, bool):
            raise ValueError("Overnight permission must be boolean")
        if self.humidity_basis not in ("room", "home_max"):
            raise ValueError("Unknown humidity reference")
        if self.drying_availability not in ("occupied", "always"):
            raise ValueError("Unknown dehumidifier availability schedule")
        if not all([self.id, self.name, self.plant, self.temperature_entity]):
            raise ValueError("Zone identity, plant and temperature source required")
        if not isinstance(self.preferences, Preferences) or any(
            not isinstance(binding, ActivityBinding)
            for binding in self.activity_bindings
        ):
            raise ValueError("Validated preferences and activity bindings required")
        if len({b.entity for b in self.activity_bindings}) != len(
            self.activity_bindings
        ):
            raise ValueError("Duplicate room activity binding")
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
        if type(self.dry_dewpoint_completion) is not bool:
            raise ValueError("Drying dew-point completion must be boolean")
        if self.dry_max_temperature_drop is not None:
            object.__setattr__(self, "dry_max_temperature_drop", bounded(
                self.dry_max_temperature_drop, "dry_max_temperature_drop", 0, 10
            ))
        if self.humidifier_entity and (
            self.dry_dewpoint_completion or self.dry_max_temperature_drop is not None
        ):
            raise ValueError("Split drying reservation guards require a climate actuator")
        if self.dry_pause_action not in ["stop", "retain_owned"]:
            raise ValueError("Unknown owned-dry pause action")
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
        if self.humidity_basis == "home_max" and not self.humidifier_entity:
            raise ValueError("Home-wide humidity is only supported for an independent dehumidifier")
        if self.drying_availability != "occupied" and not self.humidifier_entity:
            raise ValueError("Independent dehumidifier availability is only supported for its own actuator")
        for name in [
            "dehumidifier_min_s",
            "dehumidifier_cooldown_s",
        ]:
            object.__setattr__(
                self, name, int(bounded(getattr(self, name), name, 180, 86400))
            )
        object.__setattr__(self, "dehumidifier_max_s", int(bounded(self.dehumidifier_max_s, "dehumidifier_max_s", 0, 86400)))
        if self.dehumidifier_max_s and self.dehumidifier_max_s < self.dehumidifier_min_s:
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
    strategy: str = "legacy"

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if self.strategy not in STRATEGIES:
            raise ValueError("Unknown strategy")
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
            baseline = next(
                (b for b in self.policy.bands if b.name == "normal"),
                self.policy.bands[len(self.policy.bands) // 2],
            )
            pref = zone.preferences
            for phase in ("day", "sleep"):
                ht = zone.heat_sleep_targets if phase == "sleep" else zone.heat_targets
                ct = zone.cool_sleep_targets if phase == "sleep" else zone.cool_targets
                heat = getattr(pref, f"heat_{phase}")
                cool = getattr(pref, f"cool_{phase}")
                heat = (
                    ht.get(baseline.name, getattr(baseline, f"heat_{phase}"))
                    if heat is None
                    else heat
                )
                cool = (
                    ct.get(baseline.name, getattr(baseline, f"cool_{phase}"))
                    if cool is None
                    else cool
                )
                if not pref.minimum_heat <= heat < cool <= pref.maximum_cool:
                    raise ValueError("Preferred targets must fit the authorized band")
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
    received_at: float = 0
    origin_at: float | None = None
    semantics: str = "received"

    def __post_init__(self) -> None:
        if self.value is not None:
            object.__setattr__(self, "value", finite(self.value, "reading"))
        object.__setattr__(self, "at", finite(self.at, "report timestamp"))
        object.__setattr__(
            self, "received_at", finite(self.received_at, "reception timestamp")
        )
        if self.origin_at is not None:
            object.__setattr__(
                self, "origin_at", finite(self.origin_at, "origin timestamp")
            )
        if self.semantics not in ("received", "origin", "provider", "configuration"):
            raise ValueError("Unknown reading clock semantics")

    def fresh(self, now: float, maximum: int) -> bool:
        return (
            self.value is not None
            and isfinite(self.value)
            and (self.semantics != "origin" or self.origin_at is not None)
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
    dry_floor: Reading = field(default_factory=lambda: Reading(None))
    activity: str = "unknown"

    def __post_init__(self) -> None:
        if self.activity not in ("unknown", "occupied", "vacant"):
            raise ValueError("Unknown room activity")
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
    home_humidity: Reading = field(default_factory=lambda: Reading(None))

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
    dry_active: bool = False
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
    activity_last_positive: dict[str, float] = field(default_factory=dict)
    thermal_wait_since: float = 0
    thermal_wait_until: float = 0
    discomfort_degree_minutes: float = 0
    comfort_last_at: float = 0
    comfort_last_report: float = 0
    thermal_wait_mode: str | None = None

    dry_start_temperature: float | None = None
    dry_dew_target: float | None = None

    def __post_init__(self) -> None:
        for name in ["dry_start_temperature", "dry_dew_target"]:
            if getattr(self, name) is not None:
                setattr(self, name, bounded(getattr(self, name), name, -100, 100))
        if type(self.dry_active) is not bool:
            raise ValueError("Stored dry activity must be boolean")
        if not isinstance(self.activity_last_positive, dict):
            raise ValueError("Activity memory must be a mapping")
        for value in self.activity_last_positive.values():
            bounded(value, "activity clock", 0, 100000000000)
        if self.thermal_wait_mode not in (None, "heat", "cool"):
            raise ValueError("Unknown waiting direction")
        self.discomfort_degree_minutes = bounded(
            self.discomfort_degree_minutes, "discomfort_degree_minutes", 0, 100000000000
        )
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
            "thermal_wait_since",
            "thermal_wait_until",
            "comfort_last_at",
            "comfort_last_report",
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
    session_floor: float | None = None
    strategy: str = "legacy"
    strategy_reason: str = "legacy_tables"
    preferred_heat: float | None = None
    preferred_cool: float | None = None
    activity: str = "unknown"


def house_from_dict(data: dict[str, Any]) -> House:
    policy = dict(data.get("policy", {}))
    if "bands" in policy:
        policy["bands"] = tuple(PriceBand(**row) for row in policy["bands"])
    return House(
        **{k: v for k, v in data.items() if k not in ["policy", "plants", "zones"]},
        plants=tuple(Plant(**p) for p in data["plants"]),
        zones=tuple(
            Zone(
                **{
                    **z,
                    "labels": tuple(z.get("labels", [])),
                    "preferences": Preferences(**z.get("preferences", {})),
                    "activity_bindings": tuple(
                        ActivityBinding(**b) for b in z.get("activity_bindings", [])
                    ),
                }
            )
            for z in data["zones"]
        ),
        policy=Policy(**policy),
    )
