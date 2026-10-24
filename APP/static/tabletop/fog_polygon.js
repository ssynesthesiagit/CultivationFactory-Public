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
//   KNOWN DIFFERENCE (MAINREDMISC7F2): the engine lets a creature target a solid
//   BLOCKED wall or object cell at its near face (combat/sight_lines.py,
//   near_endpoint). This module draws a solid wall as its lit edge and does not
//   light that cell's interior, so the only cell the masks may disagree on is
//   the wall cell the viewer faces. Targeting stays engine-authoritative, and
//   tests/test_loslines3f8.py pins that exact difference.
//
// Airborne viewers also supply continuous target-plane polygons with shadow
// holes from fog-altitude.js. Roof tops and floors are separate planes; holes
// from server sense restrictions are kept separate from 3D scenery geometry.
//
// This module only draws. It re-implements no sense, range, light, or blindness
// rule, and it is never on the path that decides who can act, target, or be hit.
import {cellSegments, boundSegments, viewerSegments, rayVisible, surfaceEdges} from './sight-lines.js?v=loslines3f8';
const EPSILON = 1e-5;

function intersectRay(origin, angle, a, b) {
  const dx = Math.cos(angle), dy = Math.sin(angle), sx = b[0] - a[0], sy = b[1] - a[1];
  const cross = dx * sy - dy * sx;
  if (Math.abs(cross) < 1e-10) return null;
  const qx = a[0] - origin[0], qy = a[1] - origin[1];
  const t = (qx * sy - qy * sx) / cross, u = (qx * dy - qy * dx) / cross;
  return t >= 0 && u >= -1e-10 && u <= 1+1e-10 ? [origin[0] + t * dx, origin[1] + t * dy, t] : null;
}

// Returns the hit points and, when dynamic (darkness/smoke) segments exist, a
// parallel flag per point: true when that hit lies on a dynamic segment. Flags
// travel to fogPresentationGeometry, which must not simplify such a face away.
function rayPolygon(viewer, segments, tagDynamic = false) {
  const angles = [0, Math.PI / 2, Math.PI, Math.PI * 1.5];
  for (const [a, b] of segments) for (const [x, y] of [a, b]) {
    const angle = Math.atan2(y - viewer.y, x - viewer.x);
    angles.push(angle - EPSILON, angle, angle + EPSILON);
  }
  // atan2 returns negative angles; cardinal rays must share the same 0..2π
  // interval or the closing edge crosses the polygon and erases lit wedges.
  const ordered = angles.map(angle => (angle + 2 * Math.PI) % (2 * Math.PI)).sort((a, b) => a - b);
  const points = [], pinned = [];
  for (const angle of ordered) {
    let nearest = null, dynamicT = Infinity;
    for (const seg of segments) {
      const hit = intersectRay([viewer.x, viewer.y], angle, seg[0], seg[1]);
      if (hit && (!nearest || hit[2] < nearest[2])) nearest = hit;
      if (tagDynamic && hit && seg.dynamic && hit[2] < dynamicT) dynamicT = hit[2];
    }
    if (!nearest) continue;
    points.push([nearest[0], nearest[1]]);
    pinned.push(dynamicT <= nearest[2] + 1e-9);
  }
  return {points, pinned};
}

export function blockerSegments({walls = [], trees = [], objects = [], blockedCells = [], dynamicCells = [], centerlineCells = [], sources, width, height}) {
  const out = [], wallCellKeys = new Set(), treeCellKeys = new Set();
  const thin = new Set(centerlineCells.map(c => `${c[0]},${c[1]}`));
  // Obscurement fills its entire footprint, unlike physical wall centre runs.
  // Keep its perimeter and provenance on both bound and legacy inputs.
  const dynamic = surfaceEdges(dynamicCells).map(s=>Object.assign(s,{dynamic:true}));
  const withDarkCells = segments => {
    if (dynamicCells.length) segments.darkCells = new Set(dynamicCells.map(c =>
      Array.isArray(c) ? `${c[0]},${c[1]}` : `${c.x},${c.y}`));
    return segments;
  };
  if (sources) {
    const groundSources = sources.filter(r=>r.bottom_ft<=0 && (r.top_ft==null || r.top_ft>0));
    // Each plus arm remembers its own square, so the exact sampler can apply the engine's endpoint exemption
    // (a target inside an occluder cell is seen through that cell's own cross) without exempting its neighbours.
    const ownerCell = (segment, cells) => cells.find(([x,y]) => {
      const mx=(segment[0][0]+segment[1][0])/2, my=(segment[0][1]+segment[1][1])/2;
      return mx>=x-1e-9 && mx<=x+1+1e-9 && my>=y-1e-9 && my<=y+1+1e-9;
    });
    for (const row of groundSources) for (const segment of boundSegments(row)) {
      if (row.occluder==='centerline' && row.cells?.length) {
        const cell=ownerCell(segment,row.cells);
        if (cell) segment.occluderCell=cell;
      }
      if (row.kind==='SIGHT_BLOCKED') Object.assign(segment,{screenCells:row.cells});
      out.push(segment);
    }
    // Bound physical geometry omits obscures-only ability walls. With bound
    // sources, callers supply only these supplemental, observer-selected cells.
    // Keep independent sources even when they overlap sparse physical scenery.
    out.push(...dynamic);
    for(const [x,y] of centerlineCells) out.push(
      Object.assign([[x,y+.5],[x+1,y+.5]],{occluderCell:[x,y]}),
      Object.assign([[x+.5,y],[x+.5,y+1]],{occluderCell:[x,y]}));
    return withDarkCells(out);
  }
  const addRect = (x, y, w = 1, h = 1) => {
    out.push(...cellSegments(Array.from({length:w*h},(_,i)=>[x+i%w,y+Math.floor(i/w)])));
  };
  // The shared centre plus of one square: the same arms the bound geometry uses.
  const addPlus = (x, y) => out.push([[x,y+.5],[x+1,y+.5]], [[x+.5,y],[x+.5,y+1]]);
  for (const wall of walls) {
    // The server resolved each wall's sight shape (combat/tabletop.py): a round scenery wall or object is a plus,
    // a wall keeps its centre runs.
    if (wall.occluder === 'centerline') {
      for (const [x,y] of wall.cells || []) {
        wallCellKeys.add(`${x},${y}`);
        if (!thin.has(`${x},${y}`)) addPlus(x,y);
      }
      continue;
    }
    if (wall.cells?.length) {
      wall.cells.forEach(([x,y])=>wallCellKeys.add(`${x},${y}`));
      out.push(...cellSegments(wall.cells));
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
      thin.add(`${x},${y}`);
    }
  }
  for (const object of objects) {
    // Doors and windows are opaque table barriers while present; other objects follow their explicit blocks flag.
    // The server states the sight shape (combat/object_rules.py sight): a centre plus by default, a whole square for
    // a square-filling kind such as a door.
    if (object.hp > 0 && object.blocks) {
      if (object.occluder === 'centerline') addPlus(object.x, object.y);
      else addRect(object.x, object.y);
    }
  }
  const remainingCells=[];
  for (const cell of blockedCells) {
    const x = Array.isArray(cell) ? cell[0] : cell.x, y = Array.isArray(cell) ? cell[1] : cell.y;
    if (!thin.has(`${x},${y}`) && !wallCellKeys.has(`${x},${y}`) && !treeCellKeys.has(`${x},${y}`)) remainingCells.push([x,y]);
  }
  wallEdges.push(...cellSegments(remainingCells));
  // Independent obscuring footprints never cancel against physical scenery.
  wallEdges.push(...dynamic);
  // Dynamic barriers retain their own centre runs and caps, including when
  // they overlap thin map scenery. Deduplicate coincident source segments
  // without removing their barriers.
  const edges = new Map();
  for (const [a, b] of out) {
    const key = point => `${point[0]},${point[1]}`;
    const forward = `${key(a)}>${key(b)}`, reverse = `${key(b)}>${key(a)}`;
    if (!edges.has(reverse)) edges.set(forward, [a, b]);
  }
  const unique = new Map();
  for (const source of [...wallEdges, ...edges.values()]) {
    const [a, b] = source;
    const key = [a.join(','), b.join(',')].sort().join('>');
    const segment = [a, b];
    // A static edge drawn over a darkness face keeps the face's provenance.
    if (source.dynamic || unique.get(key)?.dynamic) segment.dynamic = true;
    unique.set(key, segment);
  }
  // Cross segments are barriers, never rectangle edges: do not cancel them as
  // shared interiors. Neighbouring tips meet exactly, including diagonals.
  for (const key of thin) {
    const [x,y] = key.split(',').map(Number);
    unique.set(`cross-h:${key}`, Object.assign([[x,y+0.5],[x+1,y+0.5]],{occluderCell:[x,y]}));
    unique.set(`cross-v:${key}`, Object.assign([[x+0.5,y],[x+0.5,y+1]],{occluderCell:[x,y]}));
  }
  return withDarkCells([...unique.values()]);
}

// One polygon per viewer; callers union them in the fog mask. Inputs are map-square coordinates.
export function visibilityPolygons(viewers, blockers, width, height) {
  const segments = [...blockers];
  const bounds = [[0, 0], [width, 0], [width, height], [0, height]];
  for (let i = 0; i < 4; i++) segments.push([bounds[i], bounds[(i + 1) % 4]]);
  const tagDynamic = segments.some(s => s.dynamic);
  const darkCells = blockers.darkCells || new Set();
  return viewers.map(viewer => {
    const origin=viewer.position || viewer;
    const usable=viewerSegments(origin,segments.filter(s=>!s.occluderCell || s.occluderCell[0]!==Math.floor(origin.x) || s.occluderCell[1]!==Math.floor(origin.y)));
    // Viewers inside darkness keep the untagged (main) presentation path.
    const insideDark=darkCells.has(`${Math.floor(origin.x)},${Math.floor(origin.y)}`);
    const {points, pinned}=rayPolygon(origin,usable,tagDynamic && !insideDark);
    const polygon={viewer:viewer.entity_id,origin:{x:origin.x,y:origin.y},
      raySegments:usable.slice(0,usable.length-4),
      solidSegments:blockers.filter(s=>!s.occluderCell),points};
    // Only scenes with darkness/smoke carry the flags, so walls-only output is unchanged.
    if (tagDynamic && !insideDark) polygon.pinned=pinned;
    return polygon;
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
  const raster=[[start[0]+nx,start[1]+ny],[end[0]+nx,end[1]+ny],
    [end[0]-nx,end[1]-ny],[start[0]-nx,start[1]-ny]];
  raster.screenCells=shadow.screenCells;
  return raster;
}

// True when a shadow carries a screen-cell exemption for cell (x,y).
function exemptsCell(shadow, x, y) {
  return (shadow.screenCells || []).some(([cx, cy]) => cx === x && cy === y);
}

// The canvas renderer and static render checks use this same mask drawing path.
//
// The drawn mask is the union of the continuous visibility polygons, followed by
// one lit square per token the service reports as perceived (fogTokenCells).
// polygons is the shape of what is lit; tokenCells is the service's own token
// authority, and the only place `seen` decides the drawn pixels is the
// squareFog diagnostic below (?fogSquares=1, and the map editor's own visibility
// preview, which passes cells without viewer geometry).
export function paintFogMask(context, width, height, seen, {polygons = [], tokenCells = [], squareFog = false, opacity = 1} = {}, scale = 64) {
  context.fillStyle = opacity === 1 ? '#fff' : `rgba(255,255,255,${opacity})`;
  if (squareFog) {
    for (let index = 0; index < seen.length; index++) if (seen[index])
      context.fillRect((index % width) * scale, Math.floor(index / width) * scale, scale, scale);
  } else {
    for (const {points, origin, raySegments, shadows: holes = [], covered = [], clips} of polygons) {
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
          // A target in an occupied screen cell sees that cell's own part of
          // the screen. Toggle those squares back into this shadow's clip only;
          // other overlapping shadows still independently obscure them.
          const exemptions=(raster.screenCells || []).map(([x,y])=>[
            [x,y],[x+1,y],[x+1,y+1],[x,y+1],
          ]);
          path([[[0,0],[width,0],[width,height],[0,height]],raster,...exemptions]);
          context.clip('evenodd');
        }
      }
      context.beginPath(); context.moveTo(points[0][0] * scale, points[0][1] * scale);
      for (let i = 1; i < points.length; i++) context.lineTo(points[i][0] * scale, points[i][1] * scale);
      context.closePath(); context.fill();
      if (shadows.length || clips) context.restore();
      // Screen-cell exemptions are additive, not another even/odd contour:
      // they may extend outside their own projected shadow. Restore each
      // exempt cell inside this viewer polygon and surface footprint, still
      // clipped by every other independent shadow.
      for (let own=0; own<shadows.length; own++) {
        const raster=canvasShadow(shadows[own],scale);
        for (const [x,y] of raster.screenCells || []) {
          context.save();
          if (clips) { path(clips); context.clip(); }
          path([points]); context.clip();
          // Another shadow that exempts this same cell does not block it; the
          // sampler (fogPointVisible) skips every shadow whose screenCells hold
          // the sampled cell. Only the other shadows still block it.
          for (let other=0; other<shadows.length; other++) if (!exemptsCell(shadows[other],x,y)) {
            const blocker=canvasShadow(shadows[other],scale);
            if (!blocker.length) continue;
            path([[[0,0],[width,0],[width,height],[0,height]],blocker]);
            context.clip('evenodd');
          }
          context.fillRect(x*scale,y*scale,scale,scale);
          context.restore();
        }
      }
      // The continuous polygon ends at a sight-blocked screen's boundary,
      // while its occupied cell is itself visible to a target inside it.
      // Paint only cells whose center passes the same ray exception used by
      // fogPointVisible; independent blockers still win.
      const screenCells=new Map();
      for (const segment of raySegments || []) for (const [x,y] of segment.screenCells || [])
        screenCells.set(`${x},${y}`,[x,y]);
      for (const [x,y] of screenCells.values())
        if (raySegments && rayVisible(origin,[x+.5,y+.5],viewerSegments({x:x+.5,y:y+.5},raySegments)))
          context.fillRect(x*scale,y*scale,scale,scale);
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

// Presentation geometry ONLY. Exact paintFogMask/fogPointVisible inputs are
// retained for memory isolation and every sight decision. Coordinates and the
// 0.5 tolerance are in map squares (maximum displacement on either cell axis).
const turn = (a,b,c) => (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
const area = p => p.reduce((s,a,i)=>s+a[0]*p[(i+1)%p.length][1]-a[1]*p[(i+1)%p.length][0],0);
const distance = (a,b) => Math.hypot(a[0]-b[0],a[1]-b[1]);
function deviation(p,a,b) {
  const dx=b[0]-a[0],dy=b[1]-a[1],d=dx*dx+dy*dy;
  const t=d ? Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/d)) : 0;
  return Math.max(Math.abs(p[0]-a[0]-t*dx),Math.abs(p[1]-a[1]-t*dy));
}

// `pinned` (optional, aligned with points) marks ray hits on darkness/smoke faces.
// A pinned point is never removed, and neither is any point next to one: a chord
// across a dynamic face would shift the projected wedge, so its shadow leaks.
export function simplifyFogOutline(points, shadow = false, origin = null, pinned = null) {
  if (points.length < 3) return points.map(p=>p.slice());
  const winding=Math.sign(area(points)) || 1;
  const nodes=points.map((p,i)=>({p:p.slice(),removed:[],pin:Boolean(pinned?.[i])}));
  // Retain the original points on each replacement edge: successive removals
  // cannot accumulate an unbounded drift. Only cut lit corners / fill shadow
  // notches, never move an edge toward less shadow.
  let changed=true;
  while (changed && nodes.length>3) {
    changed=false;
    for (let i=0;i<nodes.length && nodes.length>3;i++) {
      const previous=nodes[(i+nodes.length-1)%nodes.length],current=nodes[i],next=nodes[(i+1)%nodes.length];
      if (previous.pin || current.pin || next.pin) continue;
      const a=previous.p,b=current.p,c=next.p;
      const chain=[...previous.removed,b,...current.removed];
      const side=shadow ? -winding : winding;
      if (chain.some(p=>turn(a,p,c)*side < -1e-7)) continue;
      const collinear=Math.abs(turn(a,b,c))<1e-8;
      let tooth=false;
      if (origin && !shadow) {
        const o=[origin.x,origin.y],ra=distance(o,a),rb=distance(o,b),rc=distance(o,c);
        const angle=Math.abs(Math.atan2(turn(o,a,c),(a[0]-o[0])*(c[0]-o[0])+(a[1]-o[1])*(c[1]-o[1])));
        tooth=rb>Math.max(ra,rc)+0.5 && angle*rb<0.35;
      }
      // Very narrow inward notches are lit fingers between shadow rays.
      if (shadow && distance(a,c)<0.35) tooth=true;
      if (!collinear && !tooth && chain.some(p=>deviation(p,a,c)>0.500001)) continue;
      previous.removed=chain;
      nodes.splice(i,1); changed=true; i--;
    }
  }
  return nodes.map(n=>n.p);
}

// Clip projections (which may extend to 1e9 squares) before all presentation
// operations. This bounds precision, union cost and wedge-width classification.
function boardClip(points,width,height) {
  let out=points.map(p=>p.slice());
  for (const [axis,bound,sign] of [[0,0,1],[0,width,-1],[1,0,1],[1,height,-1]]) {
    const input=out; out=[];
    for (let i=0;i<input.length;i++) {
      const a=input[i],b=input[(i+1)%input.length],ia=(a[axis]-bound)*sign>=0,ib=(b[axis]-bound)*sign>=0;
      if (ia) out.push(a);
      if (ia!==ib) {const t=(bound-a[axis])/(b[axis]-a[axis]);out.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);}
    }
  }
  return out;
}

// Vector union: split boundary segments at intersections, discard pieces inside
// another polygon, and stitch the surviving boundary. No pixel threshold or
// raster trace can introduce fingers. Used before simplification so overlapping
// wall cells and viewer polygons have ONE outer contour and no internal seams.
export function unionFogOutlines(input) {
  const polygons=input.filter(p=>p.length>=3).map(p=>area(p)<0?p.slice().reverse():p);
  if (polygons.length<2) return polygons;
  const boxes=polygons.map(p=>[Math.min(...p.map(v=>v[0])),Math.min(...p.map(v=>v[1])),Math.max(...p.map(v=>v[0])),Math.max(...p.map(v=>v[1]))]);
  const edges=polygons.flatMap((p,owner)=>p.map((a,i)=>({a,b:p[(i+1)%p.length],owner,cuts:[0,1]})));
  for (let i=0;i<edges.length;i++) for (let j=i+1;j<edges.length;j++) {
    const e=edges[i],f=edges[j]; if(e.owner===f.owner) continue;
    if(Math.max(e.a[0],e.b[0])<Math.min(f.a[0],f.b[0])-1e-8 || Math.max(f.a[0],f.b[0])<Math.min(e.a[0],e.b[0])-1e-8 ||
       Math.max(e.a[1],e.b[1])<Math.min(f.a[1],f.b[1])-1e-8 || Math.max(f.a[1],f.b[1])<Math.min(e.a[1],e.b[1])-1e-8) continue;
    const dx=e.b[0]-e.a[0],dy=e.b[1]-e.a[1],fx=f.b[0]-f.a[0],fy=f.b[1]-f.a[1];
    const cross=dx*fy-dy*fx,qx=f.a[0]-e.a[0],qy=f.a[1]-e.a[1];
    if(Math.abs(cross)>1e-10) {
      const t=(qx*fy-qy*fx)/cross,u=(qx*dy-qy*dx)/cross;
      if(t>=-1e-8 && t<=1+1e-8 && u>=-1e-8 && u<=1+1e-8) {e.cuts.push(Math.max(0,Math.min(1,t)));f.cuts.push(Math.max(0,Math.min(1,u)));}
    } else if(Math.abs(qx*dy-qy*dx)<1e-8) {
      for(const [edge,other] of [[e,f],[f,e]]) {
        const ax=edge.b[0]-edge.a[0],ay=edge.b[1]-edge.a[1],len=ax*ax+ay*ay;
        if(!len) continue;
        for(const p of [other.a,other.b]) {const t=((p[0]-edge.a[0])*ax+(p[1]-edge.a[1])*ay)/len;if(t>0 && t<1) edge.cuts.push(t);}
      }
    }
  }
  const inside=(x,y)=>polygons.some((p,i)=>x>=boxes[i][0] && x<=boxes[i][2] && y>=boxes[i][1] && y<=boxes[i][3] && inPolygon(x,y,p));
  const key=p=>p.map(v=>Math.round(v*1e7)).join(',');
  const pieces=new Map();
  for(const e of edges) {
    e.cuts.sort((a,b)=>a-b);
    for(let i=1;i<e.cuts.length;i++) {
      const at=t=>[e.a[0]+t*(e.b[0]-e.a[0]),e.a[1]+t*(e.b[1]-e.a[1])];
      const a=at(e.cuts[i-1]),b=at(e.cuts[i]),length=distance(a,b);if(length<1e-7) continue;
      const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2,nx=-(b[1]-a[1])/length*1e-7,ny=(b[0]-a[0])/length*1e-7;
      if(inside(mx+nx,my+ny) && !inside(mx-nx,my-ny)) pieces.set(`${key(a)}>${key(b)}`,{a,b});
    }
  }
  const starts=new Map();
  for(const [id,e] of pieces) {const k=key(e.a);if(!starts.has(k)) starts.set(k,[]);starts.get(k).push(id);}
  const out=[];
  while(pieces.size) {
    const [firstId,first]=pieces.entries().next().value;const ring=[first.a];let id=firstId,edge=first;
    while(edge) {
      pieces.delete(id); if(key(edge.b)===key(ring[0])) break;
      ring.push(edge.b);id=starts.get(key(edge.b))?.find(k=>pieces.has(k));edge=pieces.get(id);
    }
    // A numerical or unsupported self-intersection must retain exact geometry,
    // rather than silently dropping a wall or exposing hidden floor.
    if(!edge) return polygons;
    if(ring.length>=3) out.push(ring);
  }
  // paintFogMask subtracts each hole independently. Keep exact source polygons
  // if the union encloses a courtyard; a negative ring is clear ground.
  return out.some(r=>area(r)<0) ? polygons : out;
}

function shadowWidth(points,origin) {
  if(points.length<3) return 0;
  if(origin) {
    const center=points.reduce((s,p)=>[s[0]+p[0]/points.length,s[1]+p[1]/points.length],[0,0]);
    const dx=center[0]-origin.x,dy=center[1]-origin.y,len=Math.hypot(dx,dy);
    if(len) {const across=points.map(p=>(p[0]*dy-p[1]*dx)/len);return Math.max(...across)-Math.min(...across);}
  }
  // Without a viewer, the narrowest caliper width is a conservative fallback.
  return Math.min(...points.map((a,i)=>{const b=points[(i+1)%points.length],len=distance(a,b);if(!len)return Infinity;
    const v=points.map(p=>turn(a,b,p)/len);return Math.max(...v)-Math.min(...v);}));
}

function wideShadowRegion(points,origin) {
  if(!origin) return shadowWidth(points,null)>=1 ? points : [];
  const center=points.reduce((s,p)=>[s[0]+p[0]/points.length,s[1]+p[1]/points.length],[0,0]);
  const dx=center[0]-origin.x,dy=center[1]-origin.y,len=Math.hypot(dx,dy);
  if(!len) return points;
  const ux=dx/len,uy=dy/len;
  const along=p=>(p[0]-origin.x)*ux+(p[1]-origin.y)*uy;
  if(points.some(p=>along(p)<=0)) return points; // A wall around the viewer.
  const angles=points.map(p=>Math.atan2((p[1]-origin.y)*ux-(p[0]-origin.x)*uy,along(p)));
  const spread=Math.max(...angles)-Math.min(...angles);
  if(spread<1e-9) return [];
  // Angular width times distance: a ray can be dappled near the trunk and
  // solid farther away. Classifying only its far-end width would leave the
  // thin near section black. A broad wall starts beyond this cut, staying solid.
  const limit=1/(2*Math.tan(spread/2)),out=[];
  for(let i=0;i<points.length;i++) {
    const a=points[i],b=points[(i+1)%points.length],da=along(a)-limit,db=along(b)-limit;
    if(da>=0) out.push(a);
    if((da>=0)!==(db>=0)){const t=da/(da-db);out.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);}
  }
  return out;
}

export function fogPresentationGeometry(polygons,width,height,scale=32) {
  polygons=polygons.map(p=>{
    if(!p.origin || p.shadows?.length || p.covered?.length || p.clips || p.pinned?.some(Boolean)) return p;
    const points=simplifyFogOutline(p.points,false,p.origin,p.pinned),o=p.origin;
    const shadows=[];
    for(let i=0;i<points.length;i++) {
      const a=points[i],b=points[(i+1)%points.length];
      const far=v=>[o.x+(v[0]-o.x)*1e6,o.y+(v[1]-o.y)*1e6];
      const hole=boardClip([a,b,far(b),far(a)],width,height);
      if(hole.length>=3 && Math.abs(area(hole))>1e-7) {
        // Retain source silhouette width: a narrow ray cut from the corner of
        // a broad wall is still a wall shadow, not a pole. Cross barriers are
        // the bound thin occluders, independent of decorative canopy artwork.
        hole.dappled=!(p.solidSegments || []).some(([s,t])=>deviation(a,s,t)<=0.500001 || deviation(b,s,t)<=0.500001);
        shadows.push(hole);
      }
    }
    return {...p,points:[[0,0],[width,0],[width,height],[0,height]],shadows};
  });
  // Darkness/smoke faces are solid barriers: their exact ray outline is the
  // presentation, so no simplification or shadow union can drop a dark wedge.
  const exact=polygons.filter(p=>p.pinned?.some(Boolean) && !p.shadows?.length && !p.covered?.length && !p.clips);
  const plain=polygons.filter(p=>!p.shadows?.length && !p.covered?.length && !p.clips && !exact.includes(p));
  const out=[...exact.map(p=>({points:p.points.map(q=>q.slice())})),
    ...unionFogOutlines(plain.map(p=>p.points)).map(points=>({points:simplifyFogOutline(points,false,plain.length===1?plain[0].origin:null)}))];
  for(const p of polygons.filter(p=>!plain.includes(p) && !exact.includes(p))) {
    const all=[],wide=[];
    for(const hole of [...(p.shadows || []),...(p.covered || [])]) {
      const clipped=boardClip(canvasShadow(hole,scale),width,height);
      if(clipped.length<3) continue;
      all.push(clipped);
      // Covered surfaces/limits and walls remain solid. Only genuinely narrow
      // cast wedges receive dappled shade, never a broad wall's pointed corner.
      const broad=(p.covered || []).includes(hole) || (p.origin && !(hole.dappled ?? hole.closed));
      const solid=broad ? clipped : wideShadowRegion(clipped,p.origin);
      if(solid.length>=3) wide.push(solid);
    }
    const simplify=rows=>unionFogOutlines(rows).map(r=>simplifyFogOutline(r,true));
    out.push({...p,points:simplifyFogOutline(p.points),shadows:simplify(all),covered:[],wideShadows:simplify(wide)});
  }
  return out;
}

export function paintFogPresentationMask(context,width,height,seen,sight,scale=32) {
  const polygons=fogPresentationGeometry(sight.polygons || [],width,height,scale);
  // Union opaque viewer cuts before applying the partial strength once. Filling
  // each cut at .58 would brighten overlapping thin shadows with viewer count.
  // This scratch mask is presentation only; exact token/hover authority is untouched.
  const partial=document.createElement('canvas');
  partial.width=width*scale; partial.height=height*scale;
  const cut=partial.getContext('2d');
  paintFogMask(cut,width,height,seen,{...sight,polygons:polygons.map(p=>({...p,shadows:p.wideShadows ?? p.shadows}))},scale);
  cut.globalCompositeOperation='destination-in';
  cut.fillStyle='rgba(255,255,255,0.58)';
  cut.fillRect(0,0,partial.width,partial.height);
  context.drawImage(partial,0,0);
  paintFogMask(context,width,height,seen,{...sight,polygons},scale);
}

// Exact sight sampler for static geometry checks. Canvas additionally gives
// zero-area closed line shadows a device-pixel footprint (see canvasShadow):
// inside the continuous polygon union, on a lit token square, or - in the
// ?fogSquares=1 diagnostic - on a square the service approved.
export function fogPointVisible(x, y, width, height, seen, polygons, tokenCells = [], squareFog = false) {
  if (x < 0 || y < 0 || x >= width || y >= height) return false;
  if (squareFog) return Boolean(seen[Math.floor(y) * width + Math.floor(x)]);
  if (tokenCells.some(([cx, cy]) => Math.floor(x) === cx && Math.floor(y) === cy)) return true;
  const cell = [Math.floor(x), Math.floor(y)];
  return polygons.some(({points, origin, raySegments, shadows = [], sampleShadows, covered = [], clips}) => points.length >= 3
    // Endpoint exemption, as the engine's near_endpoint sight (combat/sight_lines.py hit) applies it: a target in
    // an occluder cell is seen through that cell's own centre plus. Every other cell's plus still blocks.
    && (raySegments ? rayVisible(origin,[x,y], viewerSegments({x,y}, (raySegments || []).filter(segment =>
        !segment.occluderCell || segment.occluderCell[0] !== cell[0] || segment.occluderCell[1] !== cell[1]))) : inPolygon(x,y,points))
    && (!clips || clips.some(p=>inPolygon(x,y,p)))
    && ![...(sampleShadows ?? shadows),...covered].some(p=>!p.screenCells?.some(([cx,cy])=>cx===Math.floor(x) && cy===Math.floor(y)) && inPolygon(x,y,p,p.closed)));
}
