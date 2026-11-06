"""Native chartable goals and a compact proposed-strategy sensor per zone."""

from dataclasses import asdict
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from .entity import ClimateDiagnostic
from .const import DOMAIN, VERSION
from .domain.engine import dew_point
from .domain.accounting import PERIODS
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt

KEYS = [
    "planned_stage",
    "heat_goal",
    "cool_goal",
    "humidity_start",
    "humidity_stop",
    "physical_target",
    "dew_point",
]


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([ConfigurationSensor(c, None, "configuration")])
    async_add_entities(
        [
            PeriodSensor(c, meter, period, metric)
            for meter in [*c.meters, None]
            for period in PERIODS
            for metric in ["energy", "cost"]
        ]
        if c.meters
        else []
    )
    async_add_entities(
        [
            PlanSensor(c, z, k)
            for z in c.house.zones
            for k in KEYS
            if not z.independent_drying or k not in ["heat_goal", "cool_goal"]
        ]
    )
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
                or (zone.independent_drying and key == "physical_target")
                else SensorDeviceClass.TEMPERATURE
            )
            self._attr_native_unit_of_measurement = (
                PERCENTAGE
                if key.startswith("humidity")
                or (zone.independent_drying and key == "physical_target")
                else UnitOfTemperature.CELSIUS
            )
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if self.key == "dew_point":
            c = self.coordinator
            o = c.data["observations"].get(self.zone.id)
            now = dt.utcnow().timestamp()
            if (
                o
                and o.temperature.fresh(now, c.house.policy.temperature_fresh_s)
                and o.humidity.fresh(now, c.house.policy.humidity_fresh_s)
            ):
                return round(dew_point(o.temperature.value, o.humidity.value), 2)
            return None
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
            "actuator": self.zone.actuator_entity,
            "execution_mode": "control"
            if self.coordinator.executor.enabled
            else "shadow",
            "temperature_unit": None if self.zone.independent_drying else "°C",
            "target_unit": "%" if self.zone.independent_drying else "°C",
            "actuator_domain": "humidifier"
            if self.zone.independent_drying
            else "climate",
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


class PeriodSensor(ClimateDiagnostic, SensorEntity):
    """Measured-scope subtotal with explicit missing history and tariff coverage."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, c, meter, period, metric):
        super().__init__(c, None, f"system_{metric}_{period}")
        self.meter, self.period, self.metric = meter, period, metric
        self._attr_translation_key = f"period_{metric}_{period}"
        if meter:
            self._attr_unique_id = (
                f"{c.entry.entry_id}_meter_{meter.id}_{metric}_{period}"
            )
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{c.entry.entry_id}:meter:{meter.id}")},
                name=meter.name,
                manufacturer="Home Climate Orchestrator",
                model="Explicitly scoped energy meter",
            )
        self._attr_device_class = (
            SensorDeviceClass.ENERGY
            if metric == "energy"
            else SensorDeviceClass.MONETARY
        )
        self._attr_native_unit_of_measurement = "kWh" if metric == "energy" else "EUR"
        self._attr_suggested_display_precision = 3 if metric == "energy" else 2

    def row(self):
        c = self.coordinator
        source = (
            c.data.get("metering", {}).get(self.meter.id, {})
            if self.meter
            else c.data.get("system_accounting", {})
        )
        return source.get("periods", {}).get(self.period, {})

    @property
    def native_value(self):
        return self.row().get(self.metric)

    @property
    def last_reset(self):
        row = self.row()
        if self.meter:
            values = [row.get("period_start"), row.get("tracking_since")]
        else:
            values = [
                v.get(k)
                for v in row.get("coverage", {}).values()
                for k in ["period_start", "tracking_since"]
            ]
        parsed = [dt.parse_datetime(v) for v in values if v]
        return max(parsed) if parsed else None

    @property
    def extra_state_attributes(self):
        c, row = self.coordinator, self.row()
        return {
            **row,
            "period": self.period,
            "complete": row.get(self.metric + "_complete", False),
            "scope": self.meter.scope if self.meter else "measured_system_subset",
            "source_entity": self.meter.power_entity if self.meter else None,
            "unmetered_zones": c.data.get("system_accounting", {}).get(
                "unmetered_zones", []
            )
            if not self.meter
            else [],
            "interpretation": "Integrated measured active power; variable energy charge, not whole bill. Missing history is not zero. No per-split allocation.",
        }


class ConfigurationSensor(ClimateDiagnostic, SensorEntity):
    """Validated public HA configuration surface, never a write or permission API."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["shadow", "control"]
    _attr_icon = "mdi:cog-outline"

    @property
    def native_value(self):
        return "control" if self.coordinator.executor.enabled else "shadow"

    @property
    def extra_state_attributes(self):
        c = self.coordinator
        return {
            "schema_version": 1,
            "version": VERSION,
            "policy": asdict(c.house.policy),
            "plants": [
                {
                    key: getattr(plant, key)
                    for key in [
                        "id",
                        "minimum_off_s",
                        "minimum_on_s",
                        "direction_hold_s",
                        "reversal_gap_s",
                        "coil_drain_s",
                    ]
                }
                for plant in c.house.plants
            ],
            "zones": {
                zone.id: {
                    "actuator_entity": zone.actuator_entity,
                    "temperature_entity": zone.temperature_entity,
                    "humidity_entity": zone.humidity_entity,
                    "enabled": zone.enabled,
                }
                for zone in c.house.zones
            },
            "physical_control": c.executor.enabled,
            "interpretation": "Validated read-only configuration for dashboards and explicit consumers; never grants actuator authority or exposes credentials.",
        }
