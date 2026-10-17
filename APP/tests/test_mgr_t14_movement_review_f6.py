"""F6 native commit/reload guards for Speed modes, drag prices and Earth allies."""
import pytest

from combat import flight, granted_movement
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield
from combat.typed_executor import bears_mark
from tests.cw2_service_support import seal
from tests.h1_support import sheet
from tests.test_mgr_t14_committed_movement import EARTH, CLOD, native_burden
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, turn, settle, candidate, reload, sealed_native_attack,
)


@pytest.mark.parametrize('selected,speed', [('fly', 20), ('walk', 30)])
def test_anchor_selected_speed_preserves_independent_flight_after_reload(tmp_path, selected, speed):
    def wings(bundles):
        bundles[2]['actor_template'].update(speed_ft=10, fly_speed_ft=30, hover=True)
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [EARTH, CLOD], cl=6,
        bundle_transform=wings, foe_position={'x': 3, 'y': 5})
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    move = next(c for c in before.legal_candidates() if c.kind == 'MOVE'
                and c.destination == Position(x=3, y=4, z=1)
                and c.metadata.get('movement_mode') == 'fly')
    settle(table, mid, move.candidate_id, picks={
        'choice:needle.earth_response': 'anchor', 'choice:needle.anchor_speed': selected})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[FOE]
    assert actor.position == move.destination
    assert flight.profile(engine, actor).speed_ft == speed
    assert engine._effective_speed(actor) == (10 if selected == 'fly' else 0)
    assert flight.remaining(engine, actor, 'fly') == speed - 5
    assert flight.budget(engine, actor).available_ft == speed - 5
    assert not bears_mark(actor, OWNER, 'Burden Mark')
    assert any(mode == 'fly' for _, _, mode in granted_movement.routes(engine, actor, 5).values())
    follow = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                  and c.destination == Position(x=3, y=3, z=1)
                  and c.metadata.get('movement_mode') == 'fly')
    settle(table, mid, follow.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position == follow.destination
    assert flight.remaining(engine, engine.state.actors[FOE], 'fly') == speed - 10


def test_mode_reduction_does_not_override_global_immobilization():
    from tests.test_roof_movement import engine_at_wall, condition
    engine, actor = engine_at_wall()
    actor.fly_speed_ft = 30
    condition(actor, 'condition:typed.review_slow', data={'movement_speed_reductions': {'walk': 30}})
    condition(actor, 'condition:typed.review_pinned', data={'rule': {'speed_zero': True}})
    assert flight.profile(engine, actor).speed_ft == 0
    assert flight.budget(engine, actor).available_ft == 0
    assert granted_movement.routes(engine, actor, 5) == {}


@pytest.mark.parametrize('walking,spatial', [(15, False), (20, False), (15, True)])
def test_dragging_difficult_step_quote_matches_commit_and_reload(tmp_path, walking, spatial):
    owner = compile_character(sheet([], cl=18, key='STR', score=30), actor_id=OWNER,
                              reaction_plan={'ask': True})
    owner['actor_template'].update(speed_ft=walking)
    seal(owner)
    arena = to_battlefield(normalize_map({
        'display_name': 'Drag price yard', 'width_squares': 16, 'height_squares': 12,
        'materials': [{'material': 'terrain:bamboo thicket',
                       'cells': [[x, 7] for x in range(16)]}],
        **({'walls': [{'shape': 'rect', 'points': [[10, 2], [13, 4]], 'filled': False}],
            'roofs': {'height_ft': 10, 'climb_check': 'none'}} if spatial else {}),
    }))
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, battlefield=arena,
        foe_sheet=sheet([], cl=18, score=1), foe_position={'x': 3, 'y': 5},
        ally_position={'x': 1, 'y': 6}, seed='REVIEW-DRAG')
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id,
        picks={'choice:needle.save_choice': 'STR', 'choice:needle.grapple_part': 'hand:left'})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    endpoint = Position(x=3, y=7)
    move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                and c.destination == endpoint and c.metadata.get('movement_mode', 'walk') == 'walk')
    assert move.movement_cost_ft == 15
    assert granted_movement.routes(engine, actor, 15, mode='walk')[endpoint][1] == 15
    settle(table, mid, move.candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position == endpoint
    assert actor.movement_remaining_ft == walking - 15
    receipt = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED'
                   and e.actor_id == OWNER)
    assert receipt.payload['cost_ft'] == 15
    assert any(c.condition_id == 'condition:typed.grappled'
               for c in engine.state.actors[FOE].conditions.values())
    assert engine._distance_actor_to_actor(actor, engine.state.actors[FOE]) <= 5


@pytest.mark.parametrize('mode', ['walk', 'fly', 'climb'])
def test_drag_cost_adds_once_after_terrain_and_surcharges(monkeypatch, mode):
    from tests.test_roof_movement import engine_at_wall, condition
    from tests.test_lock_choices import install
    engine, actor = engine_at_wall(climb_speed=30)
    actor.fly_speed_ft = 30
    other = next(a for a in engine.state.actors.values() if a is not actor)
    other.position = Position(x=actor.position.x, y=actor.position.y - 1)
    other.size_category = actor.size_category
    condition(other, 'condition:typed.grappled', source_actor_id=actor.entity_id,
              data={'reach_ft': 5, 'escape_dc': 1})
    install(monkeypatch, 'movement_step_surcharge', lambda *args: 3)
    destination = Position(x=actor.position.x, y=actor.position.y + 1)
    engine.grid.base_movement_cost[(destination.x, destination.y)] = 2
    assert engine._drag_multiplier(actor) == 2
    assert flight.step_cost(engine, actor, actor.position, destination, mode, set(),
                            passage_difficult={(destination.x, destination.y, 0)}) == 18


@pytest.mark.parametrize('spatial', [False, True])
def test_jump_approach_does_not_charge_drag_twice(spatial):
    from tests.test_roof_movement import engine_at_wall, condition
    engine, actor = engine_at_wall()
    actor.strength_score = 30
    other = next(a for a in engine.state.actors.values() if a is not actor)
    other.position = Position(x=actor.position.x, y=actor.position.y - 1)
    other.size_category = actor.size_category
    condition(other, 'condition:typed.grappled', source_actor_id=actor.entity_id,
              data={'reach_ft': 5, 'escape_dc': 1})
    approach = Position(x=actor.position.x, y=actor.position.y + 1)
    path = (actor.position, approach)
    route = (path, 10, 'walk') if spatial else (path, 10)
    assert engine._drag_multiplier(actor) == 2
    assert flight.jumps(engine, actor, {approach: route})[approach.model_copy(update={'z': 1})][1] == 20


@pytest.mark.parametrize('ask', [True, False])
@pytest.mark.parametrize('friendly', [True, False])
def test_bear_protects_only_eligible_creatures_after_native_damage(tmp_path, ask, friendly):
    hostile = FOE + '1'
    recipient = ALLY if friendly else hostile
    def attack(bundles):
        source = sealed_native_attack(bundles[2], 'Review blow', count=1, sides=6, modifier=30, range_ft=5)
        next(a for a in bundles[2]['action_catalog'] if a['source_definition_id'] == source)[
            'target_kind'] = 'ANY_CREATURE'
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [EARTH, CLOD], cl=6, ask=ask,
        extra_foes=1, bundle_transform=attack,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                   FOE: {'x': 5, 'y': 6}, hostile: {'x': 4, 'y': 7}}, seed='REVIEW-BEAR')
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.event_sequence
    prompts = settle(table, mid, candidate(combat, mid, 'Review blow', target=recipient).candidate_id,
        picks={'choice:needle.earth_response': 'bear', 'choice:needle.shift_recipient': None})
    engine = reload(tmp_path, mid)
    damage = next(e for e in engine.events if e.sequence > before and e.event_type == 'DAMAGE_COMMITTED'
                  and e.actor_id == FOE and e.target_ids == (recipient,))
    assert (damage.payload['reduced_to'] < damage.payload['rolled_or_pending_damage']) == friendly
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Burden Mark') == (not friendly)
    if ask:
        assert any(p['context']['reaction_source_id'] == 'choice:needle.earth_response'
                   for p in prompts) == friendly
