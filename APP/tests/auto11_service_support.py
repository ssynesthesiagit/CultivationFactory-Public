"""Real table-service harness for the Scoundrel lane (AUTO11f1).

A Scoundrel and a second fighter are compiled from real sheets, put in a real CombatService match and driven
through TabletopService, so the questions these talents ask are read as a player reads them: the rendered
REACTION_REQUIRED prompt (its choice options by name, its bounds, its prompt sentence) and what a commit plus a
reload leaves in the saved fight. Nothing here reaches into a plug-in's private state.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from combat.ext import scoundrel_riders
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

THIEF = FACTORY_ACTOR_PREFIX + "auto11-thief"
VICTIM = FACTORY_ACTOR_PREFIX + "auto11-victim"
ALLY = FACTORY_ACTOR_PREFIX + "auto11-ally"
RIVAL = FACTORY_ACTOR_PREFIX + "auto11-rival"
FOCUS = scoundrel_riders.FOCUS
SWORD = {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1}]}
PACK = {"items": [{"item_id": "tianxia.mortal.gear.explorer_s_pack", "name": "Explorer's Pack", "quantity": 1}]}
ARMOR = {"items": [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1}]}
PACK_KEY = "tianxia.mortal.gear.explorer_s_pack"
ARMOR_KEY = "tianxia.mortal.armor.lacquered_lamellar"
ARMORED = {"items": [*SWORD["items"], *ARMOR["items"]]}


def _doc(talents, *, kit, name, ac=14):
    doc = sheet(talents, cl=12, dc=16, key="DEX")
    doc["identity"]["display_name"] = name
    doc["equipment"] = [{"starting_kit": kit}]
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 60
    doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    return doc


def fight(tmp_path, talents, *, victim_kit=PACK, thief_kit=PACK, seed="AUTO11F1-SVC", ally=False, rival=False,
          control="MANUAL", thief_skills=None, thief_size=None):
    """The thief (owner) against the victim, both compiled from real sheets, in a real service match.

    ``ally`` adds a fighter on the thief's own side and ``rival`` a second one on the victim's side, each carrying
    ``thief_kit``: a third fighter holding the same things is what lets a test tell two identical objects apart.
    """
    ids = [THIEF, VICTIM, ALLY, RIVAL] if (ally or rival) else [THIEF, VICTIM]
    team = {THIEF: "team:a", VICTIM: "team:b",
            **({ALLY: "team:a"} if ally else {}), **({RIVAL: "team:b"} if rival else {})}
    where = {THIEF: {"x": 3, "y": 6}, VICTIM: {"x": 4, "y": 6},
             **({ALLY: {"x": 3, "y": 7}} if ally else {}), **({RIVAL: {"x": 2, "y": 6}} if rival else {})}
    docs = {THIEF: _doc(talents, kit=thief_kit, name="Thief"),
            VICTIM: _doc([], kit=victim_kit, name="Victim", ac=12),
            ALLY: _doc([], kit=thief_kit, name="Ally", ac=12),
            RIVAL: _doc([], kit=thief_kit, name="Rival", ac=12)}
    if thief_size is not None:
        where[THIEF] = {"x": 2, "y": 5}
    if thief_skills is not None:
        docs[THIEF]["ability_scores_and_statistics"]["skills"] = list(thief_skills)
    for aid in ids:
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(docs[aid]))
    bundles = [compile_character(docs[aid], actor_id=aid, reaction_plan={"ask": True} if aid == THIEF else None)
               for aid in ids]
    if thief_size is not None:
        from tests.cw2_service_support import add_action
        add_action(bundles[0], "Prepare thief footprint", [{"type": "size_change", "size": thief_size,
                   "expires_on": "UNTIL_REMOVED"}], target="SELF")
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(bundles, ids, team, where, arena, [THIEF], [aid for aid in ids if aid != THIEF],
                                       control_modes={aid: control for aid in ids}, match_seed=seed,
                                       display_name="AUTO11f1", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != THIEF:
        if control == "MANUAL":  # an AI fighter's own controller plays its turn; only a player presses End Turn
            play(table, mid, table.state(mid)["menu"]["end_turn"], answer=None)
        else:
            table.auto_step(mid, table.state(mid)["last_sequence"])
    if thief_size is not None:
        play(table, mid, candidate(table, mid, "Prepare thief footprint"))
    return combat, table, mid


def act(table, mid, candidate_id, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"],
                     table.state(mid)["last_sequence"], list(answers))


def answer_for(prompt, answer=None):
    """One table answer to one rendered prompt: a real option id inside its bounds, or a decline.

    This is what a player at the table sends, and what the AI controller sends when the choice is its own.
    ``answer`` may be a callable taking the prompt, for a fight that asks a second question about the first
    answer (Steal's "plant one Tiny object", which is only asked once a planted object has been named).
    """
    if callable(answer):
        answer = answer(prompt)
    choice = prompt.get("choice") or {}
    legal = [row["id"] for row in choice.get("options") or []]
    if not legal:
        return {**prompt["context"], "selection": "USE"} if answer is None else {**prompt["context"], "selection": "USE"}
    if answer is None:
        if choice.get("allow_decline"):
            return {**prompt["context"], "selection": "DECLINE"}
        picked = (choice.get("preferred") or legal)[:int(choice.get("minimum") or 1)]
    else:
        named = offered(legal, answer)
        # a name this particular question does not offer (the fighter answered one question and the table raised
        # another): the first thing on offer, which is what the controller takes for an unnamed choice
        picked = [named if named in legal else legal[0]]
    return {**prompt["context"], "selection": "USE", "option_ids": picked}


def offered(legal, wanted):
    """The option the table offered for a name the caller used, so every answer is a legal option id.

    A fighter names the object it means ("take:an Explorer's Pack"); when two fighters carry the same thing the
    table offers one option per object and spells its id with that object's own identity, so that a bare item key
    is not two answers at once. This turns the fighter's name into the option that was actually on offer, and is
    left alone when nothing matches or when the name would match two options -- a caller that means one of two
    identical objects has to say which, exactly as the fighter at the table does.
    """
    wanted = str(wanted)
    if wanted in legal:
        return wanted
    kind, _, named = wanted.partition(":")
    matches = [option for option in legal
               if str(option).partition(":")[0] == kind and str(option).partition(":")[2].endswith(named)]
    return matches[0] if len(matches) == 1 else wanted


def play(table, mid, candidate_id, answer=None, *, limit=24):
    """Commit one table action, answering every question it raises; returns (response, prompts)."""
    answers, prompts = [], []
    for _ in range(limit):
        result = act(table, mid, candidate_id, answers)
        if result["status"] == "COMMITTED":
            return result, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompts.append(result["reaction"])
        answers.append(answer_for(result["reaction"], answer))
    raise AssertionError("too many prompts")


def records(engine, key):
    """Every transfer record in the fight for one object: (creature filed on, record data)."""
    return [(who, dict(row.data)) for who, creature in engine.state.actors.items()
            for row in creature.conditions.values() if (row.data or {}).get("item_key") == key]


def checks_succeeded(engine, at_least=1):
    """Whether at least ``at_least`` printed Scoundrel Checks in this fight have succeeded."""
    rolled = [event for event in engine.events
              if event.event_type == "CHECK_ROLLED" and (event.payload or {}).get("skill") == "Sleight of Hand"]
    return sum(1 for event in rolled if (event.payload or {}).get("success")) >= at_least


def to_thief(table, mid, *, end_thief=False):
    """Back to the thief's own menu, in the table's own turn order: end their turn, let the others take theirs.

    ``end_thief`` first presses End Turn on the thief's menu, which is how a player gives the turn back after an
    action, so a test can watch a second use of an ability the way a fight does.
    """
    for _ in range(16):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == THIEF and not end_thief:
            return menu
        play(table, mid, menu["end_turn"], answer=None)
        end_thief = False
    raise AssertionError("the thief's menu never came back")


def candidate(table, mid, label, target=None):
    for group in table.state(mid)["menu"]["actions"]:
        if label not in group["label"]:
            continue
        for option in group["options"]:
            if target is None or target in (option.get("target_ids") or []):
                return option["candidate_id"]
    raise AssertionError(f"{label!r} is not on the menu: {[g['label'] for g in table.state(mid)['menu']['actions']]}")


def engine(combat, mid):
    return combat._load_session(mid).engine


def held_by(creature, key):
    return [row for row in creature.conditions.values() if (row.data or {}).get("item_key") == key]


def scratch(tmp_path):
    path = Path(tmp_path)
    path.mkdir(parents=True, exist_ok=True)
    return path
