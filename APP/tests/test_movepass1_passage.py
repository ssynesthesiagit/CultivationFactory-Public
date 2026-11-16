"""MOVEPASS1: voluntary movement passes allies, Incapacitated, Tiny and size-distant creatures."""
import pytest
from combat import movement_passage
from combat.creature_passage import geometry
from combat.gate2_runtime_models import Position, ActionIntent
from tests import lock8_support as S
from tests.test_lock_choices import install


def corridor(e):
    e.grid.blocked = {(x, y) for x in range(e.grid.width) for y in range(e.grid.height) if y != 6}
    e.grid.base_movement_cost.clear()
    e.grid.qi_hazard.clear()
    e._wall_base = (frozenset(e.grid.blocked), frozenset(), frozenset(), {})


def move(e, x):
    return next((c for c in e.legal_candidates()
                 if c.kind.value == 'MOVE' and c.destination == Position(x=x, y=6)), None)


def moves(e):
    return {(c.destination.x, c.destination.y) for c in e.legal_candidates() if c.kind.value == 'MOVE'}


def use(e, c):
    e.execute_intent(ActionIntent(intent_id='movepass-' + str(e.state.event_sequence),
        decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination))


def ally_fight():
    return S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),
                   ally=S.bundle('SAND_BASE_SCOURING_HAND', actor_id=S.ALLY), ally_at=(4, 6), foe_at=(9, 6))


def test_ally_space_is_passed_at_difficult_cost_and_not_ended_in():
    e = ally_fight()
    corridor(e)
    assert move(e, 4) is None
    c = move(e, 5)
    assert c is not None and c.movement_cost_ft == 15
    assert c.canonical_path[1] == Position(x=4, y=6)
    use(e, c)
    mover = e.state.actors[S.ME]
    assert mover.position == Position(x=5, y=6)
    assert mover.movement_remaining_ft == 30 - 15


def test_menu_keeps_every_square_it_offered_before(monkeypatch):
    e = ally_fight()
    corridor(e)
    monkeypatch.setattr(movement_passage, 'passable', lambda *args: False)
    before = moves(e)
    monkeypatch.undo()
    assert before <= moves(e) and (5, 6) in moves(e) and (4, 6) not in moves(e)


def test_hostile_creature_still_blocks():
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    assert move(e, 5) is None
    blocked, ends, _, _ = geometry(e, e.state.actors[S.ME])
    assert (4, 6) in blocked


def test_incapacitated_hostile_creature_can_be_passed_then_blocks_when_condition_removed():
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    foe = e.state.actors[S.FOE]
    source = 'test:movepass:incapacitated'
    e._apply_condition(foe, 'condition:typed.incapacitated', source, S.ME,
                       expires_on='UNTIL_REMOVED')
    assert movement_passage.incapacitated(foe)
    c = move(e, 5)
    assert c is not None and c.movement_cost_ft == 15 and move(e, 4) is None

    e._remove_condition(foe, 'condition:typed.incapacitated', source)
    assert not movement_passage.incapacitated(foe)
    assert move(e, 5) is None


@pytest.mark.parametrize('category,passable', [('Tiny', True), ('Small', False), ('Large', False), ('Huge', True)])
def test_size_rule_for_hostile_creatures(monkeypatch, category, passable):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    real = movement_passage.current_category
    monkeypatch.setattr(movement_passage, 'current_category',
                        lambda engine, actor: category if actor.entity_id == S.FOE else real(engine, actor))
    assert (move(e, 5) is not None) is passable


def test_plugin_hook_makes_hostile_space_passable_and_is_inert_by_default(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    assert move(e, 5) is None
    install(monkeypatch, 'movement_pass_through', lambda engine, mover, other: True)
    c = move(e, 5)
    assert c is not None and c.movement_cost_ft == 15 and move(e, 4) is None


def test_plugin_hook_rejects_non_boolean_reply(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    install(monkeypatch, 'movement_pass_through', lambda engine, mover, other: 'difficult')
    with pytest.raises(ValueError):
        geometry(e, e.state.actors[S.ME])
