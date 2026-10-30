"""Native route tie selection and real table route preview/commit/replay."""
import pytest
from combat import ext, movement_routes
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopError
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_lock2_persistence import table_match
from tests.test_lock10_flight_movement import grant


def p(x, y, z=0):
    return Position(x=x, y=y, z=z)


def repro():
    e = duel([])
    e.state.actors[FOE].position = p(3, 4)
    return e


def move(e, destination):
    return next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == destination)


def intent(c, explicit=False):
    return ActionIntent(intent_id='test:route', decision_id=c.decision_id, state_version=c.state_version,
        candidate_id=c.candidate_id, actor_id=c.actor_id, destination=c.destination,
        movement_path=c.canonical_path if explicit else None,
        movement_mode=c.metadata.get('movement_mode', 'walk') if explicit else None)


def test_oa_avoiding_native_tie_and_default_inert_seam(monkeypatch):
    e = repro()
    before = e.state.model_dump(mode='json')
    c = move(e, p(1, 5))
    assert c.canonical_path == (p(3, 6), p(2, 6), p(1, 5))
    assert c.movement_cost_ft == 10
    assert c.metadata['expected_opportunity_attack_count'] == 0
    assert e.state.model_dump(mode='json') == before
    monkeypatch.setitem(ext._HOOKS, 'native_route_selection', [])
    old = move(e, p(1, 5))
    assert old.canonical_path == (p(3, 6), p(2, 5), p(1, 5))
    assert old.metadata['expected_opportunity_attack_count'] == 1


def test_all_provoking_routes_keep_destination_and_report_threat():
    e = repro()
    e.state.actors[FOE].position = p(3, 5)
    c = move(e, p(1, 6))
    assert c.movement_cost_ft == 10
    assert c.metadata['expected_opportunity_attack_count'] == 1
    assert c.metadata['expected_opportunity_attacks'][0]['actor_id'] == FOE


def test_hazard_avoiding_equal_cost_route():
    e = repro()
    e.state.actors[FOE].position = p(9, 4)
    e.grid.qi_hazard.add((2, 5))
    c = move(e, p(1, 5))
    assert p(2, 5) not in c.canonical_path
    assert c.movement_cost_ft == 10 and not c.metadata['hazard_exposure']


def test_custom_route_identity_exact_execution_and_invalid_steps():
    e = repro()
    a = movement_routes.explicit_candidate(e, ME, (p(3, 6), p(2, 6), p(1, 5)))
    b = movement_routes.explicit_candidate(e, ME, (p(3, 6), p(2, 5), p(1, 5)))
    assert a.candidate_id != b.candidate_id != move(e, p(1, 5)).candidate_id
    before = e.state.model_dump(mode='json')
    for path in ((p(3, 6), p(1, 5)), (p(2, 6), p(1, 5)), (p(3, 6), p(3, 6))):
        with pytest.raises(ValueError):
            movement_routes.explicit_candidate(e, ME, path)
    e.grid.blocked.add((2, 6))
    e._wall_base = None
    with pytest.raises(ValueError):
        e.execute_intent(intent(a, True))
    assert e.state.model_dump(mode='json') == before
    e.grid.blocked.remove((2, 6))
    e._wall_base = None
    e.execute_intent(intent(a, True))
    event = next(ev for ev in reversed(e.events) if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == ME)
    assert event.payload['path'] == [v.model_dump(mode='json') for v in a.canonical_path]


def test_explicit_terrain_cost_and_budget():
    e = repro()
    e.grid.base_movement_cost[(2, 6)] = 2
    e._wall_base = None
    c = movement_routes.explicit_candidate(e, ME, (p(3, 6), p(2, 6), p(1, 5)))
    assert c.movement_cost_ft == 15
    e.state.actors[ME].movement_remaining_ft = 10
    with pytest.raises(ValueError, match='difficult terrain'):
        movement_routes.explicit_candidate(e, ME, c.canonical_path)


def test_explicit_flight_altitude_and_grounding():
    e = repro()
    route = (p(3, 6), p(3, 6, 1), p(3, 6, 2))
    with pytest.raises(ValueError):
        movement_routes.explicit_candidate(e, ME, route, 'fly')
    grant(e, e.state.actors[ME])
    c = movement_routes.explicit_candidate(e, ME, route, 'fly')
    assert c.movement_cost_ft == 10
    e.execute_intent(intent(c, True))
    assert e.state.actors[ME].position == route[-1]
    e.state.actors[ME].conditions.clear()
    grant(e, e.state.actors[ME], cannot_gain_altitude=1)
    with pytest.raises(ValueError):
        movement_routes.explicit_candidate(e, ME, (route[-1], p(3, 6, 3)), 'fly')


@pytest.mark.parametrize('point,steps,cost', [('movement_attempt', 0, 0), ('movement_step', 1, 5)])
def test_custom_route_keeps_native_step_checkpoints_and_forced_stops(monkeypatch, point, steps, cost):
    e = repro()
    path = (p(3, 6), p(2, 6), p(1, 5))
    c = movement_routes.explicit_candidate(e, ME, path)
    monkeypatch.setitem(ext._HOOKS, point, [lambda *a: {'stop': True, 'source_id': 'test:stop', 'label': 'Movement stops here.'}])
    e.execute_intent(intent(c, True))
    event = next(ev for ev in reversed(e.events) if ev.event_type == 'MOVEMENT_COMMITTED')
    assert event.payload['interrupted'] and event.payload['cost_ft'] == cost
    assert e.state.actors[ME].position == path[steps]


def test_shared_oa_query_projects_position_and_preserves_free_steps():
    e = repro()
    mover = e.state.actors[ME]
    before = e.state.model_dump(mode='json')
    assert e.opportunity_eligible(mover, p(2, 5), p(1, 5)) == (FOE,)
    assert e.opportunity_eligible(mover, p(2, 6), p(1, 5)) == ()
    assert e.opportunity_eligible(mover, p(2, 5), p(1, 5), ignore_oa_from=(FOE,)) == ()
    mover.turn_flags['oa_free_ft'] = 5
    assert movement_routes.expected_attacks(e, mover, (p(3, 6), p(2, 5), p(1, 5))) == [FOE]
    mover.turn_flags['oa_free_ft'] = 10
    assert movement_routes.expected_attacks(e, mover, (p(3, 6), p(2, 5), p(1, 5))) == []
    del mover.turn_flags['oa_free_ft']
    assert e.state.model_dump(mode='json') == before


def test_custom_route_rechecks_occupancy_and_binding_before_commit(tmp_path):
    combat, table, mid = table_match(tmp_path)
    state, menu, path = table_route(table, mid)
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], menu['actor_id'], path)
    changed = [path[0], path[1], {**path[-1], 'y': path[-1]['y'] + 1}]
    with pytest.raises(TabletopError):
        table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'], menu['state_version'],
                               menu['actor_id'], changed, state['last_sequence'])
    with pytest.raises(TabletopError, match='current space'):
        table.preview_move_path(mid, menu['decision_id'], menu['state_version'], menu['actor_id'], list(reversed(path)))
    with pytest.raises(TabletopError, match='whole-number grid squares'):
        table.preview_move_path(mid, menu['decision_id'], menu['state_version'], menu['actor_id'],
                                [path[0], {**path[1], 'x': float(path[1]['x'])}, path[2]])
    engine = combat._load_session(mid).engine
    other = next(a for a in engine.state.actors.values() if a.entity_id != menu['actor_id'])
    with pytest.raises(ValueError, match='free legal space'):
        movement_routes.explicit_candidate(engine, menu['actor_id'], (Position.model_validate(path[0]), other.position))


def test_custom_route_ask_me_pause_continues_after_reload(tmp_path):
    from tests.test_tabletop_hunt6 import table_fight, RIGHT, LEFT
    from tests.test_lock2_persistence import act
    combat, table, mid = table_fight(tmp_path, [], ask=True)
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state, menu, path = table_route(table, mid)
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], RIGHT, path)
    before = canonical_state_sha256(combat._load_session(mid).engine.state)
    def send(current, answers=()):
        return current.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
            menu['state_version'], RIGHT, path, state['last_sequence'], reactions=list(answers))
    paused = send(table)
    assert paused['status'] == 'REACTION_REQUIRED'
    assert paused['reaction']['context']['reactor_id'] == LEFT
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == before
    from combat.tabletop_service import TabletopService
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    result = send(reopened, [{**paused['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}])
    assert result['status'] == 'COMMITTED'
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'


def table_route(table, mid):
    state = table.state(mid)
    menu = state['menu']
    actor = table.combat._load_session(mid).engine.state.actors[menu['actor_id']]
    # Retreat straight away from the neighbouring enemy, then turn.
    direction = -1 if actor.position.x == 3 else 1
    path = [actor.position, actor.position.model_copy(update={'x': actor.position.x + direction}),
            actor.position.model_copy(update={'x': actor.position.x + 2 * direction, 'y': actor.position.y + 1})]
    return state, menu, [v.model_dump(mode='json') for v in path]


def query_snapshot(engine):
    return (engine.state.model_dump(mode='json'),
            [e.model_dump(mode='json') for e in engine.events],
            [r.model_dump(mode='json') for r in engine.rolls])


def observe_table_queries(monkeypatch, combat, before_query=None):
    """Capture the actual sessions each query loads, before it uses their engines."""
    loaded = []
    original = combat._load_session
    def load(*args, **kwargs):
        session = original(*args, **kwargs)
        loaded.append((session.engine, query_snapshot(session.engine)))
        if before_query is not None:
            before_query()
        return session
    monkeypatch.setattr(combat, '_load_session', load)
    return loaded


def assert_queries_unchanged(loaded):
    assert loaded, 'The table query must use the captured loader.'
    for engine, before in loaded:
        assert query_snapshot(engine) == before, 'query engine changed'


def test_table_route_quote_commit_reload_and_replay(tmp_path):
    combat, table, mid = table_match(tmp_path)
    state, menu, path = table_route(table, mid)
    before = canonical_state_sha256(combat._load_session(mid).engine.state)
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], menu['actor_id'], path)
    c = quote['candidate']
    assert quote['authoritative_state_unchanged']
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == before
    send = lambda answers: table.commit_move_path(mid, c['candidate_id'], menu['decision_id'], menu['state_version'],
        menu['actor_id'], path, state['last_sequence'], reactions=answers)
    result = send([])
    while result['status'] == 'REACTION_REQUIRED':
        result = send([{**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[menu['actor_id']].position == Position.model_validate(path[-1])
    assert loaded.mechanical.replay()['status'] == 'PASS'
    with pytest.raises(TabletopError, match='moved on'):
        table.preview_move_path(mid, menu['decision_id'], menu['state_version'], menu['actor_id'], path)
    records, _ = loaded.store.scan_journal(recover_trailing_partial=False)
    assert next(r for r in records if r['record_type'] == 'PREPARE')['intent']['movement_path'] == path


def test_prior_destination_only_move_replays_its_recorded_route(monkeypatch, tmp_path):
    ext._load()
    providers = ext._HOOKS['native_route_selection']
    monkeypatch.setitem(ext._HOOKS, 'native_route_selection', [])
    original_metadata = movement_routes.threat_metadata
    monkeypatch.setattr(movement_routes, 'threat_metadata', lambda *a, **kw: {})
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[menu['actor_id']]
    c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination.y == actor.position.y + 1
             and abs(c.destination.x - actor.position.x) == 2)
    result = table.act(mid, c.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    monkeypatch.setitem(ext._HOOKS, 'native_route_selection', providers)
    monkeypatch.setattr(movement_routes, 'threat_metadata', original_metadata)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    records, _ = loaded.store.scan_journal(recover_trailing_partial=False)
    assert all('movement_path' not in r['intent'] for r in records if r['record_type'] == 'PREPARE')
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_waypoint_request_models_and_endpoint_source_contract():
    from app.models import TabletopRoutePreviewRequest, TabletopRouteCommitRequest
    request = TabletopRoutePreviewRequest(decision_id='d', state_version=1, actor_id='a',
                                         waypoints=[{'x': 0, 'y': 0}, {'x': 1, 'y': 0}])
    assert TabletopRouteCommitRequest(**request.model_dump(), candidate_id='c').movement_mode == 'walk'
    with pytest.raises(ValueError):
        TabletopRoutePreviewRequest(decision_id='d', state_version=1, actor_id='a',
                                   waypoints=[{'x': 0, 'y': 0}, {'x': 1.0, 'y': 0}])
    source = (ROOT / 'app/api.py').read_text()
    assert '/movement-path/preview' in source and '/movement-path/commit' in source


@pytest.mark.parametrize('selection', ['USE', 'DECLINE'])
def test_guiding_star_table_queries_observe_and_execution_asks(monkeypatch, tmp_path, selection):
    from tests import test_tabletop_hunt6 as fixture
    from tests.test_tabletop_hunt6 import table_fight, LEFT
    from combat.ext.fate_riders import AUSPICE, GUIDING_FREE
    original_sheet = fixture.sheet
    def auspice_only(*args, **kwargs):
        document = original_sheet(*args, **kwargs)
        if 'spheres_and_talents' in document:
            # Isolate this talent from the Fate base's automatic defensive reactions.
            document['spheres_and_talents']['automatic_sphere_component_record_ids'] = []
        return document
    monkeypatch.setattr(fixture, 'sheet', auspice_only)
    combat, table, mid = table_fight(tmp_path, ['TAL_FATE_GUIDING_STAR_AUSPICE'])
    state = table.state(mid)
    menu = state['menu']
    engine = combat._load_session(mid).engine
    group = next(g for g in menu['actions'] if 'Guiding Star Auspice' in
                 getattr(engine.action_catalog.get(g['source_definition_id']), 'display_name', ''))
    cid = next(o['candidate_id'] for o in group['options'] if o['target_ids'] == [LEFT])
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == AUSPICE for c in engine.state.actors[LEFT].conditions.values())
    assert engine.state.actors[LEFT].concentration is not None
    before = engine.state.model_dump(mode='json')
    queried = observe_table_queries(monkeypatch, combat)
    state, menu, path = table_route(table, mid)
    assert_queries_unchanged(queried)
    queried.clear()
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], LEFT, path)
    assert_queries_unchanged(queried)
    assert quote['candidate']['metadata']['expected_opportunity_attack_count'] == 1
    def send(answers):
        return table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
            menu['state_version'], LEFT, path, state['last_sequence'], reactions=answers)
    paused = send([])
    assert paused['status'] == 'REACTION_REQUIRED'
    assert 'Guiding Star' in str(paused['reaction']) and 'Opportunity Attack' in str(paused['reaction'])
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == canonical_state_sha256(engine.state)
    answers = [{**paused['reaction']['context'], 'selection': selection,
                'option_ids': ['release'] if selection == 'USE' else []}]
    result = send(answers)
    while result['status'] == 'REACTION_REQUIRED':
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
        result = send(answers)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert any(c.condition_id == GUIDING_FREE for c in actor.conditions.values()) == (selection == 'USE')
    assert any(c.condition_id == AUSPICE for c in actor.conditions.values()) == (selection == 'DECLINE')
    if selection == 'DECLINE':
        assert actor.concentration.model_dump(mode='json') == before['actors'][LEFT]['concentration']
    assert actor.reaction_available == (selection == 'DECLINE')
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_guiding_star_purity_detects_effectful_query_subscriber(monkeypatch, tmp_path):
    from combat.ext.fate_riders import guiding_star, guiding_star_protection
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'opportunity_allowed', [
        guiding_star if provider is guiding_star_protection else provider
        for provider in ext._HOOKS['opportunity_allowed']])
    with pytest.raises(AssertionError, match='query engine changed'):
        test_guiding_star_table_queries_observe_and_execution_asks(monkeypatch, tmp_path, 'USE')


@pytest.mark.parametrize('selection,failed_save', [('USE', True), ('USE', False), ('DECLINE', True)])
def test_unrecorded_movement_table_queries_and_execution(monkeypatch, tmp_path, selection, failed_save, before_query=None):
    from tests import test_tabletop_hunt6 as fixture
    from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
    from combat.ext.unwritten_footprint import DOMAIN, UNNOTICING
    from combat.tabletop_service import TabletopService
    original_sheet = fixture.sheet
    def domain_sheet(*args, **kwargs):
        return original_sheet(*args, **kwargs, dc=40 if failed_save else -40)
    monkeypatch.setattr(fixture, 'sheet', domain_sheet)
    combat, table, mid = table_fight(tmp_path, [DOMAIN], cl=18, primary='Resonance', ally_talents=[])
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    group = next(g for g in state['menu']['actions'] if
                 engine.action_catalog[g['source_definition_id']].display_name == 'Concept of the Missing Footstep')
    assert table.act(mid, group['options'][0]['candidate_id'], state['menu']['decision_id'],
                     state['menu']['state_version'], state['last_sequence'])['status'] == 'COMMITTED'
    queried = observe_table_queries(monkeypatch, combat, before_query)
    table.state(mid)
    assert_queries_unchanged(queried)
    queried.clear()
    state, menu, path = table_route(table, mid)
    assert_queries_unchanged(queried)
    queried.clear()
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], LEFT, path)
    assert_queries_unchanged(queried)
    assert quote['candidate']['metadata']['expected_opportunity_attack_count'] == 1
    before = query_snapshot(combat._load_session(mid).engine)
    def send(current, answers):
        return current.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
            menu['state_version'], LEFT, path, state['last_sequence'], reactions=answers)
    paused = send(table, [])
    assert paused['status'] == 'REACTION_REQUIRED'
    assert 'Unrecorded Movement' in str(paused['reaction'])
    assert 'Right' in str(paused['reaction']) and 'moves' in str(paused['reaction'])
    assert query_snapshot(combat._load_session(mid).engine) == before
    answers = [{**paused['reaction']['context'], 'selection': selection,
                'option_ids': ['choose'] if selection == 'USE' else []}]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    result = send(reopened, answers)
    while result['status'] == 'REACTION_REQUIRED':
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
        result = send(reopened, answers)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner, witness = loaded.engine.state.actors[LEFT], loaded.engine.state.actors[RIGHT]
    assert owner.turn_flags[f'unrecorded:{RIGHT}'] == ('chosen' if selection == 'USE' else 'declined')
    assert any(c.condition_id == UNNOTICING and c.source_actor_id == LEFT
               for c in witness.conditions.values()) == (selection == 'USE' and failed_save)
    assert witness.reaction_available == (selection == 'USE')
    records, _ = loaded.store.scan_journal(recover_trailing_partial=False)
    movement = [r for r in records if r['record_type'] == 'COMMIT'][-1]
    assert any(e['event_type'] == 'ATTACK_ROLLED' for e in movement['events']) == (selection == 'DECLINE')
    if selection == 'USE':
        assert len(loaded.engine.rolls) - len(before[2]) == 1  # One witness save, despite multiple steps.
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_unrecorded_purity_detects_effectful_query_subscriber(monkeypatch, tmp_path):
    from combat.ext.unwritten_footprint import unwritten_no_opportunity, _unrecorded_opportunity
    ext._load()
    def restore_effectful_subscriber():
        # Restore it after loading: otherwise it also corrupts recovery before
        # the table can query its engine, hiding the query-specific failure.
        monkeypatch.setitem(ext._HOOKS, 'opportunity_allowed', [
            _unrecorded_opportunity if provider is unwritten_no_opportunity else provider
            for provider in ext._HOOKS['opportunity_allowed']])
    with pytest.raises(AssertionError, match='query engine changed'):
        test_unrecorded_movement_table_queries_and_execution(monkeypatch, tmp_path, 'USE', True,
                                                           restore_effectful_subscriber)


@pytest.mark.parametrize('explicit', [True, False])
def test_jump_table_commit_reload_and_prior_destination_only_replay(monkeypatch, tmp_path, explicit):
    ext._load()
    # Persist the synthetic Strength in genesis rather than mutating a loaded save.
    def strong(engine):
        for actor in engine.state.actors.values():
            actor.strength_score = 30
    monkeypatch.setitem(ext._HOOKS, 'match_start', [*ext._HOOKS.get('match_start', []), strong])
    original_metadata = movement_routes.threat_metadata
    if not explicit:
        monkeypatch.setattr(movement_routes, 'threat_metadata', lambda *a, **kw: {})
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[menu['actor_id']]
    route = (actor.position, actor.position.model_copy(update={'z': 1}))
    path = [v.model_dump(mode='json') for v in route]
    if explicit:
        quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], actor.entity_id, path, 'jump')
        candidate = quote['candidate']
        send = lambda answers: table.commit_move_path(mid, candidate['candidate_id'], menu['decision_id'],
            menu['state_version'], actor.entity_id, path, state['last_sequence'], 'jump', answers)
    else:
        c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == route[-1]
                 and c.metadata['movement_mode'] == 'jump')
        send = lambda answers: table.act(mid, c.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    answers = []
    result = send(answers)
    while result['status'] == 'REACTION_REQUIRED':
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
        result = send(answers)
    assert result['status'] == 'COMMITTED'
    monkeypatch.setattr(movement_routes, 'threat_metadata', original_metadata)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    event = next(e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED')
    assert event.payload['path'] == path and event.payload['cost_ft'] == 5
    records, _ = loaded.store.scan_journal(recover_trailing_partial=False)
    assert all(('movement_path' in r['intent']) == explicit for r in records if r['record_type'] == 'PREPARE')
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_jump_limits_posture_and_granted_movement_stay_restricted():
    from combat.granted_movement import path_cost
    e = repro()
    actor = e.state.actors[ME]
    actor.strength_score = 30
    route = (actor.position, actor.position.model_copy(update={'z': 1}))
    assert movement_routes.explicit_candidate(e, ME, route, 'jump').movement_cost_ft == 5
    with pytest.raises(ValueError, match='walking or flying'):
        path_cost(e, actor, route, mode='jump')
    for invalid in (None, (), ({'x': 0, 'y': 0},)):
        with pytest.raises(ValueError, match='current space'):
            path_cost(e, actor, invalid)
    with pytest.raises(ValueError, match='jump height'):
        movement_routes.explicit_candidate(e, ME, (*route, route[-1].model_copy(update={'z': 2})), 'jump')
    e._apply_condition(actor, 'condition:typed.prone', 'test:prone', ME, expires_on='END_OF_CURRENT_TURN')
    with pytest.raises(ValueError, match='prevents jumping'):
        movement_routes.explicit_candidate(e, ME, route, 'jump')
    assert not any(c.kind == 'MOVE' and c.metadata.get('movement_mode') == 'jump' for c in e.legal_candidates())


def test_shared_typed_opportunity_selector_only_executes_response_when_asking(monkeypatch):
    from combat import typed_reactions
    from tests.test_riders_lane9 import _fate_fight, ME as CASTER, THEM
    e = _fate_fight(['GUIDING_STAR_AUSPICE'], ally_at=None)
    seen = []
    def response(engine, reactor, mover):
        seen.append((reactor.entity_id, mover.entity_id))
        return False
    monkeypatch.setitem(ext._HOOKS, 'opportunity_response', [response])
    reactor, mover = e.state.actors[THEM], e.state.actors[CASTER]
    assert typed_reactions.wants_opportunity_attack(e, reactor, mover, ask=False)
    assert seen == []
    assert not typed_reactions.wants_opportunity_attack(e, reactor, mover)
    assert seen == [(THEM, CASTER)]
