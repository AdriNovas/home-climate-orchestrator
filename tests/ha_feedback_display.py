"""Native dispatch for opt-in feedback exits/OFF targets; fictional devices only."""

import asyncio
import json
import pathlib
import sys
import tempfile
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
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.util import dt
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    with tempfile.TemporaryDirectory(prefix="feedback-display-lab-") as folder:
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
        calls, checks = [], []
        try:
            await bootstrap.async_from_config_dict(
                {
                    "homeassistant": {
                        "name": "Fictional laboratory",
                        "latitude": 0,
                        "longitude": 0,
                        "elevation": 0,
                        "time_zone": "Europe/Madrid",
                        "unit_system": "metric",
                    }
                },
                hass,
            )

            def put(entity, state, attrs=None):
                hass.states.async_set(entity, str(state), attrs or {})

            put("input_boolean.demo_control", "off")
            put("sensor.demo_t", 22, {"unit_of_measurement": "°C"})
            put("number.demo_display", 20, {"unit_of_measurement": "°C"})
            attrs = {
                "temperature": 19,
                "current_temperature": 22,
                "hvac_modes": ["off", "heat", "cool"],
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
                    "policy": {"continuous_hold": True, "overshoot_delta": 2},
                    "plants": [{"id": "plant", "name": "Plant"}],
                    "zones": [
                        {
                            "id": "room",
                            "name": "Room",
                            "plant": "plant",
                            "temperature_entity": "sensor.demo_t",
                            "climate_entity": "climate.demo",
                            "off_goal_entity": "number.demo_display",
                            "night_allowed": True,
                            "require_internal_feedback": True,
                            "feedback_loss_action": "stop",
                        }
                    ],
                },
                "tariff": {"type": "flat", "price": 0.15},
                "control_entity": "input_boolean.demo_control",
                "execution_mode": "control",
                "exclusive_control": True,
            }

            async def simulated(call):
                journal = next(
                    s
                    for s in hass.states.async_all("sensor")
                    if s.attributes.get("actuator") == "climate.demo"
                    and s.attributes.get("schema_version") == 1
                )
                assert journal.state == "sending", journal
                calls.append((call.service, dict(call.data)))
                old = hass.states.get("climate.demo")
                put(
                    "climate.demo",
                    call.data.get("hvac_mode", old.state),
                    {
                        **old.attributes,
                        "temperature": call.data.get(
                            "temperature", old.attributes["temperature"]
                        ),
                    },
                )

            for service in ["set_temperature", "set_hvac_mode"]:
                hass.services.async_register("climate", service, simulated)
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
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()
            c = entry.runtime_data
            # Keep actual native listeners/journals, but drive this laboratory's
            # transactions explicitly rather than racing its periodic reviewer.
            c._started = False
            put("input_boolean.demo_control", "on")
            await hass.async_block_till_done()
            assert not calls
            zone = c.house.zones[0]

            async def run():
                await c.async_refresh()
                decision = c.fresh_plan()[1]["room"]
                result = await c.executor.execute(zone, decision, c.accepted)
                await hass.async_block_till_done()
                return result

            since = hass.states.get("climate.demo").last_changed
            assert await run() == "acked", c.executor.errors
            assert calls == [
                ("set_temperature", {"entity_id": "climate.demo", "temperature": 20})
            ], calls
            assert hass.states.get("climate.demo").state == "off"
            assert hass.states.get("climate.demo").last_changed == since
            assert c.memories["room"].last_sent == 0
            assert not c.executor.state["owned"]
            assert c.executor.is_automatic("room")
            checks.append(
                "native target-only dispatch publishes journal, ACKs OFF, and preserves rest/thermal cadence"
            )
            assert await run() == "already_satisfied"
            assert len(calls) == 1
            checks.append("an already satisfied OFF display is not resent")

            hass.states.get("number.demo_display").last_reported = (
                dt.utcnow() - timedelta(days=1)
            )
            assert c.snapshot().zones["room"].off_goal.value == 20
            checks.append(
                "unchanged native numeric configuration does not expire as a physical sensor"
            )

            put("number.demo_display", "unavailable")
            await hass.async_block_till_done()
            assert c.fresh_plan()[1]["room"].target_only is False
            checks.append("a missing display binding cannot invent a target")
            put("number.demo_display", 20, {"unit_of_measurement": "°C"})
            put("climate.demo", "heat", {**attrs, "temperature": 24})
            await hass.async_block_till_done()
            # This is a fixture setup, not a command from the native executor.
            await c.executor.resume("room")
            put("sensor.demo_t", "unavailable")
            await hass.async_block_till_done()
            calls.clear()
            assert await run() == "acked", c.executor.errors
            assert calls == [
                ("set_hvac_mode", {"entity_id": "climate.demo", "hvac_mode": "off"})
            ], calls
            assert c.executor.is_automatic("room")
            checks.append(
                "reference loss stops opted-in automatic thermal mode without a false uncertain/Manual latch"
            )

            # °F is converted both as source data and as an outgoing HA target.
            hass.config.units = US_CUSTOMARY_SYSTEM
            put("sensor.demo_t", 72, {"unit_of_measurement": "°F"})
            put("number.demo_display", 68, {"unit_of_measurement": "°F"})
            put(
                "climate.demo",
                "off",
                {
                    **attrs,
                    "temperature": 65,
                    "current_temperature": 72,
                    "min_temp": 60,
                    "max_temp": 86,
                    "target_temp_step": 1,
                },
            )
            await hass.async_block_till_done()
            await c.executor.resume("room")
            calls.clear()
            assert await run() == "acked", c.executor.errors
            assert calls == [
                ("set_temperature", {"entity_id": "climate.demo", "temperature": 68})
            ], calls
            assert hass.states.get("climate.demo").state == "off"
            checks.append(
                "Fahrenheit OFF display remains target-only and returns to the native HA unit"
            )
            print(
                json.dumps(
                    {
                        "checks": checks,
                        "physical_services": 0,
                        "production_config_writes": 0,
                    }
                )
            )
        finally:
            await hass.async_stop()


asyncio.run(asyncio.wait_for(main(), 55))
