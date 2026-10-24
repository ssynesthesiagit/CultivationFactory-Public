// Production chooser regressions: no browser, live data, network or model server.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {Element} from './objects_dom_stub.mjs';
import {OptionDraft} from '../static/tabletop/option-composition.js';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function declaration(name) {
  let start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  if (source.slice(start - 6, start) === 'async ') start -= 6;
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function harness(reply = async () => ({actions: []})) {
  const menu = {actor_id: 'xiahou', decision_id: 'decision', state_version: 130, actions: []};
  const app = {menu, state: {menu, presentation: {current_actor_id: 'xiahou'}}, matchId: 'copy',
    targeting: null, pendingChoice: null};
  const hintNode = new Element('div'), messages = [], calls = [], broadcasts = [], requests = [];
  // This DOM method is used by the real hint-bar list, not by our production logic.
  hintNode.insertBefore = (node, before) => {
    if (!before) return hintNode.appendChild(node);
    node.parentNode = hintNode; hintNode.children.splice(hintNode.children.indexOf(before), 0, node);
  };
  const context = {app, OptionDraft, URLSearchParams, refreshSequence: 0, crypto: {randomUUID: () => 'request'},
    enc: encodeURIComponent, currentViewer: () => ({ready: true}),
    api: async (url, options) => {requests.push({url, options}); return reply(url, options);},
    act: async id => {calls.push(id); return true;},
    toast: text => messages.push(text), renderHighlights() {}, renderShapePanel() {}, renderDraftSummary() {},
    broadcastActors: () => broadcasts.push(app.pendingChoice),
    hint: text => {context.hintText = text; if (!text) hintNode.replaceChildren();},
    $: () => hintNode, document: {createElement: tag => new Element(tag), body: new Element('body')}};
  for (const name of ['refuseCoveredView', 'closeChoice', 'cancelTargeting', 'invalidateTargeting',
    'actOnce', 'chooseLocalOption', 'useGroup', 'chooseFromList', 'aimComposedAction']) {
    vm.runInNewContext(declaration(name), context);
  }
  return {app, context, hintNode, calls, messages, broadcasts, requests};
}
const option = (id = 'self-use') => ({candidate_id: id, target_ids: ['xiahou'], option_ids: [], label: id});
const header = label => ({source_definition_id: 'ability', label, lazy: true, options: []});

for (const label of ['Ruin Channel', 'Black-Claw Manifestation (1 Stamina) + Daemonic Augment: Bonus Damage']) {
  for (const shape of ['lazy', 'unflagged', 'missing']) {
    test(`${label}: ${shape} header expands before self activation`, async () => {
      const h = harness(async () => ({actions: [{source_definition_id: 'ability', options: [option()]}]}));
      const group = header(label);
      if (shape !== 'lazy') delete group.lazy;
      if (shape === 'missing') delete group.options;
      h.app.menu.actions = [group];
      assert.equal(await h.context.useGroup(group), true);
      assert.equal(h.requests.length, 1);
      assert.match(h.requests[0].url, /action-options\?/);
      assert.deepEqual(h.calls, ['self-use']);
      assert.equal(h.app.targeting, null);
      assert.equal(h.app.pendingChoice, null);
      assert.equal(group.lazy, false);
    });
  }
}

test('multiple self modes stay in the list and every mode is reachable', async () => {
  const h = harness();
  const options = [option('claws'), option('fangs')];
  const pending = h.context.useGroup({label: 'Manifestation', options});
  assert.equal(h.app.targeting, null);
  assert.equal(h.app.pendingChoice.kind, 'list');
  assert.equal(h.hintNode.querySelectorAll('button').length, 3);
  await h.hintNode.querySelectorAll('button')[1].click();
  assert.equal(await pending, true);
  assert.deepEqual(h.calls, ['fangs']);
  assert.equal(h.app.pendingChoice, null);
});

test('a covered lazy press neither expands nor cancels the outstanding choice', async () => {
  const h = harness();
  const pending = h.app.pendingChoice = {kind: 'list', label: 'Existing choice'};
  h.context.currentViewer = () => ({ready: false});
  assert.equal(await h.context.useGroup(header('Ruin Channel')), false);
  assert.equal(h.app.pendingChoice, pending);
  assert.equal(h.requests.length, 0);
});

test('empty unknown group settles, clears an old prompt and permits the next action', async () => {
  const h = harness();
  const old = h.context.useGroup({label: 'Attack', options: [
    {...option('a'), target_ids: ['foe-a']}, {...option('b'), target_ids: ['foe-b']}]});
  assert.ok(h.app.targeting);
  const empty = h.context.useGroup({label: 'No choices', options: []});
  assert.equal(h.app.targeting, null, 'no empty map can open');
  assert.equal(await empty, false);
  assert.equal(await old, false);
  assert.equal(h.app.pendingChoice, null);
  assert.match(h.messages.at(-1), /No legal options.*another action/);
  assert.equal(await h.context.useGroup({options: [option('next')]}), true);
  assert.deepEqual(h.calls, ['next']);
});

for (const reply of [{actions: []}, {actions: [{source_definition_id: 'ability', options: []}]}]) {
  test('empty expansion closes the previous target prompt without spending anything', async () => {
    const h = harness(async () => reply);
    const old = h.context.useGroup({label: 'Attack', options: [
      {...option('a'), target_ids: ['a']}, {...option('b'), target_ids: ['b']}]});
    assert.equal(await h.context.useGroup(header('Ruin Channel')), false);
    assert.equal(await old, false);
    assert.equal(h.app.targeting, null);
    assert.equal(h.app.pendingChoice, null);
    assert.deepEqual(h.calls, []);
    assert.match(h.messages.at(-1), /No legal options/);
  });
}

test('drafted self activation uses preview candidates, never re-expands the lazy base', async () => {
  const h = harness(async url => {
    assert.match(url, /composition\/preview$/, 'no native expansion may replace the draft');
    return {menu: {actions: [{source_definition_id: 'drafted', options: [option('drafted-self')]}]}};
  });
  h.app.optionDraft = new OptionDraft({...h.app.menu, composition: {
    augment: {key: ['augment', 'ability', 'damage'], mode: 'toggle', source: 'augment', family: 'ability'},
  }}, h.app.matchId);
  h.app.optionDraft.choose('augment');
  assert.equal(await h.context.useGroup(header('Black-Claw + Bonus Damage')), true);
  assert.equal(h.requests.length, 1);
  assert.deepEqual(h.requests[0].options.body.sources, ['augment']);
  assert.deepEqual(h.calls, ['drafted-self']);
  assert.equal(h.app.composedAction.menu.actions[0].options[0].candidate_id, 'drafted-self');
  assert.equal(h.app.targeting, null);
});

test('empty composition cannot leave a blank map prompt', async () => {
  const h = harness(async () => ({menu: {actions: [{options: []}]}}));
  h.app.optionDraft = {dirty: true, revision: 1, request: () => ({}), matches: () => true};
  assert.equal(await h.context.useGroup(header('Black-Claw')), false);
  assert.equal(h.app.targeting, null);
  assert.deepEqual(h.calls, []);
  assert.match(h.messages.at(-1), /No legal options/);
});

test('a poll retires a legacy empty picker and broadcasts its removal', () => {
  const h = harness(), settled = [];
  h.app.targeting = {group: {label: 'Black-Claw', options: []}, byTarget: new Map(),
    actorId: 'xiahou', decisionId: 'decision', stateVersion: 130,
    areas: [], destinations: [], resolve: result => settled.push(result)};
  h.app.pendingChoice = {kind: 'target', label: 'Black-Claw', prompt: ' for Black-Claw'};
  h.context.invalidateTargeting();
  assert.equal(h.app.targeting, null);
  assert.equal(h.app.pendingChoice, null);
  assert.deepEqual(settled, [false]);
  assert.equal(h.broadcasts.at(-1), null);
  assert.match(h.messages.at(-1), /no legal targets or options.*again/);
});

test('a poll clears orphaned local notices, but never a live list or a saved server question', () => {
  for (const kind of ['target', 'placement', 'list']) {
    const h = harness();
    h.app.pendingChoice = {kind};
    h.context.invalidateTargeting();
    assert.equal(h.app.pendingChoice, null);
  }
  for (const owner of ['listPick', 'mapPick', 'saved']) {
    const h = harness();
    const pending = h.app.pendingChoice = {kind: 'list'};
    if (owner === 'saved') h.app.state.pending_action = {method: 'act'};
    else h.app[owner] = {};
    h.context.invalidateTargeting();
    assert.equal(h.app.pendingChoice, pending);
    assert.deepEqual(h.messages, []);
  }
});

test('table entry point cannot reuse the pre-lazy cached client URL', () => {
  const html = readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  assert.match(html, /tabletop\.js\?v=bonusfix1-optdraft1/);
  assert.doesNotMatch(html, /tabletop\.js\?v=charlist1/);
});

test('a served build that differs from the page build reloads once, with a plain banner', async () => {
  const {checkBuild} = await import('../static/tabletop/build-check.js?case=stale');
  const reloads = [], stored = new Map();
  const storage = {getItem: k => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, v)};
  const banner = {textContent: '', setAttribute() {}, style: {}};
  globalThis.document = {body: {append() {}}, getElementById: () => banner, createElement: () => banner};
  try {
    assert.equal(checkBuild('new123', 'old000', {reload: () => reloads.push('reload'), storage}), true);
    assert.equal(banner.textContent, 'The game was updated — reloading…');
    await new Promise(resolve => setTimeout(resolve, 700));
    assert.deepEqual(reloads, ['reload']);
  } finally { delete globalThis.document; }
});

test('a matching or missing build never reloads the table', async () => {
  const {checkBuild} = await import('../static/tabletop/build-check.js?case=same');
  const reloads = [];
  assert.equal(checkBuild('abc', 'abc', {reload: () => reloads.push(1), storage: null}), false);
  assert.equal(checkBuild(null, 'abc', {reload: () => reloads.push(1), storage: null}), false);
  assert.equal(checkBuild('abc', '', {reload: () => reloads.push(1), storage: null}), false);
  assert.deepEqual(reloads, []);
});

test('every table request feeds the served build to the client check', () => {
  const api = readFileSync(new URL('../static/tabletop/api.js', import.meta.url), 'utf8');
  assert.match(api, /import \{checkBuild\} from '\.\/build-check\.js'/);
  assert.match(api, /checkBuild\(response\.headers\.get\("X-Factory-Build"\)\)/);
});

