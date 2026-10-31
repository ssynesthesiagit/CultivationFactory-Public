"""Search uses the real table journal and never an unseen enemy location."""
import pytest

from combat import ai_search, target_knowledge
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_hidden_targeting import table_fight, turn, LEFT, RIGHT, ROOT, hidden_fight


def context(engine):
    policy, _ = PolicyLibrary(ROOT).for_actor(engine.state.current_actor_id)
    return build_decision_context(engine, policy, for_ai=True)


def yard(tmp_path, disconnected=False):
    combat, _, _ = table_fight(tmp_path)
    combat.tabletop_maps.save({'display_name': 'Search yard', 'width_squares': 25, 'height_squares': 15,
        'walls': [{'shape': 'rect', 'points': [[10, 0], [11, 15 if disconnected else 10]], 'filled': True}],
        'starts': {'team1': [[2, 5]], 'team2': [[22, 5]]}})
    mid = combat.create_factory_match(project_ids=['left'], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: 'MANUAL', RIGHT: 'MANUAL'}, arena_id='battlefield:map.search-yard',
        match_seed='SOL175-TABLE')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


def test_search_commits_and_reloads_then_normal_combat_resumes(tmp_path):
    combat, table, mid = yard(tmp_path)
    e = combat._load_session(mid).engine
    first = context(e)
    first_choice = LocalDeterministicController().choose_primary_action(first)
    first_candidate = next(row for row in first.legal_candidates if row.candidate_id == first_choice.intent.candidate_id)
    assert first_candidate.kind == 'MOVE', 'An AI with no observed enemy must walk to look for one, rather than Dodge/end-turn.'
    assert ai_search.saved_policy(e.events) == 1
    assert not any(a.team_id != e.state.actors[LEFT].team_id for a in context(e).actors)
    start = e.state.actors[LEFT].position
    moved = 0
    for _ in range(35):
        c = context(e)
        if c.search_move_candidate_id is None:
            break
        choice = LocalDeterministicController().choose_primary_action(c)
        assert choice.intent.candidate_id == c.search_move_candidate_id
        assert choice.record.scored_alternatives[0].components[0].component == 'search_unknown_opponent'
        state = table.state(mid)
        assert table.act(mid, choice.intent.candidate_id, c.decision_id, c.state_version,
                         state['last_sequence'])['status'] == 'COMMITTED'
        moved += 1
        fresh = CombatService(ROOT, tmp_path)
        e = fresh._load_session(mid).engine
        assert ai_search.saved_policy(e.events) == 1
        if not e.state.actors[LEFT].movement_remaining_ft:
            from tests.test_lock2_persistence import act
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
            turn(table, mid, LEFT)
            e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert moved and e.state.actors[LEFT].position != start
    assert target_knowledge.located(e, e.state.actors[LEFT], e.state.actors[RIGHT])
    assert context(e).search_move_candidate_id is None
    assert combat._load_session(mid).verify()['status'] == 'PASS'


@pytest.mark.parametrize('disconnected', [False, True])
def test_unknown_position_does_not_change_search_and_disconnected_map_is_safe(tmp_path, disconnected):
    combat, _, mid = yard(tmp_path, disconnected)
    e = combat._load_session(mid).engine
    c = context(e)
    assert c.search_move_candidate_id
    e.state.actors[RIGHT].position = Position(x=23, y=7)
    assert context(e).search_move_candidate_id == c.search_move_candidate_id
    selected = next(row for row in c.legal_candidates if row.candidate_id == c.search_move_candidate_id)
    assert not selected.metadata.get('hazard_exposure')
    assert (selected.destination.x, selected.destination.y) not in e.grid.blocked


def test_missing_stamp_and_manual_context_remain_legacy(tmp_path):
    combat, _, mid = yard(tmp_path)
    e = combat._load_session(mid).engine
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    assert build_decision_context(e, policy).search_move_candidate_id is None
    for event in e.events:
        event.payload.pop(ai_search.KEY, None)
    c = context(e)
    assert c.search_move_candidate_id is None
    assert 'search_move_candidate_id' not in c.model_dump(mode='json')


def test_search_excludes_hazard_receipts_and_public_hazard_goals(tmp_path):
    combat, _, mid = yard(tmp_path)
    e = combat._load_session(mid).engine
    c = context(e)
    selected = next(row for row in c.legal_candidates if row.candidate_id == c.search_move_candidate_id)
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    rows = tuple(row.model_copy(update={'metadata': {**row.metadata, 'hazard_exposure': True}})
                 if row.candidate_id == selected.candidate_id else row for row in c.legal_candidates)
    result = ai_search.search_move(e, e.state.actors[LEFT], rows, policy,
                                  target_knowledge.actors_for(e, e.state.actors[LEFT]), c.recent_events)
    assert result != selected.candidate_id
    e.grid.qi_hazard.add((selected.destination.x, selected.destination.y))
    result = ai_search.search_move(e, e.state.actors[LEFT], rows, policy,
                                  target_knowledge.actors_for(e, e.state.actors[LEFT]), c.recent_events)
    if result:
        destination = next(row.destination for row in rows if row.candidate_id == result)
        assert (destination.x, destination.y) not in e.grid.qi_hazard


def test_search_explores_when_this_turn_cannot_advance_the_public_route(tmp_path):
    combat, _, mid = yard(tmp_path)
    e = combat._load_session(mid).engine
    c = context(e)
    viewer = e.state.actors[LEFT]
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    # The legal menu is authoritative even when a temporary obstruction means
    # the public map's shortest route cannot advance during this turn.
    rows = tuple(row for row in c.legal_candidates if row.kind == 'MOVE'
                 and row.destination.x < viewer.position.x and row.destination.y <= viewer.position.y)
    assert rows
    result = ai_search.search_move(e, viewer, rows, policy,
                                  target_knowledge.actors_for(e, viewer), c.recent_events)
    assert result in {row.candidate_id for row in rows}


def test_search_keeps_existing_stand_up_priority(tmp_path):
    combat, _, mid = yard(tmp_path)
    e = combat._load_session(mid).engine
    viewer = e.state.actors[LEFT]
    e._apply_condition(viewer, 'condition:typed.prone', 'test:prone', viewer.entity_id, expires_on='STAND_UP')
    c = context(e)
    assert c.search_move_candidate_id
    choice = LocalDeterministicController().choose_primary_action(c)
    selected = next(row for row in c.legal_candidates if row.candidate_id == choice.intent.candidate_id)
    assert 'standing_cost_ft' in selected.metadata


def test_remembered_place_then_widen_without_following_hidden_movement(tmp_path, monkeypatch):
    combat, _, mid = hidden_fight(tmp_path, monkeypatch, move=True)
    e = combat._load_session(mid).engine
    c = context(e)
    assert c.search_move_candidate_id
    original = c.search_move_candidate_id
    e.state.actors[RIGHT].position = Position(x=20, y=20)
    assert context(e).search_move_candidate_id == original
    e.state.actors[LEFT].position = Position(x=15, y=11)
    e.state.actors[LEFT].movement_remaining_ft = 30
    assert context(e).search_move_candidate_id


def test_later_sighting_renews_previously_travelled_goal_after_table_reload(tmp_path, monkeypatch):
    from tests.test_hidden_targeting import move_to
    from tests.test_lock2_persistence import act
    from tests.r10_fixup_support import cast_sender, commit, fixed_dice

    combat, table, mid = table_fight(tmp_path, left_at=(9, 11), right_at=(21, 11))
    turn(table, mid, LEFT)
    move_to(table, mid, (15, 11))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    move_to(table, mid, (9, 11))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    # A later visible arrival renews information about an already travelled cell.
    move_to(table, mid, (15, 11))
    for name in ('Augment Darkness: Greater Darkness', 'Augment Darkness: Persistent Darkness',
                 'Shape Darkness: Pure Darkness'):
        commit(cast_sender(combat, table, mid, name))
    commit(cast_sender(combat, table, mid, 'Darkness + Greater Darkness + Persistent Darkness', at=(15, 11)))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    fixed_dice(monkeypatch, [100] * 60)
    commit(cast_sender(combat, table, mid, 'Hide'))
    move_to(table, mid, (16, 11))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)

    def reload():
        fresh = CombatService(ROOT, tmp_path)
        return fresh, TabletopService(fresh, tmp_path), fresh._load_session(mid).engine

    combat, table, e = reload()
    viewer = e.state.actors[LEFT]
    assert e.state.observations[viewer.team_id][RIGHT] == Position(x=15, y=11)
    c = context(e)
    selected = next(row for row in c.legal_candidates if row.candidate_id == c.search_move_candidate_id)
    assert selected.destination == Position(x=15, y=11), 'Travel before the later sighting must not clear its goal'
    assert LocalDeterministicController().choose_primary_action(c).intent.candidate_id == c.search_move_candidate_id
    original = c.search_move_candidate_id
    e.state.actors[RIGHT].position = Position(x=20, y=20)
    assert context(e).search_move_candidate_id == original
    combat, table, e = reload()
    c = context(e)
    state = table.state(mid)
    assert table.act(mid, c.search_move_candidate_id, c.decision_id, c.state_version,
                     state['last_sequence'])['status'] == 'COMMITTED'
    combat, table, e = reload()
    assert e.state.actors[LEFT].position == Position(x=15, y=11)
    assert not target_knowledge.located(e, e.state.actors[LEFT], e.state.actors[RIGHT])
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    combat, table, e = reload()
    c = context(e)
    widened = next(row for row in c.legal_candidates if row.candidate_id == c.search_move_candidate_id)
    assert widened.destination != Position(x=15, y=11)
    assert max(abs(widened.destination.x - 15), abs(widened.destination.y - 11)) > 0
    state = table.state(mid)
    assert table.act(mid, c.search_move_candidate_id, c.decision_id, c.state_version,
                     state['last_sequence'])['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    combat, table, e = reload()
    c = context(e)
    continued = next(row for row in c.legal_candidates if row.candidate_id == c.search_move_candidate_id)
    assert continued.destination != Position(x=15, y=11), 'An investigated sighting must stay cleared after leaving and reloading'
    assert combat._load_session(mid).verify()['status'] == 'PASS'


def test_same_coordinate_sighting_is_renewed_after_table_commit_and_reload(tmp_path):
    from tests.test_hidden_targeting import move_to
    from tests.test_lock2_persistence import act

    combat, _, _ = table_fight(tmp_path)
    combat.tabletop_maps.save({'display_name': 'Renewed sighting yard',
        'width_squares': 25, 'height_squares': 25,
        'walls': [{'shape': 'rect', 'points': [[14, 8], [17, 9]], 'filled': True}],
        'starts': {'team1': [[9, 11]], 'team2': [[15, 11]]}})
    mid = combat.create_factory_match(project_ids=['left'], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: 'MANUAL', RIGHT: 'MANUAL'},
        arena_id='battlefield:map.renewed-sighting-yard', match_seed='SOL175-RENEWED')['match_id']
    table = TabletopService(combat, tmp_path)

    def conceal():
        turn(table, mid, RIGHT)
        move_to(table, mid, (15, 7))
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        turn(table, mid, LEFT)

    conceal()
    move_to(table, mid, (15, 11))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    move_to(table, mid, (9, 11))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    move_to(table, mid, (15, 11))
    # No new remembered coordinate: only the freshness of the sighting changes.
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    conceal()
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    e = combat._load_session(mid).engine
    viewer = e.state.actors[LEFT]
    assert not target_knowledge.located(e, viewer, e.state.actors[RIGHT])
    assert e.state.observations[viewer.team_id][RIGHT] == Position(x=15, y=11)
    c = context(e)
    selected = next(row for row in c.legal_candidates if row.candidate_id == c.search_move_candidate_id)
    assert selected.destination == Position(x=15, y=11), 'A renewed same-square sighting must survive reload'
    state = table.state(mid)
    assert table.act(mid, c.search_move_candidate_id, c.decision_id, c.state_version,
                     state['last_sequence'])['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    assert fresh._load_session(mid).engine.state.actors[LEFT].position == Position(x=15, y=11)
    assert fresh._load_session(mid).verify()['status'] == 'PASS'


@pytest.mark.parametrize('evidence', ['observations_after', 'redacted_event'])
def test_search_hint_ordering_uses_only_knowable_evidence(tmp_path, evidence):
    combat, _, mid = yard(tmp_path)
    e = combat._load_session(mid).engine
    viewer = e.state.actors[LEFT]
    c = context(e)
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    cell = {'x': 5, 'y': 5}
    start = viewer.position.model_dump(mode='json')
    sequence = e.events[-1].sequence + 1
    payload = {'path': [start, cell, start], 'destination': start}
    if evidence == 'observations_after':
        payload['observations_after'] = {viewer.team_id: {RIGHT: cell}}
    # Planner-only fixture: earlier exploration and a later observation in the
    # same receipt, or a subsequent already-redacted movement hint. No hidden
    # opponent path is supplied to the planner.
    e.events.append(e.events[-1].model_copy(update={'event_type': 'MOVEMENT_COMMITTED',
        'actor_id': LEFT, 'source_definition_id': 'system:combat.movement',
        'sequence': sequence, 'payload': payload}))
    memory = Position(**cell) if evidence == 'observations_after' else Position(x=10, y=5)
    known = [e.state.actors[RIGHT].model_copy(update={'position': memory})]
    recent = () if evidence == 'observations_after' else ({'event_type': 'MOVEMENT_COMMITTED',
        'actor_id': RIGHT, 'sequence': sequence + 1, 'payload': {'destination': cell}},)
    result = ai_search.search_move(e, viewer, c.legal_candidates, policy, known, recent)
    selected = next(row for row in c.legal_candidates if row.candidate_id == result)
    assert selected.destination == Position(**cell)
