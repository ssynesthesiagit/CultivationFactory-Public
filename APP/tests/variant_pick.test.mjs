import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function declaration(name) {
  const start = source.search(new RegExp('(?:async )?function ' + name + '\\('));
  assert.notEqual(start, -1, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function harness() {
  const calls = [], toasts = [], aims = [];
  const actor = {entity_id:'me',display_name:'Wren'};
  const chosen = {source_definition_id:'ability+a',options:[]};
  const version = {source_definition_id:'ability+b', label:'Wide ability', lazy:false,
    options:[{candidate_id:'b-left',target_ids:[],area:{center:{x:2,y:3}}},
             {candidate_id:'b-right',target_ids:[],area:{center:{x:3,y:3}}}]};
  const menu = {actor_id:'me',manual:true,decision_id:'d1',state_version:1,actions:[chosen],
    augment_versions:{'ability+b':{family:'ability',augments:['b'],selected:false}}};
  const app = {matchId:'fight',menu,state:{menu,unavailable_reasons:{'act:ability+b':'Wrong loadout'}},
    optionDraft:{matches:()=>true,request:()=>({sources:['shape:fire']})}};
  const context = {app, crypto:{randomUUID:()=> 'request'}, refreshSequence:0,
    synchronizePresets:async()=>{}, actorById:()=>actor,isManualActor:()=>true,
    refuseCoveredView:()=>false, cancelTargeting(){}, cancelAbilityChoice(){}, hint(){},
    preferredTargets:()=>[], menuReadFor:()=>({fog:true,compact:true}), enc:encodeURIComponent,
    document:{body:{classList:{add(){},remove(){}}}},
    reasonFor:()=> 'LOADOUT refusal', toast:(...args)=>toasts.push(args),
    refresh(){throw Error('full menu refetch');},
    render(state, options) {
      assert.equal(options.keepBar, true);
      app.state=state; app.menu=state.menu; app.optionDraft=null;
    },
    async api(path, options) {
      calls.push({path,body:options.body});
      return {menu:{...menu,decision_id:'d2',state_version:2,actions:[version]},
        state:{menu:{...menu,decision_id:'d2',state_version:2,actions:[version]}}};
    },
    chooseLocalOption(){throw Error('Version click is not a relative toggle');},
    renderHighlights(){}, broadcastActors(){},
    actOnce(){throw Error('Cast before the player picked a target');},
    chooseFromList(){throw Error('Expected the map target step');},
  };
  for (const name of ['runButton','selectAbilityVersion','useGroup']) vm.runInNewContext(declaration(name),context);
  return {context,app,calls,toasts,aims,version,
    button:{id:'act:ability+b',kind:'combat',label:'Wide ability',combat:{source_definition_id:'ability+b'}}};
}

for (const entry of ['sheet','bar']) test(entry + ' click selects a non-selected version then aims its returned targets without refetch', async () => {
  const h=harness();
  // Both production entrypoints call runButton; the sheet supplies this row
  // over BroadcastChannel, while the bar binds the same row to its click.
  assert.match(source, entry === 'sheet' ? /runButton\(message.button, message.actor_id\)/ : /onClick: \(\) => runButton\(action, menu.actor_id\)/);
  const pending=h.context.runButton(h.button,'me');
  // Let the settings reply render; the real useGroup must then wait for a
  // player target, rather than firing an old/default candidate.
  for (let i=0; i<10 && !h.app.targeting; i++) await new Promise(resolve=>setImmediate(resolve));
  assert.ok(h.app.targeting, 'The same click must open the real map targeting step');
  assert.equal(h.app.busy,false);
  assert.equal(h.app.targeting.decisionId,'d2');
  assert.equal(h.app.targeting.group.source_definition_id,'ability+b');
  assert.deepEqual(h.app.targeting.group.options,h.version.options);
  assert.equal(h.app.targeting.areas.length,2);
  assert.equal(h.app.targeting.group.lazy,false);
  h.app.targeting.resolve(true);
  const result=await pending;
  assert.equal(result.ok,true);
  assert.equal(h.calls.length,1);
  assert.match(h.calls[0].path,/composition\/select-version$/);
  assert.equal(h.calls[0].body.source_definition_id,'ability+b');
  assert.deepEqual(h.calls[0].body.sources,['shape:fire']);
  assert.deepEqual(h.toasts,[]);
});

test('illegal version reports its own server reason and never opens old targets or refetches', async () => {
  const h=harness();
  h.context.api=async()=>{throw Error('Requires 2 CP; you have 1.');};
  const result=await h.context.runButton(h.button,'me');
  assert.equal(result.ok,false);
  assert.equal(result.message,'Requires 2 CP; you have 1.');
  assert.equal(h.app.targeting,undefined);
  assert.equal(h.app.busy,false);
});

test('covered and AI clicks cannot change a selection', async () => {
  for (const block of ['cover','AI']) {
    const h=harness();
    if (block==='cover') h.context.refuseCoveredView=()=>true;
    else h.context.isManualActor=()=>false;
    assert.equal((await h.context.runButton(h.button,'me')).ok,false);
    assert.equal(h.calls.length,0);
    assert.equal(h.app.targeting,undefined);
  }
});

test('bar and sheet expose owned version selectors instead of the old loadout cast refusal', () => {
  const h=harness();
  vm.runInNewContext(declaration('reasonFor'),h.context);
  assert.equal(h.context.reasonFor({},h.button),'');
  // Keep the server reason for a version that is already selected: that button
  // really casts, rather than checking a new selection.
  h.app.menu.augment_versions['ability+b'].selected=true;
  assert.equal(h.context.reasonFor({},h.button),'Wrong loadout');
  assert.match(source,/Boolean\(menu.augment_versions\?\.\[source\]\)/);
  const actorMessage=declaration('actorMessage');
  assert.match(actorMessage,/\.\.\.versionChoices/);
});
