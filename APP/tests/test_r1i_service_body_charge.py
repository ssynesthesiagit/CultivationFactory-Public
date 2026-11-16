"""Missed Opportunity Attacks offer Lightning-God Body's optional Charge.

riders/c13 (14cd285f, approved C13r3.review.md, merged 51edf97d)
restricts Gather Charge to its printed willing recipients. Establish the hostile
Charge with the shared native Lash setup; keep every cap/replacement assertion.
"""
import pytest
from combat import typed_executor as te
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, charge_setup, commit_charge, OWNER, FOE, SECOND

BODY = "TAL_LIGHTNING_LIGHTNING_GOD_BODY"


def next_owner(table, mid, commit):
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])


def answer_body(combat, mid, send, cid, *, auto=False, use=True, replace=True, off_turn=False):
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, seen = [], []
    for _ in range(16):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        source = p["context"]["reaction_source_id"]
        seen.append(source)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send(cid, answers, auto=auto)["reaction"] == p
        a = {**p["context"], "selection": "USE"}
        if source.endswith("god_body_charge") or source.endswith("god_body_replace"):
            assert "Lightning-God Body" in p["moment"] and "Opportunity Attack" in p["moment"]
            assert "Owner" in p["moment"] and ("Second" if off_turn else "Foe") in p["moment"]
            if not (replace if source.endswith("god_body_replace") else use):
                a["selection"] = "DECLINE"
            else:
                a["option_ids"] = [p["choice"]["options"][0]["id"]]
        elif source.endswith("black_claw"):
            a["option_ids"] = ["move"]
        elif source.endswith("black_claw_step"):
            a["option_ids"] = ["cell:4,5"]
        elif p.get("choice"):
            a["option_ids"] = [p["choice"]["options"][0]["id"]]
        else:
            # Only the second creature's missed OA is needed on off-turns.
            a["selection"] = "USE" if off_turn or p["context"]["reactor_id"] == FOE else "DECLINE"
        answers.append(a)
    assert result["status"] == "COMMITTED", result
    assert "choice:needle.god_body_charge" in seen, seen
    return before, seen


@pytest.mark.parametrize("use,replace", [(False, False), (True, False), (True, True)])
def test_body_charge_optional_cap_preview_reload(tmp_path, use, replace):
    combat, table, mid, send, commit = fixture(tmp_path, [BODY], owner_ac=500, owner_pb=1, bundle_transform=charge_setup)
    commit(candidate(table, mid, "Lightning-God Body"))
    next_owner(table, mid, commit)
    commit_charge(table, mid, send, SECOND)
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 3, "y": 8})
    before, seen = answer_body(combat, mid, send, cid, use=use, replace=replace)
    assert ("choice:needle.god_body_replace" in seen) == use
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert te.bears_mark(loaded.engine.state.actors[FOE], OWNER, "Charged") == (use and replace)
    assert te.bears_mark(loaded.engine.state.actors[SECOND], OWNER, "Charged") == (not (use and replace))
    if not (use and replace):
        assert loaded.engine.state.actors[SECOND].model_dump(mode="json")["conditions"] == before["actors"][SECOND]["conditions"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ai_body_charge_resolves_automatically_at_cap(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [BODY], owner_ac=500, owner_pb=1, bundle_transform=charge_setup)
    commit(candidate(table, mid, "Lightning-God Body"))
    next_owner(table, mid, commit)
    commit_charge(table, mid, send, SECOND)
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 3, "y": 8})
    force_ai_candidate(combat, mid, OWNER, cid)
    assert send(cid, auto=True)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert te.bears_mark(loaded.engine.state.actors[FOE], OWNER, "Charged")
    assert not te.bears_mark(loaded.engine.state.actors[SECOND], OWNER, "Charged")
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("use,replace", [(False, False), (True, False), (True, True)])
def test_off_turn_body_charge_asks_owner_after_missed_oa(tmp_path, auto_turn, use, replace):
    combat, table, mid, send, commit = fixture(tmp_path, [BODY, "TAL_DAEMONIC_CULTIVATION_DEMON_SEED",
        "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION"], owner_ac=500, owner_pb=1, foe_ac=0, seed="R1I-CLAW", bundle_transform=charge_setup,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 2, "y": 6}})
    for label in ["Demon Seed", "Black-Claw Manifestation", "Lightning-God Body"]:
        commit(candidate(table, mid, label))
        if label != "Lightning-God Body":
            next_owner(table, mid, commit)
    next_owner(table, mid, commit)
    commit_charge(table, mid, send, FOE)
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 4, "y": 8})
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    answer_body(combat, mid, send, cid, auto=auto_turn, use=use, replace=replace, off_turn=True)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert te.bears_mark(loaded.engine.state.actors[SECOND], OWNER, "Charged") == (use and replace)
    assert te.bears_mark(loaded.engine.state.actors[FOE], OWNER, "Charged") == (not (use and replace))
    assert loaded.mechanical.replay()["status"] == "PASS"
