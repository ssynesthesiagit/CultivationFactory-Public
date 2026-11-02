"""Map geometry defaults shared with the editor; explicit authored heights win.

These are scenery dimensions, not ability rules. The shared JSON is also read
by static/tabletop/map-heights.js, so old maps and new editor walls agree.
"""
import json
from pathlib import Path

DEFAULTS = json.loads((Path(__file__).resolve().parents[1] /
                      "static/tabletop/map-heights.json").read_text())


def wall_height_ft(wall):
    if wall.get("height_ft") is not None:
        return wall["height_ft"]
    kind = wall.get("kind")
    if kind == "building":
        return DEFAULTS["storey_ft"] * wall.get("storeys", 1)
    return DEFAULTS["low_ft"].get(kind, DEFAULTS["low_ft"].get(wall.get("look"), DEFAULTS["wall_ft"]))


def roof_height_ft(settings, wall_height):
    return settings.get("height_ft", wall_height + DEFAULTS["roof_rise_ft"])


def walking_height_ft(roof_top_ft):
    """Standing height on a roof: its top rounded to the nearest 5 ft (ties round up).

    Sight uses the exact top. Walking, climbing and the movement menu use this
    value so the 5-ft movement model stays unchanged. Mirrored by
    static/tabletop/map-heights.js (walkingRoofHeightFt).
    """
    return (roof_top_ft + 2) // 5 * 5


def scenery_height_ft(row, family):
    """Authoring policy, mirrored in map-heights.js; geometry reads represented spans.

    Height is relative to the base, never the absolute top. Zero is valid.
    Trees describe trunk-column height, not a new solid canopy footprint.
    Uncatalogued objects/cover have finite, editable fallbacks; paint is ground.
    """
    if "height_ft" in row:
        return row["height_ft"]
    if family == "object":
        return DEFAULTS["object_ft"].get(row.get("kind"), DEFAULTS["object_fallback_ft"])
    if family == "tree":
        height = DEFAULTS["tree_ft"].get(row.get("look"), DEFAULTS["tree_ft"]["broadleaf"])
        return height * (DEFAULTS["great_tree_multiplier"] if row.get("size") == 2 else 1)
    if family == "material":
        return DEFAULTS["bamboo_ft"] if row.get("material") == "terrain:bamboo thicket" else 0
    if family == "terrain":
        return DEFAULTS["terrain_ft"].get(row.get("look"),
            DEFAULTS["cover_fallback_ft"] if row.get("type") == "SIMPLE_COVER" else 0)
    raise ValueError("Unknown scenery family")


def scenery_span(row, family):
    """Validated persisted metadata for map normalization (integer feet only)."""
    height = scenery_height_ft(row, family)
    bottom = row.get("base_altitude_ft", 0)
    if any(type(value) is not int or not 0 <= value <= 9007199254740991 for value in (height, bottom)):
        raise ValueError("Scenery height and base altitude must be whole numbers of feet, zero or more.")
    return {"height_ft": height, **({"base_altitude_ft": bottom} if "base_altitude_ft" in row else {})}
