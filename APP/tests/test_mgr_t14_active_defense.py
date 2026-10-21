"""Active Defense's additional AC belongs to one real table attack, not a turn."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto55_shield import ME, THEM, ROOT, _sheet
from tests.test_riders_lane9 import _sheet as plain
from tests.test_shield_fix_r1 import reload, table_action
from tests.test_shield_fix_r2 import advance, defense, finish
from tests.test_lock_choices import install

AD = 'SHIELD_BASE_ACTIVE_DEFENSE'
FOCUS = 'resource:core.martial_focus'


def match(tmp_path, *, owner=True, shield=True):
    # Actual admitted character sheets and portable source archives. No injected
    # reaction rows, attack receipts, awareness facts or replacement actions.
    doc = _sheet([], cl=16, shield=shield, bases=False)
    doc['spheres_and_talents']['automatic_sphere_component_record_ids'] = (
        [AD, 'SHIELD_BASE_SHIELD_TRAINING'] if owner else [])
    if not owner:
        doc['spheres_and_talents']['sphere_record_ids'] = []
    bundles = []
    for aid, sheet in [(ME, doc), (THEM, plain([], 16, 60))]:
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
        bundles.append(compile_character(sheet, actor_id=aid, reaction_plan={'ask': True}))
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    mid = service._finish_factory_match(
        bundles, [ME, THEM], {ME: 'team:a', THEM: 'team:b'},
        {ME: {'x': 3, 'y': 6}, THEM: {'x': 4, 'y': 6}},
        service.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        ['auto55_shield'], [THEM], control_modes={ME: 'MANUAL', THEM: 'MANUAL'},
        match_seed='MGR-T14-ACTIVE-DEFENSE', display_name='Active Defense scope regression',
        maximum_rounds=8)['match_id']
    advance(table, mid, ME)
    return service, table, mid


def test_shipped_authority_compiles_attack_only_defense():
    bundle = compile_character(_sheet([], cl=16), actor_id=ME)
    row = next(r for r in bundle['typed_reactions']
               if r['feature_id'] == AD and r['block'] == 'generic')
    effects = row['effects']
    assert [(e['flat'], e['duration']) for e in effects if e['type'] == 'ac_bonus'] == [
        (2, 'triggering_attack')]


def test_defense_bonus_is_additional_and_ends_with_triggering_attack(tmp_path, monkeypatch):
    # Dagger +2: 16+2 hits ordinary AC18 but misses Active Defense AC20.
    install(monkeypatch, 'd20_result', lambda *a: {
        'source_id': 'test:boundary', 'operation': 'replace', 'natural_result': 16})
    service, table, mid = match(tmp_path)
    assert table_action(table, mid, 'end')['status'] == 'COMMITTED'
    before = service._load_session(mid).engine.state.actors[ME].current_hp
    prompts = finish(table, mid, 'Bi Shou (Dagger) attack', defense)
    assert any('ACTIVE_DEFENSE' in p['context']['reaction_source_id']
               or 'active_defense_payment' in p['context']['reaction_source_id'] for p in prompts)
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    me = engine.state.actors[ME]
    roll = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert roll.payload['target_ac'] == 20
    assert me.current_hp == before
    assert not me.reaction_available and me.resources[FOCUS] == 1
    # This is the regression: the old "special" effect survives cold reload
    # as a +2 modifier until the owner's next turn.
    assert not any(m.source_definition_id == AD for m in me.modifiers.values())
    table = TabletopService(service, tmp_path)
    finish(table, mid, 'Bi Shou (Dagger) attack', lambda p: None)
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    roll = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert roll.payload['target_ac'] == 18
    assert engine.state.actors[ME].current_hp < before


@pytest.mark.parametrize('owner,shield', [(False, True), (True, False)])
def test_unowned_or_unwielded_defense_is_not_offered(tmp_path, monkeypatch, owner, shield):
    install(monkeypatch, 'd20_result', lambda *a: {
        'source_id': 'test:boundary', 'operation': 'replace', 'natural_result': 16})
    service, table, mid = match(tmp_path, owner=owner, shield=shield)
    table_action(table, mid, 'end')
    prompts = finish(table, mid, 'Bi Shou (Dagger) attack', defense)
    assert not any('ACTIVE_DEFENSE' in p['context']['reaction_source_id']
                   or 'active_defense_payment' in p['context']['reaction_source_id'] for p in prompts)
    service = reload(service, mid)
    assert not any(e.event_type == 'REACTION_WINDOW_OPENED' and e.source_definition_id == AD
                   for e in service._load_session(mid).engine.events)
