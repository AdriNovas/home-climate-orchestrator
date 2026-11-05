"""HA binding validation; instance IDs never enter the planning core."""

from homeassistant.helpers import entity_registry

from .const import DOMAIN


def validate_sources(hass, profile: dict) -> None:
    """Reject feedback loops through this integration's own diagnostic outputs."""
    registry = entity_registry.async_get(hass)
    sources = {
        profile.get(name)
        for name in [
            "power_entity",
            "outdoor_entity",
            "presence_entity",
            "control_entity",
        ]
    }
    sources.add(profile["tariff"].get("entity"))
    for zone in profile["house"]["zones"]:
        sources.update(
            zone.get(name)
            for name in [
                "temperature_entity",
                "humidity_entity",
                "climate_entity",
                "authority_entity",
            ]
        )
    for source in sources - {None, ""}:
        entry = registry.async_get(source)
        if entry and entry.platform == DOMAIN:
            raise ValueError("Planner outputs cannot be used as planner inputs")
