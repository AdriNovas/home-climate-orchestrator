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
    c = entry.runtime_data
    if c.executor.enabled or c.meters:
        async_add_entities([ExecutionProblem(c, None, "execution_problem")])


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
            "physical_control": self.coordinator.executor.enabled,
        }


class SourceDegraded(ClimateDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return any(
            d.reason
            in [
                "temperature_stale",
                "plant_state_unknown",
                "power_data_or_budget",
                "external_goal_unavailable",
            ]
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
            "physical_control": self.coordinator.executor.enabled,
        }


class ServiceBlocked(ClimateDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return any(
            d.urgent and d.stage in ["blocked", "waiting"]
            for d in self.coordinator.data["decisions"].values()
        )


class ExecutionProblem(ClimateDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        c = self.coordinator
        return bool(
            c.executor.errors
            or c.executor.state["critical"]
            or any(
                reason != "user_pause" for reason in c.executor.state["manual"].values()
            )
            or any(
                (m.power_entity and c.data["metering"][m.id]["power"] is None)
                or (m.energy_entity and c.data["metering"][m.id]["energy"] is None)
                for m in c.meters
            )
        )

    @property
    def extra_state_attributes(self):
        c = self.coordinator
        return {
            "critical_cut": c.executor.state["critical"],
            "execution_errors": c.executor.errors,
            "local_manual": c.executor.state["manual"],
            "pending": {
                z: {k: row.get(k) for k in ["mode", "target", "phase", "expires"]}
                for z, row in c.executor.state["pending"].items()
            },
        }
