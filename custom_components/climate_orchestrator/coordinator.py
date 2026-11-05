"""Read-only HA adapter. Decisions and model state never command a device."""

from __future__ import annotations
from dataclasses import asdict
from datetime import timedelta
from math import isfinite
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt
from .const import DOMAIN, STORAGE_VERSION
from .validation import validate_sources
from .domain.engine import evaluate
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

    async def async_restore(self) -> None:
        data = await self._store.async_load() or {}
        if not isinstance(data, dict):
            LOGGER.warning("Discarding incompatible observation store")
            return
        for key, row in data.get("zones", {}).items():
            if key in {z.id for z in self.house.zones}:
                try:
                    self.memories[key] = Memory(**row)
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
        }

    async def async_close(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await self._store.async_save(self._saved())
        await self.async_shutdown()

    @callback
    def async_listen(self) -> None:
        entities = {
            x
            for z in self.house.zones
            for x in [
                z.temperature_entity,
                z.humidity_entity,
                z.climate_entity,
                z.authority_entity,
            ]
            if x
        }
        entities |= {
            x
            for x in [
                self.tariff.get("entity"),
                self.profile.get("presence_entity"),
                self.profile.get("power_entity"),
                self.profile.get("outdoor_entity"),
                self.profile.get("control_entity"),
            ]
            if x
        }

        @callback
        def changed(event) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._remove_listener = async_track_state_change_event(
            self.hass, list(entities), changed
        )

    def reading(self, entity: str | None, kind: str) -> Reading:
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
        elif kind == "power":
            if unit == "kW":
                value *= 1000
            elif unit != "W":
                return Reading(None)
        return Reading(value, state.last_reported.timestamp())

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

    async def _async_update_data(self) -> dict:
        now = dt.utcnow()
        readings = {}
        for z in self.house.zones:
            state = self.hass.states.get(z.climate_entity) if z.climate_entity else None
            attrs = dict(state.attributes) if state else {}
            native_celsius = str(self.hass.config.units.temperature_unit) == "°C"

            def native(key, default=None):
                value = attrs.get(key, default)
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    return None
                return value if isfinite(value) else None

            minimum, maximum = native("min_temp"), native("max_temp")
            step = native("target_temp_step", 0.5)
            capable = (
                native_celsius
                and minimum is not None
                and maximum is not None
                and minimum < maximum
                and step is not None
                and 0 < step <= 10
            )
            internal = native("current_temperature") if native_celsius else None
            authority = (
                self.hass.states.get(z.authority_entity) if z.authority_entity else None
            )
            readings[z.id] = Observation(
                self.reading(z.temperature_entity, "temperature"),
                self.reading(z.humidity_entity, "humidity"),
                Reading(internal, state.last_reported.timestamp() if state else 0),
                state.state if state else "unknown",
                state.last_changed.timestamp() if state else now.timestamp(),
                native("temperature"),
                tuple(attrs.get("hvac_modes", [])) if capable else (),
                minimum if capable else 16,
                maximum if capable else 30,
                step if capable else 0.5,
                authority.state == "on"
                if z.authority_entity and authority
                else not bool(z.authority_entity),
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
                occupancy.state == "on"
                if occupancy and occupancy.state in ["on", "off"]
                else None
            )
            if self.profile.get("presence_entity")
            else True
        )
        snap = Snapshot(
            now,
            readings,
            occupied,
            bool(self.profile.get("control_entity"))
            and (
                (control := self.hass.states.get(self.profile["control_entity"]))
                is None
                or control.state != "on"
            ),
            self.reading(self.profile.get("outdoor_entity"), "temperature"),
            self.reading(self.profile.get("power_entity"), "power"),
            bool(self.profile.get("power_entity")),
        )
        prices = self._prices(now)
        decisions = evaluate(self.house, snap, prices, self.memories, self.plants)
        self._store.async_delay_save(self._saved, 30)
        return {
            "at": now.isoformat(),
            "decisions": decisions,
            "observations": readings,
            "price_error": self.price_error,
            "physical_control": False,
            "mode": "shadow",
        }
