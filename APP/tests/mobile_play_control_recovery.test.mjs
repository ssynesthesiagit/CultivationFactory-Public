// A transient control-setting failure must not abandon the guided phone default.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

test('guided entry recovers a failed first state read or controller setting without replaying combat or overriding Manual', async () => {
  for (const failure of ['initial-state', 'controller-mode']) for (const preference of [null, 'MANUAL']) {
    const id='actor:factory.control-recovery', writes=[];
    const doc=installDOM(readFileSync(new URL('../static/play/play.html', import.meta.url), 'utf8'));
    doc.createTextNode=text=>Object.assign(new Element('span'), {textContent:String(text), nodeType:3});
    const viewerStore=createViewerStore({viewId:'control-recovery'});
    viewerStore.bindPlayer('fight', [id]);
    const snapshot={presentation:{display_name:'Control recovery', current_actor_id:id, round_number:1, zones:[],
      battlefield:{width_squares:2,height_squares:2,terrain_regions:[]},
      actors:[{entity_id:id,display_name:'Player',primary_combatant:true,controller:'MANUAL',
        active:true,team_index:0,position:{x:0,y:0,z:0}}]},
      menu:{actor_id:id,manual:true,decision_id:'d',state_version:1,control_mode:'MANUAL',
        actions:[],moves:[],end_turn:'end'},
      fog_perception:{[id]:{cells:[[0,0]],creatures:[id]}}};
    let failOnce=true;
    const request=async(path, options={})=>{
      if (options.body) {
        assert.ok(path.endsWith('/controller-mode'), 'Recovery must never submit a combat action');
        writes.push(options.body);
        if (failOnce && failure === 'controller-mode') {failOnce=false; throw new Error('Temporary control-setting connection loss');}
        snapshot.presentation.actors[0].controller=options.body.controller_mode;
        snapshot.menu.control_mode=options.body.controller_mode;
        return {};
      }
      if (path.includes('/state?')) {
        if (failOnce && failure === 'initial-state') {failOnce=false; throw new Error('Temporary state connection loss');}
        return structuredClone(snapshot);
      }
      if (path.endsWith('/seat-status')) return {seats:{}};
      if (path.includes('/events?')) return {events:[]};
      if (path.endsWith('/sheet')) return {buttons:[]};
      throw new Error(`Unexpected fake request ${path}`);
    };
    const board={element:new Element(),map:{width:2,height:2},view:{zoom:1},closeHoverCard(){},fit(){},
      terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
    for (const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
    const client=createPlay({doc,request,board,viewerStore,frame:()=>{},
      memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},controlStore:{read:()=>preference,write(){}}});
    await client.load('fight');
    if (failure === 'initial-state') assert.equal(client.state, null);
    else assert.equal(client.state.menu.control_mode, 'MANUAL');
    assert.equal(writes.length, preference || failure === 'initial-state' ? 0 : 1, 'No immediate retry loop after a failed read or setting');
    await client.refresh();
    assert.equal(client.state.menu.control_mode, preference || 'SUGGESTED',
      'Controller must initialize after a transient setting failure');
    const expectedWrites=preference ? 0 : failure === 'initial-state' ? 1 : 2;
    assert.equal(writes.length, expectedWrites);
    await client.refresh();
    assert.equal(writes.length, expectedWrites, 'A successful default must not write again on every poll');
  }
});
