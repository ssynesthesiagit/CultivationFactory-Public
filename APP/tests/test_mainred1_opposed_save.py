"""Forced opposed saves retain real totals, explicit outcomes, and no next-roll state."""
import pytest

from combat import ext, typed_executor as te
from combat.ext.d20_rewrite import Holder, Rule, RULES
from tests.h1_support import ME, FOE, duel, script


@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("draws", [(20, 1), (1, 20)])
def test_forced_opposed_save_preserves_modifier_even_when_totals_agree(monkeypatch, outcome, draws):
    engine = duel("HUNGER_BASE_TASTE_THE_QI")
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    bonus = target.saving_throws["CHA"]
    rule = Rule("test_mainred1_outcome", "Training rewrite", rolls=("save",), when="any", op="choose",
        choose=lambda e, h, rc: rc.natural, outcome=outcome,
        finder=lambda e: [Holder(target, "test:mainred1", {}, "test:mainred1")], ai=lambda e, h, rc: True)
    ext.effects()
    monkeypatch.setitem(RULES, rule.kind, rule)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    script(engine, list(draws))
    result = te.resolve_opposed_check(ctx, target, {"kind": "cultivation"}, {"kind": "save", "ability": "CHA"})
    assert result.target.modifier == bonus
    assert result.target.total == result.target.natural_result + bonus
    assert result.outcome_override is (outcome == "failure")
    assert result.success is (outcome == "failure")
    assert not engine._typed_roll_outcome
    monkeypatch.delitem(RULES, rule.kind)
    script(engine, [1, 20])
    following = te.resolve_opposed_check(ctx, target, {"kind": "cultivation"}, {"kind": "save", "ability": "CHA"})
    assert following.outcome_override is None
    assert following.target.modifier == bonus
    assert not engine._typed_roll_outcome
