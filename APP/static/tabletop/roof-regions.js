// Authored coverage, also used by combat/roof_coverage.py. Use AUTHORED walls/doors:
// an open door or a combat breach changes vision, not the building's roof.
import {rasterizeWalls, wallCells} from './vision.js?v=rel6-2';
import defaults from './map-heights.json' with {type: 'json'};
import {wallHeightFt, roofHeightFt, walkingRoofHeightFt} from './map-heights.js';

const indoor = new Set(defaults.indoor_styles);
const cache = new Map();
const keyOf = (x, y) => `${x},${y}`;
const xy = c => Array.isArray(c) ? c : [c.x, c.y];

export function roofMapKey(map) {
  return JSON.stringify([map.width, map.height, map.background?.style, map.walls || [],
    (map.objects || []).filter(o=>['wall_section','door','gate','portcullis','window'].includes(o.kind)).map(o=>[o.kind,o.x,o.y,o.height_ft]),
    map.floors || []]);
}

// Enclosed walkable components with indoor flooring throughout. Outdoor
// courtyards and bridges are deliberately not inferred from floor paint alone.
// Adjacent enclosed rooms sharing structural wall cells form one building.
export function detectRoofRegions(map) {
  const key = roofMapKey(map);
  if (cache.has(key)) return cache.get(key);
  const {width, height} = map;
  const structuralWalls = (map.walls || []).map(wall => ({wall,
    cells: [...wallCells(wall, width, height)].map(i => keyOf(i % width, Math.floor(i / width)))}));
  const raster = rasterizeWalls(map.walls || [], width, height); // do not cut doors out
  const barriers = new Set([...raster.blocked, ...raster.sight].map(c => keyOf(...c)));
  for (const o of map.objects || []) if (['wall_section', 'door', 'gate', 'portcullis'].includes(o.kind))
    barriers.add(keyOf(o.x, o.y));
  const styles = new Map();
  for (const row of map.floors || []) for (const c of row.cells || []) styles.set(keyOf(...xy(c)), row.style);
  const isIndoor = (x,y) => indoor.has(styles.get(keyOf(x,y)) || map.background?.style);
  // Older owner maps represent entrances as one/two-square gaps rather than
  // door objects (Willow homes). Close only short collinear authored wall gaps
  // beside indoor floor for roof inference; NEVER feed these cells to vision.
  const authored = new Set(barriers);
  for (let y=0; y<height; y++) for (let x=0; x<width; x++) for (const [dx,dy] of [[1,0],[0,1]]) {
    if (!authored.has(keyOf(x,y))) continue;
    for (const length of [1,2]) {
      const gap = Array.from({length},(_,i)=>[x+dx*(i+1),y+dy*(i+1)]);
      const ex=x+dx*(length+1), ey=y+dy*(length+1);
      if (ex>=width || ey>=height || !authored.has(keyOf(ex,ey)) || gap.some(c=>authored.has(keyOf(...c)))) continue;
      if (!authored.has(keyOf(x-dx,y-dy)) || !authored.has(keyOf(ex+dx,ey+dy))) continue;
      if (gap.some(([gx,gy])=>isIndoor(gx+dy,gy+dx)||isIndoor(gx-dy,gy-dx)))
        gap.forEach(c=>barriers.add(keyOf(...c)));
    }
  }
  const visited = new Set(), rooms = [];
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const start = keyOf(x, y);
    if (barriers.has(start) || visited.has(start)) continue;
    const cells = [[x, y]], boundary = new Set();
    visited.add(start);
    let exterior = false, indoorCount = 0;
    for (let i = 0; i < cells.length; i++) {
      const [cx, cy] = cells[i];
      if (isIndoor(cx, cy)) indoorCount++;
      for (const [nx, ny] of [[cx-1,cy], [cx+1,cy], [cx,cy-1], [cx,cy+1]]) {
        if (nx < 0 || ny < 0 || nx >= width || ny >= height) { exterior = true; continue; }
        const next = keyOf(nx, ny);
        if (barriers.has(next)) { boundary.add(next); continue; }
        if (!visited.has(next)) { visited.add(next); cells.push([nx, ny]); }
      }
    }
    if (!exterior && indoorCount === cells.length) rooms.push({cells, boundary});
  }
  // Union connected rooms. Includes wall corners in the visual footprint, but
  // never fills an unroofed enclosed courtyard with a bounding rectangle.
  const buildings = [];
  while (rooms.length) {
    const room = rooms.shift();
    for (let changed = true; changed;) {
      changed = false;
      for (let i = rooms.length - 1; i >= 0; i--) if ([...rooms[i].boundary].some(c => room.boundary.has(c))) {
        const other = rooms.splice(i, 1)[0]; room.cells.push(...other.cells);
        other.boundary.forEach(c => room.boundary.add(c)); changed = true;
      }
    }
    room.cells.sort((a,b) => a[1]-b[1] || a[0]-b[0]);
    const footprint = new Set(room.cells.map(c => keyOf(...c)));
    room.boundary.forEach(c => footprint.add(c));
    for (const [cx, cy] of room.cells) for (const dx of [-1, 1]) for (const dy of [-1, 1])
      if (barriers.has(keyOf(cx+dx,cy+dy))) footprint.add(keyOf(cx+dx,cy+dy));
    const [ax, ay] = room.cells[0];
    // Windows never block roof detection, but boundary window heights do set
    // the inferred building height, matching combat/roof_coverage.py.
    const heights = structuralWalls.filter(w => w.cells.some(c => room.boundary.has(c)))
      .map(w => wallHeightFt(w.wall)).concat(structuralObjects(map).filter(o => room.boundary.has(keyOf(o.x,o.y)))
        .map(wallHeightFt));
    buildings.push({id: keyOf(ax, ay), x: ax, y: ay, cells: room.cells,
      wall_height_ft: heights.length ? Math.max(...heights) : defaults.wall_ft,
      inside: new Set(footprint), footprint: [...footprint].map(c => c.split(',').map(Number))});
  }
  buildings.sort((a,b) => a.y-b.y || a.x-b.x);
  if (cache.size >= 32) cache.delete(cache.keys().next().value);
  cache.set(key, buildings);
  return buildings;
}

const structuralObjects = map => (map.objects || []).filter(o =>
  ['wall_section','door','gate','portcullis','window'].includes(o.kind));

// Editor building height changes its actual boundary structures, not nearby
// courtyard walls. Explicit roof peaks remain independent authored choices.
export function setBuildingWallHeight(document, regions, heightFt) {
  const width = document.width_squares, height = document.height_squares;
  const covered = new Set(regions.flatMap(r => [...r.inside]));
  for (const wall of document.walls || []) if ([...wallCells(wall, width, height)]
    .some(i => covered.has(keyOf(i % width, Math.floor(i / width))))) wall.height_ft = heightFt;
  for (const object of structuralObjects(document)) if (covered.has(keyOf(object.x, object.y))) object.height_ft = heightFt;
}

export function roofSettings(region, settings = {}) {
  // Anchors are grid squares, so settings survive re-detection and editor saves.
  const override = (settings.regions || []).find(row => region.inside.has(keyOf(row.x, row.y)));
  return {enabled: settings.enabled !== false && override?.enabled !== false,
    height_ft: roofHeightFt({...settings, ...override}, region.wall_height_ft ?? defaults.wall_ft),
    style: (override?.style || settings.style) === 'red' ? 'red' : 'grey',
    climb_check: ['slippery', 'few_handholds'].includes(override?.climb_check ?? settings.climb_check)
      ? override?.climb_check ?? settings.climb_check : 'none'};
}

export function creatureHeightFt(creature) {
  return creature.position?.z != null ? creature.position.z * 5 : creature.z != null ? creature.z * 5
    : creature.altitude_ft ?? creature.altitudeFt ?? 0;
}

// Standing height on a roof: its top rounded to the nearest 5 ft, same as combat/map_heights.py.
export function roofWalkFt(region, settings = {}) {
  return walkingRoofHeightFt(roofSettings(region, settings).height_ft);
}

export function belowRoof(region, creature, settings = {}) {
  const roof = roofSettings(region, settings);
  return roof.enabled && creatureHeightFt(creature) < roof.height_ft && insideRoof(region, creature);
}

// A roof level remains useful in the picker even above an open hatch. It is
// only a reference level; the rules engine still supplies all legal routes.
export function roofLevelsAt(map, creature) {
  if (!map || !creature) return [];
  return [...new Set(detectRoofRegions(map).filter(region => roofSettings(region, map.roofs).enabled && insideRoof(region, creature))
    .map(region => roofWalkFt(region, map.roofs) / 5))].sort((a, b) => a - b);
}

export function onRoof(map, creature) {
  if (!map || !creature) return false;
  const height = creatureHeightFt(creature), p = creature.position || creature;
  return detectRoofRegions(map).some(region => {
    const roof = roofSettings(region, map.roofs);
    if (!roof.enabled || roofWalkFt(region, map.roofs) !== height || !insideRoof(region, creature)) return false;
    const width = creature.footprint?.width_cells || creature.size || 1;
    const depth = creature.footprint?.height_cells || creature.height || width;
    for (let y = Math.floor(p.y); y < p.y + depth; y++) for (let x = Math.floor(p.x); x < p.x + width; x++) {
      if (region.inside.has(keyOf(x, y)) && !(map.roofs?.openings || []).some(row => row.x === x && row.y === y && row.open === true)) return true;
    }
    return false;
  });
}

export function insideRoof(region, creature) {
  const p = creature.position || creature;
  const width = creature.footprint?.width_cells || creature.size || 1;
  const height = creature.footprint?.height_cells || creature.height || width;
  for (let y = Math.floor(p.y); y < p.y + height; y++) for (let x = Math.floor(p.x); x < p.x + width; x++)
    if (region.inside.has(keyOf(x,y))) return true;
  return false;
}

export function roofOpacity(region, {viewers = [], gm = false, enabled = true} = {}, settings = {}) {
  const roof = roofSettings(region, settings);
  if (!enabled || !roof.enabled) return 0;
  if (gm) return 0.28;
  // Only viewers beneath the roof enter its room. Flying over its footprint
  // leaves the roof visible; grid z is in five-foot squares.
  return viewers.some(c => belowRoof(region, c, settings)) ? 0 : 1;
}
