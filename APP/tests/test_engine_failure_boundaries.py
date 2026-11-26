"""A paused or failed damage collection must not leak partial engine context.

The resolution tests interrupt the earliest callbacks, before any gameplay effect executes.
"""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from combat import ext, typed_executor
from combat import action_geometry, shot_geometry


def context(engine, source, resolution):
    """A real typed_executor.Context, so dispatch meets every field it reads (attack_damage_context, ...). Its actor,
    action and intent stay empty: the geometry and collection they feed are replaced below, and effect_source gives
    Context.source without an action."""
    return typed_executor.Context(engine, None, None, None, {}, [], effect_source=source, effect_resolution=resolution)


@pytest.mark.parametrize("stage", ["request", "collect"])
@pytest.mark.parametrize("failure_type", [ValueError, ext.ControllerPause])
def test_early_damage_instance_failure_restores_resolution_context(monkeypatch, stage, failure_type):
    prior_instance = [{"type": "prior", "amount": 1}]
    engine = SimpleNamespace(_effect_resolution_mode="ordinary", _typed_damage_instance=prior_instance)
    context_ = context(engine, "delayed-source", "delayed")
    failure = failure_type("interrupted before effect dispatch")

    def interrupt(*_):
        raise failure

    monkeypatch.setattr(ext, "has", lambda _: True)
    monkeypatch.setattr(ext, "run", interrupt if stage == "request" else lambda *_: [True])
    monkeypatch.setattr(typed_executor, "_collect_damage_instance", interrupt)
    with pytest.raises(failure_type) as result:
        typed_executor.run_effects(context_, [])
    assert result.value is failure
    assert engine._effect_resolution_mode == "ordinary"
    assert engine._typed_damage_instance is prior_instance


def test_effect_dispatch_and_nested_resolution_restore_their_own_context(monkeypatch):
    original = [{"type": "prior", "amount": 1}]
    engine = SimpleNamespace(_effect_resolution_mode="ordinary", _typed_damage_instance=original, events=[])
    outer = context(engine, "outer", "delayed")
    inner = context(engine, "inner", "ordinary")
    observations = []
    monkeypatch.setattr(ext, "has", lambda _: True)
    monkeypatch.setattr(ext, "run", lambda *_: [True])
    monkeypatch.setattr(ext, "iter_strict_all", lambda *_: ())
    monkeypatch.setattr(action_geometry, "attack", lambda *_: nullcontext())
    monkeypatch.setattr(shot_geometry, "attack_scope", lambda *_: nullcontext())
    monkeypatch.setattr(typed_executor, "_defeat_chain", lambda *_: nullcontext())
    monkeypatch.setattr(typed_executor, "_moment_scope", lambda *_: nullcontext())
    monkeypatch.setattr(typed_executor, "_collect_damage_instance", lambda ctx, _: [ctx.source])

    def resolve(ctx, effects):
        observations.append((ctx.source, engine._effect_resolution_mode, tuple(engine._typed_damage_instance)))
        if ctx is outer:
            typed_executor.run_effects(inner, [])
            observations.append(("outer-restored", engine._effect_resolution_mode, tuple(engine._typed_damage_instance)))

    monkeypatch.setattr(typed_executor, "_run_effects_in_chain", resolve)
    typed_executor.run_effects(outer, [])
    assert observations == [("outer", "delayed", ("outer",)), ("inner", "ordinary", ("inner",)),
                            ("outer-restored", "delayed", ("outer",))]
    assert engine._effect_resolution_mode == "ordinary"
    assert engine._typed_damage_instance is original
