"""HA observations and optional execution; the planner remains I/O-free."""

from __future__ import annotations
from dataclasses import asdict, replace
import copy
from datetime import timedelta
from math import isfinite
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Context, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers import issue_registry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt
from .const import DOMAIN, STORAGE_VERSION
from .validation import validate_sources, source_entities
from .domain.engine import evaluate, begin_dry, sleeping, dew_point, dry_reservation_unsafe
from .domain.energy import meters_from_profile, normalize
from .domain.accounting import Accounting, PERIODS
from .domain.safety import SupplyProtection, supply_cut
from .domain.sources import SourceContract
from .domain.activity import ActivitySample, resolve_activity
from .domain.strategies import preview
from .domain.provenance import record, transition_echo, critical_echo, cut_record
from .execution import Executor
from .domain.models import (
    Memory,
    Observation,
    PlantMemory,
    Reading,
    Snapshot,
    house_from_dict,
)
from .domain.scheduling import (
    immediate_review_required,
    next_deadline_within,
    plan_review_due,
)
from .domain.tariffs import (
    FixedPeriod,
    fixed_intervals,
    generic_intervals,
    pvpc_intervals,
    PriceInterval,
    validate_fixed,
    current_price,
)
import logging

LOGGER = logging.getLogger(__name__)

PLAN_REVIEW_INTERVAL_SECONDS = 300
SAFETY_RECHECK_INTERVAL_SECONDS = 60

DRY_MEMORY_FIELDS = {"dry_start_temperature", "dry_dew_target"}


STRATEGY_MEMORY_FIELDS = {
    "activity_last_positive",
    "thermal_wait_since",
    "thermal_wait_until",
    "discomfort_degree_minutes",
    "comfort_last_at",
    "comfort_last_report",
    "thermal_wait_mode",
}


def configuration(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


class ClimateCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=PLAN_REVIEW_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.profile = configuration(entry)
        validate_sources(hass, self.profile)
        self.house = house_from_dict(self.profile["house"])
        self.tariff = self.profile["tariff"]
        self.currency = self.tariff.get("currency", "EUR")
        if self.tariff["type"] == "fixed":
            validate_fixed(
                tuple(
                    FixedPeriod(**{**x, "weekdays": tuple(x["weekdays"])})
                    for x in self.tariff["periods"]
                ),
                self.house.timezone,
            )
        self.memories: dict[str, Memory] = {}
        self.plants: dict[str, PlantMemory] = {}
        self.price_error: str | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._remove_listener = None
        self.meters = meters_from_profile(self.profile, self.house)
        self.accounting = {m.id: Accounting(self.house.timezone) for m in self.meters}
        self.accounting_archive = []
        self.supply_policy = SupplyProtection(
            **self.profile.get("supply_protection", {})
        )
        self.executor = Executor(
            self.house,
            Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.executor"),
            self.fresh_plan,
            self.emit,
            lambda: dt.utcnow().timestamp(),
            self.profile.get("execution_mode", "shadow") == "control",
            publish=self.publish_execution,
        )
        self.execution_snapshot = {}
        self._worker = None
        self._pending_review = False
        self._closing = False
        self._started = False
        self._safety_worker = None
        self._safety_pending = False
        self._safety_tick_unsub = None
        self._deadline_review_unsub = None
        self._last_review_at: float | None = None
        self._next_deadline_at: float | None = None
        self._observation_store_loaded = False
        self._source_clock_issue_count = 0

    @callback
    def async_apply_target_options(self) -> bool:
        """Apply table cells without unloading controls during rapid UI edits.

        Source bindings, policy, metadata, execution mode and topology must be
        identical. All other option changes still require the normal reload.
        """
        profile = configuration(self.entry)
        if profile == self.profile:
            return True
        before, after = copy.deepcopy(self.profile), copy.deepcopy(profile)
        for item in [before, after]:
            item.pop("apply_strategy", None)
            item.pop("strategy_schema", None)
            item["house"].pop("strategy", None)
            for zone in item["house"]["zones"]:
                zone.pop("preferences", None)
                zone.pop("night_allowed", None)
                for table in [
                    "heat_targets",
                    "cool_targets",
                    "heat_sleep_targets",
                    "cool_sleep_targets",
                    "humidity_start_targets",
                    "humidity_stop_targets",
                ]:
                    zone.pop(table, None)
        if before != after:
            return False
        validate_sources(self.hass, profile)
        house = house_from_dict(profile["house"])
        # Revoke in-flight decisions before publishing new goals, without
        # resetting Manual, ownership, learned response or session budgets.
        self.executor.invalidate()
        self.profile = copy.deepcopy(profile)
        self.house = house
        self.executor.house = house
        return True

    def planning_house(self):
        # Shadow goals may already have external consumers. New strategies are
        # preview-only unless this entry owns execution AND explicitly applies them.
        return (
            self.house
            if self.executor.enabled and self.profile.get("apply_strategy", False)
            else replace(self.house, strategy="legacy")
        )

    async def publish_execution(self, persisted):
        """Publish only durable bytes, before the corresponding physical call."""
        self.execution_snapshot = persisted
        if self.data is not None:
            self.async_update_listeners()

    def source_record(self, entity):
        state = self.hass.states.get(entity) if entity else None
        return record(state.state) if state else None

    def external_echo(self, zone, old, new, user):
        if zone.independent_drying or not old or not new:
            return False
        now = dt.utcnow().timestamp()
        return transition_echo(
            self.source_record(zone.expected_ledger_entity),
            new.state,
            new.attributes.get("temperature"),
            old.state,
            old.attributes.get("temperature"),
            now,
            user,
        ) or critical_echo(
            self.source_record(zone.critical_ledger_entity),
            self.source_record(self.profile.get("external_cut_entity")),
            new.state,
            new.attributes.get("temperature"),
            now,
            user,
        )

    def actuator_mode(self, zone, state):
        if zone.independent_drying and state and state.state in ["on", "off"]:
            return "dry" if state.state == "on" else "off"
        return state.state if state else "unknown"

    def actuator_target(self, zone, state):
        if zone.independent_drying:
            try:
                value = float(state.attributes.get("humidity")) if state else None
                return value if value is not None and isfinite(value) else None
            except (TypeError, ValueError):
                return None
        return self.native_temperature(state, "temperature")

    async def async_restore(self) -> None:
        await self.executor.restore()
        data = await self._store.async_load() or {}
        if not isinstance(data, dict):
            LOGGER.warning("Discarding incompatible observation store")
            return
        if (
            type(data.get("strategy_schema", 1)) is not int
            or data.get("strategy_schema", 1) != 1
        ):
            raise ValueError(
                "Unknown strategy memory schema; preserve store for recovery"
            )
        if type(data.get("dry_memory_schema", 1)) is not int or data.get("dry_memory_schema", 1) != 1:
            raise ValueError("Unknown drying memory schema; preserve store for recovery")
        saved_dry = data.get("dry_memory", {})
        if not isinstance(saved_dry, dict):
            raise ValueError("Invalid drying memory; preserve store for recovery")
        for fields in saved_dry.values():
            if not isinstance(fields, dict) or set(fields) - DRY_MEMORY_FIELDS:
                raise ValueError("Unknown drying memory fields")
            Memory(**fields)
        for owner in self.executor.state["owned"].values():
            if owner.get("mode") != "dry":
                continue
            if "dry_schema" in owner and (
                type(owner["dry_schema"]) is not int or owner["dry_schema"] != 1
            ):
                raise ValueError("Unknown drying owner schema; preserve journal for recovery")
            Memory(dry_start=owner.get("start"), dry_until=owner.get("until"),
                   dry_floor=owner.get("floor"), dry_target=owner.get("target"),
                   dry_start_temperature=owner.get("start_temperature"),
                   dry_dew_target=owner.get("dew_target"))
        saved_strategy = data.get("strategy_memory", {})
        if not isinstance(saved_strategy, dict):
            raise ValueError("Invalid strategy memory; preserve store for recovery")
        for fields in saved_strategy.values():
            if not isinstance(fields, dict) or set(fields) - STRATEGY_MEMORY_FIELDS:
                raise ValueError("Unknown strategy memory fields")
            Memory(**fields)
        if data.get("currency", "EUR") != self.currency and data.get("accounting"):
            raise ValueError(
                "Currency migration requires a separate entry; existing measured energy and cost are preserved"
            )
        for key, row in data.get("zones", {}).items():
            if key in {z.id for z in self.house.zones}:
                try:
                    binding = next(
                        z.actuator_entity for z in self.house.zones if z.id == key
                    )
                    if data.get("bindings", {}).get(key, binding) != binding:
                        continue
                    strategy_memory = saved_strategy.get(key, {})
                    self.memories[key] = Memory(**{**row, **strategy_memory, **saved_dry.get(key, {})})
                except (TypeError, ValueError):
                    LOGGER.warning("Discarding incompatible observation memory")
        # Journal persistence precedes observer persistence on acceptance. A
        # restart between those writes still restores the accepted reservation.
        for zone in self.house.zones:
            owner = self.executor.state["owned"].get(zone.id, {})
            if owner.get("mode") == "dry" and owner.get("binding") == zone.actuator_entity:
                memory = self.memories.setdefault(zone.id, Memory())
                memory.dry_active = True
                memory.dry_start = owner["start"]
                memory.dry_until = owner["until"]
                memory.dry_floor = owner["floor"]
                memory.dry_target = owner["target"]
                memory.dry_start_temperature = owner.get("start_temperature")
                memory.dry_dew_target = owner.get("dew_target")
        self.accounting_archive = data.get("accounting_archive", [])
        for meter in self.meters:
            saved = data.get("accounting", {}).get(meter.id)
            if saved:
                if saved.get("binding") != [
                    meter.power_entity,
                    meter.scope,
                    meter.target,
                ]:
                    self.accounting_archive.append({"meter": meter.id, **saved})
                    continue
                self.accounting[meter.id] = Accounting(
                    self.house.timezone, saved["ledger"]
                )
        for key, row in data.get("plants", {}).items():
            if key in {p.id for p in self.house.plants}:
                try:
                    self.plants[key] = PlantMemory(**row)
                except (TypeError, ValueError):
                    LOGGER.warning("Discarding incompatible plant observation memory")
        self._observation_store_loaded = True

    def _saved(self) -> dict:
        return {
            "currency": self.currency,
            "strategy_schema": 1,
            # Keep old room payloads readable by the preceding version: it
            # rejects unknown Memory fields and would otherwise lose budgets.
            "zones": {
                k: {
                    name: value
                    for name, value in asdict(v).items()
                    if name not in STRATEGY_MEMORY_FIELDS | DRY_MEMORY_FIELDS
                }
                for k, v in self.memories.items()
            },
            "strategy_memory": {
                k: {
                    name: value
                    for name, value in asdict(v).items()
                    if name in STRATEGY_MEMORY_FIELDS
                }
                for k, v in self.memories.items()
            },
            "dry_memory_schema": 1,
            "dry_memory": {
                k: {name: value for name, value in asdict(v).items()
                    if name in DRY_MEMORY_FIELDS}
                for k, v in self.memories.items()
            },
            "plants": {k: asdict(v) for k, v in self.plants.items()},
            "bindings": {z.id: z.actuator_entity for z in self.house.zones},
            "accounting": {
                m.id: {
                    "binding": [m.power_entity, m.scope, m.target],
                    "ledger": self.accounting[m.id].saved(),
                }
                for m in self.meters
            },
            "accounting_archive": self.accounting_archive,
        }

    async def async_close(self) -> None:
        self._closing = True
        issue_registry.async_delete_issue(
            self.hass, DOMAIN, f"{self.entry.entry_id}_origin_clock"
        )
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        if self._safety_tick_unsub:
            self._safety_tick_unsub()
            self._safety_tick_unsub = None
        self._cancel_deadline_review()
        await self.executor.close()
        if self._worker:
            self._worker.cancel()
            import asyncio

            await asyncio.gather(self._worker, return_exceptions=True)
        if self._observation_store_loaded:
            await self._store.async_save(self._saved())
        await self.async_shutdown()

    @callback
    def async_listen(self) -> None:
        entities = source_entities(self.profile)
        urgent_entities = {
            entity
            for entity in [
                self.profile.get("control_entity"),
                self.profile.get("critical_entity"),
                self.profile.get("external_cut_entity"),
                *(
                    entity
                    for zone in self.house.zones
                    for entity in [
                        zone.authority_entity,
                        zone.permission_entity,
                        zone.heat_permission_entity,
                        zone.cool_permission_entity,
                        zone.dry_permission_entity,
                        zone.thermal_presence_entity,
                    ]
                ),
            ]
            if entity
        }

        @callback
        def changed(event) -> None:
            entity = event.data["entity_id"]
            old, new = event.data.get("old_state"), event.data.get("new_state")
            # Capture short pulses before the coalesced refresh: current state
            # may already be off when the planner reads it. Attribute-only
            # republishes must not extend the original positive transition.
            if new and (not old or old.state != new.state):
                for zone in self.house.zones:
                    for binding in zone.activity_bindings:
                        if (
                            entity == binding.entity
                            and new.state in binding.active_states
                        ):
                            clock = self.source_clock(entity, new)
                            at = (
                                clock.at
                                if clock.semantics == "origin"
                                else new.last_changed.timestamp()
                            )
                            if new.attributes.get("restored") or (
                                clock.semantics == "origin" and clock.origin_at is None
                            ):
                                continue
                            if 0 < at <= dt.utcnow().timestamp():
                                memory = self.memories.setdefault(zone.id, Memory())
                                memory.activity_last_positive[entity] = at
            climate = next(
                (z for z in self.house.zones if z.actuator_entity == entity), None
            )
            actuator_changed = bool(
                climate
                and (
                    not old
                    or not new
                    or old.state != new.state
                    or self.actuator_target(climate, old)
                    != self.actuator_target(climate, new)
                )
            )
            user_action = bool(
                climate
                and new
                and new.context.user_id
                and (
                    not old
                    or old.context.id != new.context.id
                    or old.state != new.state
                    or self.actuator_target(climate, old)
                    != self.actuator_target(climate, new)
                )
            )
            if climate:
                user = bool(
                    new
                    and new.context.user_id
                    and (
                        not old
                        or old.context.id != new.context.id
                        or old.state != new.state
                        or self.actuator_target(climate, old)
                        != self.actuator_target(climate, new)
                    )
                )
                self.executor.observe(
                    climate.id,
                    self.actuator_mode(climate, new),
                    self.actuator_target(climate, new),
                    self.actuator_mode(climate, old) if old else None,
                    self.actuator_target(climate, old),
                    user,
                    external=self.external_echo(climate, old, new, user),
                )
            elif (not old or not new or old.state != new.state) and (
                entity == self.profile.get("control_entity")
                or entity == self.profile.get("critical_entity")
                or entity == self.profile.get("external_cut_entity")
                or any(
                    entity
                    in [
                        z.authority_entity,
                        z.permission_entity,
                        z.heat_permission_entity,
                        z.cool_permission_entity,
                        z.dry_permission_entity,
                        z.thermal_presence_entity,
                    ]
                    for z in self.house.zones
                )
            ):
                self.executor.invalidate()
                for zone in self.house.zones:
                    if (
                        entity == zone.authority_entity
                        and new
                        and new.state in zone.authority_states
                    ):
                        self.executor.spawn(self.executor.resume(zone.id))
                    elif (
                        entity == zone.authority_entity
                        and new
                        and new.state not in ["unknown", "unavailable"]
                    ):
                        self.executor.manual(zone.id, "external_authority")
            if self.executor.enabled:
                self._queue_safety_check()
            immediate = immediate_review_required(
                old.state if old else None,
                new.state if new else None,
                urgent_entity=entity in urgent_entities,
                actuator_changed=actuator_changed,
                user_action=user_action,
            )
            self._request_plan_review(immediate=immediate)

        self._remove_listener = async_track_state_change_event(
            self.hass, list(entities), changed
        )
        self._started = True
        if self.executor.enabled:
            self._safety_tick_unsub = async_track_time_interval(
                self.hass,
                self._safety_tick,
                timedelta(seconds=SAFETY_RECHECK_INTERVAL_SECONDS),
            )
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _request_plan_review(self, *, immediate: bool = False) -> bool:
        """Coalesce routine source changes; urgent authority and actuator events bypass."""
        if self._closing:
            return False
        now = dt.utcnow().timestamp()
        if not plan_review_due(
            self._last_review_at,
            now,
            PLAN_REVIEW_INTERVAL_SECONDS,
            immediate=immediate,
        ):
            return False
        self.hass.async_create_task(self.async_request_refresh())
        return True

    @callback
    def _queue_safety_check(self) -> None:
        if self._closing or not self.executor.enabled:
            return
        self._safety_pending = True
        if self._safety_worker is None or self._safety_worker.done():
            self._safety_worker = self.executor.spawn(self.safety_worker())

    @callback
    def _safety_tick(self, _now) -> None:
        """Run guard-only checks each minute without invoking the full planner."""
        self._queue_safety_check()

    @callback
    def _cancel_deadline_review(self) -> None:
        if self._deadline_review_unsub:
            self._deadline_review_unsub()
            self._deadline_review_unsub = None
        self._next_deadline_at = None

    @callback
    def _deadline_review(self, _now) -> None:
        self._deadline_review_unsub = None
        self._next_deadline_at = None
        if not self._closing:
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _schedule_deadline_review(self, decisions, now: float) -> None:
        self._cancel_deadline_review()
        deadline = next_deadline_within(
            decisions.values(), now, PLAN_REVIEW_INTERVAL_SECONDS
        )
        if deadline is None or self._closing:
            return
        self._next_deadline_at = deadline
        self._deadline_review_unsub = async_call_later(
            self.hass,
            max(0, deadline - now),
            self._deadline_review,
        )

    def reading(
        self,
        entity: str | None,
        kind: str,
        configured_at=None,
        *,
        negative_power_tolerance_w=0,
    ) -> Reading:
        state = self.hass.states.get(entity) if entity else None
        if state is None:
            return Reading(None)
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return Reading(None)
        if not isfinite(value):
            return Reading(None)
        unit = state.attributes.get("unit_of_measurement")
        if kind == "temperature":
            if unit == "°F":
                value = (value - 32) * 5 / 9
            elif unit != "°C":
                return Reading(None)
        elif kind == "humidity":
            if unit != "%" or not 0 < value <= 100:
                return Reading(None)
        elif kind == "bias":
            if unit == "°F":
                value *= 5 / 9
            elif unit != "°C":
                return Reading(None)
        elif kind == "power":
            try:
                value = normalize(
                    value,
                    unit,
                    kind,
                    negative_power_tolerance_w=negative_power_tolerance_w,
                )
            except ValueError:
                return Reading(None)
        elif kind == "energy":
            try:
                value = normalize(value, unit, kind)
            except ValueError:
                return Reading(None)
        # A numeric setting is persistent configuration, not a live thermometer.
        at = (
            configured_at
            if configured_at is not None
            and entity.split(".")[0] in ["input_number", "number"]
            else state.last_reported.timestamp()
        )
        if configured_at is not None and entity.split(".")[0] in [
            "input_number",
            "number",
        ]:
            return Reading(
                value, at, state.last_reported.timestamp(), semantics="configuration"
            )
        return self.source_clock(entity, state, value)

    def source_clock(self, entity, state, value=1):
        if state is None:
            return Reading(None)
        at = state.last_reported.timestamp()
        contract = SourceContract(
            **self.profile.get("source_quality", {}).get(entity, {})
        )
        origin = None
        if contract.semantics == "origin":
            stamp = (
                state.attributes.get(contract.timestamp_attribute)
                if contract.timestamp_attribute
                else None
            )
            if contract.timestamp_entity:
                clock_state = self.hass.states.get(contract.timestamp_entity)
                stamp = clock_state.state if clock_state else None
            try:
                if isinstance(stamp, bool):
                    raise ValueError("Boolean is not a timestamp")
                if isinstance(stamp, (int, float)):
                    origin = float(stamp)
                elif isinstance(stamp, str):
                    parsed = dt.parse_datetime(stamp)
                    origin = (
                        parsed.timestamp() if parsed and parsed.tzinfo else float(stamp)
                    )
                if origin is not None and not isfinite(origin):
                    origin = None
            except (TypeError, ValueError, OverflowError):
                origin = None
            at = origin if origin is not None else 0
        return Reading(
            value, at, state.last_reported.timestamp(), origin, contract.semantics
        )

    def meter_power(self, meter):
        return self.reading(
            meter.power_entity,
            "power",
            negative_power_tolerance_w=meter.negative_power_tolerance_w,
        )

    def allowed(self, entity, states=("on",)):
        state = self.hass.states.get(entity) if entity else None
        return state is not None and state.state in states if entity else True

    def native_temperature(self, state, key, default=None, delta=False):
        try:
            value = float(state.attributes.get(key, default)) if state else None
        except (ValueError, TypeError):
            return None
        if value is None or not isfinite(value):
            return None
        if str(self.hass.config.units.temperature_unit) == "°F":
            return value * 5 / 9 if delta else (value - 32) * 5 / 9
        return value

    def _prices(self, now) -> tuple[PriceInterval, ...]:
        from datetime import timedelta

        mode = self.tariff["type"]
        try:
            if mode == "flat":
                result = (
                    PriceInterval(now, now + timedelta(hours=36), self.tariff["price"]),
                )
            elif mode == "fixed":
                result = fixed_intervals(
                    tuple(
                        FixedPeriod(**{**x, "weekdays": tuple(x["weekdays"])})
                        for x in self.tariff["periods"]
                    ),
                    now,
                    self.house.timezone,
                )
            else:
                state = self.hass.states.get(self.tariff["entity"])
                if not state or state.state in ["unknown", "unavailable"]:
                    raise ValueError("price_source_unavailable")
                if mode == "pvpc" and state.attributes.get(
                    "unit_of_measurement"
                ) not in ["EUR/kWh", "€/kWh"]:
                    raise ValueError("Unsupported PVPC price unit")
                result = (
                    pvpc_intervals(
                        dict(state.attributes), state.state, now, self.house.timezone
                    )
                    if mode == "pvpc"
                    else generic_intervals(
                        dict(state.attributes),
                        state.attributes.get("unit_of_measurement", ""),
                        self.currency,
                    )
                )
            if current_price(result, now) is None:
                raise ValueError("published_interval_missing")
            self.price_error = None
            return result
        except (ValueError, KeyError, TypeError) as err:
            self.price_error = str(err)
            return ()

    def snapshot(self):
        now = dt.utcnow()
        readings = {}
        for z in self.house.zones:
            state = (
                self.hass.states.get(z.actuator_entity) if z.actuator_entity else None
            )
            attrs = dict(state.attributes) if state else {}

            def native(key, default=None):
                return self.native_temperature(
                    state, key, default, key == "target_temp_step"
                )

            minimum, maximum = native("min_temp"), native("max_temp")
            step = native("target_temp_step", 0.5)
            capable = (
                minimum is not None
                and maximum is not None
                and minimum < maximum
                and step is not None
                and 0 < step <= 10
            )
            if z.independent_drying:
                minimum, maximum, step = (
                    attrs.get("min_humidity", 35),
                    attrs.get("max_humidity", 85),
                    1,
                )
                capable = (
                    attrs.get("device_class") == "dehumidifier"
                    and isinstance(minimum, (int, float))
                    and isinstance(maximum, (int, float))
                    and 0 <= minimum < maximum <= 100
                )
            internal = native("current_temperature")
            heat_goal = self.reading(
                z.heat_goal_entity, "temperature", configured_at=now.timestamp()
            )
            cool_goal = self.reading(
                z.cool_goal_entity, "temperature", configured_at=now.timestamp()
            )
            bias = self.reading(z.bias_entity, "bias", configured_at=now.timestamp())
            readings[z.id] = Observation(
                self.reading(z.temperature_entity, "temperature"),
                self.reading(z.humidity_entity, "humidity"),
                self.reading(z.internal_entity, "temperature")
                if z.internal_entity
                else Reading(internal, state.last_reported.timestamp() if state else 0),
                self.actuator_mode(z, state),
                state.last_changed.timestamp() if state else now.timestamp(),
                self.actuator_target(z, state),
                (
                    ("off", "dry")
                    if z.independent_drying
                    else tuple(attrs.get("hvac_modes", []))
                )
                if capable
                else (),
                minimum if capable else 16,
                maximum if capable else 30,
                step if capable else 0.5,
                self.allowed(z.authority_entity, z.authority_states)
                and self.executor.is_automatic(z.id),
                heat_goal,
                cool_goal,
                bias,
                self.allowed(z.heat_permission_entity),
                self.allowed(z.cool_permission_entity),
                self.allowed(z.dry_permission_entity),
                (
                    not z.heat_goal_entity
                    or heat_goal.fresh(
                        now.timestamp(), self.house.policy.temperature_fresh_s
                    )
                    and 5 <= heat_goal.value <= 35
                )
                and (
                    not z.cool_goal_entity
                    or cool_goal.fresh(
                        now.timestamp(), self.house.policy.temperature_fresh_s
                    )
                    and 5 <= cool_goal.value <= 35
                )
                and (
                    not z.bias_entity
                    or bias.fresh(
                        now.timestamp(), self.house.policy.temperature_fresh_s
                    )
                    and abs(bias.value) <= self.house.policy.correction_limit
                ),
                self.allowed(z.permission_entity),
                self.source_record(z.response_entity),
                self.reading(
                    z.off_goal_entity, "temperature", configured_at=now.timestamp()
                ),
                self.allowed(z.thermal_presence_entity)
                if z.thermal_presence_entity
                else None,
                self.reading(
                    z.dry_floor_entity, "temperature", configured_at=now.timestamp()
                ),
            )
            samples = {}
            for binding in z.activity_bindings:
                activity_state = self.hass.states.get(binding.entity)
                if activity_state:
                    clock = self.source_clock(binding.entity, activity_state)
                    valid = not activity_state.attributes.get("restored") and (
                        clock.semantics != "origin" or clock.origin_at is not None
                    )
                    samples[binding.entity] = ActivitySample(
                        activity_state.state if valid else None,
                        clock.at
                        if clock.semantics == "origin"
                        else activity_state.last_changed.timestamp(),
                        clock.at,
                    )
            memory = self.memories.setdefault(z.id, Memory())
            activity = resolve_activity(
                z.activity_bindings,
                samples,
                now.timestamp(),
                memory.activity_last_positive,
            )
            memory.activity_last_positive = activity.last_positive
            readings[z.id] = replace(readings[z.id], activity=activity.state)
        # Persist observed plant direction, not a planned or sent direction.
        for p in self.house.plants:
            members = [readings[z.id] for z in self.house.zones if z.plant == p.id]
            modes = {x.mode for x in members if x.mode in ["heat", "cool", "dry"]}
            pm = self.plants.setdefault(p.id, PlantMemory())
            if len(modes) == 1:
                mode = next(iter(modes))
                if mode != pm.direction:
                    pm.direction = mode
                    pm.since = now.timestamp()
                    pm.last_flip = now.timestamp()
            latest = max((x.mode_since for x in members), default=0)
            pm.last_transition = max(pm.last_transition, latest)
        occupancy = self.hass.states.get(self.profile.get("presence_entity", ""))
        occupied = (
            (
                occupancy.state in self.profile.get("presence_states", ["on"])
                if occupancy and occupancy.state not in ["unknown", "unavailable"]
                else None
            )
            if self.profile.get("presence_entity")
            else True
        )
        external_cut = (
            cut_record(self.source_record(self.profile.get("external_cut_entity")))
            if self.profile.get("external_cut_entity")
            else None
        )
        snap = Snapshot(
            now,
            readings,
            occupied,
            not self.allowed(
                self.profile.get("control_entity"),
                self.profile.get("control_states", ["on"]),
            )
            or bool(self.profile.get("critical_entity"))
            and not self.allowed(self.profile["critical_entity"], ("off",))
            or self.executor.state["critical"],
            self.reading(self.profile.get("outdoor_entity"), "temperature"),
            self.reading(self.profile.get("power_entity"), "power"),
            bool(self.profile.get("power_entity")),
            (external_cut["at"], external_cut["released"]) if external_cut else None,
            {
                plant.id: self.meter_power(matched[0])
                for plant in self.house.plants
                if len(
                    matched := [
                        m
                        for m in self.meters
                        if m.scope == "plant"
                        and m.target == plant.id
                        and m.power_entity
                    ]
                )
                == 1
            },
            {
                zone.id: self.meter_power(matched[0])
                for zone in self.house.zones
                if len(
                    matched := [
                        m
                        for m in self.meters
                        if m.scope == "zone" and m.target == zone.id and m.power_entity
                    ]
                )
                == 1
            },
        )
        if self.profile.get("external_cut_entity") and (
            external_cut is None or external_cut["active"]
        ):
            snap = replace(snap, paused=True)
        return snap

    def fresh_plan(self, executing_zone=None):
        snap = self.snapshot()
        memories = copy.deepcopy(self.memories)
        if executing_zone in memories:
            memories[executing_zone].last_sent = 0
        decisions = evaluate(
            self.planning_house(),
            snap,
            self._prices(snap.now),
            memories,
            copy.deepcopy(self.plants),
        )
        return snap, decisions

    async def emit(self, zone, service, data, token):
        if self.profile.get("external_cut_entity") and data.get("hvac_mode") != "off":
            cut = cut_record(self.source_record(self.profile["external_cut_entity"]))
            if cut is None or cut["active"]:
                raise ValueError("External critical fence denies non-off emission")
        payload = {"entity_id": zone.actuator_entity, **data}
        if zone.independent_drying:
            if service == "set_temperature":
                service, payload = (
                    "set_humidity",
                    {
                        "entity_id": zone.actuator_entity,
                        "humidity": data["temperature"],
                    },
                )
            elif service == "set_hvac_mode" and data["hvac_mode"] in ["off", "dry"]:
                service, payload = (
                    ("turn_off" if data["hvac_mode"] == "off" else "turn_on"),
                    {"entity_id": zone.actuator_entity},
                )
            else:
                raise ValueError("Unsupported dehumidifier command")
            await self.hass.services.async_call(
                "humidifier", service, payload, blocking=True, context=Context(id=token)
            )
            return
        if (
            "temperature" in payload
            and str(self.hass.config.units.temperature_unit) == "°F"
        ):
            payload["temperature"] = payload["temperature"] * 9 / 5 + 32
        await self.hass.services.async_call(
            "climate", service, payload, blocking=True, context=Context(id=token)
        )

    async def accepted(self, zone, decision):
        now = dt.utcnow().timestamp()
        memory = self.memories.setdefault(zone.id, Memory())
        if not decision.target_only:
            memory.last_sent = now
        if decision.stage == "dry_ready" and not (memory.dry_active or memory.dry_until):
            snap = self.snapshot()
            p = self.house.policy
            begin_dry(
                memory,
                now,
                decision.session_floor
                if decision.session_floor is not None
                else zone.dehumidifier_min_temperature
                if zone.independent_drying
                else p.dry_floor_sleep
                if sleeping(self.house, snap)
                else p.dry_floor_day,
                decision.humidity_stop,
                zone.dehumidifier_max_s if zone.independent_drying else p.dry_max_s,
                start_temperature=snap.zones[zone.id].temperature.value,
                dew_target=round(dew_point(
                    decision.session_floor if decision.session_floor is not None
                    else (p.dry_floor_sleep if sleeping(self.house, snap) else p.dry_floor_day),
                    decision.humidity_stop,
                ), 3) if zone.dry_dewpoint_completion else None,
            )
            self.executor.state["owned"][zone.id] = {
                "id": self.executor.state["pending"][zone.id]["id"],
                "binding": zone.actuator_entity,
                "mode": "dry",
                "start": memory.dry_start,
                "until": memory.dry_until,
                "floor": memory.dry_floor,
                "target": memory.dry_target,
                "dry_schema": 1,
                "start_temperature": memory.dry_start_temperature,
                "dew_target": memory.dry_dew_target,
            }
            await self.executor.save()
        await self._store.async_save(self._saved())

    async def check_safety(self):
        snap = self.snapshot()
        state = self.executor.state
        memory = state.setdefault("supply", {})
        external = False
        if entity := self.profile.get("critical_entity"):
            s = self.hass.states.get(entity)
            external = s.state == "on" if s and s.state in ["on", "off"] else None
        if self.profile.get("external_cut_entity"):
            cut = cut_record(self.source_record(self.profile["external_cut_entity"]))
            external = (
                True
                if cut and cut["active"] or external is True
                else None
                if cut is None or external is None
                else False
            )
        active = supply_cut(
            memory,
            snap.power if self.profile.get("power_entity") else None,
            snap.now.timestamp(),
            self.house.policy.power_fresh_s,
            self.supply_policy,
            state["critical"],
            external,
        )
        if (
            not active
            and state["critical"]
            and (
                self.executor.inflight
                or any(
                    snap.zones[z.id].mode != "off"
                    for z in self.house.zones
                    if z.actuator_entity
                )
            )
        ):
            active = True
        await self.executor.critical(active)
        for zone in self.house.zones:
            owner = state["owned"].get(zone.id, {})
            if owner.get("mode") != "dry":
                continue
            obs = snap.zones[zone.id]
            now = snap.now.timestamp()
            if self.allowed(zone.authority_entity, zone.authority_states) and (
                (owner.get("until", 0) > 0 and now >= owner["until"])
                or not obs.temperature.fresh(now, self.house.policy.temperature_fresh_s)
                or obs.temperature.value < owner["floor"]
                or dry_reservation_unsafe(zone, obs.temperature.value,
                                          owner.get("start_temperature"), owner.get("dew_target"))
                or not obs.humidity.fresh(now, self.house.policy.humidity_fresh_s)
                or not obs.dry_allowed
                or not zone.enabled
                or (snap.paused and zone.dry_pause_action == "stop")
                or not obs.permitted
                or (
                    zone.independent_drying
                    and obs.temperature.value > zone.dehumidifier_max_temperature
                )
            ):
                await self.executor.stop_owned(zone)

    async def safety_worker(self):
        while self._safety_pending and not self._closing:
            self._safety_pending = False
            await self.check_safety()

    async def run_control(self):
        import asyncio

        while self._pending_review and not self._closing:
            self._pending_review = False
            await self.check_safety()
            snap, decisions = self.fresh_plan()

            # Plants can progress independently; one serial transaction per plant.
            async def plant(p):
                for zone in self.house.zones:
                    if zone.plant == p.id and zone.actuator_entity:
                        _, latest = self.fresh_plan()
                        decision = latest[zone.id]
                        if decision.mode is not None:
                            await self.executor.execute(zone, decision, self.accepted)

            await asyncio.gather(*(plant(p) for p in self.house.plants))
            await self.executor.save()

    async def _async_update_data(self) -> dict:
        snap = self.snapshot()
        now = snap.now
        prices = self._prices(now)
        invalid_clocks = sum(
            1
            for entity, contract in self.profile.get("source_quality", {}).items()
            if contract.get("semantics") == "origin"
            and (
                (
                    clock := self.source_clock(entity, self.hass.states.get(entity))
                ).origin_at
                is None
                or clock.at > now.timestamp()
            )
        )
        if invalid_clocks != self._source_clock_issue_count:
            issue_id = f"{self.entry.entry_id}_origin_clock"
            if invalid_clocks:
                issue_registry.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=issue_registry.IssueSeverity.WARNING,
                    translation_key="origin_clock",
                    translation_placeholders={"count": str(invalid_clocks)},
                )
            else:
                issue_registry.async_delete_issue(self.hass, DOMAIN, issue_id)
            self._source_clock_issue_count = invalid_clocks
        previews = preview(self.house, snap, prices, self.memories, self.plants)
        prior_waits = {
            key: memory.thermal_wait_until for key, memory in self.memories.items()
        }
        decisions = evaluate(
            self.planning_house(), snap, prices, self.memories, self.plants
        )
        if (
            self.executor.enabled
            and self.profile.get("apply_strategy", False)
            and any(
                memory.thermal_wait_until > 0
                and memory.thermal_wait_until != prior_waits.get(key, 0)
                for key, memory in self.memories.items()
            )
        ):
            # An active economic concession gets a durable absolute lease before
            # publication, not only the usual delayed observation checkpoint.
            await self._store.async_save(self._saved())
        metering = {}
        for meter in self.meters:
            power = self.meter_power(meter)
            energy = self.reading(meter.energy_entity, "energy")
            watts = power.value if power.fresh(now.timestamp(), meter.fresh_s) else None
            kwh = (
                energy.value
                if energy.fresh(now.timestamp(), meter.energy_fresh_s)
                else None
            )
            price = current_price(prices, now)
            metering[meter.id] = {
                "power": watts,
                "energy": kwh,
                "cost_rate": watts / 1000 * price
                if watts is not None and price is not None
                else None,
                "scope": meter.scope,
                "target": meter.target,
            }
            self.accounting[meter.id].observe(
                now, watts, power.at, meter.fresh_s, prices
            )
            metering[meter.id]["periods"] = {
                period: self.accounting[meter.id].view(now, period)
                for period in PERIODS
            }
        selected = [m for m in self.meters if m.include_in_system]
        covered = {
            z.id
            for z in self.house.zones
            if any(
                m.scope == "house"
                or m.scope == "zone"
                and m.target == z.id
                or m.scope == "plant"
                and m.target == z.plant
                for m in selected
            )
        }
        system = {
            "meters": [m.id for m in selected],
            "unmetered_zones": [z.id for z in self.house.zones if z.id not in covered],
            "periods": {},
        }
        for period in PERIODS:
            rows = [metering[m.id]["periods"][period] for m in selected]
            system["periods"][period] = {
                metric: sum(row[metric] for row in rows)
                if rows and all(row[metric] is not None for row in rows)
                else None
                for metric in ["energy", "cost"]
            }
            system["periods"][period].update(
                {
                    "energy_complete": not system["unmetered_zones"]
                    and bool(rows)
                    and all(row["energy_complete"] for row in rows),
                    "cost_complete": not system["unmetered_zones"]
                    and bool(rows)
                    and all(row["cost_complete"] for row in rows),
                    "coverage": {
                        m.id: metering[m.id]["periods"][period] for m in selected
                    },
                }
            )
        self._store.async_delay_save(self._saved, 30)
        if self.executor.enabled and self._started and not self._closing:
            self._pending_review = True
            if self._worker is None or self._worker.done():
                self._worker = self.executor.spawn(self.run_control())
        self._last_review_at = now.timestamp()
        self._schedule_deadline_review(decisions, self._last_review_at)
        return {
            "at": now.isoformat(),
            "decisions": decisions,
            "strategy_preview": previews,
            "selected_strategy": self.house.strategy,
            "effective_strategy": self.planning_house().strategy,
            "observations": snap.zones,
            "price_error": self.price_error,
            "metering": metering,
            "system_accounting": system,
            "execution_errors": dict(self.executor.errors),
            "physical_control": self.executor.enabled,
            "mode": "control" if self.executor.enabled else "shadow",
        }
