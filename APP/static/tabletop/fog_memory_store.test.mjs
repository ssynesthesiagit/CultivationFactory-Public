import test from 'node:test';
import assert from 'node:assert/strict';
import {createFogMemoryStore, indexedMemoryBackend} from './fog_memory_store.js';
import {emptyMemory, memoryKey, recordSeen, saveMemory} from './fog_memory.js';

function quotaStorage(limit) {
  const values = new Map();
  return {values, getItem: key => values.get(key) ?? null, setItem(key, value) {
    const bytes = [...values].filter(([k]) => k !== key).reduce((n, [k, v]) => n + 2 * (k.length + v.length), 0)
      + 2 * (key.length + value.length);
    if (bytes > limit) throw new Error('QuotaExceededError');
    values.set(key, value);
  }};
}
function durableBackend() {
  const values = new Map();
  return {values, get: async key => structuredClone(values.get(key)),
    set: async (key, value) => { values.set(key, structuredClone(value)); }};
}

test('quota-limited storage reload preserves all accumulated captures and the existing saved snapshot', async () => {
  const storage = quotaStorage(5 * 1024 * 1024);
  const backend = durableBackend();
  const key = memoryKey('large-map', 'viewer:on', 80, 60);
  const old = {version: 3, cells: {0: {floor: {swatch: 'sight-time-old'}, tokens: [{id: 'goblin'}], objects: [{id: 'chest'}]}}};
  assert.equal(saveMemory(storage, key, old), true);
  const store = createFogMemoryStore({storage, backend});
  await store.flush(key);
  assert.deepEqual(store.read(key), old, 'legacy snapshot is migrated without changing unseen records');
  const seen = new Uint8Array(4800).fill(1);
  seen[0] = 0;
  const next = recordSeen(store.read(key), seen, index => ({
    // Synthetic unique, detailed 16x16 PNG-sized strings; no image/model server.
    floor: {swatch: `data:image/png;base64,${String(index).padStart(4, '0')}${'abcd'.repeat(400)}`},
    tokens: [{id: `seen-${index}`}], objects: [{id: `object-${index}`}], zones: [], terrain: [],
  }));
  const bytes = 2 * JSON.stringify(next).length;
  assert.ok(bytes > 5 * 1024 * 1024, `aggregate ${bytes} bytes exceeds the legacy quota`);
  assert.equal(saveMemory(storage, key, next), false, 'the former save path fails and leaves an older snapshot');
  assert.deepEqual(JSON.parse(storage.getItem(key)), old);
  store.save(key, next);
  await store.flush(key);
  const reloaded = createFogMemoryStore({storage, backend});
  await reloaded.flush(key);
  assert.deepEqual(reloaded.read(key), next, 'reload retains every floor, token, and object exactly');
  assert.equal(Object.keys(reloaded.read(key).cells).length, 4800);
  await reloaded.flush(memoryKey('other', 'viewer:on', 80, 60));
  assert.deepEqual(reloaded.read(memoryKey('other', 'viewer:on', 80, 60)), emptyMemory());
});

test('loading gates capture and serialized saves cannot replace a newer snapshot with an older one', async () => {
  const backend = durableBackend();
  let release;
  backend.get = () => new Promise(resolve => { release = resolve; });
  const store = createFogMemoryStore({backend});
  store.read('k');
  assert.equal(store.ready('k'), false);
  assert.equal(store.save('k', emptyMemory()), false);
  release({version: 3, cells: {1: {floor: {swatch: 'old-unseen'}}}});
  await store.flush('k');
  const writes = [];
  backend.set = (key, value) => new Promise(resolve => { writes.push({key, value, resolve}); });
  const first = {version: 3, cells: {...store.read('k').cells, 2: {floor: {swatch: 'first'}}}};
  const latest = {version: 3, cells: {...first.cells, 3: {floor: {swatch: 'latest'}}}};
  store.save('k', first);
  store.save('k', latest);
  assert.equal(writes.length, 1);
  writes[0].resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(writes.length, 2);
  assert.deepEqual(writes[1].value, latest);
  writes[1].resolve();
  await store.flush('k');
});

test('durable save failures are reported and preserve the previous complete snapshot; next save retries', async () => {
  const storage = quotaStorage(1024);
  const backend = durableBackend();
  const errors = [];
  const store = createFogMemoryStore({storage, backend, onError: error => errors.push(error)});
  await store.flush('k');
  const old = {version: 3, cells: {0: {floor: {swatch: 'old'}}}};
  store.save('k', old);
  await store.flush('k');
  const write = backend.set;
  backend.set = async () => { throw new Error('QuotaExceededError'); };
  const latest = {version: 3, cells: {...old.cells, 1: {floor: {swatch: 'latest'}}}};
  store.save('k', latest);
  await store.flush('k');
  assert.equal(errors.length, 1);
  assert.deepEqual(backend.values.get('k'), old);
  assert.deepEqual(store.read('k'), latest, 'current tab retains all records');
  backend.set = write;
  store.save('k', latest);
  await store.flush('k');
  assert.deepEqual(backend.values.get('k'), latest);
});

test('IndexedDB save resolves only at commit and rejects an abort after a successful put', async () => {
  let request, tx;
  const db = {transaction() {
    tx = {objectStore: () => ({put: () => ({}), get: () => ({result: {version: 3, cells: {}}})})};
    return tx;
  }};
  const backend = indexedMemoryBackend({open() {
    request = {};
    queueMicrotask(() => { request.result = db; request.onsuccess(); });
    return request;
  }});
  let settled = false;
  const pending = backend.set('k', emptyMemory()).then(() => { settled = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false);
  tx.oncomplete();
  await pending;
  const failed = backend.set('k', emptyMemory());
  await new Promise(resolve => setImmediate(resolve));
  tx.error = new Error('QuotaExceededError');
  tx.onabort();
  await assert.rejects(failed, /QuotaExceededError/);
});

test('a failed database read never overwrites unseen durable records and a later read retries', async () => {
  const backend = durableBackend();
  const saved = {version: 3, cells: {9: {floor: {swatch: 'unseen-durable'}}}};
  backend.values.set('k', saved);
  const get = backend.get;
  backend.get = async () => { throw new Error('temporarily blocked'); };
  const errors = [];
  const store = createFogMemoryStore({backend, onError: error => errors.push(error)});
  await store.flush('k');
  assert.equal(store.ready('k'), false);
  assert.equal(store.save('k', emptyMemory()), false);
  assert.deepEqual(backend.values.get('k'), saved);
  assert.equal(errors.length, 1);
  // Finish the retry initiated by save before enabling recovery.
  await store.flush('k');
  backend.get = get;
  store.read('k');
  await store.flush('k');
  assert.equal(store.ready('k'), true);
  assert.deepEqual(store.read('k'), saved);
});

test('without IndexedDB legacy saving remains available, and a full legacy store reports failure', async () => {
  const storage = quotaStorage(1000);
  const errors = [];
  const store = createFogMemoryStore({storage, backend: indexedMemoryBackend(null), onError: e => errors.push(e)});
  await store.flush('k');
  store.save('k', emptyMemory());
  await store.flush('k');
  assert.deepEqual(JSON.parse(storage.getItem('k')), emptyMemory());
  store.save('k', {version: 3, cells: {0: {floor: {swatch: 'x'.repeat(1000)}}}});
  await store.flush('k');
  assert.equal(errors.length, 1);
  assert.deepEqual(JSON.parse(storage.getItem('k')), emptyMemory(), 'last complete save is retained');
});
