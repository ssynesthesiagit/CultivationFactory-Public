"""L6 review: contact geometry and attack-use accounting at the real table."""
import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_hidden_targeting import ROOT, LEFT, RIGHT, table_fight, turn, move_to
from tests.test_lock2_persistence import act
from tests.test_lock6_destroyed_mount import mounted_table, mount
from tests.test_lock_choices import install


def place(engine, actor, at):
    actor.position = Position(x=at[0], y=at[1])
    engine._append_event('MOVEMENT_COMMITTED', 'test:placement', actor_id=actor.entity_id,
        payload={'destination': actor.position.model_dump(mode='json'), 'movement_remaining_ft': actor.movement_remaining_ft,
                 'movement_cost_ft': 0, 'path': []})


def test_hidden_large_nonanchor_contact_is_excluded_after_reload_and_ai_ends(monkeypatch, tmp_path):
    def arrange(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == RIGHT:
            blocker = mount(engine)
            engine._apply_condition(blocker, 'condition:typed.hidden', 'test:hide', blocker.entity_id, expires_on='UNTIL_REMOVED')
            place(engine, engine.state.actors[RIGHT], (6, 6))
    install(monkeypatch, 'event', arrange)
    combat, table, mid = mounted_table(tmp_path)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = combat._load_session(mid).engine
    assert mount(before).position == Position(x=5, y=4)
    assert (6, 5) in before._actor_cells(mount(before))
    allowance = before.state.actors[RIGHT].movement_remaining_ft
    move_to(table, mid, (6, 5))  # non-anchor corner of the unseen 2x2 creature
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    session = combat._load_session(mid)
    actor = session.engine.state.actors[RIGHT]
    assert actor.position == Position(x=6, y=6) and actor.movement_remaining_ft == allowance
    assert {'x': 6, 'y': 5} in actor.turn_flags['unseen_contact_cells']
    assert all(type(v) is int for cell in actor.turn_flags['unseen_contact_cells'] for v in cell.values())
    assert not any(c['destination'] == {'x': 6, 'y': 5} for c in table.state(mid)['menu']['moves'])
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    for _ in range(12):
        state = table.state(mid)
        assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
        if combat._load_session(mid).engine.state.current_actor_id != RIGHT:
            break
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id != RIGHT
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def empty_square_table(monkeypatch, tmp_path):
    def conceal_and_move(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == RIGHT:
            target = engine.state.actors[RIGHT]
            engine._apply_condition(target, 'condition:typed.hidden', 'test:hide', RIGHT, expires_on='UNTIL_REMOVED')
            place(engine, target, (9, 11))
    install(monkeypatch, 'event', conceal_and_move)
    combat, table, mid = table_fight(tmp_path, left_at=(7, 11), right_at=(8, 11),
        left_abilities=('TAL_DUAL_WIELDING_SYNCHRONOUS_ACCURACY',), left_weapons=('duan_jian', 'bi_shou'))
    turn(table, mid, RIGHT)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    return combat, table, mid


def use_weapon(table, mid, suffix):
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'].endswith(suffix))
    option = next(o for o in group['options'] if o['target_ids'] == [RIGHT])
    assert option['destination'] == {'x': 8, 'y': 11}
    assert table.act(mid, option['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])['status'] == 'COMMITTED'


@pytest.mark.parametrize('answer', ['bi_shou#offhand', 'bi_shou#offhand_synchronous'])
def test_empty_square_lead_opens_answer_and_answer_consumes_use(monkeypatch, tmp_path, answer):
    combat, table, mid = empty_square_table(monkeypatch, tmp_path)
    before = combat._load_session(mid).engine
    sequence, counter = before.state.event_sequence, before.roller.counter
    hp = before.state.actors[RIGHT].current_hp
    use_weapon(table, mid, 'duan_jian')
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    loaded = combat._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.turn_flags['offhand:1'] is True
    assert actor.turn_flags['pair:lead_missed'] is True
    use_weapon(table, mid, answer)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.turn_flags['offhand:1'] is False
    assert actor.turn_flags['pair:paired_strike_done'] is True
    if answer.endswith('synchronous'):
        assert actor.turn_flags['pair:synchronous_used'] is True
        assert actor.resources['resource:core.martial_focus'] == 0
    assert not any(g['source_definition_id'].endswith(answer) for g in table.state(mid)['menu']['actions'])
    events = [e for e in loaded.engine.events if e.sequence > sequence]
    assert any(e.event_type == 'ATTACK_LOCATION_MISSED' for e in events)
    assert not any(e.event_type in ('ATTACK_ROLLED', 'DAMAGE_COMMITTED', 'REACTION_RESOLVED') for e in events)
    assert loaded.engine.roller.counter == counter and loaded.engine.state.actors[RIGHT].current_hp == hp
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
