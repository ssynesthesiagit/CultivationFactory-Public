"""Authored roof footprints and horizontal sight surfaces; no LoS evaluation.

Mirrors static/tabletop/roof-regions.js: enclosed indoor components, joined
through shared walls, with short authored entrance gaps closed for inference.
Doors and breached walls never erase a roof. Windows do not block roof
detection, but their height contributes on inferred building boundaries,
matching the editor. Open-air courtyard overrides do. The rasterizer is
injected to avoid a dependency cycle with tabletop.py.
"""
from .map_heights import DEFAULTS, roof_height_ft, wall_height_ft


def roof_regions(document, rasterizer):
    width, height = document["width_squares"], document["height_squares"]
    walls = [(wall, rasterizer(wall, width, height)) for wall in document.get("walls", [])]
    barriers = set().union(*(cells for _, cells in walls))
    barriers.update((o["x"], o["y"]) for o in document.get("objects", [])
                    if o["kind"] in {"wall_section", "door", "gate", "portcullis"})
    styles = {tuple(cell): row["material"][6:] for row in document.get("materials", [])
              if row["material"].startswith("floor:") for cell in row["cells"]}
    indoor_styles = set(DEFAULTS["indoor_styles"])
    background = document.get("background", {}).get("style", "flagstone")

    def indoor(x, y):
        return styles.get((x, y), background) in indoor_styles

    authored = set(barriers)
    for x, y in authored:
        for dx, dy in ((1, 0), (0, 1)):
            for length in (1, 2):
                gap = [(x + dx * i, y + dy * i) for i in range(1, length + 1)]
                ex, ey = x + dx * (length + 1), y + dy * (length + 1)
                if ex >= width or ey >= height or (ex, ey) not in authored or any(c in authored for c in gap):
                    continue
                if (x - dx, y - dy) not in authored or (ex + dx, ey + dy) not in authored:
                    continue
                if any(indoor(gx + dy, gy + dx) or indoor(gx - dy, gy - dx) for gx, gy in gap):
                    barriers.update(gap)
    visited, rooms = set(), []
    for y in range(height):
        for x in range(width):
            if (x, y) in barriers or (x, y) in visited:
                continue
            cells, boundary = [(x, y)], set()
            visited.add((x, y))
            exterior, all_indoor = False, True
            for cx, cy in cells:
                all_indoor &= indoor(cx, cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        exterior = True
                    elif (nx, ny) in barriers:
                        boundary.add((nx, ny))
                    elif (nx, ny) not in visited:
                        visited.add((nx, ny))
                        cells.append((nx, ny))
            if not exterior and all_indoor:
                rooms.append((set(cells), boundary))
    buildings = []
    while rooms:
        cells, boundary = rooms.pop(0)
        changed = True
        while changed:
            changed = False
            for index in range(len(rooms) - 1, -1, -1):
                other_cells, other_boundary = rooms[index]
                if boundary & other_boundary:
                    cells |= other_cells
                    boundary |= other_boundary
                    rooms.pop(index)
                    changed = True
        footprint = cells | boundary
        footprint |= {(cx + dx, cy + dy) for cx, cy in cells for dx in (-1, 1) for dy in (-1, 1)
                      if (cx + dx, cy + dy) in barriers}
        ax, ay = min(cells, key=lambda c: (c[1], c[0]))
        boundary_heights = [wall_height_ft(w) for w, wc in walls if wc & boundary]
        boundary_heights.extend(wall_height_ft(o) for o in document.get("objects", [])
            if o["kind"] in {"wall_section", "door", "gate", "portcullis", "window"}
            and (o["x"], o["y"]) in boundary)
        building_height = max(boundary_heights, default=DEFAULTS["wall_ft"])
        buildings.append({"x": ax, "y": ay, "cells": cells, "footprint": footprint,
                          "wall_height_ft": building_height})
    return sorted(buildings, key=lambda r: (r["y"], r["x"]))


def roof_cells(document, rasterizer):
    """[{x, y, roof_top_height_ft}] in feet above map ground, integers only.

    These are horizontal opaque surfaces, NOT columns from ground to roof.
    Sight crossing the surface cannot see the room beneath it. They impose no
    movement rule here. Rendering transparency and viewer/GM toggles never
    remove surfaces; authored roofs.enabled=False means an open-air building.
    """
    settings = document.get("roofs", {})
    if settings.get("enabled") is False:
        return []
    covered = {}
    for region in roof_regions(document, rasterizer):
        override = next((row for row in settings.get("regions", [])
                         if (row["x"], row["y"]) in region["footprint"]), {})
        if override.get("enabled") is False:
            continue
        top = roof_height_ft({**settings, **override}, region["wall_height_ft"])
        for cell in region["footprint"]:
            covered[cell] = max(top, covered.get(cell, 0))
    # A skylight is a transparent panel and an open aperture is empty: neither
    # is an opaque sight surface (combat/roof_geometry.py applies the same rule).
    see_through = {(o["x"], o["y"]) for o in settings.get("openings", [])
                   if o.get("kind") == "skylight" or o.get("open") is True}
    return [{"x": x, "y": y, "roof_top_height_ft": covered[x, y]}
            for x, y in sorted(covered, key=lambda c: (c[1], c[0])) if (x, y) not in see_through]
