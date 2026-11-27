import assert from 'node:assert/strict';
import test from 'node:test';
import {bambooCulms,bambooGroups,plantBlocksSight,treeTrunks,trunkCross} from '../static/tabletop/scenery-sight.js';
import {paintMaterial} from '../static/tabletop/zonepaint.js';
import {treeMarkup,treeScene} from '../static/tabletop/tree-art.js';
import {terrainCellMarkup} from '../static/tabletop/terrain-art.js';
import {sightBlockerLines} from '../static/tabletop/los-lines.js';

const centres = markup => [...markup.matchAll(/<circle cx="([\d.-]+)" cy="([\d.-]+)" r="[^"]+" fill="(?:#4a7a2c|#c9a83a)"/g)].map(m=>[+m[1],+m[2]]);
const sorted = rows => rows.map(p=>p.map(n=>Math.round(n*1000)/1000)).sort((a,b)=>a[0]-b[0] || a[1]-b[1]);

test('tree bamboo SVG and reusable sprite place every stem at its bound centre',()=>{
 for(const look of ['bamboo_stand','golden_bamboo']) for(const size of [1,2]) {
  const tree={x:4,y:5,size,look,seed:19},expected=treeTrunks(tree).map(p=>[p.x/100,p.y/100]);
  assert.deepEqual(sorted(centres(treeMarkup(tree))),sorted(expected));
  const scene=treeScene([tree]),sprite=scene.shapes.get(scene.placements[0].id);
  assert.deepEqual(sorted(centres(sprite.markup).map(([x,y])=>[x+4,y+5])),sorted(expected));
 }
});

test('material painter places all large and tiny culms; only qualifying culms receive preview crosses',()=>{
 const cells=[[2,2],[3,2],[2,3],[3,3],[7,5]],arcs=[];
 const ctx=new Proxy({fillStyle:'',createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),
  createRadialGradient:()=>({addColorStop(){}}),arc(x,y,r){if(this.fillStyle==='rgba(30,38,14,0.92)') arcs.push([x,y,r/.3]);}},
  {get:(target,key)=>key in target?target[key]:()=>{}});
 paintMaterial(ctx,'bamboo',{cells,x0:2,y0:2,w:6,h:4,ppc:1,seed:91,color:[60,90,40]});
 const ps=bambooGroups(cells).flatMap(g=>bambooCulms(g.x,g.y,g.size));
 assert.deepEqual(sorted(arcs.map(p=>p.slice(0,2))),sorted(ps.map(p=>[p.x/100,p.y/100])));
 const lines=sightBlockerLines({materials:[{material:'terrain:bamboo thicket',cells,height_ft:20}]});
 assert.equal(lines.length,ps.filter(p=>plantBlocksSight(p,20)).length*2);
 assert.equal(sightBlockerLines({materials:[{material:'terrain:bamboo thicket',cells,height_ft:4}]}).length,0);
});

test('cover bamboo stems are stable across leaf variants; quarter turn moves art and cross together',()=>{
 for(const seed of [1,9,123]) {
  assert.deepEqual(sorted(centres(terrainCellMarkup('SIMPLE_COVER','bamboo_clump',false,seed))),
    sorted(bambooCulms(0,0,1,true).map(p=>[p.x*.64,p.y*.64])));
 }
 for(const rotation of [0,90,180,270]) {
  const row={type:'SIMPLE_COVER',look:'bamboo_clump',height_ft:10,cells:[[3,4]],rotation};
  const lines=sightBlockerLines({terrain:[row]});
  const expected=bambooCulms(3,4,1,true,rotation).filter(p=>plantBlocksSight(p,10)).flatMap(trunkCross);
  assert.deepEqual(lines.map(l=>[l.a,l.b]),expected.map(s=>s.map(p=>p.map(n=>n/100))));
  if(rotation) assert.match(terrainCellMarkup(row.type,row.look,false,4,rotation),new RegExp(`rotate\\(${rotation} 32 32\\)`));
 }
});
