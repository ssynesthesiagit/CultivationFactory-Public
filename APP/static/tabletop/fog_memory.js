// Remembered fog: what a player last SAW on each square, kept per viewer and per match.
//
// A square the viewer can see now is recorded with what was perceived there at that moment (terrain,
// zones, objects and enemy tokens they could see). Doors are not recorded. A square they saw before but cannot see now
// is drawn from that record, greyed out, so things can have changed without the player knowing until
// they look again. Nothing is recorded for squares that were never perceived, so unseen things never leak.
//
// Pure data and legacy storage helpers: fog_memory_store.js persists current
// snapshots in IndexedDB, the board draws them, tabletop.js decides what counts as seen.

// Version 2 added the terrain each square had. Version 3 added each zone's id and owner. Older saves lack these, so they
// are dropped on load rather than read as a change on every remembered square.
export const MEMORY_VERSION = 3;

// The snapshot is JSON-safe: integers, strings and plain nested objects only (no floats, no objects with
// methods). memory: {version, cells: {[index]: {tokens: [...], objects: [...], zones: [...],
//   scenery: string | null, floor: {style, seed, patch} | {swatch: string} | null}}}.
// scenery is sight-time JSON for map trees/decor/walls; objects may carry an art
// string for their arranged face. Both are optional on older version-3 records.
// A record with no `floor` field (saved before that field existed)
// or an unexpected shape there is read as "no floor provenance", the same as an explicit null -- board.js
// never substitutes today's live floor for either, so neither can leak a floor that changed while unseen.
export function emptyMemory() {
  return {version: MEMORY_VERSION, cells: {}};
}

// Keep the remembered copy of every square currently seen, and leave remembered squares alone otherwise.
// `seen` is a Uint8Array (1 = visible now). `perceived(index)` returns the snapshot for that square.
// visibleTokenIds includes perceived creatures even when their anchor square is
// outside the visible-cell mask (large tokens/special senses). validTokenIds is
// the match's complete roster, never the visible subset; it rejects foreign or
// synthetic token records without consulting hidden positions or names.
// rosterNames optionally maps the same roster ids to the {name, label} the viewer's
// roster shows for that creature today (the same fields the recorder stores on a
// fresh square). A remembered token carrying a roster id but another creature's
// name or label is re-identified from it instead of showing letters nobody can
// explain; honest records are left as the same objects, and stored squares keep
// their positions. Absent the option nothing is changed (default-inert).
export function recordSeen(memory, seen, perceived, {visibleTokenIds = [], validTokenIds = null, rosterNames = null} = {}) {
  if (!seen) return memory;
  const cells = {...memory.cells};
  const visible = new Set(visibleTokenIds);
  for (let index = 0; index < seen.length; index += 1) {
    if (seen[index]) {
      cells[index] = perceived(index);
      for (const token of cells[index].tokens || []) if (token.id) visible.add(token.id);
    }
  }
  for (const [index, record] of Object.entries(cells)) {
    const original = record.tokens || [];
    const tokens = original.filter(token =>
      (!validTokenIds || validTokenIds.has(token.id)) && (seen[index] || !visible.has(token.id)))
      .map(token => {
        if (!rosterNames) return token;
        const fresh = rosterNames.get(token.id);
        return fresh && (token.name !== fresh.name || token.label !== fresh.label)
          ? {...token, name: fresh.name, label: fresh.label} : token;
      });
    if (tokens.length !== original.length || tokens.some((token, at) => token !== original[at]))
      cells[index] = {...record, tokens};
  }
  return {version: MEMORY_VERSION, cells};
}

// Which remembered squares are drawn as ghosts: remembered, but not seen right now.
export function ghostCells(memory, seen) {
  const ghosts = [];
  for (const key of Object.keys(memory.cells)) {
    const index = Number(key);
    if (!seen || !seen[index]) ghosts.push(index);
  }
  return ghosts;
}

// Storage key per match, audience and map size, so one fight's memory never leaks into another and a resized
// map never reinterprets old cell indexes as different squares.
export function memoryKey(matchId, audience, width = 0, height = 0) {
  return `tt-fog-memory:${matchId}:${audience}:${width}x${height}`;
}

export function loadMemory(storage, key) {
  try {
    const raw = storage?.getItem(key);
    if (!raw) return emptyMemory();
    const parsed = JSON.parse(raw);
    if (parsed?.version !== MEMORY_VERSION || typeof parsed.cells !== "object" || !parsed.cells) return emptyMemory();
    return parsed;
  } catch (_error) {
    return emptyMemory();
  }
}

export function saveMemory(storage, key, memory) {
  try {
    if (!storage) return false;
    storage.setItem(key, JSON.stringify(memory));
    return true;
  } catch (_error) {
    return false;
  }
}
