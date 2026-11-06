"""HA binding validation; instance IDs never enter the planning core."""

from homeassistant.helpers import entity_registry

from .const import DOMAIN
from .domain.models import house_from_dict
from .domain.energy import meters_from_profile
from .domain.safety import SupplyProtection


ZONE_SOURCES = [
    "temperature_entity",
    "humidity_entity",
    "climate_entity",
    "humidifier_entity",
    "authority_entity",
    "heat_goal_entity",
    "cool_goal_entity",
    "bias_entity",
    "internal_entity",
    "permission_entity",
    "heat_permission_entity",
    "cool_permission_entity",
    "dry_permission_entity",
    "response_entity",
    "expected_ledger_entity",
    "critical_ledger_entity",
]
HOUSE_SOURCES = [
    "power_entity",
    "outdoor_entity",
    "presence_entity",
    "control_entity",
    "critical_entity",
    "external_cut_entity",
]


def source_entities(profile):
    sources = {profile.get(name) for name in HOUSE_SOURCES}
    sources.add(profile["tariff"].get("entity"))
    for zone in profile["house"]["zones"]:
        sources.update(zone.get(name) for name in ZONE_SOURCES)
    for meter in profile.get("meters", []):
        sources.update(meter.get(name) for name in ["power_entity", "energy_entity"])
    return sources - {None, ""}


def validate_sources(hass, profile: dict) -> None:
    """Reject feedback loops through this integration's own diagnostic outputs."""
    registry = entity_registry.async_get(hass)
    house = house_from_dict(profile["house"])
    meters_from_profile(profile, house)
    SupplyProtection(**profile.get("supply_protection", {}))
    for zone in house.zones:
        if zone.humidifier_entity:
            if zone.expected_ledger_entity or zone.critical_ledger_entity:
                raise ValueError(
                    "External climate echo ledgers cannot describe a humidity actuator"
                )
            if not zone.humidifier_entity.startswith("humidifier."):
                raise ValueError("Use a native dehumidifier entity")
            actuator = hass.states.get(zone.humidifier_entity)
            if actuator and actuator.attributes.get("device_class") != "dehumidifier":
                raise ValueError("Humidifiers that add water are not drying actuators")
        if zone.critical_ledger_entity and not profile.get("external_cut_entity"):
            raise ValueError("A critical echo ledger requires its matching cut fence")
    if profile.get("execution_mode", "shadow") not in ["shadow", "control"]:
        raise ValueError("Unknown execution mode")
    if profile.get("execution_mode") == "control" and not profile.get("control_entity"):
        raise ValueError("Control requires an explicit global permission binding")
    if (
        profile.get("execution_mode") == "control"
        and profile.get("exclusive_control") is not True
    ):
        raise ValueError("Confirm exclusive actuator control before activation")
    for name in ["control_states", "presence_states"]:
        values = profile.get(name, ["on"])
        if (
            not isinstance(values, (tuple, list))
            or not values
            or any(
                not isinstance(x, str) or not x or x in ["unknown", "unavailable"]
                for x in values
            )
        ):
            raise ValueError("Explicit available permission states required")
    for source in source_entities(profile):
        if (
            not isinstance(source, str)
            or len(source.split(".")) != 2
            or not all(x and x.replace("_", "").isalnum() for x in source.split("."))
        ):
            raise ValueError("Invalid entity binding")
        entry = registry.async_get(source)
        if entry and entry.platform == DOMAIN:
            raise ValueError("Planner outputs cannot be used as planner inputs")
