"""HA observations and optional execution; the planner remains I/O-free."""

from __future__ import annotations
from dataclasses import asdict
import copy
from datetime import timedelta
from math import isfinite
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Context, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt
from .const import DOMAIN, STORAGE_VERSION
from .validation import validate_sources, source_entities
from .domain.engine import evaluate, begin_dry, sleeping
from .domain.energy import meters_from_profile, normalize
from .domain.safety import SupplyProtection, supply_cut
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


def configuration(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


class ClimateCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=60),
        )
        self.entry = entry
        self.profile = configuration(entry)
        validate_sources(hass, self.profile)
        self.house = house_from_dict(self.profile["house"])
        self.tariff = self.profile["tariff"]
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

    @callback
    def async_apply_target_options(self) -> bool:
        """Apply table cells without unloading controls during rapid UI edits.

        Source bindings, policy, metadata, execution mode and topology must be
        identical. All other option changes still require the normal reload.
        """
        profile = configuration(self.entry)
        before, after = copy.deepcopy(self.profile), copy.deepcopy(profile)
        for item in [before, after]:
            for zone in item["house"]["zones"]:
                for table in [
                    "heat_targets",
                    "cool_targets",
                    "heat_sleep_targets",
                    "cool_sleep_targets",
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

    async def publish_execution(self, persisted):
        """Publish only durable bytes, before the corresponding physical call."""
        self.execution_snapshot = persisted
        if self.data is not None:
            self.async_update_listeners()

    def source_record(self, entity):
        state = self.hass.states.get(entity) if entity else None
        return record(state.state) if state else None

    def external_echo(self, zone, old, new, user):
        if not old or not new:
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

    async def async_restore(self) -> None:
        await self.executor.restore()
        data = await self._store.async_load() or {}
        if not isinstance(data, dict):
            LOGGER.warning("Discarding incompatible observation store")
            return
        for key, row in data.get("zones", {}).items():
            if key in {z.id for z in self.house.zones}:
                try:
                    binding = next(
                        z.climate_entity for z in self.house.zones if z.id == key
                    )
                    if data.get("bindings", {}).get(key, binding) != binding:
                        continue
                    self.memories[key] = Memory(**row)
                    owner = self.executor.state["owned"].get(key, {})
                    if (
                        owner.get("mode") == "dry"
                        and owner.get("binding") == binding
                        and owner.get("until")
                    ):
                        self.memories[key].dry_start = owner["start"]
                        self.memories[key].dry_until = owner["until"]
                        self.memories[key].dry_floor = owner["floor"]
                        self.memories[key].dry_target = owner["target"]
                except (TypeError, ValueError):
                    LOGGER.warning("Discarding incompatible observation memory")
        for key, row in data.get("plants", {}).items():
            if key in {p.id for p in self.house.plants}:
                try:
                    self.plants[key] = PlantMemory(**row)
                except (TypeError, ValueError):
                    LOGGER.warning("Discarding incompatible plant observation memory")

    def _saved(self) -> dict:
        return {
            "zones": {k: asdict(v) for k, v in self.memories.items()},
            "plants": {k: asdict(v) for k, v in self.plants.items()},
            "bindings": {z.id: z.climate_entity for z in self.house.zones},
        }

    async def async_close(self) -> None:
        self._closing = True
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await self.executor.close()
        if self._worker:
            self._worker.cancel()
            import asyncio

            await asyncio.gather(self._worker, return_exceptions=True)
        await self._store.async_save(self._saved())
        await self.async_shutdown()

    @callback
    def async_listen(self) -> None:
        entities = source_entities(self.profile)

        @callback
        def changed(event) -> None:
            entity = event.data["entity_id"]
            old, new = event.data.get("old_state"), event.data.get("new_state")
            climate = next(
                (z for z in self.house.zones if z.climate_entity == entity), None
            )
            if climate:
                user = bool(
                    new
                    and new.context.user_id
                    and (
                        not old
                        or old.context.id != new.context.id
                        or old.state != new.state
                        or old.attributes.get("temperature")
                        != new.attributes.get("temperature")
                    )
                )
                self.executor.observe(
                    climate.id,
                    new.state if new else "unavailable",
                    self.native_temperature(new, "temperature"),
                    old.state if old else None,
                    self.native_temperature(old, "temperature"),
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
                self._safety_pending = True
                if self._safety_worker is None or self._safety_worker.done():
                    self._safety_worker = self.executor.spawn(self.safety_worker())
            self.hass.async_create_task(self.async_request_refresh())

        self._remove_listener = async_track_state_change_event(
            self.hass, list(entities), changed
        )
        self._started = True
        if self.executor.enabled:
            self.hass.async_create_task(self.async_request_refresh())

    def reading(self, entity: str | None, kind: str, configured_at=None) -> Reading:
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
                value = normalize(value, unit, kind)
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
        return Reading(value, at)

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
            state = self.hass.states.get(z.climate_entity) if z.climate_entity else None
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
                state.state if state else "unknown",
                state.last_changed.timestamp() if state else now.timestamp(),
                native("temperature"),
                tuple(attrs.get("hvac_modes", [])) if capable else (),
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
            )
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
                plant.id: self.reading(matched[0].power_entity, "power")
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
                zone.id: self.reading(matched[0].power_entity, "power")
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
            from dataclasses import replace

            snap = replace(snap, paused=True)
        return snap

    def fresh_plan(self, executing_zone=None):
        snap = self.snapshot()
        memories = copy.deepcopy(self.memories)
        if executing_zone in memories:
            memories[executing_zone].last_sent = 0
        decisions = evaluate(
            self.house,
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
        payload = {"entity_id": zone.climate_entity, **data}
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
        memory.last_sent = now
        if decision.stage == "dry_ready" and not memory.dry_until:
            snap = self.snapshot()
            p = self.house.policy
            begin_dry(
                memory,
                now,
                p.dry_floor_sleep if sleeping(self.house, snap) else p.dry_floor_day,
                decision.humidity_stop,
                p.dry_max_s,
            )
            self.executor.state["owned"][zone.id] = {
                "id": self.executor.state["pending"][zone.id]["id"],
                "binding": zone.climate_entity,
                "mode": "dry",
                "start": memory.dry_start,
                "until": memory.dry_until,
                "floor": memory.dry_floor,
                "target": memory.dry_target,
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
                    if z.climate_entity
                )
            )
        ):
            active = True
        await self.executor.critical(active)
        for zone in self.house.zones:
            owner = state["owned"].get(zone.id, {})
            if owner.get("mode") != "dry" or not owner.get("until"):
                continue
            obs = snap.zones[zone.id]
            now = snap.now.timestamp()
            if self.allowed(zone.authority_entity, zone.authority_states) and (
                now >= owner["until"]
                or not obs.temperature.fresh(now, self.house.policy.temperature_fresh_s)
                or obs.temperature.value < owner["floor"]
                or not obs.humidity.fresh(now, self.house.policy.humidity_fresh_s)
                or not obs.dry_allowed
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
                    if zone.plant == p.id and zone.climate_entity:
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
        decisions = evaluate(self.house, snap, prices, self.memories, self.plants)
        self._store.async_delay_save(self._saved, 30)
        metering = {}
        for meter in self.meters:
            power = self.reading(meter.power_entity, "power")
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
        if self.executor.enabled and self._started and not self._closing:
            self._pending_review = True
            if self._worker is None or self._worker.done():
                self._worker = self.executor.spawn(self.run_control())
        return {
            "at": now.isoformat(),
            "decisions": decisions,
            "observations": snap.zones,
            "price_error": self.price_error,
            "metering": metering,
            "execution_errors": dict(self.executor.errors),
            "physical_control": self.executor.enabled,
            "mode": "control" if self.executor.enabled else "shadow",
        }
