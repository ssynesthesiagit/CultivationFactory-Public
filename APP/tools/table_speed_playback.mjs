// Browserless scheduler measurement. Production catch-up/playback functions;
// timer-backed board/dice stand-ins. NOT a DOM, layout, paint or GPU benchmark.
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {performance} from 'node:perf_hooks';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const boardSource = readFileSync(new URL('../static/tabletop/board.js', import.meta.url), 'utf8');
const piece = (src, name, async = false, exported = false) => {
  const start = src.indexOf(`${exported ? 'export ' : ''}${async ? 'async ' : ''}function ${name}(`);
  assert.ok(start >= 0, name);
  return src.slice(start, src.indexOf('\n}', start) + 2).replace(/^export /, '');
};
const moveFrames = new Function(piece(boardSource, 'moveFrames', false, true) + ';return moveFrames;')();
let input = '';
for await (const chunk of process.stdin) input += chunk;
const report = JSON.parse(input);
const results = [];
for (const scenario of report.scenarios.filter(s => !s.profiled)) {
  for (const [index, feed] of scenario.feeds.entries()) {
    const fast = feed.phase === 'ai';
    const cursor = Math.min(...feed.events.map(row => row.event_sequence)) - 1;
    const app = {matchId: 'probe', lastSequence: Number.isFinite(cursor) ? cursor : 0, diceOn: false};
    let requested = 0, calls = 0;
    const positions = feed.events.flatMap(row => [row.actor_id, ...(row.target_ids || [])])
      .filter(Boolean).map(entity_id => ({entity_id, position: {x: 0, y: 0}}));
    const board = {animateMove: async (_id, path, options) => {
      for (const frame of moveFrames(path, options)) {
        requested += frame.delayMs;
        await new Promise(resolve => setTimeout(resolve, frame.delayMs));
      }
    }, flashLine() {}, floatText() {}};
    const api = async () => { calls++; return {events: [], dice: [], last_sequence: feed.last_sequence}; };
    const fns = new Function('app', 'appendFeed', 'actors', 'board', 'api',
      piece(source, 'playEventBatch', true) + '\n' + piece(source, 'eventsThroughState', true)
      + ';return {playEventBatch, eventsThroughState};')(app, () => {}, () => positions, board, api);
    let t = performance.now();
    await fns.eventsThroughState(feed, {last_sequence: feed.last_sequence}, 'probe');
    const catchup = performance.now() - t;
    assert.equal(calls, 0, 'coherent boundary must not reread events');
    t = performance.now();
    await fns.playEventBatch(feed, {fast, finalizePause: true});
    const playback = performance.now() - t;
    results.push({actors: scenario.actors, phase: feed.phase, batch: index, fast,
      catchup_ms: catchup, catchup_requests: calls, playback_timer_wall_ms: playback,
      movement_timer_budget_ms: requested, default_interstep_ms: fast ? 700 : 0});
  }
}
console.log(JSON.stringify({kind: 'production JS with timer stand-ins; no real DOM/paint', results}));
