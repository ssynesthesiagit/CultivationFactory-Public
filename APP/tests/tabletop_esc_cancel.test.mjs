import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function piece(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};
// The page's choice dialog, reduced to the parts showChoiceDialog() drives: its answer buttons and its Esc event.
function dialogStub() {
  const listeners = {}, buttons = ['USE', 'DECLINE'].map(answer => ({dataset: {answer}, hidden: false, onclick: null}));
  return {buttons, listeners, close() {}, addEventListener(event, fn) { listeners[event] = fn; },
    removeEventListener(event) { delete listeners[event]; }, querySelectorAll: selector => (selector === '[data-answer]' ? buttons : [])};
}
function harness() {
  const nodes = new Map(), listeners = {}, sent = [], rendered = [], reads = [], dialog = dialogStub();
  const classes = new Set();
  function node() {
    return {hidden: true, firstChild: {}, lastChild: {addEventListener(event, fn) { this[event] = fn; }},
      replaceChildren() {}, addEventListener(event, fn) { this[event] = fn; }};
  }
  const app = {matchId: 'm', fog: 'own', lastSequence: 0, state: {menu: {decision_id: 'd', state_version: 1}},
    menu: {decision_id: 'd'}, busy: false};
  const context = {app, sent, rendered, reads, console,
    $: id => { if (id === '#ttReaction') return dialog; if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
    decisionText: () => '', spaceGrid: () => '', resumeViewerDialogs() {}, appendReactionAnswer() {},
    document: {addEventListener(event, fn) { listeners[event] = fn; },
      body: {classList: {add: name => classes.add(name), remove: name => classes.delete(name)}}},
    escapeHtml: String, enc: encodeURIComponent, broadcastActors() {}, renderHighlights() {},
    renderShapePanel() {}, renderActionBar() {}, currentViewer: () => ({ready: true}),
    synchronizePresets: async () => {}, toast: message => { throw Error(message); },
    api: async path => { sent.push(path); return {events: []}; },
    loadSeats: async () => {}, readTableState: async () => { const read = deferred(); reads.push(read); return read.promise; },
    eventsThroughState: async events => events, playEvents: async () => {},
    render: state => { app.state = state; rendered.push(state); },
    renderObservedState: state => rendered.push(state), handleUnavailableFight: async () => false,
    gmNotice() {}, invalidateTargeting() {}, scheduleSeatPoll() {},
    resumePendingAction: pending => { sent.push(['resume', pending]); },
  };
  runInNewContext(`let refreshSequence = 0; let deferredMenuRead = null;
    ${['hint', 'closeChoice', 'cancelTargeting', 'refuseCoveredView', 'abilityChoiceActive', 'abilityReserved', 'cancelAbilityChoice',
      'showChoiceDialog', 'requestDeferredMenu', 'refresh', 'resumeServerPrompt', 'withReactions', 'act'].map(piece).join('\n')}
    ${source.slice(source.indexOf('$("#ttViewport").addEventListener("contextmenu"'),
      source.indexOf('// Keep a watching table in step'))}`, context);
  return {context, app, nodes, listeners, sent, rendered, reads, dialog, classes,
    escape() { listeners.keydown({key: 'Escape', target: {closest: () => 'select'}, preventDefault() {}}); }};
}
async function tick() { for (let i = 0; i < 12; i++) await Promise.resolve(); }

for (const method of ['Escape', 'right-click', 'Cancel button']) {
  test(`${method} cancels deferred loading; late state cannot resume a picker`, async () => {
    const h = harness();
    h.app.state.menu_pending = {state_version: 1};
    const pending = h.context.requestDeferredMenu();
    await tick();
    const hint = h.nodes.get('#ttHint');
    assert.equal(hint.hidden, false);
    assert.match(hint.firstChild.textContent, /Loading/);
    if (method === 'Escape') h.escape();
    if (method === 'right-click') h.nodes.get('#ttViewport').contextmenu({preventDefault() {}});
    if (method === 'Cancel button') hint.lastChild.click();
    assert.equal(hint.hidden, true);
    h.reads[0].resolve({pending_action: {reaction: {}, request: {}}, last_sequence: 0});
    await pending;
    assert.equal(h.rendered.length, 0);
    assert.equal(h.sent.some(row => Array.isArray(row)), false);
    assert.ok(h.sent.every(path => typeof path === 'string' && path.includes('/events?')));
  });
}

test('cancel during ability preparation prevents intent submission', async () => {
  const h = harness(), preparation = deferred();
  h.context.synchronizePresets = () => preparation.promise;
  const pending = h.context.act('breath');
  h.escape();
  preparation.resolve();
  assert.equal(await pending, false);
  assert.equal(h.sent.length, 0);
  assert.equal(h.app.abilityChoice, null);
});

test('preview gathers choices before a single final act submission', async () => {
  const h = harness();
  h.context.askReaction = async () => ({selection: 'USE', option_ids: ['cone']});
  let previews = 0;
  h.context.appendReactionAnswer = (answers, prompt, answer) => answers.push({...prompt.context, ...answer});
  h.context.api = async (path, options) => {
    h.sent.push({path, answers: [...options.body.reactions]});
    if (path.endsWith('/prepare')) return ++previews === 1
      ? {status: 'REACTION_REQUIRED', reaction: {context: {choice: 'area'}}, events: {}}
      : {status: 'PREPARED'};
    return {status: 'COMMITTED', events: {}, state: {menu: null}};
  };
  assert.equal(await h.context.act('breath'), true);
  assert.deepEqual(h.sent.map(row => row.path.split('/').at(-1)), ['prepare', 'prepare', 'act']);
  assert.equal(h.sent[2].answers[0].option_ids[0], 'cone');
});

test('late area response after cancel opens no dialog and submits no answer', async () => {
  const h = harness(), response = deferred();
  h.context.api = async path => { h.sent.push(path); return response.promise; };
  h.context.askReaction = () => { throw Error('cancelled response reopened a picker'); };
  const pending = h.context.act('breath');
  await tick();
  assert.equal(h.sent.length, 1);
  h.escape();
  response.resolve({status: 'REACTION_REQUIRED', reaction: {context: {choice: 'area'}}});
  assert.equal(await pending, false);
  assert.equal(h.sent.length, 1);
  h.app.viewerDeferredPrompt = true;
  h.context.resumeServerPrompt({menu: h.app.menu, pending_action: null});
  assert.equal(h.sent.length, 1, 'poll cannot reopen a cancelled preview');
});

for (const method of ['Escape', 'right-click', 'Cancel button']) {
  test(`${method} releases an unresolved preparation before its response and preserves the next action`, async () => {
    const h = harness(), oldResponse = deferred(), nextResponse = deferred();
    h.context.api = async (path, options) => {
      h.sent.push(path);
      if (path.endsWith('/prepare')) {
        return options.body.candidate_id === 'breath' ? oldResponse.promise : nextResponse.promise;
      }
      return {status: 'COMMITTED', events: {}, state: {menu: null}};
    };
    h.context.askReaction = () => { throw Error('abandoned preparation reopened a picker'); };
    let settled = false;
    const oldAction = h.context.act('breath').then(result => { settled = true; return result; });
    await tick();
    assert.equal(h.app.busy, true);
    if (method === 'Escape') h.escape();
    if (method === 'right-click') h.nodes.get('#ttViewport').contextmenu({preventDefault() {}});
    if (method === 'Cancel button') h.nodes.get('#ttHint').lastChild.click();
    assert.equal(h.app.busy, false, 'Cancel releases the turn without waiting for the server');
    const nextAction = h.context.act('other');
    await tick();
    assert.equal(settled, true, 'the abandoned act promise settles before its transport');
    assert.equal(await oldAction, false);
    assert.equal(h.sent.filter(path => path.endsWith('/prepare')).length, 2, 'another legal action starts immediately');
    const nextChoice = h.app.abilityChoice;
    assert.equal(h.app.busy, true);
    assert.equal(h.classes.has('is-working'), true);
    oldResponse.resolve({status: 'REACTION_REQUIRED', reaction: {context: {choice: 'area'}}});
    await tick();
    assert.equal(h.app.abilityChoice, nextChoice, 'late cleanup cannot retire the newer choice');
    assert.equal(h.app.busy, true, 'late cleanup cannot release the newer request');
    assert.equal(h.classes.has('is-working'), true);
    assert.match(h.nodes.get('#ttHint').firstChild.textContent, /Loading/);
    nextResponse.resolve({status: 'PREPARED'});
    assert.equal(await nextAction, true);
    assert.equal(h.app.busy, false);
    assert.equal(h.classes.has('is-working'), false);
    assert.equal(h.sent.filter(path => path.endsWith('/act')).length, 1, 'only the replacement submits');
  });
}

test('cancelling a required choice sends neither USE nor DECLINE', async () => {
  const h = harness();
  h.context.askReaction = async () => ({cancelled: true});
  let sends = 0;
  const result = await h.context.withReactions(async () => {
    sends++;
    return {status: 'REACTION_REQUIRED', events: {}, reaction: {}};
  });
  assert.equal(result.status, 'CANCELLED');
  assert.equal(sends, 1);
});

test('fresh page and deferred plain menu do not select an ability', () => {
  const h = harness();
  h.app.viewerDeferredPrompt = true;
  h.context.resumeServerPrompt({menu: {actions: [{label: 'Breath'}]}});
  h.context.resumeServerPrompt({menu_pending: {state_version: 16}});
  assert.equal(h.sent.length, 0);
  assert.equal(h.app.targeting, undefined);
  const real = {request: {}, reaction: {context: {choice: 'area'}}};
  h.context.resumeServerPrompt({pending_action: real});
  assert.equal(h.sent[0][0], 'resume', 'a real server pending choice is still resumed');
});

const optionalRider = {title: 'Lodged Axe Pull', choice: {minimum: 0, maximum: 1, allow_decline: true,
  options: [{id: 'pull', label: 'Pull yourself 10 feet'}]}};
const requiredChoice = {title: 'Empty Step', choice: {minimum: 1, maximum: 1, allow_decline: false,
  options: [{id: 'cell:4,6', label: 'Teleport'}]}};

test('an optional rider keeps its Pass answer, so the attack can go on without it', async () => {
  const h = harness();
  h.app.abilityChoice = {cancelled: false};
  const pending = h.context.showChoiceDialog(optionalRider);
  const pass = h.dialog.buttons.find(button => button.dataset.answer === 'DECLINE');
  assert.equal(pass.hidden, false, 'an optional rider offers Pass');
  pass.onclick();
  assert.equal(await pending, 'DECLINE', 'Pass is an explicit answer, not a cancellation');
  assert.equal(h.app.abilityChoice.cancelled, false, 'passing keeps the ability going');
});

test('Esc on an optional rider abandons the ability, and a required choice has no Pass', async () => {
  const h = harness();
  h.app.abilityChoice = {cancelled: false};
  const pending = h.context.showChoiceDialog(optionalRider);
  h.dialog.listeners.cancel({preventDefault() {}});
  assert.equal((await pending).cancelled, true, 'Esc cancels preparation and sends no DECLINE');
  h.app.abilityChoice = {cancelled: false};
  const required = h.context.showChoiceDialog(requiredChoice);
  assert.equal(h.dialog.buttons.find(button => button.dataset.answer === 'DECLINE').hidden, true);
  h.dialog.listeners.cancel({preventDefault() {}});
  assert.equal((await required).cancelled, true);
});

test('Esc on a saved prompt never hides it from the next poll', async () => {
  const h = harness(), prompt = {request: {candidate_id: 'breath'}, reaction: {context: {choice: 'area'}}};
  h.context.resumePendingAction = async pending => { h.sent.push(['resume', pending]); };
  h.app.viewerDeferredPrompt = true;
  h.app.state = {pending_action: prompt};
  h.context.resumeServerPrompt({pending_action: prompt});
  await tick();
  assert.equal(h.sent.filter(row => Array.isArray(row)).length, 1);
  h.app.waitingReaction = {prompt: prompt.reaction, matchId: 'm', reserved: true};
  h.escape();
  h.app.viewerDeferredPrompt = true;
  h.context.resumeServerPrompt({pending_action: prompt});
  await tick();
  assert.equal(h.sent.filter(row => Array.isArray(row)).length, 2, 'the saved decision is offered again');
});

test('Cancel is withdrawn once the action is sent, and the answer to it is applied', async () => {
  const h = harness(), response = deferred();
  h.context.api = async path => {
    h.sent.push(path);
    if (path.endsWith('/prepare')) return {status: 'PREPARED'};
    return response.promise;
  };
  const pending = h.context.act('breath');
  await tick();
  assert.match(h.nodes.get('#ttHint').firstChild.textContent, /Applying/, 'the prompt no longer offers to cancel');
  h.escape();
  response.resolve({status: 'COMMITTED', events: {}, state: {menu: null}});
  assert.equal(await pending, true, 'a sent action is not discarded by Esc');
});

test('a choice answered after the action is sent is shown, not dropped by Esc', async () => {
  const h = harness(), first = deferred(), asked = [];
  h.context.askReaction = async prompt => { asked.push(prompt); return {selection: 'USE', option_ids: ['cone']}; };
  let acts = 0;
  h.context.api = async path => {
    h.sent.push(path);
    if (path.endsWith('/prepare')) return {status: 'PREPARED'};
    return ++acts === 1 ? first.promise : {status: 'COMMITTED', events: {}, state: {menu: null}};
  };
  const pending = h.context.act('breath');
  await tick();
  h.escape();
  first.resolve({status: 'REACTION_REQUIRED', reaction: {context: {choice: 'late'}}, events: {}});
  assert.equal(await pending, true);
  assert.equal(asked.length, 1, 'the late pending choice is answered, not hidden');
  assert.deepEqual(h.sent.map(path => path.split('/').at(-1)), ['prepare', 'act', 'act'], 'a sent action is never previewed again');
});
