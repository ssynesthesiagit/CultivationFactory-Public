"""Shared TabletopService helpers for Hunt 52 identity regressions.

Two character sources:
- ``character()`` builds an in-repo portable character that owns exactly the named typed mechanics and is compiled by the
  real Factory compiler (the tests/h1_support.py sheet builder), so these regressions run everywhere;
- ``roster()`` reads the retained real Hunt 52 portable characters (H52_PORTABLE_ROOT) and skips when they are absent.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet as compiled_sheet

APP = pathlib.Path(__file__).resolve().parents[1]
PORTABLE_ROOT = pathlib.Path(os.environ.get(
    "H52_PORTABLE_ROOT", "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters"
))


def roster() -> list[dict]:
    if not PORTABLE_ROOT.is_dir():
        pytest.skip("real Hunt 52 portable inputs unavailable; set H52_PORTABLE_ROOT")
    result = []
    for archive in sorted(PORTABLE_ROOT.glob("*/current.zip")):
        with zipfile.ZipFile(archive) as source:
            sheet = json.loads(source.read("Tianxia_Owner_Character_Sheet_v1.json"))
        result.append({"pid": archive.parent.name, "archive": archive, "sheet": sheet,
                       "name": sheet["identity"]["display_name"],
                       "cl": int(sheet["identity"].get("cultivation_level", 1)),
                       "features": set((sheet.get("path_and_subpath") or {}).get("path_feature_record_ids") or [])})
    return result


IMMORTAL_SPIRIT = "tianxia.path.spirit_awakening.feature.immortal_spirit"
IRON_VOICE = "tianxia.path.body_refining.feature.iron_voice"  # Bonus Action, 1 Stamina: CON save or Frightened
TEARS = "tianxia.talent.beauty.tears_like_pearls"  # Action, 1 Qi: WIS save or Charmed for 1 minute
QI_TWO_FORMS = ["tianxia.path.qi_cultivation.feature.golden_core_form",
                "tianxia.path.qi_cultivation.feature.perfected_golden_core",
                "tianxia.path.qi_cultivation.feature.second_golden_core_form", TEARS]  # Tears: a Qi-cost technique
BODY_TWO_EXPRESSIONS = ["tianxia.path.body_refining.feature.core_tempering_expression",
                        "tianxia.path.body_refining.feature.perfected_core_tempering",
                        "tianxia.path.body_refining.feature.second_core_tempering_expression", IRON_VOICE]  # a Stamina cost
CLOSE_STARTS = {"team1": [[3, 3], [3, 5]], "team2": [[6, 3], [6, 5]]}  # everyone within 30 feet of everyone


def character(pid: str, name: str, mids: list[str], *, cl: int, primary: str = "Qi", dc: int = 16,
               golden: tuple[str, ...] = ()) -> dict:
    """An in-repo portable character owning exactly ``mids`` (proficiency +4, all abilities 14, 30 of its resource).

    ``golden`` records the fixed Golden Core Form(s) on the sheet (FD-7: a build choice, not an in-fight row)."""
    doc = compiled_sheet(mids, cl=cl, dc=dc, primary=primary)
    doc["identity"]["display_name"] = name
    if golden:
        doc.setdefault("path_and_subpath", {})["golden_core_forms"] = list(golden)
    return {"pid": pid, "sheet": doc, "name": name, "cl": cl, "features": set(mids)}


def fight(tmp_path: pathlib.Path, characters: list[dict], seed: str, manual_pids: tuple[str, ...] = (), *,
          starts: dict | None = None, ask_owner: bool = True):
    user = tmp_path / "table-user"
    shutil.rmtree(user, ignore_errors=True)
    user.mkdir()
    ids = []
    for row in characters:
        target = user / "portable_characters" / row["pid"]
        target.mkdir(parents=True)
        if row.get("archive"):
            shutil.copyfile(row["archive"], target / "current.zip")
        else:
            with zipfile.ZipFile(target / "current.zip", "w") as archive:
                archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(row["sheet"]))
        ids.append(row["pid"])
    owner_entity = "actor:factory." + ids[0]
    if ask_owner:
        ButtonStore(user / "tabletop_buttons").save_reactions(ids[0], {"mode": "ask"}, set())
    service = CombatService(APP, user)
    table = TabletopService(service, user)
    map_row = service.tabletop_maps.save({"display_name": "H52 regression", "width_squares": 16,
                                           "height_squares": 16,
                                           "starts": starts or {"team1": [[3, 3], [15, 15]],
                                                                "team2": [[4, 3], [14, 15]]}})
    modes = {"actor:factory." + pid: "MANUAL" for pid in manual_pids}
    mid = service.create_factory_match(
        project_ids=ids[:2], opponent_actor_ids=["actor:factory." + pid for pid in ids[2:]],
        control_modes={owner_entity: "MANUAL", **modes}, arena_id="battlefield:map." + map_row["map_id"],
        match_seed=seed, maximum_rounds=4,
    )["match_id"]
    return user, service, table, mid, owner_entity


def owner_menu(service: CombatService, table: TabletopService, mid: str, owner_entity: str) -> dict:
    state = table.state(mid)
    answers = []
    for _ in range(80):
        if state["menu"].get("manual") and service._load_session(mid).engine.state.current_actor_id == owner_entity:
            return state
        response = table.auto_step(mid, state["last_sequence"], answers)
        while response["status"] == "REACTION_REQUIRED":
            prompt = response["reaction"]
            answer = {**prompt["context"], "selection": "USE"}
            if prompt.get("choice"):
                answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
            answers.append(answer)
            response = table.auto_step(mid, state["last_sequence"], answers)
        assert response["status"] == "COMMITTED", response
        state = response["state"]
        answers = []
    raise AssertionError("real CL20 owner did not receive a manual turn")


def choose(service: CombatService, table: TabletopService, mid: str, owner_entity: str, wanted: str) -> dict:
    state = owner_menu(service, table, mid, owner_entity)
    group = next(row for row in state["menu"]["actions"] if row["label"] == wanted)
    response = table.act(mid, group["options"][0]["candidate_id"], state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"], [])
    assert response["status"] == "COMMITTED", response
    return response["state"]


def committed_state(service: CombatService, mid: str) -> dict:
    first = service._load_session(mid).engine.state.model_dump(mode="json")
    reloaded = CombatService(service.source_root, service.userdata_root)._load_session(mid)
    assert reloaded.engine.state.model_dump(mode="json") == first
    verify = reloaded.verify()
    replay = reloaded.mechanical.replay()
    assert verify["canonical_state_sha256"] == replay["canonical_state_sha256"]
    return first


def commit(table: TabletopService, mid: str, candidate_id: str | None = None) -> dict:
    """Act with ``candidate_id`` (else Auto Step), declining reactions and taking the first option of any choice."""
    answers: list[dict] = []
    for _ in range(16):
        state = table.state(mid)
        menu = state["menu"]
        response = (table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
                    if candidate_id else table.auto_step(mid, state["last_sequence"], answers))
        if response["status"] == "COMMITTED":
            return response
        assert response["status"] == "REACTION_REQUIRED", response
        prompt = response["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    raise AssertionError("too many reaction prompts")


def turn_of(table: TabletopService, mid: str, entity: str) -> dict:
    """End every other manual turn (Auto Step the AI's) until ``entity`` has a manual turn; return the table state."""
    for _ in range(60):
        state = table.state(mid)
        menu = state["menu"]
        if menu.get("manual") and menu.get("actor_id") == entity:
            return state
        commit(table, mid, menu["end_turn"] if menu.get("manual") else None)
    raise AssertionError(f"{entity} never received a manual turn")


def option(state: dict, label: str, target: str | None = None) -> str:
    """The candidate id of the menu action labelled ``label`` (aimed at ``target`` when given)."""
    return next(row["candidate_id"] for group in state["menu"]["actions"] if group["label"] == label
                for row in group["options"] if target is None or row.get("target_ids") == [target])


def labels(state: dict) -> set[str]:
    return {group["label"] for group in state["menu"]["actions"]}
