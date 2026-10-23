"""Native delivery evidence for the supported Show Your Hand branch.

This does not close Ignore the Fool's non-attack harmful-effect trigger.
"""
import pytest

from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

J = "tianxia.talent.jester."


@pytest.mark.parametrize("proposition,delivers", [("Show Your Hand", True), ("Strike the Fool", False)])
def test_learned_punchline_uses_native_foil_after_cold_reload(tmp_path, proposition, delivers):
    combat, table, mid = fixture(
        tmp_path, [J + "excellent_idea"], owner_dc=23,
        foe_sheet=sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]), named=True,
    )
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Set the Scene: " + proposition, target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    assert any(c.source_actor_id == OWNER and "foil_" in c.condition_id
               for c in before.state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, "Calming Heart Pill").candidate_id,
                     {"reaction:typed." + J + "excellent_idea": "first"})
    after = reload(tmp_path, mid)
    saves = [e for e in after.events if e.event_type == "SAVE_ROLLED"
             and e.payload.get("reason") == "SAVE:" + J + "excellent_idea:WIS"]
    assert bool(saves) == delivers
    if delivers:
        assert len(saves) == 1 and saves[0].payload["dc"] == 23
        assert any(p["context"]["reactor_id"] == OWNER for p in prompts)
        assert not after.state.actors[OWNER].reaction_available
    assert any(c.source_actor_id == OWNER and "foil_" in c.condition_id
               for c in after.state.actors[FOE].conditions.values()) != delivers
