"""Home Climate Orchestrator: observation-only alpha, no physical service calls."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from .const import PLATFORMS
from .coordinator import ClimateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        coordinator = ClimateCoordinator(hass, entry)
    except (ValueError, TypeError, KeyError) as err:
        raise ConfigEntryError(f"Invalid climate profile: {err}") from err
    entry.runtime_data = coordinator
    await coordinator.async_restore()
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    coordinator.async_listen()
    return True


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_close()
        return True
    return False


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Reject unknown future schemas; never silently discard a configuration.
    return entry.version == 1
