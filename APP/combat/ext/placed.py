"""Placed and delayed effects on the map (owner 2026-09-29: "i want everything we can automated, keep going until its
Shared public helpers serve Iron Fist riders, Forms, Diagnosis and their placement/menu consumers.
only the non-combat ones left"; lead's systems list U3): things a creature puts somewhere and that act later -- a
Trap, a dormant Blossom, a Figment, a Standard, a puppet's vessel, the trace of a teleport.

Shared helpers serve trap, blossom, figment, banner, vessel and return_mark;
Spirit Awakening also uses ``note`` for an evented, readable diagnosis.
Shared public helpers include context and note, used by Radiance's timed states
and Unclean damage riders as well as the placement consumers below.

They share one store: a typed zone (combat/zones.py, kind "TYPED") whose ``trigger_profile["placed"]`` names what it is
(``{"tag": "trap" | "blossom" | "figment" | "standard" | "trace" ..., ...its own data}``).  A placement therefore
- is drawn on the table by the zone's own name, colour and material (static/tabletop/zones.js), with its tooltip;
- is replayed from its ZONE_CREATED / ZONE_REMOVED events like every zone (combat/gate3_reducer.py), so a saved fight
  reloads with every trap and bud where it was;
- rides a creature (``anchor_id``) or its creator (``follows_owner``) through zones.follow;
- runs its own triggers through zones._fire (enter / start), once per creature per turn;
- ends by itself when its ``duration_rounds`` have run out (zones.on_turn_start, at its creator's turn).

Changing a placement is one more ZONE_CREATED with the whole zone (``update``), never an in-place edit the events do not
show; removing one is ``drop`` (ZONE_REMOVED).  The plug-in modules that use it (trap.py, blossom.py, ...) put their own
effect blocks in ``combat/ext`` and register nothing here but the two engine hooks below.

Hooks added to the framework by this module: none.  It uses ``event`` (a MOVEMENT_COMMITTED's path).  The plug-ins that use it
add ``after_search`` (typed_executor.block_search; see combat/ext/__init__.py) and one PASSIVE_TRIGGERED line format
(``note`` below; combat/history_feed.py prints its ``text``).
Shared helpers are used by trap, blossom, illusion, war_banner, vessel and
other placement plug-ins; protection uses the readable evented ``note`` helper
for Punishment Aegis. They do not access this module's private helpers.
"""

from __future__ import annotations

import copy
from typing import Any

from . import hook, run

TAG_KEY = "placed"


def deadline_due(engine: Any, zone: Any, name: str) -> bool:
    """Shared stored-token reader for Shadow, Force and Destruction placements."""
    from .effect_durations import stored_token_due
    return stored_token_due(engine, name, zone.per_turn_triggered, "placed_until")


@hook("nominal_slot_boundary")
def nominal_placements(engine: Any, actor: Any, checkpoint: str) -> None:
    from .effect_durations import stored_token_due
    for zone in list(of(engine)):
        until = data(zone).get("until")
        if until and stored_token_due(engine, until, zone.per_turn_triggered, "placed_until",
                                      actor=actor, checkpoint=checkpoint):
            run("placed_deadline_expiring", engine, zone)
            if zone.active:
                drop(engine, zone, "DURATION_ENDED")


def _zones() -> Any:
    from .. import zones

    return zones


def new_id(engine: Any, owner: Any, tag: str) -> str:
    """The id the next placement will have (its own events number it: two placements in one action still differ)."""
    return f"zone:placed:{tag}:{owner.entity_id}:{engine.state.event_sequence + 1}"


def place(engine: Any, owner: Any, *, source: str, tag: str, cells: Any, name: str, placed: dict[str, Any] | None = None,
          triggers: list[dict[str, Any]] | None = None, numbers: dict[str, Any] | None = None, duration_rounds: int | None = None,
          color: str | None = None, material: str = "generic", terrain: list[str] | None = None, difficult: str | None = None,
          anchor_id: str | None = None, follows_owner: bool = False, concentration: bool = False, zone_id: str | None = None,
          shape: str = "cube", size_ft: int = 5, inside: list[dict[str, Any]] | None = None, obscured: str | None = None,
          extra: dict[str, Any] | None = None, radial_volume: bool = False) -> Any:
    """Put a placement on the map.  ``source`` must be an action of its creator's catalog (zones._run looks it up to run a
    trigger); ``cells`` are the squares it fills (a Position or a list of them). Shared radial_volume is opt-in for Great Mantra and Silence: the first cell is the center, shape/size supply native 3D membership. Default False retains explicit painted footprints."""
    from ..gate2_runtime_models import Position, ZoneState

    zones = _zones()
    cells = tuple(cells) if isinstance(cells, (list, tuple, set)) else (cells,)
    cells = tuple(cell if isinstance(cell, Position) else Position(x=int(cell[0]), y=int(cell[1])) for cell in cells)
    zone_id = zone_id or new_id(engine, owner, tag)
    zone = ZoneState(
        zone_id=zone_id, source_definition_id=source, owner_id=owner.entity_id, center=cells[0], radius_cells=(size_ft // engine.grid.square_size_ft if radial_volume else 0), affected_cells=cells,
        concentration_link=bool(concentration), duration_rounds=duration_rounds, created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "name": name, "terrain": list(terrain or []), "difficult": difficult, "obscured": obscured,
                         "color": color, "follows_owner": bool(follows_owner), "shape": shape, "size_ft": size_ft,
                         "triggers": copy.deepcopy(triggers or []), "move_through": None, "talents": [], "inside": copy.deepcopy(inside or []),
                         "visual": {"material": material}, "numbers": dict(numbers or {}),
                         **({"anchor_id": anchor_id} if anchor_id else {}), **(extra or {}),
                         TAG_KEY: {"tag": tag, **copy.deepcopy(placed or {})}})
    engine.state.zones[zone_id] = zone
    engine._append_event("ZONE_CREATED", source, actor_id=owner.entity_id, payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, source)
    return zone


def data(zone: Any) -> dict[str, Any]:
    """Plug-in placement metadata; ordinary typed zones use a scalar placement stamp.

    Shared by Banner, Trap and the other placement consumers in this module's
    documented list. Scalar stamps are not plug-in records and remain inert.
    """
    record = (zone.trigger_profile or {}).get(TAG_KEY)
    return record if isinstance(record, dict) else {}


def of(engine: Any, tag: str | None = None, *, owner_id: str | None = None) -> list[Any]:
    """Active placements, oldest first, of one tag and/or one creator."""
    rows = [zone for zone in engine.state.zones.values() if zone.active and data(zone) and (tag is None or data(zone).get("tag") == tag)
            and (owner_id is None or zone.owner_id == owner_id)]
    return sorted(rows, key=lambda zone: (zone.created_round, int(zone.zone_id.rsplit(":", 1)[-1])))


def at(engine: Any, position: Any, tag: str | None = None) -> list[Any]:
    return [zone for zone in of(engine, tag) if any((cell.x, cell.y) == (position.x, position.y) for cell in zone.affected_cells)]


def update(engine: Any, zone: Any, **changes: Any) -> None:
    """Change what a placement remembers (a warned creature, a spent charge): the whole zone is re-recorded so a reload
    or replay sees it."""
    zone.trigger_profile = {**zone.trigger_profile, TAG_KEY: {**data(zone), **changes}}
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})


def reshape(engine: Any, zone: Any, *, cells: Any = None, center: Any = None, name: str | None = None,
            triggers: list[dict[str, Any]] | None = None, profile: dict[str, Any] | None = None, **placed: Any) -> None:
    """Change the squares, name or triggers of a placement together with what it remembers, as one recorded change.  ``profile``
    changes the zone's own settings (shape, size_ft, difficult, anchor_id, ...); a value of None takes the setting away.  An
    area zone keeps its ``center`` (the square its shape is drawn round); by default the first of ``cells``."""
    from ..gate2_runtime_models import Position

    if cells is not None:
        cells = tuple(cells) if isinstance(cells, (list, tuple, set)) else (cells,)
        zone.affected_cells = tuple(cell if isinstance(cell, Position) else Position(x=int(cell[0]), y=int(cell[1])) for cell in cells)
        zone.center = center if center is not None else zone.affected_cells[0]
    elif center is not None:
        zone.center = center
    settings = dict(zone.trigger_profile)
    if name is not None:
        settings["name"] = name
    if triggers is not None:
        settings["triggers"] = copy.deepcopy(triggers)
    for key, value in (profile or {}).items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = copy.deepcopy(value)
    settings[TAG_KEY] = {**data(zone), **placed}
    zone.trigger_profile = settings
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})


def unanchor(engine: Any, zone: Any, **placed: Any) -> None:
    """The placement stays where it is instead of riding a creature (zones.follow reads ``anchor_id`` and ``follows_owner``)."""
    reshape(engine, zone, profile={"anchor_id": None, "follows_owner": False}, **placed)


def area(engine: Any, centre: Any, shape: str, size_ft: int, vertex: Any = None) -> tuple[Any, ...]:
    """The squares a shape of a size covers around a centre (a "10-foot-radius sphere" is ``area(engine, cell, "sphere", 10)``)."""
    return _zones()._cells(engine, centre, {"shape": shape, "size_ft": size_ft}, vertex)


def context(engine: Any, owner: Any, source: str, numbers: dict[str, Any], targets: Any = (), *, action: Any = None) -> Any:
    """A typed Context (combat/typed_executor.py) for a placement's own effects: ``owner`` uses ``action`` (a catalog action;
    the placement's source by default) against ``targets``. Blossom, Trap and
    Formation consumers can supply a full recipient roster. Bind target only
    for a single recipient; a bound target otherwise narrows a multi-save root."""
    from ..typed_executor import Context

    targets = list(targets)
    typed = {"effects": [], "numbers": dict(numbers), "weapon": None, "duration": {"kind": "instant"}, "riders": [], "source": source}
    return Context(engine, owner, action or engine.action_catalog.get(source), getattr(engine, "_active_intent", None), typed, targets,
                   targets[0] if len(targets) == 1 else None, {})


def drop(engine: Any, zone: Any, reason: str) -> None:
    _zones().remove(engine, zone, reason)


def note(engine: Any, source: str, actor: Any, text: str, targets: Any = ()) -> None:
    """A plain log line for something that happened (a GM_RIDER prints as "Not automated", which is the wrong words here)."""
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=getattr(actor, "entity_id", actor), target_ids=tuple(t.entity_id for t in targets),
                         payload={"text": text})


def notice(ctx: Any, text: str) -> None:
    """Plain resolved-effect notice shared by Formations, mounts and spirit abilities.

    Keep ctx.rider for mechanics requiring a GM ruling or skipped automation.
    """
    note(ctx.engine, ctx.source, ctx.actor, text, ctx.targets)


def cl_row(cl: int, rows: list[tuple[int, int, Any]]) -> Any:
    """The value of the (low, high, value) row a Cultivation Level falls in (the rules' "CL 1-4 / 5-10 / ..." tables)."""
    for low, high, value in rows:
        if low <= cl <= high:
            return value
    return rows[-1][2] if cl > rows[-1][1] else rows[0][2]


def occupied(engine: Any, cell: Any) -> bool:
    """Whether a creature stands on the square (any part of its footprint)."""
    return any(actor.active and engine._footprint_intersects(actor, (cell,)) for actor in engine.state.actors.values())


def free_square(engine: Any, cell: Any) -> bool:
    grid = engine.grid
    return grid.in_bounds((cell.x, cell.y)) and (cell.x, cell.y) not in grid.blocked and not occupied(engine, cell)


# ----------------------------------------------------------------------------------------------- the path of a move
@hook("event")
def squares_passed_through(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The engine reads a move by where it starts and ends (zones.on_moved); a trap is sprung by entering one of its
    squares "for the first time on a turn" even when the mover walks on (Trap core, Default Trigger: "even if that creature
    crosses several spaces occupied by the same trap").  So every square of a committed path is offered to the placements'
    "enter" triggers, in order, after the move: the mover's own end square is left to zones.on_moved (the per-turn
    guard makes a second look harmless).  A per-step hook in the movement loop (gate2_engine, saved-fight lock) would stop a
    mover Restrained or Prone by the trap at that square; this hook applies the trap's effect once the move is over."""
    if event_type != "MOVEMENT_COMMITTED":
        return None
    payload = kwargs.get("payload") or {}
    path = payload.get("path") or ()
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not path or not any(zone.trigger_profile.get("triggers") and data(zone).get("walk_through") for zone in of(engine)):
        return None
    zones = _zones()
    from ..gate2_runtime_models import Position

    seen: set[str] = set()
    for step in path[1:-1]:  # not the square it started on, nor the one it ended on (zones.on_moved sees that)
        cell = step if isinstance(step, Position) else Position(x=int(step["x"]), y=int(step["y"])) if isinstance(step, dict) else Position(x=int(step[0]), y=int(step[1]))
        for zone in of(engine):
            if zone.zone_id in seen or not data(zone).get("walk_through") or not zone.active:
                continue
            if any((square.x, square.y) == (cell.x, cell.y) for square in zone.affected_cells):
                seen.add(zone.zone_id)
                if mover.active:
                    zones._fire(engine, zone, mover, "enter")
    return None
