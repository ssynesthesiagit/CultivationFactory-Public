"""Whole-row audit: canonical CAT3 Sword inventory -> portable sheet -> table.

The strict expected failures expose missing acquisition enforcement. They are
not completion credit for Sword Practice or permission to infer access features.
No authority, action, passive, or fight-state metadata is injected into combat.
"""
import hashlib
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark
from sphere_component_authority import normalize_sphere_automatic_components
from tests import h1_support as H
from tests import test_ocf8_sword_core as S

PRACTICE = 'SWORD_BASE_SWORD_PRACTICE'
WAVE = 'SWORD_BASE_SWORD_BEYOND_HAND'
HAND = 'SWORD_BASE_SWORD_IN_HAND'
PROJECTS = ('71400001', '71400002')
IDS = tuple('actor:factory.' + p for p in PROJECTS)
HASHES = {
    PRACTICE: 'ff8816e60c8f6cd9956a8e419b398a838d64f97b037bae1660033193045cc16b',
    WAVE: '4269ef0199b8a33939b4fc4413573a9398569eece95f99d45f911d0adcf995ff',
}


def source_sheet(*, body=False, cl=1):
    """Use the shipped component normalizer and unmodified CAT3 source.

    Portable owner sheets are the native combat input. No acquisition or
    exception receipt is fabricated: this checks execution of the source
    inventory, not completion of the upstream learning workflow.
    """
    catalog = json.loads((H.ROOT / 'catalog_authority/cat3/generated/catalog_authority.v1.json').read_text())
    sphere = next(r for r in catalog['spheres'] if r['canonical_sphere_id'] == S.SWORD_SPHERE)
    record = {**sphere, 'record_id': S.SWORD_SPHERE,
              'record_hash': sphere['record_commitment_sha256']}
    packet = normalize_sphere_automatic_components(record)
    doc = H.sheet([], cl=cl, primary='Stamina' if body else 'Qi', key='WIS', score=18)
    doc['identity'].update(path='Body Refining' if body else 'Qi Cultivation', display_name='Sword learner')
    doc['path_and_subpath'] = {'path_record_ids': [
        'tianxia.path.body_refining' if body else 'tianxia.path.qi_cultivation']}
    doc['spheres_and_talents'] = {
        'sphere_record_ids': [S.SWORD_SPHERE], 'learned_talent_record_ids': [],
        'automatic_sphere_component_record_ids': packet['component_ids'],
        'automatic_sphere_components': packet['components'],
    }
    # Separate the actual Path key from every other ability.
    for row in doc['ability_scores_and_statistics']['abilities']:
        if row['ability'] != 'WIS':
            row.update(score=10, modifier=0)
    doc['equipment'] = [{'starting_kit': {'items': [{'item_id': S.JIAN, 'name': 'Jian', 'quantity': 1}]}}]
    return doc


def fixture(tmp_path, *, body=False, cl=1, distance=20, attack_bonus=100):
    docs = [source_sheet(body=body, cl=cl), H.sheet([], cl=cl, key='STR', score=10)]
    bundles = []
    for i, (project, doc) in enumerate(zip(PROJECTS, docs)):
        stats = doc['ability_scores_and_statistics']
        stats['initiative'] = {'bonus': 100 if i == 0 else -100}
        stats['technique_attack_bonus'] = attack_bonus
        stats['hit_points']['maximum'] = 1000
        stats['armor_class'] = {'base_value': 10}
        directory = tmp_path / 'portable_characters' / project
        directory.mkdir(parents=True)
        with zipfile.ZipFile(directory / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(project, {'mode': 'ask'}, set())
    combat = CombatService(H.ROOT, tmp_path)
    # Read the native portable source back through the same loader the table uses.
    for project, actor in zip(PROJECTS, IDS):
        bundles.append(compile_character(combat._factory_owner_sheet(project), actor_id=actor,
                                         reaction_plan={'ask': True}))
    arena = combat.tabletop_maps.save({'display_name': 'Sword Practice audit yard',
        'width_squares': 30, 'height_squares': 8, 'walls': [],
        'starts': {'team1': [[2, 3]], 'team2': [[2 + distance // 5, 3]]}})
    mid = combat._finish_factory_match(bundles, list(IDS),
        {IDS[0]: 'team:a', IDS[1]: 'team:b'},
        {IDS[0]: {'x': 2, 'y': 3}, IDS[1]: {'x': 2 + distance // 5, 'y': 3}},
        combat.factory_arenas()['battlefield:map.' + arena['map_id']], [IDS[0]], [IDS[1]],
        control_modes={actor: 'MANUAL' for actor in IDS}, match_seed='MGR-SWORD-WAVE',
        maximum_rounds=10, display_name='Sword Practice audit')['match_id']
    table = TabletopService(combat, tmp_path)
    ready(table, mid, IDS[0])
    return combat, table, mid


def ready(table, mid, actor_id):
    for _ in range(16):
        view = table.state(mid)
        menu = view['menu']
        setup = next((g for g in menu.get('actions', []) if g['label'] == 'Finish fight setup'), None)
        if setup:
            candidate = setup['options'][0]['candidate_id']
        elif menu['actor_id'] == actor_id:
            return
        else:
            candidate = menu['end_turn']
        assert S._press(table, mid, menu, view, candidate=candidate)['status'] == 'COMMITTED'
    pytest.fail('table did not reach requested actor')


def cold(tmp_path, mid):
    session = CombatService(H.ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_full_decoded_source_hashes_and_separate_authority_provenance():
    texts = json.loads((H.ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    for owner, expected in HASHES.items():
        assert hashlib.sha256(texts[owner].encode()).hexdigest() == expected
    # The wave's source hash uses the builder's pre-edit provenance scope.
    from tools.typed_mechanics_helpers import source_texts
    originals = source_texts()
    assert H.mechanics()[WAVE]['source']['text_sha256'] == hashlib.sha256(originals[WAVE].encode()).hexdigest()


@pytest.mark.parametrize('cl,count,kind', [
    (1, 1, 'Slashing'), (4, 1, 'Force'), (5, 2, 'Slashing'), (10, 2, 'Force'),
    (11, 3, 'Slashing'), (16, 3, 'Force'), (17, 4, 'Slashing'), (20, 4, 'Force'),
])
def test_native_wave_damage_choice_cost_key_and_expiry(tmp_path, cl, count, kind):
    combat, table, mid = fixture(tmp_path, cl=cl, distance=60)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[IDS[0]]
    before = dict(actor.resources)
    hp = engine.state.actors[IDS[1]].current_hp
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == IDS[0] and a.display_name == S.BEYOND_HAND)
    assert action.range_ft == 60 and action.economy.value == 'ACTION' and not action.costs
    assert action.parameters['typed']['numbers']['key_mod'] == 4
    view = table.state(mid)
    asked = []
    _, candidate = S._sword_option(view['menu'], target=IDS[1])
    assert S._press(table, mid, view['menu'], view, candidate=candidate, want=kind, asked=asked)['status'] == 'COMMITTED'
    assert any(kind in str(p.get('choice', {})) for p in asked)
    fresh = cold(tmp_path, mid)
    assert fresh.state.actors[IDS[0]].resources == before
    assert not fresh.state.actors[IDS[0]].action_available
    assert bears_mark(fresh.state.actors[IDS[1]], IDS[0], 'Sword Intent')
    assert not bears_mark(fresh.state.actors[IDS[1]], IDS[1], 'Sword Intent')
    rows = [event.model_dump(mode='json') for event in fresh.events
            if event.sequence > view['last_sequence']]
    rolls = [r['payload'] for r in rows if r['event_type'] == 'DAMAGE_ROLLED']
    assert len(rolls) == 1, rolls
    expected_count = count * (2 if rolls[0].get('critical') else 1)
    assert rolls[0]['expression'] == f'{expected_count}d10+4', rolls
    damage = [r['payload'] for r in rows if r['event_type'] == 'DAMAGE_COMMITTED']
    assert len(damage) == 1 and damage[0]['damage_type'] == kind.upper(), damage
    assert hp - fresh.state.actors[IDS[1]].current_hp == rolls[0]['total']
    # A different actor's turn must not remove the source-owned Intent.
    view = table.state(mid)
    assert S._press(table, mid, view['menu'], view)['status'] == 'COMMITTED'
    ready(table, mid, IDS[1])
    assert bears_mark(cold(tmp_path, mid).state.actors[IDS[1]], IDS[0], 'Sword Intent')
    view = table.state(mid)
    assert S._press(table, mid, view['menu'], view)['status'] == 'COMMITTED'
    ready(table, mid, IDS[0])
    assert not bears_mark(cold(tmp_path, mid).state.actors[IDS[1]], IDS[0], 'Sword Intent')


def test_wave_native_range_and_wrong_owner_boundaries(tmp_path):
    combat, table, mid = fixture(tmp_path, distance=65)
    engine = cold(tmp_path, mid)
    assert not any(c.display_name == S.BEYOND_HAND and IDS[1] in c.target_ids
                   for c in engine.legal_candidates())
    assert not any(a.display_name == S.BEYOND_HAND and a.owner_id == IDS[1]
                   for a in engine.action_catalog.values())


def test_wave_miss_does_not_damage_or_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, attack_bonus=-100)
    hp = cold(tmp_path, mid).state.actors[IDS[1]].current_hp
    view = table.state(mid)
    _, candidate = S._sword_option(view['menu'], target=IDS[1])
    assert S._press(table, mid, view['menu'], view, candidate=candidate, want='Force')['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert engine.state.actors[IDS[1]].current_hp == hp
    assert not bears_mark(engine.state.actors[IDS[1]], IDS[0], 'Sword Intent')


def test_wave_automatic_seat_chooses_damage_type_without_model_calls(tmp_path):
    combat, table, mid = fixture(tmp_path)
    combat.set_controller_mode(mid, actor_id=IDS[0], controller_mode='LOCAL_AUTO')
    chosen = next(c for c in combat._load_session(mid).engine.legal_candidates()
                  if c.display_name == S.BEYOND_HAND and IDS[1] in c.target_ids)
    payload = {'actor_id': chosen.actor_id, 'decision_id': chosen.decision_id,
               'state_version': chosen.state_version, 'candidate_id': chosen.candidate_id,
               'target_ids': list(chosen.target_ids), 'option_ids': [], 'destination': None}
    checked = combat.ai_validate(mid, payload)
    assert combat.ai_execute(mid, payload, checked['validation_token'])['status'] == 'COMMITTED'
    assert bears_mark(cold(tmp_path, mid).state.actors[IDS[1]], IDS[0], 'Sword Intent')


@pytest.mark.xfail(strict=True, reason='OPEN: canonical Sword acquisition grants both Practices without a choice')
def test_native_learning_sword_requires_one_practice(tmp_path):
    combat, table, mid = fixture(tmp_path)
    engine = cold(tmp_path, mid)
    sources = {a.parameters.get('typed', {}).get('source') for a in engine.action_catalog.values()
               if a.owner_id == IDS[0]}
    assert not {WAVE, HAND} <= sources


@pytest.mark.xfail(strict=True, reason='OPEN: Body Refiner receives projected Sword without an admitted exception')
def test_native_body_refiner_without_exception_cannot_use_wave(tmp_path):
    combat, table, mid = fixture(tmp_path, body=True)
    assert not any(c.display_name == S.BEYOND_HAND
                   for c in cold(tmp_path, mid).legal_candidates())
