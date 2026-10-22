import test from 'node:test';
import assert from 'node:assert/strict';
import {mapPickOptions, mapPickAnswer, promptKey} from '../static/play/play-model.js';

// SQUAREPICK1: a pending map-pick reaction must be answerable from the phone map.
const view = {ready: true, isOwned: id => id === 'actor:me'};
const pending = {method: 'act', request: {candidate_id: 'c1'}, reactions: [], reaction: {
  reaction: 'Cultivate Blossom', context: {reactor_id: 'actor:me', reaction_id: 'r1'},
  choice: {minimum: 1, maximum: 1, map_pick: {cells: [{x: 3, y: 6, z: 0}]}, options: [
    {id: 'opt-a', label: 'Square 4,7', cell: {x: 3, y: 6, z: 0}},
    {id: 'opt-b', label: 'Square 9,9', cell: {x: 9, y: 9, z: 0}}]}}};

test('phone exposes pending map-pick options with their cells', () => {
  const options = mapPickOptions(pending, view);
  assert.deepEqual(options.map(o => o.id), ['opt-a', 'opt-b']);
  assert.deepEqual(options[0].cell, {x: 3, y: 6, z: 0});
});

test('no map-pick surface for a foreign or non-map prompt', () => {
  assert.equal(mapPickOptions(null, view), null);
  assert.equal(mapPickOptions({...pending, reaction: {...pending.reaction, context: {reactor_id: 'actor:them'}}}, view), null);
  assert.equal(mapPickOptions({...pending, reaction: {reaction: 'x', context: {reactor_id: 'actor:me'}, choice: {options: []}}}, view), null);
});

test('a tapped square is transported as the native option id', () => {
  const answer = mapPickAnswer(pending, ['opt-a']);
  assert.deepEqual(answer, {reactor_id: 'actor:me', reaction_id: 'r1', selection: 'USE', option_ids: ['opt-a']});
});

test('selection bounds are enforced on map answers', () => {
  assert.throws(() => mapPickAnswer(pending, []), /Choose 1–1 options/);
  assert.throws(() => mapPickAnswer(pending, ['opt-a', 'opt-b']), /Choose 1–1 options/);
  assert.throws(() => mapPickAnswer(pending, ['nope']), /Choose 1–1 options/);
});

test('prompt key changes when the map-pick request changes', () => {
  assert.notEqual(promptKey(pending), promptKey({...pending, request: {candidate_id: 'c2'}}));
});
