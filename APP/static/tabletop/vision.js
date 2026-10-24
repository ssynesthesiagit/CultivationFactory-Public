// Line of sight and fog of war for the tabletop (owner 2026-09-25).
//
// The editor's ground-preview ray is the engine's own (combat/gate2_grid.py SquareGrid.ray_cells, Bresenham) and
// a cell is seen when no cell strictly between the viewer and it blocks sight — exactly
// the engine's line_of_sight rule — so the fog never shows a target the rules would
// refuse, or hides one they would allow. Production table cells use perceivedCells;
// airborne drawing uses bound 3D spans in fog-altitude.js. Pure functions: Node tests.

import {openingCells} from './wall-openings.js?v=sol195';

export function rayCells(x0, y0, x1, y1) {
  const cells = [];
  const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx - dy, x = x0, y = y0;
  for (;;) {
    cells.push([x, y]);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 > -dy) { err -= dy; x += sx; }
    if (e2 < dx) { err += dx; y += sy; }
  }
  return cells;
}

// Cells that block sight: BLOCKED walls and SIGHT_BLOCKED screens.
export function opacityGrid(width, height, cellLists, centerlineCells = []) {
  const opaque = new Uint8Array(width * height);
  for (const list of cellLists) {
    for (const cell of list || []) {
      const x = Array.isArray(cell) ? cell[0] : cell.x, y = Array.isArray(cell) ? cell[1] : cell.y;
      if (x >= 0 && y >= 0 && x < width && y < height) opaque[y * width + x] = 1;
    }
  }
  for (const cell of centerlineCells) {
    const [x, y] = Array.isArray(cell) ? cell : [cell.x, cell.y];
    if (x >= 0 && y >= 0 && x < width && y < height && opaque[y * width + x]) opaque[y * width + x] = 2;
  }
  return opaque;
}

// Same integer supercover/tip-inclusive cross test as terrain_occlusion.py.
export function crossBlocks(x0, y0, x1, y1, x, y) {
  const origin = [2*x0+1, 2*y0+1], delta = [2*(x1-x0), 2*(y1-y0)];
  for (const [axis, center, low, high] of [[0,2*x+1,2*y,2*y+2], [1,2*y+1,2*x,2*x+2]]) {
    let d = delta[axis], n = center - origin[axis];
    if (!d) continue;
    if (d < 0) { n = -n; d = -d; }
    const other = origin[1-axis]*d + delta[1-axis]*n;
    if (n >= 0 && n <= d && other >= low*d && other <= high*d) return true;
  }
  return false;
}

export function* crossedCells(x0, y0, x1, y1) {
  let x=x0, y=y0, ix=0, iy=0;
  const nx=Math.abs(x1-x0), ny=Math.abs(y1-y0), sx=x1>x0?1:-1, sy=y1>y0?1:-1;
  yield [x,y];
  while (ix<nx || iy<ny) {
    const a=(1+2*ix)*ny, b=(1+2*iy)*nx;
    if (a===b) { yield [x+sx,y]; yield [x,y+sy]; x+=sx; y+=sy; ix++; iy++; }
    else if (a<b) { x+=sx; ix++; } else { y+=sy; iy++; }
    yield [x,y];
  }
}

export function lineOfSight(width, opaque, x0, y0, x1, y1) {
  const ray = rayCells(x0, y0, x1, y1);
  for (let index = 1; index < ray.length - 1; index += 1) {
    const [x, y] = ray[index];
    if (opaque[y * width + x] === 1) return false;
  }
  for (const [x,y] of crossedCells(x0,y0,x1,y1)) {
    if ((x===x0 && y===y0) || (x===x1 && y===y1)) continue;
    if (opaque[y*width+x] === 2 && crossBlocks(x0,y0,x1,y1,x,y)) return false;
  }
  return true;
}

// Bound server arena rows, not current map-editor defaults. A full source
// wins at overlapping cells; old fights pass cell-v1 and have no crosses.
export function centerlineTerrain(regions, policy = 'cell-v1') {
  if (policy !== 'cross-v1') return [];
  const thin = new Map(), full = new Set();
  for (const row of regions || []) {
    if (!['BLOCKED','SIGHT_BLOCKED'].includes(row.terrain_type)) continue;
    for (const c of row.cells || []) {
      const x=Array.isArray(c)?c[0]:c.x, y=Array.isArray(c)?c[1]:c.y, key=`${x},${y}`;
      if (row.occluder==='centerline') thin.set(key,[x,y]); else full.add(key);
    }
  }
  return [...thin].filter(([key])=>!full.has(key)).map(([,cell])=>cell);
}

// Editor counterpart of tabletop.to_battlefield (combat/tabletop.py normalize_map): explicit solid walls win.
// A row the editor has not saved yet carries no resolved occluder, so the same defaults normalize_map applies are
// filled in here: trees and bamboo default to the centre plus; a wall is a plus only when it is a filled circle
// (wall_sight_class), otherwise it fills its squares. An explicit occluder always wins.
// presets: the server's object presets (combat/object_rules.py editor_defaults). A free-standing blocking object
// (a boulder, pillar, statue ...) is seen through its centre plus, exactly as the fight's object zone sees it; a kind
// that fills its square says occluder 'cell' and is added to the editor's blocked squares by mapeditor.js instead.
function wallOccluder(wall) {
  if (wall.occluder) return wall.occluder;
  const sightClass = ['wall', 'object'].includes(wall.sight_class) ? wall.sight_class
    : (wall.shape === 'circle' && (wall.filled ?? true) ? 'object' : 'wall');
  return sightClass === 'object' ? 'centerline' : 'cell';
}

export function mapCenterlines(doc, presets={}) {
  const regions = [], width=doc.width_squares, height=doc.height_squares;
  for (const w of doc.walls || []) {
    regions.push({terrain_type:'BLOCKED', occluder:wallOccluder(w),
      cells:[...placedWallCells(w,width,height,doc.objects)].map(i=>[i%width,Math.floor(i/width)])});
  }
  for (const object of doc.objects || []) {
    const preset = presets[object.kind] || {};
    if (!(object.blocks ?? preset.blocks) || object.door_open) continue;
    const occluder = object.occluder ?? preset.sight?.occluder ?? 'centerline';
    if (occluder === 'centerline') regions.push({terrain_type:'BLOCKED', occluder, cells:[[object.x, object.y]]});
  }
  for (const tree of doc.trees || []) {
    const cells=[];
    for (let dx=0;dx<(tree.size||1);dx++) for (let dy=0;dy<(tree.size||1);dy++) cells.push([tree.x+dx,tree.y+dy]);
    regions.push({terrain_type:'BLOCKED',occluder:tree.occluder ?? 'centerline',cells});
  }
  const modes=new Map((doc.materials||[]).filter(r=>r.material==='terrain:bamboo thicket')
    .flatMap(r=>r.cells.map(c=>[c.join(','),r.occluder ?? 'centerline'])));
  for (const [x,y,size] of bambooStands(doc.materials)) for (let dx=0;dx<size;dx++) for (let dy=0;dy<size;dy++) {
    const c=[x+dx,y+dy]; regions.push({terrain_type:'SIGHT_BLOCKED',occluder:modes.get(c.join(',')),cells:[c]});
  }
  return centerlineTerrain(regions,'cross-v1');
}

// 1 = seen by at least one viewer ({x, y}); viewers always see their own cell.
export function visibleCells(width, height, opaque, viewers, rangeCells = Infinity) {
  const seen = new Uint8Array(width * height);
  for (const viewer of viewers) {
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const index = y * width + x;
        if (seen[index]) continue;
        if (Math.max(Math.abs(x - viewer.x), Math.abs(y - viewer.y)) > rangeCells) continue;
        if (lineOfSight(width, opaque, viewer.x, viewer.y, x, y)) seen[index] = 1;
      }
    }
  }
  return seen;
}

// Fog inputs from TabletopService.fog_perception. These helpers only combine the
// server's decisions for whichever tokens the player selected to view.
export function perceivedCells(width, height, viewers, perception) {
  const seen = new Uint8Array(width * height);
  for (const viewer of viewers || []) {
    for (const [x, y] of perception?.[viewer.entity_id]?.cells || []) {
      if (x >= 0 && y >= 0 && x < width && y < height) seen[y * width + x] = 1;
    }
  }
  return seen;
}

export function perceivedCreatures(viewers, perception) {
  const seen = new Set();
  for (const viewer of viewers || []) {
    for (const id of perception?.[viewer.entity_id]?.creatures || []) seen.add(id);
  }
  return seen;
}

// An airborne viewer can see an object's top/near face while the floor below
// it is hidden. Ground/older projections retain the existing floor policy.
export function perceivedObjects(viewers, perception, objects) {
  const seen=new Set();
  for (const viewer of viewers || []) {
    const row=perception?.[viewer.entity_id] || {};
    if (Array.isArray(row.objects)) for (const id of row.objects) seen.add(id);
    else {
      const cells=new Set((row.cells || []).map(c=>c.join(',')));
      for (const obj of objects || []) if (cells.has(`${obj.x},${obj.y}`)) seen.add(obj.id);
    }
  }
  return seen;
}

// Actual token-hiding decision: activity/HP never controls visibility. Downed
// tokens are drawn when the server says any selected viewer perceives them.
export function tokenHiddenByFog(actor, viewers, perception, fogEnabled = true) {
  if (!fogEnabled || !viewers?.length || viewers.some(row => row.entity_id === actor.entity_id)) return false;
  return !perceivedCreatures(viewers, perception).has(actor.entity_id);
}

// Presentation only: union knowledge from the chosen viewers, with sight from
// any viewer taking priority. Never use a reason for an unlisted creature.
export function tokenSensePresentation(actor, viewers, perception, fogEnabled = true) {
  const plain = {sensed: false, senseText: ''};
  if (!fogEnabled || !viewers?.length || viewers.some(row => row.entity_id === actor.entity_id)) return plain;
  const reasons = new Set();
  for (const viewer of viewers) {
    const row = perception?.[viewer.entity_id];
    if (!row?.creatures?.includes(actor.entity_id)) continue;
    const senses = row.sensed_creatures?.[actor.entity_id];
    if (!senses?.length) return plain;
    for (const sense of senses) reasons.add(sense);
  }
  if (!reasons.size) return plain;
  const explanations = {
    spiritual_sense: 'you sense it with Spiritual Sense',
    blindsight: 'you sense it with Blindsight',
    tremorsense: 'you feel its location through vibrations (Tremorsense)',
    spiritual_truesight: 'you sense its spiritual location with Spiritual Truesight',
    pinpointed: 'an effect tells you its location',
    allied_location: "you know your ally's location",
    known_location: 'you know its location',
  };
  const how = [...new Set([...reasons].map(reason => explanations[reason] || explanations.known_location))];
  return {sensed: true, senseText: `You can't see this creature; ${how.join(' or ')}.`};
}

// ---------------------------------------------------------------- walls to cells
// A line-for-line port of combat/tabletop.py (wall_cells / rasterize) so the map editor
// previews exactly the squares the engine will treat as walls.  Points are in squares.
const distance = (dx, dy) => Math.sqrt(dx * dx + dy * dy);

function segmentCells(a, b, width, height, out) {
  const length = distance(b[0] - a[0], b[1] - a[1]);
  const steps = Math.max(1, Math.trunc(length * 8));
  for (let index = 0; index <= steps; index += 1) {
    const t = index / steps;
    const x = a[0] + (b[0] - a[0]) * t;
    const y = a[1] + (b[1] - a[1]) * t;
    const cx = Math.min(Math.floor(x), width - 1), cy = Math.min(Math.floor(y), height - 1);
    if (cx >= 0 && cy >= 0 && cx < width && cy < height) out.add(cy * width + cx);
  }
}

export function wallCells(wall, width, height) {
  const out = new Set();
  const points = wall.points;
  if (wall.shape === "line") {
    for (let index = 0; index + 1 < points.length; index += 1) segmentCells(points[index], points[index + 1], width, height, out);
    return out;
  }
  const [[x0, y0], [x1, y1]] = points;
  if (wall.shape === "rect") {
    const left = Math.min(x0, x1), right = Math.max(x0, x1), top = Math.min(y0, y1), bottom = Math.max(y0, y1);
    if (wall.filled) {
      for (let x = 0; x < width; x += 1) for (let y = 0; y < height; y += 1) {
        if (left <= x + 0.5 && x + 0.5 <= right && top <= y + 0.5 && y + 0.5 <= bottom) out.add(y * width + x);
      }
      return out;
    }
    const corners = [[left, top], [right, top], [right, bottom], [left, bottom], [left, top]];
    for (let index = 0; index + 1 < corners.length; index += 1) segmentCells(corners[index], corners[index + 1], width, height, out);
    return out;
  }
  const radius = distance(x1 - x0, y1 - y0);
  for (let x = 0; x < width; x += 1) for (let y = 0; y < height; y += 1) {
    const d = distance(x + 0.5 - x0, y + 0.5 - y0);
    if ((wall.filled && d <= radius) || (!wall.filled && Math.abs(d - radius) <= 0.5)) out.add(y * width + x);
  }
  return out;
}

// {blocked: [[x, y]], sight: [[x, y]]} for a map's walls (sight-only cells exclude blocked ones).
// Squares painted with bamboo that grow together into one large stand, found as zonepaint.js M.bamboo draws them and
// as the server's combat/tabletop.py bamboo_stands does: every whole 3x3 block, then every whole 2x2 block, top-left
// corners in reading order.  [[x, y, size], ...].  A stand blocks sight (owner 2026-09-29).
export function bambooStands(materials) {
  const cells = (materials || []).filter(row => row.material === "terrain:bamboo thicket").flatMap(row => row.cells)
    .sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const have = new Set(cells.map(([x, y]) => `${x},${y}`)), used = new Set(), stands = [];
  for (const size of [3, 2]) {
    for (const [x, y] of cells) {
      const block = [];
      for (let dy = 0; dy < size; dy += 1) for (let dx = 0; dx < size; dx += 1) block.push(`${x + dx},${y + dy}`);
      if (block.some(key => !have.has(key) || used.has(key))) continue;
      block.forEach(key => used.add(key));
      stands.push([x, y, size]);
    }
  }
  return stands;
}

// Subtract apertures from matching segments before unioning a polyline's cells.
// A crossing segment remains a barrier even when it shares an opening square.
function placedWallCells(wall, width, height, objects = []) {
  const segments = wall.shape === 'line'
    ? wall.points.slice(1).map((b,i)=>({...wall,points:[wall.points[i],b]})) : [wall];
  const cells = new Set();
  for (const segment of segments) {
    const gaps = new Set(openingCells(segment, objects).map(([x,y])=>y*width+x));
    for (const index of wallCells(segment,width,height)) if (!gaps.has(index)) cells.add(index);
  }
  return cells;
}

export function rasterizeWalls(walls, width, height, objects = []) {
  const blocked = new Set(), sight = new Set();
  for (const wall of walls || []) {
    for (const index of placedWallCells(wall, width, height, objects)) (wall.blocks === "sight" ? sight : blocked).add(index);
  }
  const toCells = set => [...set].sort((a, b) => a - b).map(index => [index % width, Math.floor(index / width)]);
  return {blocked: toCells(blocked), sight: toCells(new Set([...sight].filter(index => !blocked.has(index))))};
}
