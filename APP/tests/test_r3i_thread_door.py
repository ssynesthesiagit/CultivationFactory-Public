"""Explicit simple-door Thread actions commit and replay at the table boundary."""
from types import SimpleNamespace

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield, battlefield_as_map
from combat.tabletop_service import TabletopService
from tests.test_auto_lane1 import ROOT
from tests.test_r3i_thread_object import _sheet
from tests import test_sys_placed_effects as P
from tests import test_sysv2_objects as O

BUTTON = 'Thread the Object: open/close simple door'


def _row(opened=0, **changes):
    return {'id': 1, 'kind': 'door', 'name': 'Light hinged door', 'x': 4, 'y': 6,
            'weight_lb': 10, 'interaction': 'simple_door', 'door_open': opened,
            'door_locked': 0, 'door_jammed': 0, **changes}


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('opened', [0, 1])
@pytest.mark.parametrize('decline', [False, True])
def test_thread_door_table_commit_reload(tmp_path, mode, opened, decline):
    owner, foe = P.ME, 'actor:factory.door-foe'
    sheets = [_sheet(), _sheet()]
    sheets[1]['spheres_and_talents'] = {}
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask': True})
               for d, a in zip(sheets, [owner, foe])]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = to_battlefield(normalize_map({'width_squares': 20, 'height_squares': 14,
        'objects': [_row(opened), {'id': 2, 'kind': 'door', 'x': 8, 'y': 6}]}))
    mid = combat._finish_factory_match(bundles, [owner, foe], {owner: 'team:a', foe: 'team:b'},
        {owner: {'x': 3, 'y': 6}, foe: {'x': 6, 'y': 6}}, arena, [owner], [foe],
        control_modes={owner: mode, foe: 'LOCAL_AUTO'}, match_seed='R3I-THREAD',
        display_name='Door yard', maximum_rounds=5)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    for _ in range(2):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == owner:
            break
        assert act(menu['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates() if c.display_name == BUTTON]
    assert {c.target_ids for c in candidates} == {('object:map.1',)}
    candidate = candidates[0]
    before = engine.state.model_dump(mode='json')
    result = act(candidate.candidate_id)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == owner
    assert BUTTON in prompt['moment'] and 'Light hinged door' in prompt['moment']
    operation = 'CLOSE' if opened else 'OPEN'
    assert {o['id'] for o in prompt['choice']['options']} == {operation, 'LEAVE'}
    assert act(candidate.candidate_id)['reaction'] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['LEAVE' if decline else operation]}
    assert act(candidate.candidate_id, [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    obj = loaded.engine.state.objects['object:map.1']
    expected = opened if decline else 1 - opened
    assert obj.component['door_open'] == expected
    assert type(obj.component['door_open']) is int
    assert obj.component['blocks'] == (not expected)
    assert obj.position == engine.state.objects['object:map.1'].position
    assert obj.current_hp == before['objects']['object:map.1']['current_hp']
    assert loaded.engine.state.objects['object:map.2'].model_dump(mode='json') == before['objects']['object:map.2']
    loaded.engine.legal_candidates()  # reconstruct wall query from reloaded objects
    assert ((4, 6) in loaded.engine.grid.blocked) == (not expected)
    assert ((8, 6) in loaded.engine.grid.blocked)
    assert len([e for e in loaded.engine.events if e.event_type == 'OBJECT_UPDATED'
                and e.source_definition_id == candidate.source_definition_id]) == int(not decline)
    for actor in [owner, foe]:
        assert loaded.engine.state.actors[actor].resources == before['actors'][actor]['resources']
        assert loaded.engine.state.actors[actor].movement_remaining_ft == before['actors'][actor]['movement_remaining_ft']
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('changes', [
    {'weight_lb': None}, {'weight_lb': 11}, {'door_locked': 1}, {'door_jammed': 1},
    {'door_locked': None}, {'door_open': True}, {'door_jammed': 0.0},
    {'interaction': None}, {'kind': 'gate'}, {'unattended': False}, {'artifact': True},
])
def test_thread_door_requires_explicit_eligibility(changes):
    document = normalize_map({'objects': [_row(**changes)]})
    engine = O.fight(compile_character(_sheet(), actor_id=O.ME), objects=document['objects'])
    assert not O.candidates(engine, BUTTON)


def test_door_state_roundtrips_and_attached_door_cannot_move():
    document = normalize_map({'objects': [_row(1)]})
    assert battlefield_as_map(to_battlefield(document))['objects'] == document['objects']
    engine = O.fight(compile_character(_sheet(), actor_id=O.ME), objects=document['objects'])
    assert not O.candidates(engine, 'Thread the Object: move object')
    assert O.candidates(engine, BUTTON)
    assert not O.candidates(O.fight(O.build(None, []), objects=document['objects']), BUTTON)


def test_open_door_cannot_close_on_creature_footprint_or_other_object():
    engine = O.fight(compile_character(_sheet(), actor_id=O.ME), objects=[_row(1)])
    assert O.candidates(engine, BUTTON)
    # Place the door under the existing creature through its initial map state.
    owner = engine.state.actors[O.ME]
    blocked = _row(1, x=owner.position.x, y=owner.position.y)
    assert not O.candidates(O.fight(compile_character(_sheet(), actor_id=O.ME), objects=[blocked]), BUTTON)
    occupied = [_row(1), {'id': 2, 'kind': 'crate', 'x': 4, 'y': 6}]
    assert not O.candidates(O.fight(compile_character(_sheet(), actor_id=O.ME), objects=occupied), BUTTON)
    from tests.test_riders_lane3 import _grow
    _grow(engine, actor_id=O.ME, cells=2)
    assert not O.candidates(engine, BUTTON)  # (4, 6) is the far edge, not the anchor


def test_automatic_selected_door_action_leaves_state_unchanged_without_prompt(tmp_path):
    engine = O.fight(compile_character(_sheet(), actor_id=O.ME), objects=[_row()])
    candidate = O.candidates(engine, BUTTON)[0][1]
    intent = ActionIntent(intent_id='auto-door', actor_id=candidate.actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, target_ids=candidate.target_ids)
    before = engine.state.model_dump(mode='json')
    result = CombatService(ROOT, tmp_path)._run_preview(
        SimpleNamespace(engine=engine, match_id=engine.state.match_id),
        {'participant_control_modes': {a: 'LOCAL_AUTO' for a in engine.state.actors}}, intent, ())
    assert not any(e['event_type'] == 'OBJECT_UPDATED' for e in result['events'])
    assert engine.state.model_dump(mode='json') == before
