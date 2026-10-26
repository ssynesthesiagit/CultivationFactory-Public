"""Both sides of the INS7ERB6 keyword seams remain usable together.

Table-level ability behavior is covered by the existing INS7E, Athletics and
Vessel regressions; these checks isolate the two conflicting shared contracts.
"""
from types import SimpleNamespace

import pytest

from combat.ext import granted_movement
from combat.typed_executor import FlatAmount, _roll


@pytest.mark.parametrize('preserve_sign,expected', [(True, -3), (False, 0)])
def test_signed_flat_roll_accepts_damage_replacement_context(preserve_sign, expected):
    assert _roll(None, FlatAmount(modifier=-3), 'SUPPORT', preserve_sign=preserve_sign,
                 damage_effect={}, damage_kinds=[]) == expected


@pytest.mark.parametrize('pause', [False, True])
def test_nonprovoking_grant_forwards_motion_context_and_restores_scope(pause):
    actor = SimpleNamespace(entity_id='owner', movement_remaining_ft=30,
                            turn_flags={'oa_free_ft': 5, 'spark_step_ignore_oa_from': 'old'})
    engine = SimpleNamespace(state=SimpleNamespace(actors={'owner': actor, 'foe': object()}))
    candidate = SimpleNamespace(movement_cost_ft=5)
    context = {'feature_id': 'test:motion'}
    intent = object()
    calls = []

    def resolve(mover, route, submitted, *, granted_ft, movement_context):
        calls.append((mover, route, submitted, granted_ft, movement_context))
        assert engine._granted_movement_oa == ('owner', ('owner', 'foe'))
        assert mover.movement_remaining_ft == 5
        if pause:
            raise ValueError('choice required')

    engine._resolve_movement = resolve
    if pause:
        with pytest.raises(ValueError, match='choice required'):
            granted_movement.move(engine, actor, candidate, intent, 5, [],
                                  nonprovoking=True, movement_context=context)
    else:
        granted_movement.move(engine, actor, candidate, intent, 5, [],
                              nonprovoking=True, movement_context=context)
    assert calls == [(actor, candidate, intent, 5, context)]
    assert actor.movement_remaining_ft == 30
    assert actor.turn_flags == {'oa_free_ft': 5, 'spark_step_ignore_oa_from': 'old'}
    assert engine._granted_movement_oa is None
    assert engine._granted_movement_budget is None
