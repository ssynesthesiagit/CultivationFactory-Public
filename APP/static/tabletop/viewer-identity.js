// This screen's view of a fight, independent of the fight's global controller assignments.
// A view ID is a nonsecret presentation handle, never an actor ID or an authentication token.
// The page supplies sessionStorage safely; this module also works with storage disabled.

const VERSION = 1;
const PLAYER_FOG = new Set(['own', 'team', 'selected']);
const MANUAL_MODES = new Set(['MANUAL', 'SUGGESTED', 'MANUAL_AI_BRIDGE']);
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const isActorId = value => typeof value === 'string' && value.length > 0 && value.length <= 240
  && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);
let viewSerial = 0;

export function isValidViewId(value) {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

export function mintViewId(cryptoSource = globalThis.crypto) {
  try {
    const id = cryptoSource?.randomUUID?.();
    if (isValidViewId(id)) return id;
  } catch { /* An opaque, nonsecret handle also works without Web Crypto. */ }
  try {
    const bytes = cryptoSource?.getRandomValues?.(new Uint8Array(16));
    if (bytes) return `view-${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`;
  } catch { /* Private browsing or a restricted context may disable this API. */ }
  return `view-${Date.now().toString(36)}-${(++viewSerial).toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

function actorIds(value) {
  if (!Array.isArray(value) || !value.length || !value.every(isActorId)) return null;
  return [...new Set(value)].sort();
}

function validBinding(value) {
  if (!isObject(value) || value.version !== VERSION || !Array.isArray(value.actor_ids)) return null;
  if (value.role === 'gm' && value.actor_ids.length === 0) return {version: VERSION, role: 'gm', actor_ids: []};
  const ids = value.role === 'player' && actorIds(value.actor_ids);
  return ids ? {version: VERSION, role: 'player', actor_ids: ids} : null;
}

// Current presentation.py always supplies primary_combatant, owner_id and controller.
// Older presentation rows can omit the primary flag; only an ownerless, nonsummon
// row may then be offered. An explicit false or a broken owner link never becomes a fighter.
export function isPrimaryFighter(actor) {
  if (!isObject(actor) || !isActorId(actor.entity_id)) return false;
  if (actor.owner_id != null && actor.owner_id !== '') return false;
  if (actor.summon != null || actor.summon_status != null) return false;
  return actor.primary_combatant === true || !Object.hasOwn(actor, 'primary_combatant');
}

export function createViewerStore({viewId = mintViewId(), storage = null} = {}) {
  if (!isValidViewId(viewId)) throw new TypeError('A player view needs a valid view ID.');
  // Memory is private to this store. Prefer a write here over a stale storage value
  // when setItem fails; a later reload only restores what the browser actually saved.
  const memory = new Map();
  const keyFor = (matchId, kind) => {
    if (typeof matchId !== 'string' || !matchId.length) throw new TypeError('A player view needs a match ID.');
    return `tt-viewer:v${VERSION}:${JSON.stringify([viewId, matchId, kind])}`;
  };
  function readRaw(key) {
    if (!memory.has(key)) {
      let value = null;
      try { value = storage?.getItem?.(key) ?? null; } catch { /* Use this tab's memory. */ }
      memory.set(key, value);
    }
    return memory.get(key);
  }
  function writeRaw(key, value) {
    memory.set(key, value);
    try { storage?.setItem?.(key, value); } catch { /* Keep the explicit choice in this tab. */ }
  }
  function read(matchId) {
    const value = readRaw(keyFor(matchId, 'binding'));
    if (value == null) return null;
    try { return JSON.parse(value); }
    catch { return {version: 0}; } // Corrupt storage is stale and must prompt again.
  }
  function bindPlayer(matchId, selectedIds) {
    const ids = actorIds(selectedIds);
    if (!ids) throw new TypeError('Choose at least one fighter for this screen.');
    const binding = {version: VERSION, role: 'player', actor_ids: ids};
    writeRaw(keyFor(matchId, 'binding'), JSON.stringify(binding));
    writeRaw(keyFor(matchId, 'fog'), JSON.stringify({actor_ids: ids, mode: 'own'}));
    return binding;
  }
  function bindGM(matchId) {
    const binding = {version: VERSION, role: 'gm', actor_ids: []};
    writeRaw(keyFor(matchId, 'binding'), JSON.stringify(binding));
    writeRaw(keyFor(matchId, 'fog'), 'own');
    return binding;
  }
  function readFog(matchId) {
    const binding = validBinding(read(matchId));
    if (binding?.role === 'gm') return 'off';
    if (binding?.role !== 'player') return 'own';
    // A binding and its fog preference need two browser writes. Stamp the latter
    // so a partial quota failure cannot restore a previous fighter's shared view.
    try {
      const saved = JSON.parse(readRaw(keyFor(matchId, 'fog')));
      return isObject(saved) && JSON.stringify(saved.actor_ids) === JSON.stringify(binding.actor_ids)
        && PLAYER_FOG.has(saved.mode) ? saved.mode : 'own';
    } catch { return 'own'; }
  }
  function writeFog(matchId, mode) {
    if (!PLAYER_FOG.has(mode)) throw new TypeError('Choose own, shared, or chosen-token perception.');
    // A fog preference cannot create a player binding or enter/leave the GM role.
    const binding = validBinding(read(matchId));
    if (binding?.role === 'player') {
      writeRaw(keyFor(matchId, 'fog'), JSON.stringify({actor_ids: binding.actor_ids, mode}));
    }
    return readFog(matchId);
  }
  return {viewId, read, bindPlayer, bindGM, readFog, writeFog};
}

// Resolve against the FULL current roster, including inactive and off-map owners.
// Call again after every state/controller refresh. Ownership uses canonical rows by
// ID, so the same predicate accepts playback copies carrying temporary positions.
// Actor activity/presence/position restrict fog or roof audiences in their callers;
// inactive manual owners remain available to the existing fallen-fighter fog fallback.
export function resolveViewerIdentity(binding, roster, seatStatus) {
  const ownedIds = new Set(), teams = new Set();
  const result = {
    status: binding == null ? 'unbound' : 'stale', reason: binding == null ? 'choose-fighters' : 'invalid-binding',
    role: 'player', ready: false, primaryActors: [], ownedIds, teams,
    isOwned: actorOrId => ownedIds.has(typeof actorOrId === 'string' ? actorOrId : actorOrId?.entity_id),
  };
  const chosen = validBinding(binding);
  if (!chosen) return result;
  if (chosen.role === 'gm') return {...result, status: 'gm', reason: null, role: 'gm', ready: true};
  if (!Array.isArray(roster)) return {...result, reason: 'roster-unavailable'};

  const byId = new Map(), ambiguous = new Set();
  for (const actor of roster) {
    if (!isObject(actor) || !isActorId(actor.entity_id)) continue;
    if (byId.has(actor.entity_id)) ambiguous.add(actor.entity_id);
    else byId.set(actor.entity_id, actor);
  }
  const primaries = chosen.actor_ids.map(id => byId.get(id));
  if (chosen.actor_ids.some((id, index) => ambiguous.has(id) || !isPrimaryFighter(primaries[index]))) {
    return {...result, reason: 'fighters-changed'};
  }
  result.status = 'player';
  result.primaryActors = primaries;
  result.reason = 'seats-unavailable';
  // MODEL fighters project MANUAL controllers. Missing seat information cannot
  // distinguish them from people, even when a defeated actor has no model turn.
  if (!isObject(seatStatus) || !isObject(seatStatus.seats)) return result;

  result.ready = true;
  const bound = new Set(chosen.actor_ids);
  function owns(id) {
    const visited = new Set();
    while (isActorId(id) && !visited.has(id) && !ambiguous.has(id)) {
      visited.add(id);
      const actor = byId.get(id);
      if (!actor || !MANUAL_MODES.has(actor.controller)) return false;
      if (Object.hasOwn(seatStatus.seats, id) && seatStatus.seats[id]?.control === 'MODEL') return false;
      if (isPrimaryFighter(actor)) return bound.has(id);
      id = actor.owner_id;
    }
    return false;
  }
  for (const id of byId.keys()) if (owns(id)) ownedIds.add(id);
  for (const actor of primaries) if (ownedIds.has(actor.entity_id)) {
    // The presentation's legacy default is side 0; ownership itself never uses a side.
    const team = Number(actor.team_index ?? 0);
    if (Number.isFinite(team)) teams.add(team);
  }
  result.reason = ownedIds.size ? null : 'no-manual-viewers';
  return result;
}
