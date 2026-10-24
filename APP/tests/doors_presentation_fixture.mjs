// Headless editor-save and table-token fixture; no browser or visual-layout claim.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {installDOM} from './objects_dom_stub.mjs';
import {durability as defaults} from './object_defaults_fixture.mjs';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';
import {objectArt} from '../static/tabletop/object-art.js';

const [mode, kind, flag] = process.argv.slice(2);
const opened = flag === '1';
if (mode === 'editor') {
  const dom = installDOM(readFileSync(new URL('../static/tabletop/mapeditor.html', import.meta.url), 'utf8'));
  let saved = {map_id:'sol195', display_name:'Unattached opening', width_squares:20, height_squares:14,
    walls:[], terrain:[], materials:[], trees:[], background:{style:'plain'},
    starts:{team1:[],team2:[]}, objects:[{id:1,kind,x:4,y:6,blocks:true},
      {id:2,kind:'crate',x:8,y:6,blocks:false}]};
  location.search = '?map=sol195';
  globalThis.fetch = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    let result;
    if (path === '/api/session') result = {token:'test'};
    else if (path === '/api/tabletop/terrains') result = {terrains:[]};
    else if (path === '/api/tabletop/maps' && body) result = saved = {...body.map,map_id:'sol195'};
    else if (path === '/api/tabletop/maps') result = {maps:[saved],builtin:[],object_defaults:defaults};
    else if (path === '/api/tabletop/maps/sol195') result = saved;
    else throw Error(`Unexpected API ${path}`);
    return {ok:true,status:200,text:async()=>JSON.stringify(result),json:async()=>structuredClone(result)};
  };
  await import('../static/tabletop/mapeditor.js');
  for (let i=0;i<100 && !window.mapEditor;i++) await tick();
  assert.ok(window.mapEditor);
  await dom.querySelector('[data-tool="object"]').click();
  await window.mapEditor.board.element.querySelector('.tt-token.is-object').click();
  const control = dom.querySelector('#meObjectOpen');
  assert.equal(control.disabled,false);
  control.checked = opened;
  await control.dispatch('change');
  await dom.querySelector('#meSave').click();
  assert.equal(saved.objects[0].blocks,!opened);
  assert.equal(saved.objects[0].mount_axis,undefined);
  console.log(JSON.stringify(saved));
} else if (mode === 'presentation') {
  const objects = JSON.parse(readFileSync(0,'utf8'));
  const object = objects.find(o=>o.id==='object:map.1');
  const token = tableObjectTokens(objects,new Set(),[],null,20).find(o=>o.id===object.id);
  assert.equal(token.open,opened,'cold-reloaded table token agrees with editor Open');
  assert.equal(object.mount_axis,undefined);
  assert.equal(objectArt(kind,token).includes('tt-art-arc'),opened);
  assert.equal(objects.find(o=>o.kind==='crate').open,undefined,'nonblocking crates are not openings');
} else throw Error(`Unknown mode ${mode}`);
