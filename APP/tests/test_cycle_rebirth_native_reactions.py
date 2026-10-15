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
from combat import ext
from combat.ext import mgr_t14_cycle_rebirth as R
from tests.h1_support import sheet
from tests.test_mgr_t14_ling_subpath_cycle_rebirth import (
    acquired, ready, commit, cold, ROOT, ME, FOE,
)


def native_table(tmp_path, doc, talent, foe_talent):
    doc = deepcopy(doc)
    doc['spheres_and_talents']['learned_talent_record_ids'].append(talent)
    foe = sheet([foe_talent], cl=6, name='Opponent')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    bundles = [compile_character(doc, actor_id=ME), compile_character(foe, actor_id=FOE)]
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
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), observe])
    monkeypatch.setitem(ext._NESTED_HOOKS, 'event', {*ext._NESTED_HOOKS.get('event', ()), observe})
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
    if wet:
        assert any(phase == 'movement' for phase, _ in phases)
        assert all(active == ('water' if phase == 'movement' else 'wood') for phase, active in phases)


def test_grave_refuses_failed_teleport_finishes_and_cycles(tmp_path, acquired):
    from combat.ext.earth_responses import foundation_cells
    combat, table, mid = native_table(tmp_path, acquired['fire'],
        'TAL_EARTH_THE_GRAVE_REFUSES_THE_STEP', 'TAL_VOID_EMPTY_STEP')
    ready(combat, table, mid, 'fire')
    # Lay actual Foundation first, while its Earth Source mismatches Fire.
    engine = combat._load_session(mid).engine
    foundations = [c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'EARTH_BASE_SET_FOUNDATION']
    foundation = min(foundations, key=lambda c: (0 if FOE in c.target_ids else
        abs(c.destination.x - 5) + abs(c.destination.y - 6) if c.destination is not None else 100))
    commit(table, mid, foundation.candidate_id, active='fire')
    engine = cold(tmp_path, mid)
    assert (5, 6) in foundation_cells(engine, engine.state.actors[ME])
    end(table, mid, 'earth')
    end(table, mid, 'earth')
    assert table.state(mid)['menu']['actor_id'] == ME
    end(table, mid, 'earth')
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.destination is not None
        and (c.destination.x, c.destination.y) == (7,6)
        and engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'TAL_VOID_EMPTY_STEP')
    prompts = commit(table, mid, candidate.candidate_id, active='earth')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.grave_refuses' for p in prompts)
    engine = cold(tmp_path, mid)
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (5,6)
    assert R.state(engine.state.actors[ME]).data['active'] == 'metal'
