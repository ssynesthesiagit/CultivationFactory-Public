import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {decisionChanged} from '../static/tabletop/pending-decision.js';
import {createViewerStore, resolveViewerIdentity} from '../static/tabletop/viewer-identity.js';

const source = fs.readFileSync(process.env.SOL150_CLIENT_SOURCE || new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const ask = source.slice(source.indexOf('async function askReaction(prompt'), source.indexOf('async function withReactions(send'));
const poll = source.slice(source.indexOf('async function pollTable()'), source.indexOf('setInterval(pollTable, 3000)'));
// REACTUI's continuation calls this shared answer helper. Include it rather
// than masking a missing dependency as a failed combat/network continuation.
const continuation = source.slice(source.indexOf('function appendReactionAnswer('), source.indexOf('// The Items panel over the action bar'));
const playback = source.slice(source.indexOf('function playEvents('), source.indexOf('// ------------------------------------------------------------------ sheets over BroadcastChannel'));
const eventTail = source.slice(source.indexOf('async function eventsThroughState('), source.indexOf('async function refresh('));

// These continuation fixtures explicitly use a Game Master presentation. The
// production resolver supplies readiness; no missing binding defaults to GM.
function explicitGMView(app) {
  const store = createViewerStore({viewId:'sol150-journal'});
  store.bindGM(app.matchId);
  return () => resolveViewerIdentity(store.read(app.matchId), app.state?.presentation?.actors || [], app.seatStatus);
}

// Real client continuation and event playback; only the DOM and transport are
// replaced. The Python table test supplies a committed service journal too.
export async function checkRemoteJournal({entry, replacement, localAnswer = false, method = 'act', fixture}) {
  const prompt = fixture?.prompt || {context: {checkpoint: 'SAVE', reactor_id: 'tabik'}, trigger: 'Fireball Art'};
  const next = {...prompt, context: {...prompt.context, checkpoint: 'NEXT'}};
  const pending = {method, request: {candidate_id: 'original'}, reaction: prompt, reactions: []};
  const events = fixture?.events || {last_sequence: 14, events: [
    {sequence: 11, event_type: 'DAMAGE_ROLLED', roll_id: 'damage'},
    {sequence: 12, event_type: 'DAMAGE_COMMITTED', target_ids: ['tabik'], raw: {payload: {hp_damage: 8}}},
    {sequence: 13, event_type: 'HEALING_APPLIED', target_ids: ['tabik'], raw: {payload: {amount: 2}}},
    {sequence: 14, event_type: 'GM_RIDER', summary: 'Unattended flammable objects ignite.'}],
    dice: [{roll_id: 'damage', groups: [], label: 'Fireball Art damage'}]};
  const initial = fixture?.after ?? 10;
  const state = {...fixture?.state, last_sequence: events.last_sequence,
    pending_action: replacement ? (fixture?.pending || {...pending,
      request: {candidate_id: 'replacement', decision_id: 'saved-decision', state_version: 7, after: initial}, reaction: next}) : null};
  const committed = fixture?.committed || {events: [...events.events,
    {sequence: events.last_sequence + 1, event_type: 'GM_RIDER', summary: 'The replacement action finished.'}],
    dice: events.dice, last_sequence: events.last_sequence + 1};
  const done = {...state, last_sequence: localAnswer ? committed.last_sequence : events.last_sequence, pending_action: null};
  const expected = localAnswer ? committed : events;
  const app = {matchId: 'scratch', lastSequence: initial, busy: true, fog: 'off', diceOn: true,
    state: {last_sequence: initial, pending_action: pending}};
  const feed = [], dice = [], floats = [], reads = [], notices = [];
  const inputs = [];
  let sends = 0, renders = 0, functions, replacementSends = 0;
  const api = async (url, options) => {
    if (url.endsWith('/act') || url.endsWith('/auto-step')) {
      assert.ok(url.endsWith(method === 'auto_step' ? '/auto-step' : '/act'));
      const {after, reactions, ...binding} = options.body;
      const {after: savedAfter, ...savedBinding} = state.pending_action.request;
      assert.deepEqual(binding, savedBinding, 'preserve every saved action/decision binding');
      assert.equal(savedAfter, initial, 'saved cursor precedes catch-up');
      assert.equal(options.body.reactions.at(-1).selection, 'DECLINE');
      replacementSends++;
      // Real events(after) contract: an old cursor includes catch-up AND the
      // new commit. Service fixtures retain both actual response windows.
      const journal = fixture?.responses?.[after] || {...committed,
        events: committed.events.filter(row => row.sequence > after)};
      return {status: 'COMMITTED', state: done, events: journal};
    }
    assert.match(url, /\/events\?after=/, 'never resend an answered action');
    const after = Number(url.split('after=')[1]); reads.push(after);
    return after < events.last_sequence ? events : {events: [], dice: [], last_sequence: events.last_sequence};
  };
  const render = value => {
    const journal = value.pending_action ? events : expected;
    assert.deepEqual(feed, journal.events, 'journal must reach the feed exactly once before rendering advances the cursor');
    assert.equal(dice.length, journal.dice.filter(d => journal.events.some(e => e.roll_id === d.roll_id)).length);
    app.state = value;
    app.lastSequence = Math.max(app.lastSequence, value.last_sequence); renders++;
  };
  const deps = {app, askReactionInput: () => new Promise(resolve => inputs.push(resolve)), closeChoice() {}, readTableState: async () => state,
    decisionChanged, document: {hidden: false}, api, enc: String, render, renderObservedState: render,
    currentViewer: explicitGMView(app), loadSeats: async () => { app.seatStatus = {seats:{}}; },
    gmNotice: rows => notices.push(...rows),
    toast: message => { throw new Error(message); }, refresh: () => { throw new Error('unexpected refresh'); },
    appendFeed: rows => feed.push(...rows), actors: () => [{entity_id: 'tabik', position: {x: 1, y: 1}}],
    board: {floatText: (...args) => floats.push(args), animateMove: async () => {}, flashLine() {}},
  };
  app.dice = {roll: async (...args) => dice.push(args)};
  functions = new Function(...Object.keys(deps), `let refreshSequence = 0;\n${continuation}\n${poll}\n${playback}\n${eventTail}\nreturn {withReactions, resumePendingAction, pollTable, playEvents};`)(...Object.values(deps));
  const resultPromise = entry === 'action'
    ? functions.withReactions(async () => { sends++; return {status: 'REACTION_REQUIRED', reaction: prompt}; })
    : functions.resumePendingAction(pending, true);
  // Wait through the shared playback queue before polling the open prompt.
  for (let i = 0; i < 80 && !app.waitingReaction; i++) await Promise.resolve();
  assert.ok(app.waitingReaction, 'the real continuation reached its prompt');
  await functions.pollTable();
  if (replacement) {
    const replacementPrompt = state.pending_action.reaction;
    for (let i = 0; i < 80 && app.waitingReaction?.prompt !== replacementPrompt; i++) await Promise.resolve();
    assert.equal(app.waitingReaction?.prompt, replacementPrompt);
    assert.deepEqual(feed, events.events);
    if (localAnswer) inputs.at(-1)('DECLINE');
    else app.waitingReaction.stop(done); // a third client completes the replacement
  }
  const result = await resultPromise;
  if (entry === 'action') {
    await functions.playEvents(result.events); render(result.state); notices.push(...result.events.events);
  }
  assert.equal(result.status, 'COMMITTED');
  assert.deepEqual(feed, expected.events, 'every event appears exactly once, including the new commit');
  assert.equal(app.lastSequence, expected.last_sequence);
  assert.deepEqual(reads, replacement && !localAnswer ? [initial, events.last_sequence] : [initial]);
  assert.deepEqual(notices, expected.events);
  assert.equal(sends, entry === 'action' ? 1 : 0);
  assert.equal(replacementSends, localAnswer ? 1 : 0);
  assert.equal(renders, replacement ? 2 : 1);
}

for (const entry of ['action', 'reload']) {
  for (const replacement of [false, true]) {
    test(`${entry} consumes remote ${replacement ? 'replacement' : 'completion'} journal before advancing cursor`,
      () => checkRemoteJournal({entry, replacement}));
  }
  test(`${entry} presents a locally answered replacement exactly once`,
    () => checkRemoteJournal({entry, replacement: true, localAnswer: true}));
  test(`${entry} presents an auto-step replacement with overlapping journal exactly once`,
    () => checkRemoteJournal({entry, replacement: true, localAnswer: true, method: 'auto_step'}));
}

if (process.env.SOL150_REPLACEMENT_JOURNAL) {
  const fixture = JSON.parse(fs.readFileSync(process.env.SOL150_REPLACEMENT_JOURNAL, 'utf8'));
  for (const entry of ['action', 'reload']) {
    test(`${entry} answers a real saved ${fixture.pending.method} replacement after catch-up`,
      () => checkRemoteJournal({entry, replacement: true, localAnswer: true, method: fixture.pending.method, fixture}));
  }
}

if (process.env.SOL150_SERVICE_JOURNAL) {
  const fixture = JSON.parse(fs.readFileSync(process.env.SOL150_SERVICE_JOURNAL, 'utf8'));
  for (const entry of ['action', 'reload']) {
    test(`${entry} consumes a real table's remote Healing Hymn journal`, () => checkRemoteJournal({entry, fixture}));
  }
}

for (const mode of ['answered', 'superseded', 'unchanged', 'unchanged with new journal']) {
  test(`real table polling reconciles a ${mode} prompt even while busy`, async () => {
    const prompt = {context: {checkpoint: 'TYPED:D20_REROLL_SAVE', reactor_id: 'tabik', reaction_source_id: 'guard'}, trigger: 'Lingfeng’s Quarantine Veil'};
    const unchanged = mode.startsWith('unchanged');
    const advanced = mode === 'unchanged with new journal';
    const pending = mode === 'answered' ? null : {reaction: unchanged ? prompt : {...prompt, context: {...prompt.context, checkpoint: 'NEXT'}}};
    const state = {last_sequence: advanced ? 12 : 10, pending_action: pending};
    const app = {matchId: 'scratch', busy: true, fog: 'off', lastSequence: 10,
      state: {last_sequence: 10, pending_action: {reaction: prompt}},
      mapPick: {close() { app.mapPick = null; }}};
    const journal = [{event_sequence: 11, event_type: 'GM_RIDER', summary: 'A recorded effect.'},
      {event_sequence: 12, event_type: 'GM_RIDER', summary: 'A second recorded effect.'}];
    const feed = [], reads = [], rendered = [];
    let closed = 0, seatsRead = 0;
    const deps = {app, askReactionInput: () => new Promise(() => {}), closeChoice: () => { closed++; },
      readTableState: async () => state, decisionChanged, document: {hidden: false},
      currentViewer: explicitGMView(app), loadSeats: async () => { seatsRead++; app.seatStatus = {seats:{}}; },
      api: async url => {
        reads.push(url);
        assert.equal(url, '/api/tabletop/matches/scratch/events?after=10');
        return {events: journal, dice: [], last_sequence: 12};
      }, enc: String, appendFeed: rows => feed.push(...rows), actors: () => [], board: {},
      renderObservedState: value => {
        assert.equal(app.waitingReaction?.prompt, prompt, 'rendering keeps the exact pending answer');
        assert.ok(app.mapPick, 'the map choice remains open during a same-prompt refresh');
        assert.deepEqual(feed, advanced ? journal : [], 'journal is consumed before a same-prompt state renders');
        rendered.push(value); app.state = value;
      },
    };
    const functions = new Function(...Object.keys(deps),
      `let refreshSequence = 0;\n${ask}\n${poll}\n${playback}\n${eventTail}\nreturn {askReaction, pollTable};`)(...Object.values(deps));
    const answer = functions.askReaction(prompt);
    await functions.pollTable();
    assert.equal(seatsRead, 1, 'pending prompts still refresh controller assignments');
    assert.equal(reads.length, advanced ? 1 : 0);
    assert.deepEqual(rendered, unchanged ? [state] : []);
    if (unchanged) {
      assert.equal(closed, 0);
      assert.ok(app.waitingReaction);
      assert.ok(app.mapPick);
      assert.equal(app.lastSequence, advanced ? 12 : 10);
      app.waitingReaction.stop(state); // release this test's pending promise
    }
    assert.equal((await answer).superseded, true);
    assert.equal(app.waitingReaction, null);
    assert.equal(app.mapPick, null);
    assert.equal(closed, 1);
  });
}

test('the actual hover section leads with Dead or the death-save tally', () => {
  const board = fs.readFileSync(new URL('../static/tabletop/board.js', import.meta.url), 'utf8');
  const start = board.indexOf('const section = creature =>');
  const section = new Function('escapeText', `${board.slice(start, board.indexOf('    const companion', start))}\nreturn section;`)(String);
  const dead = section({name: 'Tabik', hp: 0, maxHp: 119, down: true, lifeStatus: 'Dead',
    conditions: [{name: 'Advantage on checks', text: 'Irrelevant', tone: 'buff'}]});
  assert.match(dead, />Dead</);
  assert.doesNotMatch(dead, /down|119|Advantage|Irrelevant|No conditions/);
  const dying = section({name: 'Tabik', hp: 0, maxHp: 119, lifeStatus: 'Dying — 1 success, 2 failures'});
  assert.match(dying, /Dying — 1 success, 2 failures/);
});
