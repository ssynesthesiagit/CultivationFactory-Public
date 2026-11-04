"""Nail save-result choices through transactional table previews and reload."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r4_integration import P, F, fixture, reach, send, candidate, auto_candidate

NAIL = "TAL_METAL_HEAVEN_PIERCING_NAIL"
NAME = "Heaven-Piercing Nail"
FAIL = [
    ("Speed becomes 0", "speed_becomes"),
    ("Cannot teleport", "cannot_teleport"),
    ("Cannot take Reactions", "reaction_denied"),
    ("Cannot benefit from unsupported flight (GM)", None),
    ("Cannot maintain one GM-chosen movement, phasing, or escape technique", None),
]
SUCCESS = [("Speed reduced by 10 feet", None),
           ("Cannot take Opportunity Attacks", "no_opportunity_attacks")]


def preference_candidate(table, mid, label):
    name = "Choose Heaven-Piercing Nail: " + label
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] for o in g["options"]
                if o.get("label", g["label"]) == name)


@pytest.mark.parametrize("success,label,slug", [(False, *row) for row in FAIL] + [(True, *row) for row in SUCCESS])
def test_nail_asks_after_actual_save_and_commits_only_selected_effect(tmp_path, success, label, slug):
    combat, table, mid = fixture(tmp_path, [NAIL], foe_ac=1,
                                 foe_score=500 if success else 14, seed="R4-NAIL")
    reach(table, mid, P)
    # Standing choices must not silently answer the player's later save choice.
    preference = preference_candidate(table, mid, "Cannot teleport")
    assert send(table, mid, preference)["status"] == "COMMITTED"
    cid = candidate(table, mid, NAME, F)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    for text in (NAME, "Rider Foe", "successful Constitution save" if success else "failed Constitution save"):
        assert text in prompt["moment"]
    assert prompt["context"]["reactor_id"] == P
    assert prompt["choice"]["minimum"] == prompt["choice"]["maximum"] == 1
    assert not prompt["choice"]["allow_decline"]
    assert {o["id"] for o in prompt["choice"]["options"]} == {row[0] for row in (SUCCESS if success else FAIL)}
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send(table, mid, cid)["reaction"] == prompt
    answer = {**prompt["context"], "selection": "USE", "option_ids": [label]}
    assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor, target = loaded.engine.state.actors[P], loaded.engine.state.actors[F]
    assert actor.resources["resource:core.qi"] == before["actors"][P]["resources"]["resource:core.qi"] - 8
    assert target.current_hp < before["actors"][F]["current_hp"]
    assert len([e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED"]) == 1
    assert len([e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"]) == 1
    assert {c.condition_id for c in target.conditions.values()} == (
        {f"condition:typed.{slug}"} if slug and slug != "speed_becomes" else set())
    assert loaded.engine._effective_speed(target) == (0 if slug == "speed_becomes" else target.speed_ft - 10
                                                     if label == "Speed reduced by 10 feet" else target.speed_ft)
    lines = [e.payload.get("rider", "") for e in loaded.engine.events if e.event_type == "GM_RIDER"]
    assert any("unless supported by wings" in line for line in lines) == ("unsupported flight" in label)
    assert any("technique of the GM's choice" in line for line in lines) == ("GM-chosen" in label)
    assert loaded.mechanical.replay()["status"] == "PASS"
    reach(table, mid, F)
    reach(table, mid, P)
    target = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[F]
    if slug == "no_opportunity_attacks":
        assert not target.conditions
    elif slug:
        assert target.conditions or target.modifiers  # failure ends at source turn END, not START
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[F].conditions
    assert loaded.engine._effective_speed(loaded.engine.state.actors[F]) == target.speed_ft
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("success,label,slug", [(False, "Cannot take Reactions", "reaction_denied"),
                                              (True, "Cannot take Opportunity Attacks", "no_opportunity_attacks")])
def test_ai_nail_resolves_automatically_using_standing_preference(tmp_path, success, label, slug):
    combat, table, mid = fixture(tmp_path, [NAIL], foe_ac=1,
                                 foe_score=500 if success else 14, seed="R4-NAIL")
    reach(table, mid, P)
    assert send(table, mid, preference_candidate(table, mid, label))["status"] == "COMMITTED"
    cid = candidate(table, mid, NAME, F)
    auto_candidate(combat, mid, P, cid)
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert {c.condition_id for c in loaded.engine.state.actors[F].conditions.values()} == {f"condition:typed.{slug}"}
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_nail_miss_does_not_ask_for_save_rider_or_log_gm_options(tmp_path):
    combat, table, mid = fixture(tmp_path, [NAIL], miss=True, seed="R4-NAIL")
    reach(table, mid, P)
    assert send(table, mid, candidate(table, mid, NAME, F))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[F].conditions
    assert not any(e.event_type == "SAVE_ROLLED" for e in loaded.engine.events)
    lines = [e.payload.get("rider", "") for e in loaded.engine.events if e.event_type == "GM_RIDER"]
    assert not any("unless supported by wings" in line or "technique of the GM's choice" in line for line in lines)
    assert loaded.mechanical.replay()["status"] == "PASS"
