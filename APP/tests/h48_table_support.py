"""Small persisted-table fixture shared by Hunt 48 regressions."""

import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, FOE, SECOND = [FACTORY_ACTOR_PREFIX + "r1i-" + key for key in ("owner", "foe", "second")]
THIRD = FACTORY_ACTOR_PREFIX + "r1i-third"
ESSENCE = "resource:named.devoured_essence"


def fixture(tmp_path, talents, *, seed, extra_foe=False, bundle_transform=None, primary="Qi", path_features=(),
            owner_golden=None):
    ids = [OWNER, FOE, SECOND] + ([THIRD] if extra_foe else [])
    sheets = [sheet(talents, cl=17, dc=50, primary=primary)] + [sheet([], cl=17) for _ in ids[1:]]
    bundles = []
    for actor_id, document in zip(ids, sheets):
        if actor_id == OWNER and path_features:
            document["path_and_subpath"] = {"path_feature_record_ids": list(path_features)}
        if actor_id == OWNER and owner_golden is not None:
            # The Golden Core Form is a fixed build choice recorded on the sheet, not an in-fight row.
            document.setdefault("path_and_subpath", {})["golden_core_forms"] = list(owner_golden)
        document["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        document["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundles.append(compile_character(document, actor_id=actor_id,
                                         reaction_plan={"ask": True} if actor_id == OWNER else None))
    if bundle_transform:
        bundle_transform(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena_id = "battlefield:factory_pillar_arena"
    positions = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}}
    if extra_foe:
        positions[THIRD] = {"x": 6, "y": 6}
    match_id = combat._finish_factory_match(
        bundles, ids,
        {actor_id: "team:a" if actor_id == OWNER else "team:b" for actor_id in ids},
        positions, combat.factory_arenas(include_retired=True)[arena_id], [OWNER], ids[1:],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed=seed,
        display_name="H48 regression", maximum_rounds=15,
    )["match_id"]

    def send(candidate_id, answers=()):
        menu = table.state(match_id)["menu"]
        return table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))

    def commit(candidate_id):
        answers = []
        for _ in range(20):
            result = send(candidate_id, answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            answer = {**prompt["context"], "selection": "DECLINE"}
            if prompt.get("choice"):
                answer.update(selection="USE", option_ids=(prompt["choice"].get("preferred") or
                                                              [prompt["choice"]["options"][0]["id"]])[:1])
            answers.append(answer)
        raise AssertionError("reaction loop")

    for _ in range(20):
        if table.state(match_id)["menu"]["actor_id"] == OWNER:
            break
        commit(table.state(match_id)["menu"]["end_turn"])
    else:
        raise AssertionError("owner did not receive the opening turn")
    return combat, table, match_id, send, commit


def candidate(table, match_id, label, target=None):
    return next(option["candidate_id"] for group in table.state(match_id)["menu"]["actions"]
                if label in group["label"] for option in group["options"]
                if target is None or target in option.get("target_ids", []))


def assert_reload_verify_replay(combat, match_id, userdata):
    session = combat._load_session(match_id)
    state = session.engine.state.model_dump(mode="json")
    fresh = CombatService(combat.source_root, userdata)._load_session(match_id).engine.state.model_dump(mode="json")
    assert state == fresh
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
