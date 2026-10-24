"""Sealed area provenance shared by factory_compiler and zones.

Future area interactions (for example overlap-local suppression) can read ``of``
without consulting a caster's current sheet, current rules or visual material.
Only reviewed zone effects' explicit ``source_tags`` confer tags; sphere origin,
damage type and appearance are independent information. No interaction is
implemented here and old saved areas without a snapshot remain unclassified.
"""

from __future__ import annotations

import copy
from typing import Any

SCHEMA = "TianxiaFoundry.ZoneSource.v1"


def mundane_rows(rows: list[Any], default: Any = None) -> bool | None:
    """Unanimous effect classification for compiler and suppression helpers.

    A parent's explicit flag applies to its nested effects unless overridden.
    Mixed, malformed or missing classification stays unknown. Action-level
    mundane is the legacy default; damage type and sphere never supply it.
    """
    values = []

    def visit(value: Any, inherited: Any) -> None:
        if isinstance(value, dict):
            flag = value.get("mundane", inherited)
            if value.get("type"):
                values.append(flag)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child, flag)
        elif isinstance(value, list):
            for child in value:
                visit(child, inherited)

    visit(rows, default)
    return values[0] if values and all(type(v) is bool and v == values[0] for v in values) else None


def compile_profile(typed: dict[str, Any], mechanic: dict[str, Any], duration: dict[str, Any]) -> dict[str, Any]:
    """Seal the selected action's numbers and reviewed area tags at compilation.

    A menu's selected option owns its effects. A Fire sphere identifier alone is
    retained as provenance, never promoted to a Fire tag. ``duration_kind`` is
    the area's lifetime; ``activation_duration_kind`` distinguishes an instant
    action that leaves ground from its subsequently persistent ground.
    """
    tags = sorted({tag for effect in typed.get("effects") or []
                   if isinstance(effect, dict) and effect.get("type") == "zone"
                   for tag in effect.get("source_tags") or [] if isinstance(tag, str) and tag})
    numbers = typed.get("numbers") or {}
    source = mechanic.get("source") or {}
    # Seal explicit effect-row classification only. Missing or conflicting
    # flags stay unknown; neither sphere origin nor appearance implies magic.
    area_rows = [effect for effect in typed.get("effects") or []
                 if isinstance(effect, dict) and effect.get("type") == "zone"]
    mundane = mundane_rows(area_rows, typed.get("mundane"))
    classification = {"mundane": int(mundane)} if mundane is not None else {}
    return {"schema": SCHEMA, "mechanic_id": str(typed.get("source") or mechanic.get("mechanic_id") or ""),
            "sphere_id": str(typed.get("sphere") or mechanic.get("sphere_id") or ""),
            "text_sha256": str(source.get("text_sha256") or ""), "source_tags": tags,
            "source_cl": int(numbers.get("cl") or 1), "save_dc": int(numbers.get("save_dc") or 0),
            "duration_kind": str(duration.get("kind") or ""),
            "activation_duration_kind": str((typed.get("duration") or {}).get("kind") or ""),
            "concentration": int(bool(duration.get("concentration"))), **classification}


def of(zone: Any) -> dict[str, Any] | None:
    """Return an independent copy of sealed provenance, or None for legacy areas.

    Callers must handle missing provenance explicitly. Never reconstruct an old
    area's source from current authority, caster CL, damage or its appearance.
    """
    profile = zone.trigger_profile.get("source_profile")
    if not isinstance(profile, dict) or profile.get("schema") != SCHEMA:
        return None
    return copy.deepcopy(profile)


def capture(profile: dict[str, Any] | None, numbers: dict[str, Any]) -> dict[str, Any] | None:
    """At creation, capture actual action CL/DC while preserving sealed tags.

    Used by zones.create: runtime action adjustments can differ from the initial
    compiler numbers. Missing/legacy provenance stays absent, even for a Fire
    action; it is never regenerated from current authority.
    """
    if not isinstance(profile, dict) or profile.get("schema") != SCHEMA:
        return None
    return {**copy.deepcopy(profile), "source_cl": int(numbers.get("cl") or 1),
            "save_dc": int(numbers.get("save_dc") or 0)}
