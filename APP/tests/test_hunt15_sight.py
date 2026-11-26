"""Sight-qualified reactions must use the triggering creature's visibility."""
import pytest
from combat import senses
from tests.hunt15_support import LEFT, RIGHT, act, action_sender, fight, reload, turn

RESPONSE = "TAL_FLOWING_RIVER_FLOWING_RESPONSE"


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_unseen_melee_attacker_does_not_offer_flowing_response(tmp_path, ai, legacy):
    combat, table, mid = fight(tmp_path, [RESPONSE], legacy_reactions=legacy, effects=[
        {"type": "condition", "condition": "invisible", "applies_to": "self", "expires_on": "UNTIL_REMOVED"}])
    turn(table, mid, RIGHT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    act(table, mid, "end")
    act(table, mid, "end")
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == RIGHT
    assert any(c.condition_id == "condition:typed.invisible" for c in engine.state.actors[RIGHT].conditions.values())
    assert not senses.sees_hidden(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    row = next(r for r in engine.typed_reaction_rows[LEFT] if r["feature_id"] == RESPONSE)
    assert row.get("requires_sight") is (None if legacy else True)
    result = action_sender(combat, table, mid, ".weapon.bi_shou", ai=ai)([])
    assert result["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == RIGHT for e in engine.events)
    assert not any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == RESPONSE for e in engine.events)


def test_visible_attacker_still_offers_flowing_response(tmp_path):
    combat, table, mid = fight(tmp_path, [RESPONSE])
    turn(table, mid, RIGHT)
    result = act(table, mid, ".weapon.bi_shou")
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["reaction"] == "Flowing Response"
