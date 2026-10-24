"""Bounded text profile used by protocol.build_prompt for small model seats.

Consumes only the runner's redacted own view and public controller ranking.
No engine access, mechanics changes, or inference about unseen creatures.
"""
import json

PROMPT_BUDGET = 12000
TINY_PROMPT_BUDGET = 8000
MAX_GROUPS = 6
MAX_CHOICES = 12
MAP_RADIUS = 6  # squares: a 65-foot window, clipped to observed geometry
SYSTEM = (
    "Play this fighter using only supplied observations and legal_menu keys. "
    "Squares are 5 feet; cell_runs=[y,x_first,x_last]; wall coordinates are in "
    "thousandths of a square. The map is a cropped window, not the whole arena. "
    "Nearby known creatures and selected targets are listed; others are omitted. "
    "Dao is temperament, not an ability. Follow costs and action availability. "
    "TURN: at most 3 steps, finish with End turn; each step is rechecked. "
    "REACTION: answer only this trigger. Return one JSON object matching "
    "reply_schema, without commentary or tools."
)


def _group(option):
    return json.dumps({k: option[k] for k in ("action", "source", "description", "cost_label", "economy")
                       if k in option}, sort_keys=True)


def select_menu(legal, builtin, ranked_keys, view=None):
    """Top six scored groups / twelve choices, always retaining pick and End turn.

    Add scored alternatives and engine-legal flight representatives. Within
    other groups retain at most two destinations/target variants.
    """
    end = next(k for k, v in legal.items() if v["action"] == "End turn")
    keys = list(dict.fromkeys((builtin, end)))
    if view is not None:
        from .flight_options import representatives
        keys = list(dict.fromkeys([*keys, *representatives(view, legal, ranked_keys)]))[:MAX_CHOICES]
    counts = {}
    for key in keys:
        group = _group(legal[key])
        counts[group] = counts.get(group, 0) + 1
    for key in ranked_keys:
        if key not in legal or key in keys:
            continue
        group = _group(legal[key])
        if counts.get(group, 0) >= 2 or (group not in counts and len(counts) >= MAX_GROUPS):
            continue
        if len(keys) >= MAX_CHOICES:
            break
        keys.append(key)
        counts[group] = counts.get(group, 0) + 1
    return {k: legal[k] for k in keys}


def nearby_view(view, targets, radius):
    """Crop already observed square-clipped geometry; strip others' private fields.

    Wall pieces come from project_map, which clips each to a single square.
    Include a boundary piece only if all its points lie inside the window.
    Creature radius is 60 feet, plus any current selected action targets.
    """
    own = next((a for a in view.get("actors", []) if a["entity_id"] == view["fighter"]), {})
    position = own.get("position") or {"x": 0, "y": 0}
    x, y = position["x"], position["y"]
    board = view.get("map", {})
    bounds = [max(0, x-radius), max(0, y-radius),
              min(board.get("width", x+radius+1)-1, x+radius),
              min(board.get("height", y+radius+1)-1, y+radius)]
    def inside(cx, cy):
        return bounds[0] <= cx <= bounds[2] and bounds[1] <= cy <= bounds[3]
    def distance(actor):
        p = actor.get("position") or {}
        return max(abs(p.get("x", x+999)-x), abs(p.get("y", y+999)-y))
    actors = [a for a in view.get("actors", []) if a.get("entity_id") != view["fighter"]
              and (a.get("entity_id") in targets or distance(a) <= 12)]
    actors.sort(key=lambda a: (a["entity_id"] not in targets, distance(a), a["entity_id"]))
    # Preserve every selected target; bound optional crowded nearby observations.
    selected = [a for a in actors if a["entity_id"] in targets]
    selected += [a for a in actors if a["entity_id"] not in targets][:12]
    public_fields = ("entity_id", "display_name", "team_id", "position", "hit_points", "active", "conditions")
    state = {"fighter": view["fighter"], "round": view.get("round"),
             "actors": ([own] if own else []) + [{k: a[k] for k in public_fields if k in a} for a in selected],
             "objects": [{k: a[k] for k in ("id", "name", "kind", "x", "y", "hp", "max_hp") if k in a}
                         for a in view.get("objects", []) if a.get("id") in targets
                         or inside(a.get("x", -999), a.get("y", -999))],
             "observations_omitted": len(view.get("actors", [])) - len(selected) - bool(own)}
    dao = view.get("dao") or {}
    if view.get('information'):
        state['information'] = list(view['information'])
    temperament = dao.get("temperament") or {}
    state["dao"] = ("; ".join(filter(None, [", ".join(dao.get("role") or []),
        temperament.get("natural", ""),
        "preferred feet " + str(dao.get("preferred_distance_ft", [])),
        "save resources " + str(dao.get("save_resources", {}))])))[:240]
    cropped = {k: board[k] for k in ("width", "height") if k in board}
    cropped["window"] = bounds
    for kind in ("terrain", "zones", "trees"):
        cropped[kind] = []
        for row in board.get(kind, []):
            cells = [c for c in row.get("cells", []) if inside(
                c["x"] if isinstance(c, dict) else c[0], c["y"] if isinstance(c, dict) else c[1])]
            if cells:
                cropped[kind].append({**row, "cells": cells})
    cropped["walls"] = [w for w in board.get("walls", []) if w.get("points") and all(
        bounds[0]*1000 <= a <= (bounds[2]+1)*1000 and bounds[1]*1000 <= b <= (bounds[3]+1)*1000
        for a, b in w["points"])]
    return state, cropped


def build_compact_prompt(view, legal, builtin, kind, limit, repair, ranked_keys, profile="compact"):
    """Fit ranked alternatives then crop radius; never truncate a legal choice.

    An oversized mandatory choice/own state fails safely into runner fallback
    rather than dispatching an over-budget or misleading partial prompt.
    """
    from .protocol import build_frame, compact_map, serialize_prompt
    budget = TINY_PROMPT_BUDGET if profile == "tiny" else PROMPT_BUDGET
    limit = min(limit, 3)
    menu = select_menu(legal, builtin, ranked_keys, view) if kind == "TURN" else legal
    mandatory = {builtin, next(k for k, v in legal.items() if v["action"] == "End turn")} if kind == "TURN" else set()
    if kind == "TURN":
        from .flight_options import representatives
        flight_keys = representatives(view, legal, ranked_keys)
        mandatory.update(flight_keys[:1])
    radius = MAP_RADIUS
    while True:
        targets = {t for option in menu.values() if isinstance(option, dict) for t in option.get("targets", [])}
        state, board = nearby_view(view, targets, radius)
        # Reuse the full profile's single implementation of grouping/examples.
        frame = build_frame(state, menu, builtin, "", kind, limit)
        frame.update(state=state, visible_map={**compact_map(board), "window": board["window"]},
                     prompt_profile=profile)
        frame["built_in_reason"] = "Suggested legal choice."
        frame["worked_example"].pop("why", None)
        if repair:
            frame["repair"] = "Invalid answer: " + repair[:180] + ". Use this menu and schema."
        prompt = serialize_prompt(SYSTEM, frame, limit)
        if len(prompt) <= budget:
            return prompt
        removable = [k for k in menu if k not in mandatory] if kind == "TURN" else []
        if removable:
            menu = {k: v for k, v in menu.items() if k != removable[-1]}
        elif radius > 1:
            radius -= 1
        else:
            raise ValueError("Compact mandatory frame exceeds prompt budget")
