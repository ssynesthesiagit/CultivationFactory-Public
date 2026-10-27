import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {setImmediate} from 'node:timers/promises';
import {OptionDraft} from '../static/tabletop/option-composition.js';
import {installDOM} from './objects_dom_stub.mjs';
import {readStdinPayload} from './node_stdin.mjs';

// Python supplies a real table snapshot and its scoped preview. Only transport
// and painting are stubbed; the panel, draft, targeting and /act payload are real.
const input = await readStdinPayload();
// No stdin payload means this file is not being driven by its Python caller (the
// public CI node job runs the file on its own); report a skip, never a hang or a throw.
const fixture = input.trim() ? JSON.parse(input) : null;
const noFixture = fixture ? false : 'Python supplies the table snapshot on stdin';
const source = readFileSync(process.env.OPTIONSPEED_DESKTOP_SOURCE
  || new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');

function desktop({contract = true, preview = fixture.preview} = {}) {
  const document = installDOM('<body></body>');
  const state = structuredClone(fixture.state), menu = state.menu;
  if (!contract) menu.composition = {};
  const family = state.shapes[menu.actor_id].find(row => row.base === fixture.family);
  family.choices.push({button_id:'act:unavailable-setting',label:'Unavailable setting',activation:false});
  const app = {state, menu, matchId:'draft-test', showShape:family.base, lastSequence:state.last_sequence};
  const calls = [], notices = [], painted = [];
  const forbidden = () => { throw Error('Draft rebuilt the full menu/state'); };
  const context = vm.createContext({app, document, OptionDraft, structuredClone,
    crypto:{randomUUID:()=> 'desktop-draft'}, enc:encodeURIComponent, refreshSequence:0,
    escapeHtml:value=>String(value ?? '').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),
    markActive(){}, refuseCoveredView:()=>false, cancelTargeting(){}, hint(){}, closeChoice(){},
    actors:()=>state.presentation.actors,
    renderHighlights(){}, broadcastActors(){}, synchronizePresets:async()=>{},
    invalidateTargeting(){}, renderActionBar(){ assert.equal(calls.at(-1)?.path.endsWith('/act'), true); },
    refresh:forbidden, render:state=>painted.push(state), playEvents:async()=>{}, gmNotice(){},
    withReactions:fn=>fn([]), handleUnavailableFight:async()=>false,
    toast:message=>notices.push(message),
    api:async(path, options)=>{
      calls.push({path,body:options.body});
      if (path.endsWith('/composition/preview')) return structuredClone(preview);
      assert.ok(path.endsWith('/act'), `Unexpected request: ${path}`);
      return {status:'COMMITTED',state:{committed:true},events:{events:[]}};
    },
  });
  const load = (start,end) => vm.runInContext(source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start))),context);
  load('function draftOptionRows(', '\n// An ability the fight runs nothing for');
  load('function actOnce(', '\nfunction chooseFromList');
  load('async function onCellClick(', '\n// A move is shown the moment');
  context.renderShapePanel();
  return {context, app, calls, notices, painted, panel:()=>document.getElementById('ttShape')};
}

test('desktop discovers missing secondary beside saved parent, previews it and commits chosen target', {skip: noFixture}, async () => {
  const d = desktop();
  assert.ok(d.app.menu.actions.some(g=>g.source_definition_id === fixture.family));
  assert.ok(!d.app.menu.actions.some(g=>g.source_definition_id === fixture.secondary));
  assert.equal(d.panel().querySelector('[data-option-activation]'), null);
  const choose = d.panel().querySelector(`[data-act="${fixture.medicinal}"]`);
  assert.ok(choose, 'Medicinal Blossom is available as a local setting');
  await choose.click();
  assert.equal(d.calls.length, 0, 'Changing the talent makes no request');
  const aim = d.panel().querySelector(`[data-option-activation="act:${fixture.secondary}"]`);
  assert.ok(aim, 'Draft-enabled secondary activation must have a desktop aiming button');
  assert.equal(d.panel().querySelector('[data-option-activation="act:unavailable-setting"]'),null);
  await aim.click();
  for (let i=0; i<10 && !d.app.targeting; i++) await setImmediate();
  assert.equal(d.calls.length,1);
  assert.equal(d.calls[0].body.source_definition_id,fixture.secondary);
  assert.deepEqual(Array.from(d.calls[0].body.sources),[fixture.medicinalSource]);
  assert.equal(d.app.targeting.group.options.length, fixture.preview.menu.actions.flatMap(g=>g.options).length);
  const chosen = d.app.targeting.destinations.find(o=>o.destination.x === 3 && o.destination.y === 6);
  assert.ok(chosen, 'The preview includes the willing caster’s square');
  await d.context.onCellClick(chosen.destination);
  await setImmediate();
  assert.equal(d.calls.length,2);
  assert.ok(d.calls[1].path.endsWith('/act'));
  assert.equal(d.calls[1].body.candidate_id,chosen.candidate_id);
  assert.equal(d.calls[1].body.composition.source_definition_id,fixture.secondary);
  assert.deepEqual(JSON.parse(JSON.stringify(d.calls[1].body.composition)),d.calls[0].body);
  assert.equal(d.painted.length,1);
  assert.deepEqual(d.notices,[]);
  console.log('DESKTOP_COMMIT '+JSON.stringify(d.calls[1].body));
});

test('unowned contracts and stale drafts cannot offer or submit missing activations', {skip: noFixture}, async () => {
  const missing = desktop({contract:false});
  missing.app.optionDraft = new OptionDraft(missing.app.menu,missing.app.matchId);
  missing.context.renderShapePanel();
  assert.equal(missing.panel().querySelector('[data-option-activation]'),null);
  const stale = desktop();
  stale.context.chooseLocalOption(fixture.medicinal);
  const aim = stale.panel().querySelector('[data-option-activation]');
  assert.ok(aim, 'Draft-enabled secondary activation must have a desktop aiming button');
  stale.app.menu.state_version++;
  await aim.click();
  assert.deepEqual(stale.calls,[]);
});

test('an illegal draft previews once and never falls back to the dormant parent', {skip: noFixture}, async () => {
  const d = desktop({preview:{menu:{actions:[]}}});
  d.context.chooseLocalOption(fixture.medicinal);
  const aim = d.panel().querySelector('[data-option-activation]');
  assert.ok(aim, 'Draft-enabled secondary activation must have a desktop aiming button');
  await aim.click();
  await setImmediate();
  assert.equal(d.calls.length,1);
  assert.ok(d.calls[0].path.endsWith('/composition/preview'));
  assert.equal(d.app.targeting,undefined);
  assert.match(d.notices[0],/cannot be used with these choices/);
});
