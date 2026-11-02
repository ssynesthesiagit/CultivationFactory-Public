"""Authored roof heights, climbing conditions and openings for map geometry."""
from typing import Any


def _height(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Roof height must be a whole number of feet, zero or more.")
    return value


def _climb_check(value: Any) -> str:
    if not isinstance(value, str) or value not in {"none", "slippery", "few_handholds"}:
        raise ValueError("Roof climbing condition must be ordinary, slippery, or have few handholds.")
    return value


def normalize_roofs(value: Any, width: int, height: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    settings = {"enabled": value.get("enabled") is not False,
                "style": "red" if value.get("style") == "red" else "grey"}
    if "height_ft" in value:
        settings["height_ft"] = _height(value["height_ft"])
    if "climb_check" in value:
        settings["climb_check"] = _climb_check(value["climb_check"])
    if "catch_dc" in value:
        settings["catch_dc"] = _height(value["catch_dc"])
    regions = []
    used = set()
    rows = value.get("regions")
    for row in (rows if isinstance(rows, list) else [])[:width * height]:
        if not isinstance(row, dict):
            continue
        x, y = row.get("x"), row.get("y")
        if type(x) is not int or type(y) is not int or not (0 <= x < width and 0 <= y < height) or (x, y) in used:
            continue
        used.add((x, y))
        # Missing fields inherit at render time, including after global edits.
        override = {"x": x, "y": y}
        if "enabled" in row:
            override["enabled"] = row["enabled"] is not False
        if "style" in row:
            override["style"] = "red" if row["style"] == "red" else "grey"
        if "height_ft" in row:
            override["height_ft"] = _height(row["height_ft"])
        if "climb_check" in row:
            override["climb_check"] = _climb_check(row["climb_check"])
        if "catch_dc" in row:
            override["catch_dc"] = _height(row["catch_dc"])
        regions.append(override)
    if regions:
        settings["regions"] = regions
    openings = []
    used = set()
    rows = value.get("openings")
    for row in (rows if isinstance(rows, list) else [])[:width * height]:
        if (not isinstance(row, dict) or not isinstance(row.get("kind"), str)
                or row.get("kind") not in {"trapdoor", "skylight"}):
            continue
        x, y = row.get("x"), row.get("y")
        if (type(x) is not int or type(y) is not int or not (0 <= x < width and 0 <= y < height)
                or (x, y) in used):
            continue
        used.add((x, y))
        openings.append({"x": x, "y": y, "kind": row["kind"], "open": row.get("open") is True})
    if openings:
        settings["openings"] = openings
    return settings
