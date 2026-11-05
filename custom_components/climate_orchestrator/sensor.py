"""Native chartable goals and a compact proposed-strategy sensor per zone."""

from dataclasses import asdict
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from .entity import ClimateDiagnostic
from .const import DOMAIN
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt

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
    async_add_entities([CommandSensor(c, z) for z in c.house.zones])
    async_add_entities(
        [
            MeterSensor(c, m, key)
            for m in c.meters
            for key in ["power", "energy", "cost_rate"]
            if key != "energy" or m.energy_entity
            if key not in ["power", "cost_rate"] or m.power_entity
        ]
    )


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
                "holding",
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
            "physical_control": self.coordinator.executor.enabled,
            "observed_mode": o.mode if o else "unknown",
            "external_temperature": o.temperature.value if o else None,
            "relative_humidity": o.humidity.value if o else None,
            "regulation_response": dict(
                self.coordinator.memories[self.zone.id].regulation
            )
            if self.zone.id in self.coordinator.memories
            else {},
            "plant_load_observation": dict(
                self.coordinator.plants[self.zone.plant].modulation
            )
            if self.zone.plant in self.coordinator.plants
            else {},
            "interpretation": "Decision; execution requires its own confirmed journal. HVAC mode is not measured compressor activity.",
        }


class CommandSensor(ClimateDiagnostic, SensorEntity):
    """A read-only compatibility surface, not an authority switch or command API."""

    def __init__(self, coordinator, zone):
        super().__init__(coordinator, zone, "execution_journal")

    @property
    def native_value(self):
        return (
            self.coordinator.execution_snapshot.get("pending", {})
            .get(self.zone.id, {})
            .get("phase", "idle")
        )

    @property
    def extra_state_attributes(self):
        state = self.coordinator.execution_snapshot
        row = state.get("pending", {}).get(self.zone.id, {})
        return {
            "schema_version": 1,
            "actuator": self.zone.climate_entity,
            "execution_mode": "control"
            if self.coordinator.executor.enabled
            else "shadow",
            "temperature_unit": "°C",
            "phase": row.get("phase", "idle"),
            "command_id": row.get("id"),
            "generation": row.get("generation"),
            "expected": row.get("expected", []),
            "critical_cut_active": state.get("critical", False),
            "interpretation": "Expected echoes from persisted intentions; not measured physical effect or permission to control",
        }


class MeterSensor(ClimateDiagnostic, SensorEntity):
    def __init__(self, c, meter, key):
        zone = next(
            (
                z
                for z in c.house.zones
                if meter.scope == "zone" and z.id == meter.target
            ),
            None,
        )
        super().__init__(c, zone, "meter_" + key)
        self.meter = meter
        self._attr_unique_id = f"{c.entry.entry_id}_meter_{meter.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{c.entry.entry_id}:meter:{meter.id}")},
            name=meter.name,
            manufacturer="Home Climate Orchestrator",
            model="Explicitly scoped energy meter",
        )
        self._attr_native_unit_of_measurement = {
            "power": "W",
            "energy": "kWh",
            "cost_rate": "EUR/h",
        }[key]
        if key in ["power", "energy"]:
            self._attr_device_class = (
                SensorDeviceClass.POWER if key == "power" else SensorDeviceClass.ENERGY
            )
        if key == "energy":
            source = c.hass.states.get(meter.energy_entity)
            state_class = source.attributes.get("state_class") if source else None
            self._attr_state_class = (
                state_class if state_class in ["total", "total_increasing"] else None
            )
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self.metric = key

    @property
    def state_class(self):
        if self.metric != "energy":
            return SensorStateClass.MEASUREMENT
        source = self.hass.states.get(self.meter.energy_entity)
        value = source.attributes.get("state_class") if source else None
        return value if value in ["total", "total_increasing"] else None

    @property
    def last_reset(self):
        if self.metric != "energy" or self.state_class != "total":
            return None
        source = self.hass.states.get(self.meter.energy_entity)
        value = source.attributes.get("last_reset") if source else None
        return dt.parse_datetime(value) if isinstance(value, str) else value

    @property
    def native_value(self):
        return (
            self.coordinator.data.get("metering", {})
            .get(self.meter.id, {})
            .get(self.metric)
        )

    @property
    def extra_state_attributes(self):
        return {
            "scope": self.meter.scope,
            "scope_id": self.meter.target or None,
            "source_entity": self.meter.energy_entity
            if self.metric == "energy"
            else self.meter.power_entity,
            "accounting": "Measured at this scope; never apportioned or summed with nested meters",
            "negative_power_tolerance_w": self.meter.negative_power_tolerance_w
            if self.metric != "energy"
            else None,
            "cost_basis": "Current power × current energy price; not a bill or historical total"
            if self.metric == "cost_rate"
            else None,
        }
