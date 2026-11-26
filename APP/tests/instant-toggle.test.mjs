import test from 'node:test';
import assert from 'node:assert/strict';
import {InstantToggles} from '../static/tabletop/instant-toggle.js';
import {ApiError} from '../static/tabletop/api.js';

export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

export function setup() {
  const menu = {actor_id: 'a', state_version: 1, decision_id: 'd1', composition: {},
    actions: [{source_definition_id: 'toggle', economy: 'NONE', stores_setting: true, options: [{candidate_id: 'c1', label: 'Toggle'}]}]};
  const app = {matchId: 'fight', menu, state: {menu, button_states: {a: {'act:toggle': {active: false}}}}};
  const draws = [], reasons = [];
  const render = (state, options) => { app.state = state; app.menu = state.menu; draws.push(options); };
  return {app, draws, reasons, render, toast: reason => reasons.push(reason)};
}

test('flips before transport settles and retains the bar', async () => {
  const env = setup(), answer = deferred(), queue = new InstantToggles();
  const result = queue.run({...env, candidateId: 'c1', execute: () => answer.promise});
  assert.equal(env.app.state.button_states.a['act:toggle'].active, true);
  assert.deepEqual(env.draws, [{keepBar: true}]);
  answer.resolve(true);
  assert.equal(await result, true);
});

test('refusal restores selection and shows the exact server reason', async () => {
  const env = setup(), answer = deferred();
  const result = new InstantToggles().run({...env, candidateId: 'c1', execute: () => answer.promise});
  answer.reject(new Error('Not enough Qi.'));
  assert.equal(await result, false);
  assert.equal(env.app.state.button_states.a['act:toggle'].active, false);
  assert.deepEqual(env.reasons, ['Not enough Qi.']);
});

test('second commit waits and binds the refreshed candidate', async () => {
  const env = setup(), answer = deferred(), queue = new InstantToggles(), sent = [];
  const execute = async id => {
    sent.push(id);
    if (sent.length === 1) {
      await answer.promise;
      env.app.state.menu = {...env.app.state.menu, state_version: 2, actions: [
        {...env.app.menu.actions[0], options: [{candidate_id: 'c2', label: 'Toggle'}]}]};
    }
    return true;
  };
  const first = queue.run({...env, candidateId: 'c1', execute});
  const second = queue.run({...env, candidateId: 'c1', execute});
  assert.deepEqual(sent, ['c1']);
  answer.resolve();
  await Promise.all([first, second]);
  assert.deepEqual(sent, ['c1', 'c2']);
});

test('queued click cannot cross fights', async () => {
  const env = setup(), answer = deferred(), queue = new InstantToggles();
  const first = queue.run({...env, candidateId: 'c1', execute: () => answer.promise});
  const second = queue.run({...env, candidateId: 'c1', execute: () => assert.fail('old fight submitted')});
  env.app.matchId = 'another';
  answer.resolve(true);
  await first;
  assert.equal(await second, false);
});

test('an ApiError toasts its player-facing message, not the raw diagnostic', async () => {
  const env = setup();
  const error = new ApiError('decision_id d1 stale: state_version 1 != 2', 'STALE_DECISION', 409);
  assert.notEqual(error.message, error.diagnosticMessage);
  assert.equal(await new InstantToggles().run({...env, candidateId: 'c1', execute: async () => { throw error; }}), false);
  assert.deepEqual(env.reasons, [error.message]);
});
