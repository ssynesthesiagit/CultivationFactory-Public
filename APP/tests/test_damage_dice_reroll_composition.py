"""Several damage_dice_reroll subscribers compose: an exact die selection never drops another subscriber's count."""
from types import SimpleNamespace

import combat.ext as ext
from combat import typed_executor as te
from combat.gate2_runtime_models import DiceSpec


class FakeRoll(SimpleNamespace):
    def model_dump(self, mode=None):
        return {'dice': list(self.dice), 'total': self.total}


def _run(monkeypatch, answers, original_dice=(1, 5, 3, 6, 2)):
    """Drive the real _rerolled_damage_dice with the given subscriber answers (ext.run is the only hook seam)."""
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
    monkeypatch.setattr(ext, 'run', lambda point, *args, **kwargs: list(answers) if point == 'damage_dice_reroll' else [])
    spec = DiceSpec(count=len(original_dice), sides=6, modifier=0)
    return te._rerolled_damage_dice(ctx, spec, {}, [], 0), recorded


def test_exact_selection_keeps_other_subscribers_count(monkeypatch):
    # Mutable Damage picks die index 1 (value 5); a Seven-Hammer-style count asks for 2 dice in total.
    adjustment, recorded = _run(monkeypatch, [{'indices': [1]}, 2])
    # Two dice are rerolled: index 1 plus the lowest-valued other die (index 0, value 1). 8 - (1 + 5) = 2.
    assert len(recorded) == 1 and len(recorded[0].dice) == 2
    assert adjustment == 8 - (1 + 5)


def test_count_only_subscriber_still_rerolls_its_count(monkeypatch):
    adjustment, recorded = _run(monkeypatch, [2])
    assert len(recorded) == 1 and len(recorded[0].dice) == 2
    assert adjustment == 8 - (1 + 2)


def test_selection_larger_than_count_is_kept_exactly(monkeypatch):
    adjustment, recorded = _run(monkeypatch, [{'indices': [1, 3]}, 1])
    assert len(recorded) == 1 and len(recorded[0].dice) == 2
    assert adjustment == 8 - (5 + 6)
