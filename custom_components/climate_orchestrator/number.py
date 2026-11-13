"""Editable ambient goals, never direct actuator setpoints or authority controls."""

from __future__ import annotations

import copy

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .domain.models import bounded, house_from_dict
from .entity import ClimateDiagnostic
from .validation import validate_sources

TABLES = {
    "heat_targets": ("heat_day", "heat_day_target"),
    "cool_targets": ("cool_day", "cool_day_target"),
    "heat_sleep_targets": ("heat_sleep", "heat_sleep_target"),
    "cool_sleep_targets": ("cool_sleep", "cool_sleep_target"),
    "humidity_start_targets": ("humidity_start", "humidity_start_target"),
    "humidity_stop_targets": ("humidity_stop", "humidity_stop_target"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            AmbientTarget(coordinator, zone, table, band.name, index)
            for zone in coordinator.house.zones
            for index, band in enumerate(coordinator.house.policy.bands)
            for table in TABLES
            if (not zone.independent_drying or table.startswith("humidity"))
        ]
    )


class AmbientTarget(ClimateDiagnostic, NumberEntity):
    """One cell in the same versioned table edited by native OptionsFlow."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 5
    _attr_native_max_value = 35
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, zone, table, band, index):
        super().__init__(coordinator, zone, f"target_{table}_{band}")
        self.table = table
        self.band = band
        if table.startswith("humidity"):
            self._attr_device_class = NumberDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_native_min_value = (
                35 if table == "humidity_start_targets" else 30
            )
            self._attr_native_max_value = (
                90 if table == "humidity_start_targets" else 70
            )
            self._attr_native_step = 1
        self._attr_translation_key = TABLES[table][1]
        bands = coordinator.house.policy.bands
        low = bands[index - 1].upper if index else None
        high = bands[index].upper
        price_range = (
            f"<{high:g}"
            if low is None
            else f"{low:g}+"
            if high is None
            else f"{low:g}–{high:g}"
        )
        self._attr_translation_placeholders = {
            "price_range": f"{index + 1:02d} · {price_range} {coordinator.currency}/kWh"
        }
        self._attr_icon = (
            "mdi:water-percent"
            if table.startswith("humidity")
            else "mdi:thermometer-chevron-up"
            if table.startswith("heat")
            else "mdi:thermometer-chevron-down"
        )

    def _current(self):
        entry = self.coordinator.entry
        house = house_from_dict({**entry.data, **entry.options}["house"])
        zone = next(z for z in house.zones if z.id == self.zone.id)
        band = next(b for b in house.policy.bands if b.name == self.band)
        return zone, band

    def _external_goal(self, zone):
        if self.table.startswith("humidity"):
            return None
        return (
            zone.heat_goal_entity
            if self.table.startswith("heat")
            else zone.cool_goal_entity
        )

    @property
    def available(self):
        return super().available and not self._external_goal(self._current()[0])

    @property
    def native_value(self):
        zone, band = self._current()
        return getattr(zone, self.table).get(
            self.band, getattr(band, TABLES[self.table][0])
        )

    @property
    def extra_state_attributes(self):
        zone, _ = self._current()
        return {
            "price_band": self.band,
            "target_table": self.table,
            "inherited": self.band not in getattr(zone, self.table),
            "external_goal_entity": self._external_goal(zone),
            "physical_control": self.coordinator.executor.enabled,
            "purpose": "Relative humidity start/stop threshold; accepted sessions freeze their endpoint. Observation only changes proposals."
            if self.table.startswith("humidity")
            else "Ambient comfort goal; not the AC setpoint. Observation entries only change proposals.",
        }

    async def async_set_native_value(self, value):
        entry = self.coordinator.entry
        # No await before the update: rapid independent edits use the latest
        # entry options rather than a coordinator snapshot awaiting its reload.
        profile = copy.deepcopy({**entry.data, **entry.options})
        zone = next(z for z in profile["house"]["zones"] if z["id"] == self.zone.id)
        external = (
            None
            if self.table.startswith("humidity")
            else zone.get(
                "heat_goal_entity"
                if self.table.startswith("heat")
                else "cool_goal_entity"
            )
        )
        if external:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="external_target",
                translation_placeholders={"entity": external},
            )
        try:
            temperature = bounded(
                value,
                "ambient target",
                self._attr_native_min_value,
                self._attr_native_max_value,
            )
            zone.setdefault(self.table, {})[self.band] = temperature
            house_from_dict(profile["house"])
            validate_sources(self.hass, profile)
        except (ValueError, TypeError, KeyError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_target",
            ) from err
        self.hass.config_entries.async_update_entry(entry, options=profile)
        self.async_write_ha_state()
