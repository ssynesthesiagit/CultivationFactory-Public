"""Ordinary door actions through persisted CombatService sessions and cold reload."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import pytest
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from combat.diagnostics import CombatGate1Error
from combat.targeting import line_of_effect
from combat.ext.door_interaction import FLAG
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = 'actor:factory.door-owner', 'actor:factory.door-foe'
DOOR = 'object:map.1'


def execute(session, candidate):
    session.mechanical.execute_intent(ActionIntent(intent_id=f'door-{session.engine.state.state_version}',
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))


def setup(tmp_path, *, owner_sheet=None, other_objects=(), **door_flags):
    sheet = owner_sheet or {**SHEET, 'spheres_and_talents': {}}
    bundles = [compile_character(sheet, actor_id=actor) for actor in (ME, FOE)]
    service = CombatService(ROOT, tmp_path)
    arena = to_battlefield(normalize_map({'display_name': 'Door yard', 'width_squares': 12,
        'height_squares': 12, 'objects': [{'id': 1, 'kind': 'door', 'name': 'Wooden door',
            'x': 4, 'y': 6, 'interaction': 'simple_door', 'door_open': 0,
            'door_locked': 0, 'door_jammed': 0, **door_flags}, *other_objects]}))
    mid = service._finish_factory_match(bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, arena, [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed='DOORACT',
        display_name='Door yard', maximum_rounds=5)['match_id']
    session = service._load_session(mid)
    if session.engine.state.current_actor_id != ME:
        execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    return service, session


def choices(session, operation=None):
    return [c for c in session.engine.legal_candidates()
            if c.source_definition_id.startswith('system:door.' + (operation + '.' if operation else ''))]


def cold(tmp_path, session):
    loaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert loaded.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded


def test_open_close_sight_free_once_and_cold_reload(tmp_path):
    service, session = setup(tmp_path)
    engine = session.engine
    actor = engine.state.actors[ME]
    foe = engine.state.actors[FOE]
    assert not engine._line_of_sight_actor_to_cell(actor, foe.position)
    assert not line_of_effect(engine, actor, destination=foe.position)
    assert (4, 6) in engine.grid.blocked
    candidate, = choices(session, 'open')
    assert candidate.source_definition_id.endswith('.free')
    table = TabletopService(service, tmp_path)
    state = table.state(session.match_id, fog=True)
    assert [6, 6] not in state['fog_perception'][ME]['cells']
    menu = state['menu']
    assert any(g['source_definition_id'] == candidate.source_definition_id for g in menu['actions'])
    execute(session, candidate)
    session = cold(tmp_path, session)
    engine = session.engine
    actor = engine.state.actors[ME]
    assert engine.state.objects[DOOR].component['door_open'] == 1
    assert engine.state.objects[DOOR].component['blocks'] is False
    assert (4, 6) not in engine.grid.blocked
    assert engine._line_of_sight_actor_to_cell(actor, engine.state.actors[FOE].position)
    assert line_of_effect(engine, actor, destination=engine.state.actors[FOE].position)
    assert [6, 6] in TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(session.match_id, fog=True)['fog_perception'][ME]['cells']
    assert actor.action_available
    assert type(actor.turn_flags[FLAG]) is int
    candidate, = choices(session, 'close')
    assert candidate.source_definition_id.endswith('.utilize')
    execute(session, candidate)
    session = cold(tmp_path, session)
    assert session.engine.state.objects[DOOR].component['door_open'] == 0
    assert (4, 6) in session.engine.grid.blocked
    assert not session.engine.state.actors[ME].action_available
    assert not choices(session)
    # A new turn replenishes the single free interaction, even after reload.
    for _ in range(2):
        execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    session = cold(tmp_path, session)
    candidate, = choices(session, 'open')
    assert candidate.source_definition_id.endswith('.free')


def test_unavailable_door_refusal_flows_from_table_response_to_door_helper(tmp_path):
    service, session = setup(tmp_path)
    table = TabletopService(service, tmp_path)

    def commit(source):
        state = table.state(session.match_id)
        group = next(row for row in state['menu']['actions'] if row['source_definition_id'] == source)
        option = group['options'][0]
        return table.act(session.match_id, option['candidate_id'], state['menu']['decision_id'],
                         state['menu']['state_version'], 0, [])

    assert commit('system:door.open.free')['status'] == 'COMMITTED'
    assert commit('system:combat.dodge')['status'] == 'COMMITTED'
    response = table.state(session.match_id)
    assert any(row['id'] == DOOR for row in response['objects'])
    reason_key = f'act:system:door.close.utilize:{DOOR}'
    assert response['unavailable_reasons'][reason_key] == 'Your action has already been used this turn.'
    response_path = tmp_path / 'unavailable-door-table-response.json'
    response_path.write_text(json.dumps(response), encoding='utf-8')
    node = shutil.which('node')
    assert node, 'Node.js is required for the door helper regression'
    env = {**os.environ, 'DOOR_TABLE_RESPONSE_PATH': str(response_path)}
    result = subprocess.run([node, '--test', str(ROOT / 'static/tabletop/door-interaction.test.mjs')],
                            cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_target_availability_reuses_checked_candidates_and_rejects_stale_frame(monkeypatch, tmp_path):
    from combat import action_legality

    service, session = setup(tmp_path)
    engine = session.engine
    service._legal_candidates(session)  # the same checked pass the table uses to build its menu
    pairs = [('system:door.open.free', DOOR)]
    original_copy = action_legality.deepcopy
    copies = []

    def counted_copy(value):
        copies.append(1)
        return original_copy(value)

    monkeypatch.setattr(action_legality, 'deepcopy', counted_copy)
    reused = action_legality.query_targets(engine, ME, pairs)
    assert copies == []

    checked_frame = engine._cf_availability
    del engine._cf_availability
    isolated = action_legality.query_targets(engine, ME, pairs)
    assert reused == isolated
    assert len(copies) == 1

    engine._cf_availability = checked_frame
    engine.state.objects[DOOR].component['door_open'] = 1
    stale_state = action_legality.query_targets(engine, ME, pairs)
    assert len(copies) == 2
    assert stale_state[pairs[0]]['code'] == 'NOT_TARGETED'


def test_table_response_scopes_each_door_and_preserves_reach_guidance(tmp_path):
    service, session = setup(tmp_path, other_objects=[
        {'id': 2, 'kind': 'door', 'name': 'Far door', 'x': 10, 'y': 6,
         'interaction': 'simple_door', 'door_open': 0, 'door_locked': 0, 'door_jammed': 0},
        {'id': 3, 'kind': 'crate', 'name': 'Far crate', 'x': 10, 'y': 7},
    ])
    table = TabletopService(service, tmp_path)
    response = table.state(session.match_id)
    assert any(group['source_definition_id'] == 'system:door.open.free'
               and DOOR in [target for option in group['options'] for target in option['target_ids']]
               for group in response['menu']['actions'])
    far_door = 'object:map.2'
    reason_key = f'act:system:door.open.free:{far_door}'
    assert response['unavailable_reasons'][reason_key] == (
        'No eligible target or position is currently available for this action.')
    assert not any(key.endswith(':object:map.3') for key in response['unavailable_reasons'])
    response_path = tmp_path / 'multi-door-table-response.json'
    response_path.write_text(json.dumps(response), encoding='utf-8')
    node = shutil.which('node')
    assert node, 'Node.js is required for the door helper regression'
    env = {**os.environ, 'DOOR_MULTI_TABLE_RESPONSE_PATH': str(response_path)}
    result = subprocess.run([node, '--test', str(ROOT / 'static/tabletop/door-interaction.test.mjs')],
                            cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unused_free_interaction_and_out_of_reach_uses_explanatory_fallback(tmp_path):
    service, session = setup(tmp_path, other_objects=[
        {'id': 2, 'kind': 'door', 'name': 'Far door', 'x': 10, 'y': 6,
         'interaction': 'simple_door', 'door_open': 0, 'door_locked': 0, 'door_jammed': 0},
    ])
    table = TabletopService(service, tmp_path)
    state = table.state(session.match_id)
    dodge = next(row for row in state['menu']['actions'] if row['source_definition_id'] == 'system:combat.dodge')
    table.act(session.match_id, dodge['options'][0]['candidate_id'], state['menu']['decision_id'],
              state['menu']['state_version'], 0, [])
    response = table.state(session.match_id)
    key = f'act:system:door.open.free:object:map.2'
    assert response['unavailable_reasons'][key].startswith('No eligible target')
    response_path = tmp_path / 'out-of-reach-door-table-response.json'
    response_path.write_text(json.dumps(response), encoding='utf-8')
    node = shutil.which('node')
    assert node, 'Node.js is required for the door helper regression'
    env = {**os.environ, 'DOOR_TABLE_RESPONSE_PATH': str(response_path),
           'DOOR_TABLE_DOOR_ID': 'object:map.2'}
    result = subprocess.run([node, '--test', str(ROOT / 'static/tabletop/door-interaction.test.mjs')],
                            cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('flag,word', [('door_locked', 'Locked'), ('door_jammed', 'Stuck')])
def test_locked_or_stuck_not_offered_and_table_explains(tmp_path, flag, word):
    service, session = setup(tmp_path, **{flag: 1})
    assert not choices(session)
    state = TabletopService(service, tmp_path).state(session.match_id)
    assert word in next(o['detail'] for o in state['objects'] if o['id'] == DOOR)
    # Unknown candidate rejection is generic; the menu/status assertions above
    # cover door eligibility. This does not test the door resolver's guards.
    example = next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN')
    intent = ActionIntent(intent_id='blocked-door', decision_id=example.decision_id,
        candidate_id='forged-door', state_version=example.state_version, actor_id=ME, target_ids=(DOOR,))
    before = session.engine.state.model_dump(mode='json')
    with pytest.raises(CombatGate1Error, match='not legal'):
        session.mechanical.execute_intent(intent)
    assert session.engine.state.model_dump(mode='json') == before
    cold(tmp_path, session)


@pytest.mark.parametrize('first', ['grab', 'door'])
def test_grab_and_door_share_free_budget_after_commit_reload_and_reset(tmp_path, first):
    _, session = setup(tmp_path)

    def grabs():
        return [c for c in session.engine.legal_candidates()
                if c.source_definition_id.endswith('.improvised.grab')]

    candidate = grabs()[0] if first == 'grab' else choices(session, 'open')[0]
    execute(session, candidate)
    session = cold(tmp_path, session)
    actor = session.engine.state.actors[ME]
    assert actor.action_available
    assert actor.turn_flags[FLAG] == actor.turns_started
    assert type(actor.turn_flags[FLAG]) is int
    assert not grabs()  # No second free grab after either consumer.
    candidate, = choices(session, 'open' if first == 'grab' else 'close')
    assert candidate.source_definition_id.endswith('.utilize')
    menu = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(session.match_id)['menu']
    displayed = next(a for a in menu['actions'] if a['source_definition_id'] == candidate.source_definition_id)
    assert 'Utilize action' in displayed['label']
    execute(session, candidate)
    session = cold(tmp_path, session)
    assert not session.engine.state.actors[ME].action_available
    for _ in range(2):
        execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    session = cold(tmp_path, session)
    assert FLAG not in session.engine.state.actors[ME].turn_flags
    assert choices(session)[0].source_definition_id.endswith('.free')
    if first == 'door':
        assert grabs()  # Door use alone must not suppress grabbing next turn.


@pytest.mark.parametrize('thread', [False, True])
@pytest.mark.parametrize('altitude,blocked', [(0, True), (1, True), (2, False), (8, False)])
def test_closing_checks_object_vertical_overlap_through_service_reload(tmp_path, thread, altitude, blocked):
    from tests.test_r3i_thread_object import _sheet
    sheet = _sheet() if thread else None
    service, session = setup(tmp_path, owner_sheet=sheet, door_open=1, weight_lb=10, height_ft=10,
        other_objects=[{'id': 2, 'kind': 'crate', 'name': 'Raised crate', 'x': 4, 'y': 6,
                        'z': altitude, 'height_ft': 5, 'blocks': False}])
    session = cold(tmp_path, session)
    candidates = ([c for c in session.engine.legal_candidates()
                   if c.display_name == 'Thread the Object: open/close simple door']
                  if thread else choices(session, 'close'))
    assert bool(candidates) is not blocked
    if not blocked:
        candidate, = candidates
        if thread:
            # Resolve the player's existing door choice through the session intent.
            table = TabletopService(service, tmp_path)
            menu = table.state(session.match_id)['menu']
            result = table.act(session.match_id, candidate.candidate_id, menu['decision_id'], menu['state_version'], 0, [])
            assert result['status'] == 'REACTION_REQUIRED'
            prompt = result['reaction']
            assert 'Thread the Object' in prompt['moment'] and 'Wooden door' in prompt['moment']
            answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['CLOSE']}
            assert table.act(session.match_id, candidate.candidate_id, menu['decision_id'], menu['state_version'], 0, [answer])['status'] == 'COMMITTED'
            session = service._load_session(session.match_id)
        else:
            execute(session, candidate)
        session = cold(tmp_path, session)
        assert session.engine.state.objects[DOOR].component['door_open'] == 0
    else:
        execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
        session = cold(tmp_path, session)
        assert session.engine.state.objects[DOOR].component['door_open'] == 1


def test_close_is_a_free_table_action_and_can_reopen_with_utilize(tmp_path):
    service, session = setup(tmp_path, door_open=1)
    candidate, = choices(session, 'close')
    assert candidate.source_definition_id.endswith('.free')
    table = TabletopService(service, tmp_path)
    menu = table.state(session.match_id)['menu']
    result = table.act(session.match_id, candidate.candidate_id, menu['decision_id'], menu['state_version'], 0, [])
    assert result['status'] == 'COMMITTED'
    session = service._load_session(session.match_id)
    session = cold(tmp_path, session)
    assert session.engine.state.objects[DOOR].component['door_open'] == 0
    assert session.engine.state.actors[ME].action_available
    candidate, = choices(session, 'open')
    assert candidate.source_definition_id.endswith('.utilize')
    execute(session, candidate)
    cold(tmp_path, session)


def test_close_refuses_occupied_opening_and_door_is_out_of_reach(tmp_path):
    _, session = setup(tmp_path)
    execute(session, choices(session, 'open')[0])
    move = next(c for c in session.engine.legal_candidates() if c.kind == 'MOVE'
                and c.destination.x == 4 and c.destination.y == 6)
    execute(session, move)
    session = cold(tmp_path, session)
    assert not choices(session, 'close')
    move = next(c for c in session.engine.legal_candidates() if c.kind == 'MOVE'
                and c.destination.x == 2 and c.destination.y == 6)
    execute(session, move)
    session = cold(tmp_path, session)
    assert not choices(session, 'close')


def test_roster_creature_gets_general_interaction_without_compiled_ability(tmp_path):
    from combat.gate2_runtime_content import AN
    service = CombatService(ROOT, tmp_path)
    bundle = compile_character({**SHEET, 'spheres_and_talents': {}}, actor_id=ME)
    arena = to_battlefield(normalize_map({'width_squares': 12, 'height_squares': 12,
        'objects': [{'id': 1, 'kind': 'door', 'x': 4, 'y': 6,
                     'interaction': 'simple_door', 'door_open': 0, 'door_locked': 0, 'door_jammed': 0}]}))
    mid = service._finish_factory_match([bundle], [ME, AN], {ME: 'team:a', AN: 'team:b'},
        {ME: {'x': 6, 'y': 6}, AN: {'x': 3, 'y': 6}}, arena, [ME], [AN],
        control_modes={ME: 'MANUAL', AN: 'MANUAL'}, match_seed='DOORACT-ROSTER',
        display_name='Roster door', maximum_rounds=5)['match_id']
    session = service._load_session(mid)
    if session.engine.state.current_actor_id != AN:
        execute(session, next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN'))
    candidate, = choices(session, 'open')
    assert candidate.source_definition_id not in session.engine.state.actors[AN].action_ids
    execute(session, candidate)
    cold(tmp_path, session)
