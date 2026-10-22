"""Tabletop support for human-played combat (owner 2026-09-25: a MapTool/Roll20-style local table).

Four pieces, all owner-editable data on disk:

* Maps (``<data>/combat_maps/<map_id>.json``): grid size, background image, display
  settings, starting spots per team, and walls drawn as vector shapes (rectangle,
  circle, freeform line).  Walls are rasterised into grid cells for the rules engine:
  ``sight_and_movement`` walls become BLOCKED cells, ``sight`` walls become
  SIGHT_BLOCKED cells (block line of sight, can be walked through).  The browser
  draws the vectors; the engine and the fog of war use the same cells, so what a
  token can see is exactly what it can target.
* A light event stream read from a match's journal (events, readable feed lines and
  the dice each roll used) so the table can animate rolls without re-reading history.
* Action buttons for a character, generated from its compiled combat bundle and its
  sheet, plus the owner's custom buttons and combos (``<data>/tabletop_buttons``).
  Schema: ``docs/tabletop/BUTTON_SCHEMA.md``.
* A compact sheet summary for the pop-out character sheet.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import math
import os
import re
import tempfile
import threading
from .map_openings import placed_wall_cells
from .roof_settings import normalize_roofs
from .map_heights import wall_height_ft, scenery_span
from .scenery_sight import bamboo_groups, bamboo_culms, tree_trunks, plant_segments, terrain_blocks_sight
from .roof_coverage import roof_cells
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterable

# The history feed reads a match's journal incrementally (combat/journal_feed.py):
# the table asks for the events after the sequence it already holds, so a poll
# costs the records appended since, not the whole fight.
from .journal_feed import HIDDEN_LOG_EVENT_TYPES, journal_since

MAP_SCHEMA = "TianxiaTabletopMap.v1"
BUTTONS_SCHEMA = "TianxiaSheetButtons.v1"
MAP_PREFIX = "battlefield:map."
MAP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
WALL_SHAPES = ("rect", "circle", "line")
WALL_BLOCKS = ("sight_and_movement", "sight")


def occluder_mode(row: dict, default: str = 'cell') -> str:
    """Map-authored sight geometry, independent of movement/obscurement."""
    mode = row.get('occluder', default)
    if mode not in {'cell', 'centerline'}:
        raise TabletopError('MAP_OCCLUDER_INVALID', 'Sight blocking must use a whole square or two crossing centre lines.')
    return mode
GRID_LIMITS = {"width": (6, 80), "height": (6, 60)}
ASSET_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_ASSET_BYTES = 12 * 1024 * 1024
BACKGROUND_STYLES = ("flagstone", "tiles", "wood", "grass", "sand", "cave", "snow", "plain",  # static/tabletop/textures.js
                     "lava_rock", "marsh", "bamboo", "dirt_road", "marble", "dark_stone", "ice", "shallows", "mountain", "graveyard",
                     # biome floors (owner 2026-10-08), only the look like every floor
                     "jungle", "forest_loam", "scree_ground", "dunes", "snowfield", "swamp_mud", "temple_court", "packed_dirt",
                     "churned_earth",
                     # indoor floors/tiles and grass/forest variants (owner 2026-10-08, SON202), only the look like
                     # every floor: static/tabletop/floor-art-indoor.js
                     "wood_palace", "tatami", "clay_tile", "glazed_green_tile", "lacquer_red", "jade_marble",
                     "herringbone_brick", "hex_stone", "bamboo_slat", "taiji_medallion", "cloud_stone", "alchemy_scorch",
                     "sutra_hall_wood", "formation_floor", "temple_moss_flagstone", "rug_geometric", "rug_lotus",
                     "grass_meadow", "grass_autumn", "grass_lawn", "grass_wildflower", "grass_trampled", "grass_alpine",
                     "forest_pine_needle", "forest_moss", "forest_fern", "forest_leaf_litter", "forest_mushroom_loam",
                     "forest_root_tangle")
MAX_WALLS = 400
MAX_POINTS = 2000
MAX_TREES = 300
# How a tree looks (owner 2026-10-08: "other types of trees"); static/tabletop/tree-art.js draws them. Only the look:
# every kind keeps the same trunk rules. A tree saved without a look is the broadleaf it has always been.
# Biome decoration (owner 2026-10-08 asset packs; static/tabletop/decor-art.js). DECOR_KINDS are look-only pieces kept
# in the map's `decor` list and never read by a rule. DECOR_RULE_LOOKS are pieces that ARE ordinary cover or difficult
# terrain rows, only drawn differently: they are accepted as terrain `look` values and nothing else.
# tests/test_sol196_map_art.py checks both lists against decor-art.js.
DECOR_KINDS = ("fern", "mushrooms", "leaf_litter", "forest_bush", "wildflowers", "mountain_shrub", "fissure",
               "dune_ripples", "barrel_cactus", "bleached_bones", "dry_scrub", "frozen_puddle", "snowy_shrub",
               "footprints", "reeds", "lily_pads", "cattails", "murky_pool", "swamp_mushrooms", "prayer_flags",
               "koi_pond_edge", "prayer_mat", "bonsai_pot", "baskets", "pottery", "broken_weapons", "torn_banner",
               "shield_pile", "arrows_in_ground", "scorch_crater", "grass_tufts", "puddle", "autumn_leaves",
               "spring_blossoms", "alpine_flowers", "cracked_earth", "oasis_pool", "snow_tufts", "bog_tufts",
               "swamp_puddle", "raked_gravel", "plum_petals", "flower_planter", "mud_puddle", "trampled_grass",
               "spirit_herbs", "formation_flags", "beast_nest", "broken_immortal_sword", "spirit_spring")
DECOR_RULE_LOOKS = ("fallen_log", "stump", "mossy_rock", "crag", "cliff_edge", "cairn", "loose_gravel",
                    "boulder_pair", "cactus", "sandstone", "sand_drift", "ice_shards", "snow_drift", "snowy_rock",
                    "icicle_pillar", "mangrove_roots", "rotten_log", "stone_lantern", "incense_burner",
                    "offering_table", "market_stall", "sack_pile", "hay_bale", "water_well", "wooden_fence",
                    "handcart", "brazier", "spear_rack", "war_drum", "log_pile", "rock_slab", "desert_rocks",
                    "snowy_log", "stone_bench", "bronze_cauldron", "firewood_stack", "caltrops", "palisade",
                    "qi_crystals", "array_stone", "sect_gate_pillar", "jade_stele")
MAX_DECOR = 600
# How a wall looks (owner 2026-10-08, static/tabletop/wall-art.js WALL_LOOKS). Only the look: what a wall blocks is
# its `blocks` field and its squares come from its geometry. A wall saved without a look is drawn as it always was.
WALL_LOOKS = ("rammed_earth", "grey_brick", "red_palace", "white_plaster", "timber_lattice", "bamboo_fence",
              "stone_rampart", "jade_marble", "ruined_stone", "formation_barrier", "rock_cliff")
TREE_LOOKS = ("broadleaf", "maple", "cherry", "willow", "pine", "snowy_pine", "dead", "ancient", "bamboo_stand", "golden_bamboo")
MAX_OBJECTS = 200
NUDGE_LIMIT = 40  # hundredths of a square an object may be nudged from its arranged spot


def arena_picker_name(arena: dict[str, Any]) -> str:
    """Display an arena's authored name without changing its saved document."""
    return str(arena.get("display_name") or arena["stable_id"])


def arena_picker_order(arena: dict[str, Any]) -> tuple[int, str]:
    """Map-authored picker order, then other arenas; saved geometry is untouched."""
    key = str(arena.get("stable_id") or arena.get("arena_id") or "")
    return (_whole(arena.get("picker_order"), 1000, 2, 999), key)

SKILLS = (
    ("Acrobatics", "DEX"), ("Animal Handling", "WIS"), ("Arcana", "INT"), ("Athletics", "STR"),
    ("Deception", "CHA"), ("History", "INT"), ("Insight", "WIS"), ("Intimidation", "CHA"),
    ("Investigation", "INT"), ("Medicine", "WIS"), ("Nature", "INT"), ("Perception", "WIS"),
    ("Performance", "CHA"), ("Persuasion", "CHA"), ("Religion", "INT"), ("Sleight of Hand", "DEX"),
    ("Stealth", "DEX"), ("Survival", "WIS"),
)
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
ABILITY_NAMES = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}


class TabletopError(ValueError):
    """A request the tabletop cannot honour; ``code`` is stable for the UI."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48]
    return slug or "map"


# ---------------------------------------------------------------- maps
def _point(value: Any, width: int, height: int) -> list[float]:
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise TabletopError("MAP_WALL_INVALID", "A wall point must be [x, y] in squares.")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise TabletopError("MAP_WALL_INVALID", "A wall point must be a finite number.")
    return [round(min(max(x, 0.0), float(width)), 3), round(min(max(y, 0.0), float(height)), 3)]


def _seed(value: Any) -> int:
    try:
        return int(value) % 2_147_483_647 or 1
    except (TypeError, ValueError):
        return 1


def normalize_map(document: dict[str, Any]) -> dict[str, Any]:
    """Validate and clamp an owner map; raises TabletopError with a readable message."""
    from .journey import normalize_travel_regions
    if not isinstance(document, dict):
        raise TabletopError("MAP_INVALID", "A map must be a JSON object.")
    name = str(document.get("display_name") or "").strip()[:120] or "Untitled map"
    map_id = str(document.get("map_id") or _slug(name))
    if not MAP_ID_RE.match(map_id):
        raise TabletopError("MAP_ID_INVALID", "Map ids use lower-case letters, digits, '-' and '_' (up to 64).")
    try:
        width = int(document.get("width_squares") or 20)
        height = int(document.get("height_squares") or 14)
    except (TypeError, ValueError):
        raise TabletopError("MAP_SIZE_INVALID", "Grid width and height must be whole numbers of squares.")
    low, high = GRID_LIMITS["width"]
    if not low <= width <= high:
        raise TabletopError("MAP_SIZE_INVALID", f"Grid width must be {low}–{high} squares.")
    low, high = GRID_LIMITS["height"]
    if not low <= height <= high:
        raise TabletopError("MAP_SIZE_INVALID", f"Grid height must be {low}–{high} squares.")
    walls: list[dict[str, Any]] = []
    points_total = 0
    for index, wall in enumerate(document.get("walls") or []):
        if not isinstance(wall, dict):
            raise TabletopError("MAP_WALL_INVALID", "Each wall must be an object.")
        shape = str(wall.get("shape") or "")
        if shape not in WALL_SHAPES:
            raise TabletopError("MAP_WALL_INVALID", f"Wall shape must be one of {', '.join(WALL_SHAPES)}.")
        blocks = str(wall.get("blocks") or "sight_and_movement")
        if blocks not in WALL_BLOCKS:
            raise TabletopError("MAP_WALL_INVALID", "A wall blocks 'sight_and_movement' or 'sight'.")
        points = [_point(value, width, height) for value in wall.get("points") or []]
        if len(points) < 2 or (shape != "line" and len(points) != 2):
            raise TabletopError("MAP_WALL_INVALID", "Rectangles and circles take two points; lines take two or more.")
        points_total += len(points)
        walls.append({"id": str(wall.get("id") or f"wall-{index + 1}")[:40], "shape": shape, "points": points,
                      "filled": bool(wall.get("filled", shape != "line")), "blocks": blocks})
        if wall.get("look") in WALL_LOOKS:
            walls[-1]["look"] = wall["look"]
        if 'occluder' in wall:
            walls[-1]['occluder'] = occluder_mode(wall)
        if isinstance(wall.get("kind"), str):
            walls[-1]["kind"] = wall["kind"][:40]
        if "storeys" in wall:
            if type(wall["storeys"]) is not int or wall["storeys"] < 1:
                raise TabletopError("MAP_WALL_INVALID", "Building storeys must be a whole number, one or more.")
            walls[-1]["storeys"] = wall["storeys"]
        height_ft = wall_height_ft(wall)
        if type(height_ft) is not int or height_ft < 0:
            raise TabletopError("MAP_WALL_INVALID", "Wall height must be a whole number of feet, zero or more.")
        walls[-1]["height_ft"] = height_ft
    if len(walls) > MAX_WALLS or points_total > MAX_POINTS:
        raise TabletopError("MAP_TOO_COMPLEX", f"A map holds at most {MAX_WALLS} walls and {MAX_POINTS} points.")
    background = document.get("background") or {}
    asset = background.get("asset")
    if asset is not None and not re.match(r"^[0-9a-f]{64}\.(png|jpg|webp)$", str(asset)):
        raise TabletopError("MAP_BACKGROUND_INVALID", "The background must be an uploaded image.")
    display = document.get("display") or {}

    def _unit(value: Any, default: float) -> float:
        try:
            return round(min(max(float(value), 0.0), 1.0), 3)
        except (TypeError, ValueError):
            return default

    starts: dict[str, list[list[int]]] = {}
    for team in ("team1", "team2"):
        spots = []
        for value in (document.get("starts") or {}).get(team) or []:
            x, y = _point(value, width - 1, height - 1)
            spots.append([int(x), int(y)])
        starts[team] = spots[:12]
    terrain = []
    valid_looks = {"rice_tufts", "boulder", "bamboo_clump", "broken_tiles", "lantern", "low_wall", "pillar_rubble",
                   "roots", "rubble", "scree", "statue_plinth", "stones", *DECOR_RULE_LOOKS}
    for region in document.get("terrain") or []:
        kind = str(region.get("type") or "")
        if kind not in {"SIMPLE_COVER", "QI_HAZARD", "DIFFICULT"}:
            continue
        cells = sorted({(int(c[0]), int(c[1])) for c in region.get("cells") or [] if 0 <= int(c[0]) < width and 0 <= int(c[1]) < height})
        if cells:
            normalized = {"type": kind, "cells": [list(cell) for cell in cells]}
            from .terrain_materials import material_tag
            if region.get('material'):
                normalized['material'] = material_tag(region['material'])
            if region.get('sealed'):
                normalized['sealed'] = True
            if region.get('travel_kind') is not None:
                from .journey import TRAVEL_KINDS
                if region['travel_kind'] not in TRAVEL_KINDS:
                    raise TabletopError('MAP_TRAVEL_INVALID', 'Choose a known travel terrain kind.')
                normalized['travel_kind'] = region['travel_kind']
            look = region.get("look")
            if isinstance(look, str) and look in valid_looks:
                normalized["look"] = look
                # A biome piece may be turned (the editor's Turn control): only its look, never a rule.
                if look in DECOR_RULE_LOOKS and region.get("rotation") in (90, 180, 270):
                    normalized["rotation"] = region["rotation"]
            normalized.update(_scenery_span({**normalized, **{key: region[key]
                for key in ("height_ft", "base_altitude_ft") if key in region}}, "terrain"))
            terrain.append(normalized)
    materials = _materials(document.get("materials"), width, height)
    catch_dc = document.get('catch_dc')
    if catch_dc is not None and (type(catch_dc) is not int or catch_dc < 0):
        raise TabletopError('MAP_CATCH_DC_INVALID', 'Catch difficulty must be a nonnegative integer.')
    try:
        roofs = normalize_roofs(document.get("roofs"), width, height)
    except ValueError as error:
        raise TabletopError("MAP_ROOF_INVALID", str(error)) from error
    numbers = document.get("terrain_numbers") or {}
    # Trees (owner 2026-09-28): a trunk of one square, or two by two for a great tree, inside the map.
    trees = []
    for value in document.get("trees") or []:
        if not isinstance(value, dict):
            continue
        try:
            x, y = int(value.get("x")), int(value.get("y"))
        except (TypeError, ValueError):
            continue
        size = 2 if value.get("size") == 2 else 1
        if 0 <= x and 0 <= y and x + size <= width and y + size <= height:
            trees.append({"x": x, "y": y, "size": size, "seed": _seed(value.get("seed"))})
            if value.get("look") in TREE_LOOKS and value.get("look") != "broadleaf":
                trees[-1]["look"] = value["look"]
            trees[-1]['occluder'] = occluder_mode(value, 'centerline')
            trees[-1].update(_scenery_span({**trees[-1], **{key: value[key]
                for key in ("height_ft", "base_altitude_ft") if key in value}}, "tree"))
    objects = _objects(document.get("objects"), width, height)
    decor = []
    for value in document.get("decor") or []:
        if not isinstance(value, dict) or value.get("kind") not in DECOR_KINDS or len(decor) >= MAX_DECOR:
            continue
        try:
            x, y = int(value.get("x")), int(value.get("y"))
        except (TypeError, ValueError):
            continue
        if 0 <= x < width and 0 <= y < height:
            row = {"kind": value["kind"], "x": x, "y": y, "seed": _seed(value.get("seed"))}
            if value.get("rotation") in (90, 180, 270):
                row["rotation"] = value["rotation"]
            decor.append(row)
    try:
        travel_regions = normalize_travel_regions(document.get('travel_regions', []), width, height)
    except ValueError as exc:
        raise TabletopError('MAP_TRAVEL_INVALID', str(exc)) from exc
    return {
        "schema": MAP_SCHEMA,
        **({'catch_dc': catch_dc} if catch_dc is not None else {}),
        "map_id": map_id,
        "display_name": name,
        **({"description": str(document["description"]).strip()[:1000]} if document.get("description") else {}),
        **({"picker_order": _whole(document["picker_order"], 1000, 2, 999)} if "picker_order" in document else {}),
        "natural_haze": document.get("natural_haze") is True,
        "width_squares": width,
        "height_squares": height,
        "square_size_ft": 5,
        "background": {"asset": asset, "opacity": _unit(background.get("opacity"), 1.0),
                       "fit": "stretch" if background.get("fit") == "stretch" else "cover",
                       "style": background.get("style") if background.get("style") in BACKGROUND_STYLES else "flagstone",
                       "seed": _seed(background.get("seed"))},
        "display": {"grid_opacity": _unit(display.get("grid_opacity"), 0.35), "detail": _unit(display.get("detail"), 1.0),
                    "grid_color": str(display.get("grid_color") or "#d8c9a3")[:20],
                    # how softly painted floors fade into each other (owner 2026-09-28: "blend the different terrains")
                    "blend": _unit(display.get("blend"), 0.0)},
        "walls": walls,
        # A tree's trunk blocks movement and sight like a wall square; its canopy is only the look.
        "trees": trees[:MAX_TREES],
        # Decoration: only the look (static/tabletop/decor-art.js); no rule ever reads it. Absent when there is none.
        **({"decor": decor} if decor else {}),
        "starts": starts,
        "terrain": terrain,
        **({"travel_regions": travel_regions} if travel_regions else {}),
        # Materials painted onto squares (owner 2026-09-28: "a map editor mode so i can make maps with the materials"):
        # a floor texture (look only) and a named terrain (look and rules in a fight: combat/zones.py map_zones),
        # at most one of each per square; the map's own save DC and Proficiency Bonus for its terrain (it has no creator).
        "materials": materials,
        **({"roofs": roofs} if roofs else {}),
        "terrain_numbers": {"save_dc": _whole(numbers.get("save_dc"), 13, 5, 30), "pb": _whole(numbers.get("pb"), 2, 2, 9)},
        # Destructible objects and structures placed on squares (owner 2026-09-29, task O): a preset kind (door, gate, crate, ...)
        # and any of the numbers the placement may override; combat/object_rules.py says what each becomes in a fight.
        "objects": objects,
    }


def _whole(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _scenery_span(row: dict[str, Any], family: str) -> dict[str, int]:
    try:
        return scenery_span(row, family)
    except ValueError as error:
        raise TabletopError("MAP_HEIGHT_INVALID", str(error)) from error


def map_terrain_names() -> list[str]:
    """The named terrains a map may be painted with (combat/rules/terrain.json)."""
    from .zones import terrain_rules

    return sorted((terrain_rules().get("terrains") or {}).keys())


def _objects(rows: Any, width: int, height: int) -> list[dict[str, Any]]:
    """[{"id", "kind", "x", "y", ...}]: a known kind, a square on the map, whole numbers only (a sealed arena allows no floats).
    The optional keys are the placement's own numbers (combat/object_rules.py stats): name, material, size, resilient, ac, hp,
    threshold, blocks, unattended, immune, vulnerable, resist, artifact, weight_lb.
    Weight is optional, explicit whole pounds; unknown or invalid weight stays absent.
    Simple-door interaction requires explicit integer open/locked/jammed flags;
    unknown interaction state stays absent (combat/object_rules.py)."""
    from .object_rules import presets, rules, simple_door_state

    kinds, materials, sizes = presets(), rules()["materials"], rules()["sizes"]
    out: list[dict[str, Any]] = []
    used: set[int] = set()
    for value in rows or []:
        if not isinstance(value, dict) or len(out) >= MAX_OBJECTS:
            continue
        kind = str(value.get("kind") or "custom")
        try:
            x, y = int(value.get("x")), int(value.get("y"))
        except (TypeError, ValueError):
            continue
        if kind not in kinds or not (0 <= x < width and 0 <= y < height):
            continue
        try:
            number = int(value.get("id"))
        except (TypeError, ValueError):
            number = 0
        if number < 1 or number in used:
            number = max([*used, 0]) + 1
        used.add(number)
        row: dict[str, Any] = {"id": number, "kind": kind, "x": x, "y": y}
        if type(value.get('rotation')) is int and value['rotation'] % 90 == 0:
            row['rotation'] = value['rotation'] % 360
        axis, line = value.get('mount_axis'), value.get('mount_line')
        if (kind in {'door', 'gate', 'window'} and axis in {'h', 'v'}
                and type(line) is int and 0 <= line < (height if axis == 'h' else width) * 100
                and line // 100 == (y if axis == 'h' else x)):
            row.update(mount_axis=axis, mount_line=line)
        # A hand nudge inside a shared square (SOL201): whole hundredths of a square, look only (static/tabletop/object-arrange.js).
        nudge = value.get("nudge")
        if (isinstance(nudge, list) and len(nudge) == 2 and all(type(part) is int for part in nudge)
                and any(nudge) and 'mount_axis' not in row):
            row["nudge"] = [max(-NUDGE_LIMIT, min(NUDGE_LIMIT, part)) for part in nudge]
        if type(value.get("weight_lb")) is int and value["weight_lb"] >= 0:
            row["weight_lb"] = value["weight_lb"]
        for key in ("z",):
            if value.get(key) is not None:
                if type(value[key]) is not int or value[key] < 0:
                    raise TabletopError("MAP_OBJECT_INVALID", "Object height and altitude must be whole numbers, zero or more.")
                row[key] = value[key]
        row.update(_scenery_span(value, "object"))
        # Objects already have a position.z base, in five-foot cells.
        if "base_altitude_ft" in row:
            raise TabletopError("MAP_OBJECT_INVALID", "Use object altitude in squares; its height is in feet above that base.")
        if str(value.get("name") or "").strip():
            row["name"] = " ".join(str(value["name"]).split())[:60]
        if str(value.get("material") or "").lower() in materials:
            row["material"] = str(value["material"]).lower()
        if str(value.get("size") or "").lower() in sizes:
            row["size"] = str(value["size"]).lower()
        for key in ("resilient", "blocks", "unattended", "artifact"):
            if isinstance(value.get(key), bool):
                row[key] = value[key]
        door = simple_door_state(value)
        if door is not None:
            row.update(door)
            row["blocks"] = not bool(door["door_open"])
        for key, high in (("ac", 40), ("hp", 999), ("threshold", 999)):
            if value.get(key) not in (None, "", 0, "0"):
                row[key] = _whole(value.get(key), 0, 1, high)
                if not row[key]:
                    del row[key]
        for key in ("immune", "vulnerable", "resist"):
            kinds_named = sorted({str(kind).upper()[:24] for kind in value.get(key) or [] if str(kind).strip()})
            if kinds_named:
                row[key] = kinds_named[:12]
        out.append(row)
    return out


def _check_shared_squares(objects: list[dict[str, Any]]) -> None:
    """Several objects may share a 5-foot square when their footprints fit (combat/object_rules.py square_problem).
    Checked when a map is saved, not when one is read, so a map saved before this rule still opens unchanged."""
    from .object_rules import square_problem

    squares: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in objects:
        squares.setdefault((row["x"], row["y"]), []).append(row)
    for (x, y), rows in sorted(squares.items()):
        problem = square_problem(rows)
        if problem:
            raise TabletopError("MAP_SQUARE_FULL", f"Square ({x + 1}, {y + 1}): {problem}")


def _materials(rows: Any, width: int, height: int) -> list[dict[str, Any]]:
    """[{"material": "floor:<style>" | "terrain:<name>", "cells": [[x, y], ...]}]: known materials only, squares on the
    map, and one floor and one terrain per square (the later painting wins,
    including that square's sight geometry). Group only equal materials AND modes."""
    terrains = set(map_terrain_names())
    owner = {}
    order = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        material = str(row.get("material") or "")
        family, _, name = material.partition(":")
        if not ((family == "floor" and name in BACKGROUND_STYLES) or (family == "terrain" and name in terrains)):
            continue
        mode = occluder_mode(row, 'centerline' if material == BAMBOO else 'cell')
        span = _scenery_span(row, "material") if material == BAMBOO else {}
        group = material, mode, tuple(span.items())
        if group not in order:
            order.append(group)
        for cell in row.get("cells") or []:
            try:
                x, y = int(cell[0]), int(cell[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0 <= x < width and 0 <= y < height:
                owner[(family, (x, y))] = (group, 'occluder' in row)
    out = []
    for group in order:
        material, mode, span = group
        family = material.split(":", 1)[0]
        winners = [(cell, explicit) for (fam, cell), (identity, explicit) in owner.items()
                   if fam == family and identity == group]
        cells = sorted(cell for cell, _ in winners)
        if cells:
            out.append({"material": material, "cells": [list(cell) for cell in cells]})
            out[-1].update(dict(span))
            if material == BAMBOO or any(explicit for _, explicit in winners):
                out[-1]['occluder'] = mode
    return out


def _distance(dx: float, dy: float) -> float:
    """sqrt(dx² + dy²) exactly as the browser computes it (static/tabletop/vision.js), so the map
    editor's preview of blocked squares matches the engine bit for bit."""
    return math.sqrt(dx * dx + dy * dy)


def _segment_cells(a: list[float], b: list[float], width: int, height: int) -> set[tuple[int, int]]:
    """Cells a segment passes through (sampled finely; exact enough for 5 ft squares)."""
    cells: set[tuple[int, int]] = set()
    length = _distance(b[0] - a[0], b[1] - a[1])
    steps = max(1, int(length * 8))
    for index in range(steps + 1):
        t = index / steps
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        cell = (min(int(math.floor(x)), width - 1), min(int(math.floor(y)), height - 1))
        if 0 <= cell[0] < width and 0 <= cell[1] < height:
            cells.add(cell)
    return cells


def wall_cells(wall: dict[str, Any], width: int, height: int) -> set[tuple[int, int]]:
    points = wall["points"]
    if wall["shape"] == "line":
        cells: set[tuple[int, int]] = set()
        for a, b in zip(points, points[1:]):
            cells |= _segment_cells(a, b, width, height)
        return cells
    (x0, y0), (x1, y1) = points
    if wall["shape"] == "rect":
        left, right, top, bottom = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        if wall["filled"]:
            return {(x, y) for x in range(width) for y in range(height)
                    if left <= x + 0.5 <= right and top <= y + 0.5 <= bottom}
        corners = [[left, top], [right, top], [right, bottom], [left, bottom], [left, top]]
        cells = set()
        for a, b in zip(corners, corners[1:]):
            cells |= _segment_cells(a, b, width, height)
        return cells
    radius = _distance(x1 - x0, y1 - y0)
    result = set()
    for x in range(width):
        for y in range(height):
            distance = _distance(x + 0.5 - x0, y + 0.5 - y0)
            if (wall["filled"] and distance <= radius) or (not wall["filled"] and abs(distance - radius) <= 0.5):
                result.add((x, y))
    return result


BAMBOO = "terrain:bamboo thicket"


def bamboo_stands(document: dict[str, Any]) -> list[tuple[int, int, int]]:
    """Squares painted with bamboo that grow together into one large stand (owner 2026-09-29: "can the large clumps block
    vision as well?"), found exactly as static/tabletop/zonepaint.js M.bamboo draws them: every whole 3x3 block, then
    every whole 2x2 block, taking top-left corners in reading order. (x, y, size) each."""
    cells = sorted({(int(x), int(y)) for row in document.get("materials") or [] if row.get("material") == BAMBOO for x, y in row.get("cells") or []},
                   key=lambda cell: (cell[1], cell[0]))
    have, used, stands = set(cells), set(), []
    for size in (3, 2):
        for x, y in cells:
            block = {(x + dx, y + dy) for dy in range(size) for dx in range(size)}
            if block <= have and not block & used:
                used |= block
                stands.append((x, y, size))
    return stands


def rasterize(document: dict[str, Any]) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """(blocked cells, sight-only cells) for a normalised map."""
    blocked: set[tuple[int, int]] = set()
    sight: set[tuple[int, int]] = set()
    width, height = document["width_squares"], document["height_squares"]
    for wall in document["walls"]:
        (blocked if wall["blocks"] == "sight_and_movement" else sight).update(placed_wall_cells(wall, document, wall_cells))
    for tree in document.get("trees") or []:
        span = _scenery_span(tree, "tree")
        if span["height_ft"] and not span.get("base_altitude_ft", 0):
            blocked.update((tree["x"] + dx, tree["y"] + dy) for dx in range(tree["size"]) for dy in range(tree["size"]))
    # A large bamboo stand is too dense to see through; it can still be pushed through (difficult terrain).
    bamboo_ground = {tuple(c) for row in document.get("materials") or [] if row["material"] == BAMBOO
                    and _scenery_span(row, "material")["height_ft"] >= 5 and not row.get("base_altitude_ft", 0)
                    for c in row["cells"]}
    for row in document.get('materials') or []:
        if row['material'] != BAMBOO:
            continue
        for group in bamboo_groups(row['cells']):
            x, y, size = group['x'], group['y'], group['size']
            sight.update((x + dx, y + dy) for dx in range(size) for dy in range(size)
                         if (x + dx, y + dy) in bamboo_ground)
    return blocked, sight - blocked


def to_battlefield(document: dict[str, Any]) -> dict[str, Any]:
    """The engine arena for a map (same format as combat/rules/arenas/*.json)."""
    from .roof_geometry import surfaces_for_map
    # Keep every finite source separate; flattening trees/bamboo with walls
    # would replace their authored spans with an unlimited column.
    roof_surfaces = surfaces_for_map(document, wall_cells)
    roof_heights = {}
    for roof in roof_surfaces:
        for cell in roof['cells']:
            key = cell['x'], cell['y']
            roof_heights[key] = max(roof_heights.get(key, 0), roof['height_ft'])
    finite_walls = [wall for wall in document["walls"] if wall.get("height_ft") is not None]
    unlimited = {**document, "walls": [wall for wall in document["walls"] if wall.get("height_ft") is None],
                 "trees": [], "materials": []}
    blocked, sight = rasterize(unlimited)
    # Roofs give formerly unlimited authored building walls a finite top. Split
    # only their roof-covered cells; a long wall's outdoor continuation, trees,
    # and other independent overlapping obstacles retain their own geometry.
    inferred_walls = []
    unlimited_footprints = {}
    if roof_surfaces:
        # Finite trees and bamboo have independent physical stem sources below;
        # never duplicate them as unbounded cells when a map also has roofs.
        blocked, sight = set(), set()
        for index, wall in enumerate(document['walls']):
            if wall.get('height_ft') is not None:
                continue
            cells = placed_wall_cells(wall, document, wall_cells)
            groups = {}
            for cell in cells:
                if cell in roof_heights:
                    groups.setdefault(roof_heights[cell], set()).add(cell)
            remaining = cells - roof_heights.keys()
            unlimited_footprints[index] = remaining
            (blocked if wall['blocks'] == 'sight_and_movement' else sight).update(remaining)
            inferred_walls.extend((wall, group, height) for height, group in sorted(groups.items()))
        sight -= blocked
    width, height = document["width_squares"], document["height_squares"]
    regions: list[dict[str, Any]] = []
    from .terrain_materials import EDITOR_MATERIALS

    def region(region_id: str, kind: str, cells: Iterable[tuple[int, int]], cost: int, description: str) -> None:
        cells = sorted(cells)
        if cells:
            regions.append({"region_id": region_id, "terrain_type": kind, "movement_cost": cost, "description": description,
                            "cells": [{"x": x, "y": y} for x, y in cells]})

    # Keep sources separate: a full wall overlapping a tree still blocks fully,
    # and a raised finite wall never changes the tree's independent height.
    thin, full = set(), set()
    for index, wall in enumerate(document['walls']):
        if wall.get('height_ft') is None:
            cells = (unlimited_footprints[index] if roof_surfaces
                     else placed_wall_cells(wall, document, wall_cells))
            (thin if occluder_mode(wall) == 'centerline' else full).update(cells)
    for tree in document.get('trees') or []:
        (thin if occluder_mode(tree, 'centerline') == 'centerline' else full).update(
            (tree['x'] + dx, tree['y'] + dy) for dx in range(tree['size']) for dy in range(tree['size']))
    bamboo_modes = {tuple(c): occluder_mode(row, 'centerline') for row in document.get('materials') or []
                    if row['material'] == BAMBOO for c in row['cells']}
    for x, y, size in bamboo_stands(document):
        for dx in range(size):
            for dy in range(size):
                cell = x + dx, y + dy
                (thin if bamboo_modes[cell] == 'centerline' else full).add(cell)
    thin -= full
    # Keep authored wall footprints separate so crossing/adjacent walls do not
    # acquire a different centre axis when combined with other terrain.
    unlimited_rows = [(wall, unlimited_footprints[index] if roof_surfaces else
                       placed_wall_cells(wall, document, wall_cells))
                      for index,wall in enumerate(document['walls']) if wall.get('height_ft') is None]
    wall_footprint = set().union(*(cells for wall,cells in unlimited_rows)) if unlimited_rows else set()
    region("walls.solid", "BLOCKED", blocked - thin - wall_footprint, 0, "Blocking terrain: cannot be entered and blocks line of sight.")
    region("walls.sight", "SIGHT_BLOCKED", sight - thin - wall_footprint, 1, "Screen: blocks line of sight but can be walked through.")
    for wall,cells in unlimited_rows:
        if not cells:
            continue
        solid=wall['blocks']=='sight_and_movement'
        region('wall.line.'+wall['id'], 'BLOCKED' if solid else 'SIGHT_BLOCKED', cells,
               0 if solid else 1, 'Wall: blocks sight along its centre line and ends.')
        if 'occluder' in wall:
            regions[-1]['occluder'] = occluder_mode(wall)
            if wall['occluder'] == 'centerline':
                regions[-1]['description'] = 'Wall: blocks sight along two crossing centre lines.'
    for kind, cells, cost in [('BLOCKED', (blocked & thin)-wall_footprint, 0), ('SIGHT_BLOCKED', (sight & thin)-wall_footprint, 1)]:
        if cells:
            region('terrain.cross.' + kind.lower(), kind, cells, cost,
                   'Terrain blocks sight along two crossing centre lines; its near side stays visible.')
            regions[-1]['occluder'] = 'centerline'
    for wall in finite_walls:
        cells = placed_wall_cells(wall, document, wall_cells)
        if cells:
            solid = wall["blocks"] == "sight_and_movement"
            region("wall.height." + wall["id"], "BLOCKED" if solid else "SIGHT_BLOCKED", cells,
                   0 if solid else 1, f"Wall: {wall['height_ft']} ft. high.")
            regions[-1]["height_ft"] = wall["height_ft"]
            if 'occluder' in wall:
                regions[-1]['occluder'] = occluder_mode(wall)
    for wall, cells, roof_height in inferred_walls:
        solid = wall['blocks'] == 'sight_and_movement'
        region(f"roof.wall.{wall['id']}.{roof_height}", 'BLOCKED' if solid else 'SIGHT_BLOCKED',
               cells, 0 if solid else 1, f"Building wall: {roof_height} ft. high, up to its roof.")
        regions[-1]['height_ft'] = roof_height
        if 'occluder' in wall:
            regions[-1]['occluder'] = occluder_mode(wall)
    for index, tree in enumerate(document.get("trees") or []):
        cells = {(tree['x'] + dx, tree['y'] + dy) for dx in range(tree['size']) for dy in range(tree['size'])}
        region(f"tree.height.{index + 1}", "BLOCKED", cells, 0, "Tree trunk: blocks sight and movement below its top.")
        span = _scenery_span(tree, 'tree')
        regions[-1].update(span, sight_segments=plant_segments(tree_trunks(tree),span['height_ft']))
    for index, row in enumerate(document.get("materials") or []):
        if row['material'] != BAMBOO:
            continue
        span = _scenery_span(row, 'material')
        plants = [p for g in bamboo_groups(row['cells']) for p in bamboo_culms(g['x'],g['y'],g['size'])]
        physical = plant_segments(plants,span['height_ft'])
        if not physical['segments']:
            continue
        cells = {tuple(c) for c in row['cells']}
        if cells:
            region(f"bamboo.height.{index + 1}", "SIGHT_BLOCKED", cells, 1, "Dense bamboo: blocks sight below its top.")
            regions[-1].update(span, sight_segments=physical)
    for index, row in enumerate(document.get("terrain") or []):
        cells = {tuple(cell) for cell in row["cells"]}
        span = _scenery_span(row, 'terrain')
        if terrain_blocks_sight({**row,**span}):
            for x,y in sorted(cells):
                region(f'terrain.sight.{index+1}.{x}.{y}', 'SIGHT_BLOCKED', [(x,y)],
                       2 if row['type']=='DIFFICULT' else 1,
                       'Tall scenery: blocks sight below its top.')
                regions[-1].update(span)
                if row.get('look') == 'bamboo_clump':
                    regions[-1]['description'] = 'Bamboo trunks: block sight below their tops; small shoots are decorative.'
                    regions[-1]['sight_segments'] = plant_segments(bamboo_culms(x,y,clump=True,rotation=row.get('rotation',0)),span['height_ft'])
        kind = {"DIFFICULT": "OPEN"}.get(row["type"], row["type"])
        region(f"terrain.{index + 1}", kind, cells, 2 if row["type"] == "DIFFICULT" else 1, row["type"].replace("_", " ").title())
        if cells:
            regions[-1].update(_scenery_span(row, "terrain"))
            if row["type"] == "DIFFICULT":
                # Painted difficult ground is mundane map terrain (combat/zones.py);
                # Unimpeded Positioning's Focus waiver may ignore its price outside combat.
                regions[-1]["nonmagical_difficult"] = 1
            for key in ('material', 'sealed'):
                if key in row:
                    regions[-1][key] = row[key]
            if row.get('travel_kind'):
                regions[-1]['travel_kind'] = row['travel_kind']
    # Named editor terrains already declare their matter in terrain.json.
    # Floors describe only the ground layer; never assign soil to a wall merely
    # because the floor below it is grass. No tag changes ordinary movement.
    from .zones import terrain_rules
    for index, row in enumerate(document.get('materials') or []):
        family, _, name = row['material'].partition(':')
        material = (EDITOR_MATERIALS.get(name) if family == 'floor' else
                    (terrain_rules().get('terrains', {}).get(name) or {}).get('material'))
        if material:
            region(f'material.{index}', 'OPEN', {tuple(c) for c in row['cells']}, 1, str(material))
            regions[-1].update(material=material, height_ft=5, material_only=True)
    starts = {f"team1_{index + 1}": {"x": x, "y": y} for index, (x, y) in enumerate(document["starts"].get("team1") or [])}
    starts.update({f"team2_{index + 1}": {"x": x, "y": y} for index, (x, y) in enumerate(document["starts"].get("team2") or [])})
    if not starts:  # default: west and east edges
        rows = [height // 2, max(1, height // 2 - 3), min(height - 2, height // 2 + 3)]
        starts = {f"team1_{i + 1}": {"x": 1, "y": y} for i, y in enumerate(rows)}
        starts.update({f"team2_{i + 1}": {"x": width - 2, "y": y} for i, y in enumerate(rows)})
    return {
        "note": "Generated from a tabletop map (combat/tabletop.py); edit the map in the Tabletop map editor.",
        "battlefield_version": "1.0.0",
        "display_name": document["display_name"],
        **{key: document[key] for key in ("description", "picker_order") if key in document},
        "natural_haze": bool(document.get("natural_haze")),
        **({"travel_regions": document['travel_regions']} if document.get('travel_regions') else {}),
        "stable_id": MAP_PREFIX + document["map_id"],
        "kind": "BATTLEFIELD",
        "source": "Tabletop map (owner-drawn)",
        "information_model": "FULLY_VISIBLE",
        "victory_boundary": "NONLETHAL_WARDED_COURT",
        "square_size_ft": 5,
        "width_squares": width,
        "height_squares": height,
        "starting_positions": starts,
        "team_starts": {"team1": [starts[key] for key in starts if key.startswith("team1_")],
                        "team2": [starts[key] for key in starts if key.startswith("team2_")]},
        "terrain_regions": regions,
        **({'catch_dc': document['catch_dc']} if document.get('catch_dc') is not None else {}),
        # Horizontal roof surfaces: movement uses roof_surfaces; sight uses roof_cells (height-aware, no movement rule).
        **({'roof_surfaces': roof_surfaces} if roof_surfaces else {}),
        "roof_cells": roof_cells(document, wall_cells),
        "tabletop": table_section(document),
        # Named terrain painted on the map: each becomes an area with that terrain's rules when a fight starts on it.
        "map_terrain": [{"terrain": row["material"].split(":", 1)[1], "cells": [list(cell) for cell in row["cells"]],
                         "natural_haze": bool(document.get("natural_haze")),
                         **(document.get("terrain_numbers") or {"save_dc": 13, "pb": 2})}
                        for row in document.get("materials") or [] if row["material"].startswith("terrain:")],
        # Placed objects and structures (combat/ext/objects.py makes them real when a fight starts).
        "map_objects": [{**row, **_scenery_span(row, "object"),
                         **({'height_ft': roof_heights[(row['x'], row['y'])]}
                            if row.get('kind') in {'wall_section', 'door', 'gate', 'portcullis'} and row.get('height_ft') is None
                            and (row['x'], row['y']) in roof_heights else {})}
                        for row in document.get("objects") or []],
    }


def table_section(document: dict[str, Any]) -> dict[str, Any]:
    """The map's look for the table, in whole numbers (a sealed match's arena allows no floats):
    wall points in hundredths of a square, opacities and detail in percent."""
    background, display = document["background"], document["display"]
    return {
        "map_id": document.get("map_id"),
        **({'catch_dc': document['catch_dc']} if document.get('catch_dc') is not None else {}),
        **({"roofs": document["roofs"]} if document.get("roofs") else {}),
        "scale": 100,
        "walls": [{**wall, "points": [[int(round(x * 100)), int(round(y * 100))] for x, y in wall["points"]]} for wall in document["walls"]],
        "background": {"asset": background.get("asset"), "opacity_pct": int(round(float(background.get("opacity", 1.0)) * 100)),
                       "fit": background.get("fit") or "cover", "style": background.get("style") or "flagstone",
                       "seed": int(background.get("seed") or 1)},
        "display": {"grid_opacity_pct": int(round(float(display.get("grid_opacity", 0.35)) * 100)),
                    "detail_pct": int(round(float(display.get("detail", 1.0)) * 100)),
                    "grid_color": display.get("grid_color") or "#d8c9a3",
                    "blend_pct": int(round(float(display.get("blend", 0.0)) * 100))},
        **({'openings': [{key: obj[key] for key in ('kind', 'x', 'y', 'mount_axis', 'mount_line')}
                         for obj in document.get('objects', []) if 'mount_axis' in obj]}
           if any('mount_axis' in obj for obj in document.get('objects', [])) else {}),
        "trees": [dict(tree) for tree in document.get("trees") or []],
        "materials": [dict(row) for row in document.get("materials") or [] if row["material"] == BAMBOO],
        **({"decor": [dict(row) for row in document["decor"]]} if document.get("decor") else {}),
        # Floor patches (a named terrain is drawn as the fight's own area).
        "floors": [{"style": row["material"].split(":", 1)[1], "cells": [list(cell) for cell in row["cells"]]}
                   for row in document.get("materials") or [] if row["material"].startswith("floor:")],
        "terrain": [{"type": row["type"], **({"look": row["look"]} if row.get("look") else {}),
                     **{key: row[key] for key in ('material', 'sealed') if key in row},
                     **_scenery_span(row, "terrain"),
                     **({"rotation": row["rotation"]} if row.get("rotation") else {}),
                     "cells": [list(cell) for cell in row["cells"]]} for row in document.get("terrain") or []],
    }


def battlefield_as_map(arena: dict[str, Any]) -> dict[str, Any]:
    """A built-in arena seen as an editable map (its blocked cells become filled square walls)."""
    walls = []
    for region in arena.get("terrain_regions") or []:
        if region.get("terrain_type") not in {"BLOCKED", "SIGHT_BLOCKED"}:
            continue
        for cell in region.get("cells") or []:
            walls.append({"shape": "rect", "points": [[cell["x"], cell["y"]], [cell["x"] + 1, cell["y"] + 1]], "filled": True,
                          "blocks": "sight_and_movement" if region["terrain_type"] == "BLOCKED" else "sight"})
    starts = sorted(arena.get("starting_positions", {}).values(), key=lambda spot: (spot["x"], spot["y"]))
    half = len(starts) // 2
    team_starts = arena.get("team_starts") or {}
    tabletop = arena.get("tabletop") or {}
    scale = int(tabletop.get("scale") or 1)
    background, display = tabletop.get("background") or {}, tabletop.get("display") or {}
    terrain = []
    for region in arena.get("terrain_regions") or []:
        kind = region.get("terrain_type")
        kind = "DIFFICULT" if kind == "OPEN" and int(region.get("movement_cost") or 1) > 1 else kind
        if kind in {"SIMPLE_COVER", "QI_HAZARD", "DIFFICULT"}:
            terrain.append({"type": kind, "cells": [[cell["x"], cell["y"]] for cell in region.get("cells") or []]})
    return normalize_map({
        "map_id": str(arena.get("stable_id", "arena")).split(":")[-1].replace(".", "-").replace("_", "-")[:64],
        "display_name": arena.get("display_name") or "Arena",
        "width_squares": arena["width_squares"], "height_squares": arena["height_squares"],
        # A table section stores points in 1/scale squares and looks in percent (sealed arenas allow no floats).
        "walls": [{**wall, "points": [[x / scale, y / scale] for x, y in wall["points"]]} for wall in tabletop["walls"]] if tabletop.get("walls") else walls,
        "background": {"asset": background.get("asset"), "fit": background.get("fit"), "style": background.get("style"), "seed": background.get("seed"),
                       "opacity": background["opacity_pct"] / 100 if "opacity_pct" in background else background.get("opacity", 1.0)},
        "display": {"grid_color": display.get("grid_color"),
                    "grid_opacity": display["grid_opacity_pct"] / 100 if "grid_opacity_pct" in display else display.get("grid_opacity", 0.35),
                    "detail": display["detail_pct"] / 100 if "detail_pct" in display else display.get("detail", 1.0)},
        "terrain": terrain,
        **({'catch_dc': arena['catch_dc']} if arena.get('catch_dc') is not None else {}),
        "objects": arena.get("map_objects") or [],
        "materials": [{"material": "floor:" + row["style"], "cells": row["cells"]}
                      for row in tabletop.get("floors", [])],
        **({"roofs": tabletop["roofs"]} if tabletop.get("roofs") else {}),
        "starts": ({team: [[spot["x"], spot["y"]] for spot in team_starts.get(team) or []] for team in ("team1", "team2")} if team_starts
                   else {"team1": [[s["x"], s["y"]] for s in starts[:half]], "team2": [[s["x"], s["y"]] for s in starts[half:]]}),
    })


TEAM_MODES = ("MANUAL", "LOCAL_AUTO")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


class TeamPresetStore:
    """Saved fight setups (owner 2026-09-29: "some kind of team saver"): who is on each side, who plays them, the buffs
    cast before the fight, the map and the fight's name, under ``<data>/team_presets/presets.json`` keyed by name."""

    MAX_PRESETS = 200
    NOT_FOUND_MESSAGE = "Unknown team setup."

    def __init__(self, root: Path):
        self.path = Path(root) / "presets.json"

    def _read(self) -> dict[str, Any]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return document if isinstance(document, dict) else {}

    def list(self) -> list[dict[str, Any]]:
        from .roster_selection import preset_available
        return sorted((row for row in self._read().values() if preset_available(row)),
                      key=lambda row: str(row.get("name", "")).lower())

    @contextmanager
    def _mutation(self):
        """Serialize read/check/replace across threads and processes on a stable sidecar.

        Locking the JSON inode would not work: atomic replacement changes that inode.
        Readers need no lock because they see either complete version of the document.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _normalize(preset: dict[str, Any]) -> dict[str, Any]:
        from .roster_selection import preset_available, RETIRED_MESSAGE
        if not preset_available(preset):
            raise TabletopError("COMBAT_FIGHTER_RETIRED", RETIRED_MESSAGE)
        name = " ".join(str(preset.get("name") or "").split())[:60]
        if not name:
            raise TabletopError("TEAM_PRESET_NAME", "Give the team setup a name.")
        teams = preset.get("teams")
        if not isinstance(teams, list) or len(teams) != 2:
            raise TabletopError("TEAM_PRESET_INVALID", "A team setup has two sides.")
        sides = []
        for side in teams:
            if not isinstance(side, list) or not 1 <= len(side) <= 6:
                raise TabletopError("TEAM_PRESET_INVALID", "Each side needs one to six fighters.")
            members = []
            for member in side:
                pid = str((member or {}).get("pid") or "")
                if not _PROJECT_RE.match(pid):
                    raise TabletopError("TEAM_PRESET_INVALID", "Unknown fighter in the team setup.")
                mode = str(member.get("mode") or "LOCAL_AUTO")
                # Setup controller choices are persisted independently of the installed
                # registry. The UI falls back to AI if that model is later removed.
                model_choice = mode.startswith("MODEL:") and 0 < len(mode[6:]) <= 200
                prefight = [str(item)[:200] for item in (member.get("prefight") or [])][:4] if member.get("prefight") is not None else None
                members.append({"pid": pid, "mode": mode if mode in TEAM_MODES or model_choice else "LOCAL_AUTO", "prefight": prefight})
            sides.append(members)
        arena = preset.get("arena_id")
        return {"name": name, "teams": sides, "arena_id": str(arena)[:200] if arena else None,
                "fight_name": str(preset.get("fight_name") or "")[:120] or None}

    def save(self, preset: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(preset)
        with self._mutation():
            document = self._read()
            if normalized["name"] not in document and len(document) >= self.MAX_PRESETS:
                raise TabletopError("TEAM_PRESET_FULL", "Too many saved team setups; delete one first.")
            document[normalized["name"]] = normalized
            _atomic_write(self.path, (json.dumps(document, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        return normalized

    def delete(self, name: str) -> None:
        with self._mutation():
            document = self._read()
            if name not in document:
                raise TabletopError("TEAM_PRESET_NOT_FOUND", self.NOT_FOUND_MESSAGE, 404)
            del document[name]
            _atomic_write(self.path, (json.dumps(document, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


class SingleTeamPresetStore(TeamPresetStore):
    """Side-independent teams in teams.json; never reads or rewrites legacy presets.json.

    Names have a separate namespace from whole setups. Replacement requires an
    explicit replace flag after the caller confirms the normalized name.
    """

    NOT_FOUND_MESSAGE = "Unknown saved team."

    def __init__(self, root: Path):
        self.path = Path(root) / "teams.json"

    @staticmethod
    def _normalize(preset: dict[str, Any]) -> dict[str, Any]:
        # Reuse the setup member validation, including control and pre-fight choices.
        members = preset.get("members")
        if not isinstance(members, list) or any(not isinstance(member, dict) for member in members):
            raise TabletopError("TEAM_PRESET_INVALID", "A saved team needs one to six fighters.")
        if any(member.get("prefight") is not None and not isinstance(member["prefight"], list) for member in members):
            raise TabletopError("TEAM_PRESET_INVALID", "Casts before the fight must be a list.")
        normalized = TeamPresetStore._normalize({"name": preset.get("name"), "teams": [members, members]})
        return {"name": normalized["name"], "members": normalized["teams"][0]}

    def save(self, preset: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(preset)
        with self._mutation():
            document = self._read()
            if normalized["name"] in document and preset.get("replace") is not True:
                raise TabletopError("TEAM_NAME_EXISTS", "A team with that name already exists. Confirm replacement.", 409)
            if normalized["name"] not in document and len(document) >= self.MAX_PRESETS:
                raise TabletopError("TEAM_PRESET_FULL", "Too many saved teams; delete one first.")
            document[normalized["name"]] = normalized
            _atomic_write(self.path, (json.dumps(document, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        return normalized

class TabletopMapStore:
    """Owner maps plus optional read-only shipped editor maps.

    Built-in ids are reserved; the editor must copy a built-in to a new owner id.
    Both sources use the same rasterizer and battlefield conversion.
    A built-in with ``retired: true`` is omitted from listings and new-fight
    arenas. ``get`` still resolves it for old references; retirement metadata
    never enters normalized maps or sealed battlefields. Owner maps are unaffected.
    """

    def __init__(self, root: Path, builtin_root: Path | None = None):
        self.root = Path(root)
        self.assets = self.root / "assets"
        self.builtin_root = Path(builtin_root) if builtin_root is not None else None

    def _builtin_path(self, map_id: str) -> Path | None:
        self._path(map_id)  # validate before constructing either path
        path = self.builtin_root / f"{map_id}.json" if self.builtin_root else None
        return path if path is not None and path.is_file() else None

    def _assert_editable(self, map_id: str) -> None:
        if self._builtin_path(map_id):
            raise TabletopError("MAP_READ_ONLY", "Copy this built-in map with a new name before editing it.", 409)

    def _path(self, map_id: str) -> Path:
        if not MAP_ID_RE.match(map_id or ""):
            raise TabletopError("MAP_ID_INVALID", "Unknown map.", 404)
        return self.root / f"{map_id}.json"

    def list(self) -> list[dict[str, Any]]:
        rows = []
        paths = {path.stem: path for path in self.root.glob("*.json")}
        if self.builtin_root:
            paths.update({path.stem: path for path in self.builtin_root.glob("*.json")})
        for path in sorted(paths.values()):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if self.builtin_root and path.parent == self.builtin_root and document.get("retired") is True:
                continue
            rows.append({"map_id": document.get("map_id"), "display_name": document.get("display_name"),
                         "width_squares": document.get("width_squares"), "height_squares": document.get("height_squares"),
                         "walls": len(document.get("walls") or []), "arena_id": MAP_PREFIX + str(document.get("map_id")),
                         "background": (document.get("background") or {}).get("asset"),
                         "builtin": bool(self.builtin_root and path.parent == self.builtin_root)})
            rows[-1].update({key: document[key] for key in ("description", "picker_order") if key in document})
        return sorted(rows, key=arena_picker_order)

    def get(self, map_id: str) -> dict[str, Any]:
        path = self._builtin_path(map_id) or self._path(map_id)
        if not path.is_file():
            raise TabletopError("MAP_NOT_FOUND", "Unknown map.", 404)
        document = normalize_map(json.loads(path.read_text(encoding="utf-8")))
        # The rules squares follow the current rules (bamboo stands block sight since 2026-09-29), not the ones it was
        # saved under.
        blocked, sight = rasterize(document)
        document["cells"] = {"blocked": sorted(list(cell) for cell in blocked), "sight": sorted(list(cell) for cell in sight)}
        return document

    def save(self, document: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_map(document)
        self._assert_editable(normalized["map_id"])
        asset = normalized["background"]["asset"]
        if asset and not (self.assets / asset).is_file():
            raise TabletopError("MAP_BACKGROUND_INVALID", "The background image was not uploaded.")
        _check_shared_squares(normalized["objects"])
        blocked, sight = rasterize(normalized)
        for team in ("team1", "team2"):
            normalized["starts"][team] = [spot for spot in normalized["starts"][team] if tuple(spot) not in blocked]
        normalized["cells"] = {"blocked": sorted(list(cell) for cell in blocked), "sight": sorted(list(cell) for cell in sight)}
        _atomic_write(self._path(normalized["map_id"]), (json.dumps(normalized, indent=1) + "\n").encode("utf-8"))
        return normalized

    def delete(self, map_id: str) -> None:
        self._assert_editable(map_id)
        path = self._path(map_id)
        if not path.is_file():
            raise TabletopError("MAP_NOT_FOUND", "Unknown map.", 404)
        path.unlink()

    def save_asset(self, data: bytes, content_type: str) -> str:
        extension = ASSET_TYPES.get(str(content_type).split(";")[0].strip().lower())
        if extension is None:
            raise TabletopError("MAP_BACKGROUND_INVALID", "Upload a PNG, JPEG or WebP image.")
        if not data or len(data) > MAX_ASSET_BYTES:
            raise TabletopError("MAP_BACKGROUND_INVALID", "Images must be under 12 MB.")
        magic = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".webp": b"RIFF"}[extension]
        if not data.startswith(magic):
            raise TabletopError("MAP_BACKGROUND_INVALID", "That file is not the image type it claims to be.")
        name = hashlib.sha256(data).hexdigest() + extension
        target = self.assets / name
        if not target.is_file():
            _atomic_write(target, data)
        return name

    def asset_path(self, name: str) -> Path:
        if not re.match(r"^[0-9a-f]{64}\.(png|jpg|webp)$", name or ""):
            raise TabletopError("MAP_BACKGROUND_INVALID", "Unknown image.", 404)
        path = self.assets / name
        if not path.is_file():
            raise TabletopError("MAP_BACKGROUND_INVALID", "Unknown image.", 404)
        return path

    def arenas(self) -> dict[str, dict[str, Any]]:
        result = {}
        for row in self.list():
            try:
                result[row["arena_id"]] = to_battlefield(self.get(str(row["map_id"])))
            except (TabletopError, KeyError, ValueError):
                continue
        return result


# ---------------------------------------------------------------- events
def _dice_groups(roll: dict[str, Any]) -> list[dict[str, int]]:
    match = re.match(r"^\s*(\d+)d(\d+)", str(roll.get("expression") or ""))
    sides = int(match.group(2)) if match else 20
    return [{"sides": sides, "value": int(value)} for value in roll.get("dice") or []]


# Roll reason heads whose die decides something the table should say, instead of the bare "1d2".
# Generic: any interception provider names its die TARGET_INTERCEPT (contract in combat/ext/__init__.py).
_ROLL_PURPOSES = {"TARGET_INTERCEPT": "Which target do you hit?"}


def _roll_kind(reason: str) -> str:
    head = reason.split(":", 1)[0].upper()
    if head.startswith("ATTACK") or "ATTACK" in head:
        return "attack"
    if head.startswith("SAVE") or head.endswith("_SAVE") or "SAVE" in head:
        return "save"
    if "DAMAGE" in head or head.startswith("DAMAGE"):
        return "damage"
    if head == "INITIATIVE":
        return "initiative"
    return "plain"


def dice_rows(rolls: Iterable[dict[str, Any]], names: dict[str, str], definition_names: dict[str, str]) -> list[dict[str, Any]]:
    """Roll records as dice for the table (values come from the engine's roller)."""
    rows = []
    for roll in rolls:
        reason = str(roll.get("reason") or "")
        source = next((part for part in reason.split(":") if part.startswith("action:") or part.startswith("system:")), None)
        if source is None:
            match = re.search(r"(action:[^:]+(?::[^:]+)*?)(?::\d+)?$", reason)
            source = match.group(1) if match else None
        label = definition_names.get(source or "", "") if source else ""
        kind = _roll_kind(reason)
        who = names.get(str(roll.get("actor_id")), "")
        # A roll is labelled by what its die decides, never by its dice notation alone.
        purpose = _ROLL_PURPOSES.get(reason.split(":", 1)[0].upper())
        rows.append({
            "roll_id": roll.get("roll_id"), "actor_id": roll.get("actor_id"), "kind": kind, "reason": reason,
            "label": " · ".join(part for part in (who, purpose or label or kind.title()) if part),
            "groups": _dice_groups(roll),
            "discarded": [{"sides": 20, "value": int(value)} for value in roll.get("discarded") or []],
            "modifier": int(roll.get("modifier") or 0), "total": int(roll.get("total") or 0),
            "natural": roll.get("natural_result"), "mode": roll.get("mode") or "NORMAL",
            "mode_sources": roll.get('mode_sources') or [],
        })
    return rows


# journal_since is re-exported from combat/journal_feed.py, which reads the
# journal incrementally and returns exactly what this function used to return
# for the same request.


# ---------------------------------------------------------------- sheet and buttons
def _json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def sheet_summary(sheet: dict[str, Any], *, bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pop-out sheet's data: identity, abilities, saves, skills, defences, resources."""
    from character_sheet.path_display import path_display
    identity = sheet.get("identity") or {}
    stats = sheet.get("ability_scores_and_statistics") or {}
    abilities = {row["ability"]: {"score": int(row["score"]), "modifier": int(row["modifier"])}
                 for row in _json(stats.get("abilities")) or [] if isinstance(row, dict) and row.get("ability") in ABILITIES}
    pb = int(identity.get("proficiency_bonus") or 2)
    listed = {row["skill"]: row for row in _json(stats.get("skills")) or [] if isinstance(row, dict)}
    skills = []
    for name, ability in SKILLS:
        row = listed.get(name)
        bonus = int(row["bonus"]) if row else abilities.get(ability, {}).get("modifier", 0)
        skills.append({"skill": name, "ability": ability, "bonus": bonus,
                       "proficiency": (row or {}).get("proficiency") or "none"})
    ac = _json(stats.get("armor_class")) or {}
    hp = _json(stats.get("hit_points")) or {}
    speed = _json(stats.get("speed")) or {}
    initiative = _json(stats.get("initiative")) or {}
    resource = _json(stats.get("primary_resource")) or {}
    paths = identity.get("paths") or []
    return {
        "name": identity.get("display_name") or identity.get("name") or "Character",
        "concept": identity.get("concept"),
        **path_display(sheet),
        "species": identity.get("species"), "size": identity.get("size"),
        "path": identity.get("path"), "paths": [row.get("display_name") for row in paths if isinstance(row, dict)],
        "cultivation_level": identity.get("cultivation_level"), "realm": identity.get("realm_display") or identity.get("realm"),
        "key_ability": identity.get("key_ability"),
        "proficiency_bonus": pb,
        "abilities": [{"ability": key, "name": ABILITY_NAMES[key], **abilities.get(key, {"score": 10, "modifier": 0})} for key in ABILITIES],
        "saves": [{"ability": key, "bonus": abilities.get(key, {}).get("modifier", 0)} for key in ABILITIES],
        "skills": skills,
        "passive": {"perception": 10 + next(row["bonus"] for row in skills if row["skill"] == "Perception"),
                    "investigation": 10 + next(row["bonus"] for row in skills if row["skill"] == "Investigation"),
                    "insight": 10 + next(row["bonus"] for row in skills if row["skill"] == "Insight")},
        # The sheet's active AC (chosen calculation plus its always-on bonuses), the same number the fight uses.
        "armor_class": int(ac.get("value") or ac.get("base_value") or 10) if isinstance(ac, dict) else int(ac or 10),
        "armor_note": (ac.get("calculation") if isinstance(ac, dict) else None),
        "starting_loadout": ((bundle or {}).get("carrying") or {}).get("starting_loadout"),
        "hit_points": {"maximum": _maximum_hit_points(hp)},
        "speed_ft": int(speed.get("walking_ft") or 30),
        "initiative": int(initiative.get("bonus") or abilities.get("DEX", {}).get("modifier", 0)),
        "technique_attack_bonus": stats.get("technique_attack_bonus"), "technique_save_dc": stats.get("technique_save_dc"),
        "resource": {"name": resource.get("name") or "Qi", "maximum": int(resource.get("maximum") or 0)},
        "resources": compiled_resource_pools(resource, bundle),
    }


def _maximum_hit_points(hp: dict[str, Any]) -> int:
    """The sheet's maximum Hit Points, refused rather than defaulted.

    This used to read ``int(hp.get("maximum") or 1)``, which turned a sheet with no hit points into a character
    with one (AUDIT9 row 5).  A character whose hit points are missing is a broken sheet, and saying so is
    better than a fighter who dies to the first scratch.
    """
    raw = hp.get("maximum")
    try:
        maximum = int(raw)
    except (TypeError, ValueError):
        maximum = 0
    if maximum > 0:
        return maximum
    raise TabletopError("TABLETOP_HIT_POINTS_MISSING",
                        "This character has no maximum Hit Points on their sheet, so they cannot take part. "
                        "Ask the Game Master to fix their hit points.", 409)


def _pools(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """Every cultivation pool, primary first: a Body + Spirit character has Stamina and Resonance."""
    pools = [{"name": resource.get("name") or "Qi", "maximum": int(resource.get("maximum") or 0)}]
    for definition in resource.get("definitions") or []:
        name = str((definition or {}).get("name") or "")
        limit = definition.get("max") if definition.get("max") is not None else definition.get("maximum")
        if name and limit is not None and name.lower() not in {pool["name"].lower() for pool in pools}:
            pools.append({"name": name, "maximum": int(limit or 0)})
    return pools


def compiled_resource_pools(resource: dict[str, Any], bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Sheet cultivation pools plus compiled named Path/Subpath pools.

    TabletopService supplies its sealed compilation. Named pools use the shared
    player label and true compiled capacity, so spending abilities have a visible
    resource even when the authored sheet has no separate resource definition.
    Missing bundle preserves the ordinary primary/secondary cultivation display.
    Uses counters remain on their ability buttons rather than becoming pools.
    """
    from .resource_labels import resource_name
    pools = _pools(resource)
    seen = {row['name'].casefold() for row in pools}
    for row in ((bundle or {}).get('actor_template') or {}).get('resources') or []:
        ident = str(row.get('resource_id') or '')
        name = resource_name(ident)
        if ident.startswith('resource:named.') and name.casefold() not in seen:
            pools.append({'name': name, 'maximum': int(row['maximum']), 'resource_id': ident})
            seen.add(name.casefold())
    return pools


def _economy_group(economy: str) -> str:
    from .action_economy import group_for
    return group_for(economy)


def _cost_text(costs: Iterable[Any]) -> str:
    parts = []
    for row in costs or []:
        resource, amount = (row[0], row[1]) if isinstance(row, (list, tuple)) else (row.get("resource_id"), row.get("amount"))
        resource = str(resource)
        if resource.startswith("resource:uses."):
            parts.append("1 use")
        else:
            parts.append(f"{amount} {resource.split('.')[-1].replace('_', ' ').title()}")
    return ", ".join(parts)


def damage_text(typed: dict[str, Any], cl: int) -> str:
    """Compiled damage for tabletop buttons and ext.action_help; presentation only."""
    from factory_authoring.typed_mechanics import dice_for_cl
    from .display_values import display_formula_value, log_display_formula_once

    weapon = typed.get("weapon") or {}
    texts = []
    numbers = typed.get("numbers") or {}

    def walk(effects: list[dict[str, Any]]) -> None:
        # Plug-in effects may use on_hit/on_fail for a named outcome instead
        # of a nested typed packet. Only effect lists contain damage to total.
        if not isinstance(effects, (list, tuple)):
            return
        for effect in effects or []:
            if not isinstance(effect, dict):
                continue
            if effect.get("type") == "damage":
                if effect.get("weapon_damage") and weapon.get("damage"):
                    dice = weapon["damage"]
                    amount = (str(weapon["fixed_damage"]) if weapon.get("fixed_damage") is not None else
                              f"{dice['count']}d{dice['sides']}{_signed(int(dice.get('modifier') or 0)) if dice.get('modifier') else ''}")
                    texts.append(f"{amount} "
                                 f"{str(weapon.get('damage_type') or '').lower()}".strip())
                else:
                    dice = dice_for_cl(effect.get("dice_by_cl"), cl) or effect.get("dice")
                    if isinstance(dice, dict) and dice.get("sides"):
                        bonus = int(dice.get("bonus") or 0) + int(effect.get("flat") or 0)
                        unresolved = []
                        for field, formula in (("bonus_formula", dice.get("bonus_formula")),
                                               ("count_formula", dice.get("count_formula")),
                                               ("formula", effect.get("formula"))):
                            if not formula:
                                continue
                            # Context.dice only consults count_formula for a missing count.
                            if field == "count_formula" and dice.get("count") is not None:
                                continue
                            try:
                                value = display_formula_value(str(formula), numbers,
                                                               attack_ability_modifier=weapon.get("ability_modifier"))
                                if field == "count_formula":
                                    dice = {**dice, "count": value}
                                else:
                                    bonus += value
                            except Exception as exc:
                                log_display_formula_once(str(formula), exc)
                                unresolved.append(field)
                        count = int(dice.get("count") or 0)
                        if "count_formula" in unresolved:
                            label = f"damage dice decided when it hits{_signed(bonus) if bonus else ''}"
                        elif count < 1 or int(dice["sides"]) < 2:
                            label = str(bonus)
                        else:
                            label = f"{count}d{dice['sides']}{_signed(bonus) if bonus else ''}"
                        if any(field != "count_formula" for field in unresolved):
                            label += " + a bonus decided when it hits"
                        texts.append(f"{label} {' '.join(str(t).lower() for t in effect.get('damage_types') or [])}".strip())
                    elif effect.get("flat"):
                        texts.append(f"{effect['flat']} {' '.join(str(t).lower() for t in effect.get('damage_types') or [])}".strip())
            for key in ("on_hit", "on_fail"):
                walk(effect.get(key) or [])

    walk(typed.get("effects") or [])
    return " + ".join(texts)


# Hover text for buttons with no rules entry of their own (owner 2026-09-25).
BASIC_DESCRIPTIONS = {
    "Dash": "Gain extra movement equal to your speed for the rest of this turn.",
    "Dodge": "Until the start of your next turn, attack rolls against you have disadvantage if you can see the attacker, "
             "and you make Dexterity saving throws with advantage.",
    "Disengage": "Your movement doesn't provoke opportunity attacks for the rest of this turn.",
    "Hold Position": "Hold your ground once on your turn, without spending an Action or movement. You can still take other actions or end your turn.",
    "End Turn": "End your turn. Unused movement and actions are lost.",
    "Hide": "Only while no enemy can see you (darkness, a thick cloud, behind a wall or out of sight): a DC 15 Dexterity (Stealth) "
            "check. On a success you are Hidden -- your attacks have Advantage and attacks against you Disadvantage -- and your "
            "total is the DC to find you. It ends when you attack, an enemy finds you, or you end a move in an enemy's plain view.",
    "Search": "A Wisdom (Perception) check against each hidden enemy's Stealth total; the ones you beat are found. Where sound is "
              "dimmed (Pure Darkness) it has Disadvantage.",
    "Initiative": "Roll a d20 plus your Dexterity modifier to set the order of turns in this fight. The higher roll acts first, "
                  "and every creature rolls again at the start of a new fight.",
}

# The engine's own built-in actions are content rules rather than a character's ability, so they carry no authority
# entry and engine_button_description() is empty for them. This says which engine action is which line above, so the
# text stays written once (BASIC_DESCRIPTIONS) and both the sheet and the table menu can find it by source id: the
# sheet builds these buttons itself, while the menu reads them back out of the engine's catalog and candidates
# (gate2_engine.py offers "system:combat.hold_position" as a HOLD_POSITION candidate, not a catalog action, and
# labels it "Hold position").
SYSTEM_ACTION_DESCRIPTIONS = {
    "system:combat.dash": BASIC_DESCRIPTIONS["Dash"],
    "system:combat.dodge": BASIC_DESCRIPTIONS["Dodge"],
    "system:combat.disengage": BASIC_DESCRIPTIONS["Disengage"],
    "system:combat.hold_position": BASIC_DESCRIPTIONS["Hold Position"],
    "turn:end": BASIC_DESCRIPTIONS["End Turn"],
}


def _shape_button(row: dict[str, Any]) -> dict[str, Any]:
    """An area talent as a sheet row under its ability ("+ Numbing Darkness"; owner 2026-09-27: "still not seeing pure
    darkness or numbing or anything"): choosing it is free and lasts until changed (combat/zones.py _shaped)."""
    from .factory_compiler import _rules_text

    parameters = row.get("parameters") or {}
    talents = list(parameters.get("shape_talents") or [])
    texts = []
    for talent in talents:
        text = str(_rules_text().get(talent) or "")
        texts.append(text.split("\n", 1)[1].strip() if "\n" in text else text)
    name = str(parameters.get("zone_name") or "area")
    return {
        "id": f"act:{row['source_definition_id']}", "label": row["display_name"], "group": "actions", "kind": "combat", "economy": "NONE",
        "combat": {"source_definition_id": row["source_definition_id"], "target_kind": "SELF"}, "roll": None,
        "detail": {"cost": _cost_text(list((parameters.get("shape_costs") or {}).items())) or None, "damage": parameters.get("shape_summary") or None,
                   "gm_riders": 1 if parameters.get("shape_partial") else 0},
        "tags": ["shape"], "source": "auto",
        "description": engine_button_description(row),
        "variant_of": f"act:{parameters.get('shape_of')}",
        # The same ability id as `.parent` on a Blossom picker (option-groups.js groupOptionRows): the sheet
        # nests this row under its ability instead of leaving it alongside it with only a "+" label.
        "parent": parameters.get("shape_of"),
        "modifier": {"id": "+".join(talents) or "plain", "name": parameters.get("shape_label"), "precondition": "", "description": "\n\n".join(texts)},
        "shape": {"zone": parameters.get("zone_shape"), "zone_name": name, "talents": talents, "default": bool(parameters.get("shape_default"))},
    }


def _augment_button(row: dict[str, Any], loadouts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """An augment as a sheet row under its ability ("+ Greater Darkness"): turned on or off for the ability's next uses,
    any number together (owner 2026-09-27; combat/loadout.py)."""
    from .factory_compiler import _rules_text

    parameters = row.get("parameters") or {}
    base, key = parameters["augment_toggle"], parameters["augment_key"]
    costs = next((augment.get("costs") or [] for augment in (loadouts.get(base) or {}).get("augments") or [] if augment["key"] == key), [])
    text = str(_rules_text().get(key) or "")
    return {
        "id": f"act:{row['source_definition_id']}", "label": row["display_name"], "group": "actions", "kind": "combat", "economy": "NONE",
        "combat": {"source_definition_id": row["source_definition_id"], "target_kind": "SELF"}, "roll": None,
        "detail": {"cost": _cost_text(costs) or None, "gm_riders": 0}, "tags": ["augment"], "source": "auto",
        "description": engine_button_description(row),
        "variant_of": f"act:{base}", "augment": True,
        # Same ability id as `.parent` on a Blossom picker: the sheet nests this row under its ability.
        "parent": base,
        "modifier": {"id": key, "name": parameters.get("augment_name"), "precondition": "", "description": text.split("\n", 1)[1].strip() if "\n" in text else text},
    }


def _variant_fields(typed: dict[str, Any]) -> dict[str, Any]:
    """A choice made by an optional modifier ("Water Lash + Water Whip") points at the ability it
    changes; one option of a "Choose one" ability (owner 2026-09-26) carries ``option_of`` instead --
    there is no single base action for it to be a variant of, since the all-options action is never
    compiled (combat/factory_compiler.py)."""
    out: dict[str, Any] = {}
    modifier = typed.get("modifier") or {}
    if typed.get("variant_of") and modifier:
        text = (_authority_index().get(str(modifier.get("id") or "")) or {}).get("description") or ""
        out["variant_of"] = f"act:{typed['variant_of']}"
        out["modifier"] = {"id": modifier.get("id"), "name": modifier.get("name"), "precondition": modifier.get("precondition") or "",
                           "description": text}
    if typed.get("option_of"):
        out["option_of"] = str(typed["option_of"])
        out["option_label"] = str(typed.get("option_label") or "")
    return out


def _button_description(typed: dict[str, Any], detail: dict[str, Any], group: str) -> str:
    """The ability's rules text from the typed authority, or a plain summary of a weapon attack."""
    text = (_authority_index().get(str(typed.get("forged_from") or typed.get("source") or "")) or {}).get("description") or ""
    if text:
        return text
    if group == "attacks" and detail.get("to_hit"):
        attacks = f", {detail['attacks']} attacks per Action" if (detail.get("attacks") or 1) > 1 else ""
        reach = f" ({detail['range']})" if detail.get("range") else ""
        return (f"Weapon attack{reach}: roll 1d20{detail['to_hit']} against the target's Armor Class{attacks}. "
                f"On a hit, deal {detail.get('damage') or 'the weapon damage'}.")
    return ""


def saving_throw_text(save: dict[str, Any] | None, numbers: dict[str, Any]) -> str | None:
    """Display compiled save alternatives in words, without changing resolution."""
    if not save:
        return None
    ability = str(save.get("ability") or "").upper()
    words = " or ".join(ABILITY_NAMES.get(part, part.capitalize()) for part in ability.split("_OR_"))
    dc = numbers.get("save_dc")
    return f"{words} save" + (f", DC {dc}" if dc is not None else "")


def _area_text(typed: dict[str, Any], cl: int) -> str | None:
    """Use the compiled footprint or its printed evidence; never print nullable feet."""
    area = typed.get("area") or {}
    if not area:
        return None
    size = area.get("size_ft")
    for low, high, feet in area.get("size_ft_by_cl") or []:
        if int(low) <= cl <= int(high):
            size = feet
            break
    shape = str(area.get("shape") or "area").replace("_", " ")
    if size is not None:
        return f"{size}-foot {shape}" + (" originating from you" if shape == "cone" else "")
    evidence = next((effect.get("evidence") for effect in _all_effects(typed.get("effects") or [])
                     if effect.get("type") == "zone" and effect.get("evidence")), None)
    return str(evidence or area.get("text") or area.get("evidence") or "Choose the footprint described in the full rules.")


def _compiled_description(row: dict[str, Any]) -> str:
    """General fallback for generated actions: printed source, then compiled evidence.

    Plug-ins supply contextual rules through button_description before this fallback.
    No effect identifiers are exposed and rules are never invented when evidence is absent.
    """
    from .display_text import printed_headers
    typed = (row.get("parameters") or {}).get("typed") or {}
    attack = next((effect for effect in typed.get('effects') or [] if effect.get('type') == 'attack'), None)
    if attack:
        numbers = typed.get('numbers') or {}
        detail = {'to_hit': _signed(int(numbers.get('attack_bonus') or 0)),
                  'attacks': int(attack.get('count') or 1),
                  'range': f"{row['range_ft']} ft" if row.get('range_ft') else None,
                  'damage': damage_text(typed, int(numbers.get('cl') or 1)) or None}
        return _button_description(typed, detail, 'attacks')
    index = _authority_index()
    source = str(typed.get("forged_from") or typed.get("source") or "")
    suffix = str(row.get("source_definition_id") or "").split(".", 2)[-1]
    key = next((candidate for candidate in (source, suffix) if candidate in index), None)
    if key is None and not source:
        # A match must be a dot-delimited prefix. Check longest first without
        # sorting/scanning thousands of unrelated authority entries per button.
        candidate = suffix
        while "." in candidate:
            candidate = candidate.rsplit(".", 1)[0]
            if candidate in index:
                key = candidate
                break
    if key is None:
        wanted = " ".join(str(row.get("display_name") or "").lower().split())
        key = _mechanic_key(wanted)
    text = (index.get(key or "") or {}).get("description")
    if text:
        # The same printed header cleanup the status hovers get, so a fight button's
        # tooltip never prints "Cost: None" or a run-together header line either.
        return printed_headers(text)
    evidence = list(dict.fromkeys(str(effect["evidence"]) for effect in _all_effects(typed.get("effects") or [])
                                  if effect.get("evidence")))
    return "\n".join(evidence)


def engine_button_description(row: dict[str, Any]) -> str:
    """Shared action text interface with tabletop's compiled-evidence fallback.

    The printed rules are stated with the cost this button is really charged (decision_text.cost_as_charged),
    so a button never shows one figure while the fight log charges another.
    """
    from .action_text import describe_action
    from .decision_text import cost_as_charged
    from .turn_uses import usage_explanations

    from .ext.setting_choices import is_setting_action
    text = describe_action(row, fallback=_compiled_description)
    if not is_setting_action(row):
        text = cost_as_charged(text, row.get("costs"))
    typed = (row.get('parameters') or {}).get('typed') or {}
    names = _AuthorityNames(_authority_index())
    usage = usage_explanations(typed, names, row.get('display_name') or 'This action')
    return ' '.join(part for part in (text, _variant_cost_sentence(row, typed), usage) if part)


def _variant_cost_sentence(row: dict[str, Any], typed: dict[str, Any]) -> str:
    """State what a "+ modifier" version really costs, in the plain words a player reads first.

    A composed variant keeps its base ability's printed section as its button text, and that section
    states the BASE cost: the rider it was composed with is charged on top (factory_compiler.py builds
    the variant with ``"costs": [*costs, *spend]``), but the rider's own "Cost: ..." line lives in a
    different record and never reached the button. The player read "Cost: 1 CP" and paid 2. The
    compiled cost list is the true total, so it is stated here, once, in the same words the cost
    readout uses everywhere else. A version that is not a composed variant, or that costs nothing,
    reads exactly as before.
    """
    modifier = typed.get('modifier') or {}
    if not typed.get('variant_of') or not modifier.get('name'):
        return ''
    stated = _cost_text(row.get('costs') or [])
    return f"This version costs {stated} in total." if stated else ''


def engine_button_description_for_name(name: str, source_definition_id: str = "",
                                       parameters: dict[str, Any] | None = None) -> str:
    """Resolve generated menu rows to printed rules or plain item handling without exposing IDs."""
    import re

    label = " ".join(str(name or "").split())
    source = str(source_definition_id or "")
    basic_label = next((text for key, text in BASIC_DESCRIPTIONS.items() if key.lower() == label.lower()), None)
    if basic_label:
        return basic_label
    if ".item_drop." in source:
        return "Drop this item in your space. Dropping it costs no action; it can be picked up again."
    if ".item_pickup." in source:
        return "Pick up this item from a nearby space to carry it again."
    feature, separator, mode = label.partition(":")
    setting_only = bool((parameters or {}).get("setting_only"))
    names = _mechanic_names()
    mode_label = mode.strip().partition("(")[0].strip() if separator else ""
    mode_id = _mechanic_key(" ".join(mode_label.lower().split()))
    mode_text = str((_authority_index().get(mode_id or "") or {}).get("description") or "")
    if mode_text:
        head = (f"Free choice, kept until you change it: choose {mode_label} for {feature.strip()}.\n\n"
                if setting_only else "")
        return f"{head}For {mode_label}:\n\n{mode_text}"
    basic_mode = next((text for key, text in BASIC_DESCRIPTIONS.items()
                       if key.lower() == mode_label.lower()), None)
    if basic_mode:
        if setting_only:
            return (f"Free choice, kept until you change it: choose {mode_label} for {feature.strip()}. "
                    f"This selects how the feature works when it next applies.\n\nFor {mode_label}: {basic_mode}")
        return f"For {mode_label}: {basic_mode}"
    if mode_label.lower() == "off":
        return f"Turn off this choice. No {feature.strip()} option is active until you choose one."
    wanted = " ".join(feature.lower().split()) if separator else " ".join(label.lower().split())
    mechanic_id = _mechanic_key(wanted)
    if mechanic_id is None:
        def words(value: str) -> set[str]:
            return {token[:6] if len(token) > 6 else token for token in re.findall(r"[a-z]+", value.lower())}

        wanted_words = words(feature)
        source_words = words(source.partition("typed.")[2])
        candidates = []
        for key, value in names.items():
            authority_words = words(key.replace("_", " ") + " " + value)
            score = len(wanted_words & authority_words)
            if wanted_words and score == len(wanted_words):
                candidates.append((len(source_words & authority_words), score, key))
        if candidates:
            best = max((source_score, score) for source_score, score, _ in candidates)
            matches = [key for source_score, score, key in candidates if (source_score, score) == best]
            if len(matches) == 1:
                mechanic_id = matches[0]
    text = str((_authority_index().get(mechanic_id or "") or {}).get("description") or "")
    if not text and setting_only and mode_label:
        text = ("Free choice, kept until you change it: choose "
                f"{mode_label} for {feature.strip()}. This selects how the feature works when it next applies.")
    if text and separator:
        head = (f"Free choice, kept until you change it: choose {mode_label or mode.strip()} for {feature.strip()}.\n\n"
                if setting_only and not text.startswith("Free choice,") else "")
        return f"{head}For {mode.strip()}:\n\n{text}"
    return text


def engine_button_layout(row: dict[str, Any], *, fallback_text: str = "") -> dict[str, Any]:
    """Read-only layout with compiled fallback and usage clocks.

    ``fallback_text`` carries the shared menu's resolved built-in/setting/name rule
    when the row has no printed or compiled text, so a title-only hover never hides
    that rule. Empty by default; no saved row or existing caller is changed.
    """
    from .action_text import layout_action
    from .turn_uses import usage_explanations

    typed = (row.get('parameters') or {}).get('typed') or {}
    names = _AuthorityNames(_authority_index())
    usage = usage_explanations(typed, names, row.get('display_name') or 'This action')
    return layout_action(row, fallback=lambda item: _compiled_description(item) or fallback_text,
                         extra=[usage] if usage else [])


def _toggle_description(name: str, bundle: dict[str, Any], *, owned_ids: frozenset[str] | None = None) -> str:
    """A plug-in's choice button ("Hidden Strike: Sever Awareness", "Saint-Body Rebuke: Push 5 ft") has no rules text of its
    own: show its feature's, and which option this button picks (owner 2026-09-30: "this doesnt have a description")."""
    key = _toggle_owner(name, bundle, owned_ids=owned_ids)
    text = (_authority_index().get(key or "") or {}).get("description") or ""
    option = str(name).partition(":")[2]
    return f"This button picks: {option.strip()}.\n\n{text}" if text else ""


def _toggle_owner(name: str, bundle: dict[str, Any], *, owned_ids: frozenset[str] | None = None) -> str | None:
    """The mechanic id a "Feature: option" button belongs to, preferring the character's own abilities."""
    feature, _, option = str(name).partition(":")
    if not option:
        return None
    wanted = " ".join(feature.lower().split())
    # The character's own abilities: every compiled action id carries its record id (action:typed.<short>.<record>).
    if owned_ids is None:
        owned = {str(row.get("source_definition_id") or "").split(".", 2)[-1] for row in bundle.get("action_catalog") or []}
        owned |= {str(key) for key in (bundle.get("owned_ids") or bundle.get("mechanic_ids") or [])}
    else:
        owned = owned_ids
    names = _mechanic_names()
    index = _authority_index()
    # The table rebuilds every button on every refresh; answering this from scratch scanned the whole authority
    # against every owned id per button (~150 million checks per refresh in a 15-creature fight, 2026-10-06).
    # The answer depends only on the button name, the owned ids and the authority files, so remember it.
    owned_key = frozenset(owned)
    cache_key = (name, owned_key, _text_stamp("names", _MECHANIC_NAMES), _text_stamp("authority", _AUTHORITY_INDEX))
    if cache_key in _TOGGLE_OWNERS:
        return _TOGGLE_OWNERS[cache_key]
    mine_key = (owned_key, _text_stamp("authority", _AUTHORITY_INDEX))
    if mine_key not in _OWNED_KEYS:
        if len(_OWNED_KEYS) > 256:
            _OWNED_KEYS.clear()
        _OWNED_KEYS[mine_key] = {key for key in index if key in owned or any(own.startswith(key) for own in owned)}
    owned_records = _OWNED_KEYS[mine_key]
    matches = [key for key, row in names.items() if row == wanted]
    if not matches:
        # "Crawling Fever: 2d8 Necrotic" belongs to Court of the Crawling Fever: a name that contains the button's.
        matches = sorted((key for key, row in names.items() if f" {wanted} " in f" {row} "), key=lambda key: len(names[key]))
    mine = lambda key: key in owned_records or key in owned or any(own.startswith(key) for own in owned)
    key = next((key for key in matches if mine(key)), matches[0] if matches else None)
    if key is None:
        # "Suppressing Vein: ...", "Trap form: ..." name a part of an ability: the character's ability whose text names it.
        key = next((key for key in sorted(owned_records)
                    if wanted in " ".join(str((index[key] or {}).get("description") or "").lower().split())), None)
    if len(_TOGGLE_OWNERS) > 20000:
        _TOGGLE_OWNERS.clear()
    _TOGGLE_OWNERS[cache_key] = key
    return key


_TOGGLE_OWNERS: dict[tuple, str | None] = {}
_OWNED_KEYS: dict[tuple, set[str]] = {}


_TEXT_SNAPSHOT: ContextVar[dict | None] = ContextVar("tabletop_text_snapshot", default=None)
_TEXT_INDEX_LOCK = threading.RLock()


@contextmanager
def text_snapshot():
    """Resolve static text assets once per request, including nested table calls.

    Names and printed authority entries retain their own file identities. Each
    outer request checks them afresh; concurrent requests cannot replace this
    request's captured rows or ownership-cache stamps. Outside the scope each
    provider keeps its normal file checks. This never snapshots fight state.
    """
    if _TEXT_SNAPSHOT.get() is not None:
        yield
        return
    token = _TEXT_SNAPSHOT.set({})
    try:
        yield
    finally:
        _TEXT_SNAPSHOT.reset(token)


def _text_stamp(name: str, cache: dict) -> Any:
    frame = _TEXT_SNAPSHOT.get()
    return frame[name][0] if frame is not None and name in frame else cache.get("mtime")


def _mechanic_names() -> dict[str, str]:
    frame = _TEXT_SNAPSHOT.get()
    if frame is not None and "names" in frame:
        return frame["names"][1]
    from .factory_compiler import TYPED_AUTHORITY
    with _TEXT_INDEX_LOCK:
        rows = _load_mechanic_names(TYPED_AUTHORITY)
        if frame is not None:
            frame["names"] = (_MECHANIC_NAMES["mtime"], rows, _MECHANIC_NAMES["first"])
        return rows


def _load_mechanic_names(path: Path) -> dict[str, str]:
    """mechanic id -> its name, lower case (cached with the authority index)."""
    mtime = _text_file_identity(path)
    if _MECHANIC_NAMES.get("mtime") != mtime:
        mechanics = json.loads(path.read_text(encoding="utf-8"))["mechanics"]
        rows = {key: " ".join(str(row.get("name") or "").lower().split()) for key, row in mechanics.items()}
        first = {}
        for key, name in rows.items():
            first.setdefault(name, key)  # preserve the original first-match order
        _MECHANIC_NAMES.update(mtime=mtime, rows=rows, first=first)
    return _MECHANIC_NAMES["rows"]


_MECHANIC_NAMES: dict[str, Any] = {}


def _mechanic_key(name: str) -> str | None:
    """First exact name match, indexed with the same authority snapshot."""
    rows = _mechanic_names()
    frame = _TEXT_SNAPSHOT.get()
    if frame is not None and "names" in frame:
        return frame["names"][2].get(name)
    with _TEXT_INDEX_LOCK:
        if _MECHANIC_NAMES.get("rows") is rows:
            return _MECHANIC_NAMES["first"].get(name)
    # An unscoped caller may hold the older rows while another request reloads
    # the file. Preserve that caller's snapshot and original first-match order.
    return next((key for key, value in rows.items() if value == name), None)


class _AuthorityNames:
    """Read-only name projection for usage text; avoid a full map per button.

    turn_uses.usage_explanations only asks for referenced modifier names. Reading
    those directly keeps current snapshot values, including missing/None names.
    """
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows = rows

    def get(self, key: Any) -> Any:
        return (self.rows.get(key) or {}).get("name")


def _text_file_identity(path: Path) -> tuple:
    """Invalidate presentation indexes on source switches, edits or replacement."""
    stat = path.stat()
    return (str(path.absolute()), stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns)


def _all_effects(effects: list[Any]):
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _all_effects(effect.get(branch))


def setting_button_description(row: dict[str, Any], bundle: dict[str, Any], description: str = "", *,
                               owned_ids: frozenset[str] | None = None) -> str:
    """Shared plain selector text for table buttons and persisted setting statuses.

    General presentation seam: callers supply an owned setting action and its
    compiled bundle. No ability ids are interpreted and no fight state changes.
    """
    from .option_text import setting_text
    return setting_text(row, description or _toggle_description(row["display_name"], bundle, owned_ids=owned_ids))


def untyped_button_text(row: dict[str, Any], bundle: dict[str, Any] | None = None, *,
                        owned_ids: frozenset[str] | None = None) -> str:
    """The printed rule text of a button that has no rules entry of its own.

    Three kinds reach a player with nothing at all (HUNT108: 140 labels, including the four universal actions):
    the engine's built-in actions, a plug-in's "Feature: option" toggle, and a standing choice the player keeps
    until they change it. Each takes its text from the owner-facing source that already exists -- BASIC_DESCRIPTIONS /
    SYSTEM_ACTION_DESCRIPTIONS, the owning feature's authority entry, or the plug-in's own setting_description.

    Shared by the sheet's auto_buttons and the table menu (tabletop_service._menu_descriptions) so both surfaces
    show the same words. Inert for a row that has its own text: a character owning none of these gets "" and its
    buttons are unchanged. `bundle` is the compiled character bundle, needed to find which feature a toggle
    belongs to; without it only the built-in actions can be described.

    ``owned_ids`` optionally supplies the bundle's already-normalized complete
    ownership set for a read-only refresh. Rebuild it when the catalog changes;
    no ownership or rule answer is retained beyond the existing keyed resolver.
    """
    from .ext.setting_choices import is_setting_action

    name = str(row.get("display_name") or "")
    text = SYSTEM_ACTION_DESCRIPTIONS.get(str(row.get("source_definition_id") or "")) or BASIC_DESCRIPTIONS.get(name) or ""
    if text or bundle is None:
        return text
    if is_setting_action(row):
        return setting_button_description(row, bundle, owned_ids=owned_ids)
    return _toggle_description(name, bundle, owned_ids=owned_ids)


def auto_buttons(bundle: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Buttons generated from the compiled combat bundle and the sheet (see docs/tabletop/BUTTON_SCHEMA.md)."""
    from .ext.setting_choices import is_setting_action
    from .ext.attack_modifiers import variant_replaced

    buttons: list[dict[str, Any]] = []
    shapes: list[dict[str, Any]] = []
    loadouts = {row["source_definition_id"]: (row.get("parameters") or {}).get("augment_loadout") or {}
                for row in bundle.get("action_catalog") or [] if (row.get("parameters") or {}).get("augment_loadout")}
    cl = int(summary.get("cultivation_level") or 1)
    for row in bundle.get("action_catalog") or []:
        parameters = row.get("parameters") or {}
        if variant_replaced(row, bundle.get("action_catalog") or []):
            continue  # legacy/AI variants are represented by one player toggle
        setting = parameters.get("attack_modifier_setting")
        if setting:
            if setting["field"] == "on":
                from .ext.attack_modifiers import payment_choices, price
                from .factory_compiler import _rules_text
                parent = next(a for a in bundle["action_catalog"] if a["source_definition_id"] == setting["family"])
                group = next(g for g in parent["parameters"]["typed"]["attack_modifier_loadout"] if g["id"] == setting["modifier"])
                shapes.append({"id": f"act:{row['source_definition_id']}", "label": setting["name"], "group": "actions", "kind": "combat",
                    "economy": "NONE", "combat": {"source_definition_id": row["source_definition_id"], "target_kind": "SELF"}, "roll": None,
                    "detail": {"cost": " or ".join(price(p) for p in payment_choices(group).values()), "gm_riders": 0},
                    "description": engine_button_description(row), "source": "auto", "tags": ["modifier"], "attack_modifier": True,
                    "variant_of": f"act:{setting['family']}", "parent": setting["family"],
                    "modifier": {"id": setting["modifier"], "name": setting["name"],
                    "description": str(_rules_text().get(setting["modifier"]) or ""), "precondition": ""}})
            continue
        if (row.get("parameters") or {}).get("item_action"):
            continue  # Drop / Pick up an item: the table's Items panel (owner 2026-09-27)
        if (row.get("parameters") or {}).get("zone_shape"):
            shapes.append(_shape_button(row))
            continue
        if (row.get("parameters") or {}).get("augment_toggle"):
            if (row.get("parameters") or {}).get("augment_key"):
                shapes.append(_augment_button(row, loadouts))
            continue  # an augment is turned on or off for the ability (combat/loadout.py); "none" is the panel's Clear
        if ((row.get("parameters") or {}).get("typed") or {}).get("augments"):
            continue  # a compiled combination of augments: the ability's own button casts the chosen one
        typed = (row.get("parameters") or {}).get("typed") or {}
        numbers = typed.get("numbers") or {}
        effects = typed.get("effects") or []
        kinds = {effect.get("type") for effect in effects}
        attack = next((effect for effect in effects if effect.get("type") == "attack"), None)
        save = next((effect for effect in effects if effect.get("type") == "save"), None)
        detail = {
            "to_hit": _signed(int(numbers.get("attack_bonus") or 0)) if attack else None,
            "attacks": int(attack.get("count") or 1) if attack else None,
            "save": saving_throw_text(save, numbers),
            "damage": damage_text(typed, cl) or None,
            "range": f"{row['range_ft']} ft" if row.get("range_ft") else ("Self" if row.get("target_kind") == "SELF" else "Touch"),
            "area": _area_text(typed, cl),
            "cost": _cost_text(row.get("costs")) or None,
            "gm_riders": len(typed.get("riders") or []),
        }
        group = "attacks" if attack and str(row["source_definition_id"]).split(".")[2:3] in (["weapon"], ["natural"]) else _economy_group(row.get("economy"))
        if (row.get("parameters") or {}).get("basic"):
            group = "basic"  # Hide, Search
        description = BASIC_DESCRIPTIONS.get(row["display_name"]) if group == "basic" else None
        description = description or engine_button_description(row) or _button_description(typed, detail, group)
        if is_setting_action(row):
            # A plug-in's standing choice ("Flowing Response: Empty Step"): free, kept until changed, used when the feature
            # fires -- listed with the feature's own kind, not as an action (owner 2026-09-30: "i can select them as an
            # action which makes no sense").
            owner = _toggle_owner(row["display_name"], bundle)
            economy = str((_authority_index().get(owner or "") or {}).get("economy") or "").upper()
            if "REACTION" in economy:
                group = "reactions"
            elif "BONUS" in economy:
                group = "bonus"
            description = setting_button_description(row, bundle, description)
            kinds = kinds | {"choice"}
        elif not description:
            # Nothing of its own: the engine's built-in action, or a plug-in's "Feature: option" toggle.
            description = untyped_button_text(row, bundle)
        if typed.get("option_label"):
            # Hover text leads with the chosen option and its own printed words (owner 2026-09-26): the shared
            # rules text alone would not say which of the ability's printed choices this button is.
            own = dict.fromkeys(" ".join(str(effect.get("evidence") or "").split()) for effect in _all_effects(effects)
                                if effect.get("origin") == "model_options" and effect.get("evidence"))
            head = f"Option: {typed['option_label']}" + (f" ({'; '.join(own)})" if own else "")
            description = f"{head}\n\n{description}" if description else head
        buttons.append({
            "id": f"act:{row['source_definition_id']}", "label": row["display_name"], "group": group, "kind": "combat",
            "economy": row.get("economy"), "combat": {"source_definition_id": row["source_definition_id"], "target_kind": row.get("target_kind")},
            "roll": ({"expression": f"1d20{detail['to_hit']}", "kind": "attack"} if attack else None),
            "detail": detail, "tags": sorted(kind for kind in kinds if kind), "source": "auto",
            "description": description,
            **({"parent": row["parameters"]["menu_parent"]} if (row.get("parameters") or {}).get("menu_parent") else {}),
            **_variant_fields(typed),
        })
    # Augments first (alphabetical), then the talent choices: plain, single talents, pairs.
    shapes.sort(key=lambda row: (0, str(row["modifier"]["name"])) if row.get("augment") or row.get("attack_modifier") else (1, len(row["shape"]["talents"]), str(row["modifier"]["name"])))
    for shape in shapes:  # each area talent sits under the ability it shapes, after its augmented versions
        base = shape["variant_of"]
        at = max((index for index, button in enumerate(buttons) if base in (button["id"], button.get("variant_of"))), default=len(buttons) - 1)
        shape["group"] = next((button["group"] for button in buttons if button["id"] == base), "actions")
        buttons.insert(at + 1, shape)
    for system_id, label, economy in (("system:combat.dash", "Dash", "ACTION"), ("system:combat.dodge", "Dodge", "ACTION"),
                                     ("system:combat.disengage", "Disengage", "ACTION"),
                                     ("system:combat.hold_position", "Hold Position", "NONE")):
        buttons.append({"id": f"act:{system_id}", "label": label,
                        "group": "basic" if economy == "ACTION" else _economy_group(economy), "kind": "combat", "economy": economy,
                        "combat": {"source_definition_id": system_id}, "roll": None, "detail": {}, "tags": [], "source": "auto",
                        "description": BASIC_DESCRIPTIONS[label]})
    buttons.append({"id": "turn:end", "label": "End Turn", "group": "basic", "kind": "combat", "economy": "FREE",
                    "combat": {"end_turn": True}, "roll": None, "detail": {}, "tags": [], "source": "auto",
                    "description": BASIC_DESCRIPTIONS["End Turn"]})
    for row in summary.get("abilities") or []:
        buttons.append({"id": f"check:{row['ability']}", "label": f"{row['name']} check", "group": "checks", "kind": "roll", "economy": None,
                        "combat": None, "roll": {"expression": f"1d20{_signed(row['modifier'])}", "kind": "check"}, "detail": {}, "tags": [], "source": "auto"})
    for row in summary.get("saves") or []:
        buttons.append({"id": f"save:{row['ability']}", "label": f"{ABILITY_NAMES[row['ability']]} save", "group": "saves", "kind": "roll", "economy": None,
                        "combat": None, "roll": {"expression": f"1d20{_signed(row['bonus'])}", "kind": "save"}, "detail": {}, "tags": [], "source": "auto"})
    for row in summary.get("skills") or []:
        buttons.append({"id": f"skill:{_slug(row['skill'])}", "label": row["skill"], "group": "skills", "kind": "roll", "economy": None,
                        "combat": None, "roll": {"expression": f"1d20{_signed(row['bonus'])}", "kind": "check"}, "detail": {"proficiency": row["proficiency"]},
                        "tags": [], "source": "auto"})
    buttons.append({"id": "roll:initiative", "label": "Initiative", "group": "checks", "kind": "roll", "economy": None, "combat": None,
                    "roll": {"expression": f"1d20{_signed(int(summary.get('initiative') or 0))}", "kind": "initiative"}, "detail": {}, "tags": [], "source": "auto",
                    "description": BASIC_DESCRIPTIONS["Initiative"]})
    return buttons


def normalize_custom_buttons(document: dict[str, Any], known_ids: set[str]) -> dict[str, Any]:
    """Validate an owner's custom buttons and layout (steps may use auto button ids or dice rolls)."""
    if not isinstance(document, dict):
        raise TabletopError("BUTTONS_INVALID", "Buttons must be a JSON object.")
    buttons = []
    for index, row in enumerate(document.get("buttons") or []):
        if not isinstance(row, dict):
            raise TabletopError("BUTTONS_INVALID", "Each custom button must be an object.")
        label = str(row.get("label") or "").strip()[:40]
        if not label:
            raise TabletopError("BUTTONS_INVALID", "Every custom button needs a label.")
        steps = []
        for step in row.get("steps") or []:
            if isinstance(step, dict) and step.get("button"):
                if str(step["button"]) not in known_ids:
                    raise TabletopError("BUTTONS_INVALID", f"'{label}' uses an unknown button: {step['button']}.")
                steps.append({"button": str(step["button"]), "same_target": bool(step.get("same_target", True))})
            elif isinstance(step, dict) and step.get("roll"):
                from_expression = str(step["roll"]).strip()[:60]
                if not re.match(r"^[0-9d+\-\s]+(adv|dis)?$", from_expression, re.I):
                    raise TabletopError("BUTTONS_INVALID", f"'{label}' has a roll that is not dice notation: {from_expression}.")
                steps.append({"roll": from_expression, "label": str(step.get("label") or label)[:40]})
        if not steps or len(steps) > 8:
            raise TabletopError("BUTTONS_INVALID", f"'{label}' needs 1–8 steps.")
        buttons.append({"id": f"custom:{_slug(row.get('id') or label)}-{index + 1}" if not str(row.get("id") or "").startswith("custom:") else str(row["id"])[:60],
                        "label": label, "color": str(row.get("color") or "")[:20] or None, "group": "custom", "kind": "combo",
                        "steps": steps, "source": "custom"})
    layout = document.get("layout") or {}
    return {"schema": BUTTONS_SCHEMA, "buttons": buttons[:60],
            "layout": {"hidden": [str(value) for value in layout.get("hidden") or []][:400],
                       "pinned": [str(value) for value in layout.get("pinned") or []][:40]}}


def normalize_powering(document: dict[str, Any], choosable: dict[str, list[str]]) -> dict[str, str]:
    """Validate an owner's Powering Path choices (owner 2026-09-25, Q19): action id -> pool name,
    restricted to the character's actual choosable abilities and their available pools."""
    if not isinstance(document, dict) or not isinstance(document.get("choices"), dict):
        raise TabletopError("POWERING_INVALID", "Powering choices must be a JSON object: {\"choices\": {action id: pool}}.")
    result: dict[str, str] = {}
    for action_id, pool in document["choices"].items():
        action_id = str(action_id)
        pools = choosable.get(action_id)
        if pools is None:
            raise TabletopError("POWERING_UNKNOWN_ACTION", f"'{action_id}' is not a choosable ability.")
        pool = str(pool).strip().lower()
        if pool not in pools:
            raise TabletopError("POWERING_INVALID_POOL", f"'{action_id}' cannot be powered by '{pool}'.")
        result[action_id] = pool
    return result


class ButtonStore:
    """Per-character custom buttons, Powering Path choices and the held reaction under
    ``<data>/tabletop_buttons/<project_id>.json`` (owner 2026-09-25: "powering" added alongside
    the buttons; 2026-09-26: "reactions"; each save preserves the parts it did not touch)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @contextmanager
    def transaction(self, project_id: str):
        """Serialize rule-checked acquisition against its pre-learning sheet.

        The per-character lock spans validation and the atomic write. Default
        readers are unchanged; producers of correlated receipts use this seam.
        """
        path = self._path(project_id).with_suffix(".transaction.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _path(self, project_id: str) -> Path:
        if not re.match(r"^[0-9a-f-]{8,64}$", project_id or ""):
            raise TabletopError("CHARACTER_UNKNOWN", "Unknown character.", 404)
        return self.root / f"{project_id}.json"

    def get(self, project_id: str) -> dict[str, Any]:
        path = self._path(project_id)
        if not path.is_file():
            return {"schema": BUTTONS_SCHEMA, "buttons": [], "layout": {"hidden": [], "pinned": []}, "powering": {}, "reactions": {}}
        document = json.loads(path.read_text(encoding="utf-8"))
        document.setdefault("powering", {})
        document.setdefault("reactions", {})
        document.setdefault("granted_spheres", [])
        document.setdefault("summons", {})
        return document

    def save(self, project_id: str, document: dict[str, Any], known_ids: set[str]) -> dict[str, Any]:
        normalized = normalize_custom_buttons(document, known_ids)
        current = self.get(project_id)
        normalized["powering"] = current.get("powering") or {}
        normalized["reactions"] = current.get("reactions") or {}
        normalized["granted_spheres"] = current.get("granted_spheres") or []
        normalized["summons"] = current.get("summons") or {}
        if current.get("display_name"):
            normalized["display_name"] = current["display_name"]
        for key in ("advancement", "token_look", "token_circle", "left_behind", "attuned"):
            if current.get(key):
                normalized[key] = current[key]
        _atomic_write(self._path(project_id), (json.dumps(normalized, indent=1) + "\n").encode("utf-8"))
        return normalized

    def save_attunement(self, project_id: str, keys: list[str] | None) -> None:
        """The treasures the character is attuned to (owner 2026-09-28); None returns to the creation plan."""
        current = self.get(project_id)
        if keys is None:
            current.pop("attuned", None)
        else:
            current["attuned"] = list(keys)
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))

    def save_left_behind(self, project_id: str, keys: list[str]) -> None:
        """Items the character leaves behind for its fights (owner 2026-09-27)."""
        current = self.get(project_id)
        if keys:
            current["left_behind"] = list(keys)
        else:
            current.pop("left_behind", None)
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))

    def save_token_look(self, project_id: str, look: str, circle: dict[str, float] | None = None) -> None:
        """The owner's words for the character's Anima picture, and where the token's circle sits on it (owner 2026-09-27)."""
        current = self.get(project_id)
        if look:
            current["token_look"] = look
        else:
            current.pop("token_look", None)
        if circle is not None:
            current["token_circle"] = circle
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))

    def save_advancement(self, project_id: str, advancement: dict[str, Any]) -> dict[str, Any]:
        """What the table has added to a finished character (combat/table_advance.py): Spheres, talents and Forged
        Techniques, each marked when the GM granted it past the rules (owner 2026-09-27)."""
        from .table_advance import normalized as table_normalized

        current = self.get(project_id)
        current["advancement"] = table_normalized(advancement)
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))
        return current

    def save_granted_spheres(self, project_id: str, spheres: list[str], known: set[str]) -> dict[str, Any]:
        """Spheres the owner grants a finished character for combat (owner 2026-09-26: the Weapons Sphere for the
        characters whose treasure weapon they could not use); the printed sheet is unchanged."""
        unknown = [sphere for sphere in spheres if sphere not in known]
        if unknown:
            raise TabletopError("TABLETOP_SPHERE_UNKNOWN", "That is not a Sphere in the rules.", 400)
        current = self.get(project_id)
        current["granted_spheres"] = sorted(dict.fromkeys(spheres))
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))
        return current

    def save_display_name(self, project_id: str, name: str | None) -> dict[str, Any]:
        """The name a finished character goes by at the table and in combat (owner 2026-09-27: a rename saved while it
        was being finalized never reached the character); empty goes back to the sheet's own name."""
        cleaned = " ".join(str(name or "").split())
        if len(cleaned) > 80:
            raise TabletopError("TABLETOP_NAME_INVALID", "A name can be at most 80 characters.", 400)
        current = self.get(project_id)
        if cleaned:
            current["display_name"] = cleaned
        else:
            current.pop("display_name", None)
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))
        return current

    def save_summons(self, project_id: str, document: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        """How many of each creature the character brings and which beasts (owner 2026-09-27, combat/summons.py)."""
        most = {row["group"]: int(row["max"]) for row in options.get("groups") or []}
        counts = {str(key): int(value) for key, value in (document.get("counts") or {}).items()}
        if any(key not in most or not 0 <= value <= most[key] for key, value in counts.items()):
            raise TabletopError("TABLETOP_SUMMONS_INVALID", "That is more than the character can bring.", 400)
        known = {row["key"] for row in options.get("beasts") or []}
        beasts = [str(key) for key in document.get("beasts") or []]
        if beasts and not options.get("tamer") or any(key not in known for key in beasts) or len(beasts) > int(options.get("beast_limit") or 1):
            raise TabletopError("TABLETOP_SUMMONS_INVALID", "Those beasts can't be taken.", 400)
        current = self.get(project_id)
        kept = {"beasts": beasts} if options.get("tamer") and document.get("beasts") is not None else (
            {"beasts": (current.get("summons") or {})["beasts"]} if "beasts" in (current.get("summons") or {}) else {})
        if "mount" in options and document.get("mount") is not None:  # a Rider's steed ("" = none; combat/ext/mounts.py)
            steed = str(document["mount"])
            if steed and steed not in {row["key"] for row in options.get("mounts") or []}:
                raise TabletopError("TABLETOP_SUMMONS_INVALID", "That mount can't be taken.", 400)
            kept["mount"] = steed
        elif "mount" in (current.get("summons") or {}):
            kept["mount"] = current["summons"]["mount"]
        current["summons"] = {"counts": counts, **kept}
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))
        return current

    def save_powering(self, project_id: str, document: dict[str, Any], choosable: dict[str, list[str]]) -> dict[str, Any]:
        current = self.get(project_id)
        current["powering"] = normalize_powering(document, choosable)
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))
        return current

    def save_reactions(self, project_id: str, document: dict[str, Any], holdable: set[str],
                       menus: dict[str, int] | None = None) -> dict[str, Any]:
        """Which reactions the character uses, most important first, and which never (owner 2026-09-26: "multiple
        you can hold up and order of importance ... some dont apply"). {"mode": "auto"} clears the order; the first
        version's {"hold": id} is still read. ``options`` picks a "Choose one" reaction's option ({id: index},
        step 14; ``menus`` is each such reaction's option count) and is kept in either mode."""
        if document.get("hold") and not document.get("order"):
            document = {"mode": "custom", "order": [document["hold"]], "off": sorted(holdable - {document["hold"]})}
        plan: dict[str, Any] = {}
        if document.get("mode") == "ask":
            plan = {"ask": True}  # Ask me (step 16): the player answers each reaction while playing this character
        elif document.get("mode") == "custom":
            order = [str(key) for key in dict.fromkeys(document.get("order") or [])]
            off = [str(key) for key in dict.fromkeys(document.get("off") or []) if key not in order]
            unknown = [key for key in order + off if key not in holdable]
            if unknown:
                raise TabletopError("TABLETOP_REACTION_UNKNOWN", "That is not a reaction this character has.", 400)
            plan = {"order": order, "off": off}
        options: dict[str, int] = {}
        for key, index in (document.get("options") or {}).items():
            if key not in (menus or {}) or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < (menus or {})[key]:
                raise TabletopError("TABLETOP_REACTION_OPTION_UNKNOWN", "That is not an option this reaction has.", 400)
            options[str(key)] = index
        if options:
            plan["options"] = options
        current = self.get(project_id)
        current["reactions"] = plan
        _atomic_write(self._path(project_id), (json.dumps(current, indent=1) + "\n").encode("utf-8"))
        return current


# ---------------------------------------------------------------- ability library (owner 2026-09-25)
# "The character sheets should have all the spheres on it, so the player can search through
# their stuff and think about what they want to do, reading about what their abilities do."
_AUTHORITY_INDEX: dict[str, Any] = {}


def _authority_index() -> dict[str, dict[str, Any]]:
    frame = _TEXT_SNAPSHOT.get()
    if frame is not None and "authority" in frame:
        return frame["authority"][1]
    from .factory_compiler import TYPED_AUTHORITY
    with _TEXT_INDEX_LOCK:
        rows = _load_authority_index(TYPED_AUTHORITY)
        if frame is not None:
            frame["authority"] = (_AUTHORITY_INDEX["mtime"], rows)
        return rows


def _load_authority_index(path: Path) -> dict[str, dict[str, Any]]:
    """record id -> {sphere_id, economy, coverage} from the typed-mechanics authority (cached by mtime)."""
    rules_path = path.parent / "typed_mechanics" / "rules_text.json"
    mtime = (_text_file_identity(path), _text_file_identity(rules_path) if rules_path.is_file() else None)
    if _AUTHORITY_INDEX.get("mtime") != mtime:
        mechanics = json.loads(path.read_text(encoding="utf-8"))["mechanics"]
        # The full printed rules text (tools/build_typed_mechanics_authority.py), not the parser's untyped
        # remainder -- Wind Lash's hover said only "When Wind Lash hits, choose one basic Vector:" (owner
        # 2026-09-26 overnight check of the 2026-09-25 hover request).
        rules_text = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.is_file() else {}
        _AUTHORITY_INDEX.update(mtime=mtime, rows={
            key: {"name": row.get("name"), "kind": row.get("kind"), "sphere_id": row.get("sphere_id"), "economy": (row.get("activation") or {}).get("economy"), "coverage": row.get("coverage"),
                  "description": rules_text.get(key) or ("\n".join(str(line) for line in row.get("description") or [])
                                                        if isinstance(row.get("description"), list) else str(row.get("description") or ""))}
            for key, row in mechanics.items()})
    return _AUTHORITY_INDEX["rows"]


_SPHERE_TEXT_INDEX: dict[str, Any] = {}


def _sphere_text_index() -> dict[str, dict[str, Any]]:
    """Sphere id -> {name, text} from the compiled canonical catalog, for a Sphere the table added.

    The build's ``selected_record_sections`` carries a Sphere's printed text with the sealed sheet.
    A Sphere learned at the table has no such row yet, so the same printed text the catalog projects
    is read here (display only; no character state).
    """
    frame = _TEXT_SNAPSHOT.get()
    if frame is not None and "spheres" in frame:
        return frame["spheres"][1]
    from .factory_compiler import APP
    path = APP / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json"
    with _TEXT_INDEX_LOCK:
        mtime = _text_file_identity(path) if path.is_file() else None
        if _SPHERE_TEXT_INDEX.get("mtime") != mtime:
            rows: dict[str, dict[str, Any]] = {}
            if mtime is not None:
                document = json.loads(path.read_text(encoding="utf-8"))
                rows = {str(row["canonical_sphere_id"]): {"name": row.get("display_name"), "text": row.get("full_exact_source_text") or ""}
                        for row in document.get("spheres") or [] if row.get("canonical_sphere_id")}
            _SPHERE_TEXT_INDEX.update(mtime=mtime, rows=rows)
        if frame is not None:
            frame["spheres"] = (_SPHERE_TEXT_INDEX["mtime"], _SPHERE_TEXT_INDEX["rows"])
        return _SPHERE_TEXT_INDEX["rows"]


ECONOMY_LABELS = {"action": "Action", "bonus_action": "Bonus action", "reaction": "Reaction", "passive": "Passive", "free": "Free"}


INSIGHT_BOUNDARY_STATUS = {"automated": "auto", "partial": "partial", "manual": "gm"}


def sheet_library(sheet: dict[str, Any], buttons: list[dict[str, Any]], automated: set[str],
                   insight_boundaries: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Everything the character has, with its full rules text, grouped for reading and searching.

    Each entry says how the table handles it: ``action`` (a button runs it through the engine;
    ``partial`` when the GM adjudicates extra lines), ``auto`` (a passive or reaction the engine
    applies by itself), ``gm`` (the GM rules on it) or ``info`` (not a combat rule).

    ``insight_boundaries`` is the compiled per-Insight record (factory_compiler
    ``diagnostics.insights``): what the fight applies by itself, what the Game Master
    still rules, and one plain sentence saying which of those it is. An Insight
    reaches it for every id the character owns, so an automated benefit, a partly
    implemented one and one the fight skips no longer share one status. The
    sentence is added as ``automation`` only for those entries.
    """
    # General display boundary for every library record; the sheet and authority
    # retain verbatim evidence, while the table reads the builder's projection.
    from .player_text import clean
    from character_sheet.build_provenance import present_build_provenance
    sheet = present_build_provenance(sheet)
    boundaries = insight_boundaries or {}
    sections = sheet.get("selected_record_sections") or {}
    index = _authority_index()
    by_record: dict[str, dict[str, Any]] = {}
    for button in buttons:
        source = str((button.get("combat") or {}).get("source_definition_id") or "")
        if source.startswith("action:typed."):
            parts = source.split(".", 2)
            if len(parts) == 3:
                # One option of a "Choose one" ability (owner 2026-09-26) compiles to its own action id,
                # "<mechanic id>#optN"; every option still belongs to the one printed record.
                by_record.setdefault(re.sub(r"#opt\d+$", "", parts[2]), button)

    def entry(row: dict[str, Any], kind: str, combat: bool = True) -> dict[str, Any]:
        record_id = str(row.get("record_id") or "")
        info = index.get(record_id) or {}
        button = by_record.get(record_id)
        boundary = boundaries.get(record_id) or {}
        automation = str(boundary.get("explanation") or "")
        if automation and not boundary.get("name") and row.get("display_name"):
            # An id the rules source never named: the sheet's own display name
            # reads better than the placeholder the compiler could only guess.
            automation = automation.replace("This Insight", str(row["display_name"]), 1)
        if boundary.get("status") in INSIGHT_BOUNDARY_STATUS:
            # The compiled boundary is the truth about this Insight: a manual
            # Insight is a fight rule the table skips, not reference reading.
            status = INSIGHT_BOUNDARY_STATUS[boundary["status"]]
            automation = automation or f"{row.get('display_name') or record_id} is not run by the fight table."
        elif not combat:
            status = "info"
        elif button:
            status = "partial" if (button.get("detail") or {}).get("gm_riders") else "action"
        elif record_id in automated:
            status = "auto"
        else:
            status = "gm"
        one_line = str(row.get("one_line_description") or "").strip()
        name = clean(row.get("display_name") or record_id)
        return {
            "id": record_id, "name": name, "kind": kind,
            "economy": ECONOMY_LABELS.get(str(info.get("economy") or ""), None) if combat else None,
            "cl": row.get("acquisition_cl"),
            "summary": "" if one_line.lstrip("#").strip() == name or one_line.startswith("#") else clean(one_line),
            "text": clean(row.get("full_description")),
            "status": status, "button_id": button["id"] if button else None,
            "sphere_id": info.get("sphere_id"),
            # Present only where the table knows exactly how far it got (see docstring).
            **({"automation": clean(automation)} if automation else {}),
        }

    spheres = [{"id": row.get("record_id"), "name": clean(row.get("display_name")), "text": clean(row.get("full_description")), "entries": []}
               for row in sections.get("spheres") or []]
    # A finished character can learn a Sphere at the table (Grow's add-talents section), which the applied
    # sheet records in ``spheres_and_talents`` but the sealed build's ``selected_record_sections`` cannot
    # carry. List every Sphere the character now has, not only the build's, so the Abilities tab matches
    # the buttons and Features tab (owner 2026-10-21).
    from . import table_advance

    known = table_advance.known(sheet) if sections else {"spheres": set(), "talents": set()}
    present_spheres = {sphere["id"] for sphere in spheres}
    for sphere_id in sorted(known["spheres"]):
        if sphere_id in present_spheres:
            continue
        info = _sphere_text_index().get(sphere_id) or {}
        spheres.append({"id": sphere_id, "name": clean(info.get("name") or sphere_id),
                        "text": clean(info.get("text") or ""), "entries": []})
    by_sphere = {sphere["id"]: sphere for sphere in spheres}
    loose: list[dict[str, Any]] = []
    # Which CL the table added each talent at (table_advance.apply); build rows carry their own.
    added_cls = (sheet.get("table_advancement") or {}).get("talent_cls") or {}
    section_rows = [row for key in ("sphere_automatic_components", "talents", "background_talent")
                    for row in sections.get(key) or []]
    present_records = {str(row.get("record_id") or "") for row in section_rows}
    # present_build_provenance already moved build instructions and equipment references out of the
    # owned-components section; do not list them again just because the applied sheet still names them.
    present_records |= {str(row.get("record_id") or "") for row in (sheet.get("build_provenance") or {}).get("grant_instructions") or []}
    present_records |= {str(row.get("record_id") or "") for row in sections.get("equipment_reference") or []}
    background_id = (sheet.get("spheres_and_talents") or {}).get("background_talent_record_id")
    # Table-added and manual-memorized records have no build row: take the printed name and rules text
    # from the same typed authority the build rows resolve against, so the badge logic stays identical.
    extra_rows: list[tuple[dict[str, Any], str]] = []
    for record_id in sorted(known["talents"]):
        if record_id in present_records:
            continue
        info = index.get(record_id)
        if not info:
            # A legacy manual binding id the typed authority never named (e.g. the old
            # "tianxia.background_talent.*" form of a talent the sheet already lists under
            # its canonical id). Listing it would repeat one printed talent or show a bare id.
            continue
        kind = "Background talent" if record_id == background_id else (
            "Base ability" if info.get("kind") == "base_ability" else "Talent")
        extra_rows.append(({"record_id": record_id, "display_name": info.get("name") or record_id,
                            "full_description": info.get("description") or "", "one_line_description": "",
                            "acquisition_cl": added_cls.get(record_id), "parent_sphere_id": info.get("sphere_id")}, kind))
    for key, kind in (("sphere_automatic_components", "Base ability"), ("talents", "Talent"), ("background_talent", "Background talent")):
        for row in sections.get(key) or []:
            item = entry(row, kind)
            sphere_id = row.get("parent_sphere_id") or item["sphere_id"]
            (by_sphere[sphere_id]["entries"] if sphere_id in by_sphere else loose).append(item)
    for row, kind in extra_rows:
        item = entry(row, kind)
        sphere_id = row.get("parent_sphere_id") or item["sphere_id"]
        (by_sphere[sphere_id]["entries"] if sphere_id in by_sphere else loose).append(item)
    for sphere in spheres:
        sphere["entries"].sort(key=lambda item: (item["kind"] != "Base ability", item["name"]))
    if loose:
        spheres.append({"id": None, "name": "Other talents", "text": "", "entries": sorted(loose, key=lambda item: item["name"])})

    other = sections.get("other") or []

    def of(sub: str) -> list[dict[str, Any]]:
        return [row for row in other if str(row.get("subsection") or "") == sub]

    path = [entry(row, row.get("subsection") or "Path", combat=False) for row in sections.get("path_subpath") or []]
    path += sorted((entry(row, "Path feature") for row in (sections.get("path_features") or []) + (sections.get("advancement_features") or [])),
                   key=lambda item: (item["cl"] or 0, item["name"]))
    # The sheet's own "Foundation" row (above) only carries the short description; list its
    # printed features too, cumulative by stage (owner 2026-09-25, non_sphere_authority/foundation_features.py).
    from non_sphere_authority.foundation_features import features_for_stage

    foundation = sheet.get("foundation") or {}
    foundation_features = [
        entry({"record_id": row["id"], "display_name": row["name"], "one_line_description": row["fields"].get("Effect") or "",
               "full_description": "\n".join(f"{key}: {value}" for key, value in row["fields"].items()), "acquisition_cl": None},
              "Foundation feature")
        for row in features_for_stage(foundation.get("foundation_id"), foundation.get("stage"))
    ]
    forged_rows = list(of("Forged Technique Component"))
    forged_ids = {str(row.get("record_id") or "") for row in forged_rows}
    # A technique built at the table is appended to ``forged_techniques`` (table_advance.apply), not to
    # the sealed build's section rows; list it with the same record text the build rows carry.
    crafted = sheet.get("forged_techniques") if sections else None
    if isinstance(crafted, list):
        for technique in crafted:
            if not isinstance(technique, dict):
                continue
            record_id = str(technique.get("technique_id") or technique.get("record_id") or "")
            if not record_id or record_id in forged_ids:
                continue
            forged_rows.append({"record_id": record_id, "display_name": technique.get("name") or "Forged Technique",
                                "one_line_description": "", "full_description": technique.get("record_text") or "",
                                "acquisition_cl": technique.get("cl_created"), "subsection": "Forged Technique Component"})
    groups = [
        {"key": "spheres", "title": "Spheres", "spheres": spheres},
        {"key": "path", "title": "Path & Subpath", "entries": path},
        {"key": "techniques", "title": "Forged Techniques", "entries": [entry(row, "Forged Technique") for row in forged_rows]},
        {"key": "arts", "title": "Immortal Arts", "entries": [entry(row, "Immortal Art") for row in of("Immortal Art")]},
        {"key": "cultivation", "title": "Method & Foundation",
         "entries": [entry(row, row.get("subsection") or "", combat=False) for row in of("Cultivation Method") + of("Foundation")] + foundation_features},
        {"key": "insights", "title": "Insights", "entries": [entry(row, "Insight", combat=False) for row in sections.get("insights") or []]},
        {"key": "manuals", "title": "Manuals & Recorded Arts", "entries": [entry(row, "Manual", combat=False) for row in sections.get("manuals") or []]},
        {"key": "origin", "title": "Background & Origin",
         "entries": [entry(row, row.get("subsection") or "Origin", combat=False) for row in sections.get("background_origin") or []] + [entry(row, "Equipment", combat=False) for row in of("Item")]},
    ]
    references = [entry(row, "Equipment reference", combat=False)
                  for row in sections.get("equipment_reference") or []]
    if references:
        groups.append({"key": "equipment_reference", "title": "Equipment rules", "entries": references})
    # Forged Technique buttons use their own ids; match them to the library by name.
    forged = {button["label"]: button for button in buttons if ".forged." in str((button.get("combat") or {}).get("source_definition_id") or "")}
    for item in groups[2]["entries"]:
        button = forged.get(item["name"])
        if button:
            item["button_id"] = button["id"]
            item["status"] = "partial" if (button.get("detail") or {}).get("gm_riders") else "action"
    # Immortal Art buttons (action/bonus action economy) use their own ids too; match by name
    # (owner 2026-09-26).  A reaction-economy art already shows "auto" above: its feature_id
    # (combat/factory_compiler.py's ``_compile_immortal_arts``) is the art's own record id.
    immortal = {button["label"]: button for button in buttons if ".immortal." in str((button.get("combat") or {}).get("source_definition_id") or "")}
    for item in groups[3]["entries"]:
        button = immortal.get(item["name"])
        if button:
            item["button_id"] = button["id"]
            item["status"] = "partial" if (button.get("detail") or {}).get("gm_riders") else "action"
    return {"groups": [group for group in groups if group.get("entries") or group.get("spheres")],
            "legend": {"action": "A button runs it through the rules engine", "partial": "Button runs the roll, damage and movement; some extra lines aren't automated yet",
                       "auto": "Always on / fires by itself; the engine applies it", "gm": "Not automated yet; the fight skips it",
                       "info": "Not a combat rule"}}
