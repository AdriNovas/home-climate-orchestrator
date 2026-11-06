"""Full config-entry/platform lifecycle in a synthetic, temporary Home Assistant.

No production configuration, credentials or device integrations are loaded.
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
    from homeassistant.helpers import entity_registry

    with tempfile.TemporaryDirectory(
        prefix="climate-orchestrator-lifecycle-"
    ) as folder:
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
            result = await bootstrap.async_from_config_dict(
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
                hass,
            )
            assert result is hass
            hass.states.async_set(
                "sensor.demo_temperature", "18", {"unit_of_measurement": "°C"}
            )
            hass.states.async_set(
                "sensor.demo_humidity", "75", {"unit_of_measurement": "%"}
            )
            hass.states.async_set(
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
            profile = {
                "house": {
                    "name": "Demo",
                    "timezone": "Europe/Madrid",
                    "plants": [{"id": "demo-plant", "name": "Demo outdoor"}],
                    "zones": [
                        {
                            "id": "demo-zone",
                            "name": "Demo room",
                            "plant": "demo-plant",
                            "temperature_entity": "sensor.demo_temperature",
                            "humidity_entity": "sensor.demo_humidity",
                            "climate_entity": "climate.demo",
                        }
                    ],
                },
                "tariff": {"type": "flat", "price": 0.15},
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
            assert entry.state is ConfigEntryState.LOADED
            await hass.async_block_till_done()
            registry = entity_registry.async_get(hass)
            entities = [
                e
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            ]
            assert len(entities) == 48
            assert sum(e.entity_category.value == "diagnostic" for e in entities) == 12
            assert sum(e.entity_category.value == "config" for e in entities) == 36
            assert all(hass.states.get(e.entity_id) for e in entities)
            identities = {e.entity_id: e.unique_id for e in entities}
            assert entry.runtime_data.data["physical_control"] is False
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert {
                e.entity_id: e.unique_id
                for e in registry.entities.values()
                if e.config_entry_id == entry.entry_id
            } == identities
            coordinator = entry.runtime_data
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert coordinator._remove_listener is None
            await hass.async_block_till_done()
            # HA may retain registry-owned unavailable placeholders on unload.
            remaining = [hass.states.get(e.entity_id) for e in entities]
            assert all(
                s is None or (s.state == "unavailable" and s.attributes.get("restored"))
                for s in remaining
            ), remaining
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            assert not any(
                e.config_entry_id == entry.entry_id for e in registry.entities.values()
            )
            assert not (
                base / ".storage" / f"climate_orchestrator.{entry.entry_id}"
            ).exists()
            print(
                json.dumps(
                    {
                        "setup": True,
                        "native_entities": len(entities),
                        "reload_preserves_identity": True,
                        "unload": True,
                        "remove_own_memory": True,
                        "physical_control": False,
                        "production_config_writes": 0,
                    }
                )
            )
        finally:
            await hass.async_stop()


asyncio.run(asyncio.wait_for(main(), timeout=60))
