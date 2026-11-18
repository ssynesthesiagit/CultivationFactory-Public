"""Short-lived damage rows must not inherit a different recipient's roll."""
from types import SimpleNamespace

from combat import typed_executor as executor


def test_distinct_temporary_damage_rows_roll_separately(monkeypatch):
    rolls = []
    monkeypatch.setattr(executor, "_effect_dice", lambda ctx, effect: None)
    monkeypatch.setattr(executor, "damage_choices", lambda *args: [])
    monkeypatch.setattr(executor, "_damage_dice", lambda ctx, dice, effect, kinds: dice)

    def roll(ctx, spec, reason, **kwargs):
        total = len(rolls) + 1
        rolls.append((reason, total))
        return total

    monkeypatch.setattr(executor, "_roll", roll)
    monkeypatch.setattr("combat.ext.run_strict", lambda *args: [])
    ctx = SimpleNamespace(damage_cache={}, targets=[object()], target=None, typed={},
                          engine=SimpleNamespace(), critical_hit=False, numbers={},
                          dice=lambda *args, **kwargs: None)
    first = {"type": "damage", "flat": 1}
    first_total = executor._damage_roll(ctx, first)[0]
    del first
    second = {"type": "damage", "flat": 2}
    second_total = executor._damage_roll(ctx, second)[0]
    assert rolls == [("DAMAGE", 1), ("DAMAGE", 2)]
    assert (first_total, second_total) == (1, 2)
