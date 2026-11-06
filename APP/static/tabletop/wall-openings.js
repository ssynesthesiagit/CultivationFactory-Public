// Opt-in wall openings. Coordinates on the wall are stored as integer hundredths
// of a square; old placements without mount_axis/mount_line are unchanged.
export const OPENING_KINDS = new Set(['door', 'gate', 'window']);

// The straight line-wall segments that can carry an opening in one square: a
// horizontal or vertical line segment that runs the square's full width or
// height and passes within half a square of its centre (so the middle line, any
// of the four edges, or any other line a hand-drawn wall follows). `line` is the
// wall coordinate in hundredths of a square; `distance` is from the centre.
function mountLines(cell, walls) {
  const cx = cell[0] + .5, cy = cell[1] + .5;
  const out = [];
  for (const wall of walls || []) {
    if (wall.shape !== 'line') continue;
    for (let i = 1; i < wall.points.length; i++) {
      const a = wall.points[i-1], b = wall.points[i];
      const axis = a[1] === b[1] ? 'h' : a[0] === b[0] ? 'v' : null;
      if (!axis) continue;
      const cross = axis === 'h' ? 1 : 0, along = 1-cross;
      const pos = along ? cy : cx, line = a[cross];
      const distance = Math.abs((cross ? cy : cx) - line);
      const lo = Math.min(a[along], b[along]), hi = Math.max(a[along], b[along]);
      if (distance <= .501 && lo <= Math.floor(pos) && hi >= Math.floor(pos)+1)
        out.push({mount_axis: axis, mount_line: Math.round(line*100), distance});
    }
  }
  return out;
}

// The square an opening on this line is stored in: the line's own square (the
// one the wall coordinate rounds into), as every mounted opening has always been.
function storedSquare(cell, mount) {
  return mount.mount_axis === 'h'
    ? {x: cell[0], y: Math.floor(mount.mount_line/100)}
    : {x: Math.floor(mount.mount_line/100), y: cell[1]};
}

// Which of the square's own lines a mount lies on, for plain-words messages.
function edgeName(cell, mount) {
  return mount.mount_axis === 'h'
    ? (mount.mount_line === cell[1]*100 ? 'top' : mount.mount_line === (cell[1]+1)*100 ? 'bottom' : 'middle')
    : (mount.mount_line === cell[0]*100 ? 'left' : mount.mount_line === (cell[0]+1)*100 ? 'right' : 'middle');
}

// The nearest straight wall to the square's centre (the old behaviour): the mount
// to use when only the square is known. Returns {mount_axis, mount_line} or null.
export function wallMount(object, walls) {
  if (!OPENING_KINDS.has(object.kind)) return null;
  const candidates = mountLines([object.x, object.y], walls);
  candidates.sort((a,b) => a.distance-b.distance);
  if (!candidates.length) return null;
  const {distance, ...mount} = candidates[0];
  return mount;
}

// Where an opening lands when the pointer is at `point` inside square `cell`: the
// straight wall line nearest the pointer, whether that is the square's middle, one
// of its four edges, or another line the wall follows. Only a line with a real
// wall behind it is offered, so the opening always sits on a wall. `bounds` (the
// map's size) drops a mount that would fall outside the map. Returns
// {mount_axis, mount_line, x, y, edge} or null.
export function snapOpening(cell, point, walls, bounds = null) {
  const reach = mount => mount.mount_axis === 'h'
    ? Math.abs(point.y - mount.mount_line/100)
    : Math.abs(point.x - mount.mount_line/100);
  const options = mountLines(cell, walls).filter(mount => {
    if (!bounds) return true;
    const square = storedSquare(cell, mount);
    return square.x >= 0 && square.y >= 0 && square.x < bounds.width && square.y < bounds.height;
  });
  if (!options.length) return null;
  options.sort((a,b) => reach(a)-reach(b) || a.distance-b.distance
    || a.mount_axis.localeCompare(b.mount_axis) || a.mount_line-b.mount_line);
  const best = options[0];
  return {...storedSquare(cell, best), mount_axis: best.mount_axis, mount_line: best.mount_line, edge: edgeName(cell, best)};
}

// The spot in a square a pointer is aimed at — 'top', 'bottom', 'left', 'right'
// or 'middle' — used to name the edge in a readable "no wall there" message. A
// pointer in the very centre reads as 'middle'; otherwise the nearer axis's edge.
export function nearestOpeningSpot(cell, point) {
  const u = Math.min(point.x - cell[0], cell[0] + 1 - point.x);   // to the nearest vertical edge
  const v = Math.min(point.y - cell[1], cell[1] + 1 - point.y);   // to the nearest horizontal edge
  if (u > 0.4 && v > 0.4) return 'middle';
  return v <= u ? (point.y - cell[1] < .5 ? 'top' : 'bottom') : (point.x - cell[0] < .5 ? 'left' : 'right');
}
export function openingRotation(object) {
  return object.rotation != null ? Number(object.rotation) : object.mount_axis === 'v' ? 90 : 0;
}
export function rotateObject(object, delta = 90) {
  object.rotation = ((openingRotation(object)+delta)%360+360)%360;
}
export function openingOffset(object) {
  if (!object.mount_axis) return {};
  return object.mount_axis === 'h' ? {offsetY: object.mount_line/100-object.y-.5}
    : {offsetX: object.mount_line/100-object.x-.5};
}
// Rendering and rule rasterization must only cut segments containing the full
// one-square aperture. A partial overlap remains an independent barrier.
function segmentContainsOpening(a, b, object) {
  const axis=a[1]===b[1]?'h':a[0]===b[0]?'v':null;
  if (!axis || !OPENING_KINDS.has(object.kind) || object.mount_axis!==axis) return false;
  const cross=axis==='h'?1:0, along=1-cross, lo=along?object.y:object.x;
  return object.mount_line===Math.round(a[cross]*100)
    && Math.min(a[along],b[along])<=lo && Math.max(a[along],b[along])>=lo+1;
}
export function wallPieces(wall, objects = []) {
  if (wall.shape !== 'line') return [wall];
  if (!openingCells(wall, objects).length) return [wall];
  const out = [];
  for (let i=1; i<wall.points.length; i++) {
    const a=wall.points[i-1], b=wall.points[i];
    const axis=a[1]===b[1]?'h':a[0]===b[0]?'v':null;
    const cross=axis==='h'?1:0, along=1-cross;
    const openings=objects.filter(o=>segmentContainsOpening(a,b,o));
    if (!openings.length) {out.push({...wall, points:[a,b]}); continue;}
    let spans=[[Math.min(a[along],b[along]),Math.max(a[along],b[along])]];
    for (const o of openings) {
      const lo=along?o.y:o.x, hi=lo+1;
      spans=spans.flatMap(([s,e])=>e<=lo||s>=hi?[[s,e]]:[[s,Math.min(e,lo)],[Math.max(s,hi),e]].filter(([l,r])=>r>l));
    }
    const point = value => cross ? [value,a[cross]] : [a[cross],value];
    for (const [s,e] of spans) out.push({...wall, points:[point(s),point(e)], door_join:true});
  }
  return out;
}
export function openingCells(wall, objects = []) {
  return objects.filter(o=>wall.shape==='line' && wall.points.slice(1).some((b,i)=>
    segmentContainsOpening(wall.points[i],b,o)
  )).map(o=>[o.mount_axis==='v'?Math.floor(o.mount_line/100):o.x, o.mount_axis==='h'?Math.floor(o.mount_line/100):o.y]);
}
