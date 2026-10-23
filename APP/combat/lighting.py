"""Light on the fight map: one level per cell, and one resolved level per viewer.

Owner FD-19 ("i would like to add lighting into the game though", "rules and visuals together, ai should be using
darkness if it is part of the dao of the user"). The contract is docs/specs/LIGHTING_SPEC.md; this module is its S1
slice: the model, and the queries every other seam asks.

Three levels, in the engine's own words (combat/status_text.py), so the table never explains two kinds of dim:

    BRIGHT 2   no obscurement; nothing changes
    DIM    1   Lightly Obscured; Disadvantage on sight Perception checks, and nothing else (attacks unchanged)
    DARK   0   Heavily Obscured; the square cannot be seen into, so the unseen-target / unseen-attacker modifiers
               apply (combat/zones.py attack_modes) and no sight target is legal (combat/senses.py perceives)

Resolution order (spec §4.1), exactly as written:

    1. sources()      every contributing source: map lights, ambient regions, carried lights, area lights, plug-ins
    2. field()        for each source, Bright inside bright_ft and Dim inside dim_ft of its own squares, marked only
                      through sight-clear rays (combat/sight_lines.py clear) -- light does not pass a wall
    3. field()        the maximum per cell; the ambient level is the floor, an ambient region paints over it
    4. seen_level()   an area that is heavily obscured or magically dark caps the square at Dark, unless a printed
                      area rule (the darkness_lifted hook) says this viewer still sees through it
    5. seen_level()   then Darkvision raises Dark to Dim and Dim to Bright within its own reach
    6.                non-visual senses never change a level; they let the viewer act anyway (combat/senses.py)
    7.                each caller turns the level into its consequence: Bright nothing, Dim Lightly Obscured, Dark
                      Heavily Obscured

Step 4 before step 5 is deliberate: darkness beats light, and darkvision beats ordinary darkness.

Nothing here is saved. The map's lights and ambient live in the arena document the match already copies
(tabletop.lights / tabletop.ambient), a carried light lives in the condition "condition:typed.light", an area's light
lives in that area's trigger_profile.visual.light (spec §3). A fight whose map declares no light and whose creatures
carry none answers BRIGHT everywhere, so every existing save and replay behaves exactly as it did.

Every read here is pure: no events, no state, no mutation. Answers are shared inside a read-only frame through
combat/read_queries.shared_query and die with the next recorded change (spec §6.1); nothing is cached on the engine,
so an unrecorded edit (an editor session, a GM toggle written straight to the document) is seen by the next pass.

Public surface (spec §4):

    LightSource                            one light: its squares, its radii, or its painted level
    sources(engine)                        every answer to "what glows", in one stable order
    ambient(engine)                        time_of_day, the level it gives, and the indoor level when declared
    declared(engine)                       False lets every caller keep today's code path end to end
    field(engine)                          the viewer-independent base field, (x, y) -> level
    base(engine, x, y)                     one square of it, ambient floor included
    seen_level(engine, viewer, position)   the resolved level for one viewer; everything else asks this
    seen_field(engine, viewer)             the whole field for one viewer (the table's payload)
    heavily_obscured / dim / obscured      level Dark / level Dim / anything but Bright, for one viewer
    attack_modes(engine, viewer, target)   the uncancelled light contributions to one attack
    perception_mode(engine, actor)         the mode of a sight Perception check from where the actor stands
    own_light(engine, viewer)              the lights the creature itself carries (its sheet; S4's knowledge frame)
    summary(engine, viewer)                the compact 2-bit per-viewer payload of spec §7.1
    level_name(level), radii(row)          small shared conversions for callers and the editor

The one hook this slice adds is "light_sources" (documented in combat/ext/__init__.py): a plug-in may return further
LightSource rows, and returning None adds nothing, which is the default-inert answer every saved fight already has.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from typing import Any, Iterable, NamedTuple

from .read_queries import pure

#: The three light levels (spec §2.2).
BRIGHT, DIM, DARK = 2, 1, 0
LEVELS = {"bright": BRIGHT, "dim": DIM, "dark": DARK}
NAMES = {BRIGHT: "bright", DIM: "dim", DARK: "dark"}
#: Time of day is a setting, not a clock (spec §2.9): a fight lasts a minute and the sky does not move.
TIME_OF_DAY = {"day": BRIGHT, "dawn": DIM, "dusk": DIM, "night": DARK, "underground": DARK}
#: Where a carried or worn light lives (spec §3.4): a condition already saves, expires, and shows on the sheet.
LIGHT = "condition:typed.light"
SCHEMA = "TianxiaTabletopLight.v1"


class _Point(NamedTuple):
    """A square for the occluder ray to read (x, y, z); Position validates far more than sight_lines.clear uses."""

    x: int
    y: int
    z: int


@dataclass(frozen=True)
class LightSource:
    """One light: the squares it starts from, and what it gives the squares around them.

    "level" paints the source's own squares with a level (an ambient region, an indoor floor) and needs no radius.
    Otherwise the source gives BRIGHT inside bright_ft and DIM inside dim_ft of each of its squares; dim_ft is the
    outer radius, and a printed bright-only radius is dim_ft == bright_ft (spec §2.3).

    "following" names the creature whose footprint the cells are, when the source rides a creature. "magical" is
    recorded because ordinary light must never lift an area of darkness (spec §2.7), not because it changes the
    arithmetic (spec §2.4).
    """

    entity_id: str
    name: str
    cells: frozenset[tuple[int, int]]
    bright_ft: int = 0
    dim_ft: int = 0
    color: str | None = None
    magical: bool = False
    level: int | None = None
    following: str | None = None

    def __post_init__(self) -> None:
        if type(self.bright_ft) is not int or type(self.dim_ft) is not int:
            raise ValueError("a light's radii are whole feet (spec §2.3)")
        if self.bright_ft < 0 or self.dim_ft < self.bright_ft:
            raise ValueError("a light's dim radius is its outer radius: dim_ft >= bright_ft >= 0 (spec §2.3)")
        if self.level is not None and self.level not in (BRIGHT, DIM, DARK):
            raise ValueError("a painted light level is 0, 1 or 2 (spec §2.2)")


def level_name(level: int) -> str:
    """The stored name of a level: 'bright', 'dim' or 'dark'."""
    return NAMES.get(level, "bright")


def radii(row: dict[str, Any]) -> tuple[int, int]:
    """A stored source's (bright, dim) radii; the new keys win and today's shape is read as legacy (spec §3.5).

    {"radius_ft": R, "level": "bright"} means bright R / dim R; "level": "dim" means bright 0 / dim R. A row with
    neither shape emits nothing rather than guessing a radius from prose (that guessing is what S3 replaces).
    """
    bright, dim = _feet(row.get("bright_ft")), _feet(row.get("dim_ft"))
    if bright is not None or dim is not None:
        bright = 0 if bright is None else bright
        dim = bright if dim is None else dim
        return bright, max(bright, dim)
    radius = _feet(row.get("radius_ft"))
    if radius is None:
        return 0, 0
    return (0, radius) if _level(row.get("level")) == DIM else (radius, radius)


# --------------------------------------------------------------------------------------------- what the map declares
def _document(engine: Any) -> dict[str, Any]:
    """The arena document this fight was started from (combat/gate3_storage.py ARENA_FILE)."""
    document = getattr(engine, "battlefield_document", None)
    return document if isinstance(document, dict) else {}


def _tabletop(engine: Any) -> dict[str, Any]:
    """The map's own rules/presentation section: ambient, ambient_regions, lights, walls, roofs."""
    tabletop = _document(engine).get("tabletop")
    return tabletop if isinstance(tabletop, dict) else {}


def _square(engine: Any) -> int:
    return int(getattr(getattr(engine, "grid", None), "square_size_ft", 5) or 5)


def _level(value: Any) -> int | None:
    """A stored level -- an integer 0-2 or its name; anything else is absent, never a guess."""
    if type(value) is int and value in LEVELS.values():
        return value
    return LEVELS.get(str(value or "").strip().lower())


def _feet(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _color(value: Any) -> str | None:
    return value[:20] if isinstance(value, str) and value else None


def _cells(values: Any) -> list[tuple[int, int]]:
    """Map squares from stored pairs, ignoring anything that is not a square (an editor may be mid-write)."""
    out: list[tuple[int, int]] = []
    for value in values or ():
        try:
            out.append((int(value[0]), int(value[1])))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return out


@pure
def ambient(engine: Any) -> dict[str, Any]:
    """The map's ambient light: time_of_day, the level it gives (explicit first, derived otherwise), and, when the
    map declares one, the level under a roof (spec §3.2). An absent ambient section is Bright (OQ-1)."""
    row = _tabletop(engine).get("ambient")
    row = row if isinstance(row, dict) else {}
    time_of_day = str(row.get("time_of_day") or "day")
    level = _level(row.get("level"))
    if level is None:
        level = TIME_OF_DAY.get(time_of_day, BRIGHT)
    return {"time_of_day": time_of_day, "level": level, "indoor_level": _level(row.get("indoor_level"))}


def declared(engine: Any) -> bool:
    """Whether anything anywhere names a light, so a map with no light data keeps today's code path end to end."""
    from .read_queries import shared_query

    tabletop = _tabletop(engine)
    if tabletop.get("ambient") or tabletop.get("lights") or tabletop.get("ambient_regions"):
        return True
    return bool(shared_query(engine, ("lighting.declared",), lambda: bool(_sources(engine))))


def sources(engine: Any) -> tuple[LightSource, ...]:
    """Every contributing source (spec §4.1 step 1), in one stable order: ambient regions, map lights, carried
    lights, area lights, then whatever a plug-in adds through the "light_sources" hook."""
    from .read_queries import shared_query

    return shared_query(engine, ("lighting.sources",), lambda: tuple(_sources(engine)))


def _sources(engine: Any) -> list[LightSource]:
    from . import ext, zones

    out: list[LightSource] = []
    tabletop = _tabletop(engine)
    for index, row in enumerate(tabletop.get("ambient_regions") or ()):
        if not isinstance(row, dict):
            continue
        cells, level = _cells(row.get("cells")), _level(row.get("level"))
        if cells and level is not None:
            out.append(LightSource(str(row.get("id") or f"ambient:{index}"), str(row.get("name") or "Ambient light"),
                                   frozenset(cells), level=level))
    for index, row in enumerate(tabletop.get("lights") or ()):
        if not isinstance(row, dict) or row.get("lit") is False:
            continue
        bright, dim = radii(row)
        cells = _cells([(row.get("x"), row.get("y"))]) or _cells(row.get("cells"))
        # OQ-3: a source lives on layer 0, so a stored z belongs to the editor and never changes this answer.
        if cells and (bright > 0 or dim > 0):
            out.append(LightSource(str(row.get("id") or f"light:{index}"), str(row.get("name") or "Light"),
                                   frozenset(cells), bright, dim, _color(row.get("color")),
                                   row.get("magical") is True))
    for actor_id in sorted(engine.state.actors):
        actor = engine.state.actors[actor_id]
        if not actor.active:
            continue
        for condition in actor.conditions.values():
            if condition.condition_id != LIGHT:
                continue
            data = condition.data or {}
            bright, dim = radii(data)
            if data.get("lit") is False or (bright <= 0 and dim <= 0):
                continue
            out.append(LightSource(str(data.get("source_id") or f"light:{actor_id}"),
                                   str(data.get("name") or "Carried light"),
                                   frozenset(engine._actor_cells(actor)), bright, dim, _color(data.get("color")),
                                   data.get("magical") is True, following=actor_id))
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        light = (profile.get("visual") or {}).get("light")
        if not isinstance(light, dict):
            continue
        bright, dim = radii(light)
        cells = frozenset((int(cell.x), int(cell.y)) for cell in zone.affected_cells)
        if cells and (bright > 0 or dim > 0):
            out.append(LightSource(f"zone:{zone.zone_id}", str(profile.get("name") or "Area light"), cells, bright,
                                   dim, _color(light.get("color")), light.get("magical") is True))
    if ext.has("light_sources"):
        for reply in ext.run("light_sources", engine):
            for source in (reply if isinstance(reply, (tuple, list, set)) else (reply,)):
                if isinstance(source, LightSource):
                    out.append(source)
    return out


# ---------------------------------------------------------------------------------------------------- the base field
# ---------------------------------------------------------------------------------------------------- the base field
@pure
def field(engine: Any) -> dict[tuple[int, int], int]:
    """The whole base field, (x, y) -> level, viewer-independent (spec §4).

    A square absent from the answer carries the ambient level, which is the floor (§2.4.4); that is also what lets a
    map with no light data answer without walking its squares.
    """
    from .read_queries import shared_query

    return shared_query(engine, ("lighting.field",), lambda: _field(engine))


@pure
def base(engine: Any, x: int, y: int) -> int:
    """This square's level before senses: the field's answer, or the map's ambient level."""
    x, y = int(x), int(y)
    width, height = int(engine.grid.width), int(engine.grid.height)
    if not (0 <= x < width and 0 <= y < height):
        return ambient(engine)["level"]
    return _base_bytes(engine)[y * width + x]


def _base_bytes(engine: Any) -> bytes:
    """The base field as one byte per square, row-major: computed once per pass and shared by every viewer (§6.1)."""
    from .read_queries import shared_query

    return shared_query(engine, ("lighting.bytes",), lambda: bytes(_paint(engine)))


def _paint(engine: Any) -> bytearray:
    """The whole base field, one byte per square (spec §4.1 steps 2-3)."""
    floor = ambient(engine)["level"]
    width, height = int(engine.grid.width), int(engine.grid.height)
    cells = bytearray([floor]) * (width * height)
    if not declared(engine):
        return cells  # no light data anywhere: every square keeps the ambient level, which is today's behaviour
    indoor = ambient(engine)["indoor_level"]
    if indoor is not None and indoor != floor:
        for x, y in _roofed_cells(engine):
            if 0 <= x < width and 0 <= y < height:
                cells[y * width + x] = indoor
    painted: list[LightSource] = []
    emitting: list[LightSource] = []
    for source in sources(engine):
        (painted if source.level is not None else emitting).append(source)
    for source in painted:  # ambient regions paint over the floor and over each other: the later region wins (§3.2)
        for x, y in source.cells:
            if 0 <= x < width and 0 <= y < height:
                cells[y * width + x] = int(source.level)
    if emitting:
        square = _square(engine)
        rays = _Rays(engine)
        done: set[tuple[Any, ...]] = set()
        for source in emitting:
            # Two lights of the same size on the same squares add up to one: composition is a maximum, never a sum,
            # so a second identical source cannot change a square and is not worth a disc (spec §2.4.3).
            key = (source.cells, source.bright_ft, source.dim_ft)
            if key in done:
                continue
            done.add(key)
            _emit(engine, source, floor, square, cells, rays)
    return cells


def _field(engine: Any) -> dict[tuple[int, int], int]:
    floor = ambient(engine)["level"]
    width, height = int(engine.grid.width), int(engine.grid.height)
    cells = _base_bytes(engine)
    return {(x, y): cells[y * width + x] for y in range(height) for x in range(width)
            if cells[y * width + x] != floor}


def _roofed_cells(engine: Any) -> set[tuple[int, int]]:
    """Squares under a sealed roof: indoor light does not reach a storeroom on a day map (spec §3.2)."""
    surfaces = getattr(getattr(engine, "grid", None), "roof_surfaces", ()) or ()
    cells: set[tuple[int, int]] = set()
    for surface in surfaces:
        open_cells = getattr(surface, "open_cells", frozenset())
        skylight_cells = getattr(surface, "skylight_cells", frozenset())
        for x, y in getattr(surface, "cells", frozenset()) or ():
            if (x, y) not in open_cells and (x, y) not in skylight_cells:
                cells.add((int(x), int(y)))
    return cells


#: Disc geometry by (dim cells, bright cells); a hundred torches share one shape, and the shape is engine-free.
_ROWS: dict[tuple[int, int], tuple[tuple[int, int, int, int, int], ...]] = {}


def _rows_for(radius: int, bright_cells: int) -> tuple[tuple[int, int, int, int, int], ...]:
    """The disc's direction rows, as (ux, uy, stride, steps, bright steps), cached by the two radii.

    Every square inside a Chebyshev disc lies on exactly one reduced direction (ux, uy), and the k-th square along it is
    k*stride cells away. That is what lets one occluder ray stand for a whole row: the segments are nested.
    """
    key = (int(radius), int(bright_cells))
    rows = _ROWS.get(key)
    if rows is not None:
        return rows
    farthest: dict[tuple[int, int], int] = {}
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            distance = max(abs(dx), abs(dy))
            if distance == 0 or distance > radius:
                continue
            step = math.gcd(abs(dx), abs(dy)) or 1
            direction = (dx // step, dy // step)
            if distance > farthest.get(direction, 0):
                farthest[direction] = distance
    built = []
    for (ux, uy), distance in sorted(farthest.items()):
        stride = max(abs(ux), abs(uy))
        steps = distance // stride
        built.append((ux, uy, stride, steps, min(steps, bright_cells // stride)))
    rows = tuple(built)
    if len(_ROWS) > 256:  # a bound on geometry kept for maps that never repeat a radius
        _ROWS.clear()
    _ROWS[key] = rows
    return rows


class _Rays:
    """Cache exact native sight answers for this light-field calculation."""

    def __init__(self, engine: Any) -> None:
        self.grid = engine.grid
        self.discs: dict[tuple[int, int, int], _Disc] = {}

    def disc(self, sx: int, sy: int, radius: int) -> _Disc:
        key = (sx, sy, radius)
        if key not in self.discs:
            self.discs[key] = _Disc(self.grid, sx, sy)
        return self.discs[key]


class _Disc:
    """A source origin's exact terrain sight queries, shared across its light rays."""

    def __init__(self, grid: Any, sx: int, sy: int) -> None:
        self.grid, self.sx, self.sy = grid, sx, sy
        self.answers: dict[tuple[int, int], bool] = {}

    def clear(self, x: int, y: int) -> bool:
        from .terrain_occlusion import crossed_cells, terrain_visible

        key = (x, y)
        if key not in self.answers:
            start, end = _Point(self.sx, self.sy, 0), _Point(x, y, 0)
            # Creature sight can target a wall's near face; light cannot pass
            # into that occupied endpoint. Keep all ray geometry in the shared
            # terrain predicate, with its exact (non-near-side) endpoint policy.
            self.answers[key] = terrain_visible(
                self.grid, start, end, list(crossed_cells(start, end)), near_endpoint=False
            )
        return self.answers[key]

    def reach(self, ux: int, uy: int, limit: int) -> int:
        """Stop at the first blocked cell; every candidate uses the shared terrain sight predicate."""
        for distance in range(1, limit + 1):
            if not self.clear(self.sx + distance * ux, self.sy + distance * uy):
                return distance - 1
        return limit


def _emit(engine: Any, source: LightSource, floor: int, square: int, cells: bytearray, rays: _Rays) -> None:
    """Mark one source's disc through sight-clear rays (spec §4.1 step 2), keeping the maximum per square (step 3)."""
    # The source's own square is lit by its printed radii, whatever the grid size: a positive bright radius lights it
    # Bright, else a positive dim radius lights it Dim. Only the reach around it is quantized to whole squares.
    own_level = BRIGHT if source.bright_ft > 0 else DIM
    radius = source.dim_ft // square
    bright_cells = source.bright_ft // square
    top = BRIGHT if bright_cells > 0 else DIM  # the brightest level this source can put on any other square
    width, height = int(engine.grid.width), int(engine.grid.height)
    rows = _rows_for(radius, bright_cells) if radius > 0 else ()
    for sx, sy in sorted(source.cells):
        if not (0 <= sx < width and 0 <= sy < height):
            continue  # a source stored off the map lights nothing
        own = sy * width + sx
        was = cells[own]
        if own_level > was:
            cells[own] = own_level  # a source's own square is its own light, not its dim ring
        if radius <= 0:
            continue  # the printed reach is under one square: only the source's own square is lit
        if was >= top and _covered(cells, sx, sy, radius, width, height, top):
            continue  # every square in reach already shines at least as bright, so this disc cannot change anything
        disc = rays.disc(sx, sy, radius)
        for ux, uy, stride, steps, bright_steps in rows:
            limit = steps
            if ux > 0:
                edge = (width - 1 - sx) // ux
                if edge < limit:
                    limit = edge
            elif ux < 0:
                edge = sx // -ux
                if edge < limit:
                    limit = edge
            if uy > 0:
                edge = (height - 1 - sy) // uy
                if edge < limit:
                    limit = edge
            elif uy < 0:
                edge = sy // -uy
                if edge < limit:
                    limit = edge
            if limit <= 0:
                continue
            reach = disc.reach(ux, uy, limit)
            if reach <= 0:
                continue
            along = uy * width + ux
            bright = bright_steps if bright_steps < reach else reach
            first = own + along
            if bright > 0 and along > 0:
                # Bright is the top level, so a slice write over a reached run never lowers a square and runs in C.
                cells[first:first + along * bright:along] = bytes((BRIGHT,)) * bright
            elif bright > 0:
                index = own
                for _ in range(bright):
                    index += along
                    if cells[index] < BRIGHT:
                        cells[index] = BRIGHT
            index = own + along * bright
            for _ in range(reach - bright):
                index += along
                if cells[index] < DIM:
                    cells[index] = DIM


def _covered(cells: bytearray, sx: int, sy: int, radius: int, width: int, height: int, top: int) -> bool:
    """Whether every square this source could reach already shines at least as bright (spec §6.3 fallback).

    A lit street piles its sources on top of each other; a disc that changes nothing is dropped whole, which is what
    keeps a crowded map cheaper than one ray per source per direction. The caller only asks when the source's own
    square is already this bright, so one scan is cheap insurance against a wasted disc.
    """
    x0, x1 = max(0, sx - radius), min(width - 1, sx + radius)
    y0, y1 = max(0, sy - radius), min(height - 1, sy + radius)
    for y in range(y0, y1 + 1):
        row = y * width
        for x in range(x0, x1 + 1):
            if cells[row + x] < top:
                return False
    return True


# --------------------------------------------------------------------------------------------- one viewer's answer
def _position_of(value: Any) -> Any:
    """A Position or a 2-D map square, which is explicitly the authored ground layer."""
    if hasattr(value, "x") and hasattr(value, "y"):
        return value
    from .gate2_runtime_models import Position

    if len(value) == 3:
        x, y, z = value
    else:
        x, y = value
        z = 0
    return Position(x=int(x), y=int(y), z=int(z))


@pure
def seen_level(engine: Any, viewer: Any, position: Any) -> int:
    """The per-viewer level of one square (spec §4): the base field, after areas and after this viewer's own senses.

    viewer is the creature whose eyes are being asked; None asks about the square alone (no Darkvision, and no
    viewer-specific suppression), which is what a caller with no creature in hand means.
    """
    from .read_queries import shared_query

    point = _position_of(position)
    # The altitude is part of the answer: Darkvision measures 3D distance to the square (_feet_to), so a flier's square
    # and the ground square under it are different questions. The viewer's own position is a projected input too.
    key = ("lighting.seen", _viewer_key(viewer), (int(point.x), int(point.y), int(point.z)))
    return shared_query(engine, key, lambda: _seen_level(engine, viewer, point),
                        refs=(viewer,) if viewer is not None else ())


def _viewer_key(viewer: Any) -> Any:
    """What identifies a viewer inside a cached answer: the creature object and the square it is projected on."""
    if viewer is None:
        return None
    where = getattr(viewer, "position", None)
    return (id(viewer), (int(where.x), int(where.y), int(where.z)) if where is not None else None)


def _seen_level(engine: Any, viewer: Any, point: Any, subject: Any = None) -> int:
    if not declared(engine):
        return BRIGHT
    level = base(engine, point.x, point.y)
    if level > DARK and _area_dark(engine, viewer, point, subject=subject):
        level = DARK  # step 4: darkness beats light, whatever the torch says (§2.7)
    if level < BRIGHT and viewer is not None:
        feet = _darkvision(engine, viewer, point)
        if feet > 0 and _feet_to(engine, viewer, point) <= feet:
            level += 1  # step 5: Darkvision raises Dark to Dim and Dim to Bright within its reach (§2.8)
    return level


def _area_dark(engine: Any, viewer: Any, point: Any, *, subject: Any = None) -> bool:
    """Step 4: whether an area of darkness or heavy obscurement takes this square from this viewer (§4.1).

    Creature concealment keeps the subject in the query so target-qualified exemptions are not lost by replacing the
    creature with an anonymous terrain probe. Scalar square queries remain subject-free.
    """
    from . import senses, zones

    if not zones.heavy_zones(engine):
        return False
    probe = subject if subject is not None else senses.cell_probe(_position_of(point))
    if viewer is None:
        return any(zones.actor_inside_zone(engine, probe, zone) for zone in zones.heavy_zones(engine))
    return zones.dark_cell(engine, viewer, probe)


def _darkvision(engine: Any, viewer: Any, point: Any) -> int:
    """How far this viewer's Darkvision reaches toward one square, Pure Darkness and Clearsight included (§2.8)."""
    from .read_queries import shared_query

    if not _pure_zones(engine):
        # With no Pure Darkness on the table the range is the creature's own, so one answer serves every square.
        return shared_query(engine, ("lighting.darkvision", id(viewer)),
                            lambda: _darkvision_range(engine, viewer), refs=(viewer,))
    from . import senses

    return int(senses.reach(engine, viewer, "darkvision", senses.cell_probe(_position_of(point))) or 0)


def _darkvision_range(engine: Any, viewer: Any) -> int:
    from . import senses

    return int(senses.reach(engine, viewer, "darkvision", viewer) or 0)


def _pure_zones(engine: Any) -> list[Any]:
    """Areas of Pure Darkness, which a plain Darkvision row does not see through at all (spec §2.8)."""
    from . import senses, zones
    from .read_queries import shared_query

    return list(shared_query(engine, ("lighting.pure",),
                             lambda: [zone for zone in zones.typed_zones(engine) if senses.pure_zone(zone)]))


def _feet_to(engine: Any, viewer: Any, point: Any) -> int:
    from . import senses

    return int(engine._distance_actor_to_actor(viewer, senses.cell_probe(_position_of(point))))


def _view_bytes(engine: Any, viewer: Any) -> bytes:
    """One viewer's resolved field, one byte per square, row-major: shared inside one pass (§6.1)."""
    from .read_queries import shared_query

    return shared_query(engine, ("lighting.view", _viewer_key(viewer)),
                        lambda: _view(engine, viewer), refs=(viewer,) if viewer is not None else ())


def _view(engine: Any, viewer: Any) -> bytes:
    """Project the scalar answer onto each map cell so field and scalar levels agree.

    Each square is queried at its own terrain altitude, or ground level when no
    elevated surface is authored. Darkvision never substitutes the viewer's altitude.
    """
    width, height = int(engine.grid.width), int(engine.grid.height)
    levels = bytearray()
    for y in range(height):
        for x in range(width):
            roof_ft = engine.grid.roof_height_at(x, y) if hasattr(engine.grid, "roof_height_at") else None
            z = int(roof_ft // 5) if roof_ft is not None else 0
            levels.append(seen_level(engine, viewer, (x, y, z)))
    return bytes(levels)


@pure
def seen_field(engine: Any, viewer: Any) -> dict[tuple[int, int], int]:
    """The whole per-viewer field for a payload (spec §7.1): one answer per square, this viewer's own eyes."""
    width, height = int(engine.grid.width), int(engine.grid.height)
    cells = _view_bytes(engine, viewer)
    return {(x, y): cells[y * width + x] for y in range(height) for x in range(width)}


def heavily_obscured(engine: Any, viewer: Any, position: Any, *, subject: Any = None) -> bool:
    """Whether this viewer cannot see into the square at all: Heavily Obscured, level Dark (spec §2.5).

    ``subject`` is used only by creature-level sight checks that need its qualified concealment rules.
    """
    return _seen_level(engine, viewer, _position_of(position), subject=subject) == DARK


def perceivable(engine: Any, viewer: Any, position: Any, *, subject: Any = None) -> bool:
    """Whether one exact 3-D cell is both physically reachable by sight and not Dark to this viewer."""
    from . import senses

    point = _position_of(position)
    probe = senses.cell_probe(point)
    # This endpoint is a cell of a creature, not an empty terrain surface.
    # Preserve the ordinary creature-origin volume ray even for an airborne viewer.
    probe.near_side = True
    return senses.physical_sight(engine, viewer, probe) and not heavily_obscured(
        engine, viewer, point, subject=subject
    )


def creature_heavily_obscured(engine: Any, viewer: Any, creature: Any) -> bool:
    """Whether no occupied body cell is both physically visible and lit to this viewer.

    Light and sight use the same occupied volume and a cell counts only when both rules agree on that exact cell.
    Keep the creature as the subject of its darkness query so typed exemptions remain effective.
    """
    from . import senses

    cells = engine._actor_volume(creature) if (
        creature.position.z or engine.grid.finite_heights
    ) else engine._actor_cells(creature)
    if not cells:
        cells = [(creature.position.x, creature.position.y, creature.position.z)]
    for cell in cells:
        x, y = int(cell[0]), int(cell[1])
        z = int(cell[2]) if len(cell) > 2 else int(creature.position.z)
        point = _position_of((x, y, z))
        if perceivable(engine, viewer, point, subject=creature):
            return False
    return True


def dim(engine: Any, viewer: Any, position: Any) -> bool:
    """Whether this viewer's eyes are in Dim Light at the square: Lightly Obscured (spec §2.6)."""
    return seen_level(engine, viewer, position) == DIM


def obscured(engine: Any, viewer: Any, position: Any) -> bool:
    """Whether this viewer sees the square as anything but Bright: Lightly or Heavily Obscured (spec §2.4)."""
    return seen_level(engine, viewer, position) < BRIGHT


def attack_modes(engine: Any, viewer: Any, target: Any) -> tuple[str, ...]:
    """The light contributions to one attack, uncancelled and in the engine's order (spec §2.5).

    A square the attacker cannot see into makes the target unseen (Disadvantage); an attacker standing in one is
    unseen itself (Advantage); both cancel, exactly as the areas already do (combat/zones.py attack_modes).
    """
    return tuple(mode for mode, applies in
                 (("DISADVANTAGE", creature_heavily_obscured(engine, viewer, target)),
                  ("ADVANTAGE", creature_heavily_obscured(engine, target, viewer))) if applies)


def perception_mode(engine: Any, actor: Any) -> str:
    """DISADVANTAGE for a sight check made from Dim Light, else NORMAL (spec §2.6)."""
    return "DISADVANTAGE" if dim(engine, actor, actor.position) else "NORMAL"


def views(engine: Any, viewers: Iterable[Any]) -> list[dict[tuple[int, int], int]]:
    """The resolved field for a whole table of viewers in one pass (spec §6.3), painting the base field once.

    One viewer's answer is a pure query; the table's answer is twelve of them, and the expensive part - the base field
    and its occlusion - is shared. The answers are copies, one per viewer, and nothing survives the call.
    """
    from .read_queries import read_frame

    with read_frame(engine):
        return [seen_field(engine, viewer) for viewer in viewers]


def summaries(engine: Any, viewers: Iterable[Any]) -> list[dict[str, Any]]:
    """The per-viewer light payloads of a table read in one pass (spec §6.3, §7.1): one base field, many eyes."""
    from .read_queries import read_frame

    with read_frame(engine):
        return [summary(engine, viewer) for viewer in viewers]


@pure
def own_light(engine: Any, viewer: Any) -> list[dict[str, Any]]:
    """The lights this creature itself carries or wears (its sheet, and in S4 what the AI knows it can see by)."""
    return [{"name": source.name, "bright_ft": source.bright_ft, "dim_ft": source.dim_ft,
             "color": source.color, "magical": source.magical}
            for source in sources(engine) if source.following == viewer.entity_id]


#: Two bits per square, packed four squares to a byte in row-major order (spec §7.1): index = a<<6 | b<<4 | c<<2 | d.
_PACKED = [((index >> 6) & 3) | (((index >> 4) & 3) << 2) | (((index >> 2) & 3) << 4) | ((index & 3) << 6)
           for index in range(256)]


def _pack(levels: bytes) -> bytes:
    """Two bits per square, row-major, the last byte zero-padded: 2,400 squares become 600 bytes (spec §7.1)."""
    body = len(levels) - len(levels) % 4
    packed = bytes(_PACKED[(a << 6) | (b << 4) | (c << 2) | d] for a, b, c, d in
                   zip(levels[0:body:4], levels[1:body:4], levels[2:body:4], levels[3:body:4]))
    tail = levels[body:]
    if not tail:
        return packed
    value = 0
    for shift, level in enumerate(tail):
        value |= level << (2 * shift)
    return packed + bytes((value,))


@pure
def summary(engine: Any, viewer: Any) -> dict[str, Any]:
    """The compact per-viewer light payload of the table (spec §7.1), built from this viewer's own answers.

    cells is the resolved field, row-major, two bits per square; the table composites it under the fog mask, so a
    square the viewer has never seen keeps whatever it already drew instead of turning lit.
    """
    row = ambient(engine)
    return {"schema": SCHEMA, "by": getattr(viewer, "entity_id", None),
            "ambient": {"time_of_day": row["time_of_day"], "level": row["level"]},
            "own": own_light(engine, viewer),
            "cells": base64.b64encode(_pack(_view_bytes(engine, viewer))).decode("ascii"), "level_at": {}}
