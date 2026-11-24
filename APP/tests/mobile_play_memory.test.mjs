// Phone capture -> durable JSON -> reload -> real shared board DOM. Canvas
// pixels/layout remain the lead's opt-in browser check; no browser is launched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {createFogMemoryStore} from '../static/tabletop/fog_memory_store.js';
import {memoryKey} from '../static/tabletop/fog_memory.js';
import {playerView} from '../static/play/play-model.js';
import {renderMap} from '../static/play/play-board.js';

const actorId='actor:factory.memory-test', matchId='phone-memory-test', width=14, height=10;
const key=memoryKey(matchId,`play:${actorId}:own`,width,height);
const at=(x,y)=>y*width+x;
function state() {
  return {presentation:{battlefield:{width_squares:width,height_squares:height,blocked_cells:[]},zones:[],
    round_number:1,current_actor_id:actorId,actors:[{entity_id:actorId,display_name:'Player',team_index:0,
      primary_combatant:true,controller:'MANUAL',active:true,position:{x:0,y:0},hit_points:{current:10,maximum:10}}]},
    map:{background:{style:'plain',seed:31}},objects:[],items:[],
    fog_perception:{[actorId]:{cells:[[2,1],[3,1],[12,8]],creatures:[actorId],objects:[]}}};
}
function board() {
  const doc=installDOM('<body><div id="map"></div></body>');
  return createBoard(doc.getElementById('map'));
}
function store(rows) {
  return createFogMemoryStore({backend:{supported:true,
    get:async id=>rows.has(id) ? JSON.parse(rows.get(id)) : undefined,
    set:async(id,value)=>{rows.set(id,JSON.stringify(value));}},
    onError:error=>{throw error;}});
}
async function render(b,s,m) {
  m.read(key); await m.flush(key);
  const view=playerView({version:1,role:'player',actor_ids:[actorId]},s,{seats:{}});
  assert.equal(view.ready,true);
  renderMap(b,s,view,{matchId,actorId,memoryStore:m});
  await m.flush(key);
}
function hide(s) {s.fog_perception[actorId]={cells:[[0,0]],creatures:[actorId],objects:[]};}
// Compare actual rendered geometry/paint, ignoring only per-rebuild SVG id
// namespaces. These are DOM assertions, not a fake board's call records.
function markup(node) {
  const attrs=Object.entries(node.attributes || {}).map(([k,v])=>[k,
    String(v).replace(/tt-remembered-(?:shape|walls|prop)-\d+/g,'saved-id')]);
  return [node.tagName,attrs,node.textContent,(node.children || []).map(markup)];
}
const layer=b=>b.element.querySelector('.tt-remembered-layer');

test('F9 phone preserves sight-time tree, decor and wall geometry after hidden edits and persisted reload',async()=>{
  const rows=new Map(), m=store(rows), b=board(), s=state();
  s.map.trees=[{id:'old-pine',x:2,y:1,look:'pine',size:1,seed:2}];
  s.map.decor=[{id:'old-fern',x:2,y:1,kind:'fern',seed:3}];
  s.map.walls=[{id:'old-wall',shape:'rect',filled:true,look:'bamboo_fence',points:[[2,1],[4,2]]}];
  await render(b,s,m);
  const saved=JSON.parse(rows.get(key)).cells[at(2,1)];
  assert.equal(typeof saved.scenery,'string');
  const scene=JSON.parse(saved.scenery);
  assert.equal(scene.trees[0].id,'old-pine');
  assert.equal(scene.decor[0].id,'old-fern');
  assert.equal(scene.walls[0].id,'old-wall');
  hide(s); await render(b,s,m);
  const before=layer(b).querySelectorAll('.tt-remembered-scenery').map(markup);
  const shapes=layer(b).querySelectorAll('.tt-remembered-shape').map(markup);
  assert.equal(before.length,2); assert.ok(shapes.length>=2,'tree and decor shapes are rendered');
  s.map.trees=[];s.map.decor=[];
  s.map.walls=[{id:'unseen-new-wall',shape:'rect',filled:true,look:'grey_brick',points:[[2,1],[4,2]]}];
  await render(b,s,m); // Same mounted phone after the unseen edit.
  assert.deepEqual(layer(b).querySelectorAll('.tt-remembered-scenery').map(markup),before);
  const reloaded=board(), next=store(rows);
  await render(reloaded,s,next);
  assert.equal(next.read(key).cells[at(2,1)].scenery,saved.scenery);
  assert.deepEqual(layer(reloaded).querySelectorAll('.tt-remembered-scenery').map(markup),before);
  assert.deepEqual(layer(reloaded).querySelectorAll('.tt-remembered-shape').map(markup),shapes);
});

test('F9 phone persists explicit empty scenery so an unseen addition never appears on reload',async()=>{
  const rows=new Map(),m=store(rows),b=board(),s=state();
  await render(b,s,m);
  assert.equal(JSON.parse(rows.get(key)).cells[at(12,8)].scenery,null);
  hide(s);
  s.map.trees=[{x:12,y:8,look:'pine',size:1}];
  s.map.decor=[{x:12,y:8,kind:'fern'}];
  s.map.walls=[{id:'new-wall',shape:'rect',filled:true,look:'grey_brick',points:[[12,8],[13,9]]}];
  const reloaded=board(),next=store(rows);await render(reloaded,s,next);
  assert.equal(next.read(key).cells[at(12,8)].scenery,null);
  assert.equal(layer(reloaded).querySelectorAll('.tt-remembered-scenery').length,0);
  // Looking again legitimately replaces the old empty record.
  s.fog_perception[actorId].cells.push([12,8]);await render(reloaded,s,next);
  assert.equal(typeof next.read(key).cells[at(12,8)].scenery,'string');
});

test('F9 phone retains arranged and wall-offset open object art through hidden changes and persisted reload',async()=>{
  const rows=new Map(),m=store(rows),b=board(),s=state();
  // The table API supplies footprints. Small + tiny + tiny fills one square;
  // omitting them defaults to medium and makes the size assertion invalid.
  s.objects=[{id:'object:map.1',name:'Door',kind:'door',x:2,y:1,hp:10,max_hp:10,
      open:true,mount_axis:'h',mount_line:125,rotation:90},
    {id:'object:map.2',name:'Chest',kind:'chest',footprint:'small',x:3,y:1,hp:10,max_hp:10,rotation:90},
    {id:'object:map.3',name:'Barrel',kind:'barrel',footprint:'tiny',x:3,y:1,hp:10,max_hp:10},
    {id:'hidden-object',name:'Hidden chest',kind:'chest',footprint:'tiny',x:3,y:1,hp:10}];
  s.fog_perception[actorId].objects=s.objects.slice(0,3).map(o=>o.id);
  await render(b,s,m);
  const captured=JSON.parse(rows.get(key)).cells;
  const door=captured[at(2,1)].objects[0];
  assert.equal(typeof door.art,'string');
  assert.ok(door.art.includes('y="0.75"') && door.art.includes('data-open="1"'),'preserve the mounted open door');
  assert.equal(captured[at(3,1)].objects.length,2,'unperceived objects cannot enter memory');
  for(const o of captured[at(3,1)].objects) {
    assert.equal(o.art,b.objectArtRecordAt(o.id));
    assert.ok(Number(/width="([^"]+)"/.exec(o.art)[1])<1,`shared-square arrangement is retained: ${o.id} ${o.art.slice(0,180)}`);
  }
  hide(s);await render(b,s,m);
  const before=layer(b).querySelectorAll('.tt-remembered-object').map(markup);
  assert.equal(before.length,3);
  s.objects=s.objects.map(o=>({...o,kind:'barrel',open:false,rotation:0,mount_line:175}));
  const reloaded=board(),next=store(rows);await render(reloaded,s,next);
  assert.deepEqual(next.read(key).cells[at(3,1)].objects,captured[at(3,1)].objects);
  assert.deepEqual(layer(reloaded).querySelectorAll('.tt-remembered-object').map(markup),before);
  const hidden=reloaded.element.querySelectorAll('.tt-token').find(n=>n.getAttribute('aria-label')?.includes('Hidden chest'));
  assert.ok(hidden?.classList.contains('is-hidden'),'the shared board hides unperceived object nodes');
  assert.equal(reloaded.objectArtRecordAt('hidden-object'),null,'hidden current art cannot supply a memory snapshot');
});

test('F9 binding explanation describes the Assisted default and full alternatives with Manual available',()=>{
  const html=readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8');
  const copy=html.slice(html.indexOf('<dialog id="bindingCard"'),html.indexOf('<dialog id="reactionCard"'));
  for(const phrase of ['Assisted is the default','confirm, change or replace','any other legal option','Manual in Actions'])
    assert.ok(copy.includes(phrase),phrase);
  assert.equal(copy.includes('does not change who controls'),false);
});
