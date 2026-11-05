"""Explicit per-zone authority; rearming never bypasses an external permission."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from .entity import ClimateDiagnostic


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    if c.executor.enabled:
        async_add_entities(
            [
                ZoneAuthority(c, z, "automatic_control")
                for z in c.house.zones
                if z.climate_entity
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
