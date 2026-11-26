"""Catalog prose changes cannot invalidate a saved character's creation HP."""
from copy import deepcopy

import pytest

from combat.factory_compiler import compile_character
from non_sphere_authority import foundation_mechanics as fm
from tests.foundation_catalog_edit_support import edit_catalog, assert_saved_hp_services
from tests.h1_support import sheet

IDENTITY = 'golden_mandate_seal_v0_2B'
SOURCE = 'foundation.' + IDENTITY + '.golden_mandate_vessel'


@pytest.fixture
def mandate_catalog(monkeypatch):
    record = {
        'foundation_id': IDENTITY, 'display_name': 'Golden Mandate Seal',
        'stage': 'Awakened', 'foundation_resource': 'Edict Seal 0/1',
        'compatible_path_ids': ['QI_CULTIVATION'],
        'source': {'artifact': 'synthetic-foundation.md', 'artifact_sha256': 'a' * 64},
        'semantic_surfaces': {
            'features': ('#### Golden Mandate Vessel\n**Type:** Passive\n**Available At:** Awakened\n'
                         '**Effect:** Your maximum Hit Points increase by your Proficiency Bonus.\n'),
            'resource': '### Edict Seal\n| **Maximum** | 1 |\n| **Starting Amount** | 0 |\n',
            'progression': '', 'gm_and_counterplay': 'Original catalog commentary.',
        },
    }
    monkeypatch.setattr(fm, 'verified_foundation_records', lambda: {IDENTITY: record})
    return record


def test_saved_mandate_hp_survives_catalog_edit(tmp_path, monkeypatch, mandate_catalog):
    # Owner ask: an unrelated catalog edit must not make a saved character unplayable.
    mechanics = fm.resolve_initial_foundation_mechanics(mandate_catalog, ['tianxia.path.qi_cultivation'])
    doc = sheet([SOURCE], foundation={
        **fm.installed_foundation_state(mechanics, IDENTITY, 'creation'),
        'mechanics': mechanics, 'status': 'active'})
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 64  # creation included PB 4
    saved = deepcopy(mechanics)
    records = edit_catalog(monkeypatch)
    assert records[IDENTITY] != mandate_catalog
    assert_saved_hp_services(tmp_path, doc, 64)
    assert doc['foundation']['mechanics'] == saved


def test_mandate_uses_saved_formula_not_catalog_amount(monkeypatch, mandate_catalog):
    # Suppression must remove exactly the creation contribution, not today's assumed PB.
    mechanics = fm.resolve_initial_foundation_mechanics(mandate_catalog, ['tianxia.path.qi_cultivation'])
    mechanics['hp_maximum_modifiers'][0]['formula']['root']['terms'][0]['value'] = 2
    doc = sheet([SOURCE], foundation={
        **fm.installed_foundation_state(mechanics, IDENTITY, 'creation'),
        'mechanics': mechanics, 'status': 'active'})
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 68
    edit_catalog(monkeypatch)
    bundle = compile_character(doc, actor_id='actor:factory.12345678-abcd-0000-0000-123456789abc')
    assert bundle['mandate_source']['included_hp'] == 8
    assert bundle['actor_template']['maximum_hp'] == 68
