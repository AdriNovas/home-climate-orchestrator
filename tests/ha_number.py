"""Native number services and profile persistence in a disposable HA only."""

import asyncio
import copy
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
        if p.suffix in [".py", ".json", ".jinja"]
    }


async def main():
    from homeassistant import bootstrap, loader
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
    from homeassistant.helpers import area_registry, entity_registry, label_registry

    checks = []
    with tempfile.TemporaryDirectory(prefix="climate-native-targets-") as folder:
        base = pathlib.Path(folder)
        for name, source in FILES.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        (base / "custom_components/__init__.py").write_text("")
        sys.path.insert(0, folder)
        hass = HomeAssistant(folder)
        hass.config.skip_pip = True
        loader.async_setup(hass)
        try:
            assert (
                await bootstrap.async_from_config_dict(
                    {
                        "homeassistant": {
                            "name": "Fictional home",
                            "latitude": 0,
                            "longitude": 0,
                            "elevation": 0,
                            "time_zone": "Europe/Madrid",
                            "unit_system": "metric",
                        }
                    },
                    hass,
                )
                is hass
            )
            area = area_registry.async_get(hass).async_create("Fictional room")
            label = label_registry.async_get(hass).async_create("Fictional climate")
            hass.states.async_set(
                "sensor.demo_temperature", "20", {"unit_of_measurement": "°C"}
            )
            hass.states.async_set(
                "climate.demo",
                "off",
                {
                    "temperature": 20,
                    "current_temperature": 21,
                    "hvac_modes": ["off", "heat", "cool"],
                    "min_temp": 16,
                    "max_temp": 30,
                    "target_temp_step": 0.5,
                },
            )
            physical_calls = []

            async def forbidden(call):
                physical_calls.append(call.service)
                raise AssertionError(
                    "Number settings must not directly command a climate"
                )

            for service in ["set_temperature", "set_hvac_mode", "turn_off", "turn_on"]:
                hass.services.async_register("climate", service, forbidden)
            profile = {
                "house": {
                    "name": "Demo",
                    "timezone": "Europe/Madrid",
                    "plants": [{"id": "plant", "name": "Demo outdoor"}],
                    "zones": [
                        {
                            "id": "room",
                            "name": "Demo room",
                            "plant": "plant",
                            "climate_entity": "climate.demo",
                            "temperature_entity": "sensor.demo_temperature",
                            "area": area.id,
                            "labels": [label.label_id],
                        }
                    ],
                },
                "tariff": {"type": "flat", "price": 0.15},
                "execution_mode": "shadow",
                "exclusive_control": False,
            }
            entry = ConfigEntry(
                version=1,
                minor_version=1,
                domain="climate_orchestrator",
                title="Demo",
                data=profile,
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()
            assert entry.state is ConfigEntryState.LOADED
            registry = entity_registry.async_get(hass)
            numbers = [
                e
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id and e.domain == "number"
            ]
            assert len(numbers) == 24
            assert all(
                e.entity_category.value == "config"
                and e.area_id == area.id
                and label.label_id in e.labels
                for e in numbers
            )
            assert all(
                hass.states.get(e.entity_id).attributes["unit_of_measurement"] == "°C"
                for e in numbers
            )
            checks.append(
                "four native configuration tables expose six price bands each, with real area, labels and Celsius"
            )
            identities = {e.entity_id: e.unique_id for e in numbers}
            original_runtime = entry.runtime_data

            def target(table, band="normal"):
                return next(
                    e.entity_id
                    for e in numbers
                    if e.unique_id == f"{entry.entry_id}_room_target_{table}_{band}"
                )

            async def set_value(table, value, band="normal"):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": target(table, band), "value": value},
                    blocking=True,
                )

            await asyncio.gather(
                set_value("heat_targets", 20), set_value("heat_sleep_targets", 20)
            )
            await hass.async_block_till_done()
            assert entry.options["house"]["zones"][0]["heat_targets"] == {"normal": 20}
            assert entry.runtime_data is original_runtime
            # Source-driven refreshes are debounced; force one deterministic
            # planning sample instead of depending on wall-clock cooldowns.
            await entry.runtime_data.async_refresh()
            assert entry.runtime_data.data["decisions"]["room"].heat_goal == 20, {
                "decision": repr(entry.runtime_data.data["decisions"]["room"]),
                "runtime_zone": repr(entry.runtime_data.house.zones[0]),
                "saved_zone": entry.options["house"]["zones"][0],
                "tariff": entry.runtime_data.profile["tariff"],
                "state": entry.state.value,
            }
            assert float(hass.states.get(target("heat_targets")).state) == 20
            checks.append(
                "native number.set_value persists the shared options profile and changes the planned ambient goal"
            )
            await asyncio.gather(
                set_value("heat_targets", 21, "low"),
                set_value("cool_targets", 28, "high"),
            )
            await hass.async_block_till_done()
            zone = entry.options["house"]["zones"][0]
            assert (
                zone["heat_targets"]["low"] == 21 and zone["cool_targets"]["high"] == 28
            )
            checks.append(
                "rapid independent edits preserve both cells rather than overwriting a stale profile"
            )
            before = copy.deepcopy(dict(entry.options))
            try:
                await set_value("heat_targets", 26)
            except ServiceValidationError:
                pass
            else:
                raise AssertionError("Heating equal to cooling was accepted")
            assert entry.options == before
            checks.append(
                "crossed heat/cool goals are rejected atomically by the live service"
            )
            from custom_components.climate_orchestrator.number import AmbientTarget

            model = AmbientTarget(
                entry.runtime_data,
                entry.runtime_data.house.zones[0],
                "heat_targets",
                "normal",
                3,
            )
            model.hass = hass
            for invalid in [float("nan"), float("inf"), 4, 36, True]:
                try:
                    await model.async_set_native_value(invalid)
                except ServiceValidationError:
                    pass
                else:
                    raise AssertionError("Invalid numeric goal accepted")
                assert entry.options == before
            checks.append(
                "nonfinite, out-of-range and boolean inputs do not mutate configuration"
            )
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            fid = flow["flow_id"]
            for data in [
                {"next_step_id": "comfort"},
                {"next_step_id": "zone_targets"},
                {"zone": "room", "target_table": "heat_targets"},
                {"override": False},
            ]:
                flow = await hass.config_entries.options.async_configure(fid, data)
                assert not flow.get("errors"), flow
            assert flow["type"] == "create_entry"
            await hass.async_block_till_done()
            await entry.runtime_data.async_refresh()
            assert entry.options["house"]["zones"][0]["heat_targets"] == {}
            assert float(hass.states.get(target("heat_targets")).state) == 19.5
            assert (
                hass.states.get(target("heat_targets")).attributes["inherited"] is True
            )
            checks.append(
                "native OptionsFlow can restore table inheritance and number entities reflect it"
            )
            hass.states.async_set(
                "sensor.external_goal", "21", {"unit_of_measurement": "°C"}
            )
            external = copy.deepcopy(dict(entry.options))
            external["house"]["zones"][0]["heat_goal_entity"] = "sensor.external_goal"
            hass.config_entries.async_update_entry(entry, options=external)
            await hass.async_block_till_done()
            assert hass.states.get(target("heat_targets")).state == "unavailable"
            try:
                await set_value("heat_targets", 20)
            except HomeAssistantError:
                pass
            # Entity services may skip unavailable targets rather than raise.
            assert entry.options == external
            bound = AmbientTarget(
                entry.runtime_data,
                entry.runtime_data.house.zones[0],
                "heat_targets",
                "normal",
                3,
            )
            bound.hass = hass
            try:
                await bound.async_set_native_value(20)
            except ServiceValidationError:
                pass
            else:
                raise AssertionError("The entity handler bypassed the external goal")
            checks.append(
                "an external authoritative goal disables misleading table edits without changing its binding"
            )
            restored = copy.deepcopy(dict(entry.options))
            restored["house"]["zones"][0].pop("heat_goal_entity")
            hass.config_entries.async_update_entry(entry, options=restored)
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert identities == {
                e.entity_id: e.unique_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id and e.domain == "number"
            }
            assert (
                entry.options["execution_mode"] == "shadow"
                and entry.options["exclusive_control"] is False
            )
            assert hass.states.get("climate.demo").state == "off"
            assert not physical_calls
            checks.append(
                "reload retains number identities, shadow authority and the unchanged actuator"
            )
            from custom_components.climate_orchestrator.binary_sensor import (
                ExecutionProblem,
            )

            problem = ExecutionProblem(entry.runtime_data, None, "execution_problem")
            for reason in ["user_pause", "external_authority", "external_command"]:
                entry.runtime_data.executor.state["manual"] = {"room": reason}
                assert problem.is_on is False
            entry.runtime_data.executor.state["manual"] = {
                "room": "restart_unconfirmed"
            }
            assert problem.is_on is True
            entry.runtime_data.executor.state["manual"] = {}
            checks.append(
                "normal Manual choices are not faults, while unconfirmed recovery remains actionable"
            )
            print(
                json.dumps(
                    {
                        "checks": checks,
                        "native_editable_goals": len(numbers),
                        "physical_service_calls": len(physical_calls),
                        "production_config_writes": 0,
                    }
                )
            )
        finally:
            await hass.async_stop()


asyncio.run(asyncio.wait_for(main(), timeout=60))
