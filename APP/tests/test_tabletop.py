"""Tabletop (owner 2026-09-25): drawn maps, human turns, the event stream, buttons and fog parity."""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import (
    TabletopError,
    TabletopMapStore,
    auto_buttons,
    normalize_custom_buttons,
    normalize_map,
    rasterize,
    sheet_summary,
    to_battlefield,
)
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import _install

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "tabletop"

MAP = {
    "display_name": "Courtyard", "width_squares": 16, "height_squares": 10,
    "walls": [
        {"shape": "rect", "points": [[6, 2], [8, 5]], "filled": True},
        {"shape": "circle", "points": [[12, 5], [13.2, 5]], "filled": True, "blocks": "sight"},
        {"shape": "line", "points": [[2.5, 8.5], [5.5, 8.5], [6.5, 9.5]]},
    ],
    "starts": {"team1": [[1, 4], [1, 6]], "team2": [[14, 4], [14, 6]]},
}


def test_walls_rasterise_into_blocked_and_sight_cells():
    document = normalize_map(MAP)
    blocked, sight = rasterize(document)
    assert {(6, 2), (7, 4)} <= blocked and (8, 2) not in blocked  # filled rectangle by cell centres
    assert (12, 5) in sight and (12, 5) not in blocked             # a sight-only circle can be walked through
    assert {(2, 8), (3, 8), (5, 8)} <= blocked                      # the freeform line
    arena = to_battlefield(document)
    grid = SquareGrid(arena)
    assert (12, 5) in grid.opaque and not grid.line_of_sight(Position(x=10, y=5), Position(x=14, y=5))
    assert not grid.line_of_sight(Position(x=5, y=3), Position(x=9, y=3))
    canonical_sha256(arena)  # sealed with a match: no floats anywhere
    assert arena["team_starts"]["team1"] == [{"x": 1, "y": 4}, {"x": 1, "y": 6}]


def test_map_validation_rejects_bad_input():
    for bad, code in (({**MAP, "width_squares": 500}, "MAP_SIZE_INVALID"),
                      ({**MAP, "walls": [{"shape": "star", "points": [[0, 0], [1, 1]]}]}, "MAP_WALL_INVALID"),
                      ({**MAP, "walls": [{"shape": "rect", "points": [[0, 0]]}]}, "MAP_WALL_INVALID"),
                      ({**MAP, "map_id": "../etc"}, "MAP_ID_INVALID"),
                      ({**MAP, "background": {"asset": "../../secret.png"}}, "MAP_BACKGROUND_INVALID")):
        with pytest.raises(TabletopError) as error:
            normalize_map(bad)
        assert error.value.code == code


def test_map_store_round_trip_and_background_checks(tmp_path):
    store = TabletopMapStore(tmp_path / "combat_maps")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    asset = store.save_asset(png, "image/png")
    saved = store.save({**MAP, "terrain": [{"type": "SIMPLE_COVER", "look": "boulder", "cells": [[3, 4]]}],
                        "background": {"asset": asset, "opacity": 0.5}})
    assert saved["cells"]["blocked"] and store.get("courtyard")["background"]["opacity"] == 0.5
    assert store.get("courtyard")["terrain"] == [{"type": "SIMPLE_COVER", "cells": [[3, 4]], "look": "boulder", "height_ft": 5}]
    assert "battlefield:map.courtyard" in store.arenas()
    with pytest.raises(TabletopError):
        store.save_asset(b"not an image", "image/png")
    with pytest.raises(TabletopError):
        store.save({**MAP, "background": {"asset": "0" * 64 + ".png"}})  # never uploaded
    store.delete("courtyard")
    assert store.list() == []


def test_rule_terrain_look_survives_map_normalization_and_rejects_unknown_look():
    doc = normalize_map({**MAP, "terrain": [{"type": "SIMPLE_COVER", "look": "boulder", "cells": [[3, 4]]}]})
    assert doc["terrain"] == [{"type": "SIMPLE_COVER", "cells": [[3, 4]], "look": "boulder", "height_ft": 5}]
    assert to_battlefield(doc)["tabletop"]["terrain"] == doc["terrain"]
    invalid = normalize_map({**MAP, "terrain": [{"type": "SIMPLE_COVER", "look": "not-an-object", "cells": [[3, 4]]}]})
    assert invalid["terrain"] == [{"type": "SIMPLE_COVER", "cells": [[3, 4]], "height_ft": 3}]


def test_a_human_turn_through_the_tabletop_service(tmp_path, monkeypatch):
    left, right = "a0000000-0000-4000-8000-000000000001", "a0000000-0000-4000-8000-000000000002"
    _install(tmp_path, left)
    _install(tmp_path, right)
    combat = CombatService(ROOT, tmp_path)
    original_sheet = combat._factory_owner_sheet

    def owner_sheet_with_superseded_qi_armor(project_id):
        sheet = original_sheet(project_id)
        sections = sheet.setdefault("selected_record_sections", {})
        sections.setdefault("talents", []).append({
            "record_id": "tianxia.path.qi_cultivation.feature.qi_armor",
            "display_name": "Qi Armor", "full_description": "Gain +3 AC until the start of your next turn.",
        })
        return sheet

    monkeypatch.setattr(combat, "_factory_owner_sheet", owner_sheet_with_superseded_qi_armor)
    combat.tabletop_maps.save(MAP)
    table = TabletopService(combat, tmp_path)
    view = combat.create_factory_match(project_ids=[left], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + right],
                                       control_modes={FACTORY_ACTOR_PREFIX + left: "MANUAL"}, arena_id="battlefield:map.courtyard",
                                       match_seed="TABLETOP-TEST")
    match_id = view["match_id"]
    state = table.state(match_id)
    combat_sheet = table.sheet(left)
    left_actor = next(row for row in state["presentation"]["actors"] if row["entity_id"] == FACTORY_ACTOR_PREFIX + left)
    assert combat_sheet["summary"]["armor_class"] == left_actor["defenses"][0]["value"]
    assert "wears" in combat_sheet["summary"]["armor_note"] and "refinement" in combat_sheet["summary"]["armor_note"]
    library_rows = [entry for group in combat_sheet["library"]["groups"] for sphere in group.get("spheres", [])
                    for entry in sphere.get("entries", [])]
    qi_armor = next(entry for entry in library_rows if entry["id"] == "tianxia.path.qi_cultivation.feature.qi_armor")
    assert "+5 AC" in qi_armor["text"] and "+3 AC" not in qi_armor["text"]
    positions = {row["entity_id"]: row["position"] for row in state["presentation"]["actors"]}
    assert positions[FACTORY_ACTOR_PREFIX + left] == {"x": 1, "y": 4} and positions[FACTORY_ACTOR_PREFIX + right] == {"x": 14, "y": 4}
    assert state["map"]["scale"] == 100 and len(state["map"]["walls"]) == 3
    after = state["last_sequence"]
    for _ in range(12):  # the AI side acts until it is the human's turn
        if state["menu"] and state["menu"].get("manual"):
            break
        result = table.auto_step(match_id, after)
        after, state = result["events"]["last_sequence"], result["state"]
    menu = state["menu"]
    assert menu["manual"] and menu["moves"] and menu["end_turn"]
    move = menu["moves"][0]
    result = table.act(match_id, move["candidate_id"], menu["decision_id"], menu["state_version"], after)
    assert any("moved" in row["summary"] for row in result["events"]["events"])
    with pytest.raises(TabletopError) as error:  # the same decision again is stale
        table.act(match_id, move["candidate_id"], menu["decision_id"], menu["state_version"], after)
    assert error.value.code == "TABLETOP_STALE"
    everything = table.events(match_id, 0)
    assert everything["last_sequence"] >= result["events"]["last_sequence"]
    assert all({"groups", "total", "kind"} <= set(row) for row in everything["dice"])
    table.delete_match(match_id)
    assert match_id not in {row["match_id"] for row in combat.list_matches()}
    with pytest.raises(TabletopError):
        table.delete_match(match_id)


def test_table_presents_blood_armor_ac_and_engine_speed_after_real_action(tmp_path, monkeypatch):
    from copy import deepcopy
    from zipfile import ZipFile

    sheet = deepcopy(SHEET)
    sheet["identity"]["cultivation_level"] = 5
    abilities = json.loads(sheet["ability_scores_and_statistics"]["abilities"])
    abilities[0].update(score=4, modifier=-3)
    sheet["ability_scores_and_statistics"]["abilities"] = json.dumps(abilities)
    sheet["equipment"][0]["starting_kit"]["items"].extend([
        {"item_id": "tianxia.mortal.armor.full_lamellar_battle_dress"},
        {"item_id": "tianxia.mortal.weapon.nu_gong"},
    ])
    sheet["spheres_and_talents"]["sphere_record_ids"].append("tianxia.sphere.blood")
    sheet["spheres_and_talents"]["learned_talent_record_ids"].append("tianxia.talent.blood.blood_armor")
    for project in ("left", "right"):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    # Exercise damage formatting through the real sheet service, with one row
    # carrying bad formula data while all other buttons retain their real values.
    monkeypatch.setattr(table.buttons, "get", lambda _project_id: {})
    # This display fixture uses synthetic project names instead of production UUIDs.
    monkeypatch.setattr(table.buttons, "_path", lambda project: tmp_path / "buttons" / f"{project}.json")
    from types import SimpleNamespace
    monkeypatch.setattr(table, "_picture_store", lambda: SimpleNamespace(url=lambda _project_id: None))
    original_bundle = table._bundle_and_summary
    known_bonus = {"value": None}
    chosen_ids = []

    def with_display_regressions(project_id):
        owner_sheet, bundle, summary = original_bundle(project_id)
        bundle = deepcopy(bundle)
        rows = [row for row in bundle.get("action_catalog") or []
                if not (row.get("parameters") or {}).get("typed", {}).get("augments")]
        assert len(rows) >= 2
        chosen_ids[:] = [row["source_definition_id"] for row in rows[:2]]
        for row, formula in ((rows[0], "not_a_real_formula"), (rows[1], "key_ability_modifier")):
            typed = row.setdefault("parameters", {}).setdefault("typed", {})
            if formula == "key_ability_modifier":
                known_bonus["value"] = int((typed.get("numbers") or {}).get("key_mod", 0))
            typed.setdefault("effects", []).append({"type": "damage", "dice": {"count": 1, "sides": 4},
                                                       "formula": formula, "damage_types": ["FIRE"]})
            if formula == "not_a_real_formula":
                typed["effects"].append({"type": "damage", "dice": {"count": 1, "sides": 4},
                                         "formula": "text:your proficiency bonus and +1 AC", "damage_types": ["FIRE"]})
                typed["effects"].extend([
                    {"type": "damage", "dice": {"count": 2, "count_formula": "triple_pb", "sides": 8},
                     "damage_types": ["FIRE"]},
                    {"type": "damage", "dice": {"count": 0, "count_formula": "pb", "sides": 8, "bonus": 4},
                     "damage_types": ["FIRE"]},
                ])
        return owner_sheet, bundle, summary

    monkeypatch.setattr(table, "_bundle_and_summary", with_display_regressions)
    rendered = table.sheet("left")["buttons"]
    assert any("a bonus decided when it hits" in (row.get("detail", {}).get("damage") or "") for row in rendered)
    assert all("not_a_real_formula" not in json.dumps(row) for row in rendered)
    unknown_button = next(row for row in rendered if row["id"] == f"act:{chosen_ids[0]}")
    assert "2d8 fire + 4 fire" in unknown_button["detail"]["damage"]
    known_button = next(row for row in rendered if row["id"] == f"act:{chosen_ids[1]}")
    assert f"1d4+{known_bonus['value']} fire" in known_button["detail"]["damage"]

    actor_id = FACTORY_ACTOR_PREFIX + "left"
    match = combat.create_factory_match(
        project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
        control_modes={actor_id: "MANUAL"}, match_seed="TABLE-BLOOD-ARMOR-DISPLAY")
    match_id = match["match_id"]
    state = table.state(match_id)
    initial_engine = combat._load_session(match_id).engine
    initial_actor = initial_engine.state.actors[actor_id]
    initial_ac = initial_actor.armor_class + initial_engine._ac_modifier(initial_actor)
    for _ in range(12):
        if state.get("menu", {}).get("manual") and state["menu"].get("actor_id") == actor_id:
            break
        stepped = table.auto_step(match_id, state["last_sequence"])
        state = stepped["state"]
    menu = state["menu"]
    blood_armor = next(group for group in menu["actions"] if group["label"] == "Blood Armor")
    option = blood_armor["options"][0]
    result = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert any("Blood Armor" in row.get("summary", "") for row in result["events"]["events"])
    state = result["state"]
    engine = combat._load_session(match_id).engine
    actor = engine.state.actors[actor_id]
    presented = next(row for row in state["presentation"]["actors"] if row["entity_id"] == actor_id)
    ac = next(row["value"] for row in presented["defenses"] if row["defense_id"] == "defense:armor_class")
    assert ac == actor.armor_class + engine._ac_modifier(actor)
    assert ac == initial_ac + 2
    assert presented["speed_ft"] == engine._effective_speed(actor)
    carrying = state["carrying"][actor_id]
    assert carrying["over"] and carrying["speed_ft"] > 5
    assert presented["speed_ft"] == 5


def test_buttons_generate_from_the_bundle_and_custom_combos_validate():
    from combat.factory_compiler import compile_character

    bundle = compile_character(SHEET, actor_id="actor:factory.test")
    summary = sheet_summary(SHEET)
    buttons = auto_buttons(bundle, summary)
    ids = {row["id"] for row in buttons}
    dao = next(row for row in buttons if row["label"].startswith("Dao"))
    assert dao["group"] == "attacks" and dao["detail"]["to_hit"] and dao["combat"]["source_definition_id"]
    assert {"turn:end", "save:STR", "skill:athletics", "check:DEX", "roll:initiative"} <= ids
    assert len([row for row in buttons if row["group"] == "skills"]) == 18
    combo = normalize_custom_buttons({"buttons": [{"label": "Cut then dash", "steps": [{"button": dao["id"]}, {"button": "act:system:combat.dash"}]},
                                                  {"label": "Luck", "steps": [{"roll": "1d20 adv"}]}]}, ids)
    assert [row["kind"] for row in combo["buttons"]] == ["combo", "combo"]
    kept = normalize_custom_buttons({"buttons": [{"label": "Two cuts", "steps": [{"button": dao["id"]}, {"button": dao["id"], "same_target": False}]}]}, ids)
    assert [step["same_target"] for step in kept["buttons"][0]["steps"]] == [True, False]  # round-trips both ways
    with pytest.raises(TabletopError):
        normalize_custom_buttons({"buttons": [{"label": "Bad", "steps": [{"button": "act:nope"}]}]}, ids)
    with pytest.raises(TabletopError):
        normalize_custom_buttons({"buttons": [{"label": "Bad", "steps": [{"roll": "rm -rf"}]}]}, ids)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_browser_fog_uses_the_engine_line_of_sight():
    rng = random.Random(7)
    width, height = 18, 12
    blocked = sorted({(rng.randrange(width), rng.randrange(height)) for _ in range(40)})
    grid = SquareGrid({"width_squares": width, "height_squares": height, "square_size_ft": 5, "starting_positions": {},
                       "terrain_regions": [{"terrain_type": "BLOCKED", "movement_cost": 0, "cells": [{"x": x, "y": y} for x, y in blocked]}]})
    viewer = (3, 5)
    expected = [int(grid.line_of_sight(Position(x=viewer[0], y=viewer[1]), Position(x=x, y=y))) for y in range(height) for x in range(width)]
    script = (f"import {{opacityGrid, visibleCells}} from '{(STATIC / 'vision.js').as_posix()}';"
              f"const o = opacityGrid({width}, {height}, [{json.dumps(blocked)}]);"
              f"process.stdout.write(JSON.stringify(Array.from(visibleCells({width}, {height}, o, [{{x: {viewer[0]}, y: {viewer[1]}}}]))));")
    output = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(output) == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_map_editor_preview_rasterises_walls_exactly_like_the_engine():
    rng = random.Random(11)
    width, height = 22, 15
    walls = []
    for index in range(30):
        shape = rng.choice(["rect", "circle", "line"])
        count = rng.randint(2, 5) if shape == "line" else 2
        walls.append({"shape": shape, "points": [[round(rng.uniform(0, width), 2), round(rng.uniform(0, height), 2)] for _ in range(count)],
                      "filled": rng.random() < 0.5, "blocks": rng.choice(["sight", "sight_and_movement"])})
    document = normalize_map({"display_name": "Parity", "width_squares": width, "height_squares": height, "walls": walls})
    blocked, sight = rasterize(document)
    script = (f"import {{rasterizeWalls}} from '{(STATIC / 'vision.js').as_posix()}';"
              f"process.stdout.write(JSON.stringify(rasterizeWalls({json.dumps(document['walls'])}, {width}, {height})));")
    output = json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)
    assert {tuple(cell) for cell in output["blocked"]} == blocked
    assert {tuple(cell) for cell in output["sight"]} == sight


def test_a_built_in_map_copies_back_into_an_editable_map():
    from combat.tabletop import battlefield_as_map

    arena = json.loads((ROOT / "combat" / "rules" / "arenas" / "Mist_Courtyard.json").read_text(encoding="utf-8"))
    copy = battlefield_as_map(arena)
    assert rasterize(copy) == rasterize(normalize_map(copy))  # same walls after a round trip
    blocked, sight = rasterize(copy)
    arena_blocked = {(c["x"], c["y"]) for r in arena["terrain_regions"] if r["terrain_type"] == "BLOCKED" for c in r["cells"]}
    arena_sight = {(c["x"], c["y"]) for r in arena["terrain_regions"] if r["terrain_type"] == "SIGHT_BLOCKED" for c in r["cells"]}
    assert blocked == arena_blocked and sight == arena_sight
    assert copy["starts"]["team1"][0] == [1, 8] and {row["type"] for row in copy["terrain"]} == {"SIMPLE_COVER", "DIFFICULT"}
    pillar_arena = json.loads((ROOT / "combat" / "rules" / "arenas" / "Pillar_Arena.json").read_text(encoding="utf-8"))
    pillar = battlefield_as_map(pillar_arena)
    pillar_cells = {(c["x"], c["y"]) for r in pillar_arena["terrain_regions"] if r["terrain_type"] == "BLOCKED" for c in r["cells"]}
    assert rasterize(pillar)[0] == pillar_cells and all(wall["shape"] == "rect" for wall in pillar["walls"])


def test_the_sheet_library_groups_talents_under_their_spheres_with_full_text():
    from combat.factory_compiler import compile_character
    from combat.tabletop import sheet_library

    sheet = {**SHEET, "selected_record_sections": {
        "spheres": [{"record_id": "tianxia.sphere.brute", "display_name": "Brute", "full_description": "# Sphere of Brute\\nForce."}],
        "talents": [{"record_id": "TAL_BRUTE_MOUNTAIN_MOVING_PALM", "display_name": "Mountain-Moving Palm", "one_line_description": "A huge palm.",
                     "full_description": "### Mountain-Moving Palm\\n**Action** — push them 30 feet.", "acquisition_cl": 5}],
        "insights": [{"record_id": "insight.x", "display_name": "Quiet Mind", "full_description": "Calm."}],
    }}
    bundle = compile_character(sheet, actor_id="actor:factory.test")
    buttons = auto_buttons(bundle, sheet_summary(sheet))
    library = sheet_library(sheet, buttons, set())
    spheres = next(group for group in library["groups"] if group["key"] == "spheres")["spheres"]
    palm = spheres[0]["entries"][0]
    assert spheres[0]["name"] == "Brute" and palm["name"] == "Mountain-Moving Palm" and "push them" in palm["text"]
    assert palm["status"] in {"action", "partial"} and palm["button_id"].endswith("TAL_BRUTE_MOUNTAIN_MOVING_PALM")
    insights = next(group for group in library["groups"] if group["key"] == "insights")["entries"]
    assert insights[0]["status"] == "info"
    assert sheet_library(SHEET, buttons, set())["groups"] == []  # no record sections: nothing to list, no crash


def test_sheet_summary_lists_every_cultivation_pool():
    from combat.tabletop import _pools

    resource = {"name": "Resonance", "maximum": 20,
                "definitions": [{"name": "Resonance", "max": 20}, {"name": "Stamina", "max": 54}]}
    assert _pools(resource) == [{"name": "Resonance", "maximum": 20}, {"name": "Stamina", "maximum": 54}]
    assert _pools({"name": "Qi", "maximum": 8}) == [{"name": "Qi", "maximum": 8}]


def test_dropped_weapons_are_listed_where_they_fell():
    """Owner 2026-09-26: "weapon tracking on the ground" -- the table draws a Disarm's dropped weapon on its square."""
    from types import SimpleNamespace

    condition = SimpleNamespace(instance_id="c1", data={"disables_action": "action:typed.x.weapon.dao", "dropped_at": {"x": 4, "y": 7}})
    actor = SimpleNamespace(entity_id="actor:a", display_name="Wen Xue", conditions={"c1": condition})
    engine = SimpleNamespace(state=SimpleNamespace(actors={"actor:a": actor}),
                             action_catalog={"action:typed.x.weapon.dao": SimpleNamespace(display_name="Dao (Saber / Broadsword) attack")})
    service = TabletopService.__new__(TabletopService)
    service.combat = SimpleNamespace(_load_session=lambda match_id: SimpleNamespace(engine=engine))
    assert service._dropped_items("m1") == [{"id": "item:c1", "x": 4, "y": 7, "name": "Dao (Saber / Broadsword) (dropped by Wen Xue)",
                                             "owner_id": "actor:a"}]


def test_granted_spheres_are_kept_by_every_save(tmp_path):
    from combat.tabletop import ButtonStore

    PID = "950998a1-3474-4aa1-9419-06998011980f"
    store = ButtonStore(tmp_path)
    store.save_granted_spheres(PID, ["tianxia.sphere.weapons"], {"tianxia.sphere.weapons"})
    store.save_reactions(PID, {"mode": "custom", "order": ["opportunity_attack"], "off": []}, {"opportunity_attack"})
    assert store.get(PID)["granted_spheres"] == ["tianxia.sphere.weapons"]
    with pytest.raises(Exception):
        store.save_granted_spheres(PID, ["not.a.sphere"], {"tianxia.sphere.weapons"})
