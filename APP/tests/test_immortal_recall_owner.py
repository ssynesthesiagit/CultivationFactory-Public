"""Body Recalls Life choices on an AI-to-manual turn transition."""
import pytest

from combat import posture
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, reload, turn, act, resolve
from tests.fixed_controller import force_primary

IMMORTAL = "tianxia.path.body_refining.feature.immortal_body"
STAMINA = "resource:core.stamina"


@pytest.mark.parametrize("stand", [True, False])
def test_manual_immortal_controls_recall_and_stand_after_ai_end_turn(tmp_path, stand):
    def seal(bundle):
        # No other Ask-me row should accidentally enroll the Immortal.
        for row in bundle.get("typed_reactions", []):
            row["ask"] = False

    def initiative(doc, aid):
        # Order LEFT, ALLY, RIGHT, so RIGHT ends immediately before LEFT.
        doc["ability_scores_and_statistics"]["initiative"] = {"bonus": {LEFT: 100, ALLY: 50, RIGHT: 1}[aid]}

    combat, table, mid = fight(
        tmp_path, [IMMORTAL], cl=20, left_resource="Stamina", ally=True,
        cause=[{"type": "damage", "flat": 1000, "damage_types": ["force"]}],
        bundle_edit=seal, sheet_edit=initiative,
    )
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers, target_id=LEFT))
    before = reload(combat, mid)
    assert before.state.actors[LEFT].current_hp == 0
    assert LEFT in before.typed_ask_reactors
    stamina = before.state.actors[LEFT].resources[STAMINA]
    menu = table.state(mid)["menu"]
    force_primary(combat, mid, RIGHT, menu["end_turn"])
    send = lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    recall = result["reaction"]
    assert recall["context"]["reactor_id"] == LEFT
    assert recall["context"]["reaction_source_id"] == "choice:needle.body_recalls_life"
    assert "Body Recalls Life" in str(recall)
    answer = {**recall["context"], "selection": "USE",
              "option_ids": [recall["choice"]["options"][0]["id"]]}
    result = send([answer])
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["context"]["reaction_source_id"] == "choice:needle.body_recalls_life_stand"
    assert "Body Recalls Life" in str(prompt)
    answer2 = {**prompt["context"], "selection": "USE" if stand else "DECLINE",
               "option_ids": [prompt["choice"]["options"][0]["id"]] if stand else []}
    assert send([answer, answer2])["status"] == "COMMITTED"
    fresh = CombatService(combat.source_root, tmp_path)
    actor = fresh._load_session(mid).engine.state.actors[LEFT]
    assert actor.current_hp == 20 and actor.life_state is None
    assert actor.resources[STAMINA] == stamina - 10
    assert bool(posture.prone_conditions(actor)) is not stand
    engine = fresh._load_session(mid).engine
    assert actor.movement_remaining_ft == engine._effective_speed(actor) - (5 if stand else 0)
