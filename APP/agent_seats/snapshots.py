"""Actor-only map projection and browser-free PNGs for model seats.

No engine access: project_map clips the table's geometry to perception cells;
SnapshotRenderer accepts only that projection and the runner's redacted actors.
The bounded cache includes the entire view, fighter, match and state version.
"""
from collections import OrderedDict
import hashlib
import io
import json
import math
import threading

from PIL import Image, ImageDraw, ImageFont


def _clip(points, x, y, polygon):
    """Clip a polygon or single segment to a visible square."""
    for axis, edge, direction in ((0, x, 1), (0, x + 1, -1), (1, y, 1), (1, y + 1, -1)):
        if not points:
            break
        result = []
        pairs = zip(points[-1:] + points[:-1], points) if polygon else [(points[0], points[-1])]
        for a, b in pairs:
            inside_a = direction * (a[axis] - edge) >= 0
            inside_b = direction * (b[axis] - edge) >= 0
            if inside_a != inside_b:
                t = (edge - a[axis]) / (b[axis] - a[axis])
                crossing = [a[i] + t * (b[i] - a[i]) for i in (0, 1)]
                if not polygon and inside_a:
                    result.append(a)
                result.append(crossing)
            elif not polygon and inside_a:
                result.append(a)
            if inside_b:
                result.append(b)
        points = result
    return [[round(a * 1000), round(b * 1000)] for a, b in points]


def project_map(source, cells, width, height, zones):
    """Return integer-only, visible map geometry; omit all owner/source ids."""
    source = source or {}
    visible = set(map(tuple, cells))
    ordered_cells = sorted(visible)
    result = {"width": width, "height": height, "terrain": [], "walls": [], "zones": [], "trees": []}
    for row in [*(source.get("floors") or []), *(source.get("terrain") or [])]:
        selected = [list(cell) for cell in row.get("cells", []) if tuple(cell) in visible]
        if selected:
            result["terrain"].append({"name": row.get("type") or row.get("style") or "Ground", "cells": selected})
    scale = source.get("scale") or 1
    for wall in source.get("walls") or []:
        points = [[a / scale, b / scale] for a, b in wall["points"]]
        shape = wall["shape"]
        if shape == "rect":
            (a, b), (c, d) = points
            points = [[min(a,c), min(b,d)], [max(a,c), min(b,d)], [max(a,c), max(b,d)], [min(a,c), max(b,d)]]
        elif shape == "circle":
            (a, b), (c, d) = points
            # Table maps store the center followed by a point on the rim.
            radius = math.hypot(c - a, d - b)
            points = [[a + radius * math.cos(i*math.tau/64),
                       b + radius * math.sin(i*math.tau/64)] for i in range(64)]
        filled = bool(wall.get("filled", shape != "line")) and shape != "line"
        pieces = [points] if filled else [list(pair) for pair in zip(points, points[1:] + (points[:1] if shape != "line" else []))]
        for piece in pieces:
            lo_x, hi_x = min(p[0] for p in piece), max(p[0] for p in piece)
            lo_y, hi_y = min(p[1] for p in piece), max(p[1] for p in piece)
            for x, y in ordered_cells:
                if x > hi_x or x + 1 < lo_x or y > hi_y or y + 1 < lo_y:
                    continue
                clipped = _clip(piece, x, y, filled)
                if len(clipped) >= (3 if filled else 2):
                    result["walls"].append({"points": clipped, "filled": filled,
                                            "sight_only": wall.get("blocks") == "sight",
                                            **({"height_ft": wall["height_ft"]} if "height_ft" in wall else {})})
    for tree in source.get("trees") or []:
        # Trunk coordinates and size are whole squares, independent of wall scale.
        selected = [[tree["x"] + dx, tree["y"] + dy]
                    for dx in range(tree["size"]) for dy in range(tree["size"])
                    if (tree["x"] + dx, tree["y"] + dy) in visible]
        if selected:
            result["trees"].append({"name": "Tree trunk: blocks movement and sight", "cells": selected})
    for zone in zones:
        selected = [{"x": c["x"], "y": c["y"]} for c in zone.get("affected_cells", []) if (c["x"], c["y"]) in visible]
        if selected:
            result["zones"].append({"name": zone.get("display_name") or
                                    (zone.get("trigger_profile") or {}).get("name") or "Area", "cells": selected})
    return result


class SnapshotRenderer:
    """Callable renderer with a 16-frame LRU, no disk cache or GUI dependency."""
    def __init__(self):
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def __call__(self, view):
        key = hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode()).digest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        png = render_png(view)
        with self._lock:
            self._cache[key] = png
            self._cache.move_to_end(key)
            while len(self._cache) > 16:
                self._cache.popitem(last=False)
        return png


def render_png(view):
    """Draw a deterministic 768 px map. Labels use engine (x, y) squares."""
    board = view["map"]
    width, height = board["width"], board["height"]
    cell = min(690 / max(1, width), 600 / max(1, height))
    left, top = 45, 70
    image = Image.new("RGB", (768, 768), "#141b25")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=12)
    def text(x, y, value, color="white"):
        draw.text((int(x), int(y)), str(value), font=font, fill=color)
    def box(x, y):
        return (int(left+x*cell), int(top+y*cell), int(left+(x+1)*cell), int(top+(y+1)*cell))
    text(20, 12, "Your view | Squares are 5 feet | Move using (x, y)")
    text(20, 32, "Gold ring: you | Grey X: last seen, current position unknown")
    for x, y in view.get("visible_cells", []):
        draw.rectangle(box(x, y), fill="#d4cbb7")
    for terrain in board["terrain"]:
        color = "#" + hashlib.sha256(terrain["name"].encode()).hexdigest()[:6]
        for x, y in terrain["cells"]:
            draw.rectangle(box(x,y), fill=color)
            if cell >= 35:
                text(left+x*cell+2, top+y*cell+2, terrain["name"].replace("_", " ").title()[:12], "#111111")
    for zone in board["zones"]:
        for spot in zone["cells"]:
            draw.rectangle(box(spot["x"],spot["y"]), outline="#985be0", width=3)
        spot = zone["cells"][0]
        text(left+spot["x"]*cell+2, top+spot["y"]*cell+2, zone["name"][:22], "#6823a5")
    for wall in board["walls"]:
        points = [(int(left+a*cell/1000), int(top+b*cell/1000)) for a,b in wall["points"]]
        color = "#657f86" if wall["sight_only"] else "#30343c"
        if wall["filled"]:
            draw.polygon(points, fill=color)
        else:
            draw.line(points, fill=color, width=3)
    for tree in board.get("trees", []):
        for x, y in tree["cells"]:
            draw.rectangle(box(x, y), fill="#6d4a2d")
            if cell >= 35:
                text(left+x*cell+2, top+y*cell+2, "Tree trunk", "white")
    for x in range(width+1):
        draw.line((left+x*cell,top,left+x*cell,top+height*cell), fill="#59616a")
        if x < width:
            text(left+(x+.3)*cell,top-20,x)
    for y in range(height+1):
        draw.line((left,top+y*cell,left+width*cell,top+y*cell), fill="#59616a")
        if y < height:
            text(left-26,top+(y+.3)*cell,y)
    for marker in view.get("last_seen", []):
        x,y = marker["position"]["x"],marker["position"]["y"]
        cx,cy = left+(x+.5)*cell,top+(y+.5)*cell
        draw.line((cx-6,cy-6,cx+6,cy+6),fill="#999999",width=3)
        draw.line((cx-6,cy+6,cx+6,cy-6),fill="#999999",width=3)
        text(cx+7,cy,"Last seen")
    own = next((a for a in view["actors"] if a["entity_id"] == view["fighter"]), {})
    for actor in view["actors"]:
        position = actor.get("position")
        if not position:
            continue
        x,y = position["x"],position["y"]
        cx,cy = left+(x+.5)*cell,top+(y+.5)*cell
        radius = max(3,min(17,cell*.28))
        ally = actor["team_id"] == own.get("team_id")
        draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill="#266cac" if ally else "#ae3744",
                     outline="#ffd64e" if actor["entity_id"] == view["fighter"] else "white",width=3)
        text(cx-radius,cy-radius-16,actor["display_name"][:22],"#111111")
        hp = actor.get("hit_points") or {}
        current, maximum = hp.get("current",0),max(1,hp.get("maximum",1))
        draw.rectangle((cx-radius,cy+radius+2,cx+radius,cy+radius+7),fill="#7b2531")
        draw.rectangle((cx-radius,cy+radius+2,cx-radius+2*radius*min(1,max(0,current/maximum)),cy+radius+7),fill="#32a463")
        text(cx-radius,cy+radius+8,f"{'Ally' if ally else 'Enemy'} {current}/{maximum}","#111111")
    for obj in view.get("objects", []):
        x,y = obj["x"],obj["y"]
        draw.rectangle(box(x,y),outline="#9d642c",width=3)
        text(left+x*cell+2,top+(y+.5)*cell,obj["name"][:18],"#111111")
    if board.get("trees"):
        text(20,715,"Tree trunks block movement and sight")
    text(20,735,"Dark squares: unseen | Purple outlines: areas | Blue: allies | Red: enemies")
    output = io.BytesIO()
    image.save(output,format="PNG",compress_level=3)
    return output.getvalue()
