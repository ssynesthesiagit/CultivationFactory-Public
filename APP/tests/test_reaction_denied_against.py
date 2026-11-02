"""'Cannot take Reactions against you' only denies Reactions against the user (fight audit 2026-09-29: Jolt took every
Reaction away); 'cannot make Opportunity Attacks' is no_opportunity_attacks."""

from combat import typed_executor, unmaking
from tests.test_reaction_reach import _ctx, _engine, ME
from combat.gate2_runtime_content import AN


def _ids(actor):
    return {c.condition_id for c in actor.conditions.values()}


def test_against_you_denies_only_reactions_against_the_user():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_denied", "applies_to": "target", "on": "against you",
                                                        "evidence": "The target cannot take Reactions against you until the start of your next turn."}])
    assert "condition:typed.reaction_denied" not in _ids(foe)
    assert unmaking.reactions_denied_against(foe, me)


def test_plain_cannot_take_reactions_still_denies_all_and_opportunity_attacks_are_their_own():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_denied", "applies_to": "target", "evidence": "it cannot take Reactions"}])
    assert "condition:typed.reaction_denied" in _ids(foe)
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_denied", "applies_to": "target", "evidence": "it cannot make opportunity attacks"}])
    assert _ids(foe) & {"condition:typed.no_opportunity_attacks"} and "condition:typed.reaction_denied" not in _ids(foe)
