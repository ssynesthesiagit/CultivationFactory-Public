"""Stealth Surge (eye, 2026-09-28): "While you are hidden, creatures Analyzed by you have Disadvantage on Wisdom
(Perception) checks made to find you." Uses the new "stealth_search_mode" hook (combat/stealth.py search())."""

from __future__ import annotations

from typing import Any

from . import hook
from .eye_common import analyzed_by, has


@hook("stealth_search_mode")
def stealth_surge(engine: Any, searcher: Any, hidden_foe: Any) -> str | None:
    if not has(engine, hidden_foe.entity_id, "stealth_surge"):
        return None
    return "DISADVANTAGE" if analyzed_by(searcher, hidden_foe.entity_id) else None
