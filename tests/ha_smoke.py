"""Run with Home Assistant installed; all state and storage live in a temp directory.

No real integrations, devices, network fetches or service calls are used.
"""

import asyncio
import json
import pathlib
import sys
import tempfile
from types import MappingProxyType

if "FILES" not in globals():
    root = pathlib.Path(__file__).resolve().parents[1]
    FILES = {
        str(p.relative_to(root)): p.read_text()
        for p in (root / "custom_components").rglob("*")
        if p.suffix in [".py", ".json"]
    }


async def main():
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry, ConfigEntries
    from homeassistant.util.unit_system import METRIC_SYSTEM

    checks = []
    with tempfile.TemporaryDirectory(prefix="climate-orchestrator-smoke-") as folder:
        base = pathlib.Path(folder)
        for name, text in FILES.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        (base / "custom_components/__init__.py").write_text("")
        sys.path.insert(0, folder)
        from custom_components.climate_orchestrator.config_flow import (
            ClimateFlow,
            ClimateOptions,
        )
        from custom_components.climate_orchestrator.coordinator import (
            ClimateCoordinator,
        )
        from custom_components.climate_orchestrator import (
            sensor,
            binary_sensor,
            diagnostics,
        )

        h = HomeAssistant(folder)
        h.config.units = METRIC_SYSTEM
        h.config_entries = ConfigEntries(h, {})
        from homeassistant.helpers import entity_registry as er, device_registry as dr

        dr.async_setup(h)
        await dr.async_load(h, load_empty=True)
        await er.async_get(h).async_load(load_empty=True)
        try:
            flow = ClimateFlow()
            flow.hass = h
            flow.context = {"source": "user"}
            flow.handler = "climate_orchestrator"
            flow.flow_id = "smoke"
            assert (await flow.async_step_user())["type"] == "form"
            assert (
                await flow.async_step_user(
                    {
                        "name": "Fictional house",
                        "timezone": "Europe/Madrid",
                        "tariff_type": "flat",
                    }
                )
            )["step_id"] == "tariff"
            await flow.async_step_tariff({"price": 0.15})
            await flow.async_step_plant(
                {
                    "name": "Outdoor",
                    "shared_mode": True,
                    "minimum_off_min": 20,
                    "minimum_on_min": 20,
                    "direction_hold_min": 60,
                    "reversal_gap_min": 120,
                }
            )
            plant = flow.profile["house"]["plants"][0]["id"]
            await flow.async_step_zone(
                {
                    "name": "Demo zone",
                    "plant": plant,
                    "temperature_entity": "sensor.demo_t",
                    "humidity_entity": "sensor.demo_rh",
                    "climate_entity": "climate.demo",
                    "bias": 0,
                    "priority": 1,
                    "allow_dry": False,
                    "night_allowed": True,
                }
            )
            created = await flow.async_step_create()
            assert created["type"] == "create_entry"
            checks.append("native setup wizard creates a valid independent house")
            config = created["data"]
            entry = ConfigEntry(
                version=1,
                minor_version=1,
                domain="climate_orchestrator",
                title="Demo",
                data=config,
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            options = ClimateOptions(entry)
            options.hass = h
            options.context = {"source": "options"}
            options.handler = "climate_orchestrator"
            options.flow_id = "options"
            assert (await options.async_step_init())["type"] == "menu"
            bad = await options.async_step_policy({"hold_delta": 5})
            assert bad["errors"]["base"] == "invalid_configuration"
            good = await options.async_step_policy({"hold_delta": 0.15})
            assert good["type"] == "create_entry"
            checks.append("invalid options do not poison the next form submission")
            zone_id = config["house"]["zones"][0]["id"]
            await options.async_step_zone_targets({"zone": zone_id})
            from custom_components.climate_orchestrator.domain.models import Policy

            targets = {b.name: b.heat_day for b in Policy().bands}
            targets["normal"] = 22
            edited = await options.async_step_zone_targets_edit(
                {"override": True, **targets}
            )
            assert edited["data"]["house"]["zones"][0]["heat_targets"]["normal"] == 22
            checks.append(
                "per-zone daytime targets are editable without changing zone identity"
            )
            options.profile["power_entity"] = "sensor.optional_power"
            cleared = await options.async_step_sources({})
            assert "power_entity" not in cleared["data"]
            checks.append("clearing an optional source actually removes its binding")
            await options.async_step_tariff_type({"tariff_type": "fixed"})
            await options.async_step_tariff_period(
                {
                    "weekdays": [str(x) for x in range(7)],
                    "start": "00:00",
                    "end": "08:00",
                    "price": -0.01,
                    "add_another": True,
                }
            )
            assert options.profile["tariff"]["type"] == "flat"
            complete = await options.async_step_tariff_period(
                {
                    "weekdays": [str(x) for x in range(7)],
                    "start": "08:00",
                    "end": "00:00",
                    "price": 0.25,
                    "add_another": False,
                }
            )
            assert complete["data"]["tariff"]["type"] == "fixed"
            checks.append(
                "multi-boundary fixed tariff draft replaces the old schedule only when complete"
            )
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(h)
            own = registry.async_get_or_create(
                "sensor",
                "climate_orchestrator",
                "test-loop",
                suggested_object_id="own_proposal",
            )
            rejected = await options.async_step_sources({"power_entity": own.entity_id})
            assert rejected["errors"]["base"] == "invalid_configuration"
            checks.append(
                "planner outputs cannot form feedback loops through configured inputs"
            )
            h.states.async_set("sensor.demo_t", "18", {"unit_of_measurement": "°C"})
            h.states.async_set("sensor.demo_rh", "75", {"unit_of_measurement": "%"})
            h.states.async_set(
                "climate.demo",
                "off",
                {
                    "temperature": 19.5,
                    "current_temperature": 20,
                    "hvac_modes": ["off", "heat", "cool", "dry"],
                    "min_temp": 16,
                    "max_temp": 30,
                    "target_temp_step": 0.5,
                },
            )
            c = ClimateCoordinator(h, entry)
            entry.runtime_data = c
            await c.async_restore()
            data = await c._async_update_data()
            c.async_set_updated_data(data)
            assert data["mode"] == "shadow" and data["physical_control"] is False
            assert data["price_error"] is None
            checks.append("runtime reads real HA state machine in observation mode")
            entities = []
            await sensor.async_setup_entry(h, entry, entities.extend)
            await binary_sensor.async_setup_entry(h, entry, entities.extend)
            assert len(entities) == 9 and len({x.unique_id for x in entities}) == 9
            assert all(x.entity_category.value == "diagnostic" for x in entities)
            for x in entities:
                if isinstance(x, sensor.PlanSensor):
                    x.native_value
                else:
                    x.is_on
            checks.append(
                "nine native entities have stable IDs, values and diagnostic categories"
            )
            diag = await diagnostics.async_get_config_entry_diagnostics(h, entry)
            encoded = json.dumps(diag)
            assert (
                "sensor.demo_t" not in encoded
                and "Demo zone" not in encoded
                and "75.0" not in encoded
            )
            checks.append("diagnostic bundle omits bindings, names and raw readings")
            c.async_listen()
            await c.async_close()
            assert c._remove_listener is None
            checks.append("unload saves versioned state and removes listeners")
        finally:
            await h.async_stop()
    print(
        json.dumps(
            {
                "checks": checks,
                "physical_service_calls": 0,
                "production_config_writes": 0,
            }
        )
    )


asyncio.run(main())
