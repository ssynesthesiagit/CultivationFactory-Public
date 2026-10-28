"""Recorded feature acquisition survives a table save, a cold reload and a second acquisition.

Regression for the Read the Thread acquisition loss: `acquire_feature` saved the
feature list, but `table_advance.normalized` dropped it on every later save and
`apply` never wrote it into the sheet, so `feature_access` never reached the
compiler. Synthetic sheet and files under tmp_path only; no model, browser or GUI.
"""
from pathlib import Path

from combat import table_advance
from combat.ext.fate_reader import READ
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_c8 import sheet

ROOT = Path(__file__).resolve().parents[1]
PATH = 'tianxia.path.spirit_awakening'
PROJECT = '0badc0de-0000-4000-8000-000000000002'
ACCESS = {'kind': 'teacher', 'classification': 'Secret', 'reference': 'campaign:roundtrip-secret-teacher'}
SECOND = {'kind': 'teacher', 'classification': 'Secret', 'reference': 'campaign:roundtrip-second-teacher'}


def original_sheet():
    doc = sheet([], cl=6)
    doc['path_and_subpath']['path_record_ids'] = [PATH]
    return doc


def service(tmp_path, original):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat._factory_owner_sheet = lambda project_id: table_advance.apply(
        original, table.buttons.get(project_id).get('advancement'))
    return combat, table


def test_normalized_keeps_recorded_features():
    doc = table_advance.normalized({'features': [{'id': READ, 'source': ACCESS, 'at': 'now'}, 'not-a-row']})
    assert doc['features'] == [{'id': READ, 'source': ACCESS, 'at': 'now'}]


def test_apply_writes_acquisition_into_sheet_without_mutating_input():
    original = original_sheet()
    before = repr(original)
    out = table_advance.apply(original, {'features': [{'id': READ, 'source': ACCESS, 'at': 'now'}]})
    assert out['feature_access'][READ] == ACCESS
    assert READ in out['path_and_subpath']['path_feature_record_ids']
    assert repr(original) == before


def test_acquisition_survives_later_save_cold_reload_and_second_acquisition(tmp_path):
    original = original_sheet()
    combat, table = service(tmp_path, original)
    table.acquire_feature(PROJECT, READ, ACCESS)
    assert combat._factory_owner_sheet(PROJECT)['feature_access'][READ] == ACCESS
    # Another table write goes through the normalized round trip; the acquisition must stay.
    saved = table_advance.normalized(table.buttons.get(PROJECT).get('advancement'))
    table.buttons.save_advancement(PROJECT, saved)
    assert combat._factory_owner_sheet(PROJECT)['feature_access'][READ] == ACCESS
    # Cold reload from disk with fresh services.
    cold_combat, cold_table = service(tmp_path, original)
    reloaded = cold_combat._factory_owner_sheet(PROJECT)
    assert reloaded['feature_access'][READ] == ACCESS
    assert READ in reloaded['path_and_subpath']['path_feature_record_ids']
    # A second acquisition after reload replaces the first and leaves a single feature row.
    cold_table.acquire_feature(PROJECT, READ, SECOND)
    again = service(tmp_path, original)[0]._factory_owner_sheet(PROJECT)
    assert again['feature_access'][READ] == SECOND
    assert again['path_and_subpath']['path_feature_record_ids'].count(READ) == 1
    rows = table_advance.normalized(service(tmp_path, original)[1].buttons.get(PROJECT).get('advancement'))['features']
    assert [row['source'] for row in rows if row['id'] == READ] == [SECOND]
