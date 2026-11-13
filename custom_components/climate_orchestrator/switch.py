"""Explicit per-zone authority; rearming never bypasses an external permission."""

import copy

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from .entity import ClimateDiagnostic
from .domain.models import house_from_dict
from .validation import validate_sources


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([ZoneNightPermission(c, z, "night_permission") for z in c.house.zones if not z.independent_drying])
    if c.executor.enabled:
        async_add_entities(
            [
                ZoneAuthority(c, z, "automatic_control")
                for z in c.house.zones
                if z.actuator_entity
            ]
        )


class ZoneAuthority(ClimateDiagnostic, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        return self.coordinator.executor.is_automatic(self.zone.id)

    @property
    def extra_state_attributes(self):
        return {
            "block_reason": self.coordinator.executor.state["manual"].get(self.zone.id),
            "external_permission_required": bool(
                self.zone.authority_entity or self.zone.permission_entity
            ),
        }

    async def async_turn_on(self, **kwargs):
        await self.coordinator.executor.resume(self.zone.id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        self.coordinator.executor.manual(self.zone.id, "user_pause")
        await self.coordinator.executor.save()
        await self.coordinator.async_request_refresh()


class ZoneNightPermission(ClimateDiagnostic, SwitchEntity):
    """Persistent schedule permission, never a grant of execution authority."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "night_permission"
    _attr_icon = "mdi:weather-night"

    @property
    def is_on(self):
        return next(z for z in self.coordinator.house.zones if z.id == self.zone.id).night_allowed

    async def _set(self, enabled):
        entry = self.coordinator.entry
        profile = copy.deepcopy({**entry.data, **entry.options})
        zone = next(z for z in profile["house"]["zones"] if z["id"] == self.zone.id)
        zone["night_allowed"] = enabled
        house_from_dict(profile["house"])
        validate_sources(self.hass, profile)
        self.hass.config_entries.async_update_entry(entry, options=profile)

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
