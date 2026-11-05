"""Climate planner with separately enabled, journaled execution."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.storage import Store
from .const import DOMAIN, PLATFORMS, STORAGE_VERSION
from .coordinator import ClimateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        coordinator = ClimateCoordinator(hass, entry)
    except (ValueError, TypeError, KeyError) as err:
        raise ConfigEntryError(f"Invalid climate profile: {err}") from err
    entry.runtime_data = coordinator
    claims = hass.data.setdefault(DOMAIN, {})
    bindings = (
        {z.climate_entity for z in coordinator.house.zones if z.climate_entity}
        if coordinator.executor.enabled
        else set()
    )
    if any(e in claims and claims[e] != entry.entry_id for e in bindings):
        raise ConfigEntryError("An actuator is already owned by another control entry")
    claims.update({e: entry.entry_id for e in bindings})
    try:
        await coordinator.async_restore()
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_close()
        for e in bindings:
            if claims.get(e) == entry.entry_id:
                claims.pop(e)
        raise
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    coordinator.async_listen()
    return True


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if entry.runtime_data.async_apply_target_options():
        await entry.runtime_data.async_request_refresh()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_close()
        claims = hass.data.get(DOMAIN, {})
        for entity in [e for e, owner in claims.items() if owner == entry.entry_id]:
            claims.pop(entity)
        return True
    return False


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Reject unknown future schemas; never silently discard a configuration.
    return entry.version == 1


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete only this observation entry's own memory after removal."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.executor").async_remove()
