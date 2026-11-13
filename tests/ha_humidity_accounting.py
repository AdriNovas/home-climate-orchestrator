"""Real native flows/services and persistence; only fictional appliances."""

import asyncio
import copy
import json
import pathlib
import sys
import tempfile
from dataclasses import replace
from datetime import timedelta
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
    from homeassistant.helpers import entity_registry, device_registry
    from homeassistant.util import dt

    checks = []
    with tempfile.TemporaryDirectory(prefix="climate-humidity-accounting-") as folder:
        base = pathlib.Path(folder)
        for name, source in FILES.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        (base / "custom_components/__init__.py").write_text("")
        vendor_dir = base / "custom_components/fictional_dryer"
        vendor_dir.mkdir()
        (vendor_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "domain": "fictional_dryer",
                    "name": "Fictional dryer",
                    "version": "1.0.0",
                    "documentation": "https://example.com",
                    "codeowners": [],
                    "requirements": [],
                }
            )
        )
        (vendor_dir / "__init__.py").write_text(
            "async def async_setup_entry(hass, entry):\n return True\n"
        )
        sys.path.insert(0, folder)
        hass = HomeAssistant(folder)
        hass.config.skip_pip = True
        loader.async_setup(hass)
        try:
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
            hass.states.async_set(
                "sensor.room_temperature", "22", {"unit_of_measurement": "°C"}
            )
            hass.states.async_set(
                "sensor.bath_temperature", "18", {"unit_of_measurement": "°C"}
            )
            hass.states.async_set(
                "sensor.bath_humidity", "50", {"unit_of_measurement": "%"}
            )
            hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
            hass.states.async_set(
                "sensor.energy",
                "100",
                {"unit_of_measurement": "kWh", "state_class": "total_increasing"},
            )
            hass.states.async_set("input_boolean.allow", "on")
            hass.states.async_set(
                "climate.demo",
                "off",
                {
                    "temperature": 20,
                    "current_temperature": 22,
                    "hvac_modes": ["off", "heat", "cool"],
                    "min_temp": 16,
                    "max_temp": 30,
                },
            )
            attrs = {
                "device_class": "dehumidifier",
                "humidity": 60,
                "min_humidity": 35,
                "max_humidity": 85,
            }
            hass.states.async_set("humidifier.demo", "off", attrs)
            hass.states.async_set(
                "humidifier.wet", "off", {**attrs, "device_class": "humidifier"}
            )
            driver = ConfigEntry(
                version=1,
                minor_version=1,
                domain="fictional_dryer",
                title="Fictional vendor",
                data={},
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            await hass.config_entries.async_add(driver)
            vendor = device_registry.async_get(hass).async_get_or_create(
                config_entry_id=driver.entry_id,
                identifiers={("fictional_vendor", "dryer")},
                name="Fictional physical dryer",
            )
            # Preserve an independent physical registry device when orchestration is removed.
            entity_registry.async_get(hass).async_get_or_create(
                "humidifier",
                "fictional_vendor",
                "dryer",
                suggested_object_id="demo",
                device_id=vendor.id,
            )
            profile = {
                "house": {
                    "name": "Demo",
                    "timezone": "Europe/Madrid",
                    "plants": [{"id": "plant", "name": "Shared outdoor"}],
                    "zones": [
                        {
                            "id": "room",
                            "name": "Room",
                            "plant": "plant",
                            "temperature_entity": "sensor.room_temperature",
                            "climate_entity": "climate.demo",
                        }
                    ],
                },
                "tariff": {"type": "flat", "price": 0.15},
                "meters": [
                    {
                        "id": "meter",
                        "name": "Measured shared circuit",
                        "scope": "plant",
                        "target": "plant",
                        "power_entity": "sensor.power",
                        "energy_entity": "sensor.energy",
                    }
                ],
                "execution_mode": "shadow",
                "exclusive_control": False,
                "control_entity": "input_boolean.allow",
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
            options = hass.config_entries.options
            flow = await options.async_init(entry.entry_id)
            fid = flow["flow_id"]
            for data in [
                {"next_step_id": "splits"},
                {"next_step_id": "add_dehumidifier"},
            ]:
                flow = await options.async_configure(fid, data)
            data = {
                "name": "Bath dryer",
                "humidifier_entity": "humidifier.wet",
                "temperature_entity": "sensor.bath_temperature",
                "humidity_entity": "sensor.bath_humidity",
                "enabled": False,
            }
            bad = await options.async_configure(fid, data)
            assert bad["errors"]["humidifier_entity"] == "not_dehumidifier"
            flow = await options.async_configure(
                fid, {**data, "humidifier_entity": "humidifier.demo"}
            )
            assert flow["type"] == "create_entry"
            await hass.async_block_till_done()
            zone = entry.options["house"]["zones"][-1]
            plant = next(
                p for p in entry.options["house"]["plants"] if p["id"] == zone["plant"]
            )
            assert not plant["shared_mode"] and not zone["enabled"]
            assert entry.runtime_data.snapshot().zones[zone["id"]].mode == "off"
            checks.append(
                "native options add a paused standalone dehumidifier with its own compressor; water-adding humidifiers rejected"
            )
            registry = entity_registry.async_get(hass)
            rows = [
                e
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            ]
            targets = [
                e
                for e in rows
                if e.unique_id.startswith(f"{entry.entry_id}_{zone['id']}_target_")
            ]
            assert len(targets) == 12 and all(
                "humidity" in e.unique_id for e in targets
            )
            stop = next(
                e
                for e in targets
                if e.unique_id.endswith("humidity_stop_targets_normal")
            )
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": stop.entity_id, "value": 55},
                blocking=True,
            )
            await hass.async_block_till_done()
            assert (
                hass.states.get(stop.entity_id).attributes["unit_of_measurement"] == "%"
            )
            assert (
                entry.options["house"]["zones"][-1]["humidity_stop_targets"]["normal"]
                == 55
            )
            checks.append(
                "twelve native humidity cells per standalone device persist through the same validated options profile"
            )
            flow = await options.async_init(entry.entry_id)
            fid = flow["flow_id"]
            for data in [
                {"next_step_id": "splits"},
                {"next_step_id": "zone"},
                {"zone": zone["id"]},
                {"next_step_id": "zone_targets_menu"},
            ]:
                flow = await options.async_configure(fid, data)
            assert set(flow["menu_options"]) == {"humidity"}
            flow = await options.async_configure(fid, {"next_step_id": "humidity"})
            flow = await options.async_configure(fid, {"band": "negative"})
            bad = await options.async_configure(
                fid, {"humidity_start": 60, "humidity_stop": 60, "use_common": False}
            )
            assert bad["errors"]["base"] == "invalid_humidity_pair"
            flow = await options.async_configure(
                fid, {"humidity_start": 60, "humidity_stop": 55, "use_common": False}
            )
            assert flow["type"] == "create_entry"
            await hass.async_block_till_done()
            paired = entry.options["house"]["zones"][-1]
            assert paired["humidity_start_targets"]["negative"] == 60
            assert paired["humidity_stop_targets"]["negative"] == 55
            checks.append(
                "per-device native menu hides irrelevant thermal tables; paired humidity edits validate both thresholds atomically"
            )
            config_entity = next(
                e for e in rows if e.translation_key == "configuration"
            )
            config = hass.states.get(config_entity.entity_id)
            assert config.state == "shadow" and config.attributes["schema_version"] == 1
            assert config.attributes["policy"]["dry_min_s"] == 1200
            # Prove the runtime diagnostic reports the distribution version,
            # not a stale constant left over from a previous prerelease.
            from custom_components.climate_orchestrator.const import VERSION
            manifest = json.loads((base / "custom_components/climate_orchestrator/manifest.json").read_text())
            assert config.attributes["version"] == VERSION == manifest["version"]
            assert "control_entity" not in config.attributes
            published = config.attributes["zones"][zone["id"]]
            assert published == {
                "actuator_entity": "humidifier.demo",
                "temperature_entity": "sensor.bath_temperature",
                "humidity_entity": "sensor.bath_humidity",
                "enabled": False,
                "night_allowed": True,
                "humidity_basis": "room",
                "drying_availability": "occupied",
            }
            checks.append(
                "read-only validated policy surface supports explicit external consumers without granting authority or exposing credentials"
            )
            c = entry.runtime_data
            assert c.data["system_accounting"]["unmetered_zones"] == [zone["id"]]
            periods = [e for e in rows if e.translation_key.startswith("period_")]
            assert len(periods) == 20
            yesterday = next(
                e
                for e in periods
                if e.unique_id.endswith("_meter_meter_energy_yesterday")
            )
            assert hass.states.get(yesterday.entity_id).state == "unknown"
            assert (
                hass.states.get(yesterday.entity_id).attributes["state_class"]
                == "total"
            )
            checks.append(
                "native kWh/EUR counters expose five periods per scope and system; missing yesterday stays unknown and unmetered bath explicit"
            )
            from custom_components.climate_orchestrator.domain.accounting import (
                Accounting,
            )
            from custom_components.climate_orchestrator.domain.models import (
                PriceInterval,
            )

            now = dt.utcnow()
            start = now - timedelta(minutes=30)
            ledger = Accounting(c.house.timezone)
            price = (PriceInterval(start, now + timedelta(hours=1), 0.15),)
            ledger.observe(start, 1000, start.timestamp(), 3600, price)
            ledger.observe(now, 1000, now.timestamp(), 3600, price)
            c.accounting["meter"] = ledger
            before = copy.deepcopy(ledger.saved())
            await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            c = entry.runtime_data
            assert c.accounting["meter"].days == before["days"]
            assert hass.states.get("sensor.energy").state == "100"
            checks.append(
                "own accounting ledger survives reload without bridging downtime or rewriting original energy statistics"
            )
            calls = []

            async def appliance(call):
                calls.append((call.service, dict(call.data)))
                current = hass.states.get("humidifier.demo")
                attributes = dict(current.attributes)
                mode = current.state
                if call.service == "set_humidity":
                    attributes["humidity"] = call.data["humidity"]
                elif call.service == "turn_on":
                    mode = "on"
                elif call.service == "turn_off":
                    mode = "off"
                hass.states.async_set(
                    "humidifier.demo", mode, attributes, context=call.context
                )
                await asyncio.sleep(0)

            for service in ["set_humidity", "turn_on", "turn_off"]:
                hass.services.async_register("humidifier", service, appliance)
            active = copy.deepcopy(dict(entry.options))
            active["execution_mode"] = "control"
            active["exclusive_control"] = True
            active["house"]["zones"][-1]["enabled"] = True
            hass.config_entries.async_update_entry(entry, options=active)
            await hass.async_block_till_done()
            c = entry.runtime_data
            c._started = False
            original_snapshot = c.snapshot

            def stable_off_snapshot():
                snap = original_snapshot()
                observation = snap.zones[zone["id"]]
                if observation.mode == "off":
                    return replace(
                        snap,
                        zones={
                            **snap.zones,
                            zone["id"]: replace(
                                observation, mode_since=snap.now.timestamp() - 4000
                            ),
                        },
                    )
                return snap

            c.snapshot = stable_off_snapshot
            assert not calls
            now = dt.utcnow()
            memory = c.memories[zone["id"]]
            memory.high_since = now.timestamp() - 1800
            memory.severe_since = now.timestamp() - 1800
            hass.states.async_set(
                "sensor.bath_humidity", "82", {"unit_of_measurement": "%"}
            )
            await hass.async_block_till_done()
            z = next(z for z in c.house.zones if z.id == zone["id"])
            _, decisions = c.fresh_plan()
            assert decisions[z.id].mode == "dry", decisions[z.id]
            assert await c.executor.execute(z, decisions[z.id], c.accepted) == "acked"
            assert [x[0] for x in calls] == ["set_humidity", "turn_on"]
            assert calls[0][1]["humidity"] == 55
            assert c.executor.state["owned"][z.id]["target"] == 55
            checks.append(
                "journaled native adapter sets humidity before on, confirms mapped state echoes and owns a bounded session without split calls"
            )
            # No expiry must not erase the owned-session safety lane.
            c.executor.state["owned"][z.id]["until"] = 0
            original_stop = c.executor.stop_owned
            watchdog_snapshot = c.snapshot
            stopped = []
            async def capture_stop(zone):
                stopped.append(zone.id)
            c.executor.stop_owned = capture_stop
            healthy = c.snapshot()
            await c.check_safety()
            assert not stopped
            for field, value in [("temperature", replace(healthy.zones[z.id].temperature, value=None)), ("temperature", replace(healthy.zones[z.id].temperature, value=0)), ("humidity", replace(healthy.zones[z.id].humidity, value=None)), ("dry_allowed", False), ("permitted", False)]:
                c.snapshot = lambda field=field, value=value: replace(healthy, zones={**healthy.zones, z.id: replace(healthy.zones[z.id], **{field: value})})
                stopped.clear()
                await c.check_safety()
                assert stopped == [z.id], field
            c.snapshot = watchdog_snapshot
            c.executor.stop_owned = original_stop
            checks.append("unlimited owner retains temperature, humidity, permission and dry-safety watchdog exits")
            c.executor.state["owned"][z.id]["until"] = dt.utcnow().timestamp() - 1
            await c.check_safety()
            await asyncio.gather(*c.executor.off_tasks.values())
            assert calls[-1][0] == "turn_off"
            assert hass.states.get("humidifier.demo").state == "off"
            checks.append(
                "independent owned-session maximum stops the dryer through its native service"
            )
            hass.states.async_set(
                "humidifier.demo",
                "on",
                {**attrs, "humidity": 60},
                context=Context(user_id="fictional-person"),
            )
            await hass.async_block_till_done()
            assert not c.executor.is_automatic(z.id)
            count = len(calls)
            await c.async_refresh()
            assert len(calls) == count
            checks.append(
                "a human humidity or power command latches Manual and is not adopted or overwritten"
            )
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            assert device_registry.async_get(hass).async_get(vendor.id)
            checks.append(
                "removal preserves the vendor device and original measurement entities"
            )
            print(
                json.dumps(
                    {
                        "checks": checks,
                        "simulated_humidifier_calls": len(calls),
                        "physical_service_calls": 0,
                        "production_config_writes": 0,
                    }
                )
            )
        finally:
            await hass.async_stop(force=True)


asyncio.run(main())
