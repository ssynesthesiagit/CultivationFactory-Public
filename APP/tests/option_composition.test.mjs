import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {OptionDraft} from '../static/tabletop/option-composition.js';

const manifest = {
  poison: {key: ['blossom','seed'], mode: 'select', source: 'poison', family: 'flower'},
  piercing: {key: ['blossom','seed'], mode: 'select', source: 'piercing', family: 'flower'},
  seed: {key: ['blossom','bloom'], mode: 'select', source: 'seed', family: 'flower'},
  garden: {key: ['blossom','garden'], mode: 'select', source: 'garden', family: 'flower'},
  toggle: {key: ['augment','flower','large'], mode: 'toggle', source: 'large', family: 'flower'},
  clear: {key: ['augment','flower',null], mode: 'clear', source: 'clear', family: 'flower'},
};
const menu = {actor_id:'me', state_version:2, decision_id:'decision:2', composition:manifest};
test('independent choices compose, alternatives replace, toggles cancel and clear is ordered', () => {
  const d = new OptionDraft(menu, 'match');
  for (const key of ['poison','seed','garden']) assert.equal(d.choose(key), true);
  assert.deepEqual(d.request('flower','request').sources, ['poison','seed','garden']);
  d.choose('piercing');
  assert.deepEqual(d.request('flower','request').sources, ['piercing','seed','garden']);
  d.choose('toggle'); d.choose('toggle');
  assert.equal(d.request('flower','request').sources.length, 3);
  d.choose('toggle'); d.choose('clear'); d.choose('toggle');
  assert.deepEqual(d.request('flower','request').sources.slice(-2), ['clear','large']);
  assert.equal(d.choose('invented'), false);
  assert.equal(d.matches({...menu, state_version:3}, 'match'), false);
});
test('real desktop option click handler makes zero requests and no full render/refresh', () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function chooseLocalOption(');
  const end = source.indexOf('\nfunction useOptionCandidate', start);
  const calls = [];
  const app = {menu, matchId:'match'};
  const context = {app, OptionDraft, refuseCoveredView:()=>false, cancelTargeting(){},
    renderShapePanel(){}, renderDraftSummary(){}, renderActionBar(){throw Error('full menu rebuild');}, api(...args){calls.push(args);},
    refresh(){throw Error('full refresh');}, render(){throw Error('full state');}};
  vm.runInNewContext(source.slice(start,end), context);
  const timings = [];
  for (const key of ['poison','seed','garden']) {
    const t = performance.now();
    assert.equal(context.chooseLocalOption(key), true);
    timings.push(performance.now()-t);
  }
  assert.deepEqual(calls, []);
  assert.deepEqual(app.optionDraft.request('flower','request').sources, ['poison','seed','garden']);
  console.log('local click ms:', timings.map(x=>x.toFixed(3)).join(', '));
});

test('native commits rebind all draft settings by source and reject ownership or missing-setting changes', () => {
  const d=new OptionDraft({...menu,manual:true},'match');
  d.choose('poison'); d.choose('seed');
  const next={...menu,manual:true,state_version:3,decision_id:'decision:3',
    composition:{newPoison:manifest.poison,newSeed:manifest.seed}};
  const rebound=d.rebase(next,'match');
  assert.ok(rebound.matches(next,'match'));
  assert.deepEqual(rebound.request('flower','next').sources,['poison','seed']);
  assert.equal(rebound.request('flower','next').state_version,3);
  assert.equal(d.version,2,'Rebinding does not change the old decision');
  assert.equal(d.rebase({...next,composition:{newPoison:manifest.poison}},'match'),null);
  assert.equal(d.rebase({...next,actor_id:'someone else'},'match'),null);
  assert.equal(d.rebase({...next,manual:false},'match'),null);
  assert.equal(d.rebase(next,'another match'),null);
});

test('a real activation inside Options aims the local draft instead of bypassing it', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const group = {source_definition_id:'flower',options:[{candidate_id:'bloom-now'}]};
  const calls=[];
  const context={app:{menu:{actions:[group]},optionDraft:{dirty:true}},
    chooseLocalOption:()=>false, aimComposedAction:async row=>{calls.push(row);return true;},
    act(){throw Error('Draft was bypassed');},toast(){}};
  const start=source.indexOf('async function useGroup('), end=source.indexOf('\nfunction chooseFromList',start);
  vm.runInNewContext(source.slice(start,end),context);
  const helper=source.indexOf('function useOptionCandidate(');
  vm.runInNewContext(source.slice(helper,source.indexOf('\nfunction renderDraftSummary',helper)),context);
  assert.equal(await context.useOptionCandidate('bloom-now'),true);
  assert.deepEqual(calls,[group]);
});

test('changing an effect exposes its complete server-defined amount choices locally', () => {
  const d = new OptionDraft({...menu, composition:{
    effectA:{key:['rider','effect'],mode:'select',source:'a'},
    effectB:{key:['rider','effect'],mode:'select',source:'b'},
  }}, 'match');
  const amounts = [{value:'ask'}, {value:'1'}, {value:'3'}];
  const entries = [{base:'attack', modifiers:[{selectors:[
    {field:'option',current:'a',options:[{value:'a',candidate_id:'effectA'}, {value:'b',candidate_id:'effectB'}]},
    {field:'payment',current:'1',options:amounts.slice(0,2),all_options:amounts,
      allowed_by_effect:{a:['ask','1'],b:['ask','3']}},
  ]}]}];
  d.choose('effectB');
  const projected = d.project(entries)[0].modifiers[0].selectors[1];
  assert.deepEqual(projected.options.map(o=>o.value), ['ask','3']);
  assert.equal(projected.current, 'ask');
  assert.equal(entries[0].modifiers[0].selectors[1].current, '1');
});
