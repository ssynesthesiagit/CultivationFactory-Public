// Continuous shadows on a target plane, from the service's bound 3D spans.
// Used by table fog for airborne viewers. No ability rules or height defaults:
// map-heights consumers already resolved the heights before this projection.

import {boundSegments, splitCell, viewerSegments} from './sight-lines.js?v=loslines3f8';
const rectangle = (x, y) => [[x,y],[x+1,y],[x+1,y+1],[x,y+1]];

function sceneryFootprints(volumes) {
  // Cell spans are the server's per-cell sight rule. Drawing each cell or
  // centerline cross as its own shadow makes dense scenery read as a staircase
  // of grid cells. Join touching spans of the same kind and height for drawing;
  // server perception remains the authority for rules.
  const rows = (volumes || []).filter(r=>r.mode!=='line');
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

const inSpan = (ft, row) => row.bottom_ft<=ft && (row.top_ft==null || ft<row.top_ft);

function shadowsAt(origin, eyeFt, targetFt, geometry, width, height, smooth = true) {
  const shadows=[];
  // A finite obstacle produces a finite shadow: merely dropping every wall
  // below the viewer would incorrectly reveal ground immediately behind it.
  // exempt: the one occupied SIGHT_BLOCKED cell this shadow may not darken.
  // A target inside it at that height sees it (sight_lines.py near_endpoint).
  const project = (points, bottom, top, surface=false, closed=false, exempt=null) => {
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
    if (exempt) shadow.screenCells=exempt;
    if (shadow.length>=3 || (closed && shadow.length===2)) shadows.push(shadow);
  };
  for(const row of geometry.lines || []) {
    const screen = row.kind==='SIGHT_BLOCKED' ? row.cells : null;
    // A viewer inside an occupied screen at its height exempts only that
    // cell, exactly like the ground fog's viewerSegments; other cells block.
    const tagged = boundSegments(row).map(s=>screen ? Object.assign(s,{screenCells:screen}) : s);
    let pieces = screen && inSpan(eyeFt,row) ? viewerSegments(origin,tagged) : tagged;
    // Likewise a target at this height inside an occupied cell sees that
    // cell's own part; the rest of the screen and every other cell still block.
    if (screen && inSpan(targetFt,row)) for (const cell of screen) pieces = pieces.flatMap(piece => {
      const part = splitCell(piece, cell);
      if (part.inside) project(part.inside,row.bottom_ft,row.top_ft,false,true,[cell]);
      return part.outside;
    });
    for(const piece of pieces) project(piece,row.bottom_ft,row.top_ft,false,true);
  }
  if (smooth) {
    for (const group of sceneryFootprints(geometry.volumes)) {
      const {bottom_ft:bottom,top_ft:top,cells}=group;
      if (group.mode==='centerline' && cells.some(({x,y})=>origin.x===x+.5 && origin.y===y+.5)
        && bottom<=eyeFt && (top==null || eyeFt<top)) {
        shadows.push([[0,0],[width,0],[width,height],[0,height]]);
        continue;
      }
      if (group.mode==='centerline') {
        // Paint the bound cross arms, just as the exact sampler and server do.
        // Decorative trunk/canopy circles are art, not sight geometry: their
        // projection can both hide clear ground and reveal blocked ground.
        for (const {x,y} of cells) {
          project([[x,y+0.5],[x+1,y+0.5]],bottom,top,false,true);
          project([[x+0.5,y],[x+0.5,y+1]],bottom,top,false,true);
        }
      } else if (rectangularFootprint(cells)) {
        // A rectangle has no courtyard or re-entrant gap for its hull to fill.
        project(cells.flatMap(({x,y})=>rectangle(x,y)),bottom,top);
      } else {
        // Keep each part of a concave or holed footprint separate. The painter
        // subtracts these shadows as a union, preserving clear space inside it.
        for (const {x,y} of cells) project(rectangle(x,y),bottom,top);
      }
    }
  } else for (const row of geometry.volumes || []) {
    if(row.mode==='line') continue;
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
  for (const r of geometry.volumes || []) if (r.mode!=='centerline' && r.solid && r.top_ft>0) addSurface(r,false);
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
      const floor={viewer:viewer.entity_id,origin,points:bounds,
        shadows:[...shadows,...limits(0)], sampleShadows:[...sampleShadows,...limits(0)], surface_ft:0,
        // Floor seen beneath an eave must not light an unrelated roof tile.
        // Closed roof art is lit only by the roof-top ray below.
        covered:[...surfaces].filter(([top])=>eye>=top).flatMap(([,clips])=>clips)};
      polygons.push(floor);
      for (const [top,clips] of surfaces) if (eye>=top) polygons.push({
        viewer:viewer.entity_id, origin, points:bounds, clips, surface_ft:top,
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
