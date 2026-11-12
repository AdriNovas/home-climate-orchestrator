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
            hass.states.async_set("binary_sensor.fictional_thermal_return", "on")
            for value in ["input_number.fictional_goal", None]:
                option_id, result = await begin("splits", "zone")
                await options.async_configure(option_id, {"zone": zone_id})
                await options.async_configure(
                    option_id, {"next_step_id": "zone_advanced"}
                )
                result = await options.async_configure(
                    option_id,
                    {
                        "heat_goal_entity": value,
                        "off_goal_entity": value,
                        "dry_floor_entity": value,
                        "dry_pause_action": "retain_owned",
                        "feedback_loss_action": "stop",
                        "mode_permission_loss_action": "stop",
                        "thermal_presence_entity": "binary_sensor.fictional_thermal_return",
                    }
                    if value
                    else {
                        "feedback_loss_action": "hold",
                        "dry_pause_action": "stop",
                        "mode_permission_loss_action": "hold",
                    },
                )
                assert result["type"] == "create_entry"
                await hass.async_block_till_done()
                assert (
                    entry.runtime_data.profile["house"]["zones"][0].get(
                        "heat_goal_entity"
                    )
                    == value
                )
                current = entry.runtime_data.profile["house"]["zones"][0]
                assert current.get("thermal_presence_entity") == (
                    "binary_sensor.fictional_thermal_return" if value else None
                )
                assert entry.runtime_data.house.zones[0].thermal_presence_entity == (
                    "binary_sensor.fictional_thermal_return" if value else None
                )
                assert current.get("off_goal_entity") == value
                assert current.get("dry_floor_entity") == value
                assert entry.runtime_data.house.zones[0].dry_floor_entity == value
                assert entry.runtime_data.house.zones[0].dry_pause_action == (
                    "retain_owned" if value else "stop"
                )
                assert current["feedback_loss_action"] == ("stop" if value else "hold")
                assert current["mode_permission_loss_action"] == (
                    "stop" if value else "hold"
                )
                assert entry.runtime_data.house.zones[
                    0
                ].mode_permission_loss_action == ("stop" if value else "hold")
            checks.append(
                "real advanced flow persists/reset both opt-in stop policies and clears optional goals"
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
            hass.states.async_set(
                "climate.fictional_office",
                "off",
                {
                    "friendly_name": "Fictional office AC",
                    "temperature": 21,
                    "current_temperature": 20,
                    "hvac_modes": ["off", "heat", "cool"],
                    "min_temp": 16,
                    "max_temp": 30,
                    "target_temp_step": 0.5,
                },
            )
            option_id, result = await begin("splits", "add_split")
            result = await options.async_configure(
                option_id,
                {
                    "climate_entity": "climate.fictional_office",
                    "temperature_entity": "sensor.fictional_external",
                    "plant": plant_id,
                },
            )
            assert result["type"] == "create_entry"
            await hass.async_block_till_done()
            zones = entry.runtime_data.house.zones
            assert len(zones) == 2 and zones[0].id == zone_id and zones[1].id != zone_id
            checks.append(
                "linking another split from the integration options creates a distinct stable zone"
            )
            hass.states.async_set(
                "humidifier.fictional_dryer", "off",
                {"device_class": "dehumidifier", "min_humidity": 30, "max_humidity": 80},
            )
            for service in ["turn_on", "turn_off", "set_humidity"]:
                hass.services.async_register("humidifier", service, forbidden)
            option_id, result = await begin("splits", "add_dehumidifier")
            result = await options.async_configure(option_id, {
                "name": "Fictional dryer", "humidifier_entity": "humidifier.fictional_dryer",
                "temperature_entity": "sensor.fictional_external",
                "humidity_entity": "sensor.fictional_humidity", "enabled": False,
            })
            assert result["type"] == "create_entry", result
            await hass.async_block_till_done()
            dryer = entry.runtime_data.house.zones[-1]
            assert dryer.dehumidifier_max_s == 5400
            dryer_id = dryer.id
            dryer_identities = {
                e.entity_id: e.unique_id for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            }
            for maximum in [0, 5400, 0]:
                option_id, result = await begin("splits", "zone")
                await options.async_configure(option_id, {"zone": dryer_id})
                result = await options.async_configure(option_id, {"next_step_id": "zone_advanced"})
                # Validate the actual rendered form as well as flow-manager dispatch.
                import voluptuous as vol
                try:
                    result["data_schema"]({"dehumidifier_max_s": -1})
                except vol.Invalid:
                    pass
                else:
                    raise AssertionError("Negative duration accepted")
                values = result["data_schema"]({"dehumidifier_max_s": maximum})
                result = await options.async_configure(option_id, values)
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                assert entry.runtime_data.house.zones[-1].dehumidifier_max_s == maximum
                saved = next(z for z in entry.options["house"]["zones"] if z["id"] == dryer_id)
                assert saved["dehumidifier_max_s"] == maximum
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert entry.runtime_data.house.zones[-1].dehumidifier_max_s == 0
            assert entry.runtime_data.house.zones[-1].id == dryer_id
            assert {
                e.entity_id: e.unique_id for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            } == dryer_identities
            assert not entry.runtime_data.executor.enabled
            checks.append("independent dryer keeps bounded default; unlimited zero survives edit and reload with stable IDs")
            # Exercise every policy selector through the actual flow manager.
            from custom_components.climate_orchestrator.domain.models import POLICY_NUMERIC_BOUNDS
            import voluptuous as vol
            option_id, result = await begin("comfort", "policy", "policy_advanced")
            selectors = {k.schema: v for k, v in result["data_schema"].schema.items()}
            for name, (low, high) in POLICY_NUMERIC_BOUNDS.items():
                field_schema = vol.Schema({vol.Required(name): selectors[name]})
                assert field_schema({name: low})[name] == low, name
                assert field_schema({name: high})[name] == high, name
                for outside in (low - 1, high + 1):
                    try:
                        field_schema({name: outside})
                    except vol.Invalid:
                        pass
                    else:
                        raise AssertionError(f"Out-of-range {name} accepted: {outside}")
            unchanged_options = json.loads(json.dumps(dict(entry.options)))
            result = await options.async_configure(option_id, {"dry_max_s": 1})
            assert result["type"] == "form" and result["errors"]["base"] == "invalid_configuration"
            assert dict(entry.options) == unchanged_options
            result = await options.async_configure(option_id, {"dry_max_s": 0})
            assert result["type"] == "create_entry", result
            await hass.async_block_till_done()
            assert entry.runtime_data.house.policy.dry_max_s == 0
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert entry.runtime_data.house.policy.dry_max_s == 0
            assert not entry.runtime_data.executor.enabled
            checks.append("all 43 numeric policy selectors share domain bounds; cross-field rejection preserves config; unlimited split duration survives reload")
            for concurrent, budget, band, offset in [(True, False, 5, -0.5), (False, True, 0, None)]:
                option_id, result = await begin("comfort", "policy", "policy_advanced")
                import voluptuous as vol
                keys = {"dry_concurrent", "dry_budget_enabled", "dry_humidity_band"}
                schema = vol.Schema({k: v for k, v in result["data_schema"].schema.items()
                                     if k.schema in keys})
                values = schema({"dry_concurrent": concurrent,
                                 "dry_budget_enabled": budget,
                                 "dry_humidity_band": band})
                if offset is not None:
                    values["dry_heat_offset"] = offset
                result = await options.async_configure(option_id, values)
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                policy = entry.runtime_data.house.policy
                assert policy.dry_heat_offset == offset
                assert (policy.dry_concurrent, policy.dry_budget_enabled,
                        policy.dry_humidity_band) == (concurrent, budget, band)
                assert entry.options["house"]["policy"]["dry_budget_enabled"] == budget
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert entry.runtime_data.house.policy.dry_concurrent is False
            assert entry.runtime_data.house.policy.dry_budget_enabled is True
            assert not entry.runtime_data.executor.enabled
            checks.append("dry admission and service-budget options roundtrip through real policy flow/reload without enabling control")
            # N2 controls must survive real schema defaulting, saving and reload,
            # including clearing the optional drop guard rather than reinserting it.
            n2_ids = {
                e.entity_id: e.unique_id for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            }
            for drop, dew, debt in [(0.7, True, False), (None, False, True)]:
                option_id, result = await begin("splits", "zone")
                await options.async_configure(option_id, {"zone": zone_id})
                result = await options.async_configure(
                    option_id, {"next_step_id": "zone_advanced"}
                )
                schema = result["data_schema"]
                if drop is None:
                    key = next(k for k in schema.schema if k.schema == "dry_max_temperature_drop")
                    assert key.description["suggested_value"] == 0.7
                submitted = {"dry_dewpoint_completion": dew}
                if drop is not None:
                    submitted["dry_max_temperature_drop"] = drop
                values = schema(submitted)
                assert values.get("dry_max_temperature_drop") == drop
                result = await options.async_configure(option_id, values)
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                saved = next(z for z in entry.options["house"]["zones"] if z["id"] == zone_id)
                assert saved.get("dry_max_temperature_drop") == drop
                assert saved["dry_dewpoint_completion"] is dew
                option_id, result = await begin("comfort", "policy", "policy_advanced")
                values = result["data_schema"]({"humidity_debt_urgency": debt})
                result = await options.async_configure(option_id, values)
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                assert entry.options["house"]["policy"]["humidity_debt_urgency"] is debt
                assert await hass.config_entries.async_reload(entry.entry_id)
                await hass.async_block_till_done()
                current = next(z for z in entry.runtime_data.house.zones if z.id == zone_id)
                assert current.dry_max_temperature_drop == drop
                assert current.dry_dewpoint_completion is dew
                assert entry.runtime_data.house.policy.humidity_debt_urgency is debt
                assert not entry.runtime_data.executor.enabled
                assert {
                    e.entity_id: e.unique_id for e in registry.entities.values()
                    if e.config_entry_id == entry.entry_id
                } == n2_ids
            checks.append("N2 drop/dew/debt opt-ins enable, clear and reload through real schemas with stable IDs and no control")
            # Purpose-specific forms must actually consume their settings while
            # preserving every other group, optional override and authority.
            from custom_components.climate_orchestrator.config_flow import POLICY_GROUPS
            from dataclasses import asdict, fields
            from custom_components.climate_orchestrator.domain.models import Policy
            names = [name for group in POLICY_GROUPS.values() for name in group]
            assert len(names) == len(set(names))
            assert set(names) == {f.name for f in fields(Policy)} - {"bands"}
            entry.runtime_data.executor.manual(zone_id, "native_options_test")
            await entry.runtime_data.executor.save()
            expected_policy = asdict(entry.runtime_data.house.policy)
            grouped_edits = {
                "policy_thermal": {"start_delta": 0.6},
                "policy_drying": {"dry_heat_offset": -0.5},
                "policy_humidity": {"humidity_stable_s": 1000},
                "policy_power": {"power_limit": 6100},
                "policy_sources": {"temperature_fresh_s": 7000},
                "policy_pricing": {"lookahead_s": 5600},
            }
            for group, edit in grouped_edits.items():
                option_id, result = await begin("comfort", "policy", group)
                assert {key.schema for key in result["data_schema"].schema} == set(POLICY_GROUPS[group])
                values = result["data_schema"](edit)
                expected_policy.update(values)
                result = await options.async_configure(option_id, values)
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                assert asdict(entry.runtime_data.house.policy) == expected_policy
                assert not entry.runtime_data.executor.enabled
                assert entry.runtime_data.executor.state["manual"][zone_id] == "native_options_test"
            # A failed relationship identifies fields, retains submitted values,
            # and never commits a partial group or poisons the next submission.
            for group, edit, error_field, error in [
                ("policy_thermal", {"hold_delta": 5}, "hold_delta", "policy_hysteresis"),
                ("policy_drying", {"dry_max_s": 1}, "dry_max_s", "policy_dry_duration"),
                ("policy_power", {"shared_load_idle_w": 300}, "shared_load_idle_w", "policy_load_order"),
                ("policy_power", {"shared_load_management": True}, "shared_load_management", "policy_requires_hold"),
                ("policy_pricing", {"extreme_price_hysteresis": 0.5}, "extreme_price_hysteresis", "policy_price_margin"),
            ]:
                option_id, result = await begin("comfort", "policy", group)
                before = json.loads(json.dumps(dict(entry.options)))
                result = await options.async_configure(option_id, result["data_schema"](edit))
                assert result["errors"][error_field] == error, result
                assert dict(entry.options) == before
                assert result["data_schema"]({})[error_field] == edit[error_field]
            checks.append("all 49 policy fields grouped once; six real edits preserve other settings and Manual; relational errors stay beside fields without saving")

            # Typed source clocks use the same persisted/runtime contracts as the
            # advanced object. No domestic profile or device is involved.
            from homeassistant.util import dt as dt_util
            source = "sensor.fictional_external"
            other_source = "sensor.fictional_humidity"
            other_contract = {"semantics": "provider"}
            option_id, result = await begin("system", "source_quality", "source_quality_advanced")
            result = await options.async_configure(option_id, {
                "source_quality": {other_source: other_contract},
            })
            assert result["type"] == "create_entry", result
            await hass.async_block_till_done()

            async def clock_form():
                identity, result = await begin("system", "source_quality", "source_clock")
                result = await options.async_configure(identity, {"source": source})
                assert result["step_id"] == "source_clock_edit"
                return identity, result

            option_id, result = await clock_form()
            unchanged = json.loads(json.dumps(dict(entry.options)))
            for submitted, error_field, error in [
                ({"semantics": "origin"}, "timestamp_attribute", "source_clock_required"),
                ({"semantics": "origin", "timestamp_attribute": "measured_at", "timestamp_entity": "sensor.fictional_clock"}, "timestamp_entity", "source_clock_one_route"),
                ({"semantics": "received", "timestamp_attribute": "measured_at"}, "semantics", "source_clock_origin_only"),
            ]:
                result = await options.async_configure(option_id, result["data_schema"](submitted))
                assert result["errors"][error_field] == error, result
                assert dict(entry.options) == unchanged
            stamp = dt_util.utcnow().timestamp() - 15
            hass.states.async_set(source, "20", {
                "unit_of_measurement": "°C", "device_class": "temperature",
                "measured_at": stamp,
            })
            result = await options.async_configure(option_id, result["data_schema"]({
                "semantics": "origin", "timestamp_attribute": "measured_at",
            }))
            assert result["type"] == "create_entry", result
            await hass.async_block_till_done()
            assert entry.runtime_data.source_clock(source, hass.states.get(source)).origin_at == stamp
            assert entry.options["source_quality"][other_source] == other_contract
            # Replace attribute by entity: an omitted suggested value must not
            # silently return through schema defaults.
            hass.states.async_set("sensor.fictional_clock", str(stamp - 10))
            option_id, result = await clock_form()
            values = result["data_schema"]({"semantics": "origin", "timestamp_entity": "sensor.fictional_clock"})
            assert "timestamp_attribute" not in values
            result = await options.async_configure(option_id, values)
            assert result["type"] == "create_entry", result
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert entry.runtime_data.source_clock(source, hass.states.get(source)).origin_at == stamp - 10
            for semantics in ("received", "provider"):
                option_id, result = await clock_form()
                values = result["data_schema"]({"semantics": semantics})
                assert "timestamp_entity" not in values and "timestamp_attribute" not in values
                result = await options.async_configure(option_id, values)
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                assert entry.options["source_quality"][source] == {"semantics": semantics}
                assert entry.runtime_data.source_clock(source, hass.states.get(source)).semantics == semantics
            option_id, result = await clock_form()
            result = await options.async_configure(option_id, result["data_schema"]({"use_default": True}))
            assert result["type"] == "create_entry", result
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert dict(entry.options["source_quality"]) == {other_source: other_contract}
            assert entry.runtime_data.source_clock(source, hass.states.get(source)).semantics == "received"
            assert asdict(entry.runtime_data.house.policy) == expected_policy
            assert entry.runtime_data.executor.state["manual"][zone_id] == "native_options_test"
            assert not entry.runtime_data.executor.enabled
            assert {e.entity_id: e.unique_id for e in registry.entities.values()
                    if e.config_entry_id == entry.entry_id} == n2_ids
            checks.append("typed source clocks reject ambiguous/missing routes; origin attribute/entity and received/provider consume real values; clearing/reload preserves other sources, IDs and Manual")
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
