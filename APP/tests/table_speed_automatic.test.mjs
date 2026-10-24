import assert from 'node:assert/strict';
import fs from 'node:fs';
import {automaticTurn} from '../static/tabletop/automatic-turn.js';
const calls = [];
const result = await automaticTurn({
  start: async () => { calls.push('start'); return {running: true}; },
  observe: async () => { calls.push('observe'); return {running: false}; },
  wait: async ms => { calls.push(ms); },
  current: () => true,
  status: () => {},
});
assert.equal(result.running, false);
assert.deepEqual(calls, ['start', 100, 'observe']);
let reads = 0;
await automaticTurn({
  start: async () => ({running: true}),
  observe: async () => { reads++; },
  wait: async () => {},
  current: () => false,
  status: () => {},
});
assert.equal(reads, 0);
let starts = 0;
await assert.rejects(automaticTurn({
  start: async () => { starts++; throw new Error('uncertain command'); },
  observe: async () => { throw new Error('must not observe an unacknowledged start'); },
  wait: async () => {}, current: () => true, status: () => {},
}), /uncertain command/);
assert.equal(starts, 1);
const desktop = fs.readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const opening = desktop.indexOf('async function loadSeats()');
const loadSource = desktop.slice(opening, desktop.indexOf('\n}', opening) + 2);
const app = {matchId: 'm', userPaused: true, state: null};
let seatStatus = {paused: false, running: false, status: 'IDLE'};
const loadSeats = Function('app', 'api', 'enc',
  'let seatReadSequence=0;' + loadSource + ';return loadSeats;')(
    app, async () => seatStatus, encodeURIComponent);
await loadSeats();
assert.equal(app.userPaused, true, 'an idle poll cannot retry an uncertain start');
seatStatus = {paused: false, running: true, status: 'RUNNING'};
await loadSeats();
assert.equal(app.userPaused, false, 'a confirmed other-tab run may be observed');
for (const file of ['static/tabletop/tabletop.js', 'static/play/play-client.js']) {
  const source = fs.readFileSync(new URL('../' + file, import.meta.url), 'utf8');
  const start = file.includes('tabletop.js') ? source.indexOf('async function play()') : source.indexOf('async function step()');
  const body = source.slice(start, source.indexOf('\n}', start) + 2 || undefined);
  assert.match(body, /automaticTurn/);
  assert.doesNotMatch(body, /auto-step|requestDeferredMenu|app\.speed \* 1000/);
}
