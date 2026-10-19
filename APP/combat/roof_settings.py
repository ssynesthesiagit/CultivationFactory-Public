"""Optional roof appearance and authored top heights in whole feet."""
from typing import Any


def normalize_roofs(value: Any, width: int, height: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    settings = {"enabled": value.get("enabled") is not False,
                "style": "red" if value.get("style") == "red" else "grey"}
    def validate_height(row, target):
        if "height_ft" in row:
            if type(row["height_ft"]) is not int or row["height_ft"] < 0:
                raise ValueError("Roof height must be a whole number of feet, zero or more.")
            target["height_ft"] = row["height_ft"]
    validate_height(value, settings)
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
        validate_height(row, override)
        regions.append(override)
    if regions:
        settings["regions"] = regions
    return settings
