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
from fractions import Fraction
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
    if emitting and (floor < BRIGHT or painted):
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
    """One pass's occluder geometry: every segment measured once, and every ray asked at most once per square pair."""

    __slots__ = ("segments", "cells", "discs", "points", "width", "height", "hit")

    def __init__(self, engine: Any) -> None:
        self.segments: list[tuple[Any, float, float, tuple[float, float, float, float], tuple[Any, ...], bool]] = []
        self.discs: dict[tuple[int, int, int], _Disc] = {}
        self.points: dict[tuple[int, int], _Point] = {}
        self.width = int(engine.grid.width)
        self.height = int(engine.grid.height)
        from .sight_lines import hit

        self.hit = hit  # resolved once per pass: sight_lines.hit is the authority every light ray is judged by
        cells: set[tuple[int, int]] = set()
        for row in getattr(getattr(engine, "grid", None), "sight_line_sources", ()) or ():
            bottom, top = row.get("bottom_ft"), row.get("top_ft")
            if top is not None and top <= bottom:
                continue  # sight_lines.hit opens with this same test, so this row can never stop a ray
            segments = row.get("segments") or ()
            if not segments:
                continue  # no geometry to cross, so nothing to ask
            scale = row.get("scale", 2)
            half = scale // 2 if scale % 2 == 0 else Fraction(scale, 2)
            # A row that starts at the floor (bottom_ft 0) is decided by its geometry alone for a ray on the ground,
            # which is what every light ray is; any other row keeps asking sight_lines.hit itself.
            plane = bottom == 0
            for segment in segments:
                (ax, ay), (bx, by) = segment
                axis = 0 if ax == bx else 1
                other = 1 - axis
                low, high = (ay, by) if axis == 0 else (ax, bx)
                if low > high:
                    low, high = high, low
                # The segment's own square extent, in cells, with a half-cell margin: a filter in front of the
                # engine's geometry, never a replacement for it (a margin only ever admits one segment more).
                rect = (min(ax, bx) / scale - 0.5, max(ax, bx) / scale + 0.5,
                        min(ay, by) / scale - 0.5, max(ay, by) / scale + 0.5)
                self.segments.append(({**row, "segments": [segment]}, scale, half, rect,
                                      (axis, other, low, high, ax if axis == 0 else ay), plane))
            cells.update((int(x), int(y)) for x, y in row.get("cells") or ())
        self.cells = frozenset(cells)

    def point(self, x: int, y: int) -> _Point:
        point = self.points.get((x, y))
        if point is None:
            point = self.points[(x, y)] = _Point(int(x), int(y), 0)
        return point

    def disc(self, sx: int, sy: int, radius: int) -> _Disc:
        """The occluders that can reach one source square, measured once per square and radius."""
        key = (sx, sy, radius)
        disc = self.discs.get(key)
        if disc is None:
            disc = self.discs[key] = _Disc(self, sx, sy, radius)
        return disc


class _Disc:
    """One source square's disc: this ray origin's candidate occluders, and the answers they already gave."""

    __slots__ = ("hit", "width", "sx", "sy", "groups", "answers", "cells", "own")

    def __init__(self, rays: _Rays, sx: int, sy: int, radius: int) -> None:
        self.hit = rays.hit  # no reference back to the pass: these objects must die by refcount, not by a GC cycle
        self.width = rays.width
        self.sx, self.sy = sx, sy
        x0, x1 = sx - radius - 0.5, sx + radius + 0.5
        y0, y1 = sy - radius - 0.5, sy + radius + 0.5
        groups: dict[int, list[tuple[Any, ...]]] = {}
        for one, scale, half, rect, info, plane in rays.segments:
            if x0 > rect[1] or x1 < rect[0] or y0 > rect[3] or y1 < rect[2]:
                continue  # this segment cannot reach the disc, so none of its rays can cross it
            axis, other, low, high, a_axis = info
            groups.setdefault(scale, []).append(
                (one, sx * scale + half, sy * scale + half, axis, other, low, high, a_axis, plane))
        self.groups = tuple(groups.items())
        self.answers: dict[int, bool] = {}
        # The squares the occluders themselves stand in: a ray ending on one is judged by its own geometry, so these
        # are the only squares of a row that one clear far ray cannot speak for. Grouped by direction here so a row
        # never has to walk its squares looking for them.
        self.cells = frozenset(cell for cell in rays.cells if x0 <= cell[0] <= x1 and y0 <= cell[1] <= y1)
        own: dict[tuple[int, int], list[int]] = {}
        for cx, cy in self.cells:
            dx, dy = cx - sx, cy - sy
            step = math.gcd(abs(dx), abs(dy)) or 1
            own.setdefault((dx // step, dy // step), []).append(step)
        self.own = {key: sorted(values) for key, values in own.items()}

    def clear(self, x: int, y: int) -> bool:
        """Whether light reaches one square from this disc's own square: the occluder ray fog uses (spec §4.1 step 2).

        The question is the one sight_lines.hit answers, asked in integers because it is asked once per direction per
        source: a segment crossing the ray needs its crossing point inside the segment and between the endpoints. A
        segment that lies along the ray, or a row that does not start at the floor, is handed to sight_lines.hit.
        """
        index = y * self.width + x
        answer = self.answers.get(index)
        if answer is not None:
            return answer
        answer = True
        if not self.groups:
            self.answers[index] = True
            return True
        hit = self.hit

        sx, sy = self.sx, self.sy
        start = end = None
        for scale, segments in self.groups:
            d0, d1 = scale * (x - sx), scale * (y - sy)
            for row, ox, oy, axis, other, low, high, a_axis, plane in segments:
                if not plane:
                    if start is None:
                        start, end = _Point(sx, sy, 0), _Point(x, y, 0)
                    if hit(start, end, row):
                        answer = False
                        break
                    continue
                if axis == 0:
                    num, den, step, p_other, p_axis = a_axis - ox, d0, d1, oy, ox
                else:
                    num, den, step, p_other, p_axis = a_axis - oy, d1, d0, ox, oy
                if den == 0:
                    if p_axis != a_axis:
                        continue
                    if start is None:
                        start, end = _Point(sx, sy, 0), _Point(x, y, 0)
                    if hit(start, end, row):
                        answer = False
                        break
                    continue
                if den < 0:
                    num, den = -num, -den
                if not 0 <= num <= den:
                    continue  # the crossing is past an endpoint of this ray
                value = p_other * den + step * num  # the crossing point, times this ray's own denominator
                if low * den <= value <= high * den:
                    answer = False
                    break
            if not answer:
                break
        self.answers[index] = answer
        return answer

    def reach(self, ux: int, uy: int, limit: int) -> int:
        """How many squares along one reduced direction the light reaches: 0 when the first square is blocked.

        Along one direction the rays to the squares are nested, so one ray to the farthest square answers the row when
        it is clear, and a blocked one says every square beyond the first blocked square is blocked too.
        """
        sx, sy = self.sx, self.sy
        if not self.groups:
            return limit
        if self.clear(sx + limit * ux, sy + limit * uy):
            if not self.own:
                return limit
            # The squares a clear far ray cannot speak for: a ray that ends on an occluder's own square may stop there
            # while a farther ray runs past it, so those few squares are asked one at a time.
            for k in self.own.get((ux, uy), ()):
                if k > limit:
                    break
                if not self.clear(sx + k * ux, sy + k * uy):
                    return k - 1
            return limit
        low, high = 1, limit
        while low < high:  # the first blocked square, where every square beyond it is behind the same occluder
            middle = (low + high) // 2
            if self.clear(sx + middle * ux, sy + middle * uy):
                low = middle + 1
            else:
                high = middle
        return low - 1


def _emit(engine: Any, source: LightSource, floor: int, square: int, cells: bytearray, rays: _Rays) -> None:
    """Mark one source's disc through sight-clear rays (spec §4.1 step 2), keeping the maximum per square (step 3)."""
    radius = source.dim_ft // square
    if radius <= 0:
        return
    bright_cells = source.bright_ft // square
    top = BRIGHT if bright_cells > 0 else DIM  # the brightest level this source can put on any square
    if top <= floor:
        return  # it cannot raise one square above the ambient floor, and light never darkens (§2.4.2)
    width, height = int(engine.grid.width), int(engine.grid.height)
    rows = _rows_for(radius, bright_cells)
    for sx, sy in sorted(source.cells):
        if not (0 <= sx < width and 0 <= sy < height):
            continue  # a source stored off the map lights nothing
        own = sy * width + sx
        was = cells[own]
        if top > was:
            cells[own] = top  # a source's own square is its own light, not its dim ring
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
            reach = disc.reach(ux, uy, limit) if disc.groups else limit
            if reach <= 0:
                continue
            along = uy * width + ux
            bright = bright_steps if bright_steps < reach else reach
            first = own + along
            if bright > 0 and along > 0:
                # Bright is the top level, so a slice write over a reached run never lowers a square and runs in C.
                cells[first:first + along * bright:along] = _BRIGHT[:bright]
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
    """A Position from a Position, a square pair, or anything with .x/.y."""
    if hasattr(value, "x") and hasattr(value, "y"):
        return value
    from .gate2_runtime_models import Position

    x, y = value
    return Position(x=int(x), y=int(y), z=0)


@pure
def seen_level(engine: Any, viewer: Any, position: Any) -> int:
    """The per-viewer level of one square (spec §4): the base field, after areas and after this viewer's own senses.

    viewer is the creature whose eyes are being asked; None asks about the square alone (no Darkvision, and no
    viewer-specific suppression), which is what a caller with no creature in hand means.
    """
    from .read_queries import shared_query

    point = _position_of(position)
    key = ("lighting.seen", id(viewer) if viewer is not None else None, (int(point.x), int(point.y)))
    return shared_query(engine, key, lambda: _seen_level(engine, viewer, point),
                        refs=(viewer,) if viewer is not None else ())


def _seen_level(engine: Any, viewer: Any, point: Any) -> int:
    if not declared(engine):
        return BRIGHT
    level = base(engine, point.x, point.y)
    if level > DARK and _area_dark(engine, viewer, point):
        level = DARK  # step 4: darkness beats light, whatever the torch says (§2.7)
    if level < BRIGHT and viewer is not None:
        feet = _darkvision(engine, viewer, point)
        if feet > 0 and _feet_to(engine, viewer, point) <= feet:
            level += 1  # step 5: Darkvision raises Dark to Dim and Dim to Bright within its reach (§2.8)
    return level


def _area_dark(engine: Any, viewer: Any, point: Any) -> bool:
    """Step 4: whether an area of darkness or heavy obscurement takes this square from this viewer (§4.1)."""
    from . import senses, zones

    if not zones.heavy_zones(engine):
        return False
    probe = senses.cell_probe(_position_of(point))
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

    return shared_query(engine, ("lighting.view", id(viewer) if viewer is not None else None),
                        lambda: _view(engine, viewer), refs=(viewer,) if viewer is not None else ())


def _view(engine: Any, viewer: Any) -> bytes:
    """One viewer's whole field (spec §4.1 steps 4-5), touching only the squares an area or a sense changes."""
    from . import zones

    cells = bytearray(_base_bytes(engine))
    if not declared(engine):
        return bytes(cells)
    width, height = int(engine.grid.width), int(engine.grid.height)
    if viewer is None:
        return bytes(cells)
    heavy = zones.heavy_zones(engine)
    if heavy:
        candidates: set[tuple[int, int]] = set()
        whole = False
        for zone in heavy:
            if (zone.trigger_profile.get("visual") or {}).get("sees") == "inward" \
                    and zones.actor_inside_zone(engine, viewer, zone):
                whole = True  # an inward area takes squares outside itself from everyone within it
                break
            candidates |= {(int(cell.x), int(cell.y)) for cell in zone.affected_cells}
        squares = (((x, y) for y in range(height) for x in range(width)) if whole
                   else ((x, y) for x, y in sorted(candidates) if 0 <= x < width and 0 <= y < height))
        for x, y in squares:
            index = y * width + x
            if cells[index] != DARK and _area_dark(engine, viewer, _position_of((x, y))):
                cells[index] = DARK
    if _pure_zones(engine):
        # Pure Darkness measures every square's Darkvision separately (spec §2.8), so this rare map asks one by one.
        return bytes(_seen_level(engine, viewer, _position_of((x, y)))
                     for y in range(height) for x in range(width))
    feet = _darkvision_range(engine, viewer)
    if feet > 0:
        point = _position_of(getattr(viewer, "position", viewer))
        reach = feet // _square(engine)
        cx, cy = int(point.x), int(point.y)
        for y in range(max(0, cy - reach), min(height, cy + reach + 1)):
            offset, dy = y * width, abs(y - cy)
            for x in range(max(0, cx - reach), min(width, cx + reach + 1)):
                if dy > reach or abs(x - cx) > reach:
                    continue
                index = offset + x
                if cells[index] < BRIGHT:
                    cells[index] += 1  # step 5: Darkvision raises Dark to Dim and Dim to Bright within its reach
    return bytes(cells)


@pure
def seen_field(engine: Any, viewer: Any) -> dict[tuple[int, int], int]:
    """The whole per-viewer field for a payload (spec §7.1): one answer per square, this viewer's own eyes."""
    width, height = int(engine.grid.width), int(engine.grid.height)
    cells = _view_bytes(engine, viewer)
    return {(x, y): cells[y * width + x] for y in range(height) for x in range(width)}


def heavily_obscured(engine: Any, viewer: Any, position: Any) -> bool:
    """Whether this viewer cannot see into the square at all: Heavily Obscured, level Dark (spec §2.5)."""
    return seen_level(engine, viewer, position) == DARK


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
                 (("DISADVANTAGE", heavily_obscured(engine, viewer, target.position)),
                  ("ADVANTAGE", heavily_obscured(engine, target, viewer.position))) if applies)


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


#: A run of Bright squares, for slice painting: the level is the top one, so writing it never lowers a square.
_BRIGHT = bytes([BRIGHT]) * 64

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
