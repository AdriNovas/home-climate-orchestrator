"""Privacy-preserving support bundle: no names, bindings, presence or telemetry."""

from collections import Counter
from .const import VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    c = entry.runtime_data
    return {
        "version": VERSION,
        "mode": "shadow",
        "physical_control": False,
        "zone_count": len(c.house.zones),
        "plant_count": len(c.house.plants),
        "tariff_type": c.tariff["type"],
        "price_data_available": c.data.get("price_error") is None,
        "decision_reason_counts": dict(
            Counter(d.reason for d in c.data.get("decisions", {}).values())
        ),
        "privacy": "Names, IDs, raw states, schedules, readings and presence intentionally omitted",
    }
