"""Several damage_dice_reroll subscribers compose: an exact die selection never drops another subscriber's count."""
from types import SimpleNamespace

import combat.ext as ext
from combat import typed_executor as te
from combat.gate2_runtime_models import DiceSpec


class FakeRoll(SimpleNamespace):
    def model_dump(self, mode=None):
        return {'dice': list(self.dice), 'total': self.total}


def _ctx(original_dice):
    rolls = [FakeRoll(dice=tuple(original_dice), total=sum(original_dice), reason='DAMAGE:FAKE', roll_id='r0')]
    recorded = []

    def roll(spec, actor_id=None, reason=None, critical=False):
        out = FakeRoll(dice=(4,) * spec.count, total=4 * spec.count, reason=reason, roll_id=f'r{len(rolls)}')
        rolls.append(out)
        return out

    engine = SimpleNamespace(rolls=rolls, roller=SimpleNamespace(roll=roll),
                             _record_roll=lambda r: recorded.append(r), _append_event=lambda *a, **k: None)
    ctx = SimpleNamespace(engine=engine, actor=SimpleNamespace(entity_id='actor'), damage_source='FAKE',
                          targets=(), damage_metadata=lambda: {})
    return ctx, rolls, recorded


def _run(monkeypatch, subscribers, original_dice=(1, 5, 3, 6, 2)):
    monkeypatch.setitem(ext._HOOKS, 'damage_dice_reroll', list(subscribers))
    ctx, rolls, recorded = _ctx(original_dice)
    spec = DiceSpec(count=len(original_dice), sides=6, modifier=0)
    return te._rerolled_damage_dice(ctx, spec, {}, [], 0), recorded


def test_exact_selection_keeps_other_subscribers_count(monkeypatch):
    # Mutable Damage picks die index 1 (value 5); Seven-Hammer-style count asks for 2 dice in total.
    subs = [lambda ctx, effect, kinds, count: {'indices': [1]},
            lambda ctx, effect, kinds, count: 2]
    adjustment, recorded = _run(monkeypatch, subs)
    # Two dice are rerolled (index 1 plus the lowest-valued other die, index 0 with value 1): 4 + 4 - (1 + 5) = 2.
    assert len(recorded) == 1 and len(recorded[0].dice) == 2
    assert adjustment == 8 - (1 + 5)


def test_count_only_subscriber_still_rerolls_its_count(monkeypatch):
    adjustment, recorded = _run(monkeypatch, [lambda ctx, effect, kinds, count: 2])
    assert len(recorded) == 1 and len(recorded[0].dice) == 2
    assert adjustment == 8 - (1 + 2)


def test_selection_larger_than_count_is_kept_exactly(monkeypatch):
    subs = [lambda ctx, effect, kinds, count: {'indices': [1, 3]},
            lambda ctx, effect, kinds, count: 1]
    adjustment, recorded = _run(monkeypatch, subs)
    assert len(recorded) == 1 and len(recorded[0].dice) == 2
    assert adjustment == 8 - (5 + 6)
