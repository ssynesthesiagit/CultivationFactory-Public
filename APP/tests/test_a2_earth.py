"""Earth second-pass regressions: real table transactions and cold journal reloads."""
import pytest

from combat.ext import earth_responses as earth
from combat.posture import standing_cost
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, fight, reload, turn, cell_send, settle, resolve

SINKING = 'TAL_EARTH_SINKING_FOOT_REBUKE'
RUT = 'TAL_EARTH_SINK_THE_WHEEL_RUT'
WATCH = 'condition:typed.earth_rut_watch'
LOAD = 'TAL_EARTH_LOAD_BEARING_BACK'
STANCE = 'TAL_EARTH_DEEP_ROOT_STANCE'
MARK = {'type': 'mark', 'mark': 'Burden Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}


def choose_rebuke(option):
    def pick(prompt):
        if 'Sinking Foot Rebuke' in str(prompt):
            return [option]
        if 'Anchor Step' in str(prompt):
            return []
        if 'Drag Down' in str(prompt):
            return ['drag']
        return []
    return pick


@pytest.mark.parametrize('option', ['DASH', 'DEX', 'STAND'])
@pytest.mark.parametrize('right_ai', [False, True])
def test_rebuke_all_player_options_after_drag_commit_reload_and_expire(tmp_path, option, right_ai):
    combat, table, mid = fight(tmp_path, [earth.BASE, SINKING], prepare=[MARK],
        cause=[{'type': 'save', 'ability': 'dex', 'dc': 'technique_save_dc',
                'applies_to': 'self', 'on_fail': [], 'on_success': []}], cause_target='SELF')
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    settle(lambda answers: act(table, mid, 'end', answers), choose=choose_rebuke(option))
    assert table.state(mid)['menu']['actor_id'] == RIGHT
    send = cell_send(table, mid, 'Move', (4, 7))
    if right_ai:
        from combat.gate4_adapters import ManualControllerAdapter
        engine = combat._load_session(mid).engine
        cid = next(c.candidate_id for c in engine.legal_candidates()
                   if c.source_definition_id == 'system:combat.movement' and c.destination is not None
                   and (c.destination.x, c.destination.y) == (4, 7))
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
        send = lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers)
    _, prompts = settle(send, choose=choose_rebuke(option))
    rebuke = next(p for p in prompts if 'Sinking Foot Rebuke' in str(p))
    assert 'Drag Down' in str(rebuke) and 'Visitor' in str(rebuke)
    assert {o['id'] for o in rebuke['choice']['options']} == {'DASH', 'DEX', 'STAND'}
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    assert not bears_mark(actor, LEFT, 'Burden Mark')
    assert any(c.expires_on == 'STAND_UP' for c in actor.conditions.values())
    if right_ai:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='MANUAL')
    if option == 'STAND':
        assert standing_cost(engine, actor) == 20
        state = table.state(mid)
        candidates = [c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.stand_up']
        assert candidates
        result = table.act(mid, candidates[0].candidate_id, state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'], [])
        assert result['status'] == 'COMMITTED'
        after = reload(combat, mid).state.actors[RIGHT]
        assert actor.movement_remaining_ft - after.movement_remaining_ft == 20
        assert not any(c.expires_on == 'STAND_UP' for c in after.conditions.values())
    elif option == 'DEX':
        assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
        engine = reload(combat, mid)
        assert next(r for r in reversed(engine.rolls) if 'save' in r.reason.lower()).mode == 'DISADVANTAGE'
        assert not any(c.condition_id == earth.SLOW_DEX for c in engine.state.actors[RIGHT].conditions.values())
        assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
        assert next(r for r in reversed(reload(combat, mid).rolls) if 'save' in r.reason.lower()).mode == 'NORMAL'
    else:
        assert not any(c.display_name == 'Dash' for c in engine.legal_candidates())
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert not any(c.source_definition_id == SINKING for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('stance', [False, True])
def test_load_bearing_back_marks_actual_source_only_on_foundation(tmp_path, stance):
    combat, table, mid = fight(tmp_path, [LOAD, *([STANCE] if stance else [])], ally=[],
        cause=[{'type': 'forced_movement', 'distance_ft': 15, 'direction': 'away', 'applies_to': 'target'}])
    if stance:
        assert act(table, mid, 'Deep Root Stance')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    _, prompts = resolve(lambda answers: act(table, mid, 'Cause', answers, target_id=ALLY))
    assert any('Load-Bearing Back' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark') == stance
    assert not bears_mark(engine.state.actors[ALLY], LEFT, 'Burden Mark')
    assert not engine.state.actors[LEFT].reaction_available
    event = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == LOAD)
    assert event.payload['distance_before'] - event.payload['distance_after'] == 10


def test_load_bearing_back_can_mark_an_allied_force_source(tmp_path):
    """The printed source clause has no hostile-only restriction."""
    combat, table, mid = fight(tmp_path, [LOAD, STANCE], ally=[],
        right_team='team:factory', extra_witness=True, cause_target='ANY_CREATURE',
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 7}},
        cause=[{'type': 'forced_movement', 'distance_ft': 15, 'direction': 'away', 'applies_to': 'target'}])
    assert act(table, mid, 'Deep Root Stance')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    _, prompts = resolve(lambda answers: act(table, mid, 'Cause', answers, target_id=ALLY))
    assert any('Load-Bearing Back' in str(p) for p in prompts)
    engine = reload(combat, mid)
    event = next(e for e in reversed(engine.events) if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == LOAD)
    assert event.payload['distance_before'] - event.payload['distance_after'] == 10
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')


@pytest.mark.parametrize('success', [False, True])
def test_wheel_rut_success_requires_ten_feet_inside_after_save(tmp_path, success):
    combat, table, mid = fight(tmp_path, [RUT], left_save_dc=1 if success else 100)
    settle(cell_send(table, mid, 'Sink the Wheel-Rut', (4, 7)))
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    assert bears_mark(actor, LEFT, 'Burden Mark') == (not success)
    if not success:
        assert engine._effective_speed(actor) == 20
        turn(table, mid, LEFT)
        engine = reload(combat, mid)
        assert engine._effective_speed(engine.state.actors[RIGHT]) == 20
        return
    assert any(c.condition_id == WATCH for c in actor.conditions.values())
    settle(cell_send(table, mid, 'Move', (5, 6)))
    actor = reload(combat, mid).state.actors[RIGHT]
    assert not bears_mark(actor, LEFT, 'Burden Mark')
    assert next(c for c in actor.conditions.values() if c.condition_id == WATCH).data['feet'] == 5
    settle(cell_send(table, mid, 'Move', (5, 7)))
    actor = reload(combat, mid).state.actors[RIGHT]
    assert bears_mark(actor, LEFT, 'Burden Mark')
    assert not any(c.condition_id == WATCH for c in actor.conditions.values())


def test_wheel_rut_partial_distance_expires_at_turn_end(tmp_path):
    combat, table, mid = fight(tmp_path, [RUT], left_save_dc=1)
    settle(cell_send(table, mid, 'Sink the Wheel-Rut', (4, 7)))
    turn(table, mid, RIGHT)
    settle(cell_send(table, mid, 'Move', (5, 6)))
    turn(table, mid, LEFT)
    assert not any(c.condition_id == WATCH for c in reload(combat, mid).state.actors[RIGHT].conditions.values())
    turn(table, mid, RIGHT)
    actor = reload(combat, mid).state.actors[RIGHT]
    assert next(c for c in actor.conditions.values() if c.condition_id == WATCH).data['feet'] == 0


def test_wheel_rut_successful_entry_then_forced_steps_commit_reload(tmp_path):
    """Entry itself is not inside travel; each subsequent push counts once."""
    combat, table, mid = fight(tmp_path, [RUT], left_save_dc=1,
        positions={LEFT: {'x': 4, 'y': 3}, RIGHT: {'x': 4, 'y': 5}},
        prepare=[{'type': 'forced_movement', 'distance_ft': 5,
                  'direction': 'away', 'applies_to': 'target'}])
    settle(cell_send(table, mid, 'Sink the Wheel-Rut', (4, 7)))
    for y, feet in [(6, 0), (7, 5), (8, 10)]:
        settle(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT))
        actor = reload(combat, mid).state.actors[RIGHT]
        assert (actor.position.x, actor.position.y) == (4, y)
        assert bears_mark(actor, LEFT, 'Burden Mark') == (feet == 10)
        watches = [c for c in actor.conditions.values() if c.condition_id == WATCH]
        if feet < 10:
            assert len(watches) == 1 and watches[0].data['feet'] == feet
        else:
            assert not watches


def test_wheel_rut_large_edge_overlap_counts_steps_commit_reload(tmp_path):
    from combat.spatial_areas import zone_contains
    combat, table, mid = fight(tmp_path, [RUT], left_save_dc=1,
        positions={LEFT: {'x': 4, 'y': 4}, RIGHT: {'x': 2, 'y': 6}},
        cause_target='SELF', cause=[{'type': 'size_change', 'size': 'Large',
                                   'duration': 'until_removed'}])
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    footprint = engine._footprint(engine.state.actors[RIGHT])
    assert (footprint.width_cells, footprint.height_cells) == (2, 2)
    turn(table, mid, LEFT)
    settle(cell_send(table, mid, 'Sink the Wheel-Rut', (4, 7)))
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == LEFT)
    actor = engine.state.actors[RIGHT]
    assert zone_contains(engine, actor, zone)
    assert (actor.position.x, actor.position.y) not in {(p.x, p.y) for p in zone.affected_cells}
    assert next(c for c in actor.conditions.values() if c.condition_id == WATCH).data['feet'] == 0
    for y, feet in [(7, 5), (8, 10)]:
        settle(cell_send(table, mid, 'Move', (2, y)))
        actor = reload(combat, mid).state.actors[RIGHT]
        assert bears_mark(actor, LEFT, 'Burden Mark') == (feet == 10)
        watches = [c for c in actor.conditions.values() if c.condition_id == WATCH]
        if feet < 10:
            assert len(watches) == 1 and watches[0].data['feet'] == feet
        else:
            assert not watches


def test_load_bearing_back_on_actual_foundation_commit_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [LOAD, 'EARTH_BASE_SET_FOUNDATION'], ally=[],
        cause=[{'type': 'forced_movement', 'distance_ft': 15,
                'direction': 'away', 'applies_to': 'target'}])
    assert act(table, mid, 'EARTH_BASE_SET_FOUNDATION', target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert not any(c.condition_id == earth.STANCE for c in owner.conditions.values())
    assert earth._on_foundation(engine, owner, owner)
    assert any(z.active and z.owner_id == LEFT and 'SET_FOUNDATION' in z.source_definition_id
               for z in engine.state.zones.values())
    turn(table, mid, RIGHT)
    _, prompts = resolve(lambda answers: act(table, mid, 'Cause', answers, target_id=ALLY))
    assert any('Load-Bearing Back' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    assert not bears_mark(engine.state.actors[ALLY], LEFT, 'Burden Mark')
    assert not engine.state.actors[LEFT].reaction_available
    event = next(e for e in reversed(engine.events)
                 if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == LOAD)
    assert event.payload['distance_before'] - event.payload['distance_after'] == 10


def test_rebuke_ai_owner_chooses_automatically_on_other_turn(tmp_path):
    combat, table, mid = fight(tmp_path, [earth.BASE, SINKING], prepare=[MARK])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    settle(lambda answers: act(table, mid, 'end', answers), choose=choose_rebuke('STAND'))
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    _, prompts = settle(cell_send(table, mid, 'Move', (4, 7)))
    assert not any('Sinking Foot Rebuke' in str(p) or 'Drag Down' in str(p) for p in prompts)
    actor = reload(combat, mid).state.actors[RIGHT]
    assert any(c.condition_id == earth.SLOW_DEX for c in actor.conditions.values())


@pytest.mark.parametrize('ai', [False, True])
def test_marked_responses_require_the_owner_to_perceive_the_creature(tmp_path, ai):
    from combat.senses import perceives
    combat, table, mid = fight(tmp_path, [earth.BASE, SINKING], cl=1,
        prepare=[MARK, *[{'type': 'condition', 'condition': name, 'applies_to': 'self',
                         'duration': 'until_removed'} for name in ['blinded', 'deafened']]])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not perceives(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    _, start_prompts = settle(lambda answers: act(table, mid, 'end', answers), choose=choose_rebuke('DASH'))
    assert not any('Earth Response' in str(p) for p in start_prompts)
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    _, move_prompts = settle(cell_send(table, mid, 'Move', (4, 7)), choose=choose_rebuke('DASH'))
    assert not any('Earth Response' in str(p) or 'Sinking Foot Rebuke' in str(p) for p in move_prompts)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
