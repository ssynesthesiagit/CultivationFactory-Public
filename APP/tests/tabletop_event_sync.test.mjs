// No browser or live model: exercise the production poll and playback functions.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
function piece(name, async = false) {
  const start = source.indexOf(`${async ? 'async ' : ''}function ${name}(`);
  assert.ok(start >= 0);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function harness(response, state) {
  const app = {matchId: 'm', lastSequence: 436, fog: 'own',
    state: {menu: {manual: true, state_version: 10}}, menu: {manual: true}};
  const requests = [], displayed = [], feed = [];
  let reads = 0;
  const bindings = {
    app, document: {hidden: false}, enc: encodeURIComponent,
    api: async path => {
      requests.push(path);
      return Array.isArray(response) ? response.shift() : response;
    }, loadSeats: async () => {},
    readTableState: async () => { reads++; return state; },
    renderObservedState: state => { app.state = state; displayed.push(state); },
    resumeServerPrompt() {}, handleUnavailableFight: async error => { throw error; },
    appendFeed: rows => feed.push(...rows), actors: () => [], board: {},
    // This viewer used to skip the read with an idle seat and empty prose feed.
    currentViewer: () => ({status: 'gm'}), serverDriving: () => false,
    presentation: () => ({terminal: false}), isManualActor: () => true, actorById: () => ({}),
  };
  const functions = new Function(...Object.keys(bindings), `let refreshSequence = 0;
    ${piece('eventsThroughState', true)}
    ${piece('playEvents')}
    ${piece('playEventBatch', true)}
    ${piece('pollTable', true)}
    return {pollTable};`)(...Object.values(bindings));
  return {app, requests, displayed, feed, functions, get reads() { return reads; }};
}

test('model-seat committed turn advances playback and the next poll cursor', async () => {
  const h = harness({events: [{event_sequence: 437, event_type: 'TURN_STARTED'}],
    last_sequence: 438, state_version: 11}, {last_sequence: 438, menu: {state_version: 11}});
  await h.functions.pollTable();
  assert.equal(h.app.lastSequence, 438);
  assert.equal(h.displayed.length, 1);
  await h.functions.pollTable();
  assert.match(h.requests.at(-1), /after=438$/);
  assert.equal(h.feed.length, 1, 'committed events are never replayed');
});

for (const response of [
  {events: [], last_sequence: 436, state_version: 11},
  {events: [], last_sequence: 438, state_version: 11},
  {events: [{event_sequence: null}], last_sequence: null},
  {events: [{event_sequence: 437}]},
  {last_sequence: 436},
]) {
  test(`stalled/hidden/malformed feed refreshes the authoritative turn: ${JSON.stringify(response)}`, async () => {
    const state = {last_sequence: 438, menu: {manual: true, state_version: 11}};
    const h = harness(response, state);
    await h.functions.pollTable();
    assert.equal(h.reads, 1);
    assert.equal(h.displayed[0], state);
    assert.equal(h.app.lastSequence, 438);
    assert.equal(h.app.polling, false);
    if (response.events?.some(row => !Number.isSafeInteger(row.event_sequence))) {
      assert.equal(h.feed.length, 0, 'unsequenced prose is not replayed on every poll');
    }
  });
}

test('state-version change refreshes even without new journal events', async () => {
  const state = {last_sequence: 436, menu: {state_version: 11}};
  const h = harness({events: [], last_sequence: 436, state_version: 11}, state);
  await h.functions.pollTable();
  assert.equal(h.displayed[0].menu.state_version, 11);
});

test('malformed tail keeps the valid prefix, shows snapshot, and advances past it', async () => {
  const h = harness([
    {events: [{event_sequence: 437, event_type: 'TURN_STARTED'}], last_sequence: 437},
    {events: [{event_sequence: null, event_type: 'TURN_STARTED'}], last_sequence: null},
    {events: [], last_sequence: 438, state_version: 11},
  ], {last_sequence: 438, menu: {manual: true, state_version: 11}});

  await h.functions.pollTable();
  assert.equal(h.requests.length, 2, 'the snapshot boundary requires one tail request');
  assert.match(h.requests[1], /after=437$/);
  assert.equal(h.feed.length, 1, 'only the valid initial prefix is played');
  assert.equal(h.app.lastSequence, 438, 'the malformed tail is skipped to the snapshot boundary');
  assert.equal(h.displayed[0].menu.state_version, 11, 'the authoritative state is displayed');

  await h.functions.pollTable();
  assert.match(h.requests[2], /after=438$/);
  assert.equal(h.feed.length, 1, 'the valid prefix is not replayed on the next poll');
});
