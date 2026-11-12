"""Table-only wording for forged areas; no combat rules or saved state changes.

status_text projects the geometry and source; zones.js adds the saved triggers'
recipient, save and damage readings before the original technique background.
"""
from typing import Any


def forged_area_hover(engine: Any, zone: dict[str, Any]) -> dict[str, Any]:
    action = engine.action_catalog.get(zone.get("source_definition_id"))
    typed = ((action.parameters or {}).get("typed") or {}) if action else {}
    if not typed.get("forged_from") or typed.get("base_form") not in ("zone", "aura"):
        return {}
    profile = zone.get("trigger_profile") or {}
    shape, size = profile.get("shape"), profile.get("size_ft")
    # Read the placed zone, including augments, rather than the primary's range
    # or the Base Form's default. Missing geometry must never be guessed.
    shapes = {"sphere": "radius sphere", "cylinder": "radius cylinder",
              "cube": "cube", "square": "square", "cone": "cone", "line": "line"}
    area = f"{size}-foot-{shapes[shape]}" if shape in shapes and size else "area (size not shown)"
    if shape == "line" and profile.get("width_ft"):
        area += f", {profile['width_ft']} feet wide"
    if shape == "cylinder" and profile.get("height_ft"):
        area += f", {profile['height_ft']} feet high"
    form = "Aura" if typed["base_form"] == "aura" else "Zone"
    summary = f"{form}: {area}."
    if profile.get("follows_owner"):
        summary += " Centered on its creator; moves with them."
    summary += f" Lasts {zone['duration']}." if zone.get("duration") else " Duration not shown."
    from .status_text import printed_rules, plain, area_wording

    printed = printed_rules().get(typed["forged_from"], "")
    name = plain(printed.splitlines()[0]).split(" - ")[0] if printed else "primary technique"
    # Resolve the saved paying pool before plain() consumes CP into generic
    # wording. This appended channel is displayed after the normal presenter,
    # so it must use the same public resource helper itself.
    from .ext.resource_readings import paying_pool, expand_cp

    printed = expand_cp(printed, paying_pool(engine, None, zone, typed["forged_from"]))
    original = "\n".join(area_wording(plain(line), (profile.get("numbers") or {}).get("cl"))
                         for line in printed.splitlines())
    # The printed payment belongs to the primary, not the forged area.
    original = original.replace("\nCost:", "\nOriginal technique cost:")
    background = (f"Based on: {name}. Original technique rules (its range and shape do not describe this {form.lower()}):\n"
                  + original) if printed else ""
    # Keep the structured hover channel consistent with the flat body the board
    # uses. The original primary card must not retain active Range fields here.
    return {"detail": summary, "rule_text": summary, "source_detail": background,
            "hover": {"title": zone.get("display_name") or form, "summary": summary,
                      "fields": [], "body": [], "footer": ""}}
