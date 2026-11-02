"""Mounted movement budgets and AI endpoint memory survive table commits/reloads."""
import pytest
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import mounts
from tests.test_mounts import rider_bundle, ME, FOE, ROOT
from tests.test_hidden_targeting import turn
from tests.test_lock21_pingpong import choice_with_retreat


def setup(tmp_path, talents=()):
    athletics = 'TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS' in talents
    bundle = rider_bundle(talents)
    if athletics:
        from combat.factory_compiler import compile_character
        from tests.test_mounts import bm
        sheet = {**bm.SHEET, 'equipment': [],
            'spheres_and_talents': {'sphere_record_ids': [bm.BEASTMASTERY, 'tianxia.sphere.athletics'],
                'learned_talent_record_ids': list(talents),
                'automatic_sphere_component_record_ids': [
                    'BEASTMASTERY_BASE_RIDER_PACKAGE', 'ATHLETICS_BASE_COORDINATED_MOVEMENT']}}
        bundle = compile_character(sheet, actor_id=ME, summon_plan=bundle.get('summon_plan'))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Mountdither yard', 'width_squares': 24,
        'height_squares': 14, 'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[20, 10]]}})
    arena = combat.tabletop_maps.arenas()['battlefield:map.mountdither-yard']
    session = combat.persistence.create_match(match_seed='MOUNTDITHER', typed_bundles=(bundle,),
        battlefield=arena,
        roster_setup={'primary_actor_ids': [ME, FOE], 'team_by_actor': {ME: 'a', FOE: 'b'},
            'starting_positions': {ME: {'x': 3, 'y': 6}, FOE: {'x': 12, 'y': 6}}})
    for actor_id in (ME, FOE):
        combat.set_controller_mode(session.match_id, actor_id=actor_id, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    turn(table, session.match_id, ME)
    return combat, table, session.match_id


def reload(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def move(table, mid, engine, destination):
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == destination)
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, 0, [])
    assert result['status'] == 'COMMITTED', result
    return candidate


def test_mounted_budget_exhausts_after_mount_speed_through_cold_reload(tmp_path, monkeypatch):
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.movement_budget import WITHHELD
    original = Gate4ControllerEngine._append_event
    injected = []
    def restore(engine, event_type, *args, **kwargs):
        event = original(engine, event_type, *args, **kwargs)
        rider = engine.state.actors.get(ME)
        if (event_type == 'MOVEMENT_COMMITTED' and event.actor_id == ME
                and rider.movement_remaining_ft == 0 and not rider.turn_flags.get('test:restore_injected')):
            injected.append(True)
            rider.turn_flags['test:restore_injected'] = 1
            # Reproduce the stale withheld marker independently of a particular
            # sphere: the restoration path must respect the mounted ledger.
            rider.turn_flags[WITHHELD] = 60
            engine._apply_condition(rider, 'condition:typed.grappled', 'test:hold', FOE,
                                    expires_on='UNTIL_REMOVED')
            engine._remove_condition(rider, 'condition:typed.grappled', 'test:free')
        return event
    monkeypatch.setattr(Gate4ControllerEngine, '_append_event', restore)
    combat, table, mid = setup(tmp_path)
    spent = 0
    for step in range(12):
        session = reload(tmp_path, mid)
        engine = session.engine
        rider = engine.state.actors[ME]
        assert rider.movement_remaining_ft == 60 - spent
        destination = Position(x=4 if step % 2 == 0 else 3, y=6)
        candidate = move(table, mid, engine, destination)
        spent += candidate.movement_cost_ft
    session = reload(tmp_path, mid)
    rider = session.engine.state.actors[ME]
    mount = mounts.mount_of(session.engine, rider)
    assert spent == session.engine._effective_speed(mount) == 60
    assert rider.turn_flags[f'mount_movement_spent_ft:{mount.entity_id}'] == 60
    assert rider.movement_remaining_ft == 0
    assert injected
    restored = [ev for ev in session.engine.events if ev.event_type == 'MOVEMENT_ALLOWANCE_RESTORED']
    assert restored and restored[-1].payload['restored_ft'] == 0
    assert not [c for c in session.engine.legal_candidates() if c.kind == 'MOVE']
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_dash_still_extends_the_mounted_pool_through_cold_reload(tmp_path):
    talents = ['TAL_BEASTMASTERY_MOUNTED_MANEUVERS']
    combat, table, mid = setup(tmp_path, talents)
    engine = reload(tmp_path, mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == 'Mount: Dash')
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, 0, [])
    assert result['status'] == 'COMMITTED', result
    spent = 0
    for x in (9, 3, 9, 3):
        engine = reload(tmp_path, mid).engine
        candidate = move(table, mid, engine, Position(x=x, y=6))
        spent += candidate.movement_cost_ft
    session = reload(tmp_path, mid)
    assert spent == 120
    assert session.engine.state.actors[ME].movement_remaining_ft == 0
    assert not [c for c in session.engine.legal_candidates() if c.kind == 'MOVE']
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_mounted_pool_preserves_rider_speed_halving(tmp_path, monkeypatch):
    """The mounted allowance and ceiling use composed Speed, including a rider reduction."""
    from combat.gate2_runtime_models import ModifierInstance

    # This typed field is the same one Leg-Smasher uses. The test isolates the
    # Speed composition without needing to play a separate attack first.
    original = mounts.start_bond
    def slowed_bond(rider, mount):
        original(rider, mount)
        rider.modifiers['test:speed-halved'] = ModifierInstance(
            modifier_id='test:speed-halved', source_definition_id='test:slow', source_actor_id=FOE,
            target_id=ME, target_field='speed_halved', operation='SET', value=1, applies_to='speed')
    monkeypatch.setattr(mounts, 'start_bond', slowed_bond)
    _, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid).engine
    rider = engine.state.actors[ME]
    assert engine._effective_speed(rider) == 30
    assert mounts.mounted_allowance(engine, rider, 30) == 30
    assert mounts.mounted_remaining(engine, rider) == 30
    assert rider.movement_remaining_ft == 30
    move(table, mid, engine, Position(x=9, y=6))
    session = reload(tmp_path, mid)
    assert session.engine.state.actors[ME].movement_remaining_ft == 0
    assert not [c for c in session.engine.legal_candidates() if c.kind == 'MOVE']
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_mounted_pool_keeps_rider_speed_bonus_through_table_reload(tmp_path):
    """Court of Ten Thousand Steps adds its full bonus to a controlled mount's pool."""
    from combat.gate2_runtime_models import Position

    talents = ['TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS']
    combat, table, mid = setup(tmp_path, talents)
    engine = reload(tmp_path, mid).engine
    action = next(c for c in engine.legal_candidates() if c.display_name == 'Court of Ten Thousand Steps')
    result = table.act(mid, action.candidate_id, action.decision_id, action.state_version, 0, [])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid).engine
    assert engine._effective_speed(engine.state.actors[ME]) == 80
    assert engine.state.actors[ME].movement_remaining_ft == 80
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=7, y=6))
    assert candidate.movement_cost_ft == 20
    move(table, mid, engine, candidate.destination)
    session = reload(tmp_path, mid)
    assert session.engine.state.actors[ME].movement_remaining_ft == 60
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('dash', [False, True])
@pytest.mark.parametrize('genesis', [False, True])
def test_immobilized_start_escape_then_court_preserves_mounted_pool(tmp_path, monkeypatch, dash, genesis):
    """A restored mounted allowance remains the baseline for subsequent Speed changes."""
    from combat.gate2_runtime_models import ConditionInstance

    original = mounts.start_bond
    def held_bond(rider, mount):
        original(rider, mount)
        # Saved genesis fixture: start held, then escape through the real table
        # action. A low DC keeps the check deterministic without replacing it.
        rider.conditions['test:starting-hold'] = ConditionInstance(
            instance_id='test:starting-hold', condition_id='condition:typed.grappled',
            source_definition_id='test:hold', source_actor_id=FOE, target_id=ME,
            applied_sequence=0, expires_on='UNTIL_REMOVED', data={'escape_dc': 1})
    monkeypatch.setattr(mounts, 'start_bond', held_bond)
    talents = ['TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS', 'TAL_BEASTMASTERY_MOUNTED_MANEUVERS']
    combat, table, mid = setup(tmp_path, talents)
    if not genesis:
        turn(table, mid, FOE)
        turn(table, mid, ME)
    engine = reload(tmp_path, mid).engine
    rider = engine.state.actors[ME]
    assert engine._effective_speed(rider) == rider.movement_remaining_ft == 0
    assert rider.turn_flags['movement_withheld_ft'] == 60

    def act_named(name):
        engine = reload(tmp_path, mid).engine
        action = next(c for c in engine.legal_candidates() if c.display_name == name)
        result = table.act(mid, action.candidate_id, action.decision_id, action.state_version, 0, [])
        assert result['status'] == 'COMMITTED', result

    act_named('Escape grapple')
    engine = reload(tmp_path, mid).engine
    assert not any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[ME].conditions.values())
    assert engine.state.actors[ME].movement_remaining_ft == 60
    assert any(ev.event_type == 'MOVEMENT_ALLOWANCE_RESTORED' and ev.payload['restored_ft'] == 60
               for ev in engine.events)
    if dash:
        act_named('Mount: Dash')
    engine = reload(tmp_path, mid).engine
    move(table, mid, engine, Position(x=5, y=6))
    act_named('Court of Ten Thousand Steps')
    engine = reload(tmp_path, mid).engine
    rider = engine.state.actors[ME]
    mount = mounts.mount_of(engine, rider)
    assert engine._effective_speed(rider) == 80
    assert rider.movement_remaining_ft == (130 if dash else 70)
    assert rider.turn_flags[f'mount_movement_speed_ft:{mount.entity_id}'] == 80
    assert rider.turn_flags[f'mount_movement_spent_ft:{mount.entity_id}'] == 10
    policy, _ = combat.policies.for_actor(ME)
    human = build_decision_context(engine, policy, for_ai=False)
    ai = build_decision_context(engine, policy, for_ai=True)
    assert {c.candidate_id for c in human.legal_candidates if c.kind == 'MOVE'} == {
        c.candidate_id for c in ai.legal_candidates if c.kind == 'MOVE'}
    # Spend the complete 80-foot ordinary allowance across commits/reloads.
    # Any Dash grant remains after the ordinary allowance is spent.
    for destination in (Position(x=11, y=3), Position(x=5, y=6), Position(x=7, y=6)):
        move(table, mid, reload(tmp_path, mid).engine, destination)
    session = reload(tmp_path, mid)
    rider = session.engine.state.actors[ME]
    assert rider.movement_remaining_ft == (60 if dash else 0)
    assert rider.turn_flags[f'mount_movement_spent_ft:{mount.entity_id}'] == 80
    if not dash:
        assert not [c for c in session.engine.legal_candidates() if c.kind == 'MOVE']
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_mounted_ai_remembers_endpoints_but_human_can_return(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid).engine
    origin = engine.state.actors[ME].position
    destination = Position(x=4, y=6)
    move(table, mid, engine, destination)
    session = reload(tmp_path, mid)
    engine = session.engine
    policy, _ = combat.policies.for_actor(ME)
    context = build_decision_context(engine, policy, for_ai=True)
    assert origin in context.movement_endpoints and destination in context.movement_endpoints
    retreat = next(c for c in context.legal_candidates if c.kind == 'MOVE' and c.destination == origin)
    choice = choice_with_retreat(context, origin)
    assert retreat.candidate_id not in choice.record.legal_alternatives
    # Native human domain retains every legal destination, including the old square.
    human = build_decision_context(engine, policy, for_ai=False)
    assert {c.candidate_id for c in human.legal_candidates if c.kind == 'MOVE'} == {
        c.candidate_id for c in context.legal_candidates if c.kind == 'MOVE'}
    move(table, mid, engine, origin)
    session = reload(tmp_path, mid)
    assert session.engine.state.actors[ME].position == origin
    # A real new defensive benefit resets the policy segment, so old ground
    # can be reconsidered; the guard is not a permanent ban for AI actors.
    engine = session.engine
    dodge = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.dodge')
    result = table.act(mid, dodge.candidate_id, dodge.decision_id, dodge.state_version, 0, [])
    assert result['status'] == 'COMMITTED', result
    session = reload(tmp_path, mid)
    context = build_decision_context(session.engine, policy, for_ai=True)
    assert not context.movement_endpoints
    return_move = next(c for c in context.legal_candidates if c.kind == 'MOVE' and c.destination == destination)
    assert return_move.candidate_id in choice_with_retreat(context, destination).record.legal_alternatives
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_ai_mounted_turn_never_revisits_without_a_new_opportunity(tmp_path):
    combat, table, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    from combat.movement_history import endpoints
    moves = 0
    for step in range(30):
        before = reload(tmp_path, mid).engine
        if before.state.current_actor_id != ME:
            break
        seq = len(before.events)
        state = table.state(mid)
        result = table.auto_step(mid, state['last_sequence'])
        assert result['status'] == 'COMMITTED', result
        after = reload(tmp_path, mid).engine
        for ev in after.events[seq:]:
            if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == ME:
                assert Position.model_validate(ev.payload['destination']) not in endpoints(before, ME)
                moves += 1
    else:
        raise AssertionError('Mounted AI did not finish its turn')
    assert moves > 0
    session = reload(tmp_path, mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
