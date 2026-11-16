// Same connected centre-run/end-cap construction as combat/sight_lines.py.
// Coordinates are map squares. No movement, targeting or sense rules here.
const xy = c => Array.isArray(c) ? c : [c.x,c.y];
export function cellRuns(cells = []) {
  const remaining = new Map(cells.map(c=>[xy(c).join(','),xy(c)])), runs=[];
  while (remaining.size) {
    const first=[...remaining.values()].sort((a,b)=>a[0]-b[0] || a[1]-b[1])[0];
    remaining.delete(first.join(','));
    const group=[first], pending=[first];
    while(pending.length) {
      const [x,y]=pending.pop();
      for(const cell of [[x-1,y],[x+1,y],[x,y-1],[x,y+1]]) {
        const key=cell.join(',');
        if(remaining.has(key)) {remaining.delete(key);group.push(cell);pending.push(cell);}
      }
    }
    const xs=group.map(c=>c[0]),ys=group.map(c=>c[1]);
    const vertical=Math.max(...ys)-Math.min(...ys)>Math.max(...xs)-Math.min(...xs);
    const rows=new Map(),point=(u,v,depth)=>vertical?[v+depth/2,u]:[u,v+depth/2],strips=new Map();
    for(const [x,y] of group) {
      const [u,v]=vertical?[y,x]:[x,y];
      if(!rows.has(v)) rows.set(v,[]);
      rows.get(v).push(u);
    }
    for(const [v,values] of [...rows].sort((a,b)=>a[0]-b[0])) {
      values.sort((a,b)=>a-b);
      let first=values[0],last=first;
      for(const u of [...values.slice(1),Infinity]) {
        if(u!==last+1) {
          const key=first+','+(last+1);
          if(!strips.has(key)) strips.set(key,{start:first,end:last+1,values:[]});
          strips.get(key).values.push(v);first=u;
        }
        last=u;
      }
    }
    for(const {start,end,values} of strips.values()) {
      let first=values[0],last=first;
      for(const v of [...values.slice(1),Infinity]) {
        if(v!==last+1) {
          const depth=last-first+1;
          runs.push([point(start,first,depth),point(end,first,depth),depth]);first=v;
        }
        last=v;
      }
    }
  }
  return runs;
}
export function cellSegments(cells) {
  return cellRuns(cells).flatMap(([a,b,depth])=>{
    const [dx,dy]=a[0]===b[0]?[depth/2,0]:[0,depth/2];
    return [[a,b],...[a,b].map(p=>[[p[0]-dx,p[1]-dy],[p[0]+dx,p[1]+dy]])];
  });
}
export const boundSegments = row => row.segments.map(s=>s.map(p=>p.map(n=>n/(row.scale || 2))));
// Ground sight from inside a walk-through screen ignores only the occupied
// cell, including its boundary. Keep the rest of that source and independent
// solid barriers. Both the continuous fog polygon and its exact sampler use
// these per-viewer segments; never mutate the shared source geometry.
export function viewerSegments(origin, segments) {
  const cell = [Math.floor(origin.x), Math.floor(origin.y)];
  return segments.flatMap(segment => segment.screenCells?.some(c => c[0]===cell[0] && c[1]===cell[1])
    ? splitCell(segment, cell).outside : [segment]);
}
// The parts of one segment inside and outside a single cell. Occupied-screen
// exemptions use only the inside part; the outside parts keep blocking.
export function splitCell(segment, cell) {
  const [a,b] = segment, d = [b[0]-a[0],b[1]-a[1]];
  let lo=0, hi=1;
  for (let axis=0; axis<2; axis++) {
    if (!d[axis]) {
      if (a[axis]<cell[axis] || a[axis]>cell[axis]+1) return {inside:null, outside:[segment]};
    } else {
      const ends=[(cell[axis]-a[axis])/d[axis],(cell[axis]+1-a[axis])/d[axis]].sort((x,y)=>x-y);
      lo=Math.max(lo,ends[0]); hi=Math.min(hi,ends[1]);
    }
  }
  if (lo>hi) return {inside:null, outside:[segment]};
  const at=t=>[a[0]+d[0]*t,a[1]+d[1]*t], outside=[];
  // Keep the source's screen metadata on each surviving piece: altitude
  // projection and later viewer clipping still need to identify its exemption.
  const piece=(start,end)=>Object.assign([start,end],{screenCells:segment.screenCells});
  if (lo>1e-10) outside.push(piece(a,at(lo)));
  if (hi<1-1e-10) outside.push(piece(at(hi),b));
  return {inside:[at(lo),at(hi)], outside};
}
// Closed tips match integer server intersections. A destination on a barrier
// sees its near face; an intersection strictly before it blocks the ray.
export function rayVisible(origin, target, segments) {
  const dx=target[0]-origin.x,dy=target[1]-origin.y;
  for(const [a,b] of segments) {
    const sx=b[0]-a[0],sy=b[1]-a[1],qx=a[0]-origin.x,qy=a[1]-origin.y;
    const cross=dx*sy-dy*sx;
    if(Math.abs(cross)>1e-10) {
      const t=(qx*sy-qy*sx)/cross,u=(qx*dy-qy*dx)/cross;
      if(t>=-1e-10 && t<1-1e-10 && u>=-1e-10 && u<=1+1e-10) return false;
    } else if(Math.abs(qx*dy-qy*dx)<1e-10) {
      const axis=Math.abs(dx)>=Math.abs(dy)?0:1,d=axis===0?dx:dy;
      if(!d) continue;
      const p=axis===0?origin.x:origin.y;
      const lo=Math.min((a[axis]-p)/d,(b[axis]-p)/d),hi=Math.max((a[axis]-p)/d,(b[axis]-p)/d);
      if(hi>=0 && lo<1-1e-10) return false;
    }
  }
  return true;
}
// Horizontal roof surfaces block through their entire plane. Mark its actual
// outer edges, cancelling shared tile seams rather than inventing a column.
export function surfaceEdges(cells) {
  const edges=new Map();
  for(const c of cells) {
    const [x,y]=xy(c),points=[[x,y],[x+1,y],[x+1,y+1],[x,y+1]];
    for(let i=0;i<4;i++) {
      const a=points[i],b=points[(i+1)%4],key=a.join(',')+'>'+b.join(','),reverse=b.join(',')+'>'+a.join(',');
      if(edges.has(reverse)) edges.delete(reverse);else edges.set(key,[a,b]);
    }
  }
  return [...edges.values()];
}
