"""Storm-Heart table choices with legal Charges and interrupted-strike controls.

riders/c13 (14cd285f, C13r3.review.md) requires hostile precharging by a
real hit. lock7-punishment-aegis (e48f3767, L7aegis2.review.md) stops the
strike when a pre-effect paralyzes its attacker. Both reviews approve the lanes.
"""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, charge_setup, commit_charge, immobilize_on_action, OWNER, FOE
from tests.test_auto_martial import AXE_KIT

STORM = "TAL_LIGHTNING_STORM_HEART_ENGINE"


@pytest.mark.parametrize("off_turn,auto_turn", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("decline", [False, True])
@pytest.mark.parametrize("immobilized", [None, "grappled", "restrained", "pinned"])
def test_storm_step_is_immediate_table_choice_and_reload(tmp_path, off_turn, auto_turn, decline, immobilized):
    talents = [STORM, "TAL_LIGHTNING_CONDUCTIVE_STRIKE" if off_turn else "TAL_LIGHTNING_CRACKLING_ARROW"]
    def setup(bundles):
        charge_setup(bundles)
        immobilize_on_action("Setup Charge Hit", immobilized)(bundles)
    combat, table, mid, send, commit = fixture(tmp_path, talents, foe_ac=0, owner_kit=AXE_KIT, seed="R1I-CLAW",
        bundle_transform=setup)
    commit_charge(table, mid, send, FOE)
    if off_turn:
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != FOE:
            commit(table.state(mid)["menu"]["end_turn"])
        cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 4, "y": 8})
    else:
        cid = candidate(table, mid, "Lightning Lash: Jolt", FOE)
    if auto_turn:
        force_ai_candidate(combat, mid, FOE if off_turn else OWNER, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, seen = [], []
    for _ in range(12):
        result = send(cid, answers, auto=auto_turn)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        source = p["context"]["reaction_source_id"]
        seen.append(source)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        a = {**p["context"], "selection": "USE"}
        if source.endswith("storm_heart"):
            assert "consumes the Charge on" in p["moment"] and "Owner" in p["moment"]
            a["option_ids"] = ["move"]
        elif source.endswith("storm_heart_step"):
            assert "Storm-Heart Engine" in p["moment"] and "Owner" in p["moment"]
            assert ("Opportunity" in p["moment"] if off_turn else "Lightning Lash" in p["moment"]), p["moment"]
            if decline:
                a["selection"] = "DECLINE"
            else:
                option = next(o for o in p["choice"]["options"] if o["id"] == "cell:2,6")
                assert "Move to (2, 6), 5 feet" == option["label"]
                a["option_ids"] = [option["id"]]
        elif p.get("choice"):
            a["option_ids"] = [p["choice"]["options"][0]["id"]]
        answers.append(a)
    assert result["status"] == "COMMITTED", result
    assert ("choice:needle.storm_heart_step" in seen) == (immobilized is None)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[OWNER]
    assert owner.position.model_dump(mode="json") == (before["actors"][OWNER]["position"] if decline or immobilized else {"x": 2, "y": 6})
    if immobilized:
        if immobilized != "speed_zero":
            assert any(c.condition_id == "condition:typed." + immobilized for c in owner.conditions.values())
        assert loaded.engine._effective_speed(owner) == 0
    assert owner.movement_remaining_ft == before["actors"][OWNER]["movement_remaining_ft"]
    assert not owner.turn_flags.get("oa_free_ft")
    recent = [e for e in loaded.engine.events if e.sequence > before["event_sequence"]]
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id != OWNER for e in recent)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_storm_step_respects_effective_zero_speed_off_turn(tmp_path):
    test_storm_step_is_immediate_table_choice_and_reload(tmp_path, True, True, False, "speed_zero")


def test_ai_storm_heart_body_moves_immediately_without_prompt(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [STORM, "TAL_LIGHTNING_CRACKLING_ARROW",
                                                        "TAL_LIGHTNING_LIGHTNING_GOD_BODY"], bundle_transform=charge_setup)
    commit(candidate(table, mid, "Lightning-God Body"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit_charge(table, mid, send, FOE)
    cid = candidate(table, mid, "Lightning Lash: Jolt", FOE)
    force_ai_candidate(combat, mid, OWNER, cid)
    before = combat._load_session(mid).engine.state.actors[OWNER].model_copy(deep=True)
    assert send(cid, auto=True)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[OWNER]
    assert owner.position != before.position
    assert owner.movement_remaining_ft == before.movement_remaining_ft
    assert not owner.turn_flags.get("oa_free_ft")
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_storm_step_paralyzed_during_triggering_action_commit_reload(tmp_path):
    """lock7-punishment-aegis, approved L7aegis2.review.md: no strike while Paralyzed."""
    def setup(bundles):
        charge_setup(bundles)
        immobilize_on_action("Lightning Lash: Jolt", "paralyzed")(bundles)
    combat, table, mid, send, commit = fixture(tmp_path, [STORM, "TAL_LIGHTNING_CRACKLING_ARROW"],
        foe_ac=0, bundle_transform=setup)
    commit_charge(table, mid, send, FOE)
    before = combat._load_session(mid).engine.state.actors[OWNER].model_copy(deep=True)
    sequence = combat._load_session(mid).engine.state.event_sequence
    cid = candidate(table, mid, "Lightning Lash: Jolt", FOE)
    answers, seen = [], []
    for _ in range(12):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        source = p["context"]["reaction_source_id"]
        seen.append(source)
        assert not source.endswith("storm_heart_step")
        a = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            a["option_ids"] = ["move"] if source.endswith("storm_heart") else [p["choice"]["options"][0]["id"]]
        answers.append(a)
    # As in the Black Claw case, lock7-punishment-aegis (e48f3767,
    # L7aegis2.review.md) prevents a strike after its pre-effect paralyzes us.
    assert result["status"] == "COMMITTED" and "choice:needle.storm_heart" not in seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[OWNER]
    assert owner.position == before.position and owner.movement_remaining_ft == before.movement_remaining_ft
    assert any(c.condition_id == "condition:typed.paralyzed" for c in owner.conditions.values())
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER
                   for e in loaded.engine.events if e.sequence > sequence)
    assert loaded.mechanical.replay()["status"] == "PASS"
