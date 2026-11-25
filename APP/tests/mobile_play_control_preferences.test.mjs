// Phone controller re-entry: a deliberate Manual choice survives reopening.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

test('explicit phone Manual preference survives a new controller instance; another binding still defaults Assisted', async()=>{
  const preferences=new Map(),writes=[],ids=['actor:factory.reentry','actor:factory.other'];
  const snapshot={presentation:{display_name:'Phone re-entry',current_actor_id:ids[0],round_number:1,zones:[],
    battlefield:{width_squares:2,height_squares:2,terrain_regions:[]},actors:ids.map((id,i)=>({entity_id:id,
      display_name:`Player ${i+1}`,primary_combatant:true,controller:'MANUAL',team_index:0,active:true,position:{x:i,y:0,z:0}}))},
    menu:{actor_id:ids[0],manual:true,decision_id:'d1',state_version:1,control_mode:'MANUAL',actions:[],moves:[],end_turn:'end'},
    fog_perception:Object.fromEntries(ids.map(id=>[id,{cells:[[0,0],[1,0]],creatures:ids}]))};
  const open=()=>{
    const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
    doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
    const viewerStore=createViewerStore({viewId:'reentry'});viewerStore.bindPlayer('fight', [ids[0]]);
    const board={element:new Element(),map:{width:2,height:2},view:{zoom:1},closeHoverCard(){},fit(){},
      terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
    for(const method of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[method]=()=>{};
    const request=async(path,options={})=>{
      if(options.body) {
        assert.ok(path.endsWith('/controller-mode'),'Re-entry must never commit an action');writes.push(options.body);
        const actor=snapshot.presentation.actors.find(a=>a.entity_id===options.body.actor_id);
        actor.controller=options.body.controller_mode;
        if(snapshot.menu.actor_id===actor.entity_id) snapshot.menu.control_mode=actor.controller;
        return {};
      }
      if(path.includes('/state?')) return structuredClone(snapshot);
      if(path.endsWith('/seat-status')) return {seats:{}};
      if(path.includes('/events?')) return {events:[]};
      if(path.endsWith('/sheet')) return {buttons:[]};
      throw new Error(`Unexpected fake request ${path}`);
    };
    return createPlay({doc,request,board,viewerStore,frame:()=>{},
      memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},
      controlStore:{read:key=>preferences.get(key),write:(key,mode)=>preferences.set(key,mode)}});
  };
  const first=open();await first.load('fight');
  assert.deepEqual(writes,[{actor_id:ids[0],controller_mode:'SUGGESTED'}]);
  assert.equal(await first.setControl('MANUAL'),true);
  assert.equal(preferences.get(`fight:${ids[0]}`),'MANUAL');
  const reopened=open();await reopened.load('fight');await reopened.refresh();
  assert.equal(writes.length,2);assert.equal(reopened.state.menu.control_mode,'MANUAL');
  assert.equal(await reopened.bind(ids[1]),true);
  assert.deepEqual(writes.at(-1),{actor_id:ids[1],controller_mode:'SUGGESTED'});
  assert.equal(preferences.get(`fight:${ids[0]}`),'MANUAL');
});
