"""Actual coordinator persistence/watchdog methods, with doubles and no HA instance."""
import asyncio
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
from test_domain import fixture, NOW
from custom_components.climate_orchestrator.coordinator import ClimateCoordinator, DRY_MEMORY_FIELDS
from custom_components.climate_orchestrator.domain.models import Memory, house_from_dict, Reading
from custom_components.climate_orchestrator.domain.engine import evaluate, dew_point
from custom_components.climate_orchestrator.domain.safety import SupplyProtection

class Store:
    def __init__(self, data=None): self.data = copy.deepcopy(data)
    async def async_load(self): return copy.deepcopy(self.data)
    async def async_save(self, data): self.data = copy.deepcopy(data)

class Journal:
    def __init__(self):
        self.state = {'pending': {}, 'owned': {}, 'critical': False}
        self.stopped = []
        self.saved = None
    async def save(self): self.saved = copy.deepcopy(self.state)
    async def restore(self): pass
    async def critical(self, active): self.state['critical'] = active
    async def stop_owned(self, zone): self.stopped.append(zone.id)

def subject(house, snap, store=None, journal=None):
    c = SimpleNamespace(house=house, snapshot=lambda: snap, memories={}, plants={},
                        _store=store or Store(), executor=journal or Journal(),
                        currency='EUR', meters=[], accounting={}, accounting_archive=[],
                        profile={}, supply_policy=SupplyProtection(), allowed=lambda *_: True)
    c._saved = lambda: ClimateCoordinator._saved(c)
    return c

async def main():
    old, snap, prices, _, _ = fixture(5)
    data = asdict(old)
    data['policy']['dry_max_s'] = 0
    for z in data['zones']:
        z.update(dry_max_temperature_drop=.7, dry_dewpoint_completion=True)
    house = house_from_dict(data)
    for key in snap.zones:
        snap.zones[key] = replace(snap.zones[key], temperature=Reading(23, NOW.timestamp()))
    c = subject(house, snap)
    for z in house.zones:
        c.executor.state['pending'][z.id] = {'id': 'fictional-'+z.id}
        d = SimpleNamespace(target_only=False, stage='dry_ready',
                            session_floor=20, humidity_stop=60)
        with patch('custom_components.climate_orchestrator.coordinator.dt.utcnow', return_value=NOW):
            await ClimateCoordinator.accepted(c, z, d)
    saved = copy.deepcopy(c._store.data)
    journal = copy.deepcopy(c.executor.state)
    assert len(saved['dry_memory']) == 5
    for key, row in saved['zones'].items():
        assert not (set(row) & DRY_MEMORY_FIELDS)
        assert row['attempts'] == 1
        assert saved['dry_memory'][key]['dry_start_temperature'] == 23
        assert journal['owned'][key]['dew_target'] == round(dew_point(20, 60), 3)
    # A separate receiver loads both persisted snapshots; no reload/current reading
    # is allowed to replace the original reservation temperature or dew target.
    restored = subject(house, snap, Store(saved))
    restored.executor.state = copy.deepcopy(journal)
    await ClimateCoordinator.async_restore(restored)
    assert all(asdict(restored.memories[k]) == asdict(c.memories[k]) for k in c.memories)
    # Crash cutpoint: journal was saved, but observer data has not yet been written.
    cut = subject(house, snap, Store({}))
    cut.executor.state = copy.deepcopy(journal)
    await ClimateCoordinator.async_restore(cut)
    assert len(cut.memories) == 5
    assert all(m.dry_start == NOW.timestamp() and m.dry_start_temperature == 23
               for m in cut.memories.values())
    # Binding mismatch must not restore an owner's reservation to a different device.
    changed = copy.deepcopy(data)
    changed['zones'][0]['climate_entity'] = 'climate.another_fictional_unit'
    mismatch = subject(house_from_dict(changed), snap, Store(saved))
    mismatch.executor.state = copy.deepcopy(journal)
    mismatch.executor.state['owned'].pop('0') # Executor.restore filters mismatched binding.
    await ClimateCoordinator.async_restore(mismatch)
    assert '0' not in mismatch.memories
    # Unknown schemas/invalid metadata stop restore rather than inventing protection.
    for kind in ['schema', 'field', 'owner_schema', 'owner_value']:
        bad = subject(house, snap, Store(saved))
        bad.executor.state = copy.deepcopy(journal)
        if kind == 'schema': bad._store.data['dry_memory_schema'] = 2
        if kind == 'field': bad._store.data['dry_memory']['0']['unknown'] = 1
        if kind == 'owner_schema': bad.executor.state['owned']['0']['dry_schema'] = True
        if kind == 'owner_value': bad.executor.state['owned']['0']['start_temperature'] = float('nan')
        try: await ClimateCoordinator.async_restore(bad)
        except ValueError: pass
        else: raise AssertionError(kind)
    # Actual watchdog reads authoritative owner data, not a possibly stale observer.
    healthy = {k: replace(o, mode='dry') for k, o in snap.zones.items()}
    check = replace(snap, zones=healthy)
    c.snapshot = lambda: check
    await ClimateCoordinator.check_safety(c)
    assert not c.executor.stopped
    check.zones['0'] = replace(check.zones['0'], temperature=Reading(22.299, NOW.timestamp()))
    await ClimateCoordinator.check_safety(c)
    assert c.executor.stopped == ['0']
    c.executor.stopped.clear()
    c.executor.state['owned']['1'].pop('dew_target')
    await ClimateCoordinator.check_safety(c)
    assert set(c.executor.stopped) == {'0', '1'}
    print(json.dumps({'zones_restored': 5, 'journal_before_observer_cutpoint': True,
                      'unknown_schema_fail_closed': 4, 'binding_mismatch_preserved': True,
                      'watchdog_drop_and_missing_metadata': True,
                      'ha_instance_created': False, 'physical_calls': 0}))

asyncio.run(main())
