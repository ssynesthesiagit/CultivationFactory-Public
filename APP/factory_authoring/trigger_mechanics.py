"""Reviewed trigger event sealing, shared by the typed-authority builder and its
synthetic source-binding regressions. Runtime reaction_triggers consumes the
sealed activation.trigger_events instead of parsing presentation prose.
"""
from __future__ import annotations

import copy
import hashlib


def seal_trigger_events(mechanics: dict[str, dict], readings: dict[tuple[str, str], dict]) -> None:
    """Copy only the current source trigger's reviewed event grammar and limits.

    Yang completion/Overkindled responses and all other reviewed reactions use
    the same contract. Stale/absent readings leave the legacy classifier intact.
    Rebuilding after a source edit removes the old sealed grammar.
    """
    for key, mechanic in mechanics.items():
        activation = mechanic.get("activation") or {}
        activation.pop("trigger_events", None)
        trigger_hash = hashlib.sha256(str(activation.get("trigger") or "").encode("utf-8")).hexdigest()
        row = readings.get((key, trigger_hash))
        if row is not None:
            activation["trigger_events"] = copy.deepcopy(row.get("events") or [])
