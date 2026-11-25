import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFightStream} from '../static/tabletop/fight-stream.js';
import {automaticTurn} from '../static/tabletop/automatic-turn.js';

class Clock {
  now = 0; next = 1; jobs = new Map();
  setTimeout = (fn, ms) => this.add(fn, ms, false);
  setInterval = (fn, ms) => this.add(fn, ms, true);
  clearTimeout = id => this.jobs.delete(id);
  clearInterval = this.clearTimeout;
  add(fn, ms, repeat) { const id = this.next++; this.jobs.set(id, {fn, ms, repeat, at: this.now + ms}); return id; }
  async tick(ms) {
    const end = this.now + ms;
    while (true) {
      const entry = [...this.jobs].filter(([, j]) => j.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!entry) break;
      const [id, job] = entry; this.now = job.at;
      if (job.repeat) job.at += job.ms; else this.jobs.delete(id);
      job.fn(); await flush();
    }
    this.now = end; await flush();
  }
}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function harness() {
  const clock = new Clock(), sources = [], applied = [];
  let tablePolls = 0, statusPolls = 0;
  class FakeSource {
    listeners = {}; closed = false;
    constructor(url) { this.url = url; sources.push(this); }
    addEventListener(kind, fn) { this.listeners[kind] = fn; }
    close() { this.closed = true; }
    send(kind, payload) { this.listeners[kind]({data: JSON.stringify(payload)}); }
  }
  const stream = createFightStream({EventSource: FakeSource, timers: clock,
    poll: () => { tablePolls++; }, seatStatus: value => applied.push(value),
    events: value => applied.push(value), changed: value => applied.push(value)});
  stream.watch('a', () => 12);
  return {clock, sources, stream, applied, get tablePolls() { return tablePolls; },
    get statusPolls() { return statusPolls; }, observe: async () => { statusPolls++; return {running: true}; }};
}

test('production hook and open stream issue zero polls in 60s idle', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  // These guards ensure removing the real hook cannot leave a green module-only test.
  assert.ok(source.includes('fightStream.watch(matchId, () => app.lastSequence)'), 'production stream hook must be enabled');
  assert.doesNotMatch(source, /setInterval\(pollTable, 3000\)/);
  assert.match(source, /if \(fightStream\.open\) return;/);
  assert.match(source, /observe: \(\) => fightStream\.observeStatus/);
  const h = harness(); h.sources[0].onopen();
  const run = automaticTurn({start: async () => ({running: true}),
    observe: () => h.stream.observeStatus(h.observe),
    wait: ms => new Promise(resolve => h.clock.setTimeout(resolve, ms)),
    current: () => true, status() {}});
  await flush(); await h.clock.tick(60000);
  assert.equal(h.tablePolls, 0);
  assert.equal(h.statusPolls, 0);
  h.sources[0].send('seat-status', {running: false});
  assert.equal((await run).running, false);
  h.stream.stop();
});

test('dropped stream restores old polling rates, retries with backoff, and recovers', async () => {
  const h = harness(), first = h.sources[0]; first.onopen();
  const waiting = h.stream.observeStatus(h.observe);
  first.onerror(); await waiting;
  assert.equal(h.statusPolls, 1);
  await h.clock.tick(1000);
  assert.equal(h.sources.length, 2);
  h.sources[1].onerror();
  await h.clock.tick(2000);
  assert.equal(h.sources.length, 3);
  assert.equal(h.tablePolls, 1);
  assert.match(h.sources[2].url, /after=12$/);
  h.sources[2].onopen();
  await h.clock.tick(60000);
  assert.equal(h.tablePolls, 1);
  const waitingAgain = h.stream.observeStatus(h.observe);
  h.sources[2].send('seat-status', {running: false});
  assert.equal((await waitingAgain).running, false);
  h.stream.stop();
});

test('messages use ordered apply paths and switching fights closes the old source', async () => {
  const h = harness(), first = h.sources[0]; first.onopen();
  for (const [index, kind] of ['events', 'seat-status', 'menu-ready', 'fight-changed'].entries()) first.send(kind, {index});
  await flush(); assert.deepEqual(h.applied.map(x => x.index), [0, 1, 2, 3]);
  h.stream.watch('b', () => 0);
  assert.equal(first.closed, true);
  first.send('events', {index: 99});
  await flush(); assert.equal(h.applied.length, 4);
  h.stream.stop(); assert.equal(h.clock.jobs.size, 0);
});

test('fallback automaticTurn observes at 100ms and a buffered terminal status is not lost', async () => {
  const h = harness();
  const run = automaticTurn({start: async () => ({running: true}),
    observe: () => h.stream.observeStatus(h.observe),
    wait: ms => new Promise(resolve => h.clock.setTimeout(resolve, ms)),
    current: () => true, status() {}});
  await flush(); await h.clock.tick(1000);
  assert.equal(h.statusPolls, 10);
  h.sources[0].onopen();
  // Terminal status arrives between observations, before the next 100ms wait ends.
  h.sources[0].send('seat-status', {running: false}); await flush();
  await h.clock.tick(100);
  assert.equal((await run).running, false);
  assert.equal(h.statusPolls, 10);
  h.stream.stop();
});
