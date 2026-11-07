"""Strategy selection is a preference, never a vendor preset or HVAC command."""

import copy
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.exceptions import ServiceValidationError
from .entity import ClimateDiagnostic
from .domain.preferences import STRATEGIES
from .validation import validate_sources


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([StrategySelect(entry.runtime_data, None, "strategy")])


class StrategySelect(ClimateDiagnostic, SelectEntity):
    _attr_options = list(STRATEGIES)
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:scale-balance"

    @property
    def current_option(self):
        entry = self.coordinator.entry
        return {**entry.data, **entry.options}["house"].get("strategy", "legacy")

    @property
    def extra_state_attributes(self):
        return {
            "effective_strategy": self.coordinator.planning_house().strategy,
            "application_enabled": self.coordinator.profile.get(
                "apply_strategy", False
            ),
            "purpose": "Comfort/cost preference. Shadow entries publish separate previews and preserve existing goals. Selecting does not enable execution or take Manual authority.",
        }

    async def async_select_option(self, option):
        if option not in STRATEGIES:
            raise ServiceValidationError("Unknown climate strategy")
        if option == self.current_option:
            return
        entry = self.coordinator.entry
        profile = copy.deepcopy({**entry.data, **entry.options})
        profile["house"]["strategy"] = option
        profile["strategy_schema"] = 1
        validate_sources(self.hass, profile)
        # No await between validation, update and revocation of queued work.
        self.hass.config_entries.async_update_entry(entry, options=profile)
        self.coordinator.async_apply_target_options()
        self.async_write_ha_state()
