"""Native chartable goals and a compact proposed-strategy sensor per zone."""

from dataclasses import asdict
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from .entity import ClimateDiagnostic

KEYS = [
    "planned_stage",
    "heat_goal",
    "cool_goal",
    "humidity_start",
    "humidity_stop",
    "physical_target",
]


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([PlanSensor(c, z, k) for z in c.house.zones for k in KEYS])


class PlanSensor(ClimateDiagnostic, SensorEntity):
    def __init__(self, c, zone, key):
        super().__init__(c, zone, key)
        if key == "planned_stage":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = [
                "idle",
                "manual",
                "waiting",
                "blocked",
                "paused",
                "recovering",
                "maintaining",
                "settling",
                "protect",
                "coasting",
                "dry_ready",
                "drying",
                "dry_stop",
                "external",
                "reversing",
            ]
        else:
            self._attr_device_class = (
                SensorDeviceClass.HUMIDITY
                if key.startswith("humidity")
                else SensorDeviceClass.TEMPERATURE
            )
            self._attr_native_unit_of_measurement = (
                PERCENTAGE if key.startswith("humidity") else UnitOfTemperature.CELSIUS
            )
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        d = self.coordinator.data["decisions"].get(self.zone.id)
        return getattr(d, "stage" if self.key == "planned_stage" else self.key, None)

    @property
    def extra_state_attributes(self):
        if self.key != "planned_stage":
            return None
        d = self.coordinator.data["decisions"].get(self.zone.id)
        o = self.coordinator.data["observations"].get(self.zone.id)
        return {
            **(asdict(d) if d else {}),
            "physical_control": False,
            "observed_mode": o.mode if o else "unknown",
            "external_temperature": o.temperature.value if o else None,
            "relative_humidity": o.humidity.value if o else None,
            "interpretation": "Proposal, not a command or measured compressor operation",
        }
