"""Shared darkness classification for Radiance's darkness_lifted hook and
Yang Overbright Trail's ordinary-concealment exemption.

Supernatural technique zones are magical, even when Darkvision can see through
them. Explicit ordinary map darkness stays ordinary; superior sources require a
contest and are never suppressed automatically. Classification is conservative
when saved zones predate tier metadata.
"""
from typing import Any


def scope(engine: Any, zone: Any) -> str:
    visual = zone.trigger_profile.get("visual") or {}
    source = str(getattr(zone, "source_definition_id", ""))
    action = engine.action_catalog.get(source)
    typed = (action.parameters or {}).get("typed") or {} if action is not None else {}
    tier = str(visual.get("tier") or typed.get("tier") or typed.get("rarity") or "").lower()
    if visual.get("legendary") or visual.get("secret") or tier in ("legendary", "secret"):
        return "superior"
    if visual.get("magical") is False or visual.get("ordinary"):
        return "ordinary"
    if visual.get("magical") or typed.get("sphere") or source.startswith(("DARK_", "TAL_", "tianxia.", "action:typed.")):
        return "magical"
    return "ordinary"
