// Phone entry defers Assisted until an existing decision has resolved remotely.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {createPlay} from '../static/play/play-client.js';

test('Assisted entry resumes after a remote decision or unavailable seat authority recovers, preserving explicit Manual', async () => {
  for (const gate of ['decision', 'seats']) for (const preference of [null, 'MANUAL']) {
    const id='actor:factory.deferred', other='actor:factory.other', writes=[];
    const doc=installDOM(readFileSync(new URL('../static/play/play.html', import.meta.url), 'utf8'));
    doc.createTextNode=text=>Object.assign(new Element('span'), {textContent:String(text), nodeType:3});
    const viewerStore=createViewerStore({viewId:'deferred-control'});
    viewerStore.bindPlayer('fight', [id]);
    const snapshot={presentation:{display_name:'Deferred entry', current_actor_id:id, round_number:1, zones:[],
      battlefield:{width_squares:2, height_squares:2, terrain_regions:[]},
      actors:[{entity_id:id, display_name:'Player', primary_combatant:true, controller:'MANUAL',
        active:true, team_index:0, position:{x:0,y:0,z:0}}]},
      menu:{actor_id:id, manual:true, decision_id:'d', state_version:1, control_mode:'MANUAL',
        actions:[], moves:[], end_turn:'end'},
      fog_perception:{[id]:{cells:[[0,0]], creatures:[id]}},
      pending_action:{method:'act', request:{candidate_id:'other-action'}, reactions:[],
        reaction:{context:{reactor_id:other}, reaction:'Another player decides'}}};
    let seatsReady=gate !== 'seats';
    if (gate === 'seats') snapshot.pending_action=null;
    const request=async (path, options={})=>{
      if (options.body) {
        assert.ok(path.endsWith('/controller-mode'), 'Phone entry must not submit combat actions');
        assert.equal(snapshot.pending_action, null, 'Do not change control during any pending decision');
        assert.ok(seatsReady, 'Do not change control before checking seat authority');
        writes.push(options.body);
        snapshot.presentation.actors[0].controller=options.body.controller_mode;
        snapshot.menu.control_mode=options.body.controller_mode;
        return {};
      }
      if (path.includes('/state?')) return structuredClone(snapshot);
      if (path.endsWith('/seat-status')) {
        if (!seatsReady) throw new Error('Seat authority temporarily unavailable');
        return {seats:{}};
      }
      if (path.includes('/events?')) return {events:[]};
      if (path.endsWith('/sheet')) return {buttons:[]};
      throw new Error(`Unexpected fake request ${path}`);
    };
    const board={element:new Element(), map:{width:2,height:2}, view:{zoom:1}, closeHoverCard(){}, fit(){},
      terrainAt:()=>[], zonesAt:()=>[], floorRecordAt:()=>null};
    for (const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
    const client=createPlay({doc,request,board,viewerStore,frame:()=>{},
      memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false}, controlStore:{read:()=>preference,write(){}}});
    await client.load('fight');
    assert.deepEqual(writes, []);
    snapshot.pending_action=null;
    seatsReady=true;
    await client.refresh();
    assert.equal(client.state.menu.control_mode, preference || 'SUGGESTED');
    assert.deepEqual(writes, preference ? [] : [{actor_id:id,controller_mode:'SUGGESTED'}]);
    await client.refresh();
    assert.equal(writes.length, preference ? 0 : 1, 'Initialization must happen once, not on every poll');
  }
});
