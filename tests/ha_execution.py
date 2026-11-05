"""Real HA lifecycle and service protocol, using only fictional state entities.

The only registered climate services below are local Python stubs. No production
configuration, credentials, device integrations or network clients are loaded.
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
        if p.suffix in [".py", ".json", ".jinja"]
    }


async def main():
    from homeassistant import bootstrap, loader
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant, Context
    from homeassistant.helpers import entity_registry
    from homeassistant.util import dt

    with tempfile.TemporaryDirectory(prefix="climate-execution-") as folder:
        base = pathlib.Path(folder)
        for name, source in FILES.items():
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        (base / "custom_components/__init__.py").write_text("")
        sys.path.insert(0, folder)
        hass = HomeAssistant(folder)
        hass.config.skip_pip = True
        loader.async_setup(hass)
        checks, calls = [], []
        try:
            await bootstrap.async_from_config_dict(
                {
                    "homeassistant": {
                        "name": "Fictional lab",
                        "latitude": 0,
                        "longitude": 0,
                        "elevation": 0,
                        "time_zone": "Europe/Madrid",
                        "unit_system": "metric",
                    }
                },
                hass,
            )
            from custom_components.climate_orchestrator.config_flow import (
                ClimateOptions,
            )
            from custom_components.climate_orchestrator.diagnostics import (
                async_get_config_entry_diagnostics,
            )
            from custom_components.climate_orchestrator.validation import (
                validate_sources,
            )

            for entity, value, attrs in [
                ("sensor.demo_t", "18", {"unit_of_measurement": "°C"}),
                ("sensor.demo_goal", "22", {"unit_of_measurement": "°C"}),
                ("input_number.demo_bias", "1", {"unit_of_measurement": "°C"}),
                ("input_boolean.demo_control", "on", {}),
                ("input_select.demo_authority", "Automatic", {}),
                ("binary_sensor.demo_heat", "on", {}),
                (
                    "sensor.demo_power",
                    "1.2",
                    {
                        "unit_of_measurement": "kW",
                        "device_class": "power",
                        "state_class": "measurement",
                    },
                ),
                (
                    "sensor.demo_energy",
                    "2000",
                    {
                        "unit_of_measurement": "Wh",
                        "device_class": "energy",
                        "state_class": "total_increasing",
                    },
                ),
                ("sensor.demo_supply", "2500", {"unit_of_measurement": "W"}),
                ("input_boolean.demo_cut", "off", {}),
                ("input_text.demo_expected", '{"q":[]}', {}),
                ("input_text.demo_external_cut", "{}", {}),
            ]:
                hass.states.async_set(entity, value, attrs)
            climate_attrs = {
                "temperature": 19.5,
                "current_temperature": 20,
                "hvac_modes": ["off", "heat", "cool", "dry"],
                "min_temp": 16,
                "max_temp": 30,
                "target_temp_step": 0.5,
                "supported_features": 1,
            }
            hass.states.async_set("climate.demo", "off", climate_attrs)

            verify_journal = True

            async def simulated_service(call):
                entity = call.data["entity_id"]
                journals = [
                    s
                    for s in hass.states.async_all("sensor")
                    if s.attributes.get("schema_version") == 1
                    and s.attributes.get("actuator") == entity
                ]
                if verify_journal:
                    assert len(journals) == 1, journals
                    assert journals[0].state == "sending", journals[0]
                    assert journals[0].attributes["expected"], journals[0]
                state = hass.states.get(entity)
                attrs = dict(state.attributes)
                if "temperature" in call.data:
                    attrs["temperature"] = call.data["temperature"]
                calls.append({"service": call.service, "data": dict(call.data)})
                hass.states.async_set(
                    entity,
                    call.data.get("hvac_mode", state.state),
                    attrs,
                    context=call.context,
                )

            hass.services.async_register(
                "climate", "set_temperature", simulated_service
            )
            hass.services.async_register("climate", "set_hvac_mode", simulated_service)
            profile = {
                "house": {
                    "name": "Demo",
                    "timezone": "Europe/Madrid",
                    "plants": [
                        {
                            "id": "plant",
                            "name": "Shared unit",
                            "minimum_off_s": 0,
                            "minimum_on_s": 0,
                            "direction_hold_s": 0,
                            "reversal_gap_s": 0,
                        }
                    ],
                    "zones": [
                        {
                            "id": "room",
                            "name": "Demo room",
                            "plant": "plant",
                            "temperature_entity": "sensor.demo_t",
                            "climate_entity": "climate.demo",
                            "authority_entity": "input_select.demo_authority",
                            "authority_states": ["Automatic"],
                            "heat_goal_entity": "sensor.demo_goal",
                            "bias_entity": "input_number.demo_bias",
                            "heat_permission_entity": "binary_sensor.demo_heat",
                            "expected_ledger_entity": "input_text.demo_expected",
                        }
                    ],
                },
                "tariff": {"type": "flat", "price": 0.15},
                "control_entity": "input_boolean.demo_control",
                "critical_entity": "input_boolean.demo_cut",
                "external_cut_entity": "input_text.demo_external_cut",
                "power_entity": "sensor.demo_supply",
                "execution_mode": "control",
                "exclusive_control": True,
                "meters": [
                    {
                        "id": "shared",
                        "name": "Shared HVAC meter",
                        "scope": "plant",
                        "target": "plant",
                        "power_entity": "sensor.demo_power",
                        "energy_entity": "sensor.demo_energy",
                        "fresh_s": 120,
                    }
                ],
            }
            for changes in [
                {"control_entity": None},
                {"exclusive_control": False},
                {"execution_mode": "invalid"},
            ]:
                try:
                    validate_sources(hass, {**profile, **changes})
                except ValueError:
                    pass
                else:
                    raise AssertionError(changes)
            checks.append(
                "execution requires a global permission and explicit exclusive-control configuration"
            )

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
            await asyncio.wait_for(hass.config_entries.async_add(entry), 5)
            assert entry.state is ConfigEntryState.LOADED
            await asyncio.wait_for(hass.async_block_till_done(), 5)
            c = entry.runtime_data
            await c.async_refresh()
            if c._worker:
                await asyncio.wait_for(c._worker, 3)
            await hass.async_block_till_done()
            assert hass.states.get("climate.demo").state == "heat", (
                c.data,
                c.executor.errors,
                calls,
            )
            assert [x["service"] for x in calls] == [
                "set_temperature",
                "set_hvac_mode",
            ], calls
            assert calls[0]["data"]["temperature"] == 24
            assert c.executor.state["pending"]["room"]["phase"] == "acked"
            assert c.executor.is_automatic("room")
            checks.append(
                "native HA service dispatch confirms target before mode without falsely entering Manual"
            )
            checks.append(
                "persisted journal is visible in HA before each simulated physical call"
            )
            assert c.data["metering"]["shared"] == {
                "power": 1200,
                "energy": 2,
                "cost_rate": 0.18,
                "scope": "plant",
                "target": "plant",
            }
            registry = entity_registry.async_get(hass)
            entities = [
                e
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            ]
            meter_entities = [e for e in entities if "_meter_shared_" in e.unique_id]
            assert len(meter_entities) == 3
            assert all(hass.states.get(e.entity_id) is not None for e in meter_entities)
            energy = next(e for e in meter_entities if e.unique_id.endswith("_energy"))
            assert (
                hass.states.get(energy.entity_id).attributes["state_class"]
                == "total_increasing"
            )
            assert hass.states.get("sensor.demo_energy").state == "2000"
            checks.append(
                "native scoped sensors normalize kW/Wh and preserve original counter and statistics metadata"
            )

            from homeassistant.exceptions import ConfigEntryError
            from custom_components.climate_orchestrator import async_setup_entry

            duplicate = ConfigEntry(
                version=1,
                minor_version=1,
                domain="climate_orchestrator",
                title="Duplicate",
                data=json.loads(json.dumps(profile)),
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            before = len(calls)
            try:
                await async_setup_entry(hass, duplicate)
            except ConfigEntryError:
                pass
            else:
                raise AssertionError("duplicate actuator control was accepted")
            assert len(calls) == before
            checks.append(
                "a second active entry cannot acquire or command the same actuator"
            )

            options = ClimateOptions(entry)
            options.hass = hass
            for method in [
                options.async_step_sources,
                options.async_step_execution,
                options.async_step_energy,
            ]:
                result = await method()
                assert result["type"] == "form"
            await options.async_step_zone({"zone": "room"})
            result = await options.async_step_zone_edit()
            result["data_schema"](
                {
                    "name": "Demo room",
                    "plant": "plant",
                    "temperature_entity": "sensor.demo_t",
                    "authority_entity": "input_select.demo_authority",
                    "authority_states": ["Automatic"],
                }
            )
            await options.async_step_energy({"meter": "shared"})
            edited = await options.async_step_meter_edit(
                {
                    "name": "Shared HVAC meter",
                    "scope_target": "plant:plant",
                    "power_entity": "sensor.demo_power",
                    "energy_entity": "sensor.demo_energy",
                    "fresh_s": 300,
                    "remove": False,
                }
            )
            assert (
                edited["type"] == "create_entry"
                and edited["data"]["meters"][0]["id"] == "shared"
            )
            options = ClimateOptions(entry)
            options.hass = hass
            await options.async_step_energy({"meter": "new"})
            duplicate = await options.async_step_meter_edit(
                {
                    "name": "Double count",
                    "scope_target": "zone:room",
                    "power_entity": "sensor.demo_power",
                    "fresh_s": 120,
                    "remove": False,
                }
            )
            assert duplicate["errors"]["base"] == "invalid_configuration"
            assert len(options.profile["meters"]) == 1
            checks.append(
                "native forms edit bindings and reject duplicate shared-meter assignments atomically"
            )

            # A retained registered correction is not a person. Pause ordinary
            # work while exercising the external detector interoperability.
            hass.states.async_set("input_boolean.demo_control", "off")
            await hass.async_block_till_done()
            old_target = hass.states.get("climate.demo").attributes["temperature"]
            ledger = {"q": [[1, old_target, 1, 23, dt.utcnow().timestamp() + 20, 0]]}
            hass.states.async_set("input_text.demo_expected", json.dumps(ledger))
            attrs = dict(hass.states.get("climate.demo").attributes)
            attrs["temperature"] = 23
            hass.states.async_set("climate.demo", "heat", attrs, context=Context())
            await hass.async_block_till_done()
            assert c.executor.is_automatic("room")
            assert (
                json.loads(hass.states.get("input_text.demo_expected").state) == ledger
            )
            checks.append(
                "registered external correction preserves authority without writing or renewing its ledger"
            )

            # Simulate a real user change with a distinct user context.
            attrs = dict(hass.states.get("climate.demo").attributes)
            attrs["temperature"] = 21
            hass.states.async_set(
                "climate.demo", "heat", attrs, context=Context(user_id="fictional-user")
            )
            await hass.async_block_till_done()
            assert not c.executor.is_automatic("room")
            before = len(calls)
            await c.async_refresh()
            await hass.async_block_till_done()
            assert len(calls) == before
            checks.append(
                "a user command latches local Manual and is not overwritten by the next review"
            )
            same_user = hass.states.get("climate.demo").context
            await c.executor.resume("room")
            attrs["temperature"] = calls[0]["data"]["temperature"]
            hass.states.async_set("climate.demo", "heat", attrs, context=same_user)
            await hass.async_block_till_done()
            assert not c.executor.is_automatic("room")
            checks.append(
                "a second target change with the same human context cannot be consumed as an old automatic ACK"
            )

            hass.states.async_set("input_boolean.demo_cut", "on")
            await hass.async_block_till_done()
            if c._safety_worker:
                await asyncio.wait_for(c._safety_worker, 3)
            await asyncio.gather(*list(c.executor.off_tasks.values()))
            await hass.async_block_till_done()
            assert hass.states.get("climate.demo").state == "off"
            assert c.executor.state["critical"]
            assert calls[-1]["data"]["hvac_mode"] == "off"
            checks.append("independent critical cutoff stops an assigned Manual zone")

            # An input_select mapping other than on/off remains usable, but unknown
            # is never interpreted as permission. Source failure is not a default.
            hass.states.async_set("sensor.demo_goal", "unavailable")
            hass.states.async_set("input_boolean.demo_control", "off")
            await c.executor.resume("room")
            await c.async_refresh()
            assert c.snapshot().paused
            assert not c.snapshot().zones["room"].goals_valid
            checks.append(
                "external goals fail closed and global pause remains effective"
            )

            from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

            metric_units = hass.config.units
            hass.config.units = US_CUSTOMARY_SYSTEM
            hass.states.async_set(
                "climate.demo",
                "off",
                {
                    **climate_attrs,
                    "temperature": 68,
                    "current_temperature": 70,
                    "min_temp": 60,
                    "max_temp": 86,
                    "target_temp_step": 1,
                },
            )
            converted = c.snapshot().zones["room"]
            assert abs(converted.setpoint - 20) < 0.001
            assert abs(converted.step - 5 / 9) < 0.001
            verify_journal = (
                False  # Adapter-only conversion check, not executor dispatch.
            )
            await c.emit(
                c.house.zones[0],
                "set_temperature",
                {"temperature": 20},
                "fictional-conversion",
            )
            verify_journal = True
            assert calls[-1]["data"]["temperature"] == 68
            hass.config.units = metric_units
            hass.states.async_set("climate.demo", "off", climate_attrs)
            checks.append(
                "native Fahrenheit adapter converts setpoints and increments in both directions"
            )

            report = await async_get_config_entry_diagnostics(hass, entry)
            assert report["meter_count"] == 1 and report["physical_control"]
            assert "sensor.demo" not in json.dumps(
                report
            ) and "Demo room" not in json.dumps(report)
            checks.append(
                "support diagnostics expose counts, never assigned entities or home telemetry"
            )
            identities = {e.entity_id: e.unique_id for e in entities}
            c.executor.manual("room", "user_pause")
            await c.executor.save()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert {
                e.entity_id: e.unique_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            } == identities
            assert (
                not entry.runtime_data.executor.is_automatic("room")
                and entry.runtime_data.executor.state["critical"]
            )
            checks.append(
                "reload preserves identities, Manual state and the critical-cut journal"
            )
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            assert not (
                base / ".storage" / f"climate_orchestrator.{entry.entry_id}.executor"
            ).exists()
            assert not hass.data.get("climate_orchestrator")
            assert hass.states.get("sensor.demo_energy").state == "2000"
            checks.append(
                "removal deletes only own journals/claims and preserves original consumption entities"
            )
            print(
                json.dumps(
                    {
                        "checks": checks,
                        "native_entities": len(entities),
                        "simulated_climate_calls": len(calls),
                        "physical_service_calls": 0,
                        "production_config_writes": 0,
                        "ha_time": dt.utcnow().isoformat(),
                    }
                )
            )
        finally:
            await hass.async_stop()


asyncio.run(asyncio.wait_for(main(), timeout=60))
