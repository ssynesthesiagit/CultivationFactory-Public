"""Sequential damage dice shared by typed settlement and attack plug-ins.

Red Execution and Empowered Technique return indexed replacements instead of
independent deltas against the original draw. The original RollRecord remains
immutable journal evidence; effective copies exist only during this transaction.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DieReplacement:
    """Replace current dice at their original indices, plus an optional flat bonus."""

    dice: dict[int, int]
    bonus: int = 0


def apply(roll, result):
    """Return an effective copy; integer replies retain additive adjustment semantics."""
    if result is None:
        return roll
    if type(result) is int:
        return roll.model_copy(update={'total': roll.total + result})
    if not isinstance(result, DieReplacement) or type(result.bonus) is not int:
        raise ValueError('damage adjustment requires an integer or DieReplacement')
    values = list(roll.dice)
    for index, value in result.dice.items():
        if type(index) is not int or not 0 <= index < len(values) or type(value) is not int or value <= 0:
            raise ValueError('damage replacement requires a valid die index and positive integer result')
        values[index] = value
    return roll.model_copy(update={'dice': tuple(values),
                                  'total': roll.total + sum(values) - sum(roll.dice) + result.bonus})


def settle(point, *args, roll):
    """Strict ordered dispatch: each provider receives the preceding effective roll."""
    from . import ext

    for provider in ext.subscribers(point):
        roll = apply(roll, provider(*args, roll))
    return roll
