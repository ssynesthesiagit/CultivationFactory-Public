"""RW002 verifies the native Bend the Blade behavior whose rider is retired."""
import json

from tests.auto_worker1_support import LEFT, RIGHT, fight, act, turn
from tests.h1_support import ROOT
from tests.test_auto2_flowing_river import P, RESPONSE, FOCUS, reload, settle, decline_steps
from tests.test_double_current_method import acquired, CHOICE


def test_bend_the_blade_redirects_committed_attack_and_has_no_rider(tmp_path):
    from tests.auto_worker1_support import ALLY

    bend = P + "BEND_THE_BLADE"
    c, t, match_id = fight(tmp_path, [RESPONSE, P + "HAND_ON_THE_WRIST", bend],
        left_score=50, sheet_edit=acquired, ally=(), spheres=["tianxia.sphere.flowing_river"])
    turn(t, match_id, RIGHT)
    before = reload(c, match_id)

    def choose(prompt):
        kind = prompt["context"]["reaction_source_id"]
        if kind == CHOICE:
            return [prompt["choice"]["options"][0]["id"]]
        if kind == "choice:needle.river_bend_target":
            return [ALLY]
        return decline_steps(prompt)

    _, prompts = settle(lambda answers: act(t, match_id, ".weapon.bi_shou", answers, target_id=LEFT), choose)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.river_bend_target" for p in prompts)
    loaded = reload(c, match_id)
    assert loaded.state.actors[LEFT].resources[FOCUS] == before.state.actors[LEFT].resources[FOCUS] - 1
    redirected = [e for e in loaded.events if e.event_type == "PASSIVE_TRIGGERED"
                  and e.source_definition_id == "passive:" + bend]
    assert len(redirected) == 1 and redirected[0].target_ids == (RIGHT, ALLY)
    assert len([e for e in loaded.events if e.event_type == "ATTACK_ROLLED"]) == 1

    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    assert authority["mechanics"][bend]["riders"] == []
