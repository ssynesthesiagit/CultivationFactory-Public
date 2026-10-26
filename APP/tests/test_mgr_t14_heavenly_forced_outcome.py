"""Save adjustment timing follows a forced save outcome, not only the raw total.

A forced outcome (for example Crown Opening) is recorded on the exact roll at draw
time and consumed after the adjustments. The after_failure window must read it:
a forced success never opens the window, and a forced failure opens it even when
the numeric total passes.
"""
from types import SimpleNamespace

from combat import ext
from combat.save_adjustments import adjust, declared_outcome


class Roll(SimpleNamespace):
    def model_copy(self, update):
        return Roll(**{**vars(self), **update})


def engine_with(forced=None):
    return SimpleNamespace(d20_context=lambda: {}, _d20_forced_native_saves=forced or {})


def run(monkeypatch, forced, total, dc=12):
    """Run the real adjust(); record which phases the after_failure provider saw."""
    seen = []

    def run_strict(name, *args):
        if name == 'save_roll_adjustment':
            seen.append(args[6])  # phase
            return [1]
        return []

    monkeypatch.setattr(ext, 'run_strict', run_strict)
    target = SimpleNamespace(entity_id='ally')
    roll = Roll(roll_id='r1', total=total, modifier=0)
    engine = engine_with({'r1': {'target_id': 'ally', 'outcome': forced, 'source_id': 'crown'}} if forced else None)
    result = adjust(engine, target, 'WIS', dc, roll, 'save:test', context={}, phase=None)
    return seen, result


def test_forced_success_with_failing_total_never_opens_after_failure(monkeypatch):
    seen, _ = run(monkeypatch, 'success', total=5)
    assert seen == ['before_outcome']


def test_forced_failure_with_passing_total_opens_after_failure(monkeypatch):
    seen, _ = run(monkeypatch, 'failure', total=15)
    assert seen == ['before_outcome', 'after_failure']


def test_unforced_failing_and_passing_totals_keep_the_raw_total_gate(monkeypatch):
    assert run(monkeypatch, None, total=5)[0] == ['before_outcome', 'after_failure']
    assert run(monkeypatch, None, total=15)[0] == ['before_outcome']


def test_declared_outcome_is_read_only_and_roll_scoped():
    roll = Roll(roll_id='r1', total=5, modifier=0)
    forced = {'r1': {'target_id': 'ally', 'outcome': 'success', 'source_id': 'crown'}}
    engine = SimpleNamespace(_d20_forced_native_saves=forced)
    assert declared_outcome(engine, SimpleNamespace(entity_id='ally'), roll) == 'success'
    assert declared_outcome(engine, SimpleNamespace(entity_id='foe'), roll) is None
    assert declared_outcome(engine, SimpleNamespace(entity_id='ally'), Roll(roll_id='r2', total=5, modifier=0)) is None
    assert forced == {'r1': {'target_id': 'ally', 'outcome': 'success', 'source_id': 'crown'}}
