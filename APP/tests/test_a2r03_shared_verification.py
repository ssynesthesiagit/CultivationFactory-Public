"""Regressions for shared failures exposed by the protected A2R03 run."""
import pytest

# The ability this file needs; named here so the public export does not pull
# tests/test_a11_contests.py (whose import closure reads repository history).
HUNGER = "HUNGER_BASE_TASTE_THE_QI"


def test_sure_grip_has_one_compiled_row_for_climbing_and_retaining_grapples():
    from combat.ext import athletics, athletics_grip_lungs
    from tests.h1_support import duel, ME

    engine = duel(["TAL_ATHLETICS_SURE_GRIP"])
    actor = engine.state.actors[ME]
    rows = [r for r in engine.typed_passive_rows[ME]
            if r.get("feature_id") == "TAL_ATHLETICS_SURE_GRIP"]
    assert len(rows) == 1
    assert athletics.athletics_climbing(engine, actor)["climb_check_modes"] == ["ADVANTAGE"]
    assert athletics_grip_lungs.maintain_grip(engine, actor) is True
    assert athletics_grip_lungs.climb_and_fall(engine, actor, "STR", "Athletics",
                                             {"prevent_falling"}) == "ADVANTAGE"


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_explicit_opposed_save_outcome_survives_when_numeric_totals_already_agree(monkeypatch, outcome):
    from combat import ext, typed_executor as te
    from combat.ext.d20_rewrite import Rule, Holder, RULES
    from tests.h1_support import duel, ME, FOE, script

    engine = duel([HUNGER])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    rule = Rule("test_agreeing_outcome", "Training rewrite", rolls=("save",),
                when="any", op="choose", choose=lambda e, h, rc: rc.natural,
                outcome=outcome,
                finder=lambda e: [Holder(target, "test:rewrite", {}, "test:rewrite")],
                ai=lambda e, h, rc: True)
    ext.effects()
    monkeypatch.setitem(RULES, rule.kind, rule)
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    script(engine, [1, 20] if outcome == "success" else [20, 1])
    result = te.resolve_opposed_check(ctx, target, {"kind": "cultivation"},
                                     {"kind": "save", "ability": "CHA"})
    assert result.success is (outcome == "failure")
    assert result.outcome_override is (outcome == "failure")
    assert result.target.modifier == target.saving_throws["CHA"]


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_save_notifications_use_the_declared_outcome_before_numeric_totals(monkeypatch, outcome):
    from combat import typed_executor as te
    from tests.h1_support import duel, ME, FOE
    from tests.test_lock_choices import install

    engine = duel([])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {}, [target], target)
    seen = []
    install(monkeypatch, "after_save", lambda c, s, a, n, failed: seen.append(failed))
    engine._typed_roll_outcome = {FOE: outcome}
    # Feed the opposite numeric result: downstream riders must receive the
    # declared result, not the unadjusted comparison with the opposing roll.
    failed = te.settle_typed_save(ctx, target, "CHA", None, outcome == "success", set(), set(), 0)
    assert failed is (outcome == "failure")
    assert seen == [outcome == "failure"]
