"""Public-safe native regression, with no historical fixture imports.

Dynamic authority dependencies: TAL_WATER_RESTORATIVE_WATERS,
WATER_BASE_RETURN_THE_FLOW, WATER_BASE_SHAPE_CURRENT, tianxia.sphere.water.
Registry dependencies: combat.ext.water_return, combat.ext.water_basins,
combat.ext.choice_costs, combat.ext.cp_pools, combat.ext.needle.
"""
import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'TAL_WATER_RESTORATIVE_WATERS'
PIDS = ['00000000-0000-4000-8000-00000000000' + str(i) for i in (1, 2, 3)]
OWNER, ALLY, FOE = IDS = ['actor:factory.' + p for p in PIDS]
RETURN = 'Return the Flow: End It Early + Restorative Waters'
CHOICE = 'choice:needle.restorative_'


def document(cl, name, cp):
    return {'identity': {'name': name, 'cultivation_level': cl, 'proficiency_bonus': 4,
                         'path': 'Qi Cultivation', 'key_ability': 'WIS'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 18 if a == 'WIS' else 10,
                               'modifier': 4 if a == 'WIS' else 0}
                              for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'primary_resource': {'name': 'Qi', 'maximum': cp},
                'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 150, 'current': 10},
                'speed': {'walking_ft': 30}, 'technique_save_dc': 16, 'technique_attack_bonus': 8}}


def fixture(tmp_path, cl=10, cp=30, owned=True, ally_at=(8, 6)):
    for pid, name in zip(PIDS, ['Wren', 'Tobin', 'Mara']):
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(cl, name, cp)))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    # Native public acquisition from an initial Qi sheet. No Path progression
    # record exists on this minimal sheet; the sphere grant uses the GM path.
    table.add_advancement(PIDS[0], 'sphere', 'tianxia.sphere.water', gm=True)
    if owned:
        table.add_advancement(PIDS[0], 'talent', SOURCE, gm=True)
    docs = [combat._factory_owner_sheet(pid) for pid in PIDS]
    assert (SOURCE in docs[0]['spheres_and_talents'].get('learned_talent_record_ids', [])) is owned
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask': True}) for d, a in zip(docs, IDS)]
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid = combat._finish_factory_match(
        bundles, IDS, {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': ally_at[0], 'y': ally_at[1]}, FOE: {'x': 12, 'y': 6}},
        arena, [OWNER, ALLY], [FOE], control_modes={a: 'MANUAL' for a in IDS},
        match_seed='RESTORATIVE-NATIVE', display_name='Restorative Waters', maximum_rounds=20)['match_id']
    turn(table, mid)
    return combat, table, mid


def act(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(20):
        view = table.state(mid); menu = view['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], view['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        choice = (picks or {}).get(p['context']['reaction_source_id'], 'first')
        ids = [p['choice']['options'][0]['id']] if choice == 'first' else choice
        answers.append({**p['context'], 'selection': 'DECLINE' if ids is None else 'USE', 'option_ids': ids or []})
    raise AssertionError('Unsettled choice')


def turn(table, mid):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            return
        act(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('No owner turn')


def candidate(combat, mid, name, at=None):
    e = combat._load_session(mid).engine
    choices = [c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
               and e.action_catalog[c.source_definition_id].display_name == name
               and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert choices, name
    return choices[0].candidate_id


def basin(combat, table, mid):
    act(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', (8, 6)))
    return next(z.zone_id for z in combat._load_session(mid).engine.state.zones.values()
                if z.active and z.owner_id == OWNER)


def test_source_hash():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_bytes())[SOURCE]
    assert sha256(text.encode()).hexdigest() == 'c00483593620d5bca36cd46d4d8ae6f878976e2d1555f6c6392c70012284252d'


@pytest.mark.parametrize('cl,count', [(10, 1), (11, 2), (17, 3)])
def test_native_binding_payment_repeat_and_cold_reload(tmp_path, cl, count):
    combat, table, mid = fixture(tmp_path, cl)
    zid = basin(combat, table, mid)
    before = combat._load_session(mid).engine
    hp = before.state.actors[ALLY].current_hp
    cp = before.state.actors[OWNER].resources['resource:core.qi']
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['1']})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    e = loaded.engine
    assert not e.state.zones[zid].active
    assert count + 4 <= e.state.actors[ALLY].current_hp - hp <= count * 8 + 4
    assert e.state.actors[OWNER].resources['resource:core.qi'] == cp - 1
    assert any(c.condition_id == 'condition:typed.restorative_waters_used' for c in e.state.actors[ALLY].conditions.values())
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'recipient')
    assert {o['id'] for o in p['choice']['options']} == {ALLY}
    assert 'Restorative Waters' in str(p) and 'Return the Flow' in str(p) and 'Tobin' in str(p)
    act(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid)
    zid = basin(combat, table, mid)
    prompts = act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + 'payment': ['2']})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'payment')
    assert [o['id'] for o in p['choice']['options']] == ['2']
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == cp - 4


@pytest.mark.parametrize('stage', ['effect', 'recipient', 'payment'])
def test_decline_does_not_pay_or_mark(tmp_path, stage):
    combat, table, mid = fixture(tmp_path)
    zid = basin(combat, table, mid)
    cp = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    act(table, mid, candidate(combat, mid, RETURN), {
        CHOICE + 'effect': [zid], CHOICE + 'recipient': [ALLY], CHOICE + stage: None})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == cp
    assert not any(c.condition_id == 'condition:typed.restorative_waters_used'
                   for c in loaded.engine.state.actors[ALLY].conditions.values())


def test_no_owner_no_modifier(tmp_path):
    combat, table, mid = fixture(tmp_path, owned=False)
    assert not any('Restorative Waters' in a.display_name for a in combat._load_session(mid).engine.action_catalog.values())
