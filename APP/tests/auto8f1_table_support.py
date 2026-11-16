"""Persisted-table fixture for the AUTO8 review fixes (lane AUTO8f1).

A real Factory match built through ``CombatService``/``TabletopService``: the owner owns exactly the named
Athletics talents, its choices are answered through the table's own Ask-me transport (the same pause, answer
and replay a live player meets), and the finished fight is reloaded from disk through the supported path so
saved-fight compatibility is checked rather than asserted.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Callable

from combat.factory_compiler import compile_character
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER = FACTORY_ACTOR_PREFIX + "auto8-owner"
FOE = FACTORY_ACTOR_PREFIX + "auto8-foe"
SECOND = FACTORY_ACTOR_PREFIX + "auto8-second"
IDS = (OWNER, FOE, SECOND)
ARENA = "battlefield:factory_pillar_arena"
POLEARM_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.ji", "name": "Ji (Halberd)", "quantity": 1}]}}
AXE_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}


def strip_athletics_passives(bundles: list[dict[str, Any]]) -> None:
    """Give the owner the bundle a pre-lane build would have produced: no ``athletics`` passive rows at all.

    That is exactly the difference between the bundle stored by a fight saved before this lane and the bundle
    the current builder produces, and it is what the retired Court reader (the persisted stance alone) used."""
    for bundle in bundles:
        if bundle["actor_id"] == OWNER:
            bundle["typed_passives"] = [row for row in bundle.get("typed_passives") or []
                                        if row.get("block") != "athletics"]


def zero_martial_focus(bundles: list[dict[str, Any]]) -> None:
    """Give the owner the bundle a fighter who has already spent its one Martial Focus would carry.

    ``resource:core.martial_focus`` starts at 1 for every build, and the printed "when Coordinated Movement
    restores Martial Focus" clauses have to be read from a fighter that has none."""
    for bundle in bundles:
        if bundle["actor_id"] != OWNER:
            continue
        for resource in bundle["actor_template"]["resources"]:
            if resource["resource_id"] == "resource:core.martial_focus":
                resource["initial"] = 0


def easy_grapple_target(bundles: list[dict[str, Any]]) -> None:
    """Make every enemy's Grapple land on the owner: a hopeless defender, strong grapplers.

    Court, Dizzy and Meridian all need real holds or real misses at the table, and neither should depend on the
    match seed's dice."""
    for bundle in bundles:
        template = bundle["actor_template"]
        if bundle["actor_id"] == OWNER:
            template["strength_score"], template["dexterity_score"] = 1, 1
        else:
            template["strength_score"], template["dexterity_score"] = 20, 10


def unknowable_armor(bundles: list[dict[str, Any]]) -> None:
    """Give the owner an Armor Class no enemy roll can reach, so an enemy's attack always misses.

    The foes attack with 1d20 plus their own modifiers, so an Armor Class above the best possible roll makes the
    miss deterministic. That is how the "when a hostile creature misses you" clauses are reached at the table
    without depending on the match seed."""
    for bundle in bundles:
        if bundle["actor_id"] == OWNER:
            bundle["actor_template"]["armor_class"] = 40


# Court needs both enemies beside the fighter: a step of one square has to leave the second one's reach too,
# or there is no second Opportunity Attack for the printed clause to prevent.
BESIDE_OWNER = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}}
# Dizzying Tumble asks which of the creatures the fighter is leaving to Dizzy, so it needs two of them in reach.
FLANKED_BY_OWNER = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 2, "y": 6}}
# The layout a caller gets for free. Court and its step need the fighter beside an enemy it can be missed by;
# the second enemy stands clear so it is not already in reach. Passed to the match itself rather than only
# computed, or the engine falls back to its own first-free-cell placement and every distance-based case
# silently tests a different board (review AUTO8r2, R6).
DEFAULT_PLACES = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 9}}


def fixture(tmp_path: Path, talents: list[str], *, seed: str, kit: dict[str, Any] | None = None,
            cl: int = 17, dc: int = 16, talents_by_actor: dict[str, list[str]] | None = None,
            ask_actors: tuple[str, ...] = (),
            bundle_transform: Callable[[list[dict[str, Any]]], None] | None = None,
            ask: bool = True, places: dict[str, dict[str, int]] | None = None,
            legacy_foes: dict[str, dict[str, int]] | None = None,
            legacy_allies: tuple[str, ...] = (),
            allies: tuple[str, ...] = ()):
    """Build the match, hand the owner its opening turn, and return the pieces a test drives.

    ``legacy_foes`` adds stock fighters (ids from ``combat.gate2_runtime_content``, e.g. ``AN``) to the enemy
    team. They are real fighters the engine resolves, not stand-ins: a case about a fighter that predates the
    Factory's typed rules needs a roster that actually holds one."""
    documents = []
    for index, actor_id in enumerate(IDS):
        document = sheet(talents if index == 0 else (talents_by_actor or {}).get(actor_id, []), cl=cl, dc=dc, primary="Stamina",
                         kit=kit if index == 0 else None)
        document["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 400
        documents.append(document)
    bundles = []
    for actor_id, document in zip(IDS, documents):
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundles.append(compile_character(document, actor_id=actor_id,
                                         reaction_plan={"ask": True} if actor_id == OWNER or actor_id in ask_actors else None))
    if bundle_transform:
        bundle_transform(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    teams = {actor_id: ("team:a" if actor_id == OWNER or actor_id in allies else "team:b") for actor_id in IDS}
    spots = {actor_id: dict(spot) for actor_id, spot in (places or DEFAULT_PLACES).items()}
    roster = list(IDS)
    for legacy_id, spot in (legacy_foes or {}).items():
        roster.append(legacy_id)
        teams[legacy_id] = "team:a" if legacy_id in legacy_allies else "team:b"
        spots[legacy_id] = dict(spot)
    match_id = combat._finish_factory_match(
        bundles, roster, teams, spots, combat.factory_arenas(include_retired=True)[ARENA], [OWNER], [FOE, SECOND],
        control_modes={actor_id: "MANUAL" for actor_id in roster}, match_seed=seed,
        display_name="AUTO8f1 regression", maximum_rounds=20,
    )["match_id"]
    # The promised layout, checked against the fight the factory actually built. Without this a lost ``spots``
    # would leave every caller running on the engine's fallback placement with nothing to say so.
    placed = CombatService(combat.source_root, tmp_path)._load_session(match_id).engine.state.actors
    for actor_id, spot in spots.items():
        at = placed[actor_id].position
        assert (at.x, at.y) == (spot["x"], spot["y"]), \
            f"{actor_id} was promised {spot} but the match placed it at ({at.x},{at.y})"

    def menu():
        return table.state(match_id)["menu"]

    def send(candidate_id, answers=()):
        current = menu()
        return table.act(match_id, candidate_id, current["decision_id"], current["state_version"], 0, list(answers))

    def commit(candidate_id, chooser=None):
        """Commit one candidate, answering every Ask-me prompt. ``chooser(prompt)`` -> the answer dict."""
        answers: list[dict[str, Any]] = []
        for _ in range(30):
            result = send(candidate_id, answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            answer = {**prompt["context"], "selection": "DECLINE"}
            choice = prompt.get("choice")
            if choice:
                answer["selection"] = "USE"
                options = chooser(prompt, choice) if chooser else (choice.get("preferred") or [choice["options"][0]["id"]])
                # JSON-shaped, exactly as a client sends it. The saved choice comes back from disk with lists, and
                # the table refuses a second answer whose earlier answers are not identical to the saved ones.
                if options:
                    answer["option_ids"] = list(options)
                else:
                    answer["selection"] = "DECLINE"
            answers.append(answer)
        raise AssertionError("the table never committed that candidate")

    def first_option(prompt, choice, wanted):
        for option in choice["options"]:
            if option["id"] == wanted:
                return [option["id"]]
        return [choice["options"][0]["id"]]

    def to_owner():
        for _ in range(20):
            if menu()["actor_id"] == OWNER:
                return
            commit(menu()["end_turn"])
        raise AssertionError("the owner never received a turn")

    def turn_of(actor_id):
        """Hand the fight's turn to ``actor_id`` by ending whoever has it, the way the table does."""
        for _ in range(20):
            if menu()["actor_id"] == actor_id:
                return
            commit(menu()["end_turn"])
        raise AssertionError(f"{actor_id} never received a turn")

    def foe_acts(actor_id, label, chooser=None):
        """One enemy's own turn at the table: take its turn, then commit the named action and answer what it asks."""
        turn_of(actor_id)
        return commit(candidate_id(menu(), label), chooser)

    def reload_owner():
        return CombatService(combat.source_root, tmp_path)._load_session(match_id).engine.state.actors[OWNER]

    def stored_engine():
        """The stored fight, reloaded from disk by a fresh service (no live session reused)."""
        return CombatService(combat.source_root, tmp_path)._load_session(match_id).engine

    def end_own_turn(decline: bool = False):
        """End the owner's own turn, answering every Ask-me prompt with a decline (or with its first option when
        ``decline`` is False). Returns the prompts the turn's end raised, so a test can read what it was asked."""
        answers: list[dict[str, Any]] = []
        prompts: list[dict[str, Any]] = []
        for _ in range(30):
            result = send(menu()["end_turn"], answers)
            if result["status"] == "COMMITTED":
                return prompts
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            prompts.append(prompt)
            answer = {**prompt["context"], "selection": "DECLINE"}
            choice = prompt.get("choice")
            if choice and not decline:
                answer["selection"] = "USE"
                answer["option_ids"] = [choice["options"][0]["id"]]
            answers.append(answer)
        raise AssertionError("the owner's turn never ended")

    to_owner()
    return {"combat": combat, "table": table, "match_id": match_id, "menu": menu, "send": send, "commit": commit,
            "first_option": first_option, "to_owner": to_owner, "reload_owner": reload_owner,
            "stored_engine": stored_engine, "turn_of": turn_of, "foe_acts": foe_acts,
            "end_own_turn": end_own_turn, "userdata": tmp_path, "places": spots}


def candidate_id(menu, label, *, exact=False):
    for group in menu["actions"]:
        for option in group["options"]:
            if option["label"] == label or (not exact and label in option["label"]):
                return option["candidate_id"]
    raise AssertionError(f"{label!r} is not on the menu: {[o['label'] for g in menu['actions'] for o in g['options']]}")


def ascent_move(menu):
    """The cheapest legal move that ends in the air: a table-level ascent, not a hand-placed position."""
    climbs = [move for move in menu["moves"] if int(move["destination"].get("z") or 0) > 0]
    assert climbs, "the fighter is offered no ascent"
    return min(climbs, key=lambda move: move["cost_ft"])


def move_candidate_id(menu, x, y):
    """The move that ends on this ground square, chosen the way a player would: by where it goes."""
    for move in menu["moves"]:
        destination = move["destination"]
        if (int(destination.get("x") or 0) == x and int(destination.get("y") or 0) == y
                and not int(destination.get("z") or 0)):
            return move["candidate_id"]
    raise AssertionError(f"no move to {x},{y} is offered")


def reload_identical(combat, match_id, userdata):
    """The stored fight reloads to the same state, verifies, and replays byte-identically."""
    session = combat._load_session(match_id)
    state = session.engine.state.model_dump(mode="json")
    fresh = CombatService(combat.source_root, userdata)._load_session(match_id).engine.state.model_dump(mode="json")
    assert state == fresh, "a fresh service must load the stored fight to the same state"
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
