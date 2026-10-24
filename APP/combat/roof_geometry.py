"""Walkable roof surfaces and their queries.

Roof regions and heights come from main's combat/roof_coverage.py and
combat/map_heights.py (the single source). This module only turns those
regions into battlefield surfaces, adding the branch's per-roof climbing
condition and openings, and answers support, volume, step, and ray queries.

A roof supports feet exactly at its height. A body may touch either face but
may not straddle it. Open full-cell apertures have no support or barrier;
closed skylights are load-bearing transparent panels (sight only passes).
These grid/weight conventions are explicit engine choices, not additional RAW.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from .map_heights import roof_height_ft, walking_height_ft
from .roof_coverage import roof_regions
from .space import point, volume


def _xy(cell):
    return (cell["x"], cell["y"]) if isinstance(cell, dict) else tuple(cell[:2])


def surfaces_for_map(document, rasterizer):
    """Compile enabled roofs to battlefield records, using main's regions and heights."""
    settings = document.get("roofs") or {}
    if settings.get("enabled") is False:
        return []
    rows = []
    for region in roof_regions(document, rasterizer):
        footprint = region["footprint"]
        override = next((row for row in settings.get("regions", [])
                         if (row["x"], row["y"]) in footprint), {})
        if override.get("enabled") is False:
            continue
        height = roof_height_ft({**settings, **override}, region["wall_height_ft"])
        row = {"id": f"{region['x']},{region['y']}", "height_ft": height,
               "cells": [{"x": x, "y": y} for x, y in sorted(footprint, key=lambda c: (c[1], c[0]))]}
        climb_check = override.get("climb_check", settings.get("climb_check", "none"))
        if climb_check != "none":
            row["climb_check"] = climb_check
        catch_dc = override.get("catch_dc", settings.get("catch_dc"))
        if catch_dc is not None:
            if type(catch_dc) is not int or catch_dc < 0:
                raise ValueError("Catch difficulty must be a nonnegative integer")
            row["catch_dc"] = catch_dc
        openings = [dict(opening) for opening in settings.get("openings", [])
                    if (opening["x"], opening["y"]) in footprint]
        if openings:
            row["openings"] = openings
        rows.append(row)
    return rows


@dataclass(frozen=True)
class RoofSurface:
    id: str
    height_ft: int
    walk_ft: int
    cells: frozenset[tuple[int, int]]
    open_cells: frozenset[tuple[int, int]]
    skylight_cells: frozenset[tuple[int, int]]
    climb_check: str = "none"
    catch_dc: int | None = None

    def solid_at(self, x, y):
        return (x, y) in self.cells and (x, y) not in self.open_cells

    def blocks_sight_at(self, x, y):
        return self.solid_at(x, y) and (x, y) not in self.skylight_cells


class RoofGeometry:
    """Pure queries over the battlefield's sealed horizontal surfaces."""
    def __init__(self, rows=()):
        surfaces = []
        for index, row in enumerate(rows):
            height = row["height_ft"]
            if type(height) is not int or height <= 0:
                raise ValueError("Roof height must be a positive whole number of feet")
            cells = frozenset(_xy(c) for c in row.get("cells", ()))
            openings = row.get("openings", ())
            climb_check = row.get("climb_check", "none")
            if climb_check not in {"none", "slippery", "few_handholds"}:
                raise ValueError("Unknown roof climbing condition")
            catch_dc = row.get("catch_dc")
            if catch_dc is not None and (type(catch_dc) is not int or catch_dc < 0):
                raise ValueError("Catch difficulty must be a nonnegative integer")
            surfaces.append(RoofSurface(str(row.get("id", index)), height, walking_height_ft(height), cells,
                frozenset(_xy(o) for o in openings if o.get("open") is True) & cells,
                frozenset(_xy(o) for o in openings if o.get("kind") == "skylight") & cells, climb_check, catch_dc))
        self.surfaces = tuple(surfaces)
        by_cell = {}
        for surface in self.surfaces:
            for cell in surface.cells:
                by_cell.setdefault(cell, []).append(surface)
        self.by_cell = {cell: tuple(sorted(rows, key=lambda r: (-r.height_ft, r.id)))
                        for cell, rows in by_cell.items()}
        self.heights = tuple(sorted({surface.height_ft for surface in self.surfaces}))
        self.walk_heights = tuple(sorted({surface.walk_ft for surface in self.surfaces}))

    def roof_at(self, x, y):
        return next(iter(self.by_cell.get((x, y), ())), None)

    def supported(self, anchor, footprint=None):
        if not self.surfaces:
            return False
        x, y, z = point(anchor)
        cells = footprint.occupied_cells((x, y)) if footprint is not None else ((x, y),)
        return any(surface.walk_ft == z * 5 and surface.solid_at(cx, cy)
                   for cx, cy in cells for surface in self.by_cell.get((cx, cy), ()))

    def volume_blocked(self, anchor, footprint=None):
        if not self.surfaces:
            return False
        occupied = volume(anchor, footprint)
        if not occupied:
            return False
        bottom, top = min(c[2] for c in occupied) * 5, (max(c[2] for c in occupied) + 1) * 5
        return any(bottom < surface.walk_ft < top and surface.solid_at(x, y)
                   for x, y in {(x, y) for x, y, _ in occupied}
                   for surface in self.by_cell.get((x, y), ()))

    def step_blocked(self, start, end, footprint=None):
        """No crossing the slab, including side volumes of a diagonal step.

        A climbing route reaches the roof's height outside its footprint, then
        steps sideways onto it. It cannot cut up through an eave diagonally.
        """
        if not self.surfaces:
            return False
        a, b = point(start), point(end)
        if a[2] == b[2]:
            return False
        low, high = sorted((a[2] * 5, b[2] * 5))
        anchors = product({a[0], b[0]}, {a[1], b[1]})
        horizontal = {cell for x, y in anchors
                      for cell in (footprint.occupied_cells((x, y)) if footprint is not None else ((x, y),))}
        return any(low < surface.walk_ft <= high and surface.solid_at(x, y)
                   for x, y in horizontal
                   for surface in self.by_cell.get((x, y), ()))

    def _ray_blocked(self, start, end, *, sight=False, scale=20):
        """Exact integer plane intersections at exact roof tops. A touched roof edge is closed."""
        dz = end[2] - start[2]
        if not dz:
            return False
        for height in self.heights:
            # Plane heights are whole feet; one foot is scale / 5 units, which is an integer.
            numerator, denominator = height * scale // 5 - start[2], dz
            if denominator < 0:
                numerator, denominator = -numerator, -denominator
            if not 0 < numerator < denominator:
                continue
            xn = start[0] * denominator + (end[0] - start[0]) * numerator
            yn = start[1] * denominator + (end[1] - start[1]) * numerator
            unit = scale * denominator
            xs, ys = [xn // unit], [yn // unit]
            if xn % unit == 0:
                xs.append(xs[0] - 1)
            if yn % unit == 0:
                ys.append(ys[0] - 1)
            for x, y in product(xs, ys):
                if any(surface.height_ft == height and
                       (surface.blocks_sight_at(x, y) if sight else surface.solid_at(x, y))
                       for surface in self.by_cell.get((x, y), ())):
                    return True
        return False

    def ray_blocked(self, start, end, *, sight=False):
        if not self.surfaces:
            return False
        # Existing grid sight/effect endpoints are occupied-cell centers.
        a = tuple(20 * c + 10 for c in point(start))
        b = tuple(20 * c + 10 for c in point(end))
        return self._ray_blocked(a, b, sight=sight)

    def cover_bonus(self, start, end):
        """Partial roof-edge obstruction uses the engine's ordinary +2 cover.

        Sample near the eight target-volume corners, inset 1/20 square to avoid
        counting the target's own support face. A clear central ray with at
        least one blocked corner ray has partial cover; total blockage belongs
        to LoE. This extends the existing 5e cover numbers, not 3.5's +4 bonus.
        """
        if not self.surfaces or point(start)[2] == point(end)[2] or self.ray_blocked(start, end):
            return 0
        a = tuple(20 * c + 10 for c in point(start))
        base = tuple(20 * c for c in point(end))
        return 2 if any(self._ray_blocked(a, tuple(c + d for c, d in zip(base, corner)))
                        for corner in product((1, 19), repeat=3)) else 0
