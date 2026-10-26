"""Round-11 flight review regressions, including actual Table transport."""
import pytest

from combat import falling, flight
from combat.ext import granted_moves, rider_step
from combat.gate2_runtime_models import ActionDefinition, Position
from combat.gate5_service import CombatService
from combat.typed_executor import Context
from tests.h1_support import ROOT, ME, duel, script
from tests import lock8_support as S
from tests.test_lock_choices import install
from tests.test_lock10_falling import prone
from tests.test_lock10_flight_movement import grant, request
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, answer


@pytest.mark.parametrize('protection', ['short', 'immune', 'reduced', 'temporary_hp', 'none'])
def test_landing_prone_uses_final_damage_before_temporary_hp(monkeypatch, protection):
    e = duel([])
    a = e.state.actors[ME]
    script(e, [4])
    if protection == 'immune':
        e._apply_condition(a, 'condition:typed.test_safe', 'test:safe', ME, expires_on=None,
                           data={'fall_damage_immune': 1})
    elif protection == 'reduced':
        install(monkeypatch, 'final_damage', lambda *args: {'amount': 0})
    elif protection == 'temporary_hp':
        e._grant_temp_hp(a, 10, 'test:ward', ME)
    hp = a.current_hp
    falling.displace(e, a, 1 if protection == 'short' else 2, 'test:launch')
    assert prone(a) is (protection in {'temporary_hp', 'none'})
    assert a.current_hp == hp - (4 if protection == 'none' else 0)


@pytest.mark.parametrize('above', [False, True])
def test_prison_checks_vertical_volume_not_drawing_projection(monkeypatch, above):
    prison = 'tianxia.talent.gravity.event_horizon_prison'
    e = S.fight(S.bundle(prison, dc=50), foe_at=(8, 6))
    e.grid.blocked.clear()
    e.grid.opaque.clear()
    e._wall_base = (frozenset(), frozenset(), frozenset(), {})
    install(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll', 'operation':'replace', 'natural_result':10})
    S.use(e, 'Event Horizon Prison', at=(5, 6))
    S.turn(e, S.FOE)
    a = e.state.actors[S.FOE]
    grant(e, a)
    # A sphere includes its vertical radius, not the entire horizontal projection.
    a.position = Position(x=9 if above else 5, y=6, z=5 if above else 4)
    dest = Position(x=10, y=6, z=5) if above else Position(x=5, y=6, z=5)
    c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == dest)
    start = len(e.events)
    e.execute_intent(request(c))
    assert (a.position == dest) is above
    saves = [r for r in e.events[start:] if r.event_type == 'SAVE_ROLLED']
    assert bool(saves) is not above


@pytest.mark.parametrize('delta', [-10, 10])
def test_walking_modifier_gain_and_removal_do_not_change_flight_spent(delta):
    e = duel([])
    a = e.state.actors[ME]
    grant(e, a, 20)
    flight.spend(a, 5)
    assert flight.remaining(e, a, 'fly') == 15
    e._add_modifier(a, 'test:speed', 'speed_ft', 'ADD', delta, 'SELF', expires_on='END_OF_CURRENT_TURN')
    assert flight.remaining(e, a, 'fly') == 15
    a.movement_remaining_ft += e._effective_speed(a)
    flight.dash(e, a)
    assert flight.remaining(e, a, 'fly') == 35
    mid = next(k for k, m in a.modifiers.items() if m.source_definition_id == 'test:speed')
    del a.modifiers[mid]
    e._append_event('MODIFIER_REMOVED', 'test:speed', actor_id=ME, payload={'modifier_id': mid})
    assert flight.remaining(e, a, 'fly') == 35


def test_starting_speed_bonus_expiry_and_late_flight_grant_keep_allowance_basis():
    e = duel([])
    a = e.state.actors[ME]
    e._add_modifier(a, 'test:speed', 'speed_ft', 'ADD', 10, 'SELF', expires_on=None)
    e._system_start_turn()
    flight.spend(a, 5)
    mid = next(k for k, m in a.modifiers.items() if m.source_definition_id == 'test:speed')
    del a.modifiers[mid]
    e._append_event('MODIFIER_REMOVED', 'test:speed', actor_id=ME, payload={'modifier_id': mid})
    grant(e, a, 20)
    assert flight.remaining(e, a, 'fly') == 15


def test_ground_level_fly_grant_adapter_commits_and_reloads(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def move(engine):
        a = engine.state.actors[LEFT]
        grant(engine, a)
        destination = Position(x=2, y=4)
        engine.grid.base_movement_cost[(2, 4)] = 2
        before = a.movement_remaining_ft
        _, route, cost = next(row for row in granted_moves.destinations(engine, a, 5, lambda p: p == destination))
        assert route.mode == 'fly' and cost == 5
        assert granted_moves.commit(engine, a, route, 'test:grant', budget_ft=5) == 5
        assert a.movement_remaining_ft == before
    on_hold(monkeypatch, move)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position == Position(x=2, y=4)
    event = next(ev for ev in loaded.engine.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == 'test:grant')
    assert event.payload['movement_mode'] == 'fly' and event.payload['granted_cost_ft'] == 5
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_movement_allowance_basis_is_recorded_and_survives_table_reload(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def change(engine):
        a = engine.state.actors[LEFT]
        engine._add_modifier(a, 'test:speed', 'speed_ft', 'ADD', 10, 'SELF', expires_on=None)
        engine._system_start_turn()
        mid = next(k for k, m in a.modifiers.items() if m.source_definition_id == 'test:speed')
        del a.modifiers[mid]
        engine._append_event('MODIFIER_REMOVED', 'test:speed', actor_id=LEFT, payload={'modifier_id': mid})
        grant(engine, a, 20)
    on_hold(monkeypatch, change)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    a = loaded.engine.state.actors[LEFT]
    assert a.turn_flags['movement_allowance_adjustment_ft'] == 10
    assert flight.remaining(loaded.engine, a, 'fly') == 20
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_table_immediate_flight_choices_name_altitude_mode_and_stay(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [], ask=True)
    def choose(engine):
        a = engine.state.actors[LEFT]
        grant(engine, a)
        action = ActionDefinition(source_definition_id=HOLD, display_name='Granted flight',
                                  owner_id=LEFT, economy='ACTION', resolution_kind='TYPED', target_kind='SELF')
        ctx = Context(engine=engine, actor=a, target=None, action=action, intent=engine._active_intent,
                      typed={}, targets=())
        rider_step.step(ctx, {'distance_ft': 5, 'no_oa': True})
    on_hold(monkeypatch, choose)
    send = cast_sender(combat, table, mid, 'Hold')
    result = send()
    assert result['status'] == 'REACTION_REQUIRED'
    options = result['reaction']['choice']['options']
    labels = {row['id']: row['label'] for row in options}
    ground = labels['cell:2,4,0']
    air = labels['cell:2,4,1']
    assert '0 feet altitude' in ground and '5 feet altitude' in air and 'Fly' in air
    assert '0 feet altitude; no movement' in labels['cell:3,4']
    assert send([answer(result['reaction'], 'cell:2,4,1')])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position == Position(x=2, y=4, z=1)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
