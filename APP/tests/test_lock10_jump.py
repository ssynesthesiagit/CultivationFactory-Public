"""High jumps use Strength, running starts, movement payment and native falls."""
from combat import flight
from combat.gate2_runtime_models import Position
from tests.h1_support import ME, duel
from tests.test_lock10_flight_movement import request


def test_standing_high_jump_pays_and_lands_upright_without_damage():
    e = duel([])
    a = e.state.actors[ME]
    a.strength_score = 24  # +7: 10 ft running, 5 ft standing
    for other in e.state.actors.values():
        other.reaction_available = False
    before = a.movement_remaining_ft
    c = next(c for c in e.legal_candidates() if c.metadata.get('movement_mode') == 'jump'
             and c.destination.x == a.position.x and c.destination.y == a.position.y)
    assert c.destination.z == 1
    e.execute_intent(request(c))
    assert a.position.z == 0 and a.movement_remaining_ft == before - 5
    assert not e._has_condition(a, 'condition:typed.prone')
    assert any('jumps 5 ft.' in str(row.payload) for row in e.events)


def test_running_jump_needs_ten_feet_in_one_direction():
    e = duel([])
    a = e.state.actors[ME]
    a.strength_score = 24
    assert flight.jump_steps(e, a, (Position(x=0, y=0),)) == 1
    assert flight.jump_steps(e, a, tuple(Position(x=i, y=0) for i in range(3))) == 2
    assert flight.jump_steps(e, a, (Position(x=0,y=0), Position(x=1,y=0), Position(x=1,y=1))) == 1
    assert not flight.valid_jump(e, a, tuple(Position(x=0,y=0,z=i) for i in range(3)))
    assert flight.valid_jump(e, a, (Position(x=0,y=0), Position(x=1,y=0), Position(x=2,y=0),
                                  Position(x=2,y=0,z=1), Position(x=2,y=0,z=2)))


def test_non_flying_ai_does_not_select_jumps_and_saves_do_not_grant_strength():
    e = duel([])
    a = e.state.actors[ME]
    saved = a.model_dump()
    saved.pop('strength_score', None)
    a = type(a).model_validate(saved)
    e.state.actors[ME] = a
    a.saving_throws['STR'] = 20
    assert a.strength_score == 10
    assert not flight.jumps(e, a, {})
    a.strength_score = 30
    e.typed_control_modes = {ME: 'API_AUTO'}
    assert all(c.destination.z == 0 for c in e.legal_candidates() if c.kind == 'MOVE')


def test_walk_on_finite_platform_can_step_off_but_cannot_walk_across_air():
    e = duel([])
    a = e.state.actors[ME]
    a.position = Position(x=0, y=0, z=2)
    e.grid.blocked.update({(0,0), (1,0)})
    e.grid.terrain_spans['BLOCKED'].update({(0,0): [(0,10)], (1,0): [(0,10)]})
    e.grid.finite_heights = True
    routes = flight.reachable(e, a)
    assert Position(x=1,y=0,z=2) in routes
    assert Position(x=2,y=0,z=2) in routes
    assert Position(x=3,y=0,z=2) not in routes
