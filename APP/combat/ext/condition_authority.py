"""Shared Source CL lookup for retained condition instances.

Missing condition metadata is resolved from the recorded source actor and
source action. Unknown typed authority remains unknown so callers can keep
their printed contest instead of treating missing data as zero.

Consumers: Ghost Sight and Public Diagnosis in exorcist.py and
mudang_ritual.py, plus Gut's guest-concealment mask in mudang_ritual.py.
"""
from __future__ import annotations

from typing import Any


def source_cl(engine: Any, condition: Any) -> int | None:
    data = getattr(condition, "data", None) or {}
    explicit = data.get("source_cl")
    if explicit is not None:
        try:
            value = int(explicit)
            return value if value >= 1 else None
        except (TypeError, ValueError):
            return None
    source_id = str(getattr(condition, "source_actor_id", "") or "")
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if str(bundle.get("actor_id") or "") == source_id:
            try:
                value = int(bundle.get("cl"))
                return value if value >= 1 else None
            except (TypeError, ValueError):
                return None
    action = engine.action_catalog.get(str(getattr(condition, "source_definition_id", "") or ""))
    if action is not None:
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
        try:
            value = int((typed.get("numbers") or {}).get("cl"))
            return value if value >= 1 else None
        except (TypeError, ValueError):
            pass
    # Without a recorded source actor, there is no cultivation authority.
    # A named source with no resolvable bundle/action remains unknown; callers
    # must preserve the printed contest rather than silently assigning CL 0.
    return 0 if not source_id else None
