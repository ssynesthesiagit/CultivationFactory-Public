"""F3: the defender owns a seal's save choice in actual table transactions."""
import json

import pytest

from combat.gate5_service import CombatService
from combat.factory_compiler import compile_character
from combat.tabletop_service import TabletopService
from combat.ext import ability_lockout
from tests import test_riders_c2 as C2
from tests.test_riders_c14 import CLOSING, ROOT
from tests.test_c5_review import _act


def table_fixture(tmp_path, ask=False, target_talents=None):
    owner = C2._pp([CLOSING], dc=20)
    owner["actor_template"]["speed_ft"] = 0
    target = compile_character(C2._sheet(target_talents or ["TAL_ALCHEMY_CALMING_HEART_PILL"]), actor_id=C2.ATK,
                               reaction_plan={"ask": ask}, typed_authority=C2._authority())
    for bundle, initiative in ((owner, 0), (target, 100)):
        if target_talents:
            bundle["actor_template"]["display_name"] = "Seal user" if bundle is owner else "Defender"
        bundle["actor_template"].update(maximum_hp=500, armor_class=0, initiative_bonus=initiative)
        for action in bundle["action_catalog"]:
            if bundle is owner and action["display_name"] != "Fu (Short Axe) attack":
                # Keep the actual local controller on the melee delivery under test;
                # a thrown attack does not qualify for Touch the Point.
                action["parameters"]["player_only"] = True
            typed = action["parameters"].get("typed") or {}
            if typed.get("numbers"):
                typed["numbers"]["attack_bonus"] = 100
    target["actor_template"]["saving_throws"].update(CON=100, WIS=-100)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="C14-F3", typed_bundles=(owner, target), roster_setup={
        "primary_actor_ids": [C2.ME, C2.ATK], "team_by_actor": {C2.ME: "team:a", C2.ATK: "team:b"},
        "starting_positions": {C2.ME: {"x": 3, "y": 6}, C2.ATK: {"x": 4, "y": 6}}})
    mid = session.match_id
    combat._read_metadata(mid, session)
    table = TabletopService(combat, tmp_path)
    second_use = ("Meridian-Sealing Pill",) if target_talents else ()
    for name in ("Calming Heart Pill", "End turn", "Touch the Point: Technique-Closing Point",
                 "Fu (Short Axe) attack", "End turn", *second_use, "End turn"):
        _act(combat, table, mid, name)
    # Both targets and the source ask; the target's choice must be independent of source control.
    for actor in (C2.ME, C2.ATK):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    assert combat._load_session(mid).mechanical.verify()["status"] == "PASS"
    return CombatService(ROOT, tmp_path), mid


@pytest.mark.parametrize("source_mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("save", ["CON", "WIS"])
@pytest.mark.parametrize("ask", [False, True], ids=["manual-no-reaction-plan", "ask-me"])
def test_manual_target_chooses_on_player_and_ai_turns_after_reload(tmp_path, source_mode, save, ask):
    combat, mid = table_fixture(tmp_path, ask)
    combat.set_controller_mode(mid, actor_id=C2.ME, controller_mode=source_mode)
    table = TabletopService(combat, tmp_path)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    if source_mode == "MANUAL":
        menu = table.state(mid)["menu"]
        candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                         if c["display_name"] == "Fu (Short Axe) attack")
        result = table.act(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [])
    else:
        for _ in range(8):
            before = combat._load_session(mid).engine.state.model_dump(mode="json")
            result = table.auto_step(mid, 0)
            if result["status"] == "REACTION_REQUIRED":
                break
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == C2.ATK
    assert {o["id"] for o in prompt["choice"]["options"]} == {"CON", "WIS"}
    text = json.dumps(prompt)
    assert "Technique-Closing Point" in text and "Fu (Short Axe) attack" in text
    assert "until the end of your next turn" in text and "costs no action or resource" in text
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": [save]}
    # Reopen the service while paused, then resolve the same pending transaction.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    if source_mode == "MANUAL":
        result = table.act(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [answer])
    else:
        result = table.auto_step(mid, 0, [answer])
    assert result["status"] == "COMMITTED", result
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in session.engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == C2.ATK]
    assert saves[-1].payload["modifier"] == (100 if save == "CON" else -100)
    assert ability_lockout.records(session.engine.state.actors[C2.ATK])[0].data["mode"] == (
        "watch" if save == "CON" else "barred")
    assert session.mechanical.verify()["status"] == "PASS"


def test_ai_target_selects_automatically_after_reload(tmp_path):
    combat, mid = table_fixture(tmp_path, ask=True)
    combat.set_controller_mode(mid, actor_id=C2.ATK, controller_mode="LOCAL_AUTO")
    engine, prompts = _act(combat, TabletopService(combat, tmp_path), mid, "Fu (Short Axe) attack")
    assert not prompts
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == C2.ATK]
    assert saves[-1].payload["modifier"] == 100
    assert ability_lockout.records(engine.state.actors[C2.ATK])[0].data["mode"] == "watch"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.verify()["status"] == "PASS"
