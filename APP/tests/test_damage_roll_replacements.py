"""Indexed damage replacement contract preserves the recorded draw and flat bonuses."""
import pytest

from combat.damage_roll_replacements import DieReplacement, apply, settle
from combat.gate2_runtime_models import RollRecord


def original():
    return RollRecord(roll_id='damage', counter_start=0, counter_end=2, expression='2d6+3',
                      actor_id='actor:test', reason='DAMAGE:test', dice=(1, 2), modifier=3, total=6)


def test_sequential_replacements_keep_identity_and_original_journal(monkeypatch):
    from combat import ext
    recorded = original()
    seen = []

    def first(roll):
        return DieReplacement({0: 6}, bonus=2)

    def second(roll):
        seen.append((roll.roll_id, roll.dice, roll.total))
        return DieReplacement({0: 4})

    monkeypatch.setattr(ext, 'subscribers', lambda point: (first, second))
    effective = settle('test', roll=recorded)
    assert seen == [('damage', (6, 2), 13)]
    assert effective.dice == (4, 2) and effective.total == 11
    assert recorded.dice == (1, 2) and recorded.total == 6
    assert effective.roll_id == recorded.roll_id


def test_no_provider_preserves_roll_and_additive_adjustments_keep_dice(monkeypatch):
    from combat import ext
    recorded = original()
    monkeypatch.setattr(ext, 'subscribers', lambda point: ())
    assert settle('test', roll=recorded) is recorded
    effective = apply(recorded, -2)
    assert effective.dice == recorded.dice and effective.total == 4


@pytest.mark.parametrize('reply', [True, 1.5, DieReplacement({2: 1}), DieReplacement({0: 0}),
                                  DieReplacement({False: 2}), DieReplacement({0: 2}, bonus=1.5)])
def test_invalid_replacements_fail_transaction(reply):
    with pytest.raises(ValueError):
        apply(original(), reply)
