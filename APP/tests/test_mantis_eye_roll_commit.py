"""Eye of the Mantis spends first-attack Advantage on a committed roll only."""
import json
import zipfile

from combat import ext
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER = "actor:factory.mantis-eye-regression-owner"
FOE = "actor:factory.mantis-eye-regression-foe"
PARENT = "tianxia.subpath.body.mantis_style"


def _native(tmp_path):
    for actor_id, is_owner in ((OWNER, True), (FOE, False)):
        doc = sheet([], cl=14, primary="Stamina" if is_owner else "Qi", score=30 if is_owner else 10, dc=100 if is_owner else 16)
        if is_owner:
            doc["identity"]["path"] = "Body Refining"
            doc["path_and_subpath"] = {"path_feature_record_ids": ["tianxia.path.body_refining.feature.iron_fist"]}
        doc["identity"]["display_name"] = "Mantis practitioner" if is_owner else "Training target"
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 5
        folder = tmp_path / "portable_characters" / actor_id.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))

    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"map_id": "mantis-eye-commit", "display_name": "Training yard",
        "width_squares": 12, "height_squares": 10, "objects": [],
        "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    journey = combat.create_journey(project_ids=["mantis-eye-regression-owner", "mantis-eye-regression-foe"],
        arena_id="battlefield:map.mantis-eye-commit",
        positions={OWNER: {"x": 3, "y": 4}, FOE: {"x": 4, "y": 4}},
        base_paces={OWNER: 3000, FOE: 3000})
    acquired = combat.journey_acquire_source(journey["journey_id"], journey["revision"], OWNER, PARENT, {"operation": "select"})
    result = combat.journey_start_combat(journey["journey_id"], acquired["revision"],
        {OWNER: "team:factory", FOE: "team:opponents"}, maximum_rounds=10)
    table = TabletopService(combat, tmp_path)
    mid = result["match_id"]
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        menu = table.state(mid)["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
    return combat, table, mid


def _act(table, mid, candidate_id, *, auto_choices=False):
    answers = []
    for _ in range(40):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        context = prompt["context"]
        answer = {**context, "selection": "DECLINE"}
        if auto_choices and prompt.get("choice"):
            answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    raise AssertionError("native action did not settle")


def _candidate(table, mid, label):
    return next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"]
        if label in group["label"] for option in group["options"])


def test_pre_roll_cancellation_keeps_eye_for_first_committed_attack(tmp_path, monkeypatch):
    combat, table, mid = _native(tmp_path)
    # The Eye group offers a target per creature; this test diagnoses the foe.
    _act(table, mid, next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"]
        if "Eye of the Mantis" in group["label"] for option in group["options"]
        if option["target_ids"] == [FOE]))
    cancelled = [False]

    def cancel_one_before_roll(ctx, target, effect):
        if ctx.actor.entity_id == OWNER and target.entity_id == FOE and not cancelled[0]:
            cancelled[0] = True
            return False
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_allowed", [*ext.subscribers("attack_allowed"), cancel_one_before_roll])
    # This practitioner's unarmed strike is its Iron Fist weapon row; any
    # natural strike action is a valid committed attack for this receipt.
    attack_id = next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"]
        if ".natural." in group["source_definition_id"] and "#rapid_pincer" not in group["source_definition_id"]
        for option in group["options"] if option["target_ids"] == [FOE])
    # The fixture's Iron Fist row asks a mandatory damage-type choice, so every
    # offered choice takes its first option; the eye receipt and the pre-roll
    # cancellation are what this test measures.
    _act(table, mid, attack_id, auto_choices=True)
    engine = combat._load_session(mid).engine
    rolls = [roll for roll in engine.rolls if roll.reason.startswith("ATTACK:") and roll.actor_id == OWNER]
    assert cancelled[0], "the test must cancel an attack after mode selection but before its roll"
    assert rolls and rolls[0].mode == "ADVANTAGE"
    assert all(roll.mode == "NORMAL" for roll in rolls[1:])
    eye = next(condition for condition in engine.state.actors[FOE].conditions.values()
        if condition.condition_id.endswith("eye_of_the_mantis"))
    assert eye.data.get("attack_turn")
