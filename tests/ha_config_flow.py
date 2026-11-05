"""Exercise the actual native flow managers, not direct step method fixtures.

Uses a temporary HA, fictional driver and entities. No production files, network
devices or credentials are loaded. All climate service calls are forbidden.
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
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import area_registry, device_registry, entity_registry

    checks = []
    with tempfile.TemporaryDirectory(prefix="climate-native-config-") as folder:
        base = pathlib.Path(folder)
        for name, source in FILES.items():
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        (base / "custom_components/__init__.py").write_text("")
        vendor = base / "custom_components/fictional_hvac"
        vendor.mkdir()
        (vendor / "manifest.json").write_text(
            json.dumps(
                {
                    "domain": "fictional_hvac",
                    "name": "Fictional HVAC",
                    "version": "1.0.0",
                    "codeowners": [],
                    "requirements": [],
                }
            )
        )
        (vendor / "__init__.py").write_text(
            "async def async_setup_entry(hass, entry):\n return True\n"
        )
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
            physical_entry = ConfigEntry(
                version=1,
                minor_version=1,
                domain="fictional_hvac",
                title="Fictional driver",
                data={},
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            await hass.config_entries.async_add(physical_entry)
            area = area_registry.async_get(hass).async_create("Fictional living room")
            devices = device_registry.async_get(hass)
            physical = devices.async_get_or_create(
                config_entry_id=physical_entry.entry_id,
                identifiers={("fictional_hvac", "indoor-1")},
                name="Fictional living AC",
            )
            devices.async_update_device(physical.id, area_id=area.id)
            registry = entity_registry.async_get(hass)
            climate = registry.async_get_or_create(
                "climate",
                "fictional_hvac",
                "indoor-1",
                config_entry=physical_entry,
                device_id=physical.id,
                original_name="Fictional living AC",
                suggested_object_id="fictional_living",
            )
            hass.states.async_set(
                climate.entity_id,
                "off",
                {
                    "temperature": 22,
                    "current_temperature": 24,
                    "hvac_modes": ["off", "heat", "cool", "dry"],
                    "min_temp": 16,
                    "max_temp": 30,
                    "target_temp_step": 0.5,
                },
            )
            hass.states.async_set(
                "sensor.fictional_external",
                "20",
                {"unit_of_measurement": "°C", "device_class": "temperature"},
            )
            hass.states.async_set(
                "sensor.fictional_humidity",
                "65",
                {"unit_of_measurement": "%", "device_class": "humidity"},
            )
            hass.states.async_set(
                "sensor.wrong_measure",
                "100",
                {"unit_of_measurement": "W", "device_class": "power"},
            )
            service_calls = []

            async def forbidden(call):
                service_calls.append(call.service)
                raise AssertionError("Onboarding must never command equipment")

            for service in ["set_hvac_mode", "set_temperature", "turn_on", "turn_off"]:
                hass.services.async_register("climate", service, forbidden)

            flows = hass.config_entries.flow
            result = await flows.async_init(
                "climate_orchestrator", context={"source": "user"}
            )
            assert result["step_id"] == "user"
            flow_id = result["flow_id"]
            result = await flows.async_configure(
                flow_id,
                {
                    "name": "Fictional house",
                    "timezone": "Europe/Madrid",
                    "tariff_type": "flat",
                },
            )
            assert result["step_id"] == "tariff"
            result = await flows.async_configure(flow_id, {"price": 0.15})
            assert result["step_id"] == "plant"
            assert {key.schema for key in result["data_schema"].schema} == {
                "name",
                "shared_mode",
            }
            result = await flows.async_configure(
                flow_id, {"name": "Fictional outdoor", "shared_mode": True}
            )
            assert result["step_id"] == "split"
            fields = {key.schema for key in result["data_schema"].schema}
            assert fields == {
                "name",
                "plant",
                "climate_entity",
                "temperature_entity",
                "humidity_entity",
                "area",
                "labels",
            }
            plant_id = next(
                key.default()
                for key in result["data_schema"].schema
                if key.schema == "plant"
            )
            bad = await flows.async_configure(
                flow_id,
                {
                    "climate_entity": climate.entity_id,
                    "temperature_entity": "sensor.wrong_measure",
                    "plant": plant_id,
                },
            )
            assert bad["errors"]["temperature_entity"] == "invalid_unit"
            result = await flows.async_configure(
                flow_id,
                {
                    "climate_entity": climate.entity_id,
                    "temperature_entity": "sensor.fictional_external",
                    "humidity_entity": "sensor.fictional_humidity",
                    "plant": plant_id,
                },
            )
            assert result["type"] == "menu" and result["step_id"] == "finish"
            result = await flows.async_configure(flow_id, {"next_step_id": "create"})
            entry = result["result"]
            await hass.async_block_till_done()
            assert entry.state is ConfigEntryState.LOADED
            zone = entry.data["house"]["zones"][0]
            assert zone["area"] == area.id and zone["name"] == "Fictional living AC"
            assert entry.runtime_data.executor.enabled is False and not service_calls
            checks.append(
                "native add-integration wizard links existing split and external probes in observation"
            )
            checks.append(
                "simple initial forms validate units and infer only real registry name/area"
            )
            zone_id = zone["id"]
            identities = {
                e.entity_id: e.unique_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            }
            own_devices = device_registry.async_entries_for_config_entry(
                devices, entry.entry_id
            )
            assert own_devices and all(
                d.configuration_url
                == "homeassistant://config/integrations/integration/climate_orchestrator"
                for d in own_devices
            )
            assert all(
                d.entry_type is device_registry.DeviceEntryType.SERVICE
                for d in own_devices
            )
            zone_device = next(
                d
                for d in own_devices
                if ("climate_orchestrator", f"{entry.entry_id}:{zone_id}")
                in d.identifiers
            )
            assert zone_device.area_id == area.id
            assert physical.id in {
                d.id
                for d in device_registry.async_entries_for_config_entry(
                    devices, physical_entry.entry_id
                )
            }
            assert physical.id not in {d.id for d in own_devices}
            checks.append(
                "logical regulation devices expose native configuration without claiming vendor device ownership"
            )

            options = hass.config_entries.options

            async def begin(*menus):
                result = await options.async_init(entry.entry_id)
                identity = result["flow_id"]
                for menu in menus:
                    result = await options.async_configure(
                        identity, {"next_step_id": menu}
                    )
                return identity, result

            option_id, result = await begin("splits", "add_split")
            duplicate = await options.async_configure(
                option_id,
                {
                    "climate_entity": climate.entity_id,
                    "temperature_entity": "sensor.fictional_external",
                    "plant": plant_id,
                },
            )
            assert (
                duplicate["errors"]["climate_entity"] == "already_configured"
                and len(entry.runtime_data.house.zones) == 1
            )
            options.async_abort(option_id)
            checks.append(
                "duplicate actuator binding stays in form without changing persisted configuration"
            )

            option_id, result = await begin("splits", "zone")
            result = await options.async_configure(option_id, {"zone": zone_id})
            assert (
                result["type"] == "menu"
                and result["description_placeholders"]["name"] == zone["name"]
            )
            result = await options.async_configure(
                option_id, {"next_step_id": "zone_binding"}
            )
            result = await options.async_configure(
                option_id,
                {
                    "name": "Renamed room",
                    "climate_entity": climate.entity_id,
                    "temperature_entity": "sensor.fictional_external",
                    "plant": plant_id,
                },
            )
            assert result["type"] == "create_entry"
            await hass.async_block_till_done()
            profile = entry.runtime_data.profile
            zone = profile["house"]["zones"][0]
            assert zone["id"] == zone_id and not zone.get("humidity_entity")
            assert {
                e.entity_id: e.unique_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            } == identities
            checks.append(
                "native reconfiguration can clear optional humidity without changing any entity identity"
            )

            for step, table, field in [
                ("heat_day", "heat_targets", "heat_day"),
                ("cool_day", "cool_targets", "cool_day"),
                ("heat_sleep", "heat_sleep_targets", "heat_sleep"),
                ("cool_sleep", "cool_sleep_targets", "cool_sleep"),
            ]:
                option_id, result = await begin("splits", "zone")
                await options.async_configure(option_id, {"zone": zone_id})
                await options.async_configure(
                    option_id, {"next_step_id": "zone_targets_menu"}
                )
                result = await options.async_configure(
                    option_id, {"next_step_id": step}
                )
                assert result["description_placeholders"]["name"] == "Renamed room"
                bands = entry.runtime_data.house.policy.bands
                values = {b.name: getattr(b, field) for b in bands}
                result = await options.async_configure(
                    option_id, {"override": True, **values}
                )
                assert result["type"] == "create_entry"
                await hass.async_block_till_done()
                assert entry.runtime_data.profile["house"]["zones"][0][table] == values
            checks.append(
                "all four seasonal day/sleep tables are editable through each split native menu"
            )
            option_id, result = await begin("splits", "zone")
            await options.async_configure(option_id, {"zone": zone_id})
            result = await options.async_configure(
                option_id, {"next_step_id": "zone_advanced"}
            )
            assert not (
                {
                    "climate_entity",
                    "temperature_entity",
                    "humidity_entity",
                    "name",
                    "plant",
                    "area",
                }
                & {key.schema for key in result["data_schema"].schema}
            )
            options.async_abort(option_id)
            checks.append(
                "advanced permissions are separate from everyday split/probe bindings"
            )
            hass.states.async_set(
                "input_number.fictional_goal", "21", {"unit_of_measurement": "°C"}
            )
            for value in ["input_number.fictional_goal", None]:
                option_id, result = await begin("splits", "zone")
                await options.async_configure(option_id, {"zone": zone_id})
                await options.async_configure(
                    option_id, {"next_step_id": "zone_advanced"}
                )
                result = await options.async_configure(
                    option_id, {"heat_goal_entity": value} if value else {}
                )
                assert result["type"] == "create_entry"
                await hass.async_block_till_done()
                assert (
                    entry.runtime_data.profile["house"]["zones"][0].get(
                        "heat_goal_entity"
                    )
                    == value
                )
            checks.append(
                "advanced external goals can be assigned and genuinely cleared through native forms"
            )
            hass.states.async_set(
                "sensor.fictional_supply", "100", {"unit_of_measurement": "W"}
            )
            for value in ["sensor.fictional_supply", None]:
                option_id, result = await begin("system", "sources")
                result = await options.async_configure(
                    option_id, {"power_entity": value} if value else {}
                )
                assert result["type"] == "create_entry"
                await hass.async_block_till_done()
                assert entry.runtime_data.profile.get("power_entity") == value
            checks.append(
                "optional shared inputs use suggestions rather than restoring cleared bindings"
            )
            assert not service_calls
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            assert devices.async_get(physical.id) is not None
            assert registry.async_get(climate.entity_id) is not None
            assert not any(
                e.config_entry_id == entry.entry_id for e in registry.entities.values()
            )
            checks.append(
                "removing orchestration preserves the vendor device and physical entity"
            )
        finally:
            await hass.async_stop()
    print(
        json.dumps(
            {
                "checks": checks,
                "physical_service_calls": len(service_calls),
                "production_config_writes": 0,
            }
        )
    )


asyncio.run(asyncio.wait_for(main(), timeout=60))
