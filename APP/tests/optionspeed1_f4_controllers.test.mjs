import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {setImmediate} from 'node:timers/promises';
import {OptionDraft} from '../static/tabletop/option-composition.js';
import {renderRankedMenu} from '../static/tabletop/ranked-menu.js';
import {createPlay as currentPlay} from '../static/play/play-client.js';
import {createViewerStore} from '../static/tabletop/viewer-identity.js';
import {installDOM, Element} from './objects_dom_stub.mjs';
import {readStdinPayload} from './node_stdin.mjs';

const input = await readStdinPayload();
// No stdin payload means this file is not being driven by its Python caller (the
// public CI node job runs the file on its own); report a skip, never a hang or a throw.
const f=input.trim() ? JSON.parse(input) : {};
if (!input.trim()) test('Python supplies the option-speed case on stdin', {skip: 'no stdin fixture'}, () => {});
const source=readFileSync(process.env.OPTIONSPEED_DESKTOP_SOURCE
  || new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
// Counterfactual runs can load an exact pre-fix client, while resolving its
// ordinary imports against the production module's original location.
let createPlay=currentPlay;
if (process.env.OPTIONSPEED_PHONE_SOURCE) {
  const original=new URL('../static/play/play-client.js',import.meta.url);
  const old=readFileSync(process.env.OPTIONSPEED_PHONE_SOURCE,'utf8').replace(
    /from (['"])(\.[^'"]+)\1/g,(_match,quote,path)=>`from ${quote}${new URL(path,original).href}${quote}`);
  createPlay=(await import('data:text/javascript;base64,'+Buffer.from(old).toString('base64'))).createPlay;
}
const settle=async predicate=>{
  for (let n=0;n<20 && !predicate();n++) await setImmediate();
  assert.ok(predicate(),'Controller did not open the expected targeting choice');
};

function desktop({withoutDraftRetention = false} = {}) {
  const document=installDOM('<body></body>'), state=structuredClone(f.state);
  const app={state,menu:state.menu,matchId:'review',lastSequence:state.last_sequence,selected:new Set()};
  const calls=[];
  let releaseMenu;
  const menuReady = new Promise(resolve => { releaseMenu = resolve; });
  const context=vm.createContext({app,document,OptionDraft,structuredClone,
    crypto:{randomUUID:()=> 'review-draft'},enc:encodeURIComponent,refreshSequence:0,
    escapeHtml:x=>String(x ?? '').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),
    markActive(){},refuseCoveredView:()=>false,
    cancelTargeting(){app.targeting?.resolve(false);app.targeting=null;app.pendingChoice=null;},
    hint(){},closeChoice(){},renderHighlights(){},broadcastActors(){},
    synchronizePresets:async()=>{},invalidateTargeting(){},renderActionBar(){},playEvents:async()=>{},gmNotice(){},
    refresh(){throw Error('Unexpected full refresh');},
    toast(message){throw Error(message);},withReactions:fn=>fn([]),handleUnavailableFight:async()=>false,
    actorById:id=>state.presentation.actors.find(a=>a.entity_id===id),isManualActor:()=>true,
    sheetFor:async()=>f.sheet,actors:()=>state.presentation.actors,
    api:async(path,options={})=>{
      calls.push({path,body:options.body});
      if (path.includes('/events?')) return {events:[],last_sequence:f.after.last_sequence};
      if (path.endsWith('/composition/preview')) return structuredClone(
        f.case==='named' && options.body.sources.includes(state.menu.composition[f.setting].source)
          ? f.initialPreview : f.preview);
      assert.ok(path.endsWith('/act'));
      return structuredClone(f.committed || {status:'COMMITTED',state:f.after || state,events:{events:[]}});
    },
  });
  const load=(start,end)=>{
    assert.ok(source.includes(start) && source.includes(end),`Missing production function ${start}`);
    let code=source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
    if (withoutDraftRetention) code=code.replace(
      'if (nativeDraft) app.pendingOptionDraft = {draft: nativeDraft, matchId: actionMatchId, round: draftRound};', '');
    vm.runInContext(code,context);
  };
  load('function draftOptionRows(', '\n// An ability the fight runs nothing for');
  load('function preferredTargets(', '\n// The cover hides');
  load('function actOnce(', '\nfunction chooseFromList');
  load('async function runButton(', '\nasync function localRoll');
  load('async function onCellClick(', '\n// A move is shown the moment');
  // Exercise production render, including its null-menu interval. Stub only
  // painting/board helpers, never menu or draft assignment.
  const nodes=new Map();
  Object.assign(context, {
    $:id=>{if (!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id);},
    reconcileViewerIdentity(){},renderCommitNotice(){},modelOwner:()=>Boolean(app.modelOwned),
    mapFromState:()=>({width:1,height:1,walls:[],objects:[],trees:[],decor:[],background:{},cells:{},floors:[]}),
    board:{setRoofView(){},setMap(){}},isGMView:()=>true,wallSightCells:()=>[],
    opacityGrid:()=>new Uint8Array(1),teamIndex:()=>0,
    renderZones(){},renderTokens(){},renderInitiative(){},renderRoster(){},renderInspector(){},
    renderItemsPanel(){},scheduleAutoPlay(){},renderPip(){},scheduleSeatPoll(){},
  });
  load('function reconcileOptionDraft(', '\n// The creatures whose perception');
  if (f.committed) {
    Object.assign(context, {
      readTableState:async()=>{await menuReady;return structuredClone(f.after);},
      loadSeats:async()=>{},resumeServerPrompt(){},
    });
    load('async function eventsThroughState(', '\nasync function setControl(');
  }
  return {app,context,calls,document,releaseMenu};
}

async function fireAtSelf(d) {
  await settle(()=>d.app.targeting);
  const expected=f.preview.menu.actions.flatMap(g=>g.options);
  assert.equal(d.app.targeting.group.options.length,expected.length,'Every legal preview option remains reachable');
  const pos=f.state.presentation.actors.find(a=>a.entity_id===f.state.menu.actor_id).position;
  const option=expected.find(o=>{
    const p=o.destination || o.area?.center;
    return p && p.x===pos.x && p.y===pos.y;
  });
  assert.ok(option,'Real service preview includes the chosen square');
  await d.context.onCellClick(option.destination || option.area.center);
  await settle(()=>d.calls.some(c=>c.path.endsWith('/act')));
  return d.calls.find(c=>c.path.endsWith('/act')).body;
}

if (f.case==='assisted') test('desktop Assisted ranked confirmation previews the draft and reconfirms its square',async()=>{
  const d=desktop();
  const group=d.app.menu.actions.find(g=>g.source_definition_id===f.source);
  const option=group.options[0];
  const slot={ACTION:'Action',BONUS_ACTION:'Bonus action',NONE:'Free'}[group.economy] || 'Action';
  d.app.menu.ranked_slots={[slot]:[option.candidate_id]};
  const ranked=renderRankedMenu(d.app.menu,{doc:d.document,onAct:id=>d.context.actOnce(id),onMove(){throw Error('Not movement');}});
  const button=ranked.querySelectorAll('button').find(b=>b.querySelector('b')?.textContent===group.label);
  assert.ok(button,'Assisted exposes the real saved candidate');
  d.context.chooseLocalOption(f.setting);
  assert.equal(d.calls.length,0);
  void button.click();
  await settle(()=>d.calls.length);
  assert.ok(d.calls[0].path.endsWith('/composition/preview'),'Assisted must preview the draft before committing');
  assert.equal(d.calls.filter(c=>c.path.endsWith('/act')).length,0,'Changed square configuration requires confirmation');
  const body=await fireAtSelf(d);
  assert.deepEqual(JSON.parse(JSON.stringify(body.composition)),d.calls[0].body);
  assert.equal(d.calls.length,2);
  console.log('REVIEW_PAYLOAD '+JSON.stringify(body));
});

if (f.case==='named') test('named sheet talent overrides a conflicting local draft even when saved-active',async()=>{
  const d=desktop();
  d.context.chooseLocalOption(f.setting);
  // The player cancels aiming before clicking the explicitly named sheet row.
  void d.context.useGroup(d.app.menu.actions.find(g=>g.source_definition_id===f.source));
  await settle(()=>d.app.targeting);
  d.context.cancelTargeting();
  d.calls.length=0;
  void d.context.runButton(f.named,d.app.menu.actor_id);
  await settle(()=>d.calls.length);
  const wanted=f.preview.menu; // The real preview supplied by Python is Pure Darkness.
  const selected=d.context.draftOptionRows(d.app.menu.actor_id).find(row=>row.base===f.source);
  assert.deepEqual(Array.from(selected.options.find(o=>o.active).talents),f.named.shape.talents,
    'Explicitly named saved-active talent must replace the conflicting draft');
  assert.equal(d.calls[0].body.sources[0],d.app.menu.composition[
    selected.options.find(o=>o.active).candidate_id].source);
  const body=await fireAtSelf(d);
  assert.ok(wanted.actions.length);
  assert.equal(d.calls.length,2);
  console.log('REVIEW_PAYLOAD '+JSON.stringify(body));
});

if (f.case==='native' && f.client==='desktop') test('desktop native action bypasses composition and keeps the local draft',async()=>{
  const d=desktop();
  d.context.chooseLocalOption(f.setting);
  const picks=Array.from(d.app.optionDraft.picks.values(),p=>p.source);
  const native=d.app.menu.actions.find(g=>g.source_definition_id===f.native);
  void d.context.useGroup(native);
  await settle(()=>d.calls.length);
  assert.equal(d.calls.length,1);
  assert.ok(d.calls[0].path.endsWith('/act'),'Native action must use its issued candidate, not a composition preview');
  assert.equal(d.calls[0].body.composition,undefined);
  await settle(()=>d.app.menu?.state_version===f.after.menu.state_version && !d.app.busy);
  assert.ok(d.app.optionDraft?.matches(d.app.menu,d.app.matchId),'Native action retains the local draft');
  assert.deepEqual(Array.from(d.app.optionDraft.picks.values(),p=>p.source),picks);
  assert.equal(d.app.composedAction,null);
  console.log('REVIEW_PAYLOAD '+JSON.stringify(d.calls[0].body));
});

if (f.case==='deferred-native') test('desktop retains native-action drafts across the real deferred HTTP menu',async()=>{
  async function exercise(withoutDraftRetention=false) {
    const d=desktop({withoutDraftRetention});
    d.context.chooseLocalOption(f.setting);
    const native=d.app.menu.actions.find(g=>g.source_definition_id===f.native);
    assert.equal(await d.context.useGroup(native),true);
    assert.equal(d.app.menu,null,'HTTP committed response has no menu yet');
    assert.equal(d.app.optionDraft,null,'Stale candidates are unavailable during the delayed read');
    assert.equal(d.calls.filter(c=>c.path.endsWith('/act')).length,1);
    assert.equal(d.calls.filter(c=>c.path.endsWith('/composition/preview')).length,0);
    d.releaseMenu();
    await settle(()=>d.app.menu?.state_version===f.after.menu.state_version);
    assert.ok(d.app.optionDraft?.matches(d.app.menu,d.app.matchId),
      'Deferred native action must retain the local draft after its menu arrives');
    const nativePayload=d.calls.find(c=>c.path.endsWith('/act')).body;
    assert.equal(nativePayload.composition,undefined);
    void d.context.useGroup(d.app.menu.actions.find(g=>g.source_definition_id===f.source));
    await settle(()=>d.app.targeting);
    const previews=d.calls.filter(c=>c.path.endsWith('/composition/preview'));
    assert.equal(previews.length,1);
    assert.deepEqual(Array.from(previews[0].body.sources),[f.state.menu.composition[f.setting].source]);
    assert.equal(previews[0].body.state_version,f.after.menu.state_version);
    assert.equal(previews[0].body.decision_id,f.after.menu.decision_id);
    assert.equal(d.app.targeting.group.options.length,f.preview.menu.actions.flatMap(g=>g.options).length);
    return {nativePayload,previewPayload:previews[0].body};
  }
  const payload=await exercise();
  // Removing the retention assignment must reproduce the precise review bug,
  // rather than letting a transport/VM error count as a negative control.
  await assert.rejects(()=>exercise(true),/Deferred native action must retain the local draft/);

  for (const departure of ['actor','round','match','model','automatic','missing-setting','terminal']) {
    const d=desktop();
    d.context.chooseLocalOption(f.setting);
    await d.context.useGroup(d.app.menu.actions.find(g=>g.source_definition_id===f.native));
    assert.ok(d.app.pendingOptionDraft,'Capture waits for the delayed menu');
    if (departure==='match') d.app.matchId='another-fight';
    const changed=structuredClone(f.after);
    if (departure==='actor') changed.presentation.current_actor_id='another-actor';
    if (departure==='round') changed.presentation.round_number++;
    if (departure==='model') d.app.modelOwned=true;
    if (departure==='automatic') changed.menu.manual=false;
    if (departure==='missing-setting') changed.menu.composition={};
    if (departure==='terminal') changed.presentation.terminal=true;
    d.context.render(changed);
    assert.equal(d.app.optionDraft,null,`${departure}: stale draft must not return`);
    assert.equal(d.app.pendingOptionDraft,null,`${departure}: discard captured choices`);
    // Complete the original read as well. An intervening actor/round transition
    // permanently invalidates the draft even if a later snapshot looks similar.
    d.releaseMenu();
    await d.context.requestDeferredMenu();
    assert.equal(d.app.optionDraft,null,`${departure}: late response must not restore discarded choices`);
  }
  console.log('REVIEW_PAYLOAD '+JSON.stringify(payload));
});

if (f.case==='move-draft') test('desktop retains the local choice across successful same-turn movement and rebases it',async()=>{
  const d=desktop();
  d.context.chooseLocalOption(f.setting);
  const move=f.state.menu.moves.find(o=>o.candidate_id===f.move);
  assert.ok(move);
  await d.context.actOnce(move.candidate_id);
  await settle(()=>d.app.menu?.state_version===f.after.menu.state_version && !d.app.busy);
  assert.ok(d.app.optionDraft?.matches(d.app.menu,d.app.matchId),'Movement must rebind choices to the fresh menu');
  void d.context.useGroup(d.app.menu.actions.find(g=>g.source_definition_id===f.source));
  await settle(()=>d.calls.some(c=>c.path.endsWith('/composition/preview')));
  assert.deepEqual(d.calls.find(c=>c.path.endsWith('/composition/preview')).body.sources,
    [f.state.menu.composition[f.setting].source]);
  assert.equal(d.calls.find(c=>c.path.endsWith('/composition/preview')).body.state_version,f.after.menu.state_version);
});

if (f.case==='move-draft-phone') test('phone retains the local choice across successful same-turn movement and rebases it',async()=>{
  const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
  doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
  const viewerStore=createViewerStore({viewId:'movement-phone'}),id=f.state.menu.actor_id;
  viewerStore.bindPlayer('review',[id]);
  let state=structuredClone(f.state); const calls=[];
  const request=async(path,options={})=>{
    calls.push({path,body:options.body});
    if(path.includes('/state?')) return structuredClone(state);
    if(path.endsWith('/seat-status')) return {seats:{}};
    if(path.includes('/events?')) return {events:[],last_sequence:state.last_sequence};
    if(path.endsWith('/sheet')) return {buttons:[]};
    if(path.endsWith('/composition/preview')) return structuredClone(f.preview);
    assert.ok(path.endsWith('/act'),`Unexpected transport ${path}`); state=structuredClone(f.after); return {status:'COMMITTED'};
  };
  const board={element:new Element(),map:{width:20,height:20},view:{zoom:1},closeHoverCard(){},fit(){},terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
  for(const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
  const client=createPlay({doc,request,board,viewerStore,frame:()=>{},memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},controlStore:{read:()=> 'MANUAL',write(){}}});
  await client.load('review');
  const setting=state.menu.actions.find(g=>g.options.some(o=>o.candidate_id===f.setting));
  await client.choose(setting); calls.length=0;
  assert.ok(await client.submit(f.move),'Movement remains usable while drafting');
  calls.length=0;
  await client.choose(client.state.menu.actions.find(g=>g.source_definition_id===f.source));
  assert.equal(calls.length,1);
  assert.ok(calls[0].path.endsWith('/composition/preview'));
  assert.deepEqual(calls[0].body.sources,[f.state.menu.composition[f.setting].source]);
  assert.equal(calls[0].body.state_version,f.after.menu.state_version);
});

if (f.case==='native' && f.client==='phone') test('phone native action bypasses composition and retains the draft for the next ability',async()=>{
  const doc=installDOM(readFileSync(new URL('../static/play/play.html',import.meta.url),'utf8'));
  doc.createTextNode=text=>Object.assign(new Element('span'),{textContent:String(text),nodeType:3});
  const viewerStore=createViewerStore({viewId:'review-phone'}),id=f.state.menu.actor_id;
  viewerStore.bindPlayer('review',[id]);
  let state=structuredClone(f.state);
  const calls=[];
  const request=async(path,options={})=>{
    calls.push({path,body:options.body});
    if (path.includes('/state?')) return structuredClone(state);
    if (path.endsWith('/seat-status')) return {seats:{}};
    if (path.includes('/events?')) return {events:[],last_sequence:state.last_sequence};
    if (path.endsWith('/sheet')) return {buttons:[]};
    if (path.endsWith('/composition/preview')) return structuredClone(f.preview);
    assert.ok(path.endsWith('/act'),`Unexpected transport ${path}`);
    state=structuredClone(f.after);
    return {status:'COMMITTED'};
  };
  const board={element:new Element(),map:{width:20,height:20},view:{zoom:1},closeHoverCard(){},fit(){},
    terrainAt:()=>[],zonesAt:()=>[],floorRecordAt:()=>null};
  for (const name of ['setMap','setRoofView','setZones','setTokens','setFog','setRemembered','setHighlights']) board[name]=()=>{};
  const client=createPlay({doc,request,board,viewerStore,frame:()=>{},
    memoryStore:{read:()=>({version:3,cells:{}}),ready:()=>false},controlStore:{read:()=> 'MANUAL',write(){}}});
  await client.load('review');
  const setting=state.menu.actions.find(g=>g.options.some(o=>o.candidate_id===f.setting));
  const native=state.menu.actions.find(g=>g.source_definition_id===f.native);
  await client.choose(setting);
  calls.length=0;
  await client.choose(native);
  assert.equal(calls.length,0,'Choosing a native action must not preview a composition');
  assert.ok(await client.submit(native.options[0].candidate_id),'Native action remains usable while drafting');
  const write=calls.find(c=>c.path.endsWith('/act'));
  assert.ok(write,'Native action must commit');
  assert.equal(write.body.composition,undefined);
  calls.length=0;
  await client.choose(client.state.menu.actions.find(g=>g.source_definition_id===f.source));
  assert.equal(calls.length,1,'Retained draft is previewed when its ability is subsequently aimed');
  assert.ok(calls[0].path.endsWith('/composition/preview'));
  assert.deepEqual(calls[0].body.sources,[f.state.menu.composition[f.setting].source]);
  assert.equal(calls[0].body.state_version,f.after.menu.state_version);
  const offered=doc.getElementById('actionList').querySelectorAll('button').filter(b=>b.dataset.candidate);
  assert.equal(offered.length,f.preview.menu.actions.flatMap(g=>g.options).length);
  console.log('REVIEW_PAYLOAD '+JSON.stringify(write.body));
});
