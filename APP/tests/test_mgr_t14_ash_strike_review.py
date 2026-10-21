"""Review regressions for legacy no-cost variants and settled table consent."""
import pytest

from combat.ext.foundations3 import defer_declared_strike
from tests.test_mgr_t14_ash_strike import setup, strike, packets, STRIKE, POOL
from tests.worker2_support import OWNER, FOE, reload


def test_paid_value_hook_documents_arguments_and_inert_contract():
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "combat/ext/__init__.py"
    doc = ast.get_docstring(ast.parse(path.read_text()))
    for text in ("foundation_paid_value_bonus(ctx, target, source, signed_value, payment_event)",
                 "signed_value the raw integer base", "Providers are pure",
                 "no subscribers leaves the signed base unchanged"):
        assert text in doc


def test_owned_strike_variant_without_recorded_upfront_cost(tmp_path):
    _, _, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values()
                  if a.parameters.get("typed", {}).get("ash_strike_declared"))
    # Legacy optional modifiers did not always record the printed resource cost.
    # Reconstruct that input, retaining an unrelated technique cost verbatim.
    typed = {**action.parameters["typed"], "effects": [
        {"type": "foundations3_ash_strike", "effects": []}]}
    action = action.model_copy(update={"costs": (("resource:test.other", 2),),
        "parameters": {**action.parameters, "typed": typed}})
    result = defer_declared_strike(action, {"owned_ids": [STRIKE]})
    assert result.costs == (("resource:test.other", 2),)
    assert result.parameters["typed"]["ash_strike_declared"] == 1
    assert result.parameters["typed"]["effects"] == []


@pytest.mark.parametrize("choice", [None, "slashing"])
def test_paid_and_declined_hit_survive_table_reload(tmp_path, choice):
    combat, table, mid = setup(tmp_path)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    prompts = strike(combat, table, mid, choice)
    engine = reload(tmp_path, mid)
    assert prompts
    assert engine.state.actors[FOE].current_hp < hp
    assert engine.state.actors[OWNER].resources[POOL] == (1 if choice is None else 0)
    assert len(packets(engine)) == (0 if choice is None else 1)
    if choice:
        assert packets(engine)[0].payload["hp_damage"] == 1
        assert packets(engine)[0].payload["damage_type"] == "SLASHING"
