"""Native services/flows in disposable HA; fictional appliances and no network."""

import asyncio
import copy
import json
import pathlib
import sys
import tempfile
from datetime import timedelta
from types import MappingProxyType


async def main():
    from homeassistant import bootstrap, loader
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant, Context
    from homeassistant.helpers import entity_registry
    from homeassistant.helpers import issue_registry
    from homeassistant.util import dt

    root = pathlib.Path(__file__).resolve().parents[1]
    checks, calls = [], []
    with tempfile.TemporaryDirectory(prefix="climate-profiles-") as folder:
        base = pathlib.Path(folder)
        for source in (root / "custom_components").rglob("*"):
            if source.suffix not in (".py", ".json", ".jinja"):
                continue
            dest = base / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())
        (base / "custom_components/__init__.py").write_text("")
        sys.path.insert(0, folder)
        hass = HomeAssistant(folder)
        hass.config.skip_pip = True
        loader.async_setup(hass)
        try:
            await bootstrap.async_from_config_dict(
                {
                    "homeassistant": {
                        "name": "Fictional lab",
                        "latitude": 0,
                        "longitude": 0,
                        "elevation": 0,
                        "time_zone": "UTC",
                        "unit_system": "metric",
                    }
                },
                hass,
            )
            now = dt.utcnow()
            stamp = now.timestamp()
            intervals = [
                {
                    "start": (now - timedelta(hours=1)).isoformat(),
                    "end": (now + timedelta(minutes=10)).isoformat(),
                    "price": 0.3,
                },
                {
                    "start": (now + timedelta(minutes=10)).isoformat(),
                    "end": (now + timedelta(hours=4)).isoformat(),
                    "price": 0.05,
                },
            ]
            hass.states.async_set(
                "sensor.room",
                "20.3",
                {"unit_of_measurement": "°C", "sampled_at": now.isoformat()},
            )
            hass.states.async_set(
                "sensor.price",
                ".3",
                {"unit_of_measurement": "EUR/kWh", "intervals": intervals},
            )
            hass.states.async_set("binary_sensor.presence", "off")
            hass.states.async_set("binary_sensor.motion", "off")
            hass.states.async_set("input_boolean.control", "on")
            attrs = {
                "temperature": 21,
                "current_temperature": 20,
                "hvac_modes": ["off", "heat", "cool", "dry"],
                "min_temp": 16,
                "max_temp": 30,
                "target_temp_step": 0.5,
                "supported_features": 1,
            }
            hass.states.async_set("climate.room", "off", attrs)

            async def fake_service(call):
                calls.append((call.service, dict(call.data)))
                state = hass.states.get(call.data["entity_id"])
                changes = dict(state.attributes)
                if "temperature" in call.data:
                    changes["temperature"] = call.data["temperature"]
                hass.states.async_set(
                    state.entity_id,
                    call.data.get("hvac_mode", state.state),
                    changes,
                    context=call.context,
                )

            hass.services.async_register("climate", "set_temperature", fake_service)
            hass.services.async_register("climate", "set_hvac_mode", fake_service)
            profile = {
                "house": {
                    "name": "Demo",
                    "timezone": "UTC",
                    "strategy": "price",
                    "day_start": "00:00",
                    "night_start": "23:59",
                    "weekend_day_start": "00:00",
                    "weekend_night_start": "23:59",
                    "plants": [
                        {
                            "id": "p",
                            "name": "Plant",
                            "minimum_off_s": 0,
                            "minimum_on_s": 0,
                            "direction_hold_s": 0,
                            "reversal_gap_s": 0,
                        }
                    ],
                    "zones": [
                        {
                            "id": "r",
                            "name": "Room",
                            "plant": "p",
                            "temperature_entity": "sensor.room",
                            "climate_entity": "climate.room",
                            "preferences": {
                                "heat_day": 21,
                                "cool_day": 24,
                                "heat_sleep": 21,
                                "cool_sleep": 24,
                                "heat_flex": 2,
                                "cool_flex": 2,
                                "vacancy_heat_delta": 2,
                            },
                        }
                    ],
                },
                "tariff": {"type": "generic", "entity": "sensor.price"},
                "source_quality": {
                    "sensor.room": {
                        "semantics": "origin",
                        "timestamp_attribute": "sampled_at",
                    }
                },
                "control_entity": "input_boolean.control",
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
            coordinator = entry.runtime_data
            assert coordinator.data["effective_strategy"] == "legacy"
            original_goal = coordinator.data["decisions"]["r"].heat_goal
            registry = entity_registry.async_get(hass)
            select_id = registry.async_get_entity_id(
                "select", "climate_orchestrator", entry.entry_id + "_house_strategy"
            )
            assert select_id
            selected = registry.async_get(select_id)
            assert (
                selected.entity_category.value == "config" and selected.area_id is None
            )
            assert hass.states.get(select_id).state == "price"
            identities = {
                e.unique_id: e.entity_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            }
            coordinator.memories["r"].debt_since = stamp - 30
            coordinator.memories["r"].attempts = 1
            for strategy in ("comfort", "balanced", "price"):
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": select_id, "option": strategy},
                    blocking=True,
                )
                await hass.async_block_till_done()
                assert entry.runtime_data is coordinator
                await coordinator.async_refresh()
                assert coordinator.data["decisions"]["r"].heat_goal == original_goal
                assert coordinator.data["effective_strategy"] == "legacy"
                assert (
                    coordinator.data["strategy_preview"][strategy]["r"].preferred_heat
                    == 21
                )
                assert coordinator.memories["r"].attempts == 1
            assert not calls
            generation = coordinator.executor.state["generation"]
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": select_id, "option": "price"},
                blocking=True,
            )
            await hass.async_block_till_done()
            assert coordinator.executor.state["generation"] == generation
            assert identities == {
                e.unique_id: e.entity_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            }
            checks.append(
                "native selector is idempotent, hot-applied, preserves IDs and attempts; shadow goals and services untouched"
            )

            # Receipt advances, but a cached origin cannot become fresh.
            old = now - timedelta(hours=3)
            hass.states.async_set(
                "sensor.room",
                "20.3",
                {"unit_of_measurement": "°C", "sampled_at": old.isoformat()},
            )
            await coordinator.async_refresh()
            reading = coordinator.snapshot().zones["r"].temperature
            assert reading.received_at > reading.origin_at
            assert not reading.fresh(
                dt.utcnow().timestamp(), coordinator.house.policy.temperature_fresh_s
            )
            assert coordinator.data["decisions"]["r"].reason == "temperature_stale", (
                coordinator.data["decisions"]["r"]
            )
            hass.states.async_set("sensor.room", "20.3", {"unit_of_measurement": "°C"})
            await coordinator.async_refresh()
            assert (
                not coordinator.snapshot()
                .zones["r"]
                .temperature.fresh(dt.utcnow().timestamp(), 7200)
            )
            assert (
                issue_registry.async_get(hass).async_get_issue(
                    "climate_orchestrator", entry.entry_id + "_origin_clock"
                )
                is not None
            )
            hass.states.async_set(
                "sensor.room",
                "68.54",
                {"unit_of_measurement": "°F", "sampled_at": dt.utcnow().isoformat()},
            )
            await coordinator.async_refresh()
            assert (
                abs(coordinator.snapshot().zones["r"].temperature.value - 20.3) < 0.001
            )
            assert (
                issue_registry.async_get(hass).async_get_issue(
                    "climate_orchestrator", entry.entry_id + "_origin_clock"
                )
                is None
            )
            checks.append(
                "real adapter distinguishes origin/receipt, missing origin and Fahrenheit conversion"
            )

            # Use actual flow manager and form schema, including clear semantics.
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"next_step_id": "splits"}
            )
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"next_step_id": "zone"}
            )
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"zone": "r"}
            )
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"next_step_id": "zone_activity"}
            )
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"action": "add"}
            )
            binding = {
                "entity": "binary_sensor.presence",
                "kind": "presence",
                "active_states": ["on"],
                "inactive_states": ["off"],
                "hold_s": 10,
                "vacancy_s": 0,
                "maximum_age_s": 0,
                "remove": False,
            }
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], binding
            )
            assert flow["type"] == "create_entry", flow
            await hass.async_block_till_done()
            coordinator = entry.runtime_data
            await coordinator.async_refresh()
            assert coordinator.snapshot().zones["r"].activity == "vacant"
            assert coordinator.data["strategy_preview"]["comfort"]["r"].heat_goal == 19
            hass.states.async_set("binary_sensor.presence", "unavailable")
            await coordinator.async_refresh()
            assert coordinator.snapshot().zones["r"].activity == "unknown"
            assert coordinator.data["strategy_preview"]["comfort"]["r"].heat_goal == 21
            checks.append(
                "real options manager adds arbitrary state-mapped room sources; lost presence cannot impose vacancy setback"
            )

            options = copy.deepcopy(dict(entry.options))
            options["house"]["zones"][0]["activity_bindings"].append(
                {"entity": "binary_sensor.motion", "kind": "motion", "hold_s": 900}
            )
            hass.config_entries.async_update_entry(entry, options=options)
            await hass.async_block_till_done()
            coordinator = entry.runtime_data
            # Deliberately no planner refresh between these two short edges.
            hass.states.async_set("binary_sensor.motion", "on")
            hass.states.async_set("binary_sensor.motion", "off")
            await hass.async_block_till_done()
            await coordinator.async_refresh()
            assert coordinator.snapshot().zones["r"].activity == "occupied"
            pulse_at = coordinator.memories["r"].activity_last_positive[
                "binary_sensor.motion"
            ]
            hass.states.async_set("binary_sensor.motion", "off", {"republished": True})
            await hass.async_block_till_done()
            await coordinator.async_refresh()
            assert (
                coordinator.memories["r"].activity_last_positive["binary_sensor.motion"]
                == pulse_at
            )
            checks.append(
                "short motion pulses survive refresh coalescing; attribute republication cannot renew evidence"
            )

            # No profile switch can acquire Manual authority, even when control is enabled.
            options = copy.deepcopy(dict(entry.options))
            options.update(
                execution_mode="control", exclusive_control=True, apply_strategy=True
            )
            hass.config_entries.async_update_entry(entry, options=options)
            await hass.async_block_till_done()
            coordinator = entry.runtime_data
            await coordinator.async_refresh()
            if coordinator._worker:
                await asyncio.wait_for(coordinator._worker, 5)
            await hass.async_block_till_done()
            assert coordinator.data["effective_strategy"] == "price"
            assert (
                not calls
            )  # Complete cheaper interval: temperature is inside authorized flex.
            wait_until = coordinator.memories["r"].thermal_wait_until
            durable = await coordinator._store.async_load()
            assert durable["strategy_memory"]["r"]["thermal_wait_until"] == wait_until
            generation = coordinator.executor.state["generation"]
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": select_id, "option": "comfort"},
                blocking=True,
            )
            await hass.async_block_till_done()
            assert entry.runtime_data is coordinator
            await coordinator.async_refresh()
            if coordinator._worker:
                await asyncio.wait_for(coordinator._worker, 5)
            await hass.async_block_till_done()
            assert coordinator.executor.state["generation"] > generation
            assert any(data.get("hvac_mode") == "heat" for _, data in calls), (
                calls,
                coordinator.data,
                coordinator.executor.state,
            )
            assert hass.states.get("climate.room").state == "heat"
            assert coordinator.executor.is_automatic("r")
            checks.append(
                "select→coordinator→real executor→fictional climate service; same journal and no spurious Manual"
            )
            context = Context(user_id="fictional-human")
            hass.states.async_set("climate.room", "off", attrs, context=context)
            await hass.async_block_till_done()
            assert not coordinator.executor.is_automatic("r")
            prior_calls = len(calls)
            for strategy in ("price", "balanced", "comfort"):
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": select_id, "option": strategy},
                    blocking=True,
                )
                await hass.async_block_till_done()
                assert not coordinator.executor.is_automatic("r")
                assert coordinator.memories["r"].thermal_wait_until == wait_until
            assert len(calls) == prior_calls
            checks.append(
                "human HVAC command retains Manual across repeated strategy changes without renewing prior wait"
            )

            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            coordinator = entry.runtime_data
            assert not coordinator.executor.is_automatic("r")
            assert hass.states.get(select_id).state == "comfort"
            assert coordinator.memories["r"].thermal_wait_until == wait_until
            saved = coordinator._saved()
            assert "thermal_wait_until" not in saved["zones"]["r"]
            assert saved["strategy_memory"]["r"]["thermal_wait_until"] == wait_until
            assert "attempts" in saved["zones"]["r"]
            checks.append(
                "reload restores selected profile, Manual and absolute waiting deadline"
            )
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            for next_step in ("splits", "zone"):
                flow = await hass.config_entries.options.async_configure(
                    flow["flow_id"], {"next_step_id": next_step}
                )
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"zone": "r"}
            )
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"next_step_id": "zone_preferences"}
            )
            defaults = flow["data_schema"]({})
            before_options = copy.deepcopy(dict(entry.options))
            bad = {**defaults, "minimum_heat": 30, "maximum_cool": 24}
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], bad
            )
            assert flow["type"] == "form" and flow["errors"]
            assert dict(entry.options) == before_options
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], defaults
            )
            assert flow["type"] == "create_entry"
            await hass.async_block_till_done()
            assert entry.runtime_data is coordinator
            assert "heat_day" not in entry.options["house"]["zones"][0]["preferences"]
            assert not coordinator.executor.is_automatic("r")
            checks.append(
                "real preferences form rejects conflicts atomically, clears inherited goals and hot-applies without losing Manual"
            )
            # Reject foreign/future schema and self-feedback without half-saving.
            from custom_components.climate_orchestrator.validation import (
                validate_sources,
            )

            for patch in (
                {"strategy_schema": 2},
                {"strategy_schema": True},
                {"source_quality": []},
            ):
                try:
                    validate_sources(hass, {**entry.options, **patch})
                except (ValueError, TypeError):
                    pass
                else:
                    raise AssertionError(patch)
            loops = copy.deepcopy(dict(entry.options))
            loops["house"]["zones"][0]["activity_bindings"] = [{"entity": select_id}]
            try:
                validate_sources(hass, loops)
            except ValueError:
                pass
            else:
                raise AssertionError("Self-feedback activity binding accepted")
            checks.append(
                "unknown schemas, malformed contracts and planner-output feedback rejected"
            )

            # Different money is never a relabel of existing measured history.
            usd_profile = copy.deepcopy(dict(entry.options))
            usd_profile.update(execution_mode="shadow", apply_strategy=False)
            usd_profile["tariff"] = {"type": "flat", "price": 0.15, "currency": "USD"}
            usd_profile["meters"] = [
                {
                    "id": "m",
                    "name": "Lab meter",
                    "scope": "house",
                    "power_entity": "sensor.lab_power",
                }
            ]
            hass.states.async_set(
                "sensor.lab_power", "500", {"unit_of_measurement": "W"}
            )
            usd_entry = ConfigEntry(
                version=1,
                minor_version=1,
                domain="climate_orchestrator",
                title="USD lab",
                data=usd_profile,
                options={},
                source="user",
                unique_id=None,
                discovery_keys=MappingProxyType({}),
                subentries_data=None,
            )
            await hass.config_entries.async_add(usd_entry)
            await hass.async_block_till_done()
            assert usd_entry.state is ConfigEntryState.LOADED
            usd = usd_entry.runtime_data
            cost_sensors = [
                hass.states.get(e.entity_id)
                for e in registry.entities.values()
                if e.config_entry_id == usd_entry.entry_id and "cost" in e.unique_id
            ]
            assert cost_sensors and all(
                s.attributes["unit_of_measurement"] in ("USD", "USD/h")
                for s in cost_sensors
            )
            from custom_components.climate_orchestrator.domain.accounting import (
                Accounting,
            )
            from custom_components.climate_orchestrator.domain.models import (
                PriceInterval,
            )

            ledger = Accounting("UTC")
            ledger.observe(
                now - timedelta(seconds=60),
                500,
                stamp - 60,
                120,
                (
                    PriceInterval(
                        now - timedelta(hours=1), now + timedelta(hours=1), 0.15
                    ),
                ),
            )
            ledger.observe(
                now,
                500,
                stamp,
                120,
                (
                    PriceInterval(
                        now - timedelta(hours=1), now + timedelta(hours=1), 0.15
                    ),
                ),
            )
            usd.accounting["m"] = ledger
            await usd._store.async_save(usd._saved())
            assert await hass.config_entries.async_reload(usd_entry.entry_id)
            await hass.async_block_till_done()
            usd = usd_entry.runtime_data
            assert (
                usd.currency == "USD"
                and sum(d["energy"] for d in usd.accounting["m"].days.values()) > 0
            )
            assert await hass.config_entries.async_unload(usd_entry.entry_id)
            await hass.async_block_till_done()
            money_before = (
                base / ".storage" / f"climate_orchestrator.{usd_entry.entry_id}"
            ).read_bytes()
            changed = copy.deepcopy(usd_profile)
            changed["tariff"]["currency"] = "GBP"
            hass.config_entries.async_update_entry(usd_entry, options=changed)
            await hass.async_block_till_done()
            assert not await hass.config_entries.async_setup(usd_entry.entry_id)
            assert (
                base / ".storage" / f"climate_orchestrator.{usd_entry.entry_id}"
            ).read_bytes() == money_before
            await hass.config_entries.async_remove(usd_entry.entry_id)
            await hass.async_block_till_done()
            checks.append(
                "native USD units and ledger survive reload; currency change is blocked without overwriting measured energy/cost or relabeling history"
            )
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            assert not any(
                e.config_entry_id == entry.entry_id for e in registry.entities.values()
            )
            checks.append(
                "removal cleans native selector, preview and entry-owned memory"
            )
            print(
                json.dumps(
                    {
                        "checks": checks,
                        "passed": len(checks),
                        "fictional_calls": len(calls),
                        "production_writes": 0,
                    }
                )
            )
        finally:
            await hass.async_stop()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 60))
