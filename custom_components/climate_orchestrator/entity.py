"""Stable native diagnostic entities with real-area/label metadata."""

from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.helpers.device_registry import DeviceEntryType
from .const import DOMAIN


class ClimateDiagnostic(CoordinatorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, zone, key):
        super().__init__(coordinator)
        self.zone = zone
        self.key = key
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{zone.id if zone else 'house'}_{key}"
        )
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{coordinator.entry.entry_id}:{zone.id if zone else 'house'}")
            },
            name=zone.name if zone else coordinator.house.name,
            manufacturer="Home Climate Orchestrator",
            model=(
                "Independent dehumidification"
                if zone.independent_drying
                else "Split regulation"
            )
            if zone
            else "Climate coordination",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"homeassistant://config/integrations/integration/{DOMAIN}",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if not self.zone:
            return
        registry = entity_registry.async_get(self.hass)
        current = registry.async_get(self.entity_id)
        if not current:
            return
        changes = {}
        if self.zone.area and area_registry.async_get(self.hass).async_get_area(
            self.zone.area
        ):
            changes["area_id"] = self.zone.area
            if current.device_id:
                device_registry.async_get(self.hass).async_update_device(
                    current.device_id, area_id=self.zone.area
                )
        if self.zone.labels:
            changes["labels"] = sorted(set(current.labels) | set(self.zone.labels))
        if changes:
            registry.async_update_entity(self.entity_id, **changes)
