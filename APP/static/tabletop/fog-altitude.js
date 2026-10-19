// Continuous shadows on a target plane, from the service's bound 3D spans.
// Used by table fog for airborne viewers. No ability rules or height defaults:
// map-heights consumers already resolved the heights before this projection.

const rectangle = (x, y) => [[x,y],[x+1,y],[x+1,y+1],[x,y+1]];
const CIRCLE_STEPS = 16;
const MAX_VEGETATION_CIRCLES = 1024;
const vegetationCache = new WeakMap();

function cellSeed(x, y) {
  let n = (Math.imul(x | 0, 0x9e3779b1) ^ Math.imul(y | 0, 0x85ebca77)) >>> 0;
  n ^= n >>> 16; n = Math.imul(n, 0x7feb352d); n ^= n >>> 15;
  return n >>> 0;
}

function vegetationCircles(geometry) {
  if (vegetationCache.has(geometry)) return vegetationCache.get(geometry);
  const byCell = new Map();
  let circleCount = 0;
  const treeCells = new Set(geometry.treeCells || []), bambooCells = new Set(geometry.bambooCells || []);
  const treeRoots = new Set((geometry.trees || []).map(tree => `${tree.x},${tree.y}`));
  for (const row of geometry.volumes || []) {
    if (row.mode !== 'centerline') continue;
    const key = `${row.x},${row.y}`;
    if (!treeCells.has(key) && !bambooCells.has(key)) continue;
    if (treeCells.has(key)) {
      if (!treeRoots.has(key)) continue;
      const bottom=row.bottom_ft ?? 0, height=row.top_ft == null ? 30 : row.top_ft;
      if (height>bottom && circleCount+2<=MAX_VEGETATION_CIRCLES) {
        byCell.set(key,[
          {x:row.x+.5,y:row.y+.5,radius:.45,bottom,height,kind:'volume'},
          {x:row.x+.5,y:row.y+.5,radius:1.6,height:bottom+(height-bottom)*.82,kind:'surface'},
        ]);
        circleCount+=2;
      }
    } else {
      let seed = cellSeed(row.x,row.y), random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
      const count=3+Math.floor(random()*4), bottom=row.bottom_ft ?? 0, height=row.top_ft == null ? 20 : row.top_ft;
      if (height<=bottom) continue;
      const stalks=[];
      for (let i=0;i<count;i++) {
        const radius=(.3+random()*.3)/5;
        stalks.push({x:row.x+radius+random()*(1-2*radius),y:row.y+radius+random()*(1-2*radius),radius,bottom,height,kind:'volume'});
      }
      const retained=stalks.slice(0,Math.max(0,MAX_VEGETATION_CIRCLES-circleCount));
      if (retained.length) { byCell.set(key,retained); circleCount+=retained.length; }
    }
  }
  vegetationCache.set(geometry,byCell);
  return byCell;
}

function sceneryFootprints(volumes) {
  // Cell spans are the server's per-cell sight rule. Drawing each cell or
  // centerline cross as its own shadow makes dense scenery read as a staircase
  // of grid cells. Join touching spans of the same kind and height for drawing;
  // server perception remains the authority for rules.
  const rows = volumes || [];
  const bySpan = new Map();
  for (const row of rows) {
    const key = `${row.mode ?? 'cell'}:${row.bottom_ft ?? 0}:${row.top_ft ?? ''}`;
    if (!bySpan.has(key)) bySpan.set(key, []);
    bySpan.get(key).push(row);
  }
  const groups = [];
  for (const [key, spans] of bySpan) {
    const remaining = new Map(spans.map(row => [`${row.x},${row.y}`, row]));
    while (remaining.size) {
      const first = remaining.values().next().value;
      remaining.delete(`${first.x},${first.y}`);
      const cells = [first], queue = [first];
      while (queue.length) {
        const row = queue.pop();
        for (const [x,y] of [[row.x-1,row.y],[row.x+1,row.y],[row.x,row.y-1],[row.x,row.y+1]]) {
          const neighbor = remaining.get(`${x},${y}`);
          if (neighbor) { remaining.delete(`${x},${y}`); cells.push(neighbor); queue.push(neighbor); }
        }
      }
      groups.push({mode:first.mode ?? 'cell', bottom_ft:first.bottom_ft ?? 0,
        top_ft:first.top_ft ?? null, cells});
    }
  }
  return groups;
}

function hull(points) {
  const sorted = points.slice().sort((a,b)=>a[0]-b[0] || a[1]-b[1]);
  const cross = (a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  const half = rows => {
    const out=[];
    for (const p of rows) {
      while (out.length>1 && cross(out.at(-2),out.at(-1),p)<=0) out.pop();
      out.push(p);
    }
    return out;
  };
  return [...half(sorted).slice(0,-1),...half(sorted.reverse()).slice(0,-1)];
}

function rectangularFootprint(cells) {
  const xs=cells.map(({x})=>x), ys=cells.map(({y})=>y);
  const width=Math.max(...xs)-Math.min(...xs)+1, height=Math.max(...ys)-Math.min(...ys)+1;
  return cells.length===width*height;
}

function shadowsAt(origin, eyeFt, targetFt, geometry, width, height, smooth = true) {
  const shadows=[];
  // A finite obstacle produces a finite shadow: merely dropping every wall
  // below the viewer would incorrectly reveal ground immediately behind it.
  const project = (points, bottom, top, surface=false, closed=false) => {
    if (targetFt===eyeFt) {
      if (surface || bottom>eyeFt || (top!=null && top<=eyeFt)) return;
    } else if (bottom>=eyeFt || (top!=null && top<=targetFt)) return;
    const near=targetFt===eyeFt ? 1 : (eyeFt-targetFt)/(eyeFt-Math.max(bottom,targetFt));
    const far=targetFt===eyeFt || top==null || top>=eyeFt ? 1e7 * (width+height+1)
      : (eyeFt-targetFt)/(eyeFt-top);
    const factors=surface ? [far] : [near,far];
    const shadow=hull(factors.flatMap(f=>points.map(([x,y])=>
      [origin.x+(x-origin.x)*f,origin.y+(y-origin.y)*f])));
    shadow.closed=surface || closed;
    if (closed && !surface && top!=null && top<eyeFt && targetFt<eyeFt) {
      if (shadow.length===2) shadow.openEnds=true;
      else shadow.openEdges=[points.map(([x,y])=>[origin.x+(x-origin.x)*far,origin.y+(y-origin.y)*far])];
    }
    if (shadow.length>=3 || (closed && shadow.length===2)) shadows.push(shadow);
  };
  const projectCircle = ({x,y,radius,bottom=0,height:top,kind='volume'}) => {
    if (kind==='surface' && (targetFt>=eyeFt || top<=targetFt || top>=eyeFt)) return;
    if (kind==='volume' && (bottom>=eyeFt || (top!=null && top<=targetFt))) return;
    const near=targetFt===eyeFt ? 1 : (eyeFt-targetFt)/(eyeFt-Math.max(bottom,targetFt));
    const far=targetFt===eyeFt || top==null || top>=eyeFt ? 1e7*(width+height+1) : (eyeFt-targetFt)/(eyeFt-top);
    const points=Array.from({length:CIRCLE_STEPS},(_,i)=>{
      const angle=2*Math.PI*i/CIRCLE_STEPS;
      return [x+Math.cos(angle)*radius,y+Math.sin(angle)*radius];
    });
    const factors=kind==='surface' ? [far] : [near,far];
    const shadow=hull(factors.flatMap(f=>points.map(([px,py])=>[origin.x+(px-origin.x)*f,origin.y+(py-origin.y)*f])));
    shadow.closed=true;
    shadows.push(shadow);
  };
  const vegetationByCell = smooth ? vegetationCircles(geometry) : new Map();
  const treeCells = new Set(geometry.treeCells || []), bambooCells = new Set(geometry.bambooCells || []);
  if (smooth) {
    for (const group of sceneryFootprints(geometry.volumes)) {
      const {bottom_ft:bottom,top_ft:top,cells}=group;
      if (group.mode==='centerline' && cells.some(({x,y})=>origin.x===x+.5 && origin.y===y+.5)
        && bottom<=eyeFt && (top==null || eyeFt<top)) {
        shadows.push([[0,0],[width,0],[width,height],[0,height]]);
        continue;
      }
      if (group.mode==='centerline') {
        // Vegetation uses bounded circular stalks/trunks where available.
        // Cells beyond the drawing budget retain their original arm shadow.
        for (const {x,y} of cells) {
          const key=`${x},${y}`;
          const circles=(treeCells.has(key)||bambooCells.has(key)) ? vegetationByCell.get(key) : null;
          if (circles?.length) { for (const circle of circles) projectCircle(circle); continue; }
          project([[x,y+0.5],[x+1,y+0.5]],bottom,top,false,true);
          project([[x+0.5,y],[x+0.5,y+1]],bottom,top,false,true);
        }
      } else if (rectangularFootprint(cells)) {
        // A rectangle has no courtyard or re-entrant gap for its hull to fill.
        project(cells.flatMap(({x,y})=>rectangle(x,y)),bottom,top,false,true);
      } else {
        // Keep each part of a concave or holed footprint separate. The painter
        // subtracts these shadows as a union, preserving clear space inside it.
        for (const {x,y} of cells) project(rectangle(x,y),bottom,top,false,true);
      }
    }
  } else for (const row of geometry.volumes || []) {
    const {x,y,bottom_ft:bottom=0,top_ft:top=null}=row;
    if (row.mode==='centerline') {
      if (origin.x===x+.5 && origin.y===y+.5 && bottom<=eyeFt && (top==null || eyeFt<top)) {
        shadows.push([[0,0],[width,0],[width,height],[0,height]]);
        continue;
      }
      project([[x,y+0.5],[x+1,y+0.5]],bottom,top,false,true);
      project([[x+0.5,y],[x+0.5,y+1]],bottom,top,false,true);
    } else {
      project(rectangle(x,y),bottom,top);
    }
  }
  for (const row of geometry.roofs || []) {
    if (targetFt<eyeFt && row.top_ft===eyeFt && origin.x>=row.x && origin.x<=row.x+1
      && origin.y>=row.y && origin.y<=row.y+1) shadows.push([[0,0],[width,0],[width,height],[0,height]]);
    else project(rectangle(row.x,row.y),row.top_ft,row.top_ft,true);
  }
  return shadows;
}

export function viewerEye(viewer) {
  const p=viewer.position || viewer;
  return viewer.altitude_ft ?? (p.z ?? 0)*5;
}

// Each entry is a visible continuous plane with shadow holes. Roof masks are
// clipped to their footprint and use roof-top rays, independently of floor
// rays: seeing a roof never reveals its interior or creatures below it.
export function altitudeVisibilityPolygons(viewers, geometry, width, height) {
  const polygons=[], bounds=[[0,0],[width,0],[width,height],[0,height]];
  const surfaces=new Map();
  const addSurface = (r,roof) => {
    if (!surfaces.has(r.top_ft)) surfaces.set(r.top_ft,[]);
    const clip=rectangle(r.x,r.y); clip.roof=roof;
    if (!surfaces.get(r.top_ft).some(c=>c[0][0]===r.x && c[0][1]===r.y && c.roof===roof))
      surfaces.get(r.top_ft).push(clip);
  };
  for (const r of geometry.roofs || []) addSurface(r,true);
  for (const r of geometry.volumes || []) if (r.mode==='cell' && r.solid && r.top_ft>0) addSurface(r,false);
  for (const viewer of viewers) {
    const p=viewer.position || viewer, eye=viewerEye(viewer);
    if (eye<=0) continue;
    const limits = top => (geometry.limits?.[viewer.entity_id] || [])
      .filter(row=>row[2]===top).map(([x,y])=>rectangle(x,y));
    // Match the server's any-footprint-cell surface origins. Presentation
    // positions are cell centers; footprint width/height are integer cells.
    const w=viewer.footprint?.width_cells || 1, h=viewer.footprint?.height_cells || 1;
    for (let dy=0;dy<h;dy++) for (let dx=0;dx<w;dx++) {
      const origin={x:p.x-(w-1)/2+dx,y:p.y-(h-1)/2+dy};
      const shadows=shadowsAt(origin,eye,0,geometry,width,height);
      const sampleShadows=shadowsAt(origin,eye,0,geometry,width,height,false);
      const floor={viewer:viewer.entity_id,points:bounds,
        shadows:[...shadows,...limits(0)], sampleShadows:[...sampleShadows,...limits(0)], surface_ft:0,
        // Floor seen beneath an eave must not light an unrelated roof tile.
        // Closed roof art is lit only by the roof-top ray below.
        covered:[...surfaces].filter(([top])=>eye>=top).flatMap(([,clips])=>clips)};
      polygons.push(floor);
      for (const [top,clips] of surfaces) if (eye>=top) polygons.push({
        viewer:viewer.entity_id, points:bounds, clips, surface_ft:top,
        covered:[...surfaces].filter(([above])=>above>top && eye>=above).flatMap(([,clips])=>clips),
        shadows:[...shadowsAt(origin,eye,top,geometry,width,height),...limits(top)],
        sampleShadows:[...shadowsAt(origin,eye,top,geometry,width,height,false),...limits(top)]});
    }
  }
  return polygons;
}

// Shared production cache inputs. Keep altitude and bound geometry in the key,
// including an ascent with no x/y movement and doors/objects changed in place.
export function altitudeFogKey(viewers, geometry) {
  return JSON.stringify([viewers,geometry]);
}
