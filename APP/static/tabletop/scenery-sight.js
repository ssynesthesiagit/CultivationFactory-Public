// Physical plant placements shared with combat/scenery_sight.py. Coordinates,
// radii and cross endpoints are integer hundredths of a square. A stalk must
// be at least 5 ft tall and 1 ft across to block sight; smaller shoots are art.
// Leaf sprays can vary, but never move a physical stalk independently of LoS.
import policy from './scenery-sight.json' with {type:'json'};
import heights from './map-heights.json' with {type:'json'};
export {policy as scenerySightPolicy};

export function bambooGroups(cells = []) {
  const ordered=[...new Map(cells.map(c=>[c.join(','),c])).values()].sort((a,b)=>a[1]-b[1] || a[0]-b[0]);
  const have=new Set(ordered.map(c=>c.join(','))),used=new Set(),out=[];
  for(const size of [3,2,1]) for(const [x,y] of ordered) {
    const block=[];
    for(let dy=0;dy<size;dy++) for(let dx=0;dx<size;dx++) block.push([x+dx,y+dy]);
    if(block.some(c=>!have.has(c.join(',')) || used.has(c.join(',')))) continue;
    block.forEach(c=>used.add(c.join(',')));out.push({x,y,size,cells:block});
  }
  return out;
}

export function bambooCulms(x=0,y=0,size=1,clump=false,rotation=0) {
  return (clump?policy.bamboo_clump_culms:policy.bamboo_culms).map(([cx,cy,r])=>{
    // Quarter-turns keep exact integer geometry. Size enlarges a real clump.
    for(let turn=0;turn<rotation/90;turn++) [cx,cy]=[100-cy,cx];
    return {x:x*100+cx*size,y:y*100+cy*size,r:r*size};
  });
}
export const plantBlocksSight = (p,height) => height>=policy.plant_min_height_ft && p.r>=policy.plant_min_radius;
export const terrainBlocksSight = (row,height=row.height_ft) => height>=policy.plant_min_height_ft
  && (row.type==='SIMPLE_COVER' || (heights.terrain_ft[row.look] || 0)>=5);
export const trunkCross = p => [[[p.x-p.r,p.y],[p.x+p.r,p.y]],[[p.x,p.y-p.r],[p.x,p.y+p.r]]];
export function treeTrunks(tree) {
  const size=tree.size===2?2:1;
  return /^(bamboo_stand|golden_bamboo)$/.test(tree.look)
    ? bambooCulms(tree.x,tree.y,size)
    : [{x:tree.x*100+size*50,y:tree.y*100+size*50,r:policy.tree_radius*size}];
}
