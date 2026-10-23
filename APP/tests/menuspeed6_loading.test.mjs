import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const start = source.indexOf('async function renderActionBar(');
const render = source.slice(start, source.indexOf('\n}', start) + 2);

test('pending human choices replace action badges with an accessible spinner', async () => {
  const bar = {innerHTML: '', querySelector: () => ({textContent: ''})};
  const bindings = {$: () => bar, app: {menu: null}, presentation: () => ({current_actor_id: 'human'}),
    currentViewer: () => ({ready: true}), actorById: () => ({display_name: 'Wren'}),
    modelOwner: () => null, serverDriving: () => false, isManualActor: () => true, automaticSlot: () => false};
  await Function(...Object.keys(bindings), `${render}; return renderActionBar();`)(...Object.values(bindings));
  assert.match(bar.innerHTML, /Loading your choices…/);
  assert.match(bar.innerHTML, /role="status"/);
  assert.match(bar.innerHTML, /tt-choices-spinner/);
  assert.doesNotMatch(bar.innerHTML, /spent|data-end|disabled/);
});
