"""Native specialized reactions must publish their own successful completion.

The owner/knowledge fixture is source-backed acquisition projection; triggers
and reactions here are printed techniques, compiled and committed by the table.
The separate canonical-acquisition regression proves the full creation history.
"""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat import ext
from combat.ext import mgr_t14_cycle_rebirth as R
from tests.h1_support import sheet
from tests.test_mgr_t14_ling_subpath_cycle_rebirth import (
    acquired, ready, commit, cold, ROOT, ME, FOE,
)


def native_table(tmp_path, doc, talent, foe_talent, *, suppression=None):
    doc = deepcopy(doc)
    doc['spheres_and_talents']['learned_talent_record_ids'].append(talent)
    foe = sheet([foe_talent], cl=6, name='Opponent')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    bundles = [compile_character(doc, actor_id=ME), compile_character(foe, actor_id=FOE)]
    if suppression:
        # Explicit Source-authored restriction exercises the native effect
        # producer; no condition or ownership/activation receipt is injected.
        limit = ActionDefinition(source_definition_id='action:test.native_limit', display_name='Test elemental restriction',
            owner_id=ME, economy=EconomyKind.ACTION, costs=((R.QI, 1),),
            resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed':{'source':'test:restriction_source','numbers':{'cl':6},'riders':[],
                'effects':[{'type':'cultivation_limit','applies_to':'self','element':suppression,
                            'expires_on':'START_OF_SELF_NEXT_TURN'}]}})
        bundles[0]['action_catalog'].append(limit.model_dump(mode='json'))
        bundles[0]['actor_template']['action_ids'].append(limit.source_definition_id)
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    # Deterministic hits and saves, without replacing any reaction/receipt.
    bundles[1]['actor_template']['saving_throws']['CHA'] = -100
    for action in bundles[1]['action_catalog']:
        typed = action.get('parameters', {}).get('typed', {})
        typed.get('numbers', {})['attack_bonus'] = 100
    bundles[1].pop('bundle_sha256', None)
    bundles[1]['bundle_sha256'] = canonical_sha256(bundles[1])
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME:'team:a', FOE:'team:b'},
        {ME:{'x':3,'y':6}, FOE:{'x':5,'y':6}}, arena, [ME], [FOE],
        control_modes={ME:'MANUAL',FOE:'MANUAL'}, match_seed='CYCLE-NATIVE-REACTIONS',
        maximum_rounds=10, display_name='Cycle reaction regression')['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def end(table, mid, active):
    commit(table, mid, table.state(mid)['menu']['end_turn'], active=active)


@pytest.mark.parametrize('wet', [False, True])
def test_water_shield_finishes_and_cycles_on_the_opponents_turn(tmp_path, acquired, monkeypatch, wet):
    combat, table, mid = native_table(tmp_path, acquired['metal'],
        'TAL_WATER_WATER_SHIELD', 'FIRE_BASE_IGNITE')
    ready(combat, table, mid, 'metal' if wet else 'water')
    if wet:
        engine = combat._load_session(mid).engine
        basin = next(c for c in engine.legal_candidates() if c.destination is not None
            and (c.destination.x, c.destination.y) == (3,6)
            and engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == 'Shape Current: Mist Basin')
        commit(table, mid, basin.candidate_id, active='metal')
        end(table, mid, 'metal')
        end(table, mid, 'water')
    phases = []
    def observe(engine, event_type, kwargs):
        if event_type == 'MOVEMENT_COMMITTED' and kwargs.get('source_definition_id') == 'TAL_WATER_WATER_SHIELD':
            phases.append(('movement', R.state(engine.state.actors[ME]).data['active']))
        if event_type == 'DAMAGE_COMMITTED' and ME in kwargs.get('target_ids', ()):
            phases.append(('after_shield', R.state(engine.state.actors[ME]).data['active']))
    # Only the ordinary event phase: the nested phase runs before the
    # reaction's completion settles, so it would observe the pre-shift state.
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), observe])
    end(table, mid, 'water')
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
        if c.target_ids == (ME,) and engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'FIRE_BASE_IGNITE')
    prompts = commit(table, mid, candidate.candidate_id, active='water')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.water_shield' for p in prompts)
    engine = cold(tmp_path, mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == 'TAL_WATER_WATER_SHIELD'
               for e in engine.events)
    assert R.state(engine.state.actors[ME]).data['active'] == 'wood'
    # The reaction completes after its damage packet (and, when it is offered,
    # after the free movement). The last observation is therefore the shifted
    # Attunement; a movement never runs after the shift.
    assert phases and phases[-1][1] == 'wood'
    assert all(active == 'water' for phase, active in phases if phase == 'movement')


def test_grave_refuses_failed_teleport_finishes_and_cycles(tmp_path, acquired, monkeypatch):
    from combat.ext.earth_responses import foundation_cells
    combat, table, mid = native_table(tmp_path, acquired['fire'],
        'TAL_EARTH_THE_GRAVE_REFUSES_THE_STEP', 'TAL_VOID_EMPTY_STEP')
    ready(combat, table, mid, 'fire')
    # Lay actual Foundation first, while its Earth Source mismatches Fire.
    engine = combat._load_session(mid).engine
    foundations = [c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'EARTH_BASE_SET_FOUNDATION']
    # Set Foundation cannot cover an occupied square, so lay it in a legal
    # square beside the opponent; the opponent then walks onto it before its
    # teleport, which is exactly the printed trigger ("teleports out of your
    # Foundation").
    foundation = min(foundations, key=lambda c: 0 if c.destination is None else 1)
    commit(table, mid, foundation.candidate_id, active='fire')
    engine = cold(tmp_path, mid)
    cells = foundation_cells(engine, engine.state.actors[ME])
    start = (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y)
    target = min(cells, key=lambda cell: (abs(cell[0] - start[0]) + abs(cell[1] - start[1]), cell))
    assert target != start
    end(table, mid, 'fire')
    engine = combat._load_session(mid).engine
    step = next(c for c in engine.legal_candidates() if c.destination is not None
                and c.kind.value == 'MOVE'
                and (c.destination.x, c.destination.y) == target
                and (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == start)
    commit(table, mid, step.candidate_id, active='earth')
    end(table, mid, 'earth')
    assert table.state(mid)['menu']['actor_id'] == ME
    end(table, mid, 'earth')
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.destination is not None
        and (c.destination.x, c.destination.y) == (7,6)
        and engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'TAL_VOID_EMPTY_STEP')
    levels = []
    def declared(engine, actor, action, candidate, intent):
        if action.source_definition_id == 'TAL_EARTH_THE_GRAVE_REFUSES_THE_STEP':
            levels.append(action.parameters['typed']['numbers']['cl'])
    monkeypatch.setitem(ext._HOOKS, 'technique_declared', [*ext._HOOKS.get('technique_declared', []), declared])
    prompts = commit(table, mid, candidate.candidate_id, active='earth')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.grave_refuses' for p in prompts)
    engine = cold(tmp_path, mid)
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == target
    assert R.state(engine.state.actors[ME]).data['active'] == 'metal'
    assert levels and all(level == 6 for level in levels)


def test_suppressed_water_shield_is_not_offered_paid_or_counted(tmp_path, acquired):
    combat, table, mid = native_table(tmp_path, acquired['metal'],
        'TAL_WATER_WATER_SHIELD', 'FIRE_BASE_IGNITE', suppression='water')
    ready(combat, table, mid, 'water')
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == 'action:test.native_limit')
    commit(table, mid, candidate.candidate_id, active='water')
    engine = cold(tmp_path, mid)
    before = dict(engine.state.actors[ME].resources)
    end(table, mid, 'water')
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
        if c.target_ids == (ME,) and engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'FIRE_BASE_IGNITE')
    prompts = commit(table, mid, candidate.candidate_id, active='water')
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.water_shield' for p in prompts)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources == before
    assert engine.state.actors[ME].reaction_available
    assert R.state(engine.state.actors[ME]).data['active'] == 'water'
