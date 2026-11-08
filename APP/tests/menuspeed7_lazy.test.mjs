import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const start = source.indexOf('async function useGroup(');
const code = source.slice(start, source.indexOf('\n}', start) + 2);
function harness(api) {
  const app = {matchId:'fight', menu:{actor_id:'actor', decision_id:'decision', state_version:1}};
  const submissions = [], notices = [];
  const bindings = {app, api, URLSearchParams, enc:encodeURIComponent,
    toast: text => notices.push(text), refuseCoveredView: () => false,
    actOnce: id => {submissions.push(id); return true;}};
  const use = Function(...Object.keys(bindings), `${code}; return useGroup;`)(...Object.values(bindings));
  return {app, use, submissions, notices};
}
const group = () => ({source_definition_id:'ability', label:'Ability', lazy:true, options:[]});
const response = () => ({actions:[{source_definition_id:'ability', options:[{candidate_id:'native',target_ids:[]}]}]});

test('opening a lazy group requests only its source then uses the native option', async () => {
  const requests = [];
  const h = harness(async url => {requests.push(url); return response();});
  const g = group();
  assert.equal(await h.use(g), true);
  assert.equal(requests.length,1);
  const url = new URL(requests[0], 'http://example.test');
  assert.equal(url.pathname, '/api/tabletop/matches/fight/action-options');
  assert.equal(url.searchParams.get('state_version'),'1');
  assert.equal(url.searchParams.get('source'),'ability');
  assert.deepEqual(h.submissions,['native']);
  await h.use(g);
  assert.equal(requests.length,1);
});

test('stale expansion cannot submit or replace a newer choice', async () => {
  let release;
  const h = harness(() => new Promise(resolve => {release = resolve;}));
  const g = group(), pending = h.use(g);
  h.app.menu = {...h.app.menu, state_version:2};
  release(response());
  assert.equal(await pending,false);
  assert.deepEqual(h.submissions,[]);
  assert.equal(g.lazy,true);
});

test('opening another action retires the first in-flight expansion', async () => {
  let release;
  const h = harness(() => new Promise(resolve => {release = resolve;}));
  const pending = h.use(group());
  await h.use({options:[{candidate_id:'other'}]});
  release(response());
  assert.equal(await pending,false);
  assert.deepEqual(h.submissions,['other']);
});

test('an empty exact expansion explains that no option is legal', async () => {
  const h = harness(async () => ({actions:[], message:'No eligible targets.'}));
  assert.equal(await h.use(group()),false);
  assert.deepEqual(h.submissions,[]);
  assert.ok(h.notices.includes('No eligible targets.'));
});
