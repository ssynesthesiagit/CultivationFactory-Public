import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {decisionChanged} from '../static/tabletop/pending-decision.js';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const markup = readFileSync(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
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
  const options = [{dataset: {option: 'cone'}, onclick: null}];
  const cancelButton = {hidden: true, onclick: null};
  return {buttons, options, cancelButton, listeners, close() {}, addEventListener(event, fn) { listeners[event] = fn; },
    removeEventListener(event) { delete listeners[event]; },
    querySelector: selector => selector === '[data-cancel-ability]' ? cancelButton : null,
    querySelectorAll: selector => (selector === '[data-answer]' ? buttons : selector === '[data-option]' ? options : [])};
}
function harness() {
  const nodes = new Map(), listeners = {}, sent = [], rendered = [], reads = [], dialog = dialogStub();
  const classes = new Set();
  function node() {
    return {hidden: true, firstChild: {}, lastChild: {addEventListener(event, fn) { this[event] = fn; }},
      replaceChildren() {}, addEventListener(event, fn) { this[event] = fn; }};
  }
  const app = {matchId: 'm', fog: 'own', lastSequence: 0,
    state: {last_sequence: 0, pending_action: null, menu: {actor_id: 'hero', decision_id: 'd', state_version: 1},
      presentation: {current_actor_id: 'hero', actors: [{entity_id: 'hero', controller: 'MANUAL', active: true}]}}, seatStatus: {},
    menu: {actor_id: 'hero', decision_id: 'd', state_version: 1}, busy: false};
  const context = {app, sent, rendered, reads, console, decisionChanged,
    crypto: {randomUUID: () => 'draft-request'}, chooseLocalOption: () => false,
    $: id => { if (id === '#ttReaction') return dialog; if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
    decisionText: () => '', spaceGrid: () => '', resumeViewerDialogs() {},
    document: {addEventListener(event, fn) { listeners[event] = fn; },
      body: {classList: {add: (...names) => names.forEach(name => classes.add(name)),
        remove: (...names) => names.forEach(name => classes.delete(name))}}},
    escapeHtml: String, enc: encodeURIComponent, broadcastActors() {}, renderHighlights() {},
    renderShapePanel() {}, renderActionBar() {}, currentViewer: () => ({ready: true}),
    modelOwner: (status, actor) => status.modelActor === actor?.entity_id,
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
    ${source.match(/^const isManualActor = .*$/m)[0]}
    ${source.match(/^const automaticSlot = .*$/m)[0]}
    ${['hint', 'closeChoice', 'cancelTargeting', 'refuseCoveredView', 'abilityChoiceActive', 'abilityReserved', 'releaseMapPick', 'cancelAbilityChoice',
      'wireReactionDialog', 'showChoiceDialog', 'askChoice', 'askReactionInput', 'askReactionMenu', 'reactionMenuAnswers', 'reactionMenuRows', 'reactionMenuChoice', 'requestDeferredMenu', 'refresh', 'resumeServerPrompt', 'askReaction', 'pollTable',
      'reconcileRemoteDecision', 'appendReactionAnswer', 'withReactions', 'act', 'actOnce', 'useGroup', 'aimComposedAction', 'autoStep', 'modelTurnNow'].map(piece).join('\n')}
    ${source.slice(source.indexOf('$("#ttViewport").addEventListener("contextmenu"'),
      source.indexOf('// Keep a watching table in step'))}`, context);
  context.reactionMenuRows = prompt => prompt.alternatives.map((row, index) => ({
    key: String(index), label: row.reaction, modes: [{row, index}], useful: true, priority: 0,
  }));
  return {context, app, nodes, listeners, sent, rendered, reads, dialog, classes,
    escape() { listeners.keydown({key: 'Escape', target: {closest: () => 'select'}, preventDefault() {}}); }};
}
async function tick() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
async function until(check) {
  for (let i = 0; i < 200 && !check(); i++) await Promise.resolve();
  assert.ok(check(), 'the production choice reached its expected asynchronous checkpoint');
}

for (const method of ['Escape', 'right-click', 'Cancel button']) {
  test(`${method} cancels deferred loading; late state cannot resume a picker`, async () => {
    const h = harness();
    h.app.state.menu_pending = {state_version: 1};
    h.app.menu = null;
    let settled = false;
    const pending = h.context.requestDeferredMenu().then(() => { settled = true; });
    await tick();
    const hint = h.nodes.get('#ttHint');
    assert.equal(hint.hidden, false);
    assert.match(hint.firstChild.textContent, /Loading/);
    if (method === 'Escape') h.escape();
    if (method === 'right-click') h.nodes.get('#ttViewport').contextmenu({preventDefault() {}});
    if (method === 'Cancel button') hint.lastChild.click();
    assert.equal(hint.hidden, true);
    await tick();
    assert.equal(settled, true, 'Cancel settles its caller before the stalled response');
    await pending;
    // Production polling must be able to recover the menu without reloading.
    await h.context.pollTable();
    await tick();
    assert.equal(h.reads.length, 2, 'retry starts a fresh read before the old response');
    const ready = {menu: {decision_id: 'd', state_version: 1}, pending_action: null, last_sequence: 0};
    h.reads[1].resolve(ready);
    await tick();
    assert.equal(h.app.state, ready);
    assert.equal(h.rendered.length, 1);
    h.reads[0].resolve({pending_action: {reaction: {}, request: {}}, last_sequence: 0});
    await tick();
    assert.equal(h.app.state, ready, 'abandoned response cannot replace the fresh menu');
    assert.equal(h.rendered.length, 1);
    assert.equal(h.sent.some(row => Array.isArray(row)), false);
    assert.ok(h.sent.every(path => typeof path === 'string' && path.includes('/events?')));
  });
}

test('production poll keeps deferred AI, model and automatic turns free of the player loading hint', async () => {
  for (const mode of ['AI', 'model', 'automatic']) {
    const h = harness(), actor = h.app.state.presentation.actors[0];
    h.app.menu = null;
    h.app.state.menu_pending = {actor_id: 'hero', state_version: 1};
    if (mode === 'AI') actor.controller = 'LOCAL_AUTO';
    if (mode === 'model') h.app.seatStatus.modelActor = actor.entity_id;
    if (mode === 'automatic') actor.active = false;
    await h.context.pollTable();
    await until(() => h.reads.length === 1);
    assert.notEqual(h.nodes.get('#ttHint')?.hidden, false, mode + ': no player Cancel banner while AI loads');
    h.reads[0].resolve({pending_action: null, last_sequence: 0, menu: null});
    await tick();
    assert.notEqual(h.nodes.get('#ttHint')?.hidden, false, mode + ': no leftover banner after loading');
  }
});

test('production poll shows Cancel only during the delayed manual menu request, not idle polling', async () => {
  const h = harness(), ready = h.app.state;
  h.app.menu = null;
  h.app.state = {...ready, menu: null, menu_pending: {actor_id: 'hero', state_version: 1}};
  await h.context.pollTable();
  await until(() => h.reads.length === 1);
  const banner = h.nodes.get('#ttHint');
  assert.equal(banner.hidden, false, 'a manual player can cancel a pending menu read');
  assert.match(banner.firstChild.textContent, /Loading your turn choices/);
  assert.match(banner.innerHTML, /Cancel \(Esc\)/);
  assert.equal(typeof banner.lastChild.click, 'function');
  // Polls coalesce with the pending read; they must not start another request.
  await h.context.pollTable();
  assert.equal(h.reads.length, 1);
  h.reads[0].resolve(ready);
  await until(() => h.rendered.length === 1 && banner.hidden);
  h.app.menu = ready.menu;
  const polling = h.context.pollTable();
  await until(() => h.reads.length === 2);
  assert.equal(banner.hidden, true, 'an already-loaded player menu never shows Loading during idle polling');
  h.reads[1].resolve(ready);
  await polling;
  assert.equal(banner.hidden, true);
});

test('deferred-menu loading banner is delayed and limited to the viewer-controlled creature', () => {
  const start = source.indexOf('async function renderActionBar(');
  // The real function delimiter is a newline and a column-0 brace; the slice must be the whole body.
  const end = source.indexOf('\n}', start);
  assert.ok(end > start && end - start > 200, 'renderActionBar is extracted in full');
  const render = source.slice(start, end + 2);
  assert.match(render, /waitingForOwnMenu = !app\.menu && !!app\.state\?\.menu_pending/);
  assert.match(render, /isManualActor\(current\) && !automaticSlot\(current\)/);
  assert.match(render, /\}, 400\)/, 'fast menu reads do not flash a loading banner');
  assert.match(render, /presentation\(\)\?\.current_actor_id === actorId/,
    'the delayed banner cannot appear after the turn moves to an AI creature');
  assert.match(render, /bar\.replaceChildren\(\)/, 'the loading area stays quiet until the delay expires');
});

test('preparation choice dialog contains working Cancel and right-click controls', async () => {
  assert.match(markup, /<dialog id="ttReaction"[\s\S]*?<button type="button" class="tt-tool" data-cancel-ability hidden>Cancel ability<\/button>[\s\S]*?<\/dialog>/);
  for (const method of ['Cancel button', 'right-click']) {
    const h = harness();
    h.app.abilityChoice = {cancelled: false, stop() { this.stopped = true; }};
    let answer;
    const waiting = h.context.askReactionInput({title: 'Choose a breath area', reaction: 'Breath',
      choice: {minimum: 1, maximum: 1, allow_decline: false, options: [{id: 'cone', label: 'Cone'}]}})
      .then(value => { answer = value; });
    assert.equal(h.dialog.cancelButton.hidden, false, 'pre-submit modal exposes its own Cancel button');
    if (method === 'Cancel button') h.dialog.cancelButton.onclick();
    else {
      let prevented = false;
      h.dialog.listeners.contextmenu({preventDefault() { prevented = true; }});
      assert.equal(prevented, true, 'right-click on the modal reaches the cancellation handler');
    }
    await waiting;
    assert.equal(h.app.abilityChoice.cancelled, true);
    assert.equal(h.app.abilityChoice.stopped, true);
    assert.equal(answer.cancelled, true);
    assert.equal(h.dialog.cancelButton.hidden, true, 'closed choice hides its Cancel control');
  }
});

test('production plain reaction dispatch wires optional Escape-to-decline and cleans up', async () => {
  const h = harness();
  h.app.waitingReaction = {reserved: true, matchId: 'm'};
  const pending = h.context.askReactionInput({reaction: 'Opportunity Attack', context: {}});
  assert.equal(h.dialog.cancelButton.hidden, true, 'saved prompt cannot be cancelled as an unsent action');
  h.escape();
  assert.equal(await pending, 'DECLINE', 'Escape declines the optional saved reaction');
  assert.equal(h.app.declineReaction, null, 'settled prompt releases its decline callback');
  assert.equal(h.dialog.cancelButton.hidden, true);
});

test('production grouped reaction dispatch wires optional Escape-to-decline', async () => {
  const h = harness();
  const prompt = {alternatives: [{reaction: 'Parry', context: {reaction_source_id: 'parry', reactor_id: 'hero'}}]};
  h.app.waitingReaction = {reserved: true, matchId: 'm'};
  const pending = h.context.askReactionInput(prompt);
  h.escape();
  const answers = await pending;
  assert.equal(answers.length, 1);
  assert.equal(answers[0].reactor_id, 'hero');
  assert.equal(answers[0].reaction_source_id, 'parry');
  assert.equal(answers[0].selection, 'DECLINE');
  assert.equal(h.app.declineReaction, null);
});

test('production grouped reaction dispatch completes a selected reaction', async () => {
  const h = harness();
  const use = {dataset: {reactionUse: '0'}, onclick: null, disabled: false};
  const originalQuery = h.dialog.querySelectorAll;
  h.dialog.querySelectorAll = selector => selector === '[data-reaction-use]' ? [use] : originalQuery(selector);
  const prompt = {alternatives: [{reaction: 'Parry', context: {reaction_source_id: 'parry', reactor_id: 'hero'}}]};
  const pending = h.context.askReactionInput(prompt);
  assert.equal(typeof use.onclick, 'function');
  use.onclick();
  const answers = await pending;
  assert.equal(answers.length, 1);
  assert.equal(answers[0].reactor_id, 'hero');
  assert.equal(answers[0].reaction_source_id, 'parry');
  assert.equal(answers[0].selection, 'USE');
  assert.equal(h.app.finishReaction, null);
});

test('an abandoned deferred read cannot clear a newer read or its loading hint', async () => {
  const h = harness();
  h.app.state.menu_pending = {state_version: 1};
  h.app.menu = null;
  const abandoned = h.context.requestDeferredMenu();
  await tick();
  h.escape();
  const retry = h.context.requestDeferredMenu();
  await tick();
  assert.equal(h.reads.length, 2);
  h.reads[0].resolve({pending_action: {reaction: {}, request: {}}, last_sequence: 0});
  await abandoned;
  await tick();
  assert.equal(h.context.requestDeferredMenu(), retry, 'late cleanup cannot release the retry');
  const observing = h.context.refresh({observe: true});
  await tick();
  assert.equal(h.reads.length, 2, 'observe coalesces with the active retry');
  assert.equal(h.nodes.get('#ttHint').hidden, false, 'the retry still owns its loading hint');
  const ready = {menu: h.app.menu, pending_action: null, last_sequence: 0};
  h.reads[1].resolve(ready);
  await Promise.all([retry, observing]);
  assert.equal(h.rendered.length, 1);
  assert.equal(h.app.state, ready);
});

for (const read of ['pollTable', 'refresh']) {
  test(`unanswered preparation survives repeated ${read} reads, then commits exactly once`, async () => {
    const h = harness(), submitted = deferred(), original = h.app.state;
    const requests = [];
    h.context.api = async (path, options) => {
      requests.push({path, body: options?.body});
      if (path.endsWith('/prepare')) return options.body.reactions.length
        ? {status: 'PREPARED'}
        : {status: 'REACTION_REQUIRED', reaction: {title: 'Choose breath area', context: {choice: 'area'},
          choice: {minimum: 1, maximum: 1, allow_decline: false, options: [{id: 'cone', label: 'Cone'}]}}, events: {}};
      if (path.endsWith('/act')) return submitted.promise;
      return {events: []};
    };
    let settled = false;
    const pending = h.context.act('breath').then(result => { settled = true; return result; });
    await until(() => h.app.waitingReaction);
    const waiting = h.app.waitingReaction, finish = h.app.finishReaction;
    assert.ok(waiting, 'production askReaction owns a real preparation dialog');
    for (let i = 0; i < 2; i++) {
      const reading = h.context[read]();
      await tick();
      h.reads.at(-1).resolve({...original, menu: {...original.menu}});
      await reading;
      await tick();
      assert.equal(settled, false, 'a read cannot report a preview as committed');
      assert.equal(h.app.waitingReaction, waiting);
      assert.equal(h.app.finishReaction, finish, 'preserve the unanswered dialog');
      assert.equal(h.app.busy, true);
      assert.equal(requests.filter(row => row.path.endsWith('/act')).length, 0);
    }
    h.dialog.options[0].onclick();
    await tick();
    const commits = requests.filter(row => row.path.endsWith('/act'));
    assert.equal(commits.length, 1);
    assert.equal(commits[0].body.reactions[0].option_ids[0], 'cone');
    assert.equal(settled, false, 'only the actual submit response can finish the action');
    submitted.resolve({status: 'COMMITTED', events: {}, state: {menu: null}});
    assert.equal(await pending, true);
    assert.equal(h.app.busy, false);
  });
}

for (const read of ['pollTable', 'refresh']) {
  test(`composed preparation survives unchanged ${read} reads, commits once, and rejects a real change`, async () => {
    for (const changed of [false, true]) {
      const h = harness(), original = h.app.state, requests = [];
      const request = {...original.menu, sources: ['seed-setting'], source_definition_id: 'cultivate-blossom',
        request_id: 'draft-seed'};
      // Saving settings on the disposable projection advances its version and
      // decision. Neither advances on the live fight until the action is sent.
      const projected = {...original.menu, state_version: 2, decision_id: 'projected-d',
        actions: [{options: [{candidate_id: 'exploding-seed'}]}]};
      h.app.composedAction = {request, menu: projected};
      h.context.api = async (path, options) => {
        requests.push({path, body: options?.body});
        if (path.endsWith('/prepare')) return options.body.reactions.length
          ? {status: 'PREPARED'}
          : {status: 'REACTION_REQUIRED', reaction: {title: 'Footwork', context: {choice: 'footwork'},
            choice: {minimum: 1, maximum: 1, allow_decline: false,
              options: [{id: 'cone', label: 'Stay put'}]}}, events: {}};
        if (path.endsWith('/act')) return {status: 'COMMITTED', events: {}, state: {menu: null}};
        return {events: []};
      };
      let settled = false;
      const pending = h.context.act('exploding-seed').then(result => { settled = true; return result; });
      await until(() => h.app.waitingReaction);
      const waiting = h.app.waitingReaction, finish = h.app.finishReaction;
      for (let i = 0; i < 2; i++) {
        const reading = h.context[read]();
        await until(() => h.reads.length === i + 1);
        h.reads.at(-1).resolve({...original, menu: {...original.menu}});
        await reading;
        await tick();
        assert.equal(settled, false, 'an unchanged live version must not invalidate the projected choice');
        assert.equal(h.app.waitingReaction, waiting);
        assert.equal(h.app.finishReaction, finish, 'the same unanswered dialog stays open');
        assert.equal(requests.filter(row => row.path.endsWith('/act')).length, 0);
      }
      if (changed) {
        const reading = h.context[read]();
        await until(() => h.reads.length === 3);
        const changedState = {...original, menu: {...original.menu,
          state_version: 2, decision_id: 'another-live-action'}};
        h.reads.at(-1).resolve(changedState);
        await reading;
        // Abandoning a composed action refreshes the ordinary live menu too.
        await until(() => h.reads.length === 4);
        h.reads.at(-1).resolve(changedState);
        assert.equal(await pending, false, 'another action invalidates the unsubmitted draft');
        assert.equal(h.app.waitingReaction, null);
        assert.equal(requests.filter(row => row.path.endsWith('/act')).length, 0);
      } else {
        h.dialog.options[0].onclick();
        assert.equal(await pending, true);
        const commits = requests.filter(row => row.path.endsWith('/act'));
        assert.equal(commits.length, 1);
        assert.equal(commits[0].body.reactions[0].option_ids[0], 'cone');
        for (const {body} of requests.filter(row => /\/(prepare|act)$/.test(row.path))) {
          assert.equal(body.composition, request, 'the original live draft still authorizes composition');
          assert.equal(body.candidate_id, 'exploding-seed');
          assert.equal(body.decision_id, projected.decision_id, 'submission still uses the projected candidate');
          assert.equal(body.state_version, projected.state_version);
        }
      }
      assert.equal(h.app.busy, false);
    }
  });
}

test('preparation remains bound to the submitted preview request, not a newer local menu', async () => {
  const h = harness(), response = deferred();
  h.context.api = async path => path.endsWith('/prepare') ? response.promise : {events: []};
  const pending = h.context.act('breath');
  await tick();
  h.app.state = {...h.app.state, menu: {...h.app.state.menu, state_version: 2}};
  response.resolve({status: 'REACTION_REQUIRED', reaction: {context: {choice: 'area'},
    choice: {minimum: 1, maximum: 1, options: [{id: 'cone', label: 'Cone'}]}}, events: {}});
  await until(() => h.app.waitingReaction);
  const reading = h.context.pollTable();
  await tick();
  h.reads.at(-1).resolve(h.app.state);
  await reading;
  assert.equal(await pending, false, 'do not rebind an old preview to the newly read decision');
});

for (const change of ['version', 'decision', 'actor', 'terminal', 'saved prompt']) {
  test(`a remote ${change} change invalidates preparation without claiming a local commit`, async () => {
    const h = harness(), initial = h.app.state;
    h.context.api = async path => {
      h.sent.push(path);
      if (path.endsWith('/prepare')) return {status: 'REACTION_REQUIRED', reaction: {
        context: {choice: 'area'}, choice: {minimum: 1, maximum: 1, options: [{id: 'cone', label: 'Cone'}]}}, events: {}};
      assert.ok(path.includes('/events?'), 'an invalidated preview must never submit');
      return {events: []};
    };
    const pending = h.context.act('breath');
    await until(() => h.app.waitingReaction);
    const reading = h.context.pollTable();
    await tick();
    const state = {...initial, menu: {...initial.menu}};
    if (change === 'version') state.menu.state_version++;
    if (change === 'decision') state.menu.decision_id = 'new';
    if (change === 'actor') state.menu.actor_id = 'other';
    if (change === 'terminal') state.presentation = {terminal: true};
    if (change === 'saved prompt') state.pending_action = {reaction: {context: {choice: 'remote'}}, request: {}};
    h.reads.at(-1).resolve(state);
    await reading;
    assert.equal(await pending, false, 'remote supersession is not this unsubmitted action succeeding');
    assert.equal(h.sent.some(row => typeof row === 'string' && row.endsWith('/act')), false);
    assert.equal(h.app.state, state);
    assert.equal(h.app.waitingReaction, null);
    assert.equal(h.app.busy, false);
    if (change === 'saved prompt') assert.equal(h.sent.at(-1)[0], 'resume');
  });
}

test('a submitted choice follows the saved prompt instead of its old preparation menu', async () => {
  const h = harness(), prompt = {context: {choice: 'after-submit'},
    choice: {minimum: 1, maximum: 1, options: [{id: 'cone', label: 'Cone'}]}};
  let acts = 0;
  h.context.api = async path => {
    h.sent.push(path);
    if (path.endsWith('/prepare')) return {status: 'PREPARED'};
    if (path.endsWith('/act')) return ++acts === 1
      ? {status: 'REACTION_REQUIRED', reaction: prompt, events: {}}
      : {status: 'COMMITTED', events: {}, state: {menu: null}};
    return {events: []};
  };
  const pending = h.context.act('breath');
  await until(() => h.app.waitingReaction);
  const waiting = h.app.waitingReaction;
  assert.equal(waiting.reserved, true);
  const reading = h.context.pollTable();
  await tick();
  h.reads.at(-1).resolve({menu: null, last_sequence: 0, pending_action: {request: {}, reaction: prompt}});
  await reading;
  assert.equal(h.app.waitingReaction, waiting, 'a saved prompt can outlive the original turn menu');
  h.escape();
  assert.equal(h.app.abilityChoice.cancelled, false, 'Escape cannot abandon a sent required choice');
  assert.equal(h.app.waitingReaction, waiting, 'required saved prompt remains active');
  assert.equal(typeof h.app.finishReaction, 'function', 'required dialog remains open for its answer');
  h.dialog.options[0].onclick();
  assert.equal(await pending, true);
  assert.equal(acts, 2, 'answer the reserved action without another preparation');
});

// Start before the composition exists, through the real action-bar caller.
// Cover both the target picker and shortcuts that could submit a late preview.
for (const method of ['Escape', 'right-click', 'Cancel button']) {
  for (const mode of ['picker', 'single', 'preferred']) {
    test(`${method} cancels the initial ${mode} composition preview and drops its late continuation`, async () => {
      for (const panelOpen of [false, true]) {
        const h = harness(), preview = deferred(), replacement = deferred(), requests = [];
        const originalMenu = h.app.menu;
        h.app.showShape = panelOpen ? 'breath' : null;
        h.app.optionDraft = {dirty: true, revision: 1,
          matches: (menu, matchId) => menu === originalMenu && matchId === 'm',
          request: source => ({...originalMenu, source_definition_id: source, request_id: 'draft-request'})};
        const group = {source_definition_id: 'breath', label: 'Breath',
          options: [{candidate_id: 'plain-breath', target_ids: ['enemy']}]};
        const native = {source_definition_id: 'system:end-turn',
          options: [{candidate_id: 'end-turn', target_ids: []}]};
        originalMenu.actions = h.app.state.menu.actions = [group, native];
        const options = [{candidate_id: 'draft-breath', target_ids: ['enemy']},
          ...(mode === 'single' ? [] : [{candidate_id: 'draft-other', target_ids: ['other']}])];
        h.context.api = async (path, request) => {
          requests.push({path, body: request?.body});
          if (path.endsWith('/composition/preview')) return preview.promise;
          if (path.endsWith('/prepare')) return replacement.promise;
          return {status: 'COMMITTED', events: {}, state: {menu: null}};
        };
        let settled = false;
        const pending = h.context.useGroup(group, {preferTargets: mode === 'preferred' ? ['enemy'] : []})
          .then(result => { settled = true; return result; });
        await until(() => requests.length === 1);
        assert.equal(h.app.busy, true);
        assert.equal(h.classes.has('is-working'), true);
        assert.equal(h.classes.has('is-ability-choice'), true, 'loading Cancel remains clickable while working');
        assert.equal(h.context.abilityChoiceActive(), true, 'initial preview owns a cancellable choice even without a panel');
        const hint = h.nodes.get('#ttHint');
        assert.equal(hint.hidden, false, 'loading preview exposes Cancel');
        if (method === 'Escape') h.escape();
        if (method === 'right-click') h.nodes.get('#ttViewport').contextmenu({preventDefault() {}});
        if (method === 'Cancel button') hint.lastChild.click();
        assert.equal(h.app.busy, false, 'Cancel releases busy before the preview replies');
        await until(() => settled);
        assert.equal(await pending, false);
        assert.equal(hint.hidden, true);
        assert.equal(h.app.abilityChoice, null);
        assert.equal(h.app.showShape, null);
        // A native action remains usable even while the old preview is in flight.
        const nextAction = h.context.useGroup(native);
        await until(() => requests.some(row => row.path.endsWith('/prepare')));
        const nextChoice = h.app.abilityChoice;
        preview.resolve({menu: {...originalMenu, state_version: 2,
          actions: [{...group, options}]}});
        await tick();
        assert.equal(h.app.composedAction, undefined, 'late preview cannot install a composed action');
        assert.equal(h.app.targeting, null, 'late preview cannot reopen targeting');
        assert.equal(h.app.mapPick, undefined);
        assert.equal(h.app.listPick, undefined);
        assert.equal(h.app.abilityChoice, nextChoice, 'late cleanup preserves the replacement choice');
        assert.equal(h.app.busy, true);
        assert.equal(h.classes.has('is-working'), true);
        assert.match(h.nodes.get('#ttHint').firstChild.textContent, /Loading ability choices/);
        assert.equal(requests.length, 2, 'only preview and replacement prepare; no cancelled prepare or act');
        assert.equal(requests[1].body.candidate_id, 'end-turn');
        replacement.resolve({status: 'PREPARED'});
        assert.equal(await nextAction, true);
        assert.equal(requests.length, 3);
        assert.ok(requests[2].path.endsWith('/act'));
        assert.equal(requests[2].body.candidate_id, 'end-turn', 'only the replacement action submits');
        assert.equal(h.app.busy, false);
        assert.equal(h.app.abilityChoice, null);
      }
    });
  }
}

test('initial composition preview still reaches every target and single/preferred submission', async () => {
  for (const mode of ['picker', 'single', 'preferred']) {
    const h = harness(), requests = [], originalMenu = h.app.menu;
    const options = [{candidate_id: 'draft-breath', target_ids: ['enemy']},
      ...(mode === 'single' ? [] : [{candidate_id: 'draft-other', target_ids: ['other']}])];
    const group = {source_definition_id: 'breath', label: 'Breath',
      options: [{candidate_id: 'plain-breath', target_ids: ['enemy']}]};
    h.app.optionDraft = {dirty: true, revision: 1, matches: () => true,
      request: source => ({...originalMenu, source_definition_id: source, request_id: 'draft-request'})};
    h.context.api = async (path, request) => {
      requests.push({path, body: request?.body});
      if (path.endsWith('/composition/preview')) return {menu: {...originalMenu, state_version: 2,
        actions: [{...group, options}]}};
      return path.endsWith('/prepare') ? {status: 'PREPARED'}
        : {status: 'COMMITTED', events: {}, state: {menu: null}};
    };
    const pending = h.context.useGroup(group, {preferTargets: mode === 'preferred' ? ['enemy'] : []});
    if (mode === 'picker') {
      await until(() => h.app.targeting);
      assert.equal(h.app.busy, false);
      assert.equal(h.app.abilityChoice, null, 'preview releases ownership to the target picker');
      assert.deepEqual(Array.from(h.app.targeting.group.options, option => option.candidate_id),
        options.map(option => option.candidate_id), 'all composed options remain reachable');
      h.escape();
      assert.equal(await pending, false);
      assert.equal(requests.length, 1);
    } else {
      assert.equal(await pending, true);
      assert.deepEqual(requests.map(row => row.path.split('/').at(-1)), ['preview', 'prepare', 'act']);
      assert.equal(requests[2].body.candidate_id, 'draft-breath');
      assert.equal(requests[2].body.composition.request_id, 'draft-request');
    }
    assert.equal(h.app.busy, false);
  }
});

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

for (const stage of ['settings', 'route quote']) {
  test(`Escape settles unresolved ${stage} preparation and permits another action`, async () => {
    const h = harness(), response = deferred();
    let syncs = 0, settled = false;
    h.context.synchronizePresets = () => stage === 'settings' && ++syncs === 1 ? response.promise : Promise.resolve();
    h.app.state.menu.moves = [{candidate_id: 'edge', can_jump_down: true, path: [{x: 1, y: 1}, {x: 2, y: 1}]}];
    h.context.api = async path => {
      h.sent.push(path);
      if (path.endsWith('/movement-path/preview')) return response.promise;
      return path.endsWith('/prepare') ? {status: 'PREPARED'}
        : {status: 'COMMITTED', events: {}, state: {menu: null}};
    };
    const oldAction = h.context.act('edge', stage === 'route quote' ? {movement_mode: 'jump_down'} : null)
      .then(result => { settled = true; return result; });
    await tick();
    h.escape();
    await tick();
    assert.equal(settled, true, 'cancellation settles without a transport response');
    assert.equal(await oldAction, false);
    assert.equal(await h.context.act('other'), true);
    response.resolve({candidate: {candidate_id: 'quoted-edge'}});
    await tick();
    assert.equal(h.sent.filter(path => path.endsWith('/act')).length, 1);
    assert.equal(h.app.abilityChoice, null);
    assert.equal(h.app.busy, false);
  });
}

test('a cancelled deferred destination quote cannot touch a newer grouped prompt', async () => {
  const h = harness(), quote = deferred();
  const use = {dataset: {reactionUse: '0'}, onclick: null, disabled: false};
  const originalQuery = h.dialog.querySelectorAll;
  h.dialog.querySelectorAll = selector => selector === '[data-reaction-use]' ? [use] : originalQuery(selector);
  h.app.state.menu.moves = [{candidate_id: 'far', deferred_route: true, destination: {x: 3, y: 1}, movement_mode: 'walk'}];
  h.app.pendingMove = {path: 'before'};
  const prompt = {context: {choice: 'grouped'},
    alternatives: [{reaction: 'Parry', context: {reaction_source_id: 'parry', reactor_id: 'hero'}}]};
  let prepares = 0;
  h.context.api = async path => {
    h.sent.push(path);
    if (path.endsWith('/movement-destination/preview')) return quote.promise;
    if (path.endsWith('/prepare')) return ++prepares === 1
      ? {status: 'REACTION_REQUIRED', reaction: prompt, events: {}} : {status: 'PREPARED'};
    if (path.endsWith('/act')) return {status: 'COMMITTED', events: {}, state: {menu: null}};
    return {events: []};
  };
  const oldAction = h.context.act('far');
  await tick();
  assert.equal(h.sent.length, 1, 'the deferred destination quote is outstanding');
  h.escape();
  await tick();
  assert.equal(await oldAction, false);
  const nextAction = h.context.act('other');
  await until(() => h.app.waitingReaction);
  const nextChoice = h.app.abilityChoice, waiting = h.app.waitingReaction;
  assert.equal(typeof use.onclick, 'function', 'the newer grouped prompt is showing');
  quote.resolve({candidate: {candidate_id: 'quoted-far', canonical_path: [{x: 1, y: 1}, {x: 3, y: 1}]}});
  await tick();
  assert.equal(h.app.abilityChoice, nextChoice, 'the late quote cannot retire the newer choice');
  assert.equal(h.app.waitingReaction, waiting, 'the late quote cannot close the newer prompt');
  assert.equal(typeof use.onclick, 'function', 'the newer prompt keeps its answer handler');
  assert.deepEqual(h.app.pendingMove, {path: 'before'}, 'the late quote cannot replace the path');
  assert.equal(h.sent.some(path => path.endsWith('/movement-path/commit')), false, 'no continuation of the cancelled action');
  assert.doesNotMatch(h.nodes.get('#ttHint').firstChild.textContent, /Loading ability choices/);
  use.onclick();
  assert.equal(await nextAction, true, 'the newer action completes with its own answer');
  assert.equal(h.sent.filter(path => path.endsWith('/act')).length, 1, 'only the newer action commits');
  assert.equal(h.app.busy, false);
});

test('a second press during preparation keeps the busy refusal and the original choice', async () => {
  const h = harness(), response = deferred(), refusals = [];
  h.context.toast = message => refusals.push(message);
  h.context.api = async path => {
    h.sent.push(path);
    return path.endsWith('/prepare') ? response.promise
      : {status: 'COMMITTED', events: {}, state: {menu: null}};
  };
  const pending = h.context.act('breath');
  await tick();
  const original = h.app.abilityChoice;
  assert.equal(await h.context.act('other'), false);
  assert.equal(h.app.abilityChoice, original);
  assert.equal(original.cancelled, false);
  assert.equal(h.app.busy, true);
  assert.match(refusals[0], /Still working/);
  response.resolve({status: 'PREPARED'});
  assert.equal(await pending, true);
  assert.equal(h.sent.length, 2, 'the original choice completes its prepare and submit');
});

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
  const submitted = h.app.abilityChoice, refusals = [];
  h.context.toast = message => refusals.push(message);
  assert.equal(await h.context.act('other'), false);
  assert.equal(h.app.abilityChoice, submitted, 'a second press cannot take ownership from a submitted action');
  assert.match(refusals[0], /Still working/);
  assert.match(h.nodes.get('#ttHint').firstChild.textContent, /Applying/);
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

test('an auto-step saved prompt is reserved: Esc passes an optional rider, required stays open', async () => {
  for (const required of [false, true]) {
    // The server marks an optional rider with allow_decline; a required choice has no Pass.
    const h = harness(), prompt = {context: {choice: 'auto'}, choice: {minimum: 1, maximum: 1, allow_decline: !required,
      options: [{id: 'cone', label: 'Cone'}]}};
    let asks = 0;
    const bodies = [];
    h.context.api = async (path, options) => {
      h.sent.push(path); bodies.push(options?.body);
      if (path.endsWith('/auto-step')) return asks++ === 0
        ? {status: 'REACTION_REQUIRED', reaction: prompt, events: {}}
        : {status: 'COMMITTED', events: {}, state: {menu: null}};
      return {events: []};
    };
    h.app.busy = false;
    h.app.state = {...h.app.state, menu: {actor_id: 'hero', decision_id: 'd', state_version: 1}, pending_action: null};
    h.context.modelTurnNow = () => false;
    const pending = h.context.autoStep();
    await until(() => h.app.waitingReaction);
    assert.equal(h.app.waitingReaction.reserved, true, 'auto-step prompts are saved, so reserved');
    assert.equal(h.context.abilityReserved(), true, 'Cancel is withdrawn for an auto-step prompt');
    h.escape();
    if (required) {
      assert.ok(h.app.waitingReaction, 'a required saved prompt stays open on Esc');
      assert.equal(h.sent.filter(p => p.endsWith('/auto-step')).length, 1, 'no answer is sent locally');
      h.dialog.options[0].onclick();
    }
    assert.equal(await pending, true, 'the auto-step resolves after its answer, not as a local cancel');
    assert.equal(h.sent.filter(p => p.endsWith('/auto-step')).length, 2, 'the answer is sent to the server');
    if (!required) {
      assert.equal(bodies.at(-1).reactions.at(-1).selection, 'DECLINE', 'Esc on an optional saved rider sends Pass');
    }
  }
});

