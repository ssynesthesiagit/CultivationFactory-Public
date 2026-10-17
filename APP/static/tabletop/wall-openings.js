// Opt-in wall openings. Coordinates on the wall are stored as integer hundredths
// of a square; old placements without mount_axis/mount_line are unchanged.
export const OPENING_KINDS = new Set(['door', 'gate', 'window']);
export function wallMount(object, walls) {
  if (!OPENING_KINDS.has(object.kind)) return null;
  const cx = object.x + .5, cy = object.y + .5;
  const candidates = [];
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
        candidates.push({mount_axis: axis, mount_line: Math.round(line*100), distance});
    }
  }
  candidates.sort((a,b) => a.distance-b.distance);
  if (!candidates.length) return null;
  const {distance, ...mount} = candidates[0];
  return mount;
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
