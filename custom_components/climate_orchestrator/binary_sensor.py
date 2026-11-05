"""No push notifications: expose actionable source degradation natively."""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from .entity import ClimateDiagnostic


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            PriceDegraded(entry.runtime_data, None, "price_degraded"),
            SourceDegraded(entry.runtime_data, None, "source_degraded"),
            ServiceBlocked(entry.runtime_data, None, "service_blocked"),
        ]
    )


class PriceDegraded(ClimateDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return self.coordinator.data["price_error"] is not None

    @property
    def extra_state_attributes(self):
        return {
            "reason": self.coordinator.data["price_error"],
            "fallback": "Local comfort proposal; no opportunistic scheduling",
            "physical_control": False,
        }


class SourceDegraded(ClimateDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return any(
            d.reason
            in ["temperature_stale", "plant_state_unknown", "power_data_or_budget"]
            for d in self.coordinator.data["decisions"].values()
        )

    @property
    def extra_state_attributes(self):
        return {
            "zones": {
                z: d.reason
                for z, d in self.coordinator.data["decisions"].items()
                if d.stage == "blocked"
            },
            "physical_control": False,
        }


class ServiceBlocked(ClimateDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return any(
            d.urgent and d.stage in ["blocked", "waiting"]
            for d in self.coordinator.data["decisions"].values()
        )
