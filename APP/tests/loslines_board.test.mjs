import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard, CELL} from '../static/tabletop/board.js';
import {sightBlockerLines, blockerCellStrokes} from '../static/tabletop/los-lines.js';
import {recordSeen, emptyMemory, ghostCells} from '../static/tabletop/fog_memory.js';

const wall = {zone_id:'wall',owner_id:'jia',source_definition_id:'talisman',affected_cells:[[3,1],[3,2],[3,3]],
  duration_rounds:10,created_round:1,trigger_profile:{kind:'TYPED',name:'Talisman Wall',color:'#7fb3d5',
    visual:{material:'glyphs',wall:true},wall:{blocks_movement:true}}};
const makeMap = () => ({width:8,height:6,background:{url:null,opacity:1,style:'flagstone',seed:1},display:{},
  walls:[],trees:[],objects:[],cells:{blocked:[],sight:[],cover:[],hazard:[],difficult:[]}});
function setup(map=makeMap()) {
  const doc=installDOM('<html><body><div id="v"></div></body></html>');
  const viewport=doc.getElementById('v'), board=createBoard(viewport);
  board.setMap(map); board.fit();
  board.setZones([wall],{round:3,teamOf:()=>({owner:'Jia Fengshan',color:'#d54a48'})});
  return {doc,board,viewport};
}
const cases = [
  ['wall',{walls:[{shape:'line',points:[[2,1],[2,4]]}]}],
  ['wall',{walls:[{shape:'rect',points:[[2,1],[3,4]]}]}],
  ['wall',{walls:[{shape:'circle',points:[[3,3],[4,3]]}]}],
  ['zone',{dynamicCells:[[2,1],[2,2],[2,3]]}],
  ['object',{objects:[{x:2,y:2,hp:10,blocks:true}]}],
  ['blocked',{blockedCells:[[2,1],[2,2],[2,3]]}],
  ['tree',{trees:[{x:2,y:2}]}],
  ['centerline',{trees:[{x:2,y:2}],centerlineCells:[[2,2]]}],
  ['terrain',{}, {volumes:[{x:2,y:2,mode:'cell',bottom_ft:0,top_ft:20}]}],
  ['roof',{}, {roofs:[{x:2,y:2,top_ft:20}]}],
];
for (const [kind,geometry,heights] of cases) test(`${kind}: wall strokes only; scenery stays art-only`,()=>{
  const lines=sightBlockerLines(geometry,[],heights);
  assert.ok(lines.length,kind);
  assert.ok(lines.every(l=>l.kind===kind));
  const cells=blockerCellStrokes(lines,8,6), strokes=[...cells.values()].flat();
  if (['object','blocked','tree','centerline','terrain','roof'].includes(kind)) {
    assert.equal(strokes.length,0,'scenery geometry is not drawn over its art');
    return;
  }
  assert.ok(strokes.some(s=>s.center),'has a centre');
  assert.ok(strokes.some(s=>s.ticks),'has end ticks');
  const at=raster(strokes), mid=lines[0].a.map((v,i)=>(v+lines[0].b[i])/2);
  assert.ok([-1,0,1].some(dx=>[-1,0,1].some(dy=>at(Math.floor(mid[0]*64)+dx,Math.floor(mid[1]*64)+dy))), 'rasterized centre');
  for (const line of lines) {
    const dx=line.b[0]-line.a[0],dy=line.b[1]-line.a[1];
    const ends=strokes.flatMap(s=>segments(s.ticks));
    assert.ok(ends.some(([a,b])=>Math.abs(dx*(b[0]-a[0])+dy*(b[1]-a[1]))<1e-7),'ticks perpendicular');
  }
});
function segments(d) {
  return [...d.matchAll(/M([\d.e+-]+) ([\d.e+-]+)L([\d.e+-]+) ([\d.e+-]+)/g)]
    .map(m=>[[+m[1],+m[2]],[+m[3],+m[4]]]);
}
// Small deterministic stroke rasterizer. Samples path geometry at 64px/cell;
// DOM tests below independently verify the board installs the cell clip paths.
function raster(strokes) {
  const pixels=new Uint8Array(8*6*64*64), width=8*64;
  for (const s of strokes) for (const [a,b] of segments(s.center+s.ticks)) {
    const dx=b[0]-a[0],dy=b[1]-a[1], length=dx*dx+dy*dy;
    for(let y=Math.max(0,Math.floor(Math.min(a[1],b[1])*64)-2);y<Math.min(6*64,Math.ceil(Math.max(a[1],b[1])*64)+2);y++)
      for(let x=Math.max(0,Math.floor(Math.min(a[0],b[0])*64)-2);x<Math.min(width,Math.ceil(Math.max(a[0],b[0])*64)+2);x++) {
        const px=(x+.5)/64,py=(y+.5)/64,t=Math.max(0,Math.min(1,((px-a[0])*dx+(py-a[1])*dy)/length));
        if(Math.hypot(px-a[0]-t*dx,py-a[1]-t*dy)<=1.25/128) pixels[y*width+x]=1;
      }
  }
  return (x,y)=>pixels[y*width+x];
}
test('six-cell ability wall is one centre run, with ticks only at its true ends; raster is thin',()=>{
  const zone={...wall,affected_cells:Array.from({length:6},(_,i)=>[3,i])};
  const lines=sightBlockerLines({},[zone]);
  assert.deepEqual(lines.map(l=>[l.a,l.b]),[[[3.5,0],[3.5,6]]]);
  assert.equal(lines[0].color,'#7fb3d5','zone colour, not team tint');
  const at=raster([...blockerCellStrokes(lines,8,6).values()].flat());
  assert.equal(at(224,180),1,'centre');
  assert.equal(at(215,0),1,'top depth tick');
  assert.equal(at(215,383),1,'bottom depth tick');
  assert.equal(at(215,192),0,'no tick at internal grid seams');
  assert.equal(at(228,180),0,'crisp thin stroke');
});
test('opened cells and dead/nonblocking objects do not acquire barrier lines',()=>{
  const opened={...wall,trigger_profile:{...wall.trigger_profile,openings:[{cell:[3,2]}]}};
  assert.equal(sightBlockerLines({},[opened]).length,2,'no bridge across opening');
  assert.equal(sightBlockerLines({objects:[{x:2,y:2,hp:0,blocks:true},{x:3,y:2,hp:1,blocks:false}]}).length,0);
});
test('ability wall colour takes precedence over duplicate blocked-cell fallback',()=>{
  const lines=sightBlockerLines({blockedCells:wall.affected_cells,dynamicCells:wall.affected_cells},[wall]);
  assert.equal(lines.length,1);
  assert.equal(lines[0].kind,'zone');
  assert.equal(lines[0].color,'#7fb3d5');
});
test('a round pillar has one centre mark rather than ticks on every polygon chord',()=>{
  const lines=sightBlockerLines({walls:[{shape:'circle',points:[[3,3],[4,3]]}]});
  assert.deepEqual(lines.map(l=>[l.a,l.b]),[[[2,3],[4,3]]]);
});
test('board draws raised wall in zone colour above fog; unseen portions stay absent',()=>{
  const {doc,board}=setup();
  const seen=new Uint8Array(48);seen[2*8+3]=1;
  board.setFog(seen,null,{squareFog:true});
  const overlay=doc.querySelector('.tt-sight-lines'), parent=overlay.parentNode;
  assert.ok(parent.children.indexOf(overlay)>parent.children.indexOf(doc.querySelector('.tt-fog')));
  assert.ok(parent.children.indexOf(overlay)<parent.children.indexOf(doc.querySelectorAll('.tt-tokens').at(-1)));
  assert.equal(overlay.getAttribute('pointer-events'),'none');
  assert.equal(overlay.querySelector('.tt-sight-wall-art').getAttribute('stroke'),'#7fb3d5');
  const groups=overlay.querySelectorAll('.tt-sight-current');
  assert.deepEqual(groups.map(g=>+g.getAttribute('data-cell')),[19]);
  assert.match(groups[0].getAttribute('clip-path'),/^url\(#tt-sight-/);
  assert.equal(overlay.querySelector('rect').getAttribute('x'),'3');
  assert.equal(overlay.querySelector('rect').getAttribute('y'),'2');
  assert.equal(overlay.querySelector('rect').getAttribute('width'),'1');
  assert.equal(overlay.querySelector('rect').getAttribute('height'),'1');
  board.setFog(new Uint8Array(48),null,{squareFog:true});
  assert.equal(overlay.querySelectorAll('.tt-sight-line').length,0,'unseen wall never drawn');
});
test('remembered strokes survive JSON reload and never read changed live wall geometry',()=>{
  const {doc,board}=setup(), seen=new Uint8Array(48); seen[19]=1;
  board.setFog(seen,null,{squareFog:true});
  const snapshot=recordSeen(emptyMemory(),seen,i=>({blockers:board.blockersAt(i%8,Math.floor(i/8))}));
  const saved=JSON.parse(JSON.stringify(snapshot));
  board.setFog(new Uint8Array(48),null,{squareFog:true});
  board.setZones([{...wall,affected_cells:[[6,4]]}]);
  board.setRemembered({cells:saved.cells,ghosts:ghostCells(saved,new Uint8Array(48)),changed:[],width:8});
  const overlay=doc.querySelector('.tt-sight-lines');
  assert.deepEqual(overlay.querySelectorAll('.tt-sight-memory').map(g=>+g.getAttribute('data-cell')),[19]);
  assert.equal(overlay.querySelectorAll('.tt-sight-current').length,0,'new wall hidden');
  assert.equal(overlay.querySelector('.tt-sight-line').getAttribute('d'),saved.cells[19].blockers[0].center+saved.cells[19].blockers[0].ticks);
});
async function hover(s,x,y) {
  const callbacks=[],before=globalThis.setTimeout;
  globalThis.setTimeout=fn=>{callbacks.push(fn);return callbacks.length;};
  try {
    const v=s.board.view,event={clientX:v.x+(x+.5)*CELL*v.zoom,clientY:v.y+(y+.5)*CELL*v.zoom,buttons:0,target:s.viewport};
    await s.doc.dispatch('pointermove',event);await s.viewport.dispatch('pointermove',event);
    callbacks.forEach(fn=>fn());
  } finally {globalThis.setTimeout=before;}
  const card=s.doc.querySelector('.tt-hovercard');
  return card.hidden?'':card.querySelectorAll('.tt-zone-tip-item').map(n=>n.children.map(c=>c.textContent).join(' ')).join('\n');
}
test('wall hover names creator, sight blocking and remaining duration; hidden squares disclose no wall or token',async()=>{
  const s=setup(), seen=new Uint8Array(48);seen[19]=1;
  s.board.setTokens([{id:'hidden-enemy',name:'Secret enemy',x:3,y:1,hp:10,maxHp:10,hidden:true}]);
  s.board.setFog(seen,null,{squareFog:true});
  const text=await hover(s,3,2);
  for(const phrase of ['Talisman Wall','Jia Fengshan','blocks movement and sight','8 rounds left']) assert.ok(text.includes(phrase),phrase);
  const hidden=await hover(s,3,1);
  assert.doesNotMatch(hidden,/Talisman Wall|Jia Fengshan|Secret enemy/);
  const token=s.doc.querySelector('.tt-token');
  assert.ok(!token || token.classList.contains('is-hidden'),'hidden token stays absent');
  const css=readFileSync(new URL('../static/tabletop/tabletop.css',import.meta.url),'utf8');
  assert.match(css,/\.tt-token\.is-hidden\s*\{[^}]*display:\s*none/,'hidden token CSS still hides it');
});
test('table snapshots the clipped strokes and supplies the fog geometry without changing token visibility',()=>{
  const source=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  assert.match(source,/blockers: board\.blockersAt\(x, y\)/);
  assert.match(source,/blockerGeometry:app\.fogBlockerGeometry/);
  assert.match(source,/blockerHeights:app\.state\.fog_geometry/);
});
for (const bound of [false,true]) test(`null height geometry refreshes the board (${bound?'bound':'fallback'}) without exposing hidden tokens`,()=>{
  const s=setup();
  s.board.setTokens([{id:'hidden-enemy',name:'Secret enemy',x:3,y:1,hp:10,maxHp:10,hidden:true}]);
  const seen=new Uint8Array(48);seen[19]=1;
  const geometry=bound?{sources:[{cells:[[3,1],[3,2],[3,3]],kind:'BLOCKED',name:'Talisman Wall',
    bottom_ft:0,top_ft:null,segments:[[[7,2],[7,8]],[[6,2],[8,2]],[[6,8],[8,8]]]}]}:{};
  assert.doesNotThrow(()=>s.board.setFog(seen,null,{squareFog:true,blockerGeometry:geometry,blockerHeights:null}));
  assert.ok(s.doc.querySelector('.tt-sight-lines').querySelector('.tt-sight-current'));
  assert.ok(s.board.blockersAt(3,2).length);
  const token=s.doc.querySelector('.tt-token');
  assert.ok(!token || token.classList.contains('is-hidden'));
});
test('bound centre and cap segments are marked exactly; named memory never reads an unseen replacement',async()=>{
  const s=setup();s.board.setZones([]);
  const row={cells:[[3,1],[3,2],[3,3]],kind:'BLOCKED',name:'Maple stone wall',bottom_ft:0,top_ft:20,
    segments:[[[7,2],[7,8]],[[6,2],[8,2]],[[6,8],[8,8]]]};
  const lines=sightBlockerLines({sources:[row]},[],{});
  assert.deepEqual(lines.map(l=>[l.a,l.b]),row.segments.map(seg=>seg.map(p=>p.map(n=>n/2))));
  assert.ok(lines.every(l=>l.depth===0),'caps are explicit; no extra decorative geometry');
  const seen=new Uint8Array(48);seen[19]=1;
  s.board.setFog(seen,null,{squareFog:true,blockerGeometry:{sources:[row]}});
  assert.match(await hover(s,3,2),/Maple stone wall.*thin marked line blocks sight/s);
  const saved=JSON.parse(JSON.stringify(recordSeen(emptyMemory(),seen,i=>({blockers:s.board.blockersAt(i%8,Math.floor(i/8))}))));
  s.board.setFog(new Uint8Array(48),null,{squareFog:true,blockerGeometry:{sources:[{...row,name:'Secret new wall'}]}});
  s.board.setRemembered({cells:saved.cells,ghosts:[19],changed:[],width:8});
  const text=await hover(s,3,2);
  assert.match(text,/Maple stone wall.*current state is unknown/s);
  assert.doesNotMatch(text,/Secret new wall/);
});

test('remembered creature and wall descriptions coexist without reading hidden live state',async()=>{
  const s=setup();
  s.board.setZones([]);
  s.board.setTokens([{id:'stranger',name:'Secret true name',x:3,y:2,hidden:true}]);
  s.board.setFog(new Uint8Array(48),null,{squareFog:true});
  const remember = name => s.board.setRemembered({cells:{19:{
    tokens:[{id:'stranger',name,label:'ST'}],
    blockers:[{name:'Maple stone wall'}],
  }},ghosts:[19],changed:[],width:8});
  const words = node => [node.textContent,...node.children.map(words)].join(' ');
  for (const name of ['Sun Taitian','A masked traveler']) {
    remember(name);
    await hover(s,3,2);
    const text=words(s.doc.querySelector('.tt-hovercard'));
    assert.ok(text.includes(`${name} was here when you last saw this square. They may have moved.`));
    assert.match(text,/Maple stone wall.*current state is unknown/s);
    assert.doesNotMatch(text,/Secret true name|thin marked line blocks sight/);
    if (name !== 'Sun Taitian') assert.doesNotMatch(text,/Sun Taitian/);
  }
});

test('every board.* call in tabletop.js exists, and hovering a sight blocker square raises no error',async()=>{
  const s=setup(), seen=new Uint8Array(48);seen[19]=1;
  const source=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const used=new Set([...source.matchAll(/\bboard\.([A-Za-z_]\w*)/g)].map(m=>m[1]).filter(n=>n!=='js'));
  assert.ok(used.has('blockersAt'));
  const missing=[...used].filter(name=>!(name in s.board));
  assert.deepEqual(missing,[],'board.* calls with no board export');
  assert.equal(typeof s.board.blockersAt,'function');
  const geometry={sources:[{cells:[[3,1],[3,2],[3,3]],kind:'BLOCKED',name:'Talisman Wall',
    bottom_ft:0,top_ft:null,segments:[[[7,2],[7,8]],[[6,2],[8,2]],[[6,8],[8,8]]]}]};
  assert.doesNotThrow(()=>s.board.setFog(seen,null,{squareFog:true,blockerGeometry:geometry,blockerHeights:null}));
  assert.ok(s.board.blockersAt(3,2).length,'the wall square is a known blocker');
  assert.deepEqual(s.board.blockersAt(0,0),[]);
  await assert.doesNotReject(hover(s,3,2));
  await assert.doesNotReject(hover(s,0,0));
});
