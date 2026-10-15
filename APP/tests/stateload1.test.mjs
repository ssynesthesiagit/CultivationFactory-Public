import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {createPlay} from '../static/play/play-client.js';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';

test('phone paints its bound fog snapshot while the complete menu waits; late menus cannot replace another fight', async () => {
  for (const switchMatch of [false, true]) {
    const actor='actor:factory.stateload1', calls=[];
    const doc=installDOM(readFileSync(new URL('../static/play/play.html', import.meta.url), 'utf8'));
    doc.createTextNode=text=>Object.assign(new Element('span'), {textContent:String(text),nodeType:3});
    const viewerStore=createViewerStore({viewId:'stateload1'});
    for (const id of ['first','second']) viewerStore.bindPlayer(id,[actor]);
    const snapshot={presentation:{display_name:'Scratch fight',current_actor_id:actor,round_number:1,zones:[],
      battlefield:{width_squares:2,height_squares:2,terrain_regions:[]},
      actors:[{entity_id:actor,display_name:'Player',primary_combatant:true,controller:'MANUAL',active:true,
        team_index:0,position:{x:0,y:0,z:0},hit_points:{current:20,maximum:20},conditions:[],resources:[]}]},
      menu:null,menu_pending:{actor_id:actor,state_version:1},last_sequence:0,
      fog_perception:{[actor]:{cells:[[0,0]],creatures:[actor]}}};
    const menu={actor_id:actor,manual:true,control_mode:'MANUAL',decision_id:'first-decision',state_version:1,
      actions:[{label:'Strike',options:Array.from({length:75},(_,i)=>({candidate_id:`strike-${i}`,target_ids:[actor]}))}],moves:[],end_turn:'end'};
    let release;
    const wait=new Promise(resolve=>{release=resolve;});
    const request=async(path,options={})=>{
      calls.push(path);
      assert.equal(options.body,undefined,'No combat or control write while loading');
      if (path.includes('/state?')) {
        const url=new URL(path,'http://localhost');
        assert.equal(url.searchParams.get('fog_view'),'own');
        assert.deepEqual(url.searchParams.getAll('fog_actor_ids'),[actor]);
        const result=structuredClone(snapshot);
        if (url.searchParams.get('include_menu')==='true') {
          if (path.includes('/first/')) await wait;
          result.menu=structuredClone(menu);
          if (path.includes('/second/')) result.menu.decision_id='second-decision';
          delete result.menu_pending;
        }
        return result;
      }
      if (path.endsWith('/seat-status')) return {seats:{}};
      if (path.includes('/events?')) return {events:[],last_sequence:0};
      if (path.endsWith('/sheet')) return {buttons:[]};
      throw new Error(`Unexpected request: ${path}`);
    };
    const board={element:new Element(),map:{width:2,height:2},view:{zoom:1},closeHoverCard(){},fit(){},
      terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
    for (const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
    const client=createPlay({doc,request,board,viewerStore,frame:()=>{},
      memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},controlStore:{read:()=> 'MANUAL',write(){}}});
    await client.load('first');
    assert.equal(doc.getElementById('mapCover').hidden,true,'Fight must paint before menu finishes');
    assert.equal(client.state.menu,null);
    assert.equal(doc.getElementById('actionsButton').disabled,true);
    assert.ok(calls.some(path=>path.includes('include_menu=true')));
    assert.equal(await client.submit('strike-74'),false);
    const switched=switchMatch ? client.load('second') : null;
    release();
    if (switched) await switched;
    // Drain the asynchronous full-state read and its sheet rendering.
    for (let i=0;i<20;i++) await Promise.resolve();
    assert.equal(client.state.menu.decision_id,switchMatch ? 'second-decision' : 'first-decision');
    assert.equal(client.state.menu.actions[0].options.length,75,'All legal options remain reachable');
    assert.equal(client.state.menu.actions[0].options.at(-1).candidate_id,'strike-74');
  }
});
