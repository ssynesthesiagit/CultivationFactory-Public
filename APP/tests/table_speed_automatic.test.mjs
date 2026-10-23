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
for (const file of ['static/tabletop/tabletop.js', 'static/play/play-client.js']) {
  const source = fs.readFileSync(new URL('../' + file, import.meta.url), 'utf8');
  const start = file.includes('tabletop.js') ? source.indexOf('async function play()') : source.indexOf('async function step()');
  const body = source.slice(start, source.indexOf('\n}', start) + 2 || undefined);
  assert.match(body, /automaticTurn/);
  assert.doesNotMatch(body, /auto-step|requestDeferredMenu|app\.speed \* 1000/);
}
