"""Privacy-preserving support bundle: no names, bindings, presence or telemetry."""

from collections import Counter
from .const import VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    c = entry.runtime_data
    return {
        "version": VERSION,
        "mode": "control" if c.executor.enabled else "shadow",
        "physical_control": c.executor.enabled,
        "zone_count": len(c.house.zones),
        "plant_count": len(c.house.plants),
        "tariff_type": c.tariff["type"],
        "meter_count": len(c.meters),
        "meter_scope_counts": dict(Counter(m.scope for m in c.meters)),
        "critical_cut_active": c.executor.state["critical"],
        "execution_issue_count": len(c.executor.errors),
        "price_data_available": c.data.get("price_error") is None,
        "decision_reason_counts": dict(
            Counter(d.reason for d in c.data.get("decisions", {}).values())
        ),
        "privacy": "Names, IDs, raw states, schedules, readings and presence intentionally omitted",
    }
