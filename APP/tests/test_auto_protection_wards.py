"""AUTO69/AUTO69f1: Protection's Ward edge, Ward size, Shielded's free hand and Status, at the table.

Every printed effect asserted here is read from the built authority the fight loads
(APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json), and each test drives the real
CombatService/TabletopService through combat/ext/protection.py: no engine patching, no
live data, no hand-rolled rows.

The rolls are deterministic. The owner's Cultivation Save DC is 50 in the default fixture,
which no d20 can beat, so every printed "Failed Save" branch really runs; ``owner_dc=2``
builds the opposite fixture, which no d20 can fail, so the printed "Successful Save" branch
really runs too. Nothing below branches on which way a roll fell.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext import hand_occupancy, protection
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import FOE, OWNER, SECOND
from tests.test_r1i_round3 import reload

PR = "tianxia.talent.protection."
BASE = ["PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS", "PROTECTION_BASE_WARD"]
WARD_SIZE = "choice:needle.protection_ward_size"
IMPEDANCE = "choice:needle.protection_impedance_aegis"
REPEL = "choice:needle.protection_repel"
REELING_MOVE = "choice:needle.drunken_reeling_move"
QI = "resource:core.qi"
UNREADABLE = 50   # the owner's Cultivation Save DC: every creature in these tests fails against it
TRIVIAL = 2       # ... and here every creature passes
REELING_STEP = "TAL_DRUNKEN_STYLE_REELING_STEP"
LASH = "TAL_LIGHTNING_LIGHTNING_LASH"
KINDLE = "TAL_YANG_KINDLE_THE_WOUNDED_BREATH"
TWO_HANDS = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao"},
                                        {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou"}]}}
ONE_HAND = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao"}]}}


def flat_grid(finite_heights: bool):
    """The engine's own square grid, so a direction and a distance are measured the way the fight measures them."""
    from combat.gate2_grid import SquareGrid

    return type("Engine", (), {"grid": SquareGrid({"width_squares": 40, "height_squares": 20, "square_size_ft": 5,
                                                   "starting_positions": {}, "terrain_regions": []})})()


def spot(x: int, y: int, z: int = 0):
    """A real Position, so the engine's own distance and point reader see what a fight's would."""
    from combat.gate2_runtime_models import Position

    return type("Holder", (), {"position": Position(x=x, y=y, z=z)})()


def record(mechanic_id: str) -> dict:
    return json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text(
        encoding="utf-8"))["mechanics"][mechanic_id]


def printed(mechanic_id: str) -> str:
    """The printed rules the table is held to, read from the owner's own text."""
    return json.loads((ROOT / "authority" / "typed_mechanics" / "rules_text.json").read_text(encoding="utf-8"))[mechanic_id]


def kind(label: str):
    """Label the foe with one printed creature kind, exactly as a stat block or character sheet would."""
    def prepare(bundles):
        foe = bundles[1]
        foe["actor_template"]["creature_types"] = [label]
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)
    return prepare


def table_fixture(tmp_path, talents, *, foe_talents=(), second_talents=(), allies=(), owner_kit=None, hp=500,
                  speed_ft=30, owner_dc=UNREADABLE, positions=None, bundle_transform=None, seed="A69"):
    """:func:`tests.r1i_service_support.fixture` on the same wide map, with the four knobs these tests need: the foe's
    walking Speed (a route long enough to reach a Ward's edge and walk back is inside one turn), hit points (a real hit
    can wound or fell a bearer), the foe's team (a friendly creature inside a Repel Ward is the printed exemption's
    harder case) and the owner's Save DC (the branch a save takes). Real sheets, the real compiler, the real
    CombatService/TabletopService, and the same manual control on every fighter."""
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    ids = [OWNER, FOE, SECOND]
    docs = [sheet(talents, cl=17, dc=owner_dc, kit=owner_kit), sheet(list(foe_talents), cl=17), sheet(list(second_talents), cl=17)]
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.split("r1i-")[-1].title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 14
        if aid == FOE:
            doc["ability_scores_and_statistics"]["speed"]["walking_ft"] = speed_ft
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid == OWNER else None)
               for aid, doc in zip(ids, docs)]
    if bundle_transform:
        bundle_transform(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    saved = combat.tabletop_maps.save({"display_name": "A69 wide", "width_squares": 40, "height_squares": 20, "walls": [],
                                       "starts": {"team1": [[3, 6]], "team2": [[4, 6], [5, 6]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(bundles, ids, {aid: "team:a" if aid == OWNER or aid in allies else "team:b" for aid in ids},
                                       positions or {OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}, SECOND: {"x": 3, "y": 7}},
                                       arena, [OWNER], ids[1:], control_modes={aid: "MANUAL" for aid in ids},
                                       match_seed=seed, display_name="A69", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        act(table, mid, table.state(mid)["menu"]["end_turn"])
    return combat, table, mid


def option(table, mid, label: str, group: str | None = None, target: str | None = None):
    """The offered candidate whose label is exactly ``label`` (so a test never picks "(Persistent)" by accident), else the
    first that starts with it."""
    fallback = None
    for row in table.state(mid)["menu"]["actions"]:
        if group is not None and group not in row["label"]:
            continue
        for choice in row["options"]:
            if target is not None and target not in (choice.get("target_ids") or ()):
                continue
            if choice["label"] == label:
                return choice["candidate_id"]
            if choice["label"].startswith(label) and fallback is None:
                fallback = choice["candidate_id"]
    if fallback is not None:
        return fallback
    raise AssertionError(f"no offered choice starting {label!r}")


def play(table, mid, cid: str, picks: dict | None = None):
    """Commit one choice, answering every printed question it raises (the first offered option unless named). A pick may
    be an option id or a callable that receives the offered options and returns one, so a test can answer a question by
    what it asks rather than by an index."""
    menu = table.state(mid)["menu"]
    before = table.combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(16):
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return before, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        assert table.combat._load_session(mid).engine.state.model_dump(mode="json") == before
        choice = prompt.get("choice") or prompt["context"].get("choice") or {}
        answer = {**prompt["context"], "selection": "DECLINE"}
        if choice.get("options"):
            picked = (picks or {}).get(prompt["context"]["reaction_source_id"], "$first")
            answer["selection"] = "USE"
            answer["option_ids"] = [choice["options"][0]["id"] if picked == "$first"
                                    else picked(choice["options"]) if callable(picked) else picked]
        answers.append(answer)
    raise AssertionError("too many prompts")


def act(table, mid, cid: str):
    menu = table.state(mid)["menu"]
    result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "COMMITTED", result
    return result


def end_turn(table, mid) -> None:
    act(table, mid, table.state(mid)["menu"]["end_turn"])


def await_actor(table, mid, actor_id: str, rounds: int = 8, *, first: bool = False) -> None:
    """End turns until ``actor_id`` is up again. ``first`` crosses one boundary even when it is already up."""
    for _ in range(rounds):
        if not first and table.state(mid)["menu"]["actor_id"] == actor_id:
            return
        first = False
        end_turn(table, mid)
    if table.state(mid)["menu"]["actor_id"] != actor_id:
        raise AssertionError(f"{actor_id} never came round")


def at(engine, actor_id: str) -> tuple[int, int]:
    position = engine.state.actors[actor_id].position
    return position.x, position.y


def offered_move(table, mid, x: int, y: int) -> bool:
    return any((row["destination"]["x"], row["destination"]["y"]) == (x, y) for row in table.state(mid)["menu"]["moves"])


def move_to(table, mid, x: int, y: int) -> None:
    row = next((row for row in table.state(mid)["menu"]["moves"] if (row["destination"]["x"], row["destination"]["y"]) == (x, y)), None)
    assert row is not None, f"no move offered to {x},{y}"
    act(table, mid, row["candidate_id"])


def armor_class(table, mid, actor_id: str) -> int:
    """The Armor Class the table shows for a fighter, out of the tabletop projection."""
    for row in table.state(mid)["presentation"]["actors"]:
        if row["entity_id"] == actor_id:
            return next(defense["value"] for defense in row["defenses"] if defense["defense_id"] == "defense:armor_class")
    raise AssertionError(f"{actor_id} is not in the projection")


def zone_of(engine, talent: str):
    """The Ward this talent has standing now; a Ward its creator replaced is still in the record, and not this one."""
    return next(zone for zone in engine.state.zones.values() if zone.active
                and (engine.action_catalog.get(zone.source_definition_id).parameters or {}).get("protection_ward") == talent)


def live(combat, mid):
    """The fight as it is stored right now, the same object every assertion in these tests reads."""
    return combat._load_session(mid).engine


def said(engine) -> str:
    """Everything the fight has said: log lines and movement interruptions alike."""
    return json.dumps([event.payload for event in engine.events])


def log(engine) -> str:
    return "\n".join(str(event.payload.get("log") or "")
                     for event in engine.events if event.event_type == "PASSIVE_TRIGGERED")


def saves(engine, actor_id: str, source_prefix: str = "") -> list[dict]:
    """The saving throws this creature made, with the ability read out of the roll's own reason."""
    out = []
    for event in engine.events:
        if event.event_type != "SAVE_ROLLED" or event.actor_id != actor_id:
            continue
        row = dict(event.payload)
        row["ability"] = str(row.get("reason") or "").rsplit(":", 1)[-1]
        if source_prefix and not event.source_definition_id.startswith(source_prefix):
            continue
        out.append(row)
    return out


def conditions(engine, actor_id: str, condition_id: str) -> list:
    return [held for held in engine.state.actors[actor_id].conditions.values() if held.condition_id == condition_id]


# ----------------------------------------------------------------------------------------- Ward size (PROTECTION_BASE_WARD)
def test_ward_size_is_asked_and_the_printed_size_is_the_default(tmp_path):
    """"you may reduce its size when creating it": the creator chooses; 20 feet of radius unless they shrink it."""
    assert "you may reduce its size when creating it" in printed("PROTECTION_BASE_WARD")
    assert record("PROTECTION_BASE_WARD")["coverage"] == "FULL"
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "energy_resistance"])
    _, prompts = play(table, mid, option(table, mid, "Ward: Energy Resistance"), {WARD_SIZE: "$first"})
    assert "Ward size" in [prompt.get("title") for prompt in prompts]
    zone = zone_of(combat._load_session(mid).engine, PR + "energy_resistance")
    assert (zone.trigger_profile["size_ft"], zone.radius_cells) == (20, 4)  # the printed size, chosen by default


def test_a_smaller_ward_is_smaller_on_the_map(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "energy_resistance"])
    play(table, mid, option(table, mid, "Ward: Energy Resistance"), {WARD_SIZE: "10"})
    zone = zone_of(combat._load_session(mid).engine, PR + "energy_resistance")
    assert (zone.trigger_profile["size_ft"], zone.radius_cells) == (10, 2)


# ----------------------------------------------------------------------------------------- Impedance, the Aegis
def test_impedance_aegis_stops_a_creature_that_fails_its_wisdom_save(tmp_path):
    """"A creature attempting to enter a space within 5 feet of the bearer makes a Wisdom saving throw. Failed Save: It
    cannot enter that space until the start of its next turn." """
    assert "A creature attempting to enter a space within 5 feet of the bearer makes a Wisdom saving throw." in printed(PR + "impedance")
    assert record(PR + "impedance")["coverage"] == "FULL"
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 8, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    engine = combat._load_session(mid).engine
    assert (protection.aegises(engine.state.actors[OWNER], OWNER)[0][1].data or {})["feet"] == 5
    await_actor(table, mid, FOE)
    move_to(table, mid, 5, 6)  # the first square inside 5 feet of the bearer
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    assert [row["ability"] for row in rolls] == ["WIS"], [(row["ability"], row["source"]) for row in rolls]
    assert not rolls[-1]["success"] and rolls[-1]["dc"] == UNREADABLE  # the printed save, and it really failed
    assert at(engine, FOE) == (6, 6)  # the step that would have entered is refused
    held = conditions(engine, FOE, protection.APRON)
    assert len(held) == 1 and (held[0].data or {}).get("feet") == 5 and held[0].data["anchor"] == OWNER
    assert "Impedance Aegis" in said(engine)
    assert not offered_move(table, mid, 5, 6)
    assert at(reload(tmp_path, mid), FOE) == (6, 6)


def test_a_creature_that_passes_the_impedance_save_moves_normally(tmp_path):
    """"Successful Save: It may move normally." """
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], owner_dc=TRIVIAL,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 8, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 5, 6)
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    assert rolls and all(row["ability"] == "WIS" for row in rolls)
    assert rolls[-1]["success"] and rolls[-1]["dc"] == TRIVIAL  # "Successful Save: It may move normally."
    assert at(engine, FOE) == (5, 6)
    assert not conditions(engine, FOE, protection.APRON)


def test_the_impedance_aegis_survives_a_table_commit_and_reload(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 8, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "10"})
    engine = reload(tmp_path, mid)
    bearer = engine.state.actors[OWNER]
    assert [held.condition_id for _key, held in protection.aegises(bearer, OWNER)] == [protection._mark_ids(OWNER)[0]]
    assert (protection.aegises(bearer, OWNER)[0][1].data or {})["feet"] == 10  # the chosen distance is in the saved fight


def test_a_failed_impedance_save_holds_until_the_movers_own_next_turn(tmp_path):
    """"until the start of its next turn" -- the failing creature's own turn, not an intervening turn of the caster's.

    The restriction is checked across a full round boundary and through a real table commit plus reload, so the sealed
    engine's own early-removal name ("START_OF_TARGET_NEXT_TURN", which ends at whichever of the two turns comes first)
    cannot pass here: the caster's turn comes between the failure and the foe's next turn."""
    from combat.ext import effect_durations

    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 8, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 5, 6)
    engine = combat._load_session(mid).engine
    turn = int(engine.state.actors[FOE].turns_started) + 1
    held = conditions(engine, FOE, protection.APRON)
    assert held[0].expires_on == effect_durations.token("start", FOE, turn) == f"START_OF_TURN_AT:{FOE}:{turn}"
    assert held[0].expires_on != "START_OF_TARGET_NEXT_TURN"  # the early-removal name tests/test_expiry_names.py documents
    assert not offered_move(table, mid, 5, 6)
    end_turn(table, mid)                       # the foe's turn ends; the caster's turn begins
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    engine = combat._load_session(mid).engine
    assert conditions(engine, FOE, protection.APRON), "the caster's turn must not end the foe's restriction"
    assert conditions(reload(tmp_path, mid), FOE, protection.APRON)  # ... and it is still there after commit and reload
    await_actor(table, mid, FOE)               # the foe's own next turn starts
    assert not conditions(combat._load_session(mid).engine, FOE, protection.APRON)
    assert offered_move(table, mid, 5, 6)


def test_a_failed_impedance_save_stops_a_second_step_and_a_detouring_path(tmp_path):
    """The printed bar is about the creature, not about one step. A second step into the protected space is not even
    offered, and a route whose *destination* is well outside the protected space is not offered either because a square in
    the middle of its path is not: the whole canonical path is read, not only where it ends."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 4, "y": 14}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    engine = combat._load_session(mid).engine
    assert engine.grid.distance_ft((4, 14), engine.state.actors[OWNER].position) == 40
    await_actor(table, mid, FOE)
    move_to(table, mid, 4, 5)  # walks up the column until the square beside the bearer, and is stopped there
    engine = combat._load_session(mid).engine
    assert at(engine, FOE) == (4, 8)
    assert conditions(engine, FOE, protection.APRON)
    assert not offered_move(table, mid, 4, 7), "a second step into the protected space was offered"
    assert len(saves(engine, FOE, "action:typed.")) == 1
    assert engine.grid.distance_ft((4, 2), engine.state.actors[OWNER].position) == 20  # so a destination test would allow it
    assert not offered_move(table, mid, 4, 2), "a route whose path runs through the protected space was offered"
    await_actor(table, mid, FOE, first=True)   # the mover's own next turn: the printed bar has ended
    engine = combat._load_session(mid).engine
    assert not conditions(engine, FOE, protection.APRON)
    assert offered_move(table, mid, 4, 2), "the same route is a legal move once the printed bar has ended"


def test_movement_granted_by_an_ability_still_stops_at_the_bar(tmp_path):
    """Movement an ability grants never passes through the Move menu -- combat/granted_movement.py builds those
    destinations itself -- so the step gate is the only thing between a granted step and the protected space. Reeling
    Step's ten feet are asked for here and the gate's own refusal is read straight out of the engine's step dispatch."""
    from combat.movement_steps import checkpoint

    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"],
                                       foe_talents=["SAND_BASE_SCOURING_HAND", REELING_STEP],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 7, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 6, 6)
    move_to(table, mid, 5, 6)  # the printed save fails and the bar is on the foe
    engine = combat._load_session(mid).engine
    mover = engine.state.actors[FOE]
    assert at(engine, FOE) == (6, 6) and conditions(engine, FOE, protection.APRON)
    assert not offered_move(table, mid, 5, 6)
    # Reeling Step is offered and its ten feet are asked for; the squares of the protected space are not among them.
    menu = table.state(mid)["menu"]
    result = table.act(mid, option(table, mid, "Reeling Step"), menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "REACTION_REQUIRED"
    answers = []
    asked = []
    for _ in range(6):
        reaction = result["reaction"]
        choice = reaction.get("choice") or reaction["context"].get("choice") or {}
        asked.append(reaction["context"].get("reaction_source_id"))
        answer = {**reaction["context"], "selection": "DECLINE"}
        if choice.get("options"):
            answer.update(selection="USE", option_ids=[choice["options"][0]["id"]])
        answers.append(answer)
        result = table.act(mid, option(table, mid, "Reeling Step"), menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
    assert "choice:needle.drunken_reeling_move" in asked
    # And the gate itself: a step into the protected space that no menu ever offered is refused, in the printed words.
    inside = type(mover.position)(x=5, y=6, z=0)
    replies = checkpoint(engine, mover, mover.position, inside, None, travelled_ft=0, remaining_ft=5, point="movement_attempt")
    assert replies and replies[0]["stop"] is True
    assert "cannot come within 5 feet of the bearer" in replies[0]["label"]
    assert at(engine, FOE) == (6, 6)
    assert "Impedance Aegis: Foe already failed its Wisdom save" in said(engine)


def test_a_creature_already_inside_the_protected_space_is_asked_again(tmp_path):
    """"A creature attempting to enter a space within 5 feet of the bearer": the square being entered is what counts, so a
    creature already standing in the protected space is asked again when it steps to another square inside it."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 5, 5)  # a different square, still within 5 feet of the bearer
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    assert [row["ability"] for row in rolls] == ["WIS"] and not rolls[-1]["success"]
    assert at(engine, FOE) == (5, 6)
    assert conditions(engine, FOE, protection.APRON)


def test_the_impedance_aegis_asks_the_bearer_too(tmp_path):
    """The printed trigger says "A creature" and no more, so the bearer is asked like anyone else rather than quietly
    except. This is the reading this lane chose, and the report flags it as a ruling for the table."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 8, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "$first"})
    await_actor(table, mid, FOE)
    end_turn(table, mid)
    await_actor(table, mid, OWNER)
    move_to(table, mid, 5, 7)  # the bearer stepping to a square within 5 feet of itself
    engine = combat._load_session(mid).engine
    rolls = saves(engine, OWNER, "action:typed.")
    assert [row["ability"] for row in rolls] == ["WIS"] and not rolls[-1]["success"]
    assert at(engine, OWNER) == (4, 6)
    assert conditions(engine, OWNER, protection.APRON)


def test_impedance_augment_pays_one_more_for_ten_feet(tmp_path):
    """"Augment - 1 CP: Increase the protected distance to 10 feet." """
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"])
    before = combat._load_session(mid).engine.state.actors[OWNER].resources.get(QI, 0)
    play(table, mid, option(table, mid, "Aegis: Impedance"), {IMPEDANCE: "10"})
    engine = combat._load_session(mid).engine
    assert (protection.aegises(engine.state.actors[OWNER], OWNER)[0][1].data or {})["feet"] == 10
    assert engine.state.actors[OWNER].resources.get(QI, 0) == before - 1


# ----------------------------------------------------------------------------------------- Impedance, the Ward
def test_the_impedance_ward_asks_once_a_turn_and_keeps_creatures_out(tmp_path):
    """"A creature makes a Wisdom saving throw when it attempts to enter the Ward or move closer to the Ward's center for
    the first time on a turn. Failed Save: It cannot enter or move closer to the center until the start of its next turn." """
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}})
    _, prompts = play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    engine = combat._load_session(mid).engine
    zone = zone_of(engine, PR + "impedance")
    assert [prompt.get("title") for prompt in prompts] == ["Ward size"]  # nothing is asked about a distance to pay for
    assert "impedance" not in json.dumps(zone.trigger_profile)         # and the Ward stores no protected distance
    await_actor(table, mid, FOE)
    move_to(table, mid, 6, 6)  # one square outside the edge of a 20-foot Ward
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    assert [row["ability"] for row in rolls] == ["WIS"] and not rolls[-1]["success"]
    assert at(engine, FOE) == (9, 6)  # stopped on the rim, never inside
    held = conditions(engine, FOE, protection.APRON)
    assert len(held) == 1 and held[0].data["ward"] == zone.zone_id and held[0].data["bar"] == protection.NO_CLOSER
    assert "cannot enter this Ward or move closer to its centre" in said(engine)
    assert not offered_move(table, mid, 6, 6)
    move_to(table, mid, 9, 5)  # a step that neither enters the Ward nor closes on its centre is simply walking
    engine = combat._load_session(mid).engine
    assert at(engine, FOE) == (9, 5)
    assert len(saves(engine, FOE, "action:typed.")) == 1  # "for the first time on a turn"
    assert at(reload(tmp_path, mid), FOE) == (9, 5)


def test_the_impedance_ward_offers_no_paid_distance_and_says_what_it_blocks(tmp_path):
    """The printed augment belongs to the Aegis subsection, and the Ward's printed failure reads "cannot enter or move
    closer to the center" -- not "cannot come within 5 feet", which is a different restriction in a different talent. The
    Ward is also charged exactly what any other Ward costs the same caster: nothing was paid for a reach it cannot widen."""
    assert "Augment - 1 CP: Increase the protected distance to 10 feet." in printed(PR + "impedance").split("##### Ward")[0]
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance", PR + "energy_resistance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}})
    spent = lambda: 30 - combat._load_session(mid).engine.state.actors[OWNER].resources.get(QI, 0)
    _, prompts = play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    assert [prompt.get("title") for prompt in prompts] == ["Ward size"]   # nothing else was asked, so nothing else to pay
    impedance_cost = spent()
    await_actor(table, mid, FOE)
    move_to(table, mid, 6, 6)
    assert ("Impedance Ward: Foe fails its Wisdom save, so it cannot enter this Ward or move closer to its centre"
            in said(live(combat, mid)))
    assert "cannot come within 5 feet of this Ward" not in said(live(combat, mid))
    # "you may maintain only one Ward at a time": the next Ward is a different talent, and it costs what this one cost.
    await_actor(table, mid, OWNER, first=True)
    play(table, mid, option(table, mid, "Ward: Energy Resistance"), {WARD_SIZE: "$first"})
    assert spent() - impedance_cost == impedance_cost, "the Impedance Ward costs what any Ward costs"


def test_a_creature_far_outside_the_impedance_ward_walks_towards_it(tmp_path):
    """No printed rule reaches a step that neither enters the Ward nor closes on its centre from inside it."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 18, "y": 6}})
    play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 12, 6)  # 40 feet out: nearer the centre than it was, but nowhere near the Ward
    engine = combat._load_session(mid).engine
    assert at(engine, FOE) == (12, 6)
    assert not saves(engine, FOE, "action:typed.")
    assert not conditions(engine, FOE, protection.APRON)


def test_entering_the_impedance_ward_from_outside_is_asked_and_stopped(tmp_path):
    """"A creature attempting to enter the Ward or move closer to the Ward's center makes a Wisdom saving throw."

    Entering the Ward is a trigger in its own right, so membership is asked first and the centre-distance only decides the
    other half (a creature already inside closing in). Both facts of this test -- where the creature starts and where the
    step ends -- are read with the very query the crossing gate uses, so it is the entry half being proved rather than a
    step that merely happens to get closer."""
    from combat.gate2_runtime_models import Position
    from combat.spatial_areas import zone_contains

    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 8, "y": 7}})
    play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    engine = combat._load_session(mid).engine
    zone = zone_of(engine, PR + "impedance")
    foe = engine.state.actors[FOE]
    outside, inside = Position(x=8, y=7), Position(x=8, y=6)
    assert not zone_contains(engine, foe, zone, at=outside), "the step must really start outside the Ward"
    assert zone_contains(engine, foe, zone, at=inside), "the step must really end inside it"
    assert protection._ward_step_breaks(engine, foe, zone, outside, inside), "entering is the printed trigger"
    await_actor(table, mid, FOE)
    move_to(table, mid, 8, 6)
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    assert [row["ability"] for row in rolls] == ["WIS"] and not rolls[-1]["success"]
    assert at(engine, FOE) == (8, 7)  # stopped on the rim, still outside
    assert conditions(engine, FOE, protection.APRON)
    assert at(reload(tmp_path, mid), FOE) == (8, 7)


def test_a_creature_may_walk_out_of_the_impedance_ward(tmp_path):
    """"enter the Ward or move closer to the Ward's center" -- neither half of that sentence reaches a step that *leaves* the
    Ward. A creature standing inside is neither asked nor stopped on its way out, however close to the centre the square it
    stood on was, and it ends the step outside the sphere."""
    from combat.gate2_runtime_models import Position
    from combat.spatial_areas import zone_contains

    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}})
    play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    engine = combat._load_session(mid).engine
    zone = zone_of(engine, PR + "impedance")
    foe = engine.state.actors[FOE]
    assert zone_contains(engine, foe, zone, at=Position(x=6, y=6)), "the creature really starts inside the Ward"
    assert not zone_contains(engine, foe, zone, at=Position(x=9, y=6)), "the step really ends outside it"
    assert protection._ward_step_breaks(engine, foe, zone, Position(x=6, y=6), Position(x=9, y=6)) is False, (
        "walking out of a Ward was read as entering or closing in")
    await_actor(table, mid, FOE)
    move_to(table, mid, 9, 6)   # straight out, and every step of it moves further from the centre
    engine = combat._load_session(mid).engine
    assert at(engine, FOE) == (9, 6), "walking out of a Ward was stopped"
    assert not saves(engine, FOE, "action:typed."), "walking out of a Ward asked for a save"
    assert not conditions(engine, FOE, protection.APRON)
    assert at(reload(tmp_path, mid), FOE) == (9, 6)


def test_the_stored_ward_bar_lets_the_failing_creature_out_and_still_keeps_it_out_of_the_ward(tmp_path):
    """The bar a failed save leaves -- "It cannot enter this Ward or move closer to its centre until the start of its next
    turn" -- is about entering and closing in, so the creature that holds it may still leave the Ward, and may not come back
    in. Both halves are read after a real table commit and a reload, so the bar is proved to be saved state, not a
    turn-boundary memory."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}})
    play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 5, 6)   # from inside the Ward, one square closer to its centre: the printed save fails
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    held = conditions(engine, FOE, protection.APRON)
    assert [row["ability"] for row in rolls] == ["WIS"] and not rolls[-1]["success"]
    assert at(engine, FOE) == (6, 6) and len(held) == 1 and (held[0].data or {}).get("bar") == protection.NO_CLOSER
    assert offered_move(table, mid, 5, 6) is False      # closing in is refused
    assert offered_move(table, mid, 9, 6), "the bar also refused the walk out of the Ward"
    move_to(table, mid, 9, 6)                          # ... so take it
    engine = reload(tmp_path, mid)                     # the bar survives a commit and a reload
    assert at(engine, FOE) == (9, 6)
    assert conditions(engine, FOE, protection.APRON), "the saved bar is gone"
    assert not offered_move(table, mid, 8, 6), "the reloaded bar let the creature back into the Ward"
    assert not offered_move(table, mid, 6, 6)


def test_a_creature_inside_the_impedance_ward_is_asked_when_it_closes_on_the_centre(tmp_path):
    """The other half of the printed trigger: from inside, moving closer to the Ward's centre is what is refused."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "impedance"], speed_ft=90,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}})
    play(table, mid, option(table, mid, "Ward: Impedance"), {WARD_SIZE: "$first"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 5, 6)  # from inside the Ward, one square closer to its centre
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE, "action:typed.")
    assert [row["ability"] for row in rolls] == ["WIS"] and not rolls[-1]["success"]
    assert at(engine, FOE) == (6, 6)
    assert conditions(engine, FOE, protection.APRON)


# ----------------------------------------------------------------------------------------- Repel Spirit-Kin
def test_repel_spirit_kin_turns_away_a_chosen_family(tmp_path):
    """"A chosen creature attempting to cross the Ward's edge makes a Charisma saving throw. Failed Save: It cannot cross." """
    assert record(PR + "repel_spirit_kin")["coverage"] == "FULL"
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "repel_spirit_kin"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}},
                                       bundle_transform=kind("Undead"))
    play(table, mid, option(table, mid, "Ward: Repel Spirit-Kin"), {WARD_SIZE: "$first", REPEL: "undead"})
    engine = combat._load_session(mid).engine
    zone = zone_of(engine, PR + "repel_spirit_kin")
    assert zone.trigger_profile["profile"]["repel"]["families"] == ["undead"]
    assert FOE not in zone.trigger_profile["profile"]["repel"]["inside"]  # the foe was outside when the Ward appeared
    await_actor(table, mid, FOE)
    move_to(table, mid, 8, 6)  # across the edge
    engine = combat._load_session(mid).engine
    rolls = saves(engine, FOE)
    assert [row["ability"] for row in rolls] == ["CHA"] and not rolls[-1]["success"]
    assert at(engine, FOE) == (9, 6)  # it never crossed
    assert "Repel Spirit-Kin Ward" in said(engine)
    assert at(reload(tmp_path, mid), FOE) == (9, 6)


def test_a_paid_crossing_keeps_its_immunity_when_the_caster_makes_the_ward_again(tmp_path):
    """"Successful Save: It may cross and becomes immune to your Repel Spirit-Kin Ward until the next dawn." The printed
    immunity is to the caster's Ward, so a fresh Ward from the same caster is the same Ward to a creature that already
    paid to cross it -- across a table commit and a reload in the middle."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "repel_spirit_kin"], owner_dc=TRIVIAL,
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}},
                                       bundle_transform=kind("Undead"))
    play(table, mid, option(table, mid, "Ward: Repel Spirit-Kin"), {WARD_SIZE: "$first", REPEL: "undead"})
    first = zone_of(combat._load_session(mid).engine, PR + "repel_spirit_kin").zone_id
    await_actor(table, mid, FOE)
    move_to(table, mid, 8, 6)  # crosses and passes the printed save
    engine = combat._load_session(mid).engine
    paid = conditions(engine, FOE, protection.REPEL_BAR)
    assert len(paid) == 1 and paid[0].data["caster"] == OWNER
    end_turn(table, mid)
    play(table, mid, option(table, mid, "Ward: Repel Spirit-Kin"), {WARD_SIZE: "$first", REPEL: "undead"})
    second = zone_of(combat._load_session(mid).engine, PR + "repel_spirit_kin").zone_id
    assert second != first, "the Ward was really replaced"
    assert conditions(reload(tmp_path, mid), FOE, protection.REPEL_BAR)
    asked = len(saves(live(combat, mid), FOE))          # the save that bought the crossing, and nothing since
    await_actor(table, mid, FOE)
    move_to(table, mid, 9, 6)  # back out through the new Ward's edge
    engine = live(combat, mid)
    assert len(saves(engine, FOE)) == asked, "the printed immunity was lost when the caster re-made the Ward"
    assert at(engine, FOE) == (9, 6)


def test_repel_spirit_kin_leaves_other_families_alone(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "repel_spirit_kin"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}},
                                       bundle_transform=kind("Humanoid"))
    play(table, mid, option(table, mid, "Ward: Repel Spirit-Kin"), {WARD_SIZE: "$first", REPEL: "undead"})
    await_actor(table, mid, FOE)
    move_to(table, mid, 8, 6)
    engine = combat._load_session(mid).engine
    assert at(engine, FOE) == (8, 6)
    assert not saves(engine, FOE, "action:typed.")


def test_a_creature_already_inside_the_ward_is_unaffected(tmp_path):
    """"A creature already inside when the Ward appears is unaffected." -- printed without "hostile", so an undead ally
    standing inside when it appears is exempt too, and the exemption is read off the Ward's own volume."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "repel_spirit_kin"], allies=[FOE],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}},
                                       bundle_transform=kind("Undead"))
    play(table, mid, option(table, mid, "Ward: Repel Spirit-Kin"), {WARD_SIZE: "$first", REPEL: "undead"})
    engine = combat._load_session(mid).engine
    assert engine.state.actors[FOE].team_id == engine.state.actors[OWNER].team_id
    assert FOE in zone_of(engine, PR + "repel_spirit_kin").trigger_profile["profile"]["repel"]["inside"]
    await_actor(table, mid, FOE)
    move_to(table, mid, 9, 6)  # straight out through the edge
    engine = combat._load_session(mid).engine
    assert at(engine, FOE) == (9, 6)
    assert not saves(engine, FOE, "action:typed.")
    assert not conditions(engine, FOE, protection.REPEL_BAR)


# ----------------------------------------------------------------------------------------- Shielded
def test_shielded_is_suppressed_while_both_hands_hold_something_else(tmp_path):
    """"If the bearer uses the shield-hand to hold another object, the shield is suppressed" -- one hand has to be free for
    the shield itself, read from the same occupancy every other hand rule uses, and the Armor Class the table shows is
    the printed +2 with a free hand and nothing without one."""
    for name, kit, wanted in (("free", ONE_HAND, 16), ("busy", TWO_HANDS, 14)):
        combat, table, mid = table_fixture(tmp_path / name, [*BASE, PR + "shielded"], owner_kit=kit)
        play(table, mid, option(table, mid, "Aegis: Shielded"))
        engine = combat._load_session(mid).engine
        bearer = engine.state.actors[OWNER]
        assert protection._with(bearer, PR + "shielded")
        assert (protection._spell_shield(engine, bearer) == (2 if name == "free" else 0))
        assert armor_class(table, mid, OWNER) == wanted
        await_actor(table, mid, OWNER, first=True)
        assert armor_class(table, mid, OWNER) == wanted


def test_shielded_comes_back_at_the_start_of_the_next_turn_in_which_the_hand_is_free(tmp_path):
    """"the shield is suppressed until the start of the next turn in which that hand is free." The bearer's Armor Class as
    the table shows it drops while both hands hold something, and comes back only at a turn start with a hand free -- never
    in the middle of the turn -- and the suppression is a saved condition rather than something an Armor Class query
    writes."""
    assert record(PR + "shielded")["coverage"] != "FULL"  # the proficiency augment is still the table's to run
    assert "Augment - 1 CP: The bearer is treated as proficient with the shield." in record(PR + "shielded")["riders"]
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "shielded"], owner_kit=TWO_HANDS)
    play(table, mid, option(table, mid, "Aegis: Shielded"))
    assert armor_class(table, mid, OWNER) == 14
    await_actor(table, mid, OWNER, first=True)   # a turn boundary with no hand free: the suppression is remembered
    engine = combat._load_session(mid).engine
    assert len(conditions(engine, OWNER, protection.SHIELD_OFF)) == 1
    assert armor_class(table, mid, OWNER) == 14
    play(table, mid, option(table, mid, "Stow Dao"))  # a hand frees in the middle of the turn
    assert armor_class(table, mid, OWNER) == 14, "the +2 came back in the same turn"
    engine = reload(tmp_path, mid)
    assert conditions(engine, OWNER, protection.SHIELD_OFF), "the suppression must survive a commit and a reload"
    assert armor_class(table, mid, OWNER) == 14
    await_actor(table, mid, OWNER, first=True)   # the start of the next turn, in which that hand is free
    engine = combat._load_session(mid).engine
    assert not conditions(engine, OWNER, protection.SHIELD_OFF)
    assert armor_class(table, mid, OWNER) == 16


def test_shielded_is_suppressed_the_moment_a_hand_is_used_and_waits_for_the_next_turn(tmp_path):
    """"If the bearer uses the shield-hand to hold another object, the shield is suppressed until the start of the next turn
    in which that hand is free." The suppression is recorded by the transaction that occupies the hand -- a weapon drawn in
    the middle of a turn, with no turn boundary anywhere near -- so freeing the hand again before the next turn starts does
    NOT hand the +2 back. The recovery is the next turn start and nothing else, and the remembered suppression is saved
    state: it is still there after a commit and a reload."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "shielded"], owner_kit=TWO_HANDS)
    play(table, mid, option(table, mid, "Aegis: Shielded"))
    await_actor(table, mid, OWNER, first=True)    # both hands hold a weapon: remembered, no +2
    assert armor_class(table, mid, OWNER) == 14
    play(table, mid, option(table, mid, "Stow Dao"))   # a hand frees in the middle of the turn
    assert armor_class(table, mid, OWNER) == 14, "the +2 came back in the same turn"
    assert conditions(reload(tmp_path, mid), OWNER, protection.SHIELD_OFF), "the suppression must survive commit and reload"
    await_actor(table, mid, OWNER, first=True)   # the start of the next turn, in which that hand is free
    assert not conditions(combat._load_session(mid).engine, OWNER, protection.SHIELD_OFF)
    assert armor_class(table, mid, OWNER) == 16
    play(table, mid, option(table, mid, "Draw Dao"))   # the hand is used again, mid-turn
    assert armor_class(table, mid, OWNER) == 14, "occupying a hand mid-turn did not suppress the shield"
    assert len(conditions(combat._load_session(mid).engine, OWNER, protection.SHIELD_OFF)) == 1
    play(table, mid, option(table, mid, "Stow Dao"))   # ... and freed again in the same turn
    assert armor_class(table, mid, OWNER) == 14, "the +2 came back in the same turn"
    assert conditions(reload(tmp_path, mid), OWNER, protection.SHIELD_OFF)
    await_actor(table, mid, OWNER, first=True)   # the next turn start, in which that hand is free again
    assert not conditions(combat._load_session(mid).engine, OWNER, protection.SHIELD_OFF)
    assert armor_class(table, mid, OWNER) == 16


def test_shielded_is_suppressed_as_soon_as_it_is_made_with_both_hands_busy(tmp_path):
    """A Shielded Aegis made while both hands already hold something is suppressed at once -- the printed condition is a
    fact about the hands, not something that waits for a turn boundary -- and a hand freed later that same turn still does
    not bring the +2 back before the next turn starts."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "shielded"], owner_kit=TWO_HANDS)
    play(table, mid, option(table, mid, "Aegis: Shielded"))
    engine = combat._load_session(mid).engine
    assert armor_class(table, mid, OWNER) == 14, "a shield with no free hand is not working"
    assert conditions(engine, OWNER, protection.SHIELD_OFF), "the suppression was not recorded when the Aegis was made"
    play(table, mid, option(table, mid, "Stow Dao"))   # a hand frees in the same turn the Aegis was made
    assert armor_class(table, mid, OWNER) == 14
    assert conditions(reload(tmp_path, mid), OWNER, protection.SHIELD_OFF)
    await_actor(table, mid, OWNER, first=True)   # the next turn start, in which that hand is free
    assert armor_class(table, mid, OWNER) == 16
    assert not conditions(combat._load_session(mid).engine, OWNER, protection.SHIELD_OFF)


def test_ending_the_shielded_aegis_takes_its_suppression_with_it(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "shielded"], owner_kit=TWO_HANDS)
    play(table, mid, option(table, mid, "Aegis: Shielded"))
    await_actor(table, mid, OWNER, first=True)
    assert conditions(combat._load_session(mid).engine, OWNER, protection.SHIELD_OFF)
    end_turn(table, mid)
    await_actor(table, mid, OWNER)
    act(table, mid, option(table, mid, "End an Aegis you made"))
    engine = combat._load_session(mid).engine
    assert not protection._with(engine.state.actors[OWNER], PR + "shielded")
    assert not conditions(engine, OWNER, protection.SHIELD_OFF)
    assert armor_class(table, mid, OWNER) == 14


# ----------------------------------------------------------------------------------------- Status
def test_status_names_every_aegis_bearer_with_its_direction_and_distance(tmp_path):
    """"You always know: the direction and distance to creatures benefiting from one of your Aegises" -- every bearer, read
    after a real move at a real turn boundary and through a real commit and reload."""
    assert record(PR + "status")["coverage"] == "FULL"
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", PR + "energy_resistance"], allies=[SECOND],
                                       positions={OWNER: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}, FOE: {"x": 20, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Armored Aegis", target=SECOND))
    await_actor(table, mid, OWNER, first=True)   # one action a turn: the second Aegis is a new turn
    play(table, mid, option(table, mid, "Aegis: Energy Resistance"))
    engine = combat._load_session(mid).engine
    assert protection._with(engine.state.actors[OWNER], PR + "energy_resistance")
    assert protection._with(engine.state.actors[SECOND], "PROTECTION_BASE_ARMORED_AEGIS")
    await_actor(table, mid, SECOND)
    move_to(table, mid, 4, 12)   # the second bearer walks away
    await_actor(table, mid, OWNER, first=True)
    lines = [row for row in log(combat._load_session(mid).engine).splitlines() if row.startswith("Status:")]
    assert lines, log(combat._load_session(mid).engine)[-800:]
    assert lines[-1] == "Status: Owner is right here, unharmed; Second is 30 feet south away, unharmed", lines[-1]
    engine = reload(tmp_path, mid)
    await_actor(table, mid, OWNER, first=True)
    lines = [row for row in log(engine).splitlines() if row.startswith("Status:")]
    assert lines[-1] == "Status: Owner is right here, unharmed; Second is 30 feet south away, unharmed", lines[-1]


def test_status_says_what_a_committed_hit_did_to_a_bearer(tmp_path):
    """"whether they are unharmed, wounded, ... dying ..." read from the creature's own hit points and life state, so a
    hit the fight really committed -- not a number a test wrote -- is what the line reports."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", PR + "energy_resistance"], hp=200,
                                       foe_talents=["SAND_BASE_SCOURING_HAND", LASH],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Energy Resistance"))
    await_actor(table, mid, FOE)
    play(table, mid, option(table, mid, "Lightning Lash", target=OWNER))
    engine = combat._load_session(mid).engine
    assert [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"], "the fight really committed damage"
    bearer = engine.state.actors[OWNER]
    assert bearer.current_hp < bearer.maximum_hp, "the committed hit really wounded the bearer"
    await_actor(table, mid, OWNER, first=True)
    line = [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    assert ("disabled" if bearer.current_hp * 2 <= bearer.maximum_hp else "wounded") in line, line
    assert "unharmed" not in line, line


def test_status_reports_a_bearer_that_is_dying(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", PR + "energy_resistance"], hp=6,
                                       foe_talents=["SAND_BASE_SCOURING_HAND", LASH],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Energy Resistance"))
    await_actor(table, mid, FOE)
    play(table, mid, option(table, mid, "Lightning Lash", target=OWNER))
    engine = live(combat, mid)
    bearer = engine.state.actors[OWNER]
    assert bearer.current_hp == 0
    # "You always know" is not a once-a-turn report: the line the owner is given as the hit lands is the one that counts.
    line = [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    assert {None: "at 0 hit points", "DYING": "dying", "STABLE": "stable"}[bearer.life_state] in line, line
    assert "unharmed" not in line and "wounded" not in line, line
    assert at(reload(tmp_path, mid), OWNER) == (4, 6)


def test_status_watches_every_aegis_bearer_until_the_aegis_ends(tmp_path):
    """"whether they are unharmed, ... dying ..." -- a bearer the fight has knocked to 0 HP is dying, which is what the
    printed list says, and the owner stops being told about a creature the moment it no longer bears its Aegis."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", PR + "energy_resistance"], hp=6,
                                       foe_talents=["SAND_BASE_SCOURING_HAND", LASH], allies=[SECOND],
                                       positions={OWNER: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}, FOE: {"x": 9, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Armored Aegis", target=SECOND))
    await_actor(table, mid, OWNER, first=True)   # one action a turn: the second Aegis is a new turn
    play(table, mid, option(table, mid, "Aegis: Energy Resistance"))
    await_actor(table, mid, OWNER, first=True)
    line = [row for row in log(live(combat, mid)).splitlines() if row.startswith("Status:")][-1]
    assert line == "Status: Owner is right here, unharmed; Second is 5 feet south away, unharmed", line
    # "An Aegis may be ended early by its creator without spending an action": the awareness ends with the Aegis.
    ends = [choice["candidate_id"] for group in table.state(mid)["menu"]["actions"]
            if group["label"].startswith("End an Aegis") for choice in group["options"]
            if SECOND in (choice.get("target_ids") or ())]
    assert ends, [(group["label"], [choice.get("target_ids") for choice in group["options"]])
                  for group in table.state(mid)["menu"]["actions"] if "Aegis" in group["label"]]
    act(table, mid, ends[0])
    engine = live(combat, mid)
    assert not protection._with(engine.state.actors[SECOND], "PROTECTION_BASE_ARMORED_AEGIS")
    line = [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    assert "Second" not in line, line
    await_actor(table, mid, FOE)
    play(table, mid, option(table, mid, "Lightning Lash", target=OWNER))   # a real committed hit on the watched bearer
    engine = live(combat, mid)
    bearer = engine.state.actors[OWNER]
    assert bearer.current_hp == 0, "the bearer really fell"
    line = [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    assert {None: "at 0 hit points", "DYING": "dying", "STABLE": "stable"}[bearer.life_state] in line, line


def test_status_names_the_bearing_it_actually_has(tmp_path):
    """A bearer ten squares east and one square north is east, not north-east: the compass point nearest the true bearing,
    not the nearest unit step to the displacement."""
    engine = flat_grid(False)

    place = spot

    for offset, expected in (((1, 0), "east"), ((1, -1), "north-east"), ((10, -1), "east"), ((1, -10), "north"),
                             ((-3, 2), "west"), ((2, 3), "south-east"), ((-4, -1), "west")):
        assert protection._where(engine, place(20, 20), place(20 + offset[0], 20 + offset[1])).endswith(f"{expected} away"), offset
    assert protection._where(engine, place(20, 20), place(20, 20)) == "right here"


def test_status_says_which_height_a_bearer_is_at_when_the_fight_tracks_it(tmp_path):
    engine = flat_grid(True)

    place = spot

    assert protection._where(engine, place(20, 20, 0), place(24, 20, 2)).endswith("20 feet east away, 10 feet up")
    assert protection._where(engine, place(20, 20, 0), place(24, 20, 0)).endswith("20 feet east away")
    assert protection._where(engine, place(20, 20, 2), place(24, 20, 0)).endswith("20 feet east away, 10 feet down")


@pytest.mark.parametrize("condition_id,word", [("frightened", "frightened"), ("diseased", "diseased"),
                                               ("poisoned", "poisoned"), ("stunned", "stunned"),
                                               ("unconscious", "unconscious"), ("charmed", "charmed"),
                                               ("restrained", "restrained"), ("exhaustion", "exhausted")])
def test_status_recognises_each_printed_affliction(condition_id, word):
    """"whether they are unharmed, wounded, disabled, frightened, unconscious, dying, poisoned, diseased, stunned, or
    similarly afflicted" -- every printed name is read off the bearer's own conditions, including diseased."""
    holder = type("Bearer", (), {"active": True, "current_hp": 500, "maximum_hp": 500, "temporary_hp": 0,
                                 "life_state": None, "conditions": {}})()
    assert protection._bearing(holder) == "unharmed"
    holder.conditions = {"instance": type("Held", (), {"condition_id": f"condition:typed.{condition_id}"})()}
    assert word in protection._bearing(holder)


def test_status_distinguishes_dying_from_stable_and_never_hides_a_wound_behind_temporary_hit_points():
    """"disabled" is this system's word for hurt badly and the line says so, and a creature's real hit points are what is
    read -- temporary hit points are a cushion and do not make a creature unharmed, nor hide a fall."""
    def bearer(current_hp: int, temporary_hp: int = 0, life_state=None, maximum_hp: int = 500):
        return type("Bearer", (), {"active": True, "current_hp": current_hp, "maximum_hp": maximum_hp,
                                    "temporary_hp": temporary_hp, "life_state": life_state, "conditions": {}})()

    assert protection._bearing(bearer(300)) == "wounded"
    assert protection._bearing(bearer(120)) == protection.DISABLED
    assert "below half its health" in protection.DISABLED
    assert protection._bearing(bearer(0, 400, "DYING")).startswith("dying")
    assert protection._bearing(bearer(0, 400, "STABLE")).startswith("stable")
    assert protection._bearing(bearer(0, 400)) == "at 0 hit points"
    assert protection._bearing(bearer(0, 400, None)) != "unharmed"
    assert protection._bearing(bearer(0, 0, "DYING")) .startswith("dying")


def test_status_refreshes_when_an_ordinary_heal_makes_a_bearer_unhurt_again(tmp_path):
    """"whether they are unharmed, wounded, ..." read live, not only at the owner's turn start: a plain heal moves hit points
    and nothing else -- no condition is applied or removed and no life state changes -- and the owner must still be told, in
    the same breath, that the bearer is no longer hurt. No turn boundary happens anywhere in this test, so the line can only
    have come from the healing itself."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", KINDLE], hp=200,
                                       foe_talents=["SAND_BASE_SCOURING_HAND", LASH], allies=[SECOND],
                                       positions={OWNER: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}, FOE: {"x": 9, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Armored Aegis", target=SECOND))
    await_actor(table, mid, FOE)
    play(table, mid, option(table, mid, "Lightning Lash", target=SECOND))   # a real committed hit on the watched bearer
    engine = live(combat, mid)
    assert [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"], "the fight really committed damage"
    wounded_hp = engine.state.actors[SECOND].current_hp
    assert wounded_hp < engine.state.actors[SECOND].maximum_hp, "the committed hit really wounded the bearer"
    assert "wounded" in [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    await_actor(table, mid, OWNER)
    play(table, mid, option(table, mid, "Kindle the Wounded Breath", target=SECOND))
    engine = live(combat, mid)
    healed = [index for index, event in enumerate(engine.events) if event.event_type == "HEALING_APPLIED"]
    assert healed, "the fight really healed somebody"
    bearer = engine.state.actors[SECOND]
    assert bearer.current_hp > wounded_hp, "the heal really raised the bearer's hit points"
    # The line has to come out of the healing itself: walk forward from the recorded healing and nothing else may precede
    # it. (This heal also applies conditions of its own, and a condition change was already enough to wake the owner up,
    # so "some Status line appears later in the log" would not prove anything about ordinary healing.)
    for event in engine.events[healed[-1] + 1:]:
        said_now = event.event_type == "PASSIVE_TRIGGERED" and str(event.payload.get("log") or "").startswith("Status:")
        assert said_now or event.event_type in ("PASSIVE_TRIGGERED", "HEALING_APPLIED"), (
            f"the healing produced no Status line of its own; the next recorded event was {event.event_type}")
        if said_now:
            assert "Second is" in str(event.payload["log"]) and protection._bearing(bearer) in str(event.payload["log"]), (
                str(event.payload["log"]), protection._bearing(bearer))
            break
    else:
        raise AssertionError("the healing produced no Status line at all")
    engine = reload(tmp_path, mid)
    assert protection._bearing(engine.state.actors[SECOND]) in [
        row for row in log(engine).splitlines() if row.startswith("Status:")][-1]


def test_status_refreshes_when_the_watcher_itself_moves(tmp_path):
    """"You always know: the direction and distance to creatures benefiting from one of your Aegises" -- the distance is
    measured from the owner, so the owner's own steps change what it should be told even when the creature that moved bears
    none of its Aegises. Here the only Aegis is on an ally, and the line arrives with the move, not at the next turn."""
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status"], allies=[SECOND],
                                       positions={OWNER: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}, FOE: {"x": 20, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Armored Aegis", target=SECOND))
    engine = live(combat, mid)
    assert not protection.aegises(engine.state.actors[OWNER], OWNER), "the owner bears no Aegis of its own here"
    assert protection.aegises(engine.state.actors[SECOND], OWNER), "the ally bears the owner's Aegis"
    line = [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    assert line == "Status: Second is 5 feet south away, unharmed", line
    move_to(table, mid, 4, 9)   # the watcher walks two squares past the bearer it is watching
    engine = live(combat, mid)
    assert at(engine, OWNER) == (4, 9)
    line = [row for row in log(engine).splitlines() if row.startswith("Status:")][-1]
    assert line == "Status: Second is 10 feet north away, unharmed", line
    assert at(reload(tmp_path, mid), OWNER) == (4, 9)


def test_status_is_quiet_without_the_talent(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "energy_resistance"],
                                       positions={OWNER: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Energy Resistance"))
    await_actor(table, mid, OWNER, first=True)
    assert not [row for row in log(combat._load_session(mid).engine).splitlines() if row.startswith("Status:")]
