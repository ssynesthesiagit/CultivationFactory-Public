"""Pinned Body Refining version authority, shared by creation, Grow and combat.

This is the only runtime reader of the generated JSON. Default ownership is
derived from the character's Paths, spheres and upgrade Insights, never CL or a
GM flag. The sheet's global key ability is not changed.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTHORITY = APP / "authority/Tianxia_Body_Refining_Variants_R1.json"
MARKDOWN_SHA256 = "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775"
# Keep the generated-byte pin in code; runtime/public packages need only JSON.
# Rebuild the authority and update this pin together after source changes.
AUTHORITY_SHA256 = "c066a1a88821d00d3425076bc1c5273b8991754c611da4c08d90eb69cc1b42c8"
BODY = "tianxia.path.body_refining"


@lru_cache(maxsize=1)
def access():
    payload = AUTHORITY.read_bytes()
    if hashlib.sha256(payload).hexdigest() != AUTHORITY_SHA256:
        raise ValueError("Body Refining version authority hash does not verify")
    data = json.loads(payload)
    if data["schema"] != "TianxiaBodyRefiningVariants.v1" or data["source"]["markdown_sha256"] != MARKDOWN_SHA256:
        raise ValueError("Body Refining version source does not match the accepted compendium")
    return data


def variant(variant_id):
    return access()["variants"].get(variant_id)


@lru_cache(maxsize=85)
def default_variant(sphere_id):
    return next(({"id": key, **row} for key, row in access()["variants"].items()
                 if row["sphere_id"] == sphere_id), None)


def selected(sphere_id, sheet, *, require_owned=False):
    identity = sheet.get("identity") or {}
    paths = sheet.get("path_and_subpath") or {}
    owned_paths = identity.get("path_ids") or paths.get("path_record_ids") or []
    block = sheet.get("spheres_and_talents") or {}
    if BODY not in owned_paths or require_owned and sphere_id not in (block.get("sphere_record_ids") or []):
        return None
    row = default_variant(sphere_id)
    insights = set(block.get("cultivation_insight_record_ids") or [])
    insights.update(r.get("insight_id") or r.get("record_id")
                    for r in block.get("cultivation_insight_occurrences") or [])
    return row if row and row["access"]["insight_id"] not in insights else None


def owned(sheet):
    return [row for sid in (sheet.get("spheres_and_talents") or {}).get("sphere_record_ids") or []
            if (row := selected(sid, sheet, require_owned=True))]


def label(sphere_id, sheet):
    row = selected(sphere_id, sheet)
    return row["picker_label"] if row else None


def gate_note(sphere_id, sheet):
    row = selected(sphere_id, sheet)
    if not row:
        return None
    iid = row["access"]["insight_id"]
    if iid:
        name = iid.split(".", 1)[1].replace("-", " ").title()
        return f"Default Body Refining version; no Insight or level requirement. Taking {name} switches you to normal {row['sphere_name']}."
    return "Default Body Refining version; no Insight or level requirement."


def payload(sphere_id, sheet):
    row = selected(sphere_id, sheet)
    return {"id": row["id"], "label": row["picker_label"], "gate_note": gate_note(sphere_id, sheet)} if row else None


def key_ability_for(sphere_id, sheet):
    row = selected(sphere_id, sheet, require_owned=True)
    return row["key_ability"] if row else None


def chosen_ability(sphere_id, sheet):
    """The printed key ability this character uses for one sphere.

    Axes prints "Strength or Constitution" and Sniper "Dexterity or
    Constitution". The player's stored table choice is honoured; without one
    the better of the printed alternatives applies, so a Body Refiner is never
    given the lower modifier by default. The sheet's own key ability is never
    changed.
    """
    rule = key_ability_for(sphere_id, sheet)
    if not rule:
        return None
    alternatives = [str(a).upper() for a in rule.get("alternatives") or []]
    base = str(rule.get("ability") or "CON").upper()
    stored = str((sheet.get("body_refining_key_abilities") or {}).get(sphere_id) or "").upper()
    if stored and stored in [base, *alternatives]:
        return stored
    if not alternatives:
        return base
    from combat.table_advance import current_scores
    mods = {ability: (int(score) - 10) // 2 for ability, score in current_scores(sheet).items()}
    return max([base, *alternatives], key=lambda ability: mods.get(ability, -99))


def key_choices(sphere_id, sheet):
    """The printed alternatives and the character's current effective choice."""
    rule = key_ability_for(sphere_id, sheet)
    if not rule or not rule.get("alternatives"):
        return None
    return {"ability": str(rule.get("ability") or "CON").upper(),
            "alternatives": [str(a).upper() for a in rule["alternatives"]],
            "chosen": chosen_ability(sphere_id, sheet)}


def authored_insights():
    # Give each caller its own records; catalogue projection may remove raw text.
    return json.loads(json.dumps(list(access()["authored_upgrade_insights"].values())))
