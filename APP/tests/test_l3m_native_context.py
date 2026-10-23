"""Integration checks for round18 helpers consuming round3 native contexts.

Existing Hunt8 table tests cover Soul-Lamp prompts, answers, commits and reload.
These checks guard scratch ownership and metadata in the shared raw-save helper.
"""
import pytest
from types import SimpleNamespace

from combat.ext import ControllerPause
from combat.ext.d20_rewrite import context_of, saving_throw_context
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install


def test_raw_save_uses_native_context_and_unwinds_nested_labels(monkeypatch):
    seen = []
    install(monkeypatch, "d20_result", lambda e, r, i: seen.append(context_of(e, r)))
    engine, _ = _engine([])
    methods = engine._roll_save, engine._resolve_attack_spec
    with saving_throw_context(engine, engine.state.actors[AN], "CON", 20, "soul_lamp",
                              source_name="Soul-Lamp Continuity"):
        engine.roller.d20(modifier=0, actor_id=AN, reason="SAVE:soul_lamp:CON")
        with pytest.raises(ControllerPause):
            with saving_throw_context(engine, engine.state.actors[ME], "DEX", 12, "test:child",
                                      source_name="Child save"):
                engine.roller.d20(modifier=0, actor_id=ME, reason="SAVE:test:child:DEX")
                raise ControllerPause("choose")
        engine.roller.d20(modifier=0, actor_id=AN, reason="SAVE:soul_lamp:CON")
    assert [(c.dc, c.source_id, c.source_name) for c in seen] == [
        (20, "soul_lamp", "Soul-Lamp Continuity"), (12, "test:child", "Child save"),
        (20, "soul_lamp", "Soul-Lamp Continuity")]
    assert engine.d20_context() is None
    assert "_d20_source_label" not in engine.__dict__
    assert "_d20_frames" not in engine.__dict__
    assert (engine._roll_save, engine._resolve_attack_spec) == methods


def test_shared_escape_resolver_exposes_native_dc(monkeypatch):
    from combat.ext.escape_checks import resolve_escape_check

    seen = []
    install(monkeypatch, "d20_result", lambda e, r, i: seen.append(e.d20_context(r)))
    engine, _ = _engine([])
    ctx = SimpleNamespace(engine=engine, actor=engine.state.actors[ME],
                          source="test:thread_escape", numbers={})
    resolve_escape_check(ctx, {}, 17, [])
    context, = seen
    assert context["kind"] == "check" and context["dc"] == 17
    assert context["source_id"] == "test:thread_escape"
    assert context["actor_id"] == ME and context["target_id"] == ME
    assert engine.d20_context() is None
