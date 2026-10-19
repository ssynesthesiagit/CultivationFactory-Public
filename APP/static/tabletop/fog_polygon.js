// Fog of war: what the table draws, and what the service decides.
//
// THE CONTRACT (owner: "rules stay the same, just a visual change for the fog of war").
//
//   DRAWN FOG is the continuous visibility polygon. Its edge is where the dark
//   meets the wall line, and a doorway gap is a continuous wedge, so the mask is
//   NOT clipped to whole squares: clipping to the service's cells quantises the
//   sloping edge of a doorway back into the square staircase the owner rejected.
//   A viewer the service limits (Blinded, darkness) is painted from the same
//   geometry, so the floor a fighter cannot actually perceive is shown as bare
//   terrain: no floor detail is ever invented, and the mask is the map's own art
//   rather than a second, blurrier copy of it.
//
//   TOKENS are the service's business, and stay server-authoritative squares. A
//   token the service reports as perceived is always drawn, on a lit square under
//   it even where the polygon edge falls inside that square, so a creature the
//   rules let you see is never lost in the dark. A token the service does not
//   report is hidden, and stays hidden even when the polygon lights that spot:
//   the board removes the token itself (see vision.js tokenHiddenByFog), and this
//   module lights no square on its behalf. Targeting is likewise unchanged, so
//   the drawing can never show a creature the rules refuse as a target.
//
// Airborne viewers also supply continuous target-plane polygons with shadow
// holes from fog-altitude.js. Roof tops and floors are separate planes; holes
// from server sense restrictions are kept separate from 3D scenery geometry.
//
// This module only draws. It re-implements no sense, range, light, or blindness
// rule, and it is never on the path that decides who can act, target, or be hit.
const EPSILON = 1e-5;

function intersectRay(origin, angle, a, b) {
  const dx = Math.cos(angle), dy = Math.sin(angle), sx = b[0] - a[0], sy = b[1] - a[1];
  const cross = dx * sy - dy * sx;
  if (Math.abs(cross) < 1e-10) return null;
  const qx = a[0] - origin[0], qy = a[1] - origin[1];
  const t = (qx * sy - qy * sx) / cross, u = (qx * dy - qy * dx) / cross;
  return t >= 0 && u >= 0 && u <= 1 ? [origin[0] + t * dx, origin[1] + t * dy, t] : null;
}

function rayPolygon(viewer, segments) {
  const angles = [0, Math.PI / 2, Math.PI, Math.PI * 1.5];
  for (const [a, b] of segments) for (const [x, y] of [a, b]) {
    const angle = Math.atan2(y - viewer.y, x - viewer.x);
    angles.push(angle - EPSILON, angle, angle + EPSILON);
  }
  // atan2 returns negative angles; cardinal rays must share the same 0..2π
  // interval or the closing edge crosses the polygon and erases lit wedges.
  const ordered = angles.map(angle => (angle + 2 * Math.PI) % (2 * Math.PI)).sort((a, b) => a - b);
  return ordered.map(angle => {
    let nearest = null;
    for (const [a, b] of segments) {
      const hit = intersectRay([viewer.x, viewer.y], angle, a, b);
      if (hit && (!nearest || hit[2] < nearest[2])) nearest = hit;
    }
    return nearest ? [nearest[0], nearest[1]] : null;
  }).filter(Boolean);
}

export function blockerSegments({walls = [], trees = [], objects = [], blockedCells = [], dynamicCells = [], centerlineCells = [], width, height}) {
  const out = [], wallCellKeys = new Set(), treeCellKeys = new Set();
  const thin = new Set(centerlineCells.map(c => `${c[0]},${c[1]}`));
  const addRect = (x, y, w = 1, h = 1) => {
    const points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
    for (let i = 0; i < 4; i++) out.push([points[i], points[(i + 1) % 4]]);
  };
  for (const wall of walls) {
    if (wall.occluder === 'centerline') {
      for (const [x,y] of wall.cells || []) {
        wallCellKeys.add(`${x},${y}`);
        if (!thin.has(`${x},${y}`)) addRect(x,y);
      }
      continue;
    }
    const pts = wall.points || [];
    if (wall.shape === 'line') for (let i = 0; i + 1 < pts.length; i++) out.push([pts[i], pts[i + 1]]);
    else if (wall.shape === 'rect' && pts.length >= 2) {
      const [a, b] = pts, l = Math.min(a[0], b[0]), r = Math.max(a[0], b[0]), t = Math.min(a[1], b[1]), d = Math.max(a[1], b[1]);
      const corners = [[l, t], [r, t], [r, d], [l, d]];
      for (let i = 0; i < 4; i++) out.push([corners[i], corners[(i + 1) % 4]]);
    } else if (wall.shape === 'circle' && pts.length >= 2) {
      const [cx, cy] = pts[0], radius = Math.hypot(pts[1][0] - cx, pts[1][1] - cy);
      // Keep the chord error below half a display pixel, including large circles.
      const count = Math.max(32, Math.ceil(Math.PI / Math.acos(1 - Math.min(1, 0.5 / (64 * radius || 1)))));
      const points = Array.from({length: count}, (_, i) => [cx + Math.cos(i * 2 * Math.PI / count) * radius, cy + Math.sin(i * 2 * Math.PI / count) * radius]);
      for (let i = 0; i < count; i++) out.push([points[i], points[(i + 1) % count]]);
    }
    // Rasterized wall cells are omitted below so the actual drawn line, not a square, defines the edge.
    for (const [x, y] of wall.cells || []) wallCellKeys.add(`${x},${y}`);
  }
  // Coincident vector walls remain barriers even when drawn in reverse. Only
  // shared edges of raster rectangles can be removed as interior boundaries.
  const wallEdges = out.splice(0);
  for (const tree of trees) {
    const size = tree.size === 2 ? 2 : 1;
    for (let dy = 0; dy < size; dy++) for (let dx = 0; dx < size; dx++) {
      const x = tree.x + dx, y = tree.y + dy; treeCellKeys.add(`${x},${y}`);
      if (!thin.has(`${x},${y}`)) addRect(x, y);
    }
  }
  for (const object of objects) {
    // Doors and windows are opaque table barriers while present; other objects follow their explicit blocks flag.
    if (object.hp > 0 && object.blocks) addRect(object.x, object.y);
  }
  for (const cell of blockedCells) {
    const x = Array.isArray(cell) ? cell[0] : cell.x, y = Array.isArray(cell) ? cell[1] : cell.y;
    if (!thin.has(`${x},${y}`) && !wallCellKeys.has(`${x},${y}`) && !treeCellKeys.has(`${x},${y}`)) addRect(x, y);
  }
  // Smoke/darkness walls stay full barriers even over thin map scenery.
  // Keep them out of rectangle edge cancellation with static geometry.
  for (const c of dynamicCells) {
    const before=out.length;
    addRect(Array.isArray(c)?c[0]:c.x,Array.isArray(c)?c[1]:c.y);
    wallEdges.push(...out.splice(before));
  }
  // Collapse shared square edges so a dense wall remains a perimeter-sized ray-cast input.
  const edges = new Map();
  for (const [a, b] of out) {
    const key = point => `${point[0]},${point[1]}`;
    const forward = `${key(a)}>${key(b)}`, reverse = `${key(b)}>${key(a)}`;
    if (edges.has(reverse)) edges.delete(reverse); else edges.set(forward, [a, b]);
  }
  const unique = new Map();
  for (const [a, b] of [...wallEdges, ...edges.values()]) {
    const key = [a.join(','), b.join(',')].sort().join('>');
    unique.set(key, [a, b]);
  }
  // Cross segments are barriers, never rectangle edges: do not cancel them as
  // shared interiors. Neighbouring tips meet exactly, including diagonals.
  for (const key of thin) {
    const [x,y] = key.split(',').map(Number);
    unique.set(`cross-h:${key}`, Object.assign([[x,y+0.5],[x+1,y+0.5]],{occluderCell:[x,y]}));
    unique.set(`cross-v:${key}`, Object.assign([[x+0.5,y],[x+0.5,y+1]],{occluderCell:[x,y]}));
  }
  return [...unique.values()];
}

// One polygon per viewer; callers union them in the fog mask. Inputs are map-square coordinates.
export function visibilityPolygons(viewers, blockers, width, height) {
  const segments = [...blockers];
  const bounds = [[0, 0], [width, 0], [width, height], [0, height]];
  for (let i = 0; i < 4; i++) segments.push([bounds[i], bounds[(i + 1) % 4]]);
  return viewers.map(viewer => {
    const origin=viewer.position || viewer;
    const usable=segments.filter(s=>!s.occluderCell || s.occluderCell[0]!==Math.floor(origin.x) || s.occluderCell[1]!==Math.floor(origin.y));
    return {viewer:viewer.entity_id,points:rayPolygon(origin,usable)};
  });
}

// The squares the service's token decision requires us to light: one per drawn
// token the service reports as perceived. `hidden` is exactly that decision -
// tabletop.js builds it from vision.js tokenHiddenByFog for a fighter, and from
// the service's own square answer for a dropped item, a door or a crate - and
// such a token is left off the table, so nothing is lit on its behalf. It is
// deliberately not the same as a token the rules dim with the Invisible or
// Hidden condition (`unseen`, drawn at 45% opacity): that is a decision about
// the token, not about the square, and the square belongs to whoever is looking.
export function fogTokenCells(tokens, closedRoofTops = new Map()) {
  const cells = new Map();
  for (const token of tokens) {
    if (token.hidden) continue;
    const x = token.x + (token.offsetX || 0), y = token.y + (token.offsetY || 0);
    const width = (token.size || 1) * (token.scale || 1), height = (token.height || token.size || 1) * (token.scale || 1);
    for (let cy = Math.floor(y); cy < Math.ceil(y + height); cy++)
      for (let cx = Math.floor(x); cx < Math.ceil(x + width); cx++) {
        const key=`${cx},${cy}`, roof=closedRoofTops.get(key);
        // Furniture/items drawn below closed roof art cannot light its tiles.
        // Creature exceptions retain the service's token-authority contract.
        const top=(token.altitudeFt ?? 0)+(token.height_ft ?? 0);
        if ((token.object || token.item) && roof!=null && top<roof) continue;
        cells.set(key, [cx, cy]);
      }
  }
  return [...cells.values()];
}

// When the roof audience opens a room (or switches roofs off), its art no
// longer covers the floor. Never use a roof-top mask to reveal that interior.
export function roofPresentationPolygons(polygons, openCells) {
  const closed = rectangle => rectangle.roof===false || !openCells.has(rectangle[0].join(','));
  return polygons.map(p=>({...p,
    ...(p.covered ? {covered:p.covered.filter(closed)} : {}),
    ...(p.clips ? {clips:p.clips.filter(closed)} : {})}))
    .filter(p=>!p.clips || p.clips.length);
}

// Canvas filled clips discard a two-point (collinear) closed shadow. Render
// those exact sight barriers as a two-device-pixel strip instead: one pixel
// on either side makes an aligned sample fully dark, not half-antialiased.
// This is a raster policy, not extra wall thickness in the numerical/server
// sight rule. Exclusive endpoints retreat by one pixel, retaining clear tops.
// Applied to every closed line shadow, regardless of its scenery source.
function canvasShadow(shadow, scale) {
  if (shadow.length !== 2 || !shadow.closed) return shadow;
  const [a,b] = shadow, dx=b[0]-a[0], dy=b[1]-a[1];
  const length=Math.hypot(dx,dy), pixel=1/scale;
  if (!length) return [];
  const ux=dx/length, uy=dy/length, inset=shadow.openEnds ? pixel : 0;
  if (length<=2*inset) return [];
  const start=[a[0]+ux*inset,a[1]+uy*inset], end=[b[0]-ux*inset,b[1]-uy*inset];
  const nx=-uy*pixel, ny=ux*pixel;
  return [[start[0]+nx,start[1]+ny],[end[0]+nx,end[1]+ny],
    [end[0]-nx,end[1]-ny],[start[0]-nx,start[1]-ny]];
}

// The canvas renderer and static render checks use this same mask drawing path.
//
// The drawn mask is the union of the continuous visibility polygons, followed by
// one lit square per token the service reports as perceived (fogTokenCells).
// polygons is the shape of what is lit; tokenCells is the service's own token
// authority, and the only place `seen` decides the drawn pixels is the
// squareFog diagnostic below (?fogSquares=1, and the map editor's own visibility
// preview, which passes cells without viewer geometry).
export function paintFogMask(context, width, height, seen, {polygons = [], tokenCells = [], squareFog = false} = {}, scale = 64) {
  context.fillStyle = '#fff';
  if (squareFog) {
    for (let index = 0; index < seen.length; index++) if (seen[index])
      context.fillRect((index % width) * scale, Math.floor(index / width) * scale, scale, scale);
  } else {
    for (const {points, shadows: holes = [], covered = [], clips} of polygons) {
      const shadows=[...holes,...covered];
      if (points.length < 3) continue;
      const path = rows => {
        context.beginPath();
        for (const row of rows) {
          context.moveTo(row[0][0]*scale,row[0][1]*scale);
          for (const [x,y] of row.slice(1)) context.lineTo(x*scale,y*scale);
          context.closePath();
        }
      };
      if (shadows.length || clips) {
        context.save();
        if (clips) { path(clips); context.clip(); }
        // Intersect the complements individually; even/odd filling all holes
        // at once would wrongly relight overlaps between obstacle shadows.
        for (const shadow of shadows) {
          const raster=canvasShadow(shadow,scale);
          if (!raster.length) continue;
          path([[[0,0],[width,0],[width,height],[0,height]],raster]);
          context.clip('evenodd');
        }
      }
      context.beginPath(); context.moveTo(points[0][0] * scale, points[0][1] * scale);
      for (let i = 1; i < points.length; i++) context.lineTo(points[i][0] * scale, points[i][1] * scale);
      context.closePath(); context.fill();
      if (shadows.length || clips) context.restore();
    }
  }
  for (const [x, y] of tokenCells) if (x >= 0 && y >= 0 && x < width && y < height)
    context.fillRect(x * scale, y * scale, scale, scale);
}

function inPolygon(x, y, points, boundary = false) {
  const onSegment=([xi,yi],[xj,yj])=>Math.abs((x-xi)*(yj-yi)-(y-yi)*(xj-xi))<1e-9
    && x>=Math.min(xi,xj)-1e-9 && x<=Math.max(xi,xj)+1e-9
    && y>=Math.min(yi,yj)-1e-9 && y<=Math.max(yi,yj)+1e-9;
  if (points.openEdges?.some(([a,b])=>onSegment(a,b))) return false;
  if (points.openEnds && points.some(([px,py])=>Math.abs(x-px)<1e-9 && Math.abs(y-py)<1e-9)) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i], [xj, yj] = points[j];
    if (onSegment([xi,yi],[xj,yj])) return boundary;
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Exact sight sampler for static geometry checks. Canvas additionally gives
// zero-area closed line shadows a device-pixel footprint (see canvasShadow):
// inside the continuous polygon union, on a lit token square, or - in the
// ?fogSquares=1 diagnostic - on a square the service approved.
export function fogPointVisible(x, y, width, height, seen, polygons, tokenCells = [], squareFog = false) {
  if (x < 0 || y < 0 || x >= width || y >= height) return false;
  if (squareFog) return Boolean(seen[Math.floor(y) * width + Math.floor(x)]);
  if (tokenCells.some(([cx, cy]) => Math.floor(x) === cx && Math.floor(y) === cy)) return true;
  return polygons.some(({points, shadows = [], sampleShadows, covered = [], clips}) => points.length >= 3
    && inPolygon(x,y,points) && (!clips || clips.some(p=>inPolygon(x,y,p)))
    && ![...(sampleShadows ?? shadows),...covered].some(p=>inPolygon(x,y,p,p.closed)));
}
