import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('current fighter switches to AI in one click and the AI acts immediately', async () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('async function setControl(');
  const end = source.indexOf('\n}', start) + 2;
  assert.ok(start >= 0 && end > start, 'production setControl');
  const actor = {display_name: 'Tabik', primary_combatant: true, controller: 'MANUAL'};
  const calls = [];
  let steps = 0, confirmations = 0, label = '';
  const bindings = {
    app: {busy: false, matchId: 'fight', seatStatus: {seats: {}}},
    actorById: () => actor,
    isManualActor: row => row.controller === 'MANUAL',
    presentation: () => ({current_actor_id: 'fighter'}),
    isModelSeat: () => false,
    api: async (path, options) => {
      calls.push(path);
      actor.controller = options.body.controller_mode;
    },
    enc: encodeURIComponent,
    loadSeats: async () => {},
    toast() {},
    refresh: async () => { label = actor.controller === 'MANUAL' ? 'You' : 'AI'; },
    autoStep: async () => { steps++; },
    window: {confirm: () => { confirmations++; return false; }},
  };
  const setControl = new Function(...Object.keys(bindings), source.slice(start, end)
    + '\nreturn setControl;')(...Object.values(bindings));
  await setControl('fighter', 'LOCAL_AUTO');
  assert.deepEqual(calls, ['/api/combat/matches/fight/controller-mode']);
  assert.equal(confirmations, 0, 'handing off is a single click');
  assert.equal(label, 'AI', 'the refreshed control label reflects the saved mode');
  assert.equal(steps, 1, 'the current turn starts immediately');
  await setControl('fighter', 'MANUAL');
  assert.equal(label, 'You', 'taking control back is reflected by refresh');
  assert.equal(steps, 1, 'switching to Manual does not submit an AI step');
});
