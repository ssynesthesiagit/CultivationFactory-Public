// Executable DOM regression for the GM-only Refraction scene button (#ttGlassScene).
// It runs the production table render (render -> reconcileViewerIdentity -> renderViewerIdentity ->
// setGlassSceneVisibility) on the real tabletop.html markup. Only the DOM model is a stub (no layout, no CSS);
// the CSS rule that keeps the hidden attribute effective is checked by tests/test_glass_scene_visibility.py.
import test from 'node:test';
import assert from 'node:assert/strict';
import {setGlassSceneVisibility} from '../static/tabletop/glass-scene.js';
import {actor, createTableHarness, IN, OUT} from './viewer_identity_harness.mjs';

const roster = () => [actor('A', OUT), actor('B', IN)];
const scene = h => h.document.getElementById('ttGlassScene');

test('the Refraction scene button starts hidden in the markup, before any identity render', () => {
  const h = createTableHarness({initialize: false, boundIds: ['A'], roster: roster()});
  assert.equal(scene(h).hasAttribute('hidden'), true);
});

test('the Refraction scene button is shown and enabled for the Game Master on the first render', () => {
  const h = createTableHarness({gm: true, roster: roster()});
  assert.equal(h.currentViewer().status, 'gm');
  assert.equal(scene(h).hidden, false);
  assert.equal(scene(h).disabled, false);
});

test('the Refraction scene button stays hidden for a player view on the first render', () => {
  const h = createTableHarness({boundIds: ['A'], roster: roster()});
  assert.equal(h.currentViewer().status, 'player');
  assert.equal(scene(h).hidden, true);
  assert.equal(scene(h).disabled, true);
});

test('the Refraction scene button stays hidden for an unbound observer and a stale identity', () => {
  const unbound = createTableHarness({roster: roster()});
  assert.equal(unbound.currentViewer().status, 'unbound');
  assert.equal(scene(unbound).hidden, true);
  const stale = createTableHarness({boundIds: ['missing'], roster: roster()});
  assert.equal(stale.currentViewer().status, 'stale');
  assert.equal(scene(stale).hidden, true);
});

test('the Refraction scene button follows a change of view: shown after GM binding, hidden after a player binding', () => {
  const h = createTableHarness({boundIds: ['A'], roster: roster()});
  assert.equal(scene(h).hidden, true);
  h.viewerStore.bindGM('match');
  h.reconcileViewerIdentity();
  assert.equal(scene(h).hidden, false);
  h.viewerStore.bindPlayer('match', ['A']);
  h.reconcileViewerIdentity();
  assert.equal(scene(h).hidden, true);
});

test('without a fight loaded the GM still cannot press the Refraction scene button', () => {
  const button = {hidden: true, disabled: true};
  setGlassSceneVisibility(button, 'gm', false);
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, true);
});
