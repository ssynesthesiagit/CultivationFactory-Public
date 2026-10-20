"""Knowledge and study cannot depend on publication/translation of rule prose."""
import json

import pytest

from combat.ext import talisman_formulae
from combat.tabletop import TabletopError
from tests.test_formula_archivist_table import (
    ROOT, PID, COMMON, UNCOMMON, DISCOVERED, call, cold, install,
)


@pytest.fixture
def translated_descriptions(tmp_path, monkeypatch):
    """Keep shipped structured authority, replace only its non-mechanical text."""
    root = tmp_path / 'translated'
    authority = root / 'authority'
    (authority / 'typed_mechanics').mkdir(parents=True)
    (authority / 'Tianxia_Typed_Mechanics_Authority_R1.json').write_bytes(
        (ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_bytes())
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    (authority / 'typed_mechanics/rules_text.json').write_text(json.dumps(
        {key: 'Translated description without English rank or prerequisite headings.' for key in texts}))
    monkeypatch.setattr(talisman_formulae, 'APP', root)
    talisman_formulae.formula_catalog.cache_clear()
    yield
    talisman_formulae.formula_catalog.cache_clear()


def test_translated_formula_metadata_retains_grants_study_and_cold_knowledge(tmp_path, translated_descriptions):
    table = install(tmp_path / 'data')
    menu = table.procedures(PID)[0]
    assert [row['rank'] for row in menu['grants']] == ['Common', 'Uncommon']
    assert sum(len(row['options']) for row in menu['grants']) == 11
    call(table, 'choose', {'formula_id': COMMON}, 'common')
    call(table, 'choose', {'formula_id': UNCOMMON}, 'uncommon')
    call(table, 'discover', {'formula_id': DISCOVERED, 'discovery_id': 'found',
                            'provenance': 'GM confirms the found talisman.'}, 'discovery', gm=True)
    result = call(table, 'study', {'discovery_id': 'found', 'minutes': 240}, 'study', gm=True)
    assert result['procedure']['projects'][0]['status'] == 'awaiting_crafting_check'
    call(table, 'check', {'discovery_id': 'found', 'd20': 20,
                         'roll_provenance': 'GM confirms the physical die.'}, 'check', gm=True)
    reloaded = cold(tmp_path / 'data')
    known = reloaded.combat._factory_owner_sheet(PID)['spheres_and_talents']['learned_talent_record_ids']
    assert {COMMON, UNCOMMON, DISCOVERED} <= set(known)
    assert reloaded.procedures(PID)[0]['projects'][0]['status'] == 'learned'


@pytest.mark.parametrize('formula', [
    UNCOMMON, 'tianxia.talent.talismans.ghost_warding_talisman',
    'tianxia.talent.talismans.qi_storage_talisman',
    'tianxia.talent.talismans.demon_subduing_tag',
    'tianxia.talent.talismans.secret_formula',
])
def test_translated_descriptions_cannot_erase_prerequisites_or_allow_secret_formulae(
        tmp_path, translated_descriptions, formula):
    table = install(tmp_path / 'data', owner=False, cl=4)
    menu = table.procedures(PID)[0]
    assert {row['rank'] for row in menu['discoverable']} == {'Common'}
    assert formula not in {row['id'] for row in menu['discoverable']}
    before = table.buttons.get(PID)
    with pytest.raises(TabletopError):
        call(table, 'discover', {'formula_id': formula, 'discovery_id': 'forbidden',
                                'provenance': 'GM confirms the object, not eligibility.'}, 'forbidden', gm=True)
    assert table.buttons.get(PID) == before
