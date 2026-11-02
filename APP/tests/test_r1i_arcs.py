import pytest
from combat import typed_executor as te
from combat.ext import arcs
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from tests.test_riders_lane1 import _engine, _bundle, _mark, LASH, ME, AN, F1


@pytest.mark.parametrize("count", [1, 4])
@pytest.mark.parametrize("selection", ["DECLINE", "USE"])
def test_optional_arc_offers_single_candidate_and_respects_decline(count, selection):
    engine = _engine(_bundle(LASH), {F1: (5, 6)})
    _mark(engine, F1, "Conductive")
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Lightning Lash: Arc")
    intent = ActionIntent(intent_id="arc-test", actor_id=ME, candidate_id="test", decision_id="test", state_version=engine.state.state_version)
    seen = []
    def answer(request):
        if "extension_choice" in request:
            seen.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection=selection,
                                option_ids=(F1,) if selection == "USE" else ()), None
    engine.set_reaction_provider(answer)
    target = engine.state.actors[AN]
    ctx = te.Context(engine, engine.state.actors[ME], action, intent, {"numbers": {"pb": 4}}, [target], target, {})
    hp = engine.state.actors[F1].current_hp
    arcs.arc(ctx, {"type": "arc", "range_ft": 5, "needs_conductive": True, "count": count,
                   "effects": [{"type": "arc_damage", "basis": "pb"}]})
    assert len(seen) == 1
    assert seen[0]["extension_choice"]["allow_decline"]
    assert seen[0]["extension_choice"]["minimum_selections"] == 0
    assert hp - engine.state.actors[F1].current_hp == (4 if selection == "USE" else 0)
