"""Glass panes: Raised Pane Scripture, Pane-Step Projection and Clean Break (AUTO57, Glass sphere automation).

Owner text (APP/authority/typed_mechanics/rules_text.json):
  Raised Pane Scripture: "Create one transparent Glass Pane in an unoccupied space you can see within range. The pane is a
    5-foot-by-5-foot square. It must be vertical, horizontal, or angled, and must be anchored to a solid surface or another
    Glass Pane. The pane has: AC equal to 12 + your Proficiency Bonus; HP equal to 5 x your CL; immunity to Poison and Psychic
    damage; vulnerability to Thunder damage. When reduced to 0 HP, the pane shatters and creates Shattered Glass Terrain in its
    space until the end of your next turn. At CL 5, create two connected panes. At CL 11, create three connected panes. At
    CL 17, create four connected panes."  (Range 60 feet; Duration: Concentration, up to 1 minute.)
  Pane-Step Projection: "When you create a projected Glass Pane, you may create it within 10 feet of you without anchoring it to
    a solid surface. The pane collapses at the end of your next turn unless it becomes anchored before then."
  Clean Break: "When you reduce a Glass Surface, fragile object, mirror, window, crystal, or mundane glass item to 0 HP, choose
    one: create Shattered Glass Terrain in one 5-foot square adjacent to it; place a Faultline Mark on one creature within 5 feet
    of it; move 5 feet without provoking Opportunity Attacks from one creature that saw it break."

How it runs (combat/ext/objects.py owns what an object is; this module only makes Glass panes and reads their breaks):
  ``glass_pane``  a typed effect (Raised Pane Scripture's row, and any projected variant of it) makes one or more panes: each a
    RuntimeObjectState with AC 12 + Proficiency Bonus, hit points 5 x CL, Poison and Psychic immunity and Thunder
    Vulnerability (combat/object_rules.py works those numbers out from the same record every time). Panes are unattended and
    never fill their square (the printed text does not say a pane blocks movement); every creature that can reach one may
    "Attack an object" it. The pane rises in the square the player aimed at, and any extra panes at CL 5/11/17 continue from it
    edge-to-edge in one straight line ("connected panes"), so each of them touches the one before it. Every square is checked
    against the printed rule -- unoccupied, within the technique's range, in the user's sight -- and the chain stops at the
    first square that is not. The first pane must touch a wall, the edge of the map or another Glass Pane ("must be anchored to a
    solid surface or another Glass Pane"); that printed line names no owner, so any pane already standing anchors the new one,
    another caster's as much as the same caster's. With nothing to anchor to, no pane rises, unless Pane-Step Projection lets it
    stand free within 10 feet of the user (asked, and the square is then the player's to choose).
  pane lifetime  the printed duration is "Concentration, up to 1 minute", so every pane records two expiry names the engine
    already removes (combat/ext/effect_durations.py): the 1-minute deadline as a slot clock, and the Concentration copy that made
    it. Ending that copy (any reason) takes the pane with it; the 1-minute deadline does the same. A pane raised free under
    Pane-Step Projection also records the end of its owner's next turn: if it has not become anchored by then it collapses, and
    if it has (a wall or another pane now touches it) the collapse name is cleared and it stands on. The names are strings and the
    Concentration copy an integer, so a committed fight reloads every pane with the same deadline it had.
  retiring vs breaking  a pane that leaves because one of those clocks ran out is retired, not broken: the printed trigger for a
    break is "When reduced to 0 HP", so a retired pane creates no Shattered Glass Terrain and offers Clean Break nothing (dropping
    Concentration or waiting out the minute would otherwise pay the three answers once per pane). ``_retire`` writes the record
    with a flag the two event readers check (``retiring``); nothing outside this plug-in changes.
  broken panes   an OBJECT_UPDATED that leaves a pane at 0 hit points shatters it: Shattered Glass Terrain (terrain.json
    "shattered glass terrain", reached through the shared ``terrain_patch`` effect, combat/ext/docket_terrain.py) fills its
    square until the end of the pane owner's next turn, the printed deadline, and the pane is gone.
  Clean Break   destroying a pane (or any fragile object: combat/object_rules.has_tag "fragile", which is glass, crystal and
    ice) offers the three printed answers once per destruction. Each answer has its own legal list: a 5-foot square of Shattered
    Glass Terrain next to it (any of the eight touching squares, occupied or not -- the printed text restricts neither), a
    Faultline Mark on one creature within 5 feet of it that does not already bear the breaker's mark, or 5 feet of movement that
    provokes no Opportunity Attack from one creature that could see it break (any distance; line of sight to the broken thing's
    square is how "saw it break" is read). The answer and its target are asked; the built-in AI takes the first legal one.
Public for other Glass plug-ins: ``pane_cells`` (the squares of one user's panes, the Glass Surfaces Faultline Marks and
Refraction Responses read), ``pane_of``, ``is_pane``, ``shattered_cells`` (a named shared helper for the terrain a break
leaves, used by Clean Break and by Living Pane Sutra's shattering shell) and ``owner_turn_terrain`` (the one place that ties a
Shattered Glass Terrain patch to the end of its owner's next turn, shared with glass_refraction's Glass Domain).
Stored data is strings and integers only (component keys and expiry names), so a saved fight replays a pane, its break and its
terrain unchanged.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

KEY = "glass_pane"          # component["kind"] of every pane this module makes
TERRAIN = "shattered glass terrain"
_RETIRING = "_glass_pane_retiring"   # engine.__dict__: this pane is leaving, not breaking (see _retire)
PANE_STEP_FEET = 10   # Pane-Step Projection: "you may create it within 10 feet of you"
OWNER_KEY = "glass_owner"  # component[OWNER_KEY]: whose pane it is
ONE_MINUTE_ROUNDS = 10     # the shared standard: 1 minute is ten rounds (combat/ext/effect_durations.py)
DEFAULT_RANGE_FT = 60      # Raised Pane Scripture's printed range, used when the action row carries none


# ------------------------------------------------------------------------------------------------ reading panes
def is_pane(obj: Any) -> bool:
    return str((getattr(obj, "component", None) or {}).get("kind") or "") == KEY


def owner_id(obj: Any) -> str:
    return str((getattr(obj, "component", None) or {}).get(OWNER_KEY) or "")


def panes_of(engine: Any, owner: Any) -> list[Any]:
    """This user's panes that are still standing."""
    who = getattr(owner, "entity_id", owner)
    return [obj for obj in engine.state.objects.values()
            if is_pane(obj) and not obj.destroyed and owner_id(obj) == str(who)]


def pane_cells(engine: Any, owner: Any) -> set[tuple[int, int]]:
    """The squares of one user's panes: the Glass Surfaces its talents mark and its Responses read."""
    return {(obj.position.x, obj.position.y) for obj in panes_of(engine, owner)}


def pane_of(engine: Any, object_id: str) -> Any | None:
    obj = engine.state.objects.get(str(object_id))
    return obj if obj is not None and is_pane(obj) else None


def shattered_cells(engine: Any, owner: Any) -> set[tuple[int, int]]:
    """The user's own Shattered Glass Terrain squares (combat/rules/terrain.json "shattered glass terrain")."""
    from .. import zones

    out: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        if zone.active and zone.owner_id == getattr(owner, "entity_id", owner) and TERRAIN in (zone.trigger_profile.get("terrain") or []):
            out |= {(cell.x, cell.y) for cell in zone.affected_cells}
    return out


def owner_turn_terrain(engine: Any, zone_id: str, source: str) -> None:
    """End one Shattered Glass Terrain patch at the end of its owner's next turn ("until the end of your next turn").

    Shared by this module's own pane break and by glass_refraction's Glass Domain, which asks the same printed deadline of the
    terrain it keeps. The round countdown is cleared and the owner-turn clock put on the zone's own record, the way zones.create
    reads the same printed duration; the sweep that removes it is combat/ext/effect_durations.py's turn_end hook. A patch whose
    owner no longer exists is left alone (nothing would sweep it), and so is one the Glass Domain has already tied to itself:
    "Shattered Glass Terrain you create inside the Domain lasts until the Domain ends" is the longer printed lifetime, so a
    tied patch keeps it and this one must not stamp an owner-turn clock over the top. The tie is asked for explicitly by
    zone id (glass_refraction.domain_terrain) because terrain written inside another event never reaches the Domain's own
    ZONE_CREATED handler."""
    from .glass_refraction import DOMAIN_LINK

    zone = engine.state.zones.get(str(zone_id))
    if zone is None or not zone.active or zone.trigger_profile.get(DOMAIN_LINK):
        return
    owner = engine.state.actors.get(str(zone.owner_id or ""))
    if owner is None:
        return
    profile = {**zone.trigger_profile, "end_after_owner_turn": int(owner.turns_started) + 1}
    kept = zone.model_copy(update={"duration_rounds": None, "trigger_profile": profile})
    engine.state.zones[zone.zone_id] = kept
    engine._append_event("ZONE_CREATED", zone.source_definition_id or source, actor_id=zone.owner_id,
                         payload={"zone": kept.model_dump(mode="json")})


# ------------------------------------------------------------------------------------------------ placing panes
def _free(engine: Any, cell: tuple[int, int]) -> bool:
    if not engine.grid.in_bounds(cell):
        return False
    if any(actor.active and (actor.position.x, actor.position.y) == cell for actor in engine.state.actors.values()):
        return False
    return not any(not obj.destroyed and (obj.position.x, obj.position.y) == cell for obj in engine.state.objects.values())


def _square(cell: tuple[int, int]) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=cell[0], y=cell[1])


def _legal(engine: Any, caster: Any, cell: tuple[int, int], feet: int) -> bool:
    """A pane square the printed text allows: unoccupied, within ``feet``, and one the user can see."""
    here = _square(cell)
    return (engine.grid.in_bounds(cell)
            and engine.grid.distance_ft(caster.position, here) <= feet
            and engine._line_of_sight_actor_to_cell(caster, here))


def _anchored(engine: Any, cell: tuple[int, int], mine: set[tuple[int, int]]) -> bool:
    """Anchored to a solid surface (a wall or closed blocking square) or to another pane, as the printed text requires."""
    if cell in mine:
        return True
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        neighbour = (cell[0] + dx, cell[1] + dy)
        if neighbour in mine or neighbour in engine.grid.blocked or not engine.grid.in_bounds(neighbour):
            return True
    return False


def standing_pane_cells(engine: Any) -> set[tuple[int, int]]:
    """The squares holding a standing Glass Pane, whoever raised it.

    The printed anchor is "a solid surface or another Glass Pane" and names no owner, so any pane already on the map anchors a
    new one -- another caster's pane as much as the same caster's. Read by the anchor test when a pane is placed, and by the
    free-standing pane's own "unless it becomes anchored before then" check."""
    return {(obj.position.x, obj.position.y) for obj in engine.state.objects.values()
            if is_pane(obj) and not obj.destroyed}


def anchored_now(engine: Any, obj: Any) -> bool:
    """Whether a standing pane touches a wall, the map's edge or another Glass Pane.

    Pane-Step Projection: "The pane collapses at the end of your next turn unless it becomes anchored before then", so the
    anchor is re-read at that deadline instead of being frozen at the moment the pane rose. The printed anchor names no owner,
    so every standing pane counts, not only this owner's."""
    cell = (obj.position.x, obj.position.y)
    return _anchored(engine, cell, standing_pane_cells(engine) - {cell})


def _pane_count(row: dict[str, Any], cl: int) -> int:
    """The printed CL table ("At CL 5, create two connected panes...") as ``count_by_cl``."""
    for band in row.get("count_by_cl") or []:
        low, high, count = (int(band[0]), int(band[1]), int(band[2]))
        if low <= cl <= high:
            return count
    return max(1, int(row.get("count") or 1))


def _beside(engine: Any, caster: Any, feet: int) -> list[tuple[int, int]]:
    """The free squares within ``feet`` of the user, nearest first (a projected pane's own square is theirs)."""
    from ..gate2_runtime_models import Position
    from .needle import free_cells

    mine = (caster.position.x, caster.position.y)
    cells = [(int(cell.x), int(cell.y)) for cell in free_cells(engine, caster, feet)
             if (int(cell.x), int(cell.y)) != mine and _free(engine, (int(cell.x), int(cell.y)))]
    return sorted(cells, key=lambda cell: (engine.grid.distance_ft(caster.position, Position(x=cell[0], y=cell[1])), cell[1], cell[0]))


def _pane_step(engine: Any, caster: Any) -> bool:
    """Whether this user compiled Pane-Step Projection (feature block row "pane_step")."""
    return any(row.get("block") == BLOCK and row.get("kind") == "pane_step"
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(caster.entity_id, []))


def _asks(engine: Any, caster: Any, aimed: Any, within_ft: int) -> bool:
    """Ask whether to trade the anchor for a pane within reach of the user.

    The printed rule is the player's ("you may create it within 10 feet of you"), so an Ask me owner is asked and may
    decline; an AI owner that does not answer keeps the printed aim, because the printed anchor is what the rule wants."""
    from .needle import CHOICE, ask, checkpoint_id

    return bool(ask(engine, getattr(engine, "_active_intent", None),
                    checkpoint_id(engine, "PANE_STEP", caster.entity_id, int(getattr(aimed, "x", 0)), int(getattr(aimed, "y", 0))),
                    caster, CHOICE + "glass_pane_step", ["near"], preferred=["near"], name="Pane-Step Projection",
                    feature_id="TAL_GLASS_PANE_STEP_PROJECTION",
                    labels={"near": f"Raise the pane within {within_ft} feet of you, anchored to nothing; it collapses at the "
                                    f"end of your next turn unless something anchors it first"},
                    allow_decline=True, default="decline",
                    prompt=f"Pane-Step Projection: raise the pane within {within_ft} feet of you, anchored to nothing, instead "
                           f"of in the square you aimed at?"))


def _offer_square(engine: Any, caster: Any, cells: list[tuple[int, int]], feet: int) -> Any | None:
    """The player's own choice of the square a free-standing pane rises in, among the legal ones (``cells``), or None."""
    from ..gate2_runtime_models import Position
    from .needle import cell_options, position_of
    from .rider_choices import pick

    if not cells:
        return None
    options, labels = cell_options(engine, caster, {Position(x=x, y=y): engine.grid.distance_ft(caster.position, Position(x=x, y=y))
                                                     for x, y in cells})
    chosen = pick(engine, caster, "glass_pane_square", "Pane-Step Projection", options, labels=labels,
                  preferred=[options[0]], subject=caster,
                  trigger=f"a Glass Pane within {feet} feet of you, anchored to nothing", optional=True)
    return position_of(chosen[0]) if chosen else None


def _step(caster: Any, first: Any) -> tuple[int, int]:
    """The face-to-face direction from the user through the aimed square ("away" from them, as a projection travels)."""
    dx, dy = int(first.x) - caster.position.x, int(first.y) - caster.position.y
    if abs(dx) >= abs(dy):
        return ((1 if dx > 0 else -1 if dx < 0 else 1), 0)
    return (0, (1 if dy > 0 else -1))


def _chain(caster: Any, first: Any, wanted: int, step: tuple[int, int]) -> list[tuple[int, int]]:
    """The aimed square, then the squares continuing edge-to-edge in one straight line.

    One square at a time, so each pane touches the pane before it ("connected panes"); a step is one of the four face-to-face
    directions, never a diagonal (two panes that share only a corner are not connected)."""
    cells: list[tuple[int, int]] = [(int(first.x), int(first.y))]
    while len(cells) < max(1, int(wanted)):
        cells.append((cells[-1][0] + step[0], cells[-1][1] + step[1]))
    return cells


def _cells(engine: Any, caster: Any, first: Any, wanted: int, feet: int) -> tuple[list[tuple[int, int]], tuple[int, int] | None]:
    """The panes that may rise, and the first square of the chain that may not.

    "In an unoccupied space you can see within range" is checked for every square, not only the aimed one; the chain stops
    there, because a later pane could not touch the one before it. The chain runs away from the user where the map allows it
    and back toward them where it does not, so a pane aimed at the edge of the arena still gets its connected companions."""
    best: list[tuple[int, int]] = []
    refused: tuple[int, int] | None = None
    away = _step(caster, first)
    for step in (away, (-away[0], -away[1])):
        cells: list[tuple[int, int]] = []
        blocked: tuple[int, int] | None = None
        for cell in _chain(caster, first, wanted, step):
            if not _free(engine, cell) or not _legal(engine, caster, cell, feet):
                blocked = cell
                break
            cells.append(cell)
        if len(cells) > len(best):
            best, refused = cells, blocked
    return best, refused


def _refusal(engine: Any, caster: Any, cell: tuple[int, int] | None, feet: int) -> str:
    """Which part of "an unoccupied space you can see within range" the refused square fails, in plain words."""
    if cell is None:
        return "that space is off the map"
    if not engine.grid.in_bounds(cell):
        return "that space is off the map"
    if not _free(engine, cell):
        return "a creature or a pane is already in that space"
    if engine.grid.distance_ft(caster.position, _square(cell)) > feet:
        return f"that space is further away than the {feet} feet you can reach"
    return "you cannot see that space"


@effect("glass_pane")
def glass_pane(ctx: Any, row: dict[str, Any]) -> None:
    """One typed row per Glass pane-creating record; ``row`` carries the printed numbers (see the module docstring)."""
    from . import bound_objects
    from ..gate2_runtime_models import Position, RuntimeObjectState

    engine, caster = ctx.engine, ctx.actor
    numbers = dict(ctx.numbers)
    first = getattr(ctx.intent, "destination", None)
    if first is None:
        targets = [target for target in getattr(ctx, "targets", None) or [] if target is not None]
        first = targets[0].position if targets else caster.position
    feet = int(getattr(ctx.action, "range_ft", 0) or 0) or DEFAULT_RANGE_FT
    unanchored = False
    if _pane_step(engine, caster) and _asks(engine, caster, first, PANE_STEP_FEET):
        # Pane-Step Projection: "you may create it within 10 feet of you without anchoring it to a solid surface".
        # Asked, because it trades the anchor for reach; the square is then the player's to choose.
        unanchored = True
        picked = _offer_square(engine, caster, [cell for cell in _beside(engine, caster, PANE_STEP_FEET)
                                                if _legal(engine, caster, cell, PANE_STEP_FEET)], PANE_STEP_FEET)
        if picked is None:
            note(engine, ctx.source, caster, "No pane rises: there is no free square within 10 feet of you for it to stand in.")
            return
        first = picked
    reach = PANE_STEP_FEET if unanchored else feet      # a free-standing pane may only stand within 10 feet
    cells, refused = _cells(engine, caster, first, _pane_count(row, int(numbers.get("cl") or 1)), reach)
    # "must be anchored to a solid surface or another Glass Pane": the printed line names no owner, so every pane already
    # standing anchors this one. The first pane of a chain may not lean on its own companions (they rise with it), only on
    # the map or on a pane that was already there.
    standing = standing_pane_cells(engine)
    if not unanchored and cells and not _anchored(engine, cells[0], standing):
        note(engine, ctx.source, caster,
             "No pane rises: it must be anchored to a solid surface or another Glass Pane, and there is nothing beside that "
             "square to anchor it to. Pane-Step Projection would let one stand within 10 feet of you instead.")
        return
    if not cells:
        note(engine, ctx.source, caster, f"No pane rises: {_refusal(engine, caster, refused, reach)}.")
        return
    ac = bound_objects.formula(row.get("ac") or "12+pb", numbers) or 12
    hp = bound_objects.formula(row.get("hp") or "5*cl", numbers) or 5
    immune = tuple(sorted({"POISON", "PSYCHIC", *{str(kind).upper() for kind in row.get("immune") or []}}))
    vulnerable = sorted({str(kind).upper() for kind in row.get("vulnerable") or []})
    # "Concentration, up to 1 minute": the pane carries both clocks as names the engine already removes, and the copy that
    # made it, so ending that copy (or the minute running out) takes the pane with it.
    from . import effect_durations

    deadline = effect_durations.round_token(engine, ONE_MINUTE_ROUNDS)
    copy_start = int(getattr(caster.concentration, "started_sequence", 0) or 0) \
        if str(getattr(caster.concentration, "source_definition_id", "") or "") == ctx.source else 0
    made = []
    for index, (x, y) in enumerate(cells):
        anchored = _anchored(engine, (x, y), standing | set(cells[:index]))
        # a pane anchored to nothing carries the collapse deadline ("unless it becomes anchored before then")
        collapse = "" if anchored else effect_durations.token("end", caster.entity_id, int(caster.turns_started) + 1)
        object_id = f"object:{KEY}.{caster.entity_id}:{engine.state.event_sequence + 1 + index}"
        obj = RuntimeObjectState(object_id=object_id, object_kind="GLASS_PANE", position=Position(x=x, y=y), unattended=True,
                                 flammable=False, ac=int(ac), current_hp=int(hp), maximum_hp=int(hp), damage_immunities=immune,
                                 damage_threshold=None, destroyed=False,
                                 component={"name": "Glass Pane", "material": "glass", "size": "medium", "blocks": False,
                                            "structure": False, "resilient": False, "artifact": False, "kind": KEY,
                                            "vulnerable": vulnerable, "resist": [], OWNER_KEY: caster.entity_id,
                                            "source": ctx.source, "anchored": 1 if anchored else 0,
                                            "deadline": deadline, "collapse": collapse, "copy_start": copy_start})
        engine._update_object(obj, ctx.source, caster.entity_id)
        made.append((obj, anchored))
    _note_placed(engine, ctx, caster, made, refused)


def _note_placed(engine: Any, ctx: Any, caster: Any, made: list[tuple[Any, bool]], refused: Any) -> None:
    ac, hp = made[0][0].ac, made[0][0].maximum_hp
    loose = [obj for obj, anchored in made if not anchored]
    if loose:
        ending = ("That one is anchored to nothing, so it collapses at the end of your next turn unless something anchors it first."
                  if len(loose) == 1 else f"{len(loose)} of them are anchored to nothing, so those collapse at the end of your "
                                          f"next turn unless something anchors them first.")
    else:
        ending = "Each is anchored to a solid surface or another pane."
    short = (f" Only {len(made)} of them fit: the rest of the line has no square you can use." if refused is not None else "")
    squares = ", ".join(f"{obj.position.x},{obj.position.y}" for obj, _a in made)
    note(engine, ctx.source, caster,
         f"Glass Pane: {len(made)} transparent pane{'s' if len(made) > 1 else ''} at {squares} (AC {ac}, {hp} hit points, "
         f"immune to Poison and Psychic damage{', vulnerable to Thunder damage' if made[0][0].component.get('vulnerable') else ''}); "
         f"{ending}{short} They last up to 1 minute, and go if you stop concentrating on them.",
         targets=[obj.object_id for obj, _a in made])


# ------------------------------------------------------------------------------------------------ aiming a pane
@hook("compile_action")
def aim_at_any_square(action: Any, info: dict[str, Any]) -> Any | None:
    """A pane-creating ability is aimed at any square in range and sight (gate4_engine's any_cell candidates)."""
    import copy

    typed = (action.parameters or {}).get("typed") or {}
    if not any(isinstance(row, dict) and row.get("type") == "glass_pane" for row in typed.get("effects") or []):
        return None
    params = copy.deepcopy(action.parameters)
    params["any_cell"] = True
    return action.model_copy(update={"parameters": params, "target_kind": "CELL", "radius_ft": 0})


@hook("candidate_allowed")
def only_an_unoccupied_square(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Raised Pane Scripture places a pane in an unoccupied square you can see within range."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if not any(isinstance(row, dict) and row.get("type") == "glass_pane" for row in typed.get("effects") or []):
        return None
    cell = getattr(candidate, "destination", None)
    return None if cell is None or _free(engine, (cell.x, cell.y)) else False


# ------------------------------------------------------------------------------------------------ panes ending and breaking
@hook("event")
def pane_lifecycle(engine: Any, event_type: str, kwargs: Any) -> None:
    """A broken pane leaves Shattered Glass Terrain; a pane whose Concentration, minute or free-standing deadline ran out goes."""
    if event_type == "OBJECT_UPDATED":
        _shatter(engine, kwargs)
    elif event_type == "CONCENTRATION_ENDED":
        _concentration_end(engine, kwargs)
    elif event_type in ("TURN_STARTED", "TURN_ENDED"):
        _expiry(engine, ending_id=str(kwargs.get("actor_id") or "") if event_type == "TURN_ENDED" else None)


def _concentration_end(engine: Any, kwargs: Any) -> None:
    """The pane ends with the Concentration copy that made it ("Duration: Concentration, up to 1 minute")."""
    owner = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if owner is None:
        return
    payload = kwargs.get("payload") or {}
    ending = payload.get("started_sequence")
    source = str(kwargs.get("source_definition_id") or "")
    gone = []
    for obj in list(engine.state.objects.values()):
        component = obj.component or {}
        if not is_pane(obj) or obj.destroyed or owner_id(obj) != owner.entity_id:
            continue
        copy_start = int(component.get("copy_start") or 0)
        if copy_start:
            # more than one copy of the technique can be held; only this copy's own panes leave with it
            if ending is not None and copy_start != int(ending):
                continue
        elif str(component.get("source") or "") != source:
            continue
        _retire(engine, obj)
        gone.append(obj)
    if gone:
        note(engine, source or f"passive:{KEY}", owner,
             f"Your Concentration ends, so {'all ' if len(gone) > 1 else ''}the Glass Pane{'' if len(gone) > 1 else ''}"
             f"{'s go' if len(gone) > 1 else ' goes'} with it.")


def _expiry(engine: Any, *, ending_id: str | None = None, actor: Any = None, checkpoint: str | None = None) -> None:
    """The two clocks a pane carries: the end of its owner's next turn (free-standing panes only) and its one minute."""
    from . import effect_durations

    for obj in list(engine.state.objects.values()):
        if not is_pane(obj) or obj.destroyed:
            continue
        component = obj.component or {}
        owner = engine.state.actors.get(owner_id(obj))
        storage = owner.turn_flags if owner is not None else {}
        collapse = str(component.get("collapse") or "")
        if collapse and effect_durations.stored_token_due(engine, collapse, storage, obj.object_id + ":collapse",
                actor=actor, checkpoint=checkpoint, ending_id=ending_id):
            if anchored_now(engine, obj):
                # "unless it becomes anchored before then": it has, so the collapse name is spent and the pane stands.
                kept = obj.model_copy(update={"component": {**component, "collapse": ""}})
                engine.state.objects[obj.object_id] = kept
                engine._update_object(kept, str(component.get("source") or f"passive:{KEY}"), owner_id(obj) or None)
                note(engine, str(component.get("source") or f"passive:{KEY}"), engine.state.actors.get(owner_id(obj)),
                     "The Glass Pane has become anchored, so it no longer collapses at the end of your next turn.")
                continue
            _retire(engine, obj)
            note(engine, str(component.get("source") or f"passive:{KEY}"), engine.state.actors.get(owner_id(obj)),
                 "The unanchored Glass Pane collapses at the end of your next turn.")
            continue
        deadline = str(component.get("deadline") or "")
        if deadline and effect_durations.stored_token_due(engine, deadline, storage, obj.object_id + ":deadline",
                actor=actor, checkpoint=checkpoint, ending_id=ending_id):
            _retire(engine, obj)
            note(engine, str(component.get("source") or f"passive:{KEY}"), engine.state.actors.get(owner_id(obj)),
                 "The Glass Pane fades: Raised Pane Scripture lasts up to 1 minute.")


@hook("nominal_slot_boundary")
def nominal_panes(engine: Any, actor: Any, checkpoint: str) -> None:
    _expiry(engine, actor=actor, checkpoint=checkpoint)


def retiring(engine: Any) -> bool:
    """Whether the pane being recorded right now is retiring rather than breaking (see ``_retire``).

    Read by the two handlers that answer an OBJECT_UPDATED (this module's own shatter and Clean Break). A retirement
    flag on the engine's own instance dictionary is the same re-entrancy guard ``_shatter`` already uses for its
    terrain, and it is set only while this module writes the record, so nothing outside the plug-in can see it."""
    return bool(engine.__dict__.get(_RETIRING))


def _retire(engine: Any, obj: Any) -> None:
    """Take a standing pane off the map without its recorded end reading as a break.

    The only printed break trigger is "When reduced to 0 HP, the pane shatters and creates Shattered Glass Terrain
    in its space", so a pane whose Concentration, one-minute deadline or free-standing collapse ran out must not
    leave terrain and must not offer Clean Break's answers: its printed duration ending is not a blow. The flag is
    raised for the duration of the write, and both readers of the event (see ``retiring``) skip it. The pane's own
    record still reads ``current_hp`` 0 and ``destroyed``, so a reloaded fight sees the same pane gone."""
    component = obj.component or {}
    engine.__dict__[_RETIRING] = True
    try:
        engine._update_object(obj.model_copy(update={"destroyed": True, "current_hp": 0}),
                              str(component.get("source") or f"passive:{KEY}"), owner_id(obj) or None)
    finally:
        engine.__dict__[_RETIRING] = False


def _shatter(engine: Any, kwargs: Any) -> None:
    payload = kwargs.get("payload") or {}
    object_id = next(iter(kwargs.get("target_ids") or ()), "")
    obj = pane_of(engine, object_id)   # the record the break already wrote (its own destroyed flag is the news)
    if obj is None or not (payload.get("object") or {}).get("destroyed"):
        return
    if engine.__dict__.get("_glass_shattering") or retiring(engine):
        # a pane whose printed duration ran out leaves the map through _retire, which is not the printed trigger
        # ("when reduced to 0 HP"), so it makes no terrain
        return
    engine.__dict__["_glass_shattering"] = True
    try:
        from .. import typed_executor

        component = obj.component or {}
        owner = engine.state.actors.get(owner_id(obj))
        source = str(component.get("source") or f"passive:{KEY}")
        if owner is not None and owner.active:
            ctx = typed_executor.Context(engine, owner, engine.action_catalog.get(source), getattr(engine, "_active_intent", None),
                                         {"numbers": {}, "source": source, "effects": [], "riders": []}, [], owner)
            before = set(engine.state.zones)
            typed_executor.run_effects(ctx, [{"type": "terrain_patch", "terrain": TERRAIN, "name": "Shattered Glass Terrain",
                                              "duration": None,
                                              "center": {"x": obj.position.x, "y": obj.position.y},
                                              "evidence": "the pane shatters and creates Shattered Glass Terrain in its space"}])
            # "until the end of your next turn": the patch's own owner-turn clock, not a round count (owner_turn_terrain).
            # The Glass Domain's "Shattered Glass Terrain you create inside the Domain lasts until the Domain ends" is the
            # longer printed lifetime, and this patch is written while another event is being handled, so the tie is asked
            # for by zone id: a tied patch is then left alone by owner_turn_terrain.
            from . import glass_refraction

            tied = False
            for zone_id in [key for key in engine.state.zones if key not in before]:
                tied = glass_refraction.domain_terrain(engine, zone_id) or tied
                owner_turn_terrain(engine, zone_id, source)
            # the line says the lifetime this patch actually got, read from the tie that was just made rather than
            # assumed: a patch the Glass Domain tied lasts until that Domain ends, every other patch lasts until the
            # end of the owner's next turn
            note(engine, source, owner,
                 "The Glass Pane shatters: Shattered Glass Terrain fills its square "
                 + ("until your Glass Domain ends." if tied else "until the end of your next turn."))
    finally:
        engine.__dict__["_glass_shattering"] = False


# ------------------------------------------------------------------------------------------------ Clean Break
BLOCK = "lane9_glass"
CLEAN_BREAK = "TAL_GLASS_CLEAN_BREAK"
NEAR_SQUARES = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def clean_break_owners(engine: Any) -> list[Any]:
    return [actor for actor in engine.state.actors.values()
            if actor.active and any(row.get("block") == BLOCK and row.get("kind") == "clean_break"
                                    for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))]


def _broke_through(engine: Any, kwargs: Any) -> Any | None:
    """The object this event destroyed, when a Glass fighter's own blow reduced it to 0 hit points."""
    payload = kwargs.get("payload") or {}
    if not (payload.get("object") or {}).get("destroyed"):
        return None
    if retiring(engine):
        # a pane that retired (Concentration, minute or collapse ran out) was not reduced to 0 HP by this blow, so
        # the printed Clean Break trigger is not met
        return None
    object_id = next(iter(kwargs.get("target_ids") or ()), "")
    obj = engine.state.objects.get(str(object_id))
    breaker = kwargs.get("actor_id")
    if obj is None or not breaker:
        return None
    from .. import object_rules

    glassy = is_pane(obj) or object_rules.has_tag(obj, "fragile")
    return obj if glassy else None


@hook("event")
def clean_break(engine: Any, event_type: str, kwargs: Any) -> None:
    """Clean Break: the three printed answers for the glass thing this blow destroyed."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = _broke_through(engine, kwargs)
    if obj is None:
        return
    for breaker in clean_break_owners(engine):
        if str(kwargs.get("actor_id") or "") != breaker.entity_id:
            continue
        answers(engine, breaker, obj, CLEAN_BREAK)


def answers(engine: Any, breaker: Any, obj: Any, source: str) -> None:
    """Choose one of Clean Break's three answers for the broken object.

    Each answer keeps its own legal list (the printed text restricts each one differently), and a list that is empty takes its
    answer out of the menu rather than offering one that would do nothing. Asked; the AI takes the first legal one."""
    from .. import object_rules
    from .glass_refraction import give_mark, marked
    from .needle import position_of
    from .rider_choices import pick

    name = object_rules.label(obj)
    in_reach = [actor for actor in engine.state.actors.values()
                if actor.active and actor.entity_id != breaker.entity_id
                and engine.grid.distance_ft(obj.position, actor.position) <= engine.grid.square_size_ft]
    markable = [actor for actor in in_reach if not marked(actor, breaker.entity_id)]
    # "one creature that saw it break": line of sight to the thing that broke, at any distance
    from ..gate2_runtime_models import Position

    watchers = [actor for actor in engine.state.actors.values()
                if actor.active and actor.entity_id != breaker.entity_id
                and engine._line_of_sight_actor_to_cell(actor, Position(x=obj.position.x, y=obj.position.y))]
    squares = sorted((obj.position.x + dx, obj.position.y + dy) for dx, dy in NEAR_SQUARES if engine.grid.in_bounds(
        (obj.position.x + dx, obj.position.y + dy)))
    choices = []
    if markable:
        choices.append("mark")
    if squares:
        choices.append("terrain")
    if watchers:
        choices.append("step")
    if not choices:
        return
    labels = {"mark": f"Place a Faultline Mark on one creature within 5 feet of {name}",
              "terrain": f"Create Shattered Glass Terrain in one 5-foot square next to {name}",
              "step": "Move 5 feet without provoking Opportunity Attacks from one creature that saw it break"}
    chosen = pick(engine, breaker, "glass_clean_break", "Clean Break", choices, labels=labels,
                  preferred=[next(option for option in ("terrain", "mark", "step") if option in choices)],
                  subject=breaker, trigger=f"{breaker.display_name} breaks {name}", optional=True)
    if not chosen:
        return
    answer = chosen[0]
    if answer == "mark":
        subject = _creature(engine, breaker, markable, "glass_clean_break_mark")
        if subject is not None:
            # "one creature": the printed line names no side, so the mark lands on whoever the player chose.
            give_mark(engine, breaker, subject, source, any_side=True)
        return
    if answer == "terrain":
        from .. import typed_executor
        from ..gate2_runtime_models import Position
        from .needle import cell_options

        options, cell_labels = cell_options(engine, breaker, {Position(x=x, y=y): engine.grid.square_size_ft for x, y in squares})
        picked = pick(engine, breaker, "glass_clean_break_square", "Clean Break", options, labels=cell_labels,
                      preferred=[options[0]], subject=breaker, trigger=f"Shattered Glass Terrain next to {name}",
                      optional=True)
        if not picked:
            return
        action = _action_for(engine, breaker, source)
        # the patch's own "center" names the square, so the recipient is the user (terrain_patch reads their footprint)
        ctx = typed_executor.Context(engine, breaker, action, getattr(engine, "_active_intent", None),
                                     {"numbers": {}, "source": source, "effects": [], "riders": []}, [], breaker,
                                     effect_source=source)
        before = set(engine.state.zones)
        typed_executor.run_effects(ctx, [{"type": "terrain_patch", "terrain": TERRAIN, "name": "Shattered Glass Terrain",
                                          "duration": {"kind": "rounds", "amount": 2},
                                          "center": {"x": position_of(picked[0]).x, "y": position_of(picked[0]).y},
                                          "evidence": "create Shattered Glass Terrain in one 5-foot square adjacent to it"}])
        # the Glass Domain's "Shattered Glass Terrain you create inside the Domain lasts until the Domain ends" outranks
        # this answer's own two rounds, and this patch is written inside another event, so the tie is asked for by zone id
        from . import glass_refraction

        for zone_id in [key for key in engine.state.zones if key not in before]:
            glass_refraction.domain_terrain(engine, zone_id)
        return
    # the 5-foot step that provokes no Opportunity Attack from one creature that saw it break
    from .rider_choices import step

    watcher = _creature(engine, breaker, watchers, "glass_clean_break_watcher")
    step(engine, breaker, "glass_clean_break_step", "Clean Break", watcher or breaker, 5, source,
         trigger=f"{breaker.display_name} breaks {name}: move 5 feet without provoking that creature's Opportunity Attack",
         ignored_oa=[watcher.entity_id] if watcher is not None else None)


def _action_for(engine: Any, actor: Any, feature_id: str) -> Any:
    """The catalog action a ``feature_id`` belongs to (its ids carry the ability name), or None."""
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == getattr(actor, "entity_id", actor) and str(typed.get("source") or "") == feature_id:
            return action
    return engine.action_catalog.get(feature_id)


def _creature(engine: Any, breaker: Any, creatures: list[Any], key: str) -> Any | None:
    """Which of ``creatures`` this answer affects (asked; the AI takes the first)."""
    from .rider_choices import pick

    if not creatures:
        return None
    options = [actor.entity_id for actor in creatures]
    labels = {actor.entity_id: actor.display_name for actor in creatures}
    chosen = pick(engine, breaker, key, "Clean Break", options, labels=labels, preferred=[options[0]],
                  subject=creatures[0], trigger="the creature it affects", optional=False)
    return engine.state.actors.get((chosen or [options[0]])[0])
