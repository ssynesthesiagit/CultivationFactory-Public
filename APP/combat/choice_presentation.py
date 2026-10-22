"""Read-only map context for spatial choices; never changes legal options or answers.

Used by TabletopService after printed decision text is built. Both Needle's
``cell:x,y`` IDs and older plugins' ``x,y`` IDs are supported, without matching
ability names. Creature IDs use their pause positions; mixed choices retain
their text options alongside the map. A choice is spatial only when an option carries a square;
creature IDs alone never make a choice spatial, so purely creature or text choices keep their lists.
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
    # Only a square makes a choice spatial: a creature-only list keeps its list (see space_choice).
    if not options or not any(option_cell(option) is not None for option in options):
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

    Hooks enrich instructions/footprints for their own choices. Spatial choices
    use the map even without a hook; multi-selection uses map toggles and a
    confirmation button, retaining the native minimum and maximum.
    """
    from .ext import query

    for answer in query("choice_map_pick", engine, dict(choice), dict(context)):
        if isinstance(answer, dict):
            return answer
    return None


def engine_cell(option: dict) -> dict | None:
    """The square the engine gave an option: its own cell/position/destination/area, or a square ID."""
    return (option.get("cell") or option.get('position') or option.get('destination')
            or (option.get('area') or {}).get('center') or option_cell(option["id"]))


def space_choice(prompt: dict, context: dict, engine: Any) -> dict:
    choice = prompt.get("choice")
    if not choice or engine is None or not choice.get("options"):
        return prompt
    # A choice is spatial only when the engine marked at least one option with a square. A creature ID
    # alone never routes a list to the map: an ally or target list keeps its list dialog.
    if not any(engine_cell(option) for option in choice["options"]):
        return prompt
    positions = json.loads((context.get("choice_trigger") or {}).get("space_positions") or "{}")
    cells = []
    for option in choice["options"]:
        cell = engine_cell(option)
        target = engine.state.actors.get(option["id"])
        if cell is None and target is not None:
            cell = positions.get(option['id']) or {"x": target.position.x, "y": target.position.y, "z": target.position.z}
            cell = {key: cell[key] for key in ('x', 'y', 'z') if key in cell}
        if cell is None:
            cells.append(option)
            continue
        cells.append({**option, "cell": cell, **({"target_id": option["id"]} if target is not None else {})})
    if not any(option.get('cell') for option in cells):
        return prompt
    # Spatial answers use the main map by default. Hooks only enrich previews
    # and instructions; forgetting a presentation hook must never produce a
    # coordinate wall. Option identities and selection bounds remain native.
    pick = {**(map_pick(engine, {**choice, "options": cells}, context) or {}),
            "cells": [cell["cell"] for cell in cells if cell.get('cell')]}
    chooser_id = context.get("reactor_id")
    chooser = engine.state.actors.get(chooser_id)
    if chooser is None:
        return prompt
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
