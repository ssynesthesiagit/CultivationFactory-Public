"""Red Cord Guard through imported sheets, legal table intents and cold replay.

No saved private fighters, scripted successful receipts, or injected Due. The
owner earns Due by answering the creature that actually damaged its ally.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from non_sphere_authority.foundation_mechanics import (
    resolve_initial_foundation_state, verified_foundation_records,
)

# Literal dependencies for the public exporter's dynamic registry closure.
DEPENDENCIES = (
    'combat/rules/feature_blocks.d/shi.json',
    'combat/rules/feature_blocks.d/sys_resources-states.json',
    'non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
    'non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/rules_text.json',
)
ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = 'karma_knot_root_v0_2B'
GUARD = 'foundation.karma_knot_root_v0_2B.red_cord_guard'
REACTION = 'reaction:typed.' + GUARD
GENERATE = 'passive:foundation.karma_knot_root_v0_2B.generate_karmic_due'
DUE = 'resource:foundation.karmic_due'
MIND = 'tianxia.path.spirit_awakening.feature.mind_spike'
OWNER, ALLY, FOE = ('actor:factory.rcg-' + n for n in ('owner', 'ally', 'foe'))


def document(name, score=14, *, foundation=True):
    doc = {
        'identity': {'name': name, 'path': 'Spirit Awakening', 'key_ability': 'WIS',
                     'cultivation_level': 5, 'proficiency_bonus': 2},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': score if a == 'WIS' else 14,
                          'modifier': (score - 10) // 2 if a == 'WIS' else 2}
                         for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Resonance', 'maximum': 100},
            'hit_points': {'maximum': 100}, 'armor_class': {'base_value': 14},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 30,
            'technique_attack_bonus': 8},
        # Path imports now require the path record as well as an explicit
        # feature selection; listing the feature alone is not a legal source.
        'path_and_subpath': {'path_record_ids': ['tianxia.path.spirit_awakening'],
                             'path_feature_record_ids': [MIND]},
    }
    if foundation:
        source = verified_foundation_records()[FOUNDATION]
        initial = resolve_initial_foundation_state(source, ['tianxia.path.spirit_awakening'])
        assert initial['stage'] == 'Awakened'
        assert initial['resource']['initial_current'] == 0
        doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': initial['stage'],
                             'resource': {'name': initial['resource']['name'],
                                          'resource_id': initial['resource']['resource_id'],
                                          'maximum': initial['resource']['maximum'], 'current': 0}}
    return doc


def setup(tmp_path, score=8, *, distance=30, owns=True):
    docs = [document('Wren', score, foundation=owns), document('Tobin', foundation=False),
            document('Mara', foundation=False)]
    for aid, doc in zip((OWNER, ALLY, FOE), docs):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [compile_character(combat._factory_owner_sheet(aid.removeprefix('actor:factory.')),
                                actor_id=aid, reaction_plan={'ask': True})
               for aid in (OWNER, ALLY, FOE)]
    mid = combat._finish_factory_match(
        bundles, [OWNER, ALLY, FOE], {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        # Row 5 is open in main's Pillar Arena (its centre pillar covers (9..10, 6..7)); row 6 put the ally inside it.
        {OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 3 + distance // 5, 'y': 5},
         FOE: {'x': 6, 'y': 5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER, ALLY], [FOE], control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)},
        match_seed='MGR-T15-RED-CORD', display_name='Red Cord Guard', maximum_rounds=15)['match_id']
    return combat, table, mid


def send(table, mid, cid, answers=()):
    menu = table.state(mid)['menu']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))


def settle(table, mid, cid, use=False):
    answers, prompts = [], []
    for _ in range(15):
        result = send(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']
        prompts.append(p)
        answers.append({**p['context'], 'selection': 'USE' if use and
                        p['context']['reaction_source_id'] == REACTION else 'DECLINE'})
    raise AssertionError('Unsettled choices')


def turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('No native turn')


def candidate(combat, mid, target):
    rows = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.target_ids == (target,) and MIND in c.source_definition_id]
    assert rows, 'Mind Spike must be a legal imported Path technique'
    return rows[0].candidate_id


def cold(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def earn_due(tmp_path, combat, table, mid):
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, ALLY))
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FOE and ALLY in e.target_ids
               for e in cold(tmp_path, mid).events)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, FOE))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[DUE] == 1
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and
             e.actor_id == OWNER and e.payload.get('resource_id') == DUE]
    assert len(gains) == 1 and gains[0].source_definition_id == GENERATE
    assert gains[0].payload['gained'] == 1
    return engine


@pytest.mark.parametrize('score,reduction', [(16, 5), (10, 2), (8, 1), (6, 0), (4, 0)])
@pytest.mark.parametrize('target', [OWNER, ALLY])
def test_signed_sum_native_payment_and_cold_replay(tmp_path, score, reduction, target):
    combat, table, mid = setup(tmp_path, score)
    earn_due(tmp_path, combat, table, mid)
    turn(table, mid, FOE)
    before = cold(tmp_path, mid).state.actors[target].current_hp
    cid = candidate(combat, mid, target)
    state = cold(tmp_path, mid).state.model_dump(mode='json')
    preview = send(table, mid, cid)
    assert preview['status'] == 'REACTION_REQUIRED', preview
    assert preview['reaction']['context']['reaction_source_id'] == REACTION
    assert send(table, mid, cid)['reaction'] == preview['reaction']
    assert cold(tmp_path, mid).state.model_dump(mode='json') == state
    settle(table, mid, cid, use=True)
    engine = cold(tmp_path, mid)
    receipts = [e for e in engine.events if e.source_definition_id == GUARD
                and e.event_type == 'REACTION_RESOLVED']
    assert len(receipts) == 1
    receipt = receipts[0]
    prevented = min(receipt.payload['pending_before'], reduction)
    assert receipt.payload['reduction'] == prevented
    damages = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.actor_id == FOE and target in e.target_ids]
    assert damages[-1].payload['hp_damage'] == receipt.payload['pending_before'] - prevented
    assert engine.state.actors[target].current_hp == before - damages[-1].payload['hp_damage']
    spent = [e for e in engine.events if e.source_definition_id == GUARD and
             e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == DUE]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    assert engine.state.actors[OWNER].resources[DUE] == 0
    assert engine.state.actors[OWNER].reaction_available is False


@pytest.mark.parametrize('boundary', ['decline', 'no_due', 'no_owner', 'outside'])
def test_native_negative_boundaries(tmp_path, boundary):
    combat, table, mid = setup(tmp_path, distance=35 if boundary == 'outside' else 30,
                               owns=boundary != 'no_owner')
    if boundary not in ('no_due', 'no_owner'):
        earn_due(tmp_path, combat, table, mid)
    turn(table, mid, FOE)
    before = cold(tmp_path, mid).state.actors[ALLY].current_hp
    prompts = settle(table, mid, candidate(combat, mid, ALLY))
    engine = cold(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts) == (boundary == 'decline')
    assert not [e for e in engine.events if e.source_definition_id == GUARD and
                e.event_type in ('RESOURCE_SPENT', 'REACTION_RESOLVED')]
    last = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and ALLY in e.target_ids][-1]
    assert engine.state.actors[ALLY].current_hp == before - last.payload['hp_damage']
    assert engine.state.actors[OWNER].resources.get(DUE, 0) == int(boundary in ('decline', 'outside'))

def test_fixture_creatures_stand_on_open_squares_with_clear_sight(tmp_path):
    # RB1 (review batchfail 20261018): main's Pillar Arena has a BLOCKED pillar at (9,6)-(10,7). The fixture put the
    # ally on (9,6)/(10,6) for the 30/35 ft boundaries, so Mind Spike had no line of effect and no legal target.
    for distance in (30, 35):
        combat, table, mid = setup(tmp_path / str(distance), distance=distance)
        engine = combat._load_session(mid).engine
        arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
        regions = arena['terrain_regions'] if isinstance(arena['terrain_regions'], list) else eval(arena['terrain_regions'])
        blocked = {(c['x'], c['y']) for r in regions if r['terrain_type'] == 'BLOCKED' for c in r['cells']}
        for aid in (OWNER, ALLY, FOE):
            pos = engine.state.actors[aid].position
            assert (pos.x, pos.y) not in blocked, (aid, pos)
        turn(table, mid, FOE)
        candidate(combat, mid, ALLY)
