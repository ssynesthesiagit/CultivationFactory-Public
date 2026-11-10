"""Flowing Combination explains its free maneuver through table commit/reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

PLAYER, FOE = "actor:factory.log1-flowing", "actor:factory.log1-target"
FLOWING = "TAL_IRON_FIST_FLOWING_COMBINATION"
IRON = "tianxia.path.body_refining.feature.iron_fist"


@pytest.mark.parametrize("option", ["Grapple", "Shove: Push 5 ft", "Shove: Prone"])
@pytest.mark.parametrize("failed", [True, False])
def test_flowing_names_its_free_followup_after_reload(tmp_path, monkeypatch, option, failed):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [19, *([1 if failed else 20] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    doc = sheet([IRON, FLOWING], score=8)
    doc["identity"]["display_name"] = "Combination Player"
    foe = sheet([], score=14)
    foe["identity"]["display_name"] = "Combination Target"
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [compile_character(doc, actor_id=PLAYER), compile_character(foe, actor_id=FOE)],
        [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="LOG1-FLOWING",
        display_name="Flowing attribution regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    before = dict(engine.state.actors[PLAYER].resources)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Iron Fist attack")
    args = (mid, candidate.candidate_id, state["menu"]["decision_id"],
            state["menu"]["state_version"], state["last_sequence"])
    from tests.iron_fist_support import answering_iron_fist  # the Iron Fist strike's damage-type question (L45)
    strike = answering_iron_fist(lambda answers: table.act(*args, answers))
    pending = strike([])
    assert pending["status"] == "REACTION_REQUIRED"
    prompt = pending["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.flowing_combination"
    answer = {**prompt["context"], "selection": "USE", "option_ids": [option]}
    assert strike([answer])["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    boundary = fresh.history(mid)["boundaries"][-1]
    saves = [e for e in boundary["events"] if e["event_type"] == "SAVE_ROLLED"]
    assert len(saves) == 1
    assert saves[0]["payload"]["dc"] == 11  # 8 + PB 4 + STR -1, not cultivation DC.
    assert saves[0]["payload"]["success"] is not failed
    assert saves[0]["source_definition_id"] == f"passive:{FLOWING}"
    summaries = [e["summary"] for e in boundary["feed"]]
    assert any("save against Flowing Combination (DC 11)" in s for s in summaries)
    assert any("Flowing Combination" in s and option in s and "without spending another attack" in s
               for s in summaries)
    loaded = fresh._load_session(mid)
    actor, target = loaded.engine.state.actors[PLAYER], loaded.engine.state.actors[FOE]
    assert actor.resources == before
    assert actor.bonus_action_available
    assert sum(e["event_type"] == "ATTACK_ROLLED" for e in boundary["events"]) == 1
    if option != "Shove: Push 5 ft":
        conditions = [c for c in target.conditions.values()
                      if c.condition_id == "condition:typed." + ("grappled" if option == "Grapple" else "prone")]
        assert bool(conditions) is failed
        assert all(c.source_definition_id == f"passive:{FLOWING}" for c in conditions)
    else:
        assert loaded.engine.grid.distance_ft(actor.position, target.position) == (10 if failed else 5)
    assert loaded.mechanical.replay()["status"] == "PASS"
