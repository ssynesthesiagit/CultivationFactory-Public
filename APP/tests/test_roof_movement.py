"""Native movement regression cases for mixed climbing/walking and roof grips.

These use a real Gate2Engine with its ordinary roster, hooks and authored map.
Only starting fixture statistics/positions change; no movement or check code is
patched. Service/persistence coverage lives in test_walkable_roofs.py.
"""
from pathlib import Path

import pytest

from combat import falling, flight, roof_movement
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionIntent, ConditionInstance, Position
from combat.granted_movement import native_path_cost
from combat.movement_routes import explicit_candidate
from combat.tabletop import normalize_map, to_battlefield


ROOT = Path(__file__).resolve().parents[1]


def engine_at_wall(*, wall_x=4, climb_speed=0, climb_check='none', height_ft=10):
    document = normalize_map({
        'display_name': 'Roof movement regression yard', 'width_squares': 18, 'height_squares': 12,
        'background': {'style': 'wood'},
        'walls': [{'shape': 'rect', 'points': [[wall_x, 3], [wall_x + 5, 8]], 'filled': False}],
        'roofs': {'height_ft': height_ft, 'climb_check': climb_check},
    })
    engine = Gate2Engine(ROOT, match_seed='roof-movement-regressions', battlefield=to_battlefield(document))
    actor = engine.state.actors[engine.state.current_actor_id]
    for index, other in enumerate(engine.state.actors.values()):
        other.position = Position(x=index, y=11)
    actor.position = Position(x=wall_x - 1, y=5)
    actor.speed_ft = actor.movement_remaining_ft = 30
    actor.climb_speed_ft = climb_speed
    actor.fly_speed_ft = 0
    actor.turn_flags = {}
    return engine, actor


def condition(actor, condition_id, *, data=None, expires_on=None, source_actor_id=None):
    row = ConditionInstance(instance_id='test:' + condition_id,
        condition_id=condition_id, source_definition_id='system:combat.roof_test',
        source_actor_id=source_actor_id or actor.entity_id, target_id=actor.entity_id,
        applied_sequence=0, data=data or {}, expires_on=expires_on)
    actor.conditions[row.instance_id] = row
    return row


def test_climb_speed_cannot_fund_an_overlong_walking_approach():
    engine, actor = engine_at_wall(wall_x=10, climb_speed=60)
    actor.position = Position(x=0, y=5)
    path = tuple([Position(x=x, y=5) for x in range(10)] + [Position(x=9, y=5, z=1)])
    with pytest.raises(ValueError, match='walking or climbing'):
        native_path_cost(engine, actor, path, mode='climb')
    assert Position(x=9, y=5, z=1) not in roof_movement.routes(engine, actor)


def test_slow_climb_can_finish_with_faster_supported_roof_walking():
    # The legal route climbs outside the eave to roof height, then steps sideways onto the roof.
    engine, actor = engine_at_wall(climb_speed=20, height_ft=10)
    start = actor.position
    path = (start, Position(x=3, y=5, z=1), Position(x=3, y=5, z=2),
            Position(x=4, y=5, z=2), Position(x=5, y=5, z=2), Position(x=6, y=5, z=2))
    assert native_path_cost(engine, actor, path, mode='climb') == 25
    assert roof_movement.routes(engine, actor)[path[-1]][1] == 25
    assert roof_movement.max_remaining(engine, actor) == 30
    assert roof_movement.step_mode(engine, actor, path[2], path[3]) == 'climb'
    assert roof_movement.step_mode(engine, actor, path[3], path[4]) == 'walk'
    assert explicit_candidate(engine, actor.entity_id, path, 'climb').movement_cost_ft == 25


def test_climbing_after_walking_allowance_is_spent_remains_native_and_restrictable():
    engine, actor = engine_at_wall(climb_speed=60)
    actor.movement_remaining_ft = 0
    assert flight.remaining(engine, actor, 'climb') == 30
    assert flight.budget(engine, actor).available_ft == 30
    assert flight.budget(engine, actor).allowance_ft == 30
    assert not flight.budget(engine, actor).spent
    assert any(candidate.metadata.get('movement_mode') == 'climb'
               for candidate in engine._movement_candidates(actor))
    assert flight.restrict(engine, actor, 10) == 10
    assert flight.remaining(engine, actor, 'climb') == 20
    assert actor.movement_remaining_ft == 0


@pytest.mark.parametrize('condition_id,data,expires_on', [
    ('condition:core.prone', {}, 'STAND_UP'),
    ('condition:typed.prone', {}, 'STAND_UP'),
    ('condition:typed.incapacitated', {'rule': {'no_actions': True}}, None),
    ('condition:typed.roof_climbing_disabled', {'climbing_disabled': True}, None),
    ('condition:typed.roof_speed_zero', {'rule': {'speed_zero': True}}, None),
])
def test_climbing_posture_and_capability_gate_is_shared(condition_id, data, expires_on):
    engine, actor = engine_at_wall()
    condition(actor, condition_id, data=data, expires_on=expires_on)
    path = (actor.position, actor.position.model_copy(update={'z': 1}))
    assert not roof_movement.eligible(engine, actor)
    assert not roof_movement.valid_climb(engine, actor, path)
    assert not roof_movement.step_allowed(engine, actor, *path)
    assert not roof_movement.routes(engine, actor)
    with pytest.raises(ValueError, match='Climbing requires'):
        native_path_cost(engine, actor, path, mode='climb')
    actor.climbing = True
    actor.position = path[-1]
    assert not roof_movement.can_hold(engine, actor)
    assert falling.required(engine, actor)


def test_climbing_costs_include_difficult_terrain_without_a_climb_speed():
    engine, actor = engine_at_wall()
    a, b = actor.position, actor.position.model_copy(update={'z': 1})
    condition(actor, 'condition:typed.sky_net_slow_down')
    assert flight.step_cost(engine, actor, a, b, 'climb') == 15
    actor.climb_speed_ft = 30
    assert flight.step_cost(engine, actor, a, b, 'climb') == 10
    assert flight.step_cost(engine, actor, b, Position(x=3, y=5, z=2), 'climb') == 10


def test_supported_approach_uses_existing_walking_only_surcharge():
    from combat.ext import mounts
    engine, actor = engine_at_wall()
    mount = next(other for other in engine.state.actors.values() if other is not actor)
    mount.summon = {'trained': True}
    condition(actor, mounts.MOUNTED, source_actor_id=mount.entity_id)
    condition(mount, mounts.CARRYING, source_actor_id=actor.entity_id)
    condition(mount, mounts.PRONE, expires_on='STAND_UP')
    a, b = Position(x=2, y=5), actor.position
    assert mounts.mount_of(engine, actor) is mount
    assert flight.step_cost(engine, actor, a, b, 'walk') == 10
    assert flight.step_cost(engine, actor, a, b, 'climb') == 10


def test_difficult_climb_uses_ordinary_check_penalties_and_its_own_provenance():
    from combat.ext.forged_exhaustion import add
    engine, actor = engine_at_wall(climb_check='slippery')
    actor.skills = {'Athletics': 4}
    add(engine, actor, 2, 'system:combat.roof_test')
    before = len(engine.rolls)
    roof_movement.climb_check(engine, actor, actor.position,
                             actor.position.model_copy(update={'z': 1}), None)
    assert len(engine.rolls) == before + 1
    roll = engine.rolls[-1]
    assert roll.modifier == 0  # Athletics +4, two Exhaustion levels -4.
    assert roll.reason == 'CHECK:system:combat.climbing:Athletics'
    event = next(event for event in reversed(engine.events) if event.event_type == 'CHECK_ROLLED')
    assert event.source_definition_id == 'system:combat.climbing'
    assert event.payload['dc'] == 15


def test_only_actual_problematic_climbing_uses_the_check():
    engine, actor = engine_at_wall(climb_check='few_handholds', climb_speed=30)
    ground = actor.position
    first = ground.model_copy(update={'z': 1})
    assert not roof_movement.needs_check(engine, actor, Position(x=2, y=5), ground)
    assert roof_movement.needs_check(engine, actor, ground, first)
    actor.position = first
    actor.climbing = True
    assert roof_movement.needs_check(engine, actor, first, Position(x=3, y=4, z=1))
    condition(actor, 'condition:typed.roof_check_waiver', data={'climb_without_check': True})
    assert not roof_movement.needs_check(engine, actor, first, Position(x=3, y=4, z=1))


def test_climb_routes_offer_equal_cost_approaches_and_honor_the_native_selector():
    # Every equally short climb approach must reach the shared route selector, and
    # the equal-cost alternative it returns must be the bound route -- exactly the
    # seam ordinary ground/fly movement uses. Before the fix the climb search kept a
    # single parent and never consulted the selector at all.
    engine, actor = engine_at_wall(climb_speed=30)
    offered = {}

    def record(start, predecessors, costs, parents):
        offered['start'] = start
        offered['preds'] = {cell: set(rows) for cell, rows in predecessors.items()}
        offered['parents'] = dict(parents)
        return {}

    default = roof_movement.routes(engine, actor, path_selector=record)
    assert default, 'the bounded climb search still returns routes'
    target = next(cell for cell in offered['preds']
                  if len(offered['preds'][cell]) > 1 and cell[3]
                  and Position(x=cell[0], y=cell[1], z=cell[2]) in default)
    legacy = offered['parents'][target]
    alternative = next(row for row in sorted(offered['preds'][target])
                       if row != legacy and row[:3] != legacy[:3])

    def choose(start, predecessors, costs, parents):
        chain, node = [target], alternative
        while node != start:
            chain.append(node)
            node = next(iter(predecessors[node]))
        chain.append(start)
        return {target: tuple(reversed(chain))}

    routed = roof_movement.routes(engine, actor, path_selector=choose)
    path = routed[Position(x=target[0], y=target[1], z=target[2])][0]
    assert (path[-2].x, path[-2].y, path[-2].z) == alternative[:3], (
        "the selector's equal-cost climb approach must be the bound route")
    assert path[-1] == Position(x=target[0], y=target[1], z=target[2])


def test_climb_routes_expose_the_documented_four_field_selector_nodes():
    # The native_route_selection contract names ground/spatial cells (x,y,z); a
    # climbing search adds a trailing has_climbed boolean so two routes to the
    # same cell (one already climbing, one still on the ground) stay distinct.
    # A provider must receive those exact nodes and may echo them back.
    engine, actor = engine_at_wall(climb_speed=30)
    seen = {}

    def record(start, predecessors, costs, parents):
        seen['start'] = start
        seen['nodes'] = set(costs) | set(parents)
        for rows in predecessors.values():
            seen['nodes'] |= set(rows)
        return {}

    assert roof_movement.routes(engine, actor, path_selector=record)
    assert seen['start'][:3] == (3, 5, 0) and seen['start'][3] is False
    assert seen['nodes']
    assert all(len(node) == 4 and isinstance(node[3], bool) for node in seen['nodes']), (
        'climbing selector nodes are documented as (x, y, z, has_climbed)')

    def echo(start, predecessors, costs, parents):
        picked = next(node for node in costs if node[3])
        chain, node = [picked], parents[picked]
        while node != start:
            chain.append(node)
            node = parents[node]
        return {picked: tuple(reversed(chain + [start]))}

    routed = roof_movement.routes(engine, actor, path_selector=echo)
    assert routed, 'a provider echoing the documented nodes still binds a route'


def test_ordinary_climbing_queries_and_checks_do_not_draw_dice_or_mutate_state():
    engine, actor = engine_at_wall()
    before = engine.state.model_dump(mode='json')
    before_events, before_rolls = len(engine.events), len(engine.rolls)
    routes = roof_movement.routes(engine, actor)
    assert routes
    assert roof_movement.climb_check(engine, actor, actor.position,
                                    actor.position.model_copy(update={'z': 1}), None)
    assert engine.state.model_dump(mode='json') == before
    assert len(engine.events) == before_events and len(engine.rolls) == before_rolls


def test_grip_is_saved_and_survives_until_its_face_or_posture_changes():
    from combat.gate2_runtime_models import ActorState
    engine, actor = engine_at_wall()
    actor.position = actor.position.model_copy(update={'z': 1})
    actor.climbing = True
    saved = actor.model_dump(mode='json')
    recovered = ActorState.model_validate(saved)
    assert recovered.climbing and recovered.position == actor.position
    assert roof_movement.can_hold(engine, recovered)
    assert not falling.required(engine, recovered)
    recovered.climbing = False
    assert 'climbing' not in recovered.model_dump(mode='json')
    assert 'climb_speed_ft' not in recovered.model_dump(mode='json')
    assert falling.required(engine, recovered)


SPIDER = 'TAL_ATHLETICS_SPIDER_S_TOUCH'
SURE_GRIP = 'TAL_ATHLETICS_SURE_GRIP'
MIGHTY = 'TAL_ATHLETICS_MIGHTY_CONDITIONING'


def owned_climber(talents):
    """A source-compiled Factory owner; a recorded manual choice belongs to it."""
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_content import AN
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import sheet
    me = 'actor:factory.roof_athletics'
    document = sheet(talents, cl=11)
    stats = document['ability_scores_and_statistics']
    for ability in stats['abilities']:
        if ability['ability'] in {'STR', 'DEX'}:
            ability['score'] = 8 if ability['ability'] == 'STR' else 18
            ability['modifier'] = (ability['score'] - 10) // 2
    stats['skills'] = [{'skill': 'Athletics', 'bonus': 3, 'proficiency_multiplier': 1}]
    bundle = compile_character(document, actor_id=me)
    arena = to_battlefield(normalize_map({
        'display_name': 'Owned climbing abilities yard', 'width_squares': 12, 'height_squares': 12,
        'background': {'style': 'wood'},
        'walls': [{'shape': 'rect', 'points': [[4, 3], [9, 8]], 'filled': False}],
        'roofs': {'height_ft': 10, 'climb_check': 'slippery'},
    }))
    engine = Gate4ControllerEngine(ROOT, match_seed='roof-owned-abilities', typed_bundles=(bundle,),
        battlefield=arena, roster_setup={'primary_actor_ids': [me, AN],
            'team_by_actor': {me: 'team:a', AN: 'team:b'},
            'starting_positions': {me: {'x': 3, 'y': 5}, AN: {'x': 0, 'y': 11}}})
    engine.state.current_actor_id = me
    engine.state.current_slot_index = engine.state.initiative_order.index(me)
    engine._system_start_turn()
    engine.typed_control_modes = {me: 'MANUAL', AN: 'LOCAL_AUTO'}
    return engine, engine.state.actors[me]


def climb_intent(engine, actor):
    path = (actor.position, actor.position.model_copy(update={'z': actor.position.z + 1}))
    candidate = explicit_candidate(engine, actor.entity_id, path, 'climb')
    return ActionIntent(intent_id='roof-owned-climb', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=actor.entity_id, destination=candidate.destination,
        movement_path=path, movement_mode='climb')


def test_owned_spiders_touch_grants_climb_speed_and_sure_grip_grants_advantage():
    from combat.ext.athletics import rows_of
    from combat.ext.athletics_grip_lungs import owns as owns_grip
    engine, actor = owned_climber([SPIDER, SURE_GRIP])
    capability = roof_movement.profile(engine, actor)
    assert 'spider_touch' in rows_of(engine, actor)
    assert owns_grip(engine, actor, 'sure_grip')
    assert actor.climb_speed_ft == 0 and capability.speed_ft == engine._effective_speed(actor) == 30
    assert capability.check_modes == ('ADVANTAGE',)
    assert not capability.without_check
    intent = climb_intent(engine, actor)
    assert native_path_cost(engine, actor, intent.movement_path, mode='climb') == 5
    engine.execute_intent(intent)
    check = next(event for event in reversed(engine.events) if event.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'ADVANTAGE'
    assert check.payload['actor']['modifier'] == 3
    assert check.payload['ability'] == 'STR'


def test_owned_sure_grip_advantage_cancels_existing_disadvantage():
    engine, actor = owned_climber([SURE_GRIP])
    condition(actor, 'condition:typed.roof_check_disadvantage',
              data={'rule': {'check_mode': {'Athletics': 'DISADVANTAGE'}}})
    engine.execute_intent(climb_intent(engine, actor))
    check = next(event for event in reversed(engine.events) if event.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'NORMAL'


@pytest.mark.parametrize('selected,bonus', [('STR', 3), ('DEX', 8)])
def test_owned_mighty_conditioning_records_the_players_choice_even_for_lower_modifier(selected, bonus):
    from combat.gate2_runtime_models import ReactionDecision
    engine, actor = owned_climber([MIGHTY])
    requested = []
    def choose(request):
        requested.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(selected,)), None
    engine.set_reaction_provider(choose)
    assert roof_movement.profile(engine, actor).check_abilities == ('STR', 'DEX')
    engine.execute_intent(climb_intent(engine, actor))
    choice = next(request for request in requested
                  if request['reaction_source_id'] == 'choice:needle.climbing.ability')
    assert set(choice['legal_option_ids']) == {'STR', 'DEX'}
    assert choice['extension_choice']['automatic_use'] is False
    check = next(event for event in reversed(engine.events) if event.event_type == 'CHECK_ROLLED')
    assert check.payload['ability'] == selected and check.payload['actor']['modifier'] == bonus


def test_owned_mighty_conditioning_never_guesses_for_an_unanswered_manual_owner():
    engine, actor = owned_climber([MIGHTY])
    destination = actor.position.model_copy(update={'z': 1})
    before = engine.state.model_dump(mode='json')
    count = len(engine.rolls)
    with pytest.raises(ValueError, match='recorded movement intent'):
        roof_movement.climb_check(engine, actor, actor.position, destination, None)
    with pytest.raises(ValueError, match='Choose the ability'):
        roof_movement.climb_check(engine, actor, actor.position, destination, climb_intent(engine, actor))
    assert engine.state.model_dump(mode='json') == before and len(engine.rolls) == count


def test_mighty_climb_choice_pauses_resumes_and_replays_through_real_table_service(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_walkable_roofs import OWNER, cold, roof_fight
    combat, table, mid = roof_fight(tmp_path, owner_talents=(MIGHTY,), owner_start=(3, 2),
                                  climb_check='slippery')
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    intent = climb_intent(engine, actor)
    request = {'candidate_id': intent.candidate_id, 'decision_id': intent.decision_id,
               'state_version': intent.state_version, 'actor_id': OWNER,
               'waypoints': [position.model_dump(mode='json') for position in intent.movement_path],
               'movement_mode': 'climb'}
    before = engine.state.model_dump(mode='json')
    result = table.commit_move_path(mid, **request)
    assert result['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.climbing.ability'
    assert {option['id'] for option in prompt['choice']['options']} == {'STR', 'DEX'}
    # The question names the owning ability, the action and the climber it applies to
    # (change standard 9); it must not read as an unattributed "Climbing ability".
    assert prompt['reaction'] == 'Mighty Conditioning'
    assert prompt['action'] == 'Climbing check'
    assert prompt['affected'] == actor.display_name
    assert 'Mighty Conditioning' in prompt['moment'] and actor.display_name in prompt['moment']
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['DEX']}
    fresh = CombatService(ROOT, tmp_path)
    reopened = TabletopService(fresh, tmp_path)
    result = reopened.commit_move_path(mid, **request, reactions=[answer])
    assert result['status'] == 'COMMITTED' and 'divergence_diagnostic' not in result
    _, _, recovered = cold(fresh, tmp_path, mid)
    check = next(event for event in reversed(recovered.engine.events) if event.event_type == 'CHECK_ROLLED')
    assert check.payload['ability'] == 'DEX'


def test_climbing_picks_the_safer_equal_cost_route_through_the_real_table_service(tmp_path):
    # The player's real path: a native MOVE candidate from CombatService, committed
    # by the table and reloaded cold. Spider's Touch climbing speed makes both
    # approaches to the wall grip cost the same five feet per step:
    #   walk on the ground to (3,1) then climb   -- steps onto a glowing qi hazard
    #   climb straight up at (3,2) then move     -- stays clear of the hazard
    # The shared safer-route policy must bind the hazard-free equal-cost approach.
    from tests.test_walkable_roofs import OWNER, cold, perform, roof_fight
    combat, table, mid = roof_fight(tmp_path, owner_talents=(SPIDER,), owner_start=(3, 2),
                                    hazards=[(3, 1)])
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=2)
    assert roof_movement.profile(engine, actor).speed_ft == engine._effective_speed(actor) == 30
    destination = Position(x=3, y=1, z=1)
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == "MOVE" and c.destination == destination)
    assert candidate.movement_cost_ft == 10
    assert candidate.metadata["hazard_exposure"] is False, "the bound route must avoid the qi hazard"
    assert (3, 1, 0) not in {(p.x, p.y, p.z) for p in candidate.canonical_path}
    perform(combat, mid, lambda c: c.kind == "MOVE" and c.destination == destination)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == destination and actor.climbing
    assert actor.current_hp == actor.maximum_hp, "the safer route never entered the qi hazard"
    event = next(e for e in reversed(session.engine.events)
                 if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER)
    ground = {(row["x"], row["y"]) for row in event.payload["path"] if row.get("z", 0) == 0}
    assert (3, 1) not in ground, "the committed move must not walk through the hazard square"
