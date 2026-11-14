// Durable last-seen snapshots. IndexedDB has a separate, substantially larger
// quota than localStorage; captures are never trimmed or reconstructed from live
// ground. The old localStorage entry remains available for migration/recovery.
import {emptyMemory, loadMemory, saveMemory, MEMORY_VERSION} from './fog_memory.js';

export function indexedMemoryBackend(indexedDB) {
  let opening;
  function open() {
    if (!opening) opening = new Promise((resolve, reject) => {
      if (!indexedDB) { reject(new Error('IndexedDB unavailable')); return; }
      let failed = false;
      const request = indexedDB.open('tt-fog-memory', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('snapshots');
      request.onerror = () => { failed = true; reject(request.error); };
      request.onblocked = () => { failed = true; reject(new Error('Fog memory database is blocked')); };
      request.onsuccess = () => {
        const db = request.result;
        if (failed) { db.close(); return; }
        db.onversionchange = () => { db.close(); opening = undefined; };
        resolve(db);
      };
    }).catch(error => { opening = undefined; throw error; });
    return opening;
  }
  async function transaction(key, value, write) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('snapshots', write ? 'readwrite' : 'readonly');
      const store = tx.objectStore('snapshots');
      const request = write ? store.put(value, key) : store.get(key);
      // A successful put request is not a committed transaction (quota failures
      // can abort afterwards). Only oncomplete acknowledges a durable save.
      tx.oncomplete = () => resolve(write ? undefined : request.result);
      tx.onabort = () => reject(tx.error || new Error('Fog memory transaction aborted'));
      tx.onerror = () => {}; // onabort reports the final transaction failure.
    });
  }
  return {supported: Boolean(indexedDB), get: key => transaction(key, undefined, false), set: (key, value) => transaction(key, value, true)};
}

// Synchronous render-facing cache over asynchronous persistence. read() starts
// loading once; ready() gates sight-time recording so a reload cannot overwrite
// unseen saved cells with a partial snapshot. onReady requests a fresh render.
// Writes are serialized/coalesced per key; flush() is useful for offline checks.
export function createFogMemoryStore({storage, backend, onReady = () => {}, onError = () => {}}) {
  const entries = new Map();
  function entry(key) {
    if (!entries.has(key)) {
      const row = {memory: emptyMemory(), ready: false, pending: null, writing: null, warned: false};
      entries.set(key, row);
    }
    const row = entries.get(key);
    if (!row.ready && !row.loading) {
      row.loading = (async () => {
        try {
          const saved = await backend.get(key);
          row.memory = saved?.version === MEMORY_VERSION && saved.cells && typeof saved.cells === 'object'
            ? saved : loadMemory(storage, key);
        } catch (error) {
          row.memory = loadMemory(storage, key);
          // Only browsers without IndexedDB use legacy storage. A transient
          // database error must not create a newer local save hidden behind an
          // older database snapshot on the next reload.
          row.fallback = backend.supported === false;
          if (!row.fallback) {
            warn(row, error);
            return; // Cannot overwrite a durable record we failed to read.
          }
        }
        row.ready = true;
        onReady(key);
      })().finally(() => { row.loading = null; });
    }
    return entries.get(key);
  }
  function warn(row, error) {
    if (!row.warned) { row.warned = true; onError(error); }
  }
  function drain(key, row) {
    if (row.writing) return row.writing;
    row.writing = (async () => {
      while (row.pending) {
        const snapshot = row.pending;
        row.pending = null;
        try {
          if (row.fallback) {
            if (!saveMemory(storage, key, snapshot)) throw new Error('Fog memory storage unavailable or full');
          } else await backend.set(key, snapshot);
          row.warned = false;
        } catch (error) { warn(row, error); }
      }
    })().finally(() => {
      row.writing = null;
      if (row.pending) drain(key, row);
    });
    return row.writing;
  }
  return {
    read: key => entry(key).memory,
    ready: key => entries.get(key)?.ready === true,
    save(key, memory) {
      const row = entry(key);
      if (!row.ready) return false;
      row.memory = memory;
      row.pending = memory;
      drain(key, row);
      return true;
    },
    async flush(key) {
      const row = entry(key);
      await row.loading;
      while (row.writing) await row.writing;
    },
  };
}
