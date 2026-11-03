"""MOVEPASS1 review fix: only the Incapacitated condition (and the named states that include it) opens a route through a hostile.

Stone Womb Preservation's shell (stone_shell) also takes away Actions, but it is not Incapacitated, so a hostile wearing it must
still block the mover. Synthetic fight from tests/lock8_support; runs on public CI.
"""
import pytest
from combat import movement_passage
from combat.gate2_runtime_models import Position
from tests import lock8_support as S


def corridor(e):
    e.grid.blocked = {(x, y) for x in range(e.grid.width) for y in range(e.grid.height) if y != 6}
    e.grid.base_movement_cost.clear()
    e.grid.qi_hazard.clear()
    e._wall_base = (frozenset(e.grid.blocked), frozenset(), frozenset(), {})


def move(e, x):
    return next((c for c in e.legal_candidates()
                 if c.kind.value == 'MOVE' and c.destination == Position(x=x, y=6)), None)


@pytest.mark.parametrize('condition_id', ['incapacitated', 'stunned', 'paralyzed', 'petrified', 'unconscious'])
def test_named_incapacitating_conditions_open_the_hostile_space(condition_id):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    foe = e.state.actors[S.FOE]
    e._apply_condition(foe, 'condition:typed.' + condition_id, 'test:movepass:named', S.ME, expires_on='UNTIL_REMOVED')
    assert movement_passage.incapacitated(foe)
    assert move(e, 5) is not None


def test_explicit_incapacitated_marker_in_condition_data_counts():
    # Golden statue, bone cocoon and Fold Prison carry their own rule rows, labelled "Incapacitated" by their text.
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    foe = e.state.actors[S.FOE]
    e._apply_condition(foe, 'condition:typed.stone_shell', 'test:movepass:marker', S.ME, expires_on='UNTIL_REMOVED',
                       data={'rule': {'counts_as_incapacitated': True, 'no_actions': True, 'speed_zero': True}})
    assert movement_passage.incapacitated(foe)
    assert move(e, 5) is not None


def test_stone_shell_takes_actions_but_is_not_incapacitated_so_the_hostile_still_blocks():
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6))
    corridor(e)
    foe = e.state.actors[S.FOE]
    e._apply_condition(foe, 'condition:typed.stone_shell', 'test:movepass:stone_shell', S.ME, expires_on='UNTIL_REMOVED')
    assert not movement_passage.incapacitated(foe)
    assert move(e, 5) is None
