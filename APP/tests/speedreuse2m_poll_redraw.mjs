// SPEEDREUSE2M: the table must recognise an unchanged compact poll instead of redrawing the board and action bar.
// A poll delivers the compact movement grid; render() stores the movement-expanded copy in app.state.
// Comparing a poll with that expanded copy never matches, so every poll redrew the whole table.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, '../static/tabletop/tabletop.js'), 'utf8');
function pageFunction(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}

// The poll as the server sends it: the movement grid is still packed.
const compact = {last_sequence: 7, menu: {manual: true, movement_grid: {rows: [[{x: 1, y: 2}]]}}};
const expanded = {last_sequence: 7, menu: {manual: true, moves: [{destination: {x: 1, y: 2}}]}};

function harness(app) {
  let renders = 0, tokens = 0;
  const ctx = vm.createContext({
    app, JSON, String, Object, Array, Boolean, console,
    reconcileViewerIdentity: () => false,
    renderTokens: () => { tokens++; },
    render: state => { renders++; app.state = state; },
    serverDriving: () => false,
    $: () => null,
  });
  vm.runInContext(pageFunction('renderObservedState'), ctx);
  return {ctx, counts: () => ({renders, tokens})};
}

// The fix: the poll matches the state as received, so an unchanged poll draws nothing.
{
  const app = {state: expanded, menu: expanded.menu, seatStatus: null,
               receivedState: {shown: expanded, received: compact}};
  const {ctx, counts} = harness(app);
  ctx.renderObservedState(compact);
  assert.equal(counts().renders, 0, 'an unchanged compact poll must not rebuild the table');
}

// Without the remembered received form (the base commit), the same poll redrew everything.
{
  const app = {state: expanded, menu: expanded.menu, seatStatus: null};
  const {ctx, counts} = harness(app);
  ctx.renderObservedState(compact);
  assert.equal(counts().renders, 1, 'without the fix a compact poll always redraws (the bug)');
}

// A real change still renders, and a state stored elsewhere falls back to app.state.
{
  const app = {state: expanded, menu: expanded.menu, seatStatus: null,
               receivedState: {shown: expanded, received: compact}};
  const {ctx, counts} = harness(app);
  ctx.renderObservedState({...compact, last_sequence: 8});
  assert.equal(counts().renders, 1, 'a changed poll must still render');
}
{
  const app = {state: expanded, menu: expanded.menu, seatStatus: null,
               receivedState: {shown: {different: true}, received: compact}};
  const {ctx, counts} = harness(app);
  ctx.renderObservedState(compact);
  assert.equal(counts().renders, 1, 'a stale receivedState falls back to app.state, which renders (never skips)');
}
console.log('unchanged compact poll keeps the table: PASS');