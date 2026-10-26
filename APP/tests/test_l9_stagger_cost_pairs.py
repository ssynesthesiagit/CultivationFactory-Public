"""Staggering Blow's persisted pair cost must survive the table prompt and reload."""
import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

FEATURE = "tianxia.subpath.body.drunken_fist.feature.staggering_blow"
IDS = [f"actor:factory.h40-{name}" for name in ("brawler", "ally", "target", "foe")]


def test_staggering_blow_pair_cost_prompts_commits_and_replays(tmp_path):
    docs = [sheet([FEATURE, "TAL_IRON_FIST_IRON_FIST_TRAINING"], cl=17, dc=50, score=50, primary="Stamina")]
    docs.extend(sheet([], cl=17) for _ in range(3))
    docs[0]["identity"]["path"] = "Body Refining"
    docs[0]["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    for index, doc in enumerate(docs):
        doc["identity"]["display_name"] = ["Brawler", "Ally", "Target", "Foe"][index]
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        folder = tmp_path / "portable_characters" / IDS[index].removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))

    bundles = [compile_character(doc, actor_id=actor_id,
                reaction_plan={"ask": True} if index == 0 else None)
               for index, (actor_id, doc) in enumerate(zip(IDS, docs))]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    match_id = combat._finish_factory_match(
        bundles, IDS, {actor_id: "team:a" if index < 2 else "team:b" for index, actor_id in enumerate(IDS)},
        dict(zip(IDS, [{"x": 3, "y": 6}, {"x": 3, "y": 8}, {"x": 4, "y": 6}, {"x": 5, "y": 8}])),
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], IDS[:2], IDS[2:],
        control_modes={actor_id: "MANUAL" for actor_id in IDS}, match_seed="L9-STAGGER-PAIR",
        display_name="Staggering Blow pair cost", maximum_rounds=3)["match_id"]

    def send(candidate_id, answers=()):
        state = table.state(match_id)
        menu = state["menu"]
        return table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"],
                         state["last_sequence"], list(answers))

    while table.state(match_id)["menu"]["actor_id"] != IDS[0]:
        assert send(table.state(match_id)["menu"]["end_turn"])["status"] == "COMMITTED"

    state = table.state(match_id)
    engine = combat._load_session(match_id).engine
    row = next(row for row in engine.typed_passive_rows[IDS[0]] if row.get("feature_id") == FEATURE)
    assert row["costs"] == [["resource:core.stamina", 1]]
    group, option = next((group, option) for group in state["menu"]["actions"] for option in group["options"]
                         if IDS[2] in option["target_ids"] and group["label"] == "Unarmed Strike (Iron Fist)")
    candidate_id = option["candidate_id"]
    before = engine.state.model_dump(mode="json")
    prompt_result = send(candidate_id)
    assert prompt_result["status"] == "REACTION_REQUIRED", prompt_result
    prompt = prompt_result["reaction"]
    assert "Staggering Blow" in prompt["reaction"]
    assert "1 Stamina" in prompt["cost"]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before

    assert send(candidate_id, [{**prompt["context"], "selection": "DECLINE"}])["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
