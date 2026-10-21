// Model seats at the table (owner 2026-10-06/07): who plays a fighter, the model picker and the decision log.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {controlOf, decisionsHtml, isModelSeat, modelOwner, pickerHtml, playedByHtml, providerLabel, serverDriving} from '../static/tabletop/seats.js';
import {actionTipCard} from '../static/tabletop/rules.js';
import {resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';
import {bindPress} from '../static/tabletop/kept-bar.js?v=speedreuse2-3';
import {roofLevelsAt} from '../static/tabletop/flight-ui.js';
import {economySections, economyPills} from '../static/tabletop/action-economy.js';
import * as assisted from '../static/tabletop/assisted-menu.js';

// These controller/lifecycle fixtures explicitly choose GM presentation. The
// independent player binding and first-frame gate are tested in the identity suite.
const currentViewer = () => resolveViewerIdentity({version:1,role:'gm',actor_ids:[]},[],{seats:{}});

const providers = [{id: 'local', label: 'Local Qwen', kind: 'local', model: 'qwen3:8b'}, {id: 'api', label: 'My <API>', kind: 'openai_compatible', model: 'm1', vision: true}];
const status = {seats: {a: {control: 'MODEL', provider_id: 'api'}, b: {control: 'AI'}}, status: 'DECIDING', actor_id: 'a', text: 'A is deciding…'};

test('seat helpers read the saved seats', () => {
  assert.equal(isModelSeat(status, 'a'), true);
  assert.equal(isModelSeat(status, 'b'), false);
  assert.equal(isModelSeat(null, 'a'), false);
  assert.equal(controlOf(status, 'a', true), 'MODEL');
  assert.equal(controlOf(status, 'c', true), 'MANUAL');
  assert.equal(controlOf(status, 'c', false), 'LOCAL_AUTO');
  assert.equal(providerLabel(providers, 'api'), 'My <API>');
  assert.equal(providerLabel(providers, 'gone'), 'a model');
});

test('Model button only when a provider is installed', () => {
  assert.match(playedByHtml(providers), /data-control="MODEL"/);
  assert.doesNotMatch(playedByHtml([]), /data-control="MODEL"/);
});

test('picker lists providers escaped, preselects the current one, explains when none exist', () => {
  const html = pickerHtml(providers, 'api');
  assert.match(html, /value="api" checked/);
  assert.doesNotMatch(html, /value="local" checked/);
  assert.match(html, /My &lt;API&gt;/);
  assert.match(html, /API · m1 · sees the map/);
  assert.match(pickerHtml(providers, null), /value="local" checked/);
  assert.match(pickerHtml([], null), /No models are set up yet/);
});

test('decision log: newest first, built-in alternative when different, fallbacks marked, steps hidden', () => {
  const rows = [
    {recorded_at: 100, kind: 'TURN', actor_id: 'a', text: 'Ana plans: Strike, then End turn.', model: 'm1', latency_ms: 2300,
     tokens: {total_tokens: 812}, chosen_menu: [{action: 'Strike'}], built_in_menu: {action: 'Dash'}},
    {recorded_at: 101, kind: 'STEP', actor_id: 'a', candidate_id: 'x'},
    {recorded_at: 102, kind: 'TURN', actor_id: 'a', text: 'Ana: model took too long; built-in AI chose instead.', fallback: 'timeout', model: 'm1', latency_ms: 15000},
  ];
  const html = decisionsHtml(rows, () => 'Ana');
  assert.ok(html.indexOf('took too long') < html.indexOf('Ana plans'));
  assert.match(html, /The built-in AI would have chosen: Dash/);
  assert.match(html, /m1 · 2\.3 s · 812 tokens/);
  assert.match(html, /class="is-fallback"/);
  assert.doesNotMatch(html, /candidate/);
  assert.match(decisionsHtml([]), /No model decisions yet/);
});

// The real table code: a model's turn shows "is deciding…" and never this player's menu.
test('action bar on a model turn shows who decides, not the menu', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const from = source.indexOf('async function renderActionBar(');
  const to = source.indexOf('\n}', from) + 2;
  const el = () => ({listeners: {}, textContent: '', addEventListener(t, f) { this.listeners[t] = f; }});
  const bar = {html: '', parts: {}, set innerHTML(v) { this.html = v; this.parts = {}; }, get innerHTML() { return this.html; },
    querySelector(sel) { return (this.parts[sel] ||= el()); }};
  const app = {seatStatus: status, providers, menu: {actor_id: 'a', actions: [{label: 'Strike'}]}};
  const p = {match_id: 'm', current_actor_id: 'a', actors: [{entity_id: 'a', display_name: 'Ana'}]};
  const render = new Function('$', 'app', 'presentation', 'actorById', 'modelOwner', 'providerLabel', 'openSeatLog', 'serverDriving', 'toggleAIPlayback', 'currentViewer', 'bindPress',
    'let menuLoadingTimer = null; let menuLoadingActor = null; ' + source.slice(from, to) + '\nreturn renderActionBar;')(
    () => bar, app, () => p, id => p.actors.find(a => a.entity_id === id), modelOwner, providerLabel, () => {}, serverDriving, () => {}, currentViewer, bindPress);
  await render();
  assert.equal(bar.parts.strong.textContent, 'Ana');
  assert.equal(bar.parts['.tt-muted'].textContent, 'is deciding… (played by My <API>)');
  assert.doesNotMatch(bar.html, /Strike/);
});

test('a summon follows its owner\'s model seat; a defeated slot never belongs to the model', () => {
  assert.equal(modelOwner(status, {entity_id: 'a'}), 'a');
  assert.equal(modelOwner(status, {entity_id: 'spirit', owner_id: 'a'}), 'a');
  assert.equal(modelOwner(status, {entity_id: 'a', active: false}), null);
  assert.equal(modelOwner(status, {entity_id: 'b'}), null);
});

test('the table keeps watching a server-driven fight until this player is needed or it ends', () => {
  const idle = {...status, status: 'IDLE'};
  assert.equal(serverDriving(idle), true);                         // IDLE between chunks is not finished
  assert.equal(serverDriving(idle, {humanMenu: true}), true);      // your menu can be suspended by a reaction
  assert.equal(serverDriving(idle, {humanPrompt: true}), false);   // your reaction is open
  assert.equal(serverDriving(idle, {terminal: true}), false);
  assert.equal(serverDriving({seats: {b: {control: 'AI'}}}), false);  // no model seat: the old page behaviour
});

// The real refresh / render-scheduling / prompt-answer code (scheduleSeatPoll, resumeServerPrompt, refresh and
// resumePendingAction) against a scripted server. Only the network, the reaction dialog and the clock are stubs; timers
// are cancellable like the browser's.
function lifecycle(states, {postFails = 0, readFails = 0, actionBarDOM = false} = {}) {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const piece = (name, async = false) => {
    const from = source.indexOf(`${async ? 'async ' : ''}function ${name}(`);
    return source.slice(from, source.indexOf('\n}', from) + 2);
  };
  const timers = new Map(); let nextTimer = 1;
  const dom = actionBarDOM ? actionBarDocument() : null;
  const asked = [], posts = [], tipRows = [];
  const app = {seatStatus: {seats: {a: {control: 'MODEL', provider_id: 'api'}}, status: 'IDLE'}, busy: false, menu: null,
    matchId: 'm', fog: 'off', lastSequence: 0, promptInFlight: null, seatPoll: null};
  let reads = 0, renders = 0, failReads = readFails, failPosts = postFails, server = 0;
  const env = {
    bindPress, app, presentation: () => app.state?.presentation, serverDriving, enc: encodeURIComponent,
    currentViewer, reconcileViewerIdentity:()=>false, renderTokens() {},
    document: dom?.document || {hidden: false}, $: () => dom?.bar,
    isManualActor: () => true, actorById: id => app.state?.presentation.actors.find(a => a.entity_id === id) || {},
    setTimeout: fn => { const id = nextTimer++; timers.set(id, fn); return id; }, clearTimeout: id => { timers.delete(id); },
    readTableState: async () => { reads++; if (failReads > 0) { failReads--; throw new Error('offline'); } return states[Math.min(server, states.length - 1)]; },
    loadSeats: async () => {}, playEvents: async () => {}, gmNotice() {}, toast: () => {}, handleUnavailableFight: async () => false,
    api: async (path, options) => {
      if (!options?.body) return {events: [], last_sequence: 0};          // the events read in refresh
      posts.push(options.body);
      if (failPosts > 0) { failPosts--; throw new Error('post failed'); }  // the answer did not commit
      server++;                                                          // the server moves to its next state
      const next = states[Math.min(server, states.length - 1)];
      return next.pending_action ? {status: 'REACTION_REQUIRED', reaction: next.pending_action.reaction} : {status: 'COMMITTED', state: next, events: {events: []}};
    },
    // The dialog: the player answers "Pass" at once.
    askReaction: async prompt => { asked.push(prompt.context.checkpoint); return 'DECLINE'; },
    renderActionBar() {},
    render: state => { renders++; app.state = state; app.menu = state.menu || null; env.renderActionBar(); fns.scheduleSeatPoll(); },
  };
  if (dom) {
    // Exercise the actual human action-bar and Full rules builders. Only their
    // data helpers and DOM platform are substituted; no renderer is stubbed.
    const helpers = {...env, ...assisted, modelOwner, actionTipCard: (row, options) => {
        tipRows.push(row); return actionTipCard(row, options);
      }, automaticSlot: () => false, movementLeft: () => '30 ft',
      board: {map: null}, roofLevelsAt, economySections, economyPills,
      sheetFor: async () => null, layoutText: text => text, cleanRules: text => text, costTag: () => 'Action',
      useGroup() {}, renderHighlights() {}, renderRules: (text, h) => h('p', {}, text)};
    env.renderActionBar = new Function(...Object.keys(helpers),
      'let menuLoadingTimer = null; let menuLoadingActor = null; ' + piece('actionRules') + '\n' + piece('moveHeight') + '\n' + piece('appendActionBarRankedChoice')
      + '\n' + piece('draftOptionRows') + '\n' + piece('renderActionBar', true) + '\nreturn renderActionBar;')(...Object.values(helpers));
  }
  let fns;
  fns = new Function(...Object.keys(env), ['let refreshSequence = 0; let deferredMenuRead = null;', piece('appendReactionAnswer'), piece('scheduleSeatPoll'), piece('resumeServerPrompt'), piece('renderObservedState'),
    piece('eventsThroughState', true), piece('refresh', true), piece('pollTable', true), piece('resumePendingAction', true), 'return {scheduleSeatPoll, resumeServerPrompt, refresh, pollTable};'].join('\n'))(...Object.values(env));
  const settle = () => new Promise(r => setTimeout(r, 0));
  const tick = async () => { const [id, fn] = timers.entries().next().value || []; if (!fn) return false; timers.delete(id); await fn(); await settle(); return true; };
  return {app, fns, timers, asked, posts, tipRows, tick, settle, dom, advance: () => { server++; }, get reads() { return reads; }, get renders() { return renders; }};
}

// Minimal DOM platform for the real renderer: node replacement drops focus,
// details default closed, and scroll belongs to the existing node. This is a
// Node lifecycle check; the lead verifies actual Chromium layout separately.
function actionBarDocument() {
  const document = {hidden: false, activeElement: null};
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.parentNode = null; this.dataset = {}; this.open = false; this.scrollTop = 0; }
    get lastChild() { return this.children.at(-1); }
    appendChild(node) {
      if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1);
      node.parentNode = this; this.children.push(node); return node;
    }
    append(...nodes) { for (const node of nodes) if (typeof node === 'object') this.appendChild(node); }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    replaceChildren() {
      if (this.contains(document.activeElement)) document.activeElement = null;
      for (const child of this.children) child.parentNode = null;
      this.children = [];
    }
    set innerHTML(value) {
      this.html = value;
      this.replaceChildren();
      for (const match of value.matchAll(/<(h3|div|b|small|strong|span)\b([^>]*)>/g)) {
        const child = new Element(match[1]);
        child.className = /class="([^"]*)"/.exec(match[2])?.[1] || '';
        this.appendChild(child);
      }
    }
    querySelector(selector) {
      const [first, ...rest] = selector.split(' ');
      const matches = node => first.startsWith('.') ? (node.className || '').split(' ').includes(first.slice(1)) : node.tagName === first;
      const search = node => { for (const child of node.children) { if (matches(child)) return child; const found = search(child); if (found) return found; } return null; };
      const found = search(this);
      return rest.length ? found?.querySelector(rest.join(' ')) : found;
    }
    setAttribute(name, value) { this[name] = value; }
    addEventListener() {}
    focus() { document.activeElement = this; }
  }
  document.createElement = tag => new Element(tag);
  return {document, bar: new Element('div')};
}
const driving = {presentation: {terminal: false, current_actor_id: 'b', actors: []}};
const prompt = checkpoint => ({...driving, pending_action: {method: 'auto_step', request: {after: 1}, reaction: {context: {reactor_id: 'me', checkpoint}}}});

test('a busy moment skips a tick but never ends the observer; only one timer is ever pending', async () => {
  const h = lifecycle([driving]);
  await h.fns.refresh();
  assert.equal(h.timers.size, 1);
  h.app.busy = true;
  await h.tick();
  assert.equal(h.reads, 1);
  assert.equal(h.timers.size, 1);
  h.app.busy = false;
  await h.tick();
  assert.equal(h.reads, 2);
  assert.equal(h.timers.size, 1);          // render's reschedule cancelled the older handle
});

test('a failed refresh keeps the observer going', async () => {
  const h = lifecycle([driving], {readFails: 1});
  h.fns.scheduleSeatPoll();               // no state yet: still a model fight, so it starts
  h.app.state = driving;
  h.fns.scheduleSeatPoll();
  await h.tick();                          // the read fails
  assert.equal(h.reads, 1);
  assert.equal(h.timers.size, 1);          // and polling continues
  await h.tick();
  assert.equal(h.reads, 2);
});

test('a server prompt goes through the real answer path; a failed POST reopens it; success reaches the next prompt', async () => {
  const h = lifecycle([prompt('HIT'), prompt('SAVE'), driving], {postFails: 1});
  await h.fns.refresh(); await h.settle(); await h.settle();
  assert.deepEqual(h.asked, ['HIT']);      // opened and answered once
  assert.equal(h.posts.length, 1);         // that answer's POST failed …
  assert.equal(h.app.busy, false);         // … and the page is not stuck busy
  assert.equal(h.timers.size, 1);         // … and still observing
  await h.tick(); await h.settle();
  // Exactly: the same outstanding prompt once more for an explicit retry, then the next prompt once, nothing duplicated.
  assert.deepEqual(h.asked, ['HIT', 'HIT', 'SAVE']);
  assert.equal(h.posts.length, 3);         // failed HIT, retried HIT, SAVE
  assert.equal(h.app.busy, false);
  await h.tick(); await h.settle();
  assert.deepEqual(h.asked, ['HIT', 'HIT', 'SAVE']);   // later refreshes open nothing again
});

test('a running observer keeps a human menu observed and stops when the fight ends', async () => {
  const h = lifecycle([driving, {...driving, menu: {actor_id: 'me'}}]);
  await h.fns.refresh();
  assert.equal(h.timers.size, 1);
  h.app.state = {...driving, menu: {actor_id: 'me'}}; h.app.menu = h.app.state.menu;
  h.fns.scheduleSeatPoll();
  assert.equal(h.timers.size, 1);          // server reactions can suspend this menu
  const h2 = lifecycle([driving]);
  await h2.fns.refresh();
  h2.app.state = {presentation: {terminal: true, actors: []}};
  h2.fns.scheduleSeatPoll();
  assert.equal(h2.timers.size, 0);
});

test('human action, blocked model reaction, human follow-up: real refresh/resume path with no committed events', async () => {
  const menu = {actor_id: 'me', manual: true, actions: []};
  const waiting = {...driving, menu, model_deciding: true, last_sequence: 0};
  const human = {...prompt('FOOTWORK'), menu, last_sequence: 0};
  const h = lifecycle([waiting, human, {...driving, menu, last_sequence: 1}]);
  h.app.seatStatus.status = 'DECIDING';
  await h.fns.refresh();
  assert.equal(h.app.menu, menu);
  assert.equal(h.timers.size, 1);
  assert.deepEqual(h.asked, []);
  await h.tick();                         // still blocked; no clicks and no committed events
  assert.deepEqual(h.asked, []);
  h.advance(); h.app.seatStatus.status = 'IDLE';
  await h.tick(); await h.settle();
  assert.deepEqual(h.asked, ['FOOTWORK']);
  assert.equal(h.posts.length, 1);
  assert.equal(h.app.busy, false);
  await h.tick();
  assert.deepEqual(h.asked, ['FOOTWORK']);
});

test('a failed human follow-up POST is retried explicitly even with the human menu present', async () => {
  const menu = {actor_id: 'me', manual: true, actions: []};
  const h = lifecycle([{...prompt('HIT'), menu}, {...driving, menu}], {postFails: 1});
  await h.fns.refresh(); await h.settle(); await h.settle();
  assert.deepEqual(h.asked, ['HIT']);
  assert.equal(h.timers.size, 1);
  await h.tick(); await h.settle();
  assert.deepEqual(h.asked, ['HIT', 'HIT']);
  assert.equal(h.posts.length, 2);
});

test('idle observation keeps an unchanged human menu without cancelling its target pick', async () => {
  const state = {...driving, menu: {actor_id: 'me', manual: true, actions: []}};
  const h = lifecycle([state]);
  await h.fns.refresh();
  assert.equal(h.renders, 1);
  await h.tick();
  await h.fns.pollTable();
  assert.equal(h.reads, 3);
  assert.equal(h.renders, 1);  // full render invalidates targeting; the observer must leave it alone
  assert.equal(h.timers.size, 1);
});

test('idle human polls preserve expanded Full rules, focus and scroll in the real action bar', async () => {
  const state = {presentation: {terminal: false, current_actor_id: 'me', actors: [{entity_id: 'me', display_name: 'Player'}]},
    menu: {actor_id: 'me', manual: true, moves: [], actions: [{source_definition_id: 'ability', label: 'Strike', description: 'Strike one creature.', options: []}]}};
  const h = lifecycle([state, JSON.parse(JSON.stringify(state))], {actionBarDOM: true});
  await h.fns.refresh(); await h.settle();
  const rules = h.dom.bar.querySelector('details');
  const summary = rules.querySelector('summary');
  assert.equal(summary.textContent, 'Full rules');
  rules.open = true; summary.focus(); rules.scrollTop = 37; h.dom.bar.scrollTop = 83;
  h.advance();
  for (let tick = 0; tick < 4; tick++) {
    h.app.seatStatus.paused = tick % 2 === 0;
    await h.tick(); await h.fns.pollTable(); await h.settle();
    assert.equal(h.dom.bar.querySelector('details'), rules);
    assert.equal(rules.open, true);
    assert.equal(h.dom.document.activeElement, summary);
    assert.equal(rules.scrollTop, 37);
    assert.equal(h.dom.bar.scrollTop, 83);
    assert.equal(h.dom.bar.querySelector('.tt-ab-who .tt-muted').textContent,
      h.app.seatStatus.paused ? 'Your turn · AI turns Paused' : 'Your turn');
  }
  assert.equal(h.renders, 1);
});

test('sheetless no-action uses have their own section and retain the card activation', async () => {
  const state = {presentation: {terminal: false, current_actor_id: 'me', actors: [{entity_id: 'me', display_name: 'Player'}]},
    menu: {actor_id: 'me', manual: true, moves: [], actions: [{source_definition_id: 'response', label: 'Shelter',
      economy: 'NONE', description: 'Shelter an ally without an action.', options: []}]}};
  const h = lifecycle([state], {actionBarDOM: true});
  await h.fns.refresh(); await h.settle();
  assert.equal(h.tipRows.find(row => row.label === 'Shelter')?.economy, 'NONE');
  const all = node => [node, ...node.children.flatMap(all)];
  assert.ok(all(h.dom.bar).some(node => node.html?.includes('<h3>No action</h3>')));
});

test('after the last model seat is removed Play uses ordinary browser advancement', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const from = source.indexOf('async function toggleAIPlayback(');
  const piece = source.slice(from, source.indexOf('\n}', from) + 2);
  const released = {seats: {a: {control: 'MANUAL'}, b: {control: 'AI'}}, paused: false};
  const app = {seatStatus: {...status, paused: true},
    matchId: 'm', playing: false, userPaused: true};
  const loadFrom = source.indexOf('async function loadSeats(');
  const load = new Function('app', 'api', 'enc', 'serverDriving', 'let seatReadSequence = 0;\n' + source.slice(loadFrom, source.indexOf('\n}', loadFrom) + 2)
    + '\nreturn loadSeats;')(app, async () => released, encodeURIComponent, serverDriving);
  await load();
  assert.equal(serverDriving(app.seatStatus), false);
  let played = 0;
  const toggle = new Function('app', 'serverDriving', 'api', 'enc', 'refresh', 'toast', 'play', 'renderActionBar',
    piece + '\nreturn toggleAIPlayback;')(app, serverDriving, () => assert.fail('no server playback request'),
    encodeURIComponent, () => {}, () => {}, () => { played++; }, () => {});
  await toggle();
  assert.equal(played, 1);
  assert.equal(app.userPaused, false);
});

test('pollTable opens a follow-up prompt with a retained human menu and an empty event feed', async () => {
  const menu = {actor_id: 'me', manual: true};
  const h = lifecycle([{...driving, menu, model_deciding: true}, {...prompt('HIT'), menu}, {...driving, menu}]);
  await h.fns.refresh();
  h.advance();
  await h.fns.pollTable(); await h.settle();
  assert.deepEqual(h.asked, ['HIT']);
  assert.equal(h.posts.length, 1);
});

test('service-backed human movement → model opportunity attack → human Footwork, without intervening events',
  {skip: !process.env.SEAT_LIFECYCLE_FIXTURE}, async () => {
    const {waiting, human, committed, seats} = JSON.parse(readFileSync(process.env.SEAT_LIFECYCLE_FIXTURE, 'utf8'));
    assert.equal(waiting.menu.manual, true);
    assert.equal(waiting.model_deciding, true);
    assert.equal(waiting.last_sequence, human.last_sequence);
    assert.equal(human.pending_action.reaction.reaction, 'Footwork');
    const h = lifecycle([waiting, human, committed]);
    h.app.seatStatus = {seats, status: 'DECIDING'};
    await h.fns.refresh();
    assert.equal(h.timers.size, 1);
    assert.deepEqual(h.asked, []);
    await h.tick();
    assert.deepEqual(h.asked, []);
    h.advance(); h.app.seatStatus.status = 'IDLE';
    await h.tick(); await h.settle();
    assert.deepEqual(h.asked, [human.pending_action.reaction.context.checkpoint]);
    assert.equal(h.posts.length, 1);
    assert.deepEqual(h.posts[0], {...human.pending_action.request, reactions: [
      ...(human.pending_action.reactions || []), {...human.pending_action.reaction.context, selection: 'DECLINE'}]});
    assert.deepEqual(h.app.state, committed);
  });

test('Play/Pause posts the fight flag, refreshes, and never starts browser AI in a model-seat fight', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const from = source.indexOf('async function toggleAIPlayback(');
  const piece = source.slice(from, source.indexOf('\n}', from) + 2);
  const app = {seatStatus: {...status, paused: false}, matchId: 'm', playing: false};
  const posts = []; let refreshed = 0, played = 0;
  const toggle = new Function('app', 'serverDriving', 'api', 'enc', 'refresh', 'toast', 'play', 'renderActionBar',
    piece + '\nreturn toggleAIPlayback;')(app, serverDriving, async (url, options) => {
      posts.push([url, options.body]); return {...status, paused: options.body.paused};
    }, encodeURIComponent, async () => { refreshed++; }, () => {}, () => { played++; }, () => {});
  await toggle();
  assert.equal(app.userPaused, true);
  assert.equal(app.seatStatus.paused, true);
  await toggle();
  assert.deepEqual(posts, [['/api/tabletop/matches/m/playback', {paused: true}], ['/api/tabletop/matches/m/playback', {paused: false}]]);
  assert.equal(app.userPaused, false);
  assert.equal(refreshed, 2);
  assert.equal(played, 0);
});

test('a browser autoplay timer created before a model seat appeared cannot advance AI', () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const from = source.indexOf('function scheduleAutoPlay(');
  const piece = source.slice(from, source.indexOf('\n}', from) + 2);
  const app = {seatStatus: {seats: {}}, matchId: 'm', state: {}, menu: null};
  let timer, played = 0;
  const env = {app, serverDriving, setTimeout: fn => { timer = fn; }, presentation: () => ({}),
    automaticSlot: () => false, actorById: () => ({}), isManualActor: () => false,
    hasManualFighter: () => true, play: () => { played++; }};
  const schedule = new Function(...Object.keys(env), piece + '\nreturn scheduleAutoPlay;')(...Object.values(env));
  schedule();
  assert.equal(typeof timer, 'function');
  app.seatStatus = {...status, paused: true};
  timer();
  assert.equal(played, 0);
});

test('paused model and built-in turns show Paused and wire the same Play control', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const from = source.indexOf('async function renderActionBar(');
  const piece = source.slice(from, source.indexOf('\n}', from) + 2);
  for (const id of ['a', 'b']) {
    const parts = {};
    const bar = {innerHTML: '', querySelector: sel => (parts[sel] ||= {textContent: '', addEventListener(type, fn) { this[type] = fn; }})};
    const app = {seatStatus: {...status, paused: true}, providers, menu: null};
    const actor = {entity_id: id, display_name: id};
    const toggle = () => {};
    const env = {bindPress, $: () => bar, app, presentation: () => ({current_actor_id: id}), actorById: () => actor, currentViewer,
      modelOwner, serverDriving, providerLabel, openSeatLog() {}, toggleAIPlayback: toggle,
      isManualActor: () => false, automaticSlot: () => false, autoStep() {}, setControl() {}};
    const render = new Function(...Object.keys(env), 'let menuLoadingTimer = null; let menuLoadingActor = null; ' + piece + '\nreturn renderActionBar;')(...Object.values(env));
    await render();
    assert.equal(parts['.tt-muted'].textContent, 'Paused');
    assert.match(bar.innerHTML, /Play AI turns/);
    assert.equal(parts['[data-play]'].click, toggle);
    if (id === 'b') assert.equal(parts['[data-step]'].disabled, true);
  }
});

test('play style follows the model suggestion and only sends an override', async () => {
  const {suggestedStyle, styleToSend, styleHtml} = await import('../static/tabletop/seats.js');
  const qwen = {id: 'qwen', prompt_profile: 'choices'}, big = {id: 'big'};
  assert.equal(suggestedStyle(qwen), 'choices');
  assert.equal(suggestedStyle(big), 'full');
  assert.equal(suggestedStyle({prompt_profile: 'compact'}), 'full');
  assert.equal(styleToSend(qwen, 'choices'), null);
  assert.equal(styleToSend(qwen, 'full'), 'full');
  assert.equal(styleToSend(big, 'choices'), 'choices');
  assert.equal(styleToSend(big, undefined), null);
  const html = styleHtml(qwen, null);
  assert.match(html, /value="choices" checked/);
  assert.match(html, /Pick from a short list \(suggested for this model\)/);
  assert.doesNotMatch(html, /value="full" checked/);
  assert.match(styleHtml(qwen, 'full'), /value="full" checked/);
  assert.equal(styleHtml(undefined, null), '');
});

test('whole-turn planning overrides a compact or tiny model; a saved override is shown and re-sent', async () => {
  const {styleToSend, styleHtml} = await import('../static/tabletop/seats.js');
  for (const profile of ['compact', 'tiny']) {
    const p = {id: 'mid', prompt_profile: profile};
    assert.equal(styleToSend(p, 'full'), 'full');
    assert.equal(styleToSend(p, 'choices'), 'choices');
  }
  assert.equal(styleToSend({id: 'big', prompt_profile: 'full'}, 'full'), null);
  const qwen = {id: 'qwen', prompt_profile: 'choices'};
  const saved = styleHtml(qwen, 'full');
  assert.match(saved, /value="full" checked/);
  assert.equal(styleToSend(qwen, 'full'), 'full');
});

test('fight setup offers installed models and splits a model choice into AI + model seat', async () => {
  const {setupControlHtml, splitSetupControl, MODEL_PREFIX} = await import('../static/tabletop/seats.js');
  const html = setupControlHtml([{id: 'haiku55', label: 'Claude Haiku 5.5'}, {id: 'x"<', label: 'Bad <name>'}]);
  assert.match(html, /<option value="MANUAL">Manual — you choose<\/option><option value="SUGGESTED">Assisted — ranked choices, you choose<\/option><option value="LOCAL_AUTO">Auto — AI chooses<\/option>/);
  assert.match(html, /<option value="MODEL:haiku55">Claude Haiku 5\.5<\/option>/);
  assert.doesNotMatch(html, /Bad <name>/);
  assert.equal(setupControlHtml([]), '<option value="MANUAL">Manual — you choose</option><option value="SUGGESTED">Assisted — ranked choices, you choose</option><option value="LOCAL_AUTO">Auto — AI chooses</option>');
  assert.match(setupControlHtml([{id: 'internal-code'}]), />Installed model 1<\/option>/);
  assert.doesNotMatch(setupControlHtml([{id: 'internal-code'}]), />internal-code</);
  assert.deepEqual(splitSetupControl(MODEL_PREFIX + 'haiku55'), {mode: 'LOCAL_AUTO', provider: 'haiku55'});
  assert.deepEqual(splitSetupControl('MANUAL'), {mode: 'MANUAL', provider: null});
  assert.deepEqual(splitSetupControl('LOCAL_AUTO'), {mode: 'LOCAL_AUTO', provider: null});
  assert.deepEqual(splitSetupControl(''), {mode: 'LOCAL_AUTO', provider: null});
});
