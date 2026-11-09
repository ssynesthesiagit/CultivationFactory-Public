import pytest
from combat import typed_executor as te
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER


@pytest.mark.parametrize("ai_owner", [False, True])
def test_turning_guard_event_choice_table_commit_reload(tmp_path, ai_owner):
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_FLOWING_RIVER_TURNING_GUARD"])
    cid = candidate(table, mid, "Dodge")
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(cid, auto=ai_owner)
    if not ai_owner:
        assert result["status"] == "REACTION_REQUIRED"
        p = result["reaction"]
        assert p["context"]["reaction_source_id"] == "choice:needle.turning_guard"
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send(cid)["reaction"] == p
        result = send(cid, [{**p["context"], "selection": "USE", "option_ids": [p["choice"]["options"][0]["id"]]}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == "condition:typed.river_named_guard" for c in loaded.engine.state.actors[OWNER].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("ai_owner", [False, True])
def test_court_off_turn_event_choice_manual_and_ai_preview_reload(tmp_path, auto_turn, ai_owner):
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_COURT_OF_CHARGED_PATHS"])
    engine = combat._load_session(mid).engine
    order = list(engine.state.initiative_order)
    idx = order.index(OWNER)
    advancing, charged = order[(idx + 1) % 3], order[(idx + 2) % 3]
    commit(candidate(table, mid, "Court of Charged Paths"))
    # Gather Charge selects willing creatures; the later rider lanes enforce
    # that printed restriction. Charge this hostile creature with a real hit.
    commit(candidate(table, mid, "Lightning Lash: Charge", charged))
    assert te.bears_mark(combat._load_session(mid).engine.state.actors[charged], OWNER, "Charged")
    commit(table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == advancing
    cid = table.state(mid)["menu"]["end_turn"]
    if ai_owner:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    if auto_turn:
        force_ai_candidate(combat, mid, advancing, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(cid, auto=auto_turn)
    if not ai_owner:
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        assert p["context"]["reaction_source_id"] == "choice:needle.court_charge"
        assert p["context"]["reactor_id"] == OWNER
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send(cid, auto=auto_turn)["reaction"] == p
        picked = advancing
        result = send(cid, [{**p["context"], "selection": "USE", "option_ids": [picked]}], auto=auto_turn)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not te.bears_mark(loaded.engine.state.actors[charged], OWNER, "Charged")
    assert loaded.mechanical.replay()["status"] == "PASS"
