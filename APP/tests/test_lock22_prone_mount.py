"""Crawling mounts pay through the table, journal and fresh-service reload."""
from pathlib import Path

import pytest

from combat.ext import mounts
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
R, F = 'actor:factory.l22.rider', 'actor:factory.l22.foe'


def commit(table, mid, label, *, target=None, destination=None):
    state = table.state(mid)
    menu = state['menu']
    if destination is not None:
        cid = next(o['candidate_id'] for o in menu['moves'] if o['destination'] == destination)
    elif label == 'end':
        cid = menu['end_turn']
    else:
        group = next(g for g in menu['actions'] if g['label'] == label)
        cid = next(o['candidate_id'] for o in group['options'] if not target or o['target_ids'] == [target])
    result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result


def setup(tmp_path, *, prone=True, strength=None):
    doc = sheet(['BEASTMASTERY_BASE_RIDER_PACKAGE'], cl=10)
    doc['identity']['display_name'] = 'Rider'
    doc['spheres_and_talents']['automatic_sphere_component_record_ids'] = ['BEASTMASTERY_BASE_RIDER_PACKAGE']
    doc['spheres_and_talents']['learned_talent_record_ids'] = []
    for ability in doc['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == 'DEX':
            ability.update(score=40, modifier=15)
        elif ability['ability'] == 'STR' and strength is not None:
            ability.update(score=strength, modifier=(strength - 10) // 2)
    bundles = [compile_character(doc, actor_id=R), compile_character(sheet([]), actor_id=F)]
    action = ActionDefinition(source_definition_id='action:l22.knock_down', display_name='Knock mount prone',
        owner_id=F, economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=120,
        parameters={'typed': {'source': 'l22.knock_down', 'effects': [
            {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}],
            'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []}})
    bundles[1]['action_catalog'].append(action.model_dump(mode='json'))
    bundles[1]['actor_template']['action_ids'].append(action.source_definition_id)
    svc = CombatService(ROOT, tmp_path)
    table = TabletopService(svc, tmp_path)
    map_id = svc.tabletop_maps.save({'display_name': 'Mounted crawling', 'width_squares': 18,
        'height_squares': 12, 'walls': [], 'starts': {'team1': [[4, 4]], 'team2': [[12, 4]]}})['map_id']
    arena = svc.factory_arenas()['battlefield:map.' + map_id]
    mid = svc._finish_factory_match(bundles, [R, F], {R: 'a', F: 'b'},
        {R: {'x': 4, 'y': 4}, F: {'x': 12, 'y': 4}}, arena, [R], [F],
        control_modes={R: 'MANUAL', F: 'MANUAL'}, match_seed='H83-prone-mount',
        display_name='Mounted crawling', maximum_rounds=5)['match_id']
    while table.state(mid)['menu']['actor_id'] != F:
        commit(table, mid, 'end')
    engine = svc._load_session(mid).engine
    mount = mounts.mount_of(engine, engine.state.actors[R])
    if prone:
        commit(table, mid, 'Knock mount prone', target=mount.entity_id)
    while table.state(mid)['menu']['actor_id'] != R:
        commit(table, mid, 'end')
    return svc, table, mid, mount.entity_id


@pytest.mark.parametrize('prone,expected', [(True, 20), (False, 10)])
def test_table_quotes_charges_and_reloads_mounted_movement(tmp_path, prone, expected):
    svc, table, mid, mount_id = setup(tmp_path, prone=prone)
    engine = svc._load_session(mid).engine
    rider = engine.state.actors[R]
    assert mounts.mount_of(engine, rider).entity_id == mount_id
    before = rider.movement_remaining_ft
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                     and c.destination.x == 6 and c.destination.y == 4)
    assert candidate.movement_cost_ft == expected
    commit(table, mid, 'move', destination={'x': 6, 'y': 4})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    state = loaded.engine.state
    assert before - state.actors[R].movement_remaining_ft == expected
    assert state.actors[mount_id].position == state.actors[R].position
    assert any(c.condition_id == mounts.PRONE for c in state.actors[mount_id].conditions.values()) == prone
    receipt = next(e for e in reversed(loaded.engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == R)
    assert receipt.payload['cost_ft'] == receipt.payload['planned_cost_ft'] == expected
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('prone,jump_extra,knock_down,expected', [
    (True, 0, False, 25), (False, 0, False, 15), (True, 5, False, 30), (False, 0, True, 25)])
def test_table_mixed_jump_quotes_charges_and_reloads_each_segment(tmp_path, monkeypatch, prone, jump_extra, knock_down, expected):
    from combat import ext, flight
    # Mount admission still checks a 2D footprint and vetoes vertical steps.
    # Admit this fixture's jump only, isolating payment from that older geometry
    # limitation without replacing native execution, persistence or other hooks.
    ext.effects()
    def admit_jump(engine, actor, candidate, action):
        if actor.entity_id == R and candidate.metadata.get('movement_mode') == 'jump':
            return None
        return mounts.offered(engine, actor, candidate, action)
    monkeypatch.setitem(ext._HOOKS, 'candidate_allowed',
                        [admit_jump if fn is mounts.offered else fn for fn in ext._HOOKS['candidate_allowed']])
    if jump_extra:
        monkeypatch.setitem(ext._HOOKS, 'movement_step_surcharge', [*ext._HOOKS['movement_step_surcharge'],
            lambda engine, actor, mode: jump_extra if actor.entity_id == R and mode == 'jump' else None])
    if knock_down:
        def trip_mount(engine, mover, previous, nxt, intent):
            mount = mounts.mount_of(engine, mover) if mover.entity_id == R else None
            if mount is not None and not any(c.condition_id == mounts.PRONE for c in mount.conditions.values()):
                engine._apply_condition(mount, mounts.PRONE, 'action:l22.knock_down', F,
                                        expires_on='UNTIL_REMOVED')
        monkeypatch.setitem(ext._HOOKS, 'movement_attempt', [*ext._HOOKS.get('movement_attempt', ()), trip_mount])
    svc, table, mid, _ = setup(tmp_path, prone=prone, strength=20)
    engine = svc._load_session(mid).engine
    rider = engine.state.actors[R]
    before = rider.movement_remaining_ft
    destination = {'x': 6, 'y': 6, 'z': 1}
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                     and c.destination.model_dump(mode='json') == destination)
    assert candidate.metadata['movement_mode'] == 'jump'
    assert [p.z for p in candidate.canonical_path] == [0, 0, 0, 1]
    planned = (25 if prone else 15) + jump_extra
    assert candidate.movement_cost_ft == planned
    costs = [flight.step_cost(engine, rider, a, b, 'jump')
             for a, b in zip(candidate.canonical_path, candidate.canonical_path[1:])]
    commit(table, mid, 'move', destination=destination)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[R].movement_remaining_ft == before - expected
    receipt = next(e for e in reversed(loaded.engine.events) if e.event_type == 'MOVEMENT_COMMITTED'
                   and e.actor_id == R and e.payload.get('movement_mode') == 'jump')
    assert receipt.payload['path'] == [p.model_dump(mode='json') for p in candidate.canonical_path]
    assert receipt.payload['cost_ft'] == expected
    assert receipt.payload['planned_cost_ft'] == planned
    assert receipt.payload['interrupted'] is False
    assert costs == ([10, 10] if prone else [5, 5]) + [5 + jump_extra]
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_jump_quote_includes_difficult_ascent_and_rejects_insufficient_budget():
    from combat import zones
    from combat.gate2_runtime_models import ZoneState
    from tests.h1_support import ME, FOE, duel
    from tests.test_lock10_flight_movement import request
    engine = duel([])
    actor = engine.state.actors[ME]
    actor.strength_score = 24
    destination = actor.position.model_copy(update={'z': 1})
    engine.state.zones['test:jump_terrain'] = ZoneState(
        zone_id='test:jump_terrain', source_definition_id='test:jump_terrain', owner_id=FOE,
        center=destination, radius_cells=0, affected_cells=(destination,),
        concentration_link=False, created_round=1,
        trigger_profile={'kind': zones.KIND, 'shape': 'painted', 'difficult': 'all'})
    for other in engine.state.actors.values():
        other.reaction_available = False
    actor.movement_remaining_ft = 9
    assert not any(c.destination == destination for c in engine.legal_candidates() if c.kind.value == 'MOVE')
    actor.movement_remaining_ft = 10
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination == destination)
    assert candidate.movement_cost_ft == 10
    engine.execute_intent(request(candidate))
    assert actor.movement_remaining_ft == 0
    receipt = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED'
                   and e.actor_id == ME and e.payload.get('movement_mode') == 'jump')
    assert receipt.payload['cost_ft'] == receipt.payload['planned_cost_ft'] == 10


def test_standing_restores_ordinary_cost_without_changing_speed(tmp_path):
    svc, table, mid, mount_id = setup(tmp_path)
    engine = svc._load_session(mid).engine
    assert engine._effective_speed(engine.state.actors[R]) == 60
    commit(table, mid, 'end')
    while table.state(mid)['menu']['actor_id'] != R:
        commit(table, mid, 'end')
    engine = svc._load_session(mid).engine
    assert not any(c.condition_id == mounts.PRONE for c in engine.state.actors[mount_id].conditions.values())
    assert next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination.x == 6 and c.destination.y == 4).movement_cost_ft == 10


def test_granted_crawl_budget_and_difficult_terrain_add(tmp_path):
    from combat import granted_movement
    from combat.gate2_runtime_models import ActionIntent, Position
    svc, _, mid, _ = setup(tmp_path)
    engine = svc._load_session(mid).engine
    rider = engine.state.actors[R]
    # Pure path queries with difficult terrain use the same grid surcharge.
    engine.grid.base_movement_cost[(5, 4)] = 2
    route = (rider.position, Position(x=5, y=4))
    assert granted_movement.path_cost(engine, rider, route) == 15
    intent = ActionIntent(intent_id='query', decision_id='query', candidate_id='query',
                          state_version=engine.state.state_version, actor_id=R)
    options = granted_movement.candidates(engine, rider, 10, intent, 'test:grant')
    assert not any(c.destination == route[-1] for c in options.values())
    options = granted_movement.candidates(engine, rider, 15, intent, 'test:grant')
    assert next(c for c in options.values() if c.destination == route[-1]).movement_cost_ft == 15


def test_reaction_that_knocks_mount_prone_reprices_before_spending(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    svc, table, mid, mount_id = setup(tmp_path, prone=False)
    def knock_down(engine, mover, previous, nxt, intent):
        if mover.entity_id != R:
            return
        mount = engine.state.actors[mount_id]
        if any(c.condition_id == mounts.PRONE for c in mount.conditions.values()):
            return
        engine._apply_condition(mount, mounts.PRONE, 'action:l22.knock_down', F,
                                expires_on='UNTIL_REMOVED')
    install(monkeypatch, 'movement_attempt', knock_down)
    before = svc._load_session(mid).engine.state.actors[R].movement_remaining_ft
    commit(table, mid, 'move', destination={'x': 6, 'y': 4})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert before - loaded.engine.state.actors[R].movement_remaining_ft == 20
    receipt = next(e for e in reversed(loaded.engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == R)
    assert receipt.payload['planned_cost_ft'] == 10 and receipt.payload['cost_ft'] == 20
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('bad', [-1, True, 1.5, '5'])
def test_invalid_cost_provider_is_rejected_without_state_changes(monkeypatch, bad):
    from combat.movement_costs import surcharge
    from tests.test_lock_choices import install
    from tests.test_mounts import fight, rider_bundle, actors
    engine = fight(rider_bundle())
    actor, _, _ = actors(engine)
    before = engine.state.model_dump(mode='json')
    install(monkeypatch, 'movement_step_surcharge', lambda *args: bad)
    with pytest.raises(ValueError, match='nonnegative integer'):
        surcharge(engine, actor)
    assert engine.state.model_dump(mode='json') == before
