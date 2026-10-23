// Sight-blocker presentation only. tabletop supplies the SAME scenery used by
// fog_polygon and the bound height geometry. Never changes sight or targeting.
// Each cell keeps only its clipped strokes in fog memory, so an unseen change
// cannot move, add, or remove a remembered barrier. No token data is consumed.
import {blockerSegments} from './fog_polygon.js?v=loslines3';
import {wallSightCells, zoneLook} from './zones.js?v=r25x2';
import {cellRuns as connectedRuns, boundSegments, surfaceEdges} from './sight-lines.js?v=loslines3';
import {bambooGroups,bambooCulms,treeTrunks,plantBlocksSight,trunkCross,terrainBlocksSight} from './scenery-sight.js?v=loslines3';
import {sceneryHeightFt} from './map-heights.js';

const xy = c => Array.isArray(c) ? c : [c.x, c.y];
const STONE = '#b8aa92', WOOD = '#b89b71';

// Runs through the middle of a footprint, including bent and disconnected
// walls. Merge along its long axis without ever bridging a gap or doorway.
const cellRuns = connectedRuns;

export function sightBlockerLines(geometry = {}, zones = [], heights = {}) {
  heights ??= {};
  if (geometry.sources) {
    const lines=[];
    for(const row of geometry.sources) {
      if(row.top_ft!=null && row.top_ft<=row.bottom_ft) continue;
      const zone=zones.find(z=>wallSightCells([z]).some(c=>row.cells.some(p=>p[0]===c[0] && p[1]===c[1]))
        && (z.trigger_profile?.name || 'Wall')===row.name);
      const look=zone && zoneLook(zone);
      const kind=zone?'zone':/trunk|bamboo/i.test(row.name)?'tree':/object|door|gate|pillar/i.test(row.name)?'object':'wall';
      boundSegments(row).forEach(([a,b],index)=>lines.push({a,b,kind,color:look?.color || (kind==='tree'?WOOD:STONE),
        depth:0,art:!!look && look.wall?.kind!=='screen' && index%3===0,name:row.name}));
    }
    for(const row of heights.volumes || []) if(row.mode==='centerline') {
      for(const [a,b] of blockerSegments({centerlineCells:[[row.x,row.y]]}))
        lines.push({a,b,kind:'centerline',color:WOOD,depth:0,name:'Tree trunk or dense bamboo — blocks sight along its centre cross.'});
    }
    for(const [a,b] of surfaceEdges(heights.roofs || [])) lines.push({a,b,kind:'roof',color:STONE,
      depth:0,name:'Roof — blocks sight through its horizontal surface.'});
    return lines;
  }
  const lines = [], covered = new Set(), thin = new Set((geometry.centerlineCells || []).map(c => xy(c).join(',')));
  // Ability walls also occur in battlefield.blocked_cells. Their own colour
  // and thickness must win over the generic stone fallback for that square.
  const dynamicKeys = new Set([...(geometry.dynamicCells || []), ...wallSightCells(zones)].map(c=>xy(c).join(',')));
  const add = (segments, kind, color, depth=1, art=false) => {
    for (const [a,b] of segments) if (Math.hypot(b[0]-a[0], b[1]-a[1]) > 1e-8)
      lines.push({a,b,kind,color,depth,art});
  };
  const mark = cells => cells.forEach(c => covered.add(xy(c).join(',')));
  for (const wall of geometry.walls || []) {
    const cells = wall.cells || [];
    mark(cells);
    const color = /^#[\da-f]{6}$/i.test(wall.color || '') ? wall.color
      : /wood|timber|bamboo/i.test(wall.look || wall.material || '') ? WOOD : STONE;
    if (wall.occluder === 'centerline') {
      add(cellRuns(cells.filter(c => !thin.has(xy(c).join(',')))), 'wall', color);
    } else if (wall.shape === 'rect' && wall.points?.length >= 2) {
      const [a,b] = wall.points, w = Math.abs(b[0]-a[0]), h = Math.abs(b[1]-a[1]);
      if (Math.min(w,h) <= 1) add(w<h
        ? [[[ (a[0]+b[0])/2, Math.min(a[1],b[1])],[(a[0]+b[0])/2,Math.max(a[1],b[1])]]]
        : [[[Math.min(a[0],b[0]),(a[1]+b[1])/2],[Math.max(a[0],b[0]),(a[1]+b[1])/2]]], 'wall',color,Math.max(.12,Math.min(w,h)));
      else add(blockerSegments({walls:[wall]}), 'wall', color);
    } else if (wall.shape === 'circle' && wall.points?.length >= 2) {
      const [center,edge]=wall.points, radius=Math.hypot(edge[0]-center[0],edge[1]-center[1]);
      // A boulder/pillar gets one diameter mark, not end ticks on every tiny
      // ray-casting chord around its circumference.
      add([[[center[0]-radius,center[1]],[center[0]+radius,center[1]]]],'wall',color,.6);
    } else add(blockerSegments({walls:[wall]}), 'wall', color);
  }
  for (const tree of geometry.trees || []) {
    const cells = Array.from({length:tree.size===2?4:1}, (_,i)=>[tree.x+i%(tree.size===2?2:1),tree.y+Math.floor(i/(tree.size===2?2:1))]);
    mark(cells);
    for(const p of treeTrunks(tree)) if(plantBlocksSight(p,sceneryHeightFt(tree,'tree')))
      add(trunkCross(p).map(s=>s.map(p=>p.map(n=>n/100))), cells.every(c=>thin.has(c.join(',')))?'centerline':'tree', WOOD,0);
  }
  const plants = (ps,height) => ps.filter(p=>plantBlocksSight(p,height)).flatMap(trunkCross).map(s=>s.map(p=>p.map(n=>n/100)));
  for(const row of geometry.materials || []) if(row.material==='terrain:bamboo thicket') {
    mark(row.cells || []);
    add(plants(bambooGroups(row.cells).flatMap(g=>bambooCulms(g.x,g.y,g.size)),sceneryHeightFt(row,'material')), 'tree',WOOD,0);
  }
  for(const row of geometry.terrain || []) if(terrainBlocksSight(row,sceneryHeightFt(row,'terrain'))) {
    mark(row.cells || []);
    if(row.look==='bamboo_clump') add(plants((row.cells || []).flatMap(([x,y])=>bambooCulms(x,y,1,true,row.rotation || 0)),sceneryHeightFt(row,'terrain')), 'tree',WOOD,0);
    else for(const c of row.cells || []) add(cellRuns([c]),'terrain',STONE,0);
  }
  for (const object of geometry.objects || []) if (object.hp>0 && object.blocks) {
    mark([[object.x,object.y]]);
    add(cellRuns([[object.x,object.y]]), 'object', WOOD,.6);
  }
  const blocked=(geometry.blockedCells || []).filter(c=>!covered.has(xy(c).join(',')) && !thin.has(xy(c).join(',')) && !dynamicKeys.has(xy(c).join(',')));
  add(cellRuns(blocked), 'blocked', STONE,.6);
  mark(blocked);
  add(blockerSegments({centerlineCells:(geometry.centerlineCells || []).filter(c=>!covered.has(xy(c).join(',')))}), 'centerline', WOOD,.16);
  const dynamic = new Set();
  for (const zone of zones) {
    const cells = wallSightCells([zone]);
    if (!cells.length) continue;
    cells.forEach(c=>dynamic.add(c.join(',')));
    const look = zoneLook(zone);
    mark(cells);
    add(cellRuns(cells), 'zone', look.color,.36,look.wall?.kind!=='screen');
  }
  add(cellRuns((geometry.dynamicCells || []).filter(c=>!dynamic.has(xy(c).join(',')))), 'zone', STONE);
  // Height-bound terrain and roofs can cast shadows even when absent from
  // ground-level blockedCells. Show their physical source, not the projection.
  add(cellRuns((heights.volumes || []).filter(c=>c.mode!=='centerline' && !covered.has(xy(c).join(',')))), 'terrain', STONE,.5);
  add(blockerSegments({centerlineCells:(heights.volumes || []).filter(c=>c.mode==='centerline' && !thin.has(xy(c).join(','))).map(xy)}), 'centerline', WOOD,.16);
  add(cellRuns(heights.roofs || []), 'roof', STONE,.5);
  return lines;
}

// Exact segment/rectangle clipping, including endpoints on a cell boundary.
function clip(a,b,x,y) {
  let lo=0, hi=1;
  const dx=b[0]-a[0], dy=b[1]-a[1];
  for (const [p,q] of [[-dx,a[0]-x],[dx,x+1-a[0]],[-dy,a[1]-y],[dy,y+1-a[1]]]) {
    if (!p) {if(q<0) return null; continue;}
    const t=q/p;
    if (p<0) lo=Math.max(lo,t); else hi=Math.min(hi,t);
    if (lo>=hi) return null;
  }
  return [[a[0]+dx*lo,a[1]+dy*lo],[a[0]+dx*hi,a[1]+dy*hi]];
}

// SVG paths are stored as strings; no floating-point state enters fight saves.
export function blockerCellStrokes(lines, width, height) {
  const cells = new Map(), path = (a,b) => `M${a.join(' ')}L${b.join(' ')}`;
  for (const line of lines) {
    const {a,b,depth,color,kind,art,name} = line, length=Math.hypot(b[0]-a[0],b[1]-a[1]);
    const nx=-(b[1]-a[1])/length*depth/2, ny=(b[0]-a[0])/length*depth/2;
    const ticks=[a,b].map(p=>[[p[0]-nx,p[1]-ny],[p[0]+nx,p[1]+ny]]);
    const padding=Math.max(depth,.001);
    for (let y=Math.max(0,Math.floor(Math.min(a[1],b[1])-padding));y<Math.min(height,Math.ceil(Math.max(a[1],b[1])+padding));y++)
      for (let x=Math.max(0,Math.floor(Math.min(a[0],b[0])-padding));x<Math.min(width,Math.ceil(Math.max(a[0],b[0])+padding));x++) {
        const center=clip(a,b,x,y), ends=ticks.map(t=>clip(...t,x,y)).filter(Boolean);
        if (!center && !ends.length) continue;
        const key=y*width+x;
        if (!cells.has(key)) cells.set(key,[]);
        cells.get(key).push({center:center?path(...center):'', ticks:ends.map(t=>path(...t)).join(''),color,kind,
          name:name || ({zone:'Wall',wall:'Wall',tree:'Tree trunk',object:'Object',blocked:'Blocking terrain',centerline:'Tree trunk or dense bamboo',terrain:'Blocking terrain',roof:'Roof'}[kind])+' — blocks line of sight.',
          // Raised coloured ribbon with a light crest and crosswise joints.
          art:art && center ? path(...center) : ''});
      }
  }
  return cells;
}
