import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, immobilize_on_action, OWNER, FOE


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("immobilized", [None, "grappled", "restrained", "pinned", "paralyzed"])
def test_black_claw_opportunity_hit_choice_and_step_commit_reload(tmp_path, auto_turn, immobilized):
    """An actor paralyzed before rolling cannot land a Black-Claw hit.

    codex/lock7-punishment-aegis (e48f3767, approved L7aegis2.review.md)
    rechecks can_strike after pre-attack effects, before every typed strike.
    """
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_DAEMONIC_CULTIVATION_DEMON_SEED",
                                                       "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION"], foe_ac=0, seed="R1I-CLAW",
        bundle_transform=immobilize_on_action("Opportunity Attack" if immobilized == "paralyzed" else "Black-Claw Manifestation", immobilized))
    commit(candidate(table, mid, "Demon Seed"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Black-Claw Manifestation"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for o in menu["moves"] if o["destination"] == {"x": 4, "y": 8})
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
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
        answer = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            if source.endswith("black_claw"):
                answer["option_ids"] = ["move"]
            elif source.endswith("black_claw_step"):
                option = next(o for o in p["choice"]["options"] if o["id"] == "cell:2,6")
                assert "Move to (2, 6)" in option["label"]
                answer["option_ids"] = [option["id"]]
            else:
                answer["option_ids"] = [p["choice"]["options"][0]["id"]]
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    assert ("choice:needle.black_claw" in seen) == (immobilized != "paralyzed") and ("choice:needle.black_claw_step" in seen) == (immobilized is None), (
        seen, [e.payload for e in combat._load_session(mid).engine.events if e.event_type == "ATTACK_ROLLED"])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[OWNER]
    recent = [e for e in loaded.engine.events if e.sequence > before["event_sequence"]]
    if immobilized == "paralyzed":
        assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER for e in recent)
        assert not any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == OWNER for e in recent)
        assert loaded.engine.state.actors[FOE].current_hp == before["actors"][FOE]["current_hp"]
    assert owner.position.model_dump(mode="json") == (before["actors"][OWNER]["position"] if immobilized else {"x": 2, "y": 6})
    assert owner.movement_remaining_ft == before["actors"][OWNER]["movement_remaining_ft"]
    if immobilized:
        if immobilized != "speed_zero":
            assert any(c.condition_id == "condition:typed." + immobilized for c in owner.conditions.values())
        assert loaded.engine._effective_speed(owner) == 0
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_black_claw_step_respects_effective_zero_speed_off_turn(tmp_path):
    test_black_claw_opportunity_hit_choice_and_step_commit_reload(tmp_path, False, "speed_zero")
