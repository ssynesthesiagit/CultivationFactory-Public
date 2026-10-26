"""A posture suppressed through the table must stop affecting saves."""

import json
import zipfile
from pathlib import Path

from tests.test_auto_lane1 import _sheet
from combat.ext import save_against
from combat.factory_compiler import compile_character
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat import typed_executor


APP = Path(__file__).resolve().parents[1]
ARMOR = "TAL_GRAVITY_WEIGHT_SHIFT_BASE"
LINE = "tianxia.talent.sabers.battlefield_beheading_line"


def _choose(table, match_id, label, target=None, option=None):
    state = table.state(match_id)
    menu = state["menu"]
    if label == "end":
        candidate_id = menu["end_turn"]
    else:
        group = next((g for g in menu["actions"] if g["label"] == label or g.get("display_name") == label), None)
        assert group is not None, (menu["actor_id"], [g["label"] for g in menu["actions"]])
        candidate_id = next(o["candidate_id"] for o in group["options"] if target is None or target in o["target_ids"])
    answers = []
    for _ in range(20):
        result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            return result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            options = prompt["choice"]["options"]
            picked = next((o for o in options if option and option in o["id"]), options[0])
            ordered = [picked] + [o for o in options if o["id"] != picked["id"]]
            answer["option_ids"] = [o["id"] for o in ordered[:max(1, int(prompt["choice"].get("minimum", 1)))]]
        answers.append(answer)
    raise AssertionError("repeated prompts")


def _fight(tmp_path):
    documents = {}
    for pid, ability in [("guard", ARMOR), ("saber", LINE), ("shover", ARMOR)]:
        document = _sheet(ability, cl=20, dc=60)
        document["identity"]["display_name"] = pid.title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        documents[pid] = document
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))

    service = CombatService(APP, tmp_path)
    table = TabletopService(service, tmp_path)
    modes = {"actor:factory." + pid: "MANUAL" for pid in documents}
    templates = [compile_character(doc, actor_id="actor:factory." + pid)["actor_template"] for pid, doc in documents.items()]
    for n in range(1000):
        seed = f"H39-POSTURE-{n}"
        roller = DeterministicRollAuthority(seed)
        scores = [(roller.d20(modifier=t["initiative_bonus"], actor_id=t["entity_id"], reason="INITIATIVE").total,
                   t["initiative_bonus"], t["dexterity_score"], t["entity_id"]) for t in templates]
        if [row[3] for row in sorted(scores, key=lambda row: (-row[0], -row[1], -row[2], row[3]))] == list(modes):
            break
    else:
        raise AssertionError("seed not found")

    arena = service.tabletop_maps.save({"display_name": "H39 Posture", "width_squares": 12, "height_squares": 10,
        "walls": [], "starts": {"team1": [[3, 3]], "team2": [[8, 3], [4, 3]]}})
    match_id = service.create_factory_match(project_ids=["guard"], opponent_actor_ids=["actor:factory.saber", "actor:factory.shover"],
        control_modes=modes, arena_id="battlefield:map." + arena["map_id"], match_seed=seed)["match_id"]
    if table.state(match_id)["menu"]["actor_id"] != "actor:factory.guard":
        _choose(table, match_id, "end")
    _choose(table, match_id, "Weight Shift: Body Heavying")
    _choose(table, match_id, "end")
    guard = service._load_session(match_id).engine.state.actors["actor:factory.guard"]
    held = next(c for c in guard.conditions.values() if (c.data or {}).get("rule", {}).get("save_against"))
    _choose(table, match_id, "Battlefield Beheading Line", "actor:factory.guard", held.instance_id)
    _choose(table, match_id, "end")
    _choose(table, match_id, "Shove: Prone", "actor:factory.guard")

    fresh = CombatService(APP, tmp_path)._load_session(match_id)
    guard = fresh.engine.state.actors["actor:factory.guard"]
    condition = guard.conditions[held.instance_id]
    assert condition.condition_id.startswith("condition:typed.suppressed.")
    assert not any(row.get("save_against") for row in typed_executor.condition_rules(guard))
    assert save_against.save_against(None, guard, "STR", ["prone"]) is None
    shove_save = next(e for e in fresh.engine.events if e.event_type == "SAVE_ROLLED" and "shove_prone" in e.payload.get("reason", ""))
    assert shove_save.payload["mode"] == "NORMAL"
    assert len(shove_save.payload["dice"]) == 1
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_suppressed_defensive_benefit_does_not_grant_save_advantage(tmp_path):
    _fight(tmp_path)
