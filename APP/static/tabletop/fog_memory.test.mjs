import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyMemory, ghostCells, loadMemory, memoryKey, recordSeen, saveMemory} from './fog_memory.js';

const WIDTH = 4;
const at = (x, y) => y * WIDTH + x;
const seenOnly = indexes => {
  const seen = new Uint8Array(WIDTH * 4);
  for (const index of indexes) seen[index] = 1;
  return seen;
};
const perceivedFrom = world => index => ({
  tokens: (world.tokens[index] || []).map(id => ({id})),
  objects: (world.objects[index] || []).map(id => ({id})),
});

test('a square seen then unseen keeps the state from when it was last seen', () => {
  const world = {tokens: {[at(1, 1)]: ['goblin']}, objects: {[at(1, 1)]: ['chest']}};
  let memory = recordSeen(emptyMemory(), seenOnly([at(1, 1)]), perceivedFrom(world));

  // The goblin walks away and the chest is opened, but the viewer is looking elsewhere now.
  world.tokens = {};
  world.objects = {[at(1, 1)]: []};
  memory = recordSeen(memory, seenOnly([at(0, 0)]), perceivedFrom(world));

  assert.deepEqual(ghostCells(memory, seenOnly([at(0, 0)])), [at(1, 1)]);
  assert.deepEqual(memory.cells[at(1, 1)].tokens, [{id: 'goblin'}]);
  assert.deepEqual(memory.cells[at(1, 1)].objects, [{id: 'chest'}]);
});

test('a remembered square updates to the real state once it is seen again', () => {
  const world = {tokens: {[at(1, 1)]: ['goblin']}, objects: {}};
  let memory = recordSeen(emptyMemory(), seenOnly([at(1, 1)]), perceivedFrom(world));
  memory = recordSeen(memory, seenOnly([at(0, 0)]), perceivedFrom(world));

  world.tokens = {[at(1, 1)]: ['orc']};
  memory = recordSeen(memory, seenOnly([at(1, 1)]), perceivedFrom(world));

  assert.deepEqual(memory.cells[at(1, 1)].tokens, [{id: 'orc'}]);
  assert.deepEqual(ghostCells(memory, seenOnly([at(1, 1)])), [at(0, 0)], 'the square now in view is not a ghost');
});

test('squares never seen are never remembered', () => {
  const world = {tokens: {[at(3, 3)]: ['dragon']}, objects: {[at(3, 3)]: ['vault']}};
  const memory = recordSeen(emptyMemory(), seenOnly([at(0, 0)]), perceivedFrom(world));

  assert.equal(memory.cells[at(3, 3)], undefined);
  assert.deepEqual(ghostCells(memory, seenOnly([at(0, 0)])), []);
  assert.equal(JSON.stringify(memory).includes('dragon'), false);
  assert.equal(JSON.stringify(memory).includes('vault'), false);
});

test('memory survives a reload through storage and is kept per match and viewer', () => {
  const store = new Map();
  const storage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value)};
  const key = memoryKey('m1', 'viewer-a:own');
  const world = {tokens: {[at(2, 2)]: ['goblin']}, objects: {}};
  saveMemory(storage, key, recordSeen(emptyMemory(), seenOnly([at(2, 2)]), perceivedFrom(world)));

  const reloaded = loadMemory(storage, key);
  assert.deepEqual(reloaded.cells[at(2, 2)].tokens, [{id: 'goblin'}]);
  assert.notEqual(memoryKey('m1', 'viewer-b:own'), key);
  assert.notEqual(memoryKey('m2', 'viewer-a:own'), key);
  assert.deepEqual(loadMemory(storage, memoryKey('m2', 'viewer-a:own')), emptyMemory());
  assert.notEqual(memoryKey('m1', 'viewer-a:own', 30, 20), memoryKey('m1', 'viewer-a:own', 40, 20), 'a resized map starts a fresh memory');
});

test('corrupt or old storage is ignored instead of breaking the table', () => {
  const storage = {getItem: () => '{not json'};
  assert.deepEqual(loadMemory(storage, 'k'), emptyMemory());
  assert.deepEqual(loadMemory({getItem: () => JSON.stringify({version: 0, cells: {}})}, 'k'), emptyMemory());
});
