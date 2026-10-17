"""Read-only map context for all space choices; never changes legal options or answers.

Used by TabletopService after printed decision text is built. Both Needle's
``cell:x,y`` IDs and older plugins' ``x,y`` IDs are supported, without matching
ability names. Non-space choices keep their ordinary list presentation.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .footprints import STANDARD_ACTOR_FOOTPRINT


def token_position(engine: Any, actor_id: str, actor: Any) -> dict:
    """Presentation anchor and occupied cells, without resolving/mutating authority.

    Needle snapshots this at the pause; TabletopService also uses it for legacy
    pauses. Missing footprint authority retains the engine's single-cell default.
    """
    footprint = getattr(engine, "actor_footprints", {}).get(actor_id, STANDARD_ACTOR_FOOTPRINT)
    return {"x": actor.position.x, "y": actor.position.y,
            "cells": [{"x": x, "y": y} for x, y in footprint.occupied_cells((actor.position.x, actor.position.y))]}


def option_cell(option_id: str) -> dict | None:
    """Decode established space IDs without inferring an ability's rules."""
    match = re.fullmatch(r"(?:cell:)?(-?\d+),(-?\d+)(?:,(-?\d+))?", option_id)
    return {"x": int(match[1]), "y": int(match[2]),
            **({'z': int(match[3])} if match[3] is not None else {})} if match else None


def capture_space_positions(engine: Any, options: list[str]) -> str:
    """Needle's display-only snapshot: positions at the pause, before rollback.

    Serialized as a string in choice_trigger, never stored in mechanical state.
    TabletopService uses it for choices after movement within the current action.
    """
    if not options or not all(option_cell(option) is not None for option in options):
        return ""
    # A coordinate cannot identify a repeated route point or multiple step events.
    # Capture the exact completed event/path boundary before request rollback.
    # This is transport metadata only; old snapshots without it remain readable.
    cursors = {}
    for event in getattr(engine, "events", ()):
        if event.event_type == "MOVEMENT_COMMITTED" and event.payload.get("path"):
            cursors[event.actor_id] = {"event_sequence": event.sequence,
                                      "path_index": len(event.payload["path"]) - 1}
    return json.dumps({key: {**token_position(engine, key, actor),
                            "movement_cursor": cursors.get(key, {"event_sequence": 0, "path_index": 0})}
                       for key, actor in engine.state.actors.items() if actor.active}, sort_keys=True)


def map_pick(engine: Any, choice: dict, context: dict) -> dict | None:
    """The main-map point picker for a space choice, or None to keep the list presentation.

    The one general seam for "choose a square on the map": a plug-in answers the read-only
    ``choice_map_pick`` hook for the choices it owns and the table shows those squares highlighted
    on the main map, clicked instead of listed. ``choice`` already carries each option's ``cell``.
    The answer is copied onto the payload as ``choice.map_pick`` with its legal squares, so the
    client needs no ability knowledge. Nothing here decides legality or the answer: the hook is a
    presentation vote, the option ids it points at are the ones the transport already carries.

    Only a single-space choice qualifies; a checkbox choice over many squares has no one square to
    click, and it keeps the list. The hook is default-inert: no answer keeps every existing choice
    exactly as it was, so a saved fight and an older client are unchanged.
    """
    from .ext import query

    for answer in query("choice_map_pick", engine, dict(choice), dict(context)):
        if isinstance(answer, dict):
            return answer
    return None


def space_choice(prompt: dict, context: dict, engine: Any) -> dict:
    choice = prompt.get("choice")
    if not choice or engine is None or not choice.get("options"):
        return prompt
    cells = []
    for option in choice["options"]:
        cell = option_cell(option["id"])
        if cell is None:
            return prompt
        cells.append({**option, "cell": cell})
    pick = None
    if int(choice.get("maximum") or 0) <= 1:
        pick = map_pick(engine, {**choice, "options": cells}, context)
        if pick is not None:
            pick = {**pick, "cells": [cell["cell"] for cell in cells]}
    chooser_id = context.get("reactor_id")
    chooser = engine.state.actors.get(chooser_id)
    if chooser is None:
        return prompt
    positions = json.loads((context.get("choice_trigger") or {}).get("space_positions") or "{}")
    tokens = []
    for key, actor in engine.state.actors.items():
        if key not in positions and (positions or not getattr(actor, "active", True)):
            continue
        position = positions.get(key) or token_position(engine, key, actor)
        anchor = {"x": position["x"], "y": position["y"]}
        # Older serialized pauses contain only anchors. Retain their legacy view.
        tokens.append({"id": key, "name": actor.display_name, "position": anchor,
                       **({"movement_cursor": position["movement_cursor"]} if "movement_cursor" in position else {}),
                       "cells": position.get("cells", [anchor])})
    grid = getattr(engine, "grid", None)
    chooser_position = positions.get(chooser_id) or {"x": chooser.position.x, "y": chooser.position.y}
    origin = {"x": chooser_position["x"], "y": chooser_position["y"]}
    board = {"chooser_id": chooser_id, "origin": origin,
             "tokens": tokens, "blocked": [{"x": x, "y": y} for x, y in sorted(getattr(grid, "blocked", set()))]}
    if grid is not None:
        board.update(width=grid.width, height=grid.height, square_size_ft=getattr(grid, "square_size_ft", 5))
    return {**prompt, "title": prompt["title"] if prompt["title"] == "Reaction" else f"{prompt['reaction']}: choose a space",
            "choice": {**choice, "options": cells, "space_map": board, **({"map_pick": pick} if pick else {})}}
