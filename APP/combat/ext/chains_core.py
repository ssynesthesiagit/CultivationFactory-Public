"""Plain Bound condition text retained from rider lane C13.

The single mechanical implementation lives in chains_sphere (Speed, escape
checks, tether breaks) and move_limits (shared tether movement gate). This
module only describes the owned condition and its saved tether for players.
"""

from __future__ import annotations

from typing import Any

from . import hook

BOUND = "condition:typed.bound"


@hook("status_description")
def bound_text(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if str(row.get("condition_id") or "") != BOUND:
        return None
    anchor = engine.state.actors.get(str(row.get("source_actor_id") or "")) if engine is not None else None
    length = int((data or {}).get("tether_ft") or 0)
    reach = (f", and it can't willingly move more than {length} feet from "
             f"{anchor.display_name if anchor is not None else 'the other end of the chain'}") if length else ""
    return {"text": f"Bound by a chain: Speed 10 feet lower, it can't Dash, it has Disadvantage on checks to escape a grapple or other "
                    f"hold{reach}.",
            "handling": "The table applies all of this while the chain holds."}
