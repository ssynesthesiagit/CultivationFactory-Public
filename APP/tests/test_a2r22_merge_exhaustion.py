"""Merge seams keep immunity exceptions distinct from mandatory scene costs.

Table-level persistence for both callers lives in test_a2r22_review and
test_a2_reservoir_refinement; these regressions isolate their shared seam.
"""
import pytest

from combat import ext
from combat.ext import forged_exhaustion as exhaustion
from tests.test_auto_athletics import _engine, _me


@pytest.mark.parametrize("unavoidable", [False, True])
def test_immunity_exception_retains_veto_but_unavoidable_cost_skips_it(monkeypatch, unavoidable):
    engine = _engine([])
    actor = _me(engine)
    engine.typed_reaction_rows[actor.entity_id] = [
        {"block": "condition_immunity", "conditions": ["exhaustion"]}]
    calls = []
    original = ext.run_checkpoint

    def veto(name, *args, **kwargs):
        if name == "condition_application_attempt":
            calls.append(name)
            return [False]
        return original(name, *args, **kwargs)

    monkeypatch.setattr(ext, "run_checkpoint", veto)
    engine._apply_condition(actor, exhaustion.CONDITION_ID, "test:merge", actor.entity_id,
                            expires_on="UNTIL_REMOVED", data={"level": 1},
                            immune_bypass=True, unavoidable=unavoidable)
    assert exhaustion.level(actor) == int(unavoidable)
    assert len(calls) == int(not unavoidable)


def test_protected_cost_composes_with_immunity_exception_and_partial_recovery():
    engine = _engine([])
    actor = _me(engine)
    engine.typed_reaction_rows[actor.entity_id] = [
        {"block": "condition_immunity", "conditions": ["exhaustion"]}]
    exhaustion.set_level(engine, actor, 1, "test:cost", scene_locked_levels=1)
    assert exhaustion.level(actor) == exhaustion.locked_level(engine, actor) == 1
    exhaustion.add(engine, actor, 1, "test:exception", immune_bypass=True)
    assert exhaustion.level(actor) == 2
    before = actor.movement_remaining_ft
    exhaustion.add(engine, actor, 1, "test:ordinary")
    assert exhaustion.level(actor) == 2
    assert actor.movement_remaining_ft == before
    exhaustion.set_level(engine, actor, 0, "test:cure")
    assert exhaustion.level(actor) == exhaustion.locked_level(engine, actor) == 1
    assert actor.movement_remaining_ft == before + 5
