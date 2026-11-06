"""Native persistent floor, reload and pause safety: fictional, isolated HA only."""

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
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.util import dt
    from homeassistant.helpers import entity_registry as er

    with tempfile.TemporaryDirectory(prefix="dry-session-policy-") as folder:
        base = pathlib.Path(folder)
        for name, source in FILES.items():
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        (base / "custom_components/__init__.py").write_text("")
        sys.path.insert(0, folder)
        from custom_components.climate_orchestrator.domain.models import Memory

        h = HomeAssistant(folder)
        h.config.skip_pip = True
        loader.async_setup(h)
        checks = []
        calls = []
        try:
            await bootstrap.async_from_config_dict(
                {
                    "homeassistant": {
                        "name": "Fictional dry laboratory",
                        "latitude": 0,
                        "longitude": 0,
                        "elevation": 0,
                        "time_zone": "Europe/Madrid",
                        "unit_system": "metric",
                    }
                },
                h,
            )

            def put(e, s, a=None):
                h.states.async_set(e, str(s), a or {})

            put("input_boolean.demo_control", "off")
            put("input_boolean.demo_auto", "on")
            put("binary_sensor.demo_home", "on")
            put("sensor.demo_temperature", 24, {"unit_of_measurement": "°C"})
            put("sensor.demo_humidity", 80, {"unit_of_measurement": "%"})
            put("sensor.demo_outdoor", 13, {"unit_of_measurement": "°C"})
            put("number.demo_floor", 73.4, {"unit_of_measurement": "°F"})
            attrs = {
                "temperature": 23,
                "current_temperature": 22,
                "hvac_modes": ["off", "heat", "cool", "dry"],
                "min_temp": 16,
                "max_temp": 30,
                "target_temp_step": 0.5,
                "supported_features": 1,
            }
            put("climate.demo", "off", attrs)
            profile = {
                "house": {
                    "name": "Fictional home",
                    "timezone": "Europe/Madrid",
                    "plants": [{"id": "plant", "name": "Shared plant"}],
                    "zones": [
                        {
                            "id": "room",
                            "name": "Room",
                            "plant": "plant",
                            "temperature_entity": "sensor.demo_temperature",
                            "humidity_entity": "sensor.demo_humidity",
                            "climate_entity": "climate.demo",
                            "authority_entity": "input_boolean.demo_auto",
                            "allow_dry": True,
                            "dry_floor_entity": "number.demo_floor",
                            "dry_pause_action": "retain_owned",
                        }
                    ],
                },
                "tariff": {"type": "flat", "price": 0.15},
                "control_entity": "input_boolean.demo_control",
                "presence_entity": "binary_sensor.demo_home",
                "outdoor_entity": "sensor.demo_outdoor",
                "execution_mode": "control",
                "exclusive_control": True,
            }
            entry = ConfigEntry(
                version=1,
                minor_version=1,
                domain="climate_orchestrator",
                title="Fictional home",
                data=profile,
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            await h.config_entries.async_add(entry)
            c = entry.runtime_data
            c._started = False
            await h.async_block_till_done()

            async def simulated(call):
                calls.append((call.service, dict(call.data)))
                put("climate.demo", call.data.get("hvac_mode", "off"), attrs)

            h.services.async_register("climate", "turn_off", simulated)
            h.services.async_register("climate", "set_hvac_mode", simulated)
            now = dt.utcnow().timestamp()
            # Configuration has no telemetry age: preserve an old state without
            # pretending it is a fresh environmental measurement.
            source = h.states.get("number.demo_floor")
            source.last_reported = dt.utcnow() - __import__("datetime").timedelta(
                days=4
            )
            snapshot = c.snapshot()
            floor = snapshot.zones["room"].dry_floor
            assert (
                floor.fresh(snapshot.now.timestamp(), 7200)
                and abs(floor.value - 23) < 0.001
            )
            checks.append(
                "Old Fahrenheit configuration is current and converted as an absolute temperature"
            )
            put("number.demo_floor", "unavailable")
            assert c.snapshot().zones["room"].dry_floor.value is None
            checks.append("Unavailable bound floor has no numeric fallback")
            put("number.demo_floor", 23, {"unit_of_measurement": "°C"})
            # Drive an actual accepted native DRY transaction, not synthetic
            # ownership: this verifies floor fencing and the observed-mode ACK.
            await c.executor.resume("room")
            put("input_boolean.demo_control", "on")
            h.states.get("climate.demo").last_changed = dt.utcnow() - __import__(
                "datetime"
            ).timedelta(seconds=1800)
            await h.async_block_till_done()
            now = dt.utcnow().timestamp()
            c.memories["room"] = Memory(high_since=now - 1800)
            snap, decisions = c.fresh_plan()
            decision = decisions["room"]
            assert decision.mode == "dry", decision
            result = await c.executor.execute(c.house.zones[0], decision, c.accepted)
            assert result == "acked", (result, c.executor.errors, calls)
            memory = c.memories["room"]
            assert (
                memory.dry_floor == 23
                and c.executor.state["owned"]["room"]["floor"] == 23
            )
            checks.append(
                "Native dispatch freezes the bound floor before transport and acknowledges owned DRY without false Manual"
            )
            put("input_boolean.demo_control", "off")
            await h.async_block_till_done()
            await c.executor.save()
            await c._store.async_save(c._saved())
            calls.clear()
            await c.check_safety()
            assert not calls and h.states.get("climate.demo").state == "dry"
            checks.append(
                "Pause retains only the explicitly owned session with original maximum and floor"
            )
            ids = {
                e.entity_id: e.unique_id
                for e in er.async_get(h).entities.values()
                if e.config_entry_id == entry.entry_id
            }
            until = memory.dry_until
            await h.config_entries.async_reload(entry.entry_id)
            c = entry.runtime_data
            c._started = False
            await h.async_block_till_done()
            assert (
                c.memories["room"].dry_until == until
                and c.executor.state["owned"]["room"]["floor"] == 23
            )
            assert ids == {
                e.entity_id: e.unique_id
                for e in er.async_get(h).entities.values()
                if e.config_entry_id == entry.entry_id
            }
            assert not calls
            checks.append(
                "Native reload retains authority, session deadline, frozen floor and entity identities"
            )
            # A later configuration edit is not a revision to the old session.
            put("number.demo_floor", 20, {"unit_of_measurement": "°C"})
            await h.async_block_till_done()
            assert c.executor.state["owned"]["room"]["floor"] == 23
            checks.append(
                "Editing the configured start floor does not lower the reserved session floor"
            )
            put("sensor.demo_temperature", 22.9, {"unit_of_measurement": "°C"})
            await h.async_block_till_done()
            await c.check_safety()
            await asyncio.gather(*c.executor.off_tasks.values())
            await h.async_block_till_done()
            assert (
                calls
                and all(
                    service == "set_hvac_mode" and data.get("hvac_mode") == "off"
                    for service, data in calls
                )
                and h.states.get("climate.demo").state == "off"
            )
            assert "room" not in c.executor.state["owned"]
            checks.append(
                "Independent safety exits below the frozen floor during pause and clears only observed ownership"
            )
            print(
                json.dumps(
                    {"checks": checks, "physical_services": 0, "production_writes": 0}
                )
            )
        finally:
            await h.async_stop()


asyncio.run(asyncio.wait_for(main(), 70))
