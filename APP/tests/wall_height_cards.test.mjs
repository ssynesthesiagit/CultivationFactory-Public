import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {detectRoofRegions, roofSettings, roofOpacity} from '../static/tabletop/roof-regions.js';
import {wallHeightFt, heightInput} from '../static/tabletop/map-heights.js';
import defaults from '../static/tabletop/map-heights.json' with {type:'json'};
import {INDOOR_STYLES} from '../static/tabletop/floor-art-indoor.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';

function map() {
  const d = JSON.parse(readFileSync(new URL('../combat/maps/builtin-willow-village-compound.json',import.meta.url)));
  return {...d,width:d.width_squares,height:d.height_squares,
    floors:d.materials.filter(r=>r.material.startsWith('floor:')).map(r=>({style:r.material.slice(6),cells:r.cells}))};
}
const text = node => [node.textContent || '', ...(node.children || []).map(text)].join(' ');

test('shared defaults cover every indoor style and preserve explicit height',()=>{
  assert.deepEqual(new Set(defaults.indoor_styles),new Set(['wood','tiles','marble','flagstone',...Object.keys(INDOOR_STYLES)]));
  assert.equal(wallHeightFt({kind:'building',storeys:3}),30);
  assert.equal(wallHeightFt({look:'bamboo_fence'}),5);
  assert.equal(wallHeightFt({height_ft:0}),0);
  for (const bad of ['', ' ', '-1', '1.5', 'Infinity']) assert.equal(heightInput(bad),null);
  assert.equal(heightInput('27'),27);
});

test('production board hover names wall, building and roof heights',async()=>{
  const dom=installDOM('<body></body>');
  const board=createBoard(dom.body), d=map();
  board.setMap(d);
  const timers=[];
  globalThis.setTimeout=fn=>{timers.push(fn);return timers.length;};
  async function hover(x,y) {
    board.closeHoverCard();
    const view=board.view, box=board.viewport.getBoundingClientRect();
    await board.viewport.dispatch('pointermove',{clientX:box.left+view.x+(x+.5)*48*view.zoom,
      clientY:box.top+view.y+(y+.5)*48*view.zoom,buttons:0});
    for (const fn of timers.splice(0)) fn();
    return text(dom.body.querySelector('.tt-zone-tip'));
  }
  assert.match(await hover(10,0),/Wall · 10 ft high/);
  const home=await hover(4,4);
  assert.match(home,/Building · 10 ft high/);
  assert.match(home,/Roof · 15 ft/);
  assert.match(home,/roof hides the room beneath it/i);
  board.setMap({...d,roofs:{regions:[{x:4,y:4,height_ft:32}]}});
  assert.match(await hover(4,4),/Roof · 32 ft/);
  board.setMap({...d,roofs:{enabled:false}});
  assert.doesNotMatch(await hover(4,4),/Roof ·/);
  board.setTokens(tableObjectTokens([{id:'wall',kind:'wall_section',name:'Stone wall',x:4,y:4,height_ft:22}],new Set(),[],null,40));
  await board.tokenNode('wall').dispatch('pointerenter');
  for (const fn of timers.splice(0)) fn();
  assert.match(dom.body.querySelector('.tt-token-card').innerHTML,/22 ft high above its base/);
  board.setMap(d);
  board.setTokens([{id:'flyer',x:4,y:4,altitude_ft:40,name:'Flying creature',hp:10,maxHp:10}]);
  board.setRoofView({gm:false,viewers:[{entity_id:'flyer',position:{x:4,y:4,z:8}}]});
  assert.equal(board.element.querySelectorAll('[data-roof]')[0].style.opacity,'1','animated XY retains the viewer altitude above the roof');
});

test('roof defaults follow tall walls and explicit per-building peaks win',()=>{
  const d=map();
  d.walls.filter(w=>w.id.startsWith('west-home')).forEach(w=>{w.height_ft=30;});
  const home=detectRoofRegions(d)[0];
  assert.equal(home.wall_height_ft,30);
  assert.equal(roofSettings(home).height_ft,35);
  assert.equal(roofSettings(home,{height_ft:40,regions:[{x:4,y:4,height_ft:45}]}).height_ft,45);
  const low=detectRoofRegions(map())[0];
  assert.equal(roofOpacity(low,{viewers:[{position:{x:4,y:4,z:0}}]}),0);
  assert.equal(roofOpacity(low,{viewers:[{position:{x:4,y:4,z:8}}]}),1);
  assert.equal(roofOpacity(low,{viewers:[{x:4,y:4,altitude_ft:15}]}),1,'standing on the roof does not reveal its interior');
});
