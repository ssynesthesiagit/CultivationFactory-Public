"""World-Nerve may select a GM-run maintenance check instead of Concentration."""
import pytest

from combat import concentration, typed_executor as te
from combat.ext.speech import concentration_save
from combat.gate2_engine import SYSTEM_CONCENTRATION
from combat.gate2_runtime_models import ActionIntent, ConcentrationState
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_riders_lane1 import _rider_engine, _rider_action, _answers, ME, AN

WORLD_NERVE = "TAL_LIGHTNING_WORLD_NERVE_JUDGMENT"
GM_CHECK = "gm:maintenance_check"


def selected_notice(events):
    return [e for e in events if e.event_type == "GM_RIDER"
            and "Selected maintenance check" in str(e.payload.get("rider", ""))]


def test_gm_check_selection_preserves_all_concentration_and_next_save_mode():
    engine = _rider_engine(WORLD_NERVE, dc=50)
    subject = engine.state.actors[AN]
    subject.concentration = ConcentrationState(source_definition_id="test:older", started_sequence=1)
    concentration.hold_current(engine, subject)
    subject.concentration = ConcentrationState(source_definition_id="test:current", started_sequence=2)
    engine._apply_condition(subject, concentration.MODE, "test:advantage", AN, expires_on="UNTIL_REMOVED",
                            data={"rule": {"concentration_mode": "ADVANTAGE", "next": True}})
    seen = _answers(engine, {"held_effect": [GM_CHECK]})
    action = _rider_action(engine, WORLD_NERVE)
    intent = ActionIntent(intent_id="maintenance", actor_id=ME, decision_id="test", candidate_id="test",
                          state_version=engine.state.state_version)
    ctx = te.Context(engine, engine.state.actors[ME], action, intent, action.parameters["typed"], [subject], subject, {})
    spec = next(row for row in te._walk_rows(action.parameters["typed"]["effects"])
                if row.get("type") == "concentration_save" and row.get("choose_held"))
    before = subject.model_dump(mode="json")
    start = len(engine.events)
    concentration_save(ctx, spec)
    assert GM_CHECK in seen[0]["extension_choice"]["option_ids"]
    assert subject.model_dump(mode="json") == before
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events[start:])
    notice, = selected_notice(engine.events[start:])
    assert notice.actor_id == ME and notice.target_ids == (AN,)
    assert "without Disadvantage" in notice.payload["rider"]
    assert "no additional Concentration save" in notice.payload["rider"]


@pytest.mark.parametrize("ai_owner", [False, True])
@pytest.mark.parametrize("has_concentration", [False, True])
def test_world_nerve_maintenance_choice_table_preview_commit_reload_replay(tmp_path, ai_owner, has_concentration):
    combat, table, mid, send, commit = fixture(
        tmp_path, [WORLD_NERVE], owner_dc=-40, foe_score=50,
        foe_talents=["WATER_BASE_SHAPE_CURRENT"] if has_concentration else [])
    if has_concentration:
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != FOE:
            commit(table.state(mid)["menu"]["end_turn"])
        commit(candidate(table, mid, "Shape Current: Cleansing Basin"))
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "World-Nerve Judgment", FOE)
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert bool(before["actors"][FOE]["concentration"]) == has_concentration
    result = send(cid, auto=ai_owner)
    if not ai_owner:
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        assert p["context"]["reaction_source_id"] == "choice:needle.held_effect"
        assert p["context"]["reactor_id"] == OWNER
        option = next(o for o in p["choice"]["options"] if o["id"] == GM_CHECK)
        assert "GM-run maintenance check" in option["label"]
        assert "World-Nerve Judgment" in p["moment"] and "Foe" in p["moment"]
        assert "successful save" in p["moment"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send(cid)["reaction"] == p
        result = send(cid, [{**p["context"], "selection": "USE", "option_ids": [GM_CHECK]}])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    recent = [e for e in loaded.engine.events if e.sequence > before["event_sequence"]]
    checks = [e for e in recent if e.event_type == "SAVE_ROLLED"
              and e.source_definition_id == SYSTEM_CONCENTRATION]
    # Damage still calls for its ordinary Concentration save. Only the selected
    # tracked effect (the AI default) gets an additional World-Nerve save.
    assert len(checks) == (2 if has_concentration and ai_owner else 1 if has_concentration else 0)
    notices = selected_notice(recent)
    assert len(notices) == (0 if has_concentration and ai_owner else 1)
    assert loaded.engine.state.actors[FOE].model_dump(mode="json")["concentration"] == before["actors"][FOE]["concentration"]
    assert loaded.mechanical.replay()["status"] == "PASS"
