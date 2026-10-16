"""Public native Incarnation origin regression; no historical fixture imports.

Dynamic registry dependencies: combat.ext.water_second_pass, combat.ext.states,
combat.ext.water_basins, combat.ext.needle, combat.ext.free_use.
"""
import json
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
OWN = 'TAL_WATER_OCEAN_SOVEREIGN_INCARNATION'
LASH = 'WATER_BASE_WATER_LASH'
PIDS = ['20000000-0000-4000-8000-00000000000' + str(i) for i in (1, 2, 3)]
ME, ALLY, FOE = IDS = ['actor:factory.' + p for p in PIDS]
RUNTIME_DEPENDENCIES = (
    'authority/Tianxia_Forged_Technique_Authority_R1.json',
    'authority/Tianxia_Sphere_Path_Access_R1.json',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/rules_text.json',
    'catalog_authority/cat1/data/canonical_talents.v1.json',
    'catalog_authority/cat1/data/prerequisite_projection.v1.json',
    'combat/rules/feature_blocks.d/a2_water.json',
    'combat/rules/feature_blocks.d/auto38_water.json',
    'combat/rules/forged_techniques.json',
)


def document(name):
    return {'identity': {'name': name, 'cultivation_level': 17, 'proficiency_bonus': 6,
        'path': 'Qi Cultivation', 'path_ids': ['tianxia.path.qi_cultivation'], 'key_ability': 'WIS'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 18 if a == 'WIS' else 10,
                          'modifier': 4 if a == 'WIS' else 0}
                         for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 30},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 150, 'current': 150},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 18, 'technique_attack_bonus': 10}}


def fixture(path, owned=True):
    for pid, name in zip(PIDS, ['Wren', 'Tobin', 'Mara']):
        folder = path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(name)))
    c = CombatService(ROOT, path); t = TabletopService(c, path)
    t.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    for pid in PIDS[:2]:
        t.add_advancement(pid, 'sphere', 'tianxia.sphere.water')
    if owned:
        t.add_advancement(PIDS[0], 'talent', OWN)
    docs = [c._factory_owner_sheet(pid) for pid in PIDS]
    assert (OWN in docs[0]['spheres_and_talents'].get('learned_talent_record_ids', [])) is owned
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask': True}) for d, a in zip(docs, IDS)]
    arena = {**c.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], 'terrain_regions': []}
    mid = c._finish_factory_match(bundles, IDS, {ME: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 9}, FOE: {'x': 16, 'y': 6}},
        arena, [ME, ALLY], [FOE], control_modes={a: 'MANUAL' for a in IDS},
        match_seed='OCEAN-ORIGIN-NATIVE', display_name='Ocean-Sovereign Incarnation', maximum_rounds=20)['match_id']
    turn(t, mid, ME)
    return c, t, mid


def act(t, mid, cid):
    answers = []
    for _ in range(20):
        v = t.state(mid); m = v['menu']
        r = t.act(mid, cid, m['decision_id'], m['state_version'], v['last_sequence'], answers)
        if r['status'] != 'REACTION_REQUIRED':
            assert r['status'] == 'COMMITTED', r
            return
        p = r['reaction']
        answers.append({**p['context'], 'selection': 'DECLINE', 'option_ids': []})
    raise AssertionError('Unsettled choice')


def turn(t, mid, actor):
    for _ in range(12):
        m = t.state(mid)['menu']
        if m['actor_id'] == actor:
            return
        act(t, mid, m['end_turn'])
    raise AssertionError('No turn')


def candidate(c, mid, name, at=None):
    e = c._load_session(mid).engine
    rows = [x for x in e.legal_candidates() if e.action_catalog.get(x.source_definition_id)
            and e.action_catalog[x.source_definition_id].display_name == name
            and (at is None or x.destination and (x.destination.x, x.destination.y) == at)]
    assert rows, name
    return rows[0].candidate_id


def cold(path, mid):
    c = CombatService(ROOT, path); s = c._load_session(mid)
    assert s.verify()['status'] == 'PASS'
    assert s.mechanical.replay()['status'] == 'PASS'
    return c, TabletopService(c, path), s.engine


def origins(e, actor=ME):
    from combat.action_geometry import origins
    a = next(a for a in e.action_catalog.values()
             if a.owner_id == actor and (a.parameters.get('typed') or {}).get('source') == LASH)
    return origins(e, e.state.actors[actor], a)


def test_printed_identity():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_bytes())[OWN]
    assert sha256(text.encode()).hexdigest() == '0a54304d1bea710168296a213e0a79f2c38ba3b71002e3e4129687728d5db07c'


@pytest.mark.parametrize('owned', [True, False])
def test_native_basin_origin_and_committed_lash(tmp_path, owned):
    c, t, mid = fixture(tmp_path, owned=owned)
    act(t, mid, candidate(c, mid, 'Shape Current: Mist Basin', (8, 6)))
    if owned:
        act(t, mid, candidate(c, mid, 'Ocean-Sovereign Incarnation'))
    c, t, e = cold(tmp_path, mid)
    assert e.state.actors[ME].resources['resource:core.qi'] == 29 - (5 if owned else 0)
    assert bool(origins(e)) is owned
    if not owned:
        return
    assert any(p['position'] == {'x': 8, 'y': 6, 'z': 0} for p in origins(e))
    assert not origins(e, ALLY)
    turn(t, mid, ALLY)
    act(t, mid, candidate(c, mid, 'Shape Current: Mist Basin', (5, 10)))
    turn(t, mid, ME)
    c, t, e = cold(tmp_path, mid)
    assert not any(p['position']['y'] == 10 for p in origins(e))
    choices = [x for x in e.legal_candidates() if x.target_ids == (FOE,)
        and (e.action_catalog[x.source_definition_id].parameters.get('typed') or {}).get('source') == LASH
        and x.metadata.get('effect_origin', {}).get('position') == {'x': 8, 'y': 6, 'z': 0}]
    assert choices, 'Legal Water Lash must bind the controlled Basin origin'
    original = e.state.actors[ME].position
    act(t, mid, choices[0].candidate_id)
    c, t, e = cold(tmp_path, mid)
    assert e.state.actors[ME].position == original
    assert any(x.event_type == 'ATTACK_ROLLED' and x.actor_id == ME for x in e.events)
    for _ in range(10):
        turn(t, mid, FOE)
        turn(t, mid, ME)
    c, t, e = cold(tmp_path, mid)
    assert not origins(e)
