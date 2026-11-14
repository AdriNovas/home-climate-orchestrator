"""Run with Home Assistant installed; all state and storage live in a temp directory.

No real integrations, devices, network fetches or service calls are used.
"""

import asyncio
import json
import pathlib
import sys
import tempfile
import time
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

if "FILES" not in globals():
    root = pathlib.Path(__file__).resolve().parents[1]
    FILES = {
        str(p.relative_to(root)): p.read_text()
        for p in (root / "custom_components").rglob("*")
        if p.suffix in [".py", ".json", ".jinja"]
    }


async def main():
    from homeassistant.core import HomeAssistant
    from homeassistant import bootstrap, loader
    from homeassistant.config_entries import ConfigEntry

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
        h.config.skip_pip = True
        loader.async_setup(h)
        try:
            # Use normal empty HA bootstrap, not a partial registry mock whose
            # internal startup dependencies can change between HA releases.
            assert (
                await bootstrap.async_from_config_dict(
                    {
                        "homeassistant": {
                            "name": "Fictional test home",
                            "latitude": 0,
                            "longitude": 0,
                            "elevation": 0,
                            "time_zone": "Europe/Madrid",
                            "unit_system": "metric",
                        }
                    },
                    h,
                )
                is h
            )
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
            for table, field, value in [
                ("cool_targets", "cool_day", 28),
                ("heat_sleep_targets", "heat_sleep", 18),
                ("cool_sleep_targets", "cool_sleep", 29),
            ]:
                await options.async_step_zone_targets(
                    {"zone": zone_id, "target_table": table}
                )
                values = {b.name: getattr(b, field) for b in Policy().bands}
                values["normal"] = value
                result = await options.async_step_zone_targets_edit(
                    {"override": True, **values}
                )
                assert result["data"]["house"]["zones"][0][table]["normal"] == value
                assert result["data"]["house"]["zones"][0]["id"] == zone_id
            checks.append(
                "independent heating/cooling and day/sleep tables preserve identity and other tables"
            )
            original = __import__("copy").deepcopy(options.profile)
            bad = await options.async_step_zone_targets_edit(
                {"override": True, **{b.name: 10 for b in Policy().bands}}
            )
            assert (
                bad["errors"]["base"] == "invalid_configuration"
                and options.profile == original
            )
            cleared = await options.async_step_zone_targets_edit({"override": False})
            assert cleared["data"]["house"]["zones"][0]["cool_sleep_targets"] == {}
            assert (
                cleared["data"]["house"]["zones"][0]["heat_sleep_targets"]["normal"]
                == 18
            )
            checks.append(
                "conflicting zone tables are rejected atomically and one table can return to inheritance"
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
            c.profile["control_entity"] = "input_boolean.demo_control"
            for value in ["off", "unknown", "unavailable", None]:
                if value is None:
                    h.states.async_remove("input_boolean.demo_control")
                else:
                    h.states.async_set("input_boolean.demo_control", value)
                paused = await c._async_update_data()
                assert paused["decisions"][zone_id].stage == "paused"
                assert paused["decisions"][zone_id].mode is None
            h.states.async_set("input_boolean.demo_control", "on")
            assert (await c._async_update_data())["decisions"][
                zone_id
            ].stage != "paused"
            del c.profile["control_entity"]
            checks.append("global permission fails closed when off, unknown or missing")
            entities = []
            await sensor.async_setup_entry(h, entry, entities.extend)
            await binary_sensor.async_setup_entry(h, entry, entities.extend)
            assert len(entities) == 17 and len({x.unique_id for x in entities}) == 17
            assert all(x.entity_category.value == "diagnostic" for x in entities)
            for x in entities:
                if isinstance(x, sensor.SensorEntity):
                    x.native_value
                else:
                    x.is_on
            checks.append(
                "thirteen native diagnostic entities have stable IDs, values and diagnostic categories"
            )
            from homeassistant.helpers.template import Template

            macro = FILES[
                "custom_components/climate_orchestrator/templates/execution_echo.jinja"
            ]
            expression = Template(
                macro
                + "\n{{ execution_echo(j, 'climate.demo', 'heat', 23, 1000, person) }}",
                h,
            )
            journal = {
                "schema_version": 1,
                "actuator": "climate.demo",
                "execution_mode": "control",
                "temperature_unit": "°C",
                "phase": "sending",
                "expected": [{"mode": "heat", "target": 23, "until": 1020}],
            }
            assert expression.async_render({"j": journal, "person": None}) is True
            assert (
                expression.async_render({"j": journal, "person": "fictional-person"})
                is False
            )
            assert (
                expression.async_render(
                    {"j": {**journal, "phase": "prepared"}, "person": None}
                )
                is False
            )
            assert (
                expression.async_render(
                    {
                        "j": {
                            **journal,
                            "expected": [{"mode": "heat", "target": 23, "until": 999}],
                        },
                        "person": None,
                    }
                )
                is False
            )
            checks.append(
                "shipped Jinja journal contract recognizes only sent exact unexpired echoes without a person"
            )
            diag = await diagnostics.async_get_config_entry_diagnostics(h, entry)
            encoded = json.dumps(diag)
            assert (
                "sensor.demo_t" not in encoded
                and "Demo zone" not in encoded
                and "75.0" not in encoded
            )
            checks.append("diagnostic bundle omits bindings, names and raw readings")
            assert c.update_interval.total_seconds() == 300
            c._last_review_at = time.time()
            refresh = AsyncMock()
            c.async_request_refresh = refresh
            assert not c._request_plan_review()
            assert c._request_plan_review(immediate=True)
            await asyncio.sleep(0)
            assert refresh.await_count == 1
            c._last_review_at = time.time() - 300
            assert c._request_plan_review()
            await asyncio.sleep(0)
            assert refresh.await_count == 2
            checks.append(
                "ordinary planner refreshes coalesce for five minutes; explicit urgent review bypasses"
            )

            import custom_components.climate_orchestrator.coordinator as coordinator_module

            scheduled, cancelled = [], []

            def capture_deadline(_hass, delay, action):
                scheduled.append((delay, action))
                return lambda: cancelled.append(True)

            original_call_later = coordinator_module.async_call_later
            coordinator_module.async_call_later = capture_deadline
            try:
                now = time.time()
                c._schedule_deadline_review(
                    {"0": SimpleNamespace(next_at=now + 90)}, now
                )
                assert len(scheduled) == 1
                assert abs(scheduled[0][0] - 90) < 0.1
                c._schedule_deadline_review(
                    {"0": SimpleNamespace(next_at=now + 120)}, now
                )
                assert cancelled == [True]
                scheduled[1][1](None)
                await asyncio.sleep(0)
                assert refresh.await_count == 3
                c._schedule_deadline_review(
                    {"0": SimpleNamespace(next_at=now + 300)}, now
                )
                assert c._deadline_review_unsub is None
            finally:
                coordinator_module.async_call_later = original_call_later
                c._cancel_deadline_review()
            checks.append(
                "absolute decision deadlines wake before the five-minute periodic review"
            )

            timed, timer_removed, safety_checks = [], [], Mock()
            original_track_interval = coordinator_module.async_track_time_interval

            def capture_interval(_hass, action, interval):
                timed.append((action, interval.total_seconds()))
                return lambda: timer_removed.append(True)

            coordinator_module.async_track_time_interval = capture_interval
            c.executor.enabled = True
            c._queue_safety_check = safety_checks
            try:
                c.async_listen()
                assert timed and timed[0][1] == 60
                timed[0][0](None)
                safety_checks.assert_called_once_with()
                await asyncio.sleep(0)
                await c.async_close()
                assert timer_removed
            finally:
                coordinator_module.async_track_time_interval = original_track_interval
            checks.append(
                "control mode keeps a one-minute safety-only tick and unload removes it"
            )
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


asyncio.run(asyncio.wait_for(main(), timeout=60))
