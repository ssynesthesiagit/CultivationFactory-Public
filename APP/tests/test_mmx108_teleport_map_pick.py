"""MMX108 (owner playtest, round 24, owner message 03:14): a teleport's destination must be picked by
clicking the main map, not read off a list of squares in a dialog.

    "For any teleportation you can just click on an available square on the grid rather than a tooltip."

Pinned here, at the level the owner saw it (a real table, a real menu, the real unbindable self-teleport):

- while a player-controlled creature is choosing where a teleport lands, the paused decision the table
  publishes marks that choice as a map-point choice (``choice.map_pick``) and carries the legal squares
  (``map_pick.cells``, one per option's ``cell``), so the main map can light them up and answer with a click;
- clicking one of those squares lands the creature exactly there -- the option ids are the transport's own,
  so the candidate/destination binding is untouched;
- cancelling (Esc) leaves the creature where it was, and that is the ordinary decline the transport already had;
- no other choice changes: a space choice that is not a teleport keeps the list presentation, and an AI
  creature is still never asked at all.

The rule text behind the choice is unchanged by this lane: the destination is the user's because the printed
rule is "Teleport to an unoccupied space you can see within range" (Void, "Empty Step and Teleportation":
"it requires an unoccupied destination you can see"). Only the question's presentation moves from a list of
squares to the map.
"""
from __future__ import annotations

import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER = "actor:factory.mmx108-owner"
FOE = "actor:factory.00000000-0000-0000-0000-000000000108"
EMPTY_STEP = "TAL_VOID_EMPTY_STEP"


def _write(doc, aid, tmp_path):
    doc["identity"]["display_name"] = aid.removeprefix(FACTORY_ACTOR_PREFIX)
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))


def _unbind(bundle, suffix):
    """Leave a compiled action's square unbound: the shape a zero-size area gives it at the table.

    combat/gate4_engine.py _action_candidates binds one square per legal square for a self-teleport; an action
    that declares a zero-size area is declined by that helper, so its single candidate carries no destination
    and the destination question is asked instead (combat/ext/teleport_steps.py ask_destination).
    """
    for action in bundle.get("action_catalog") or []:
        if str(action.get("source_definition_id") or "").endswith(suffix):
            action["parameters"]["typed"]["area"] = {"size_ft": 0}
            return action["source_definition_id"]
    raise AssertionError(f"no compiled action ends with {suffix!r}")


def _table(tmp_path, *, owner_talents=(EMPTY_STEP,), owner_mode="MANUAL"):
    """A real duel on the pillar arena, the owner in the player's control, as the owner's playtest was."""
    docs = {OWNER: sheet(list(owner_talents), cl=17, dc=50), FOE: sheet([], cl=17, score=14)}
    for aid, doc in docs.items():
        _write(doc, aid, tmp_path)
    bundles = [compile_character(docs[aid], actor_id=aid) for aid in (OWNER, FOE)]
    _unbind(bundles[0], EMPTY_STEP)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 14, "y": 6}}, arena, [OWNER], [FOE],
        control_modes={OWNER: owner_mode, FOE: "MANUAL"}, match_seed="MMX108",
        display_name="MMX108 Map Pick", maximum_rounds=6)["match_id"]
    return combat, table, mid


def _menu(table, mid):
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        _send(table, mid, table.state(mid)["menu"]["end_turn"])
    return table.state(mid)


def _send(table, mid, candidate_id, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))


def _group(state, label):
    return next((g for g in state["menu"]["actions"] if g["label"].startswith(label)), None)


def _first_pause(table, mid, group):
    """Act on the group's first candidate and return the paused decision, or None if it committed."""
    result = _send(table, mid, group["options"][0]["candidate_id"])
    if result["status"] != "REACTION_REQUIRED":
        assert result["status"] == "COMMITTED", result["status"]
        return None
    return result["reaction"]


def _moved(combat, mid):
    state = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine.state
    return state.actors[OWNER].position


# ------------------------------------------------------------------ the table marks the choice and its squares
def test_a_teleport_destination_is_published_as_a_map_point_choice_with_its_legal_squares(tmp_path):
    """The owner's complaint, as data: the paused teleport names the squares to click on the main map."""
    combat, table, mid = _table(tmp_path)
    group = _group(_menu(table, mid), "Empty Step")
    assert group is not None, "Empty Step is missing from the menu"
    prompt = _first_pause(table, mid, group)
    assert prompt is not None, "an unbound teleport must pause to ask where to land"
    choice = prompt["choice"]
    pick = choice.get("map_pick")
    assert pick, f"the teleport is still a list of squares, not a map choice: {json.dumps(choice, default=str)[:400]}"
    assert pick["cells"], "a map choice with no squares would trap the player"
    assert len(pick["cells"]) > 1, "one square is not a choice; this pins the picker over a real range"
    # Every legal square is clickable, and it is exactly the set the transport offers: the same option ids.
    assert {cell["x"] for cell in pick["cells"]} == {option["cell"]["x"] for option in choice["options"]}
    assert {cell["y"] for cell in pick["cells"]} == {option["cell"]["y"] for option in choice["options"]}
    assert [cell for cell in pick["cells"]] == [option["cell"] for option in choice["options"]]
    for cell in pick["cells"]:
        assert 0 <= cell["x"] < choice["space_map"]["width"] and 0 <= cell["y"] < choice["space_map"]["height"]
    assert choice["allow_decline"] is True, "staying put must remain an answer"
    assert choice["maximum"] == 1, "one click chooses one square"


def test_the_map_choice_text_is_written_for_a_player_who_only_knows_basic_dnd(tmp_path):
    combat, table, mid = _table(tmp_path)
    group = _group(_menu(table, mid), "Empty Step")
    prompt = _first_pause(table, mid, group)
    pick = prompt["choice"]["map_pick"]
    instruction = pick["instruction"]
    assert "click" in instruction.lower() and "square" in instruction.lower()
    assert "Esc" in instruction, "the owner must be told how to cancel"
    assert not any(token in instruction for token in ("choice:", "typed.", "cell:", "reaction:")), (
        f"the instruction leaks an internal id: {instruction!r}")
    # And it names the ability and the creature, so the player knows whose move this is.
    assert prompt["title"].startswith("Empty Step"), prompt["title"]
    assert OWNER.removeprefix(FACTORY_ACTOR_PREFIX) in json.dumps(prompt, default=str)


# ------------------------------------------------------------------ clicking a square lands there
def test_clicking_a_highlighted_square_lands_the_creature_exactly_there(tmp_path):
    combat, table, mid = _table(tmp_path)
    group = _group(_menu(table, mid), "Empty Step")
    prompt = _first_pause(table, mid, group)
    choice = prompt["choice"]
    wanted = choice["options"][-1]["cell"]  # a square a player could click, far from the one the engine would prefer
    picked = next(option for option in choice["options"] if option["cell"] == wanted)
    result = _send(table, mid, group["options"][0]["candidate_id"],
                   [{**prompt["context"], "selection": "USE", "option_ids": [picked["id"]]}])
    assert result["status"] == "COMMITTED", result["status"]
    landed = _moved(combat, mid)
    assert (landed.x, landed.y) == (wanted["x"], wanted["y"]), (
        f"clicked {wanted}, landed on ({landed.x}, {landed.y})")


def test_cancelling_the_teleport_leaves_the_creature_where_it_was(tmp_path):
    """Esc is the ordinary decline the transport already carried: the cost is spent, nobody moves."""
    combat, table, mid = _table(tmp_path)
    before = _menu(table, mid)["presentation"]["actors"]
    owner_before = next(a for a in before if a["entity_id"] == OWNER)["position"]
    group = _group(_menu(table, mid), "Empty Step")
    prompt = _first_pause(table, mid, group)
    assert prompt["choice"]["allow_decline"] is True
    result = _send(table, mid, group["options"][0]["candidate_id"],
                   [{**prompt["context"], "selection": "DECLINE"}])
    assert result["status"] == "COMMITTED", result["status"]
    landed = _moved(combat, mid)
    assert (landed.x, landed.y) == (owner_before["x"], owner_before["y"]), "Esc must leave the creature in place"


# ------------------------------------------------------------------ nothing else changed
def test_an_ai_creature_is_still_never_asked():
    """The lane is player-facing: an AI teleport keeps its own behaviour, so AI fights replay unchanged."""
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, ReactionDecision
    from combat.gate4_engine import Gate4ControllerEngine

    owner_sheet = sheet([EMPTY_STEP], cl=17, dc=50)
    owner_sheet["identity"]["display_name"] = OWNER.removeprefix(FACTORY_ACTOR_PREFIX)
    bundle = compile_character(owner_sheet, actor_id=OWNER)
    _unbind(bundle, EMPTY_STEP)
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX108AI", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                                 "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    engine.typed_control_modes = {OWNER: "LOCAL_AUTO"}  # the built-in AI answers for itself
    action = ActionDefinition(source_definition_id="action:typed.mmx108.ai_step", display_name="Unbound Step", owner_id=OWNER,
                              economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=20,
                              parameters={"options": ("SELF",),
                                          "typed": {"effects": [{"type": "teleport", "applies_to": "self", "distance_ft": 20,
                                                                 "evidence": "Teleport to an unoccupied space you can see."}],
                                                    "area": {"size_ft": 0},
                                                    "numbers": {"pb": 4, "cl": 17, "save_dc": 15, "attack_bonus": 9},
                                                    "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[OWNER].action_ids = (*engine.state.actors[OWNER].action_ids, action.source_definition_id)
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.set_reaction_provider(choose)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id="mmx108ai", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=OWNER, target_ids=candidate.target_ids, option_ids=candidate.option_ids))
    assert not asked, f"an AI combatant was asked to pick its own teleport destination: {asked}"
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (3, 6)


def test_a_non_teleport_space_choice_keeps_its_list_presentation():
    """The seam is opt-in and general: no answer from the owning plug-in means the list, exactly as before."""
    from combat.choice_presentation import map_pick

    choice = {"options": [{"id": "cell:1,2"}], "maximum": 1}
    assert map_pick(None, choice, {"reaction_source_id": "choice:needle.wide_open"}) is None
    assert map_pick(None, choice, {"reaction_source_id": "choice:needle.teleport_destination"}) is not None


def test_the_table_client_picks_a_teleport_square_on_the_main_map():
    """The other half of the owner's bug, which is a display one: run the table's own client test.

    Nothing above can fail on a client that still shows a list, so the highlighted squares, the click and Esc
    are driven against the real static/tabletop/tabletop.js (the same harness style as tests/test_newcomer_text.py).
    """
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "static" / "tabletop" / "tabletop_map_pick.test.mjs"
    assert script.exists(), f"the client regression test is missing: {script}"
    result = subprocess.run(["node", "--test", "--test-isolation=none", str(script)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"the tabletop client no longer picks a teleport square on the map:\n{result.stdout}\n{result.stderr}"


def test_the_map_and_the_way_out_are_clickable_while_the_fight_is_working_the_action():
    """The map-pick question is asked from *inside* the request the fight is still working out, and that is
    exactly when the page switches the board off to clicks. So the squares were lit up on a board that swallowed
    every click: Esc still worked (it is a key handler) and nothing else did.

    The node regression drives the real act() -> paused question path and hit-tests the click against the real
    shipped stylesheet, so a rule that turns the map off during a working turn is caught here, not by a player.
    """
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "static" / "tabletop" / "tabletop_map_pick_hit.test.mjs"
    assert script.exists(), f"the client hit-test regression is missing: {script}"
    result = subprocess.run(["node", "--test", "--test-isolation=none", str(script)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"a teleport square cannot be clicked while the fight is working:\n{result.stdout}\n{result.stderr}"


def test_pause_snapshot_reload_and_token_covered_clicks_use_the_real_board_paths():
    """SOLFMMX108r2: render actual board tokens and dispatch their shipped listeners.

    Headless DOM evidence only; the lead runs rendered browser checks outside the sandbox.
    """
    import subprocess

    script = ROOT / "static" / "tabletop" / "tabletop_map_pick_hit.test.mjs"
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-name-pattern", "movement before|reload resumes|Large chooser", str(script)],
        capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"pause/token event-path regression:\n{result.stdout}\n{result.stderr}"


def test_the_working_turn_hands_the_map_back_to_an_open_pick():
    """The same fix seen from the stylesheet, so it is checked even where node is not run.

    While a turn is being worked out the page deliberately switches the board and the hint off to clicks (that
    is the "working" cue, and it is what kept the new picker unclickable). An open pick has to hand exactly those
    two surfaces back, and the rule doing it has to outrank the one that took them.
    """
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "static" / "tabletop" / "tabletop.css").read_text()
    working = re.search(r"body\.is-working :is\(([^)]*)\)\s*\{[^}]*pointer-events:\s*none", css)
    assert working, "the working turn no longer switches the map off; this test needs rethinking"
    disabled = {name.strip() for name in working.group(1).split(",")}
    assert {"#ttViewport", "#ttHint"} <= disabled, "the working cue is expected to take these two surfaces off"

    handed_back = re.search(
        r"body\.is-working\.is-map-pick :is\(([^)]*)\)\s*\{[^}]*pointer-events:\s*(auto|all)", css)
    assert handed_back, "an open map pick has to hand the map and the hint back to the pointer"
    assert {"#ttViewport", "#ttHint"} <= {name.strip() for name in handed_back.group(1).split(",")}

    # Two classes beat one, so this rule wins over the one above it wherever the sheet is later in the file.
    assert css.index("body.is-working.is-map-pick") > css.index("body.is-working :is("), \
        "the rule that hands the map back has to come after the rule that takes it"
