import test from 'node:test';
import assert from 'node:assert/strict';
import {createViewerStore, isPrimaryFighter, isValidViewId, mintViewId, resolveViewerIdentity}
  from '../static/tabletop/viewer-identity.js';

const MATCH = 'match:willow';
const humanSeats = {seats: {}};
const fighter = (id, extra = {}) => ({entity_id: id, display_name: id, primary_combatant: true,
  owner_id: null, controller: 'MANUAL', team_index: 0, active: true, position: {x: 4, y: 4}, ...extra});
const summon = (id, ownerId, extra = {}) => fighter(id, {primary_combatant: false, owner_id: ownerId,
  summon_status: 'present', ...extra});
const binding = (...ids) => ({version: 1, role: 'player', actor_ids: ids});
const owned = resolved => [...resolved.ownedIds].sort();

function browserStorage(initial = []) {
  const values = new Map(initial);
  return {values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
}

test('independent browser contexts bind different fighters despite the same URL handle', () => {
  const a = createViewerStore({viewId: 'shared-link', storage: browserStorage()});
  const b = createViewerStore({viewId: 'shared-link', storage: browserStorage()});
  a.bindPlayer(MATCH, ['A']);
  assert.equal(b.read(MATCH), null, 'a copied link carries no actor binding');
  b.bindPlayer(MATCH, ['B']);
  const roster = [fighter('A'), fighter('B')];
  assert.deepEqual(owned(resolveViewerIdentity(a.read(MATCH), roster, humanSeats)), ['A']);
  assert.deepEqual(owned(resolveViewerIdentity(b.read(MATCH), roster, humanSeats)), ['B']);
});

test('separate handles remain independent in the same profile and restore only their own match', () => {
  const storage = browserStorage();
  const a = createViewerStore({viewId: 'view-A', storage});
  const b = createViewerStore({viewId: 'view-B', storage});
  a.bindPlayer(MATCH, ['A']); a.writeFog(MATCH, 'team');
  b.bindPlayer(MATCH, ['B']); b.writeFog(MATCH, 'selected');
  const reload = createViewerStore({viewId: 'view-A', storage});
  assert.deepEqual(reload.read(MATCH), binding('A'));
  assert.equal(reload.readFog(MATCH), 'team');
  assert.deepEqual(b.read(MATCH), binding('B'));
  assert.equal(b.readFog(MATCH), 'selected');
  assert.equal(reload.read('different-match'), null);
  assert.equal(reload.readFog('different-match'), 'own');
  const another = createViewerStore({viewId: mintViewId(), storage});
  assert.equal(another.read(MATCH), null, 'a new view starts unbound even with cloned tab storage');
});

test('storage absent or throwing keeps choices in this store and cannot leak them to another', () => {
  for (const storage of [null, {}, {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }}]) {
    const a = createViewerStore({viewId: 'offline', storage});
    assert.equal(a.read(MATCH), null);
    a.bindPlayer(MATCH, ['B', 'A', 'B']);
    a.writeFog(MATCH, 'selected');
    assert.deepEqual(a.read(MATCH), binding('A', 'B'));
    assert.equal(a.readFog(MATCH), 'selected');
    const b = createViewerStore({viewId: 'offline', storage});
    assert.equal(b.read(MATCH), null);
    assert.equal(b.readFog(MATCH), 'own');
  }
});

test('a failed write never resurrects the previously saved binding or exposes mutable store state', () => {
  const storage = browserStorage();
  createViewerStore({viewId: 'limited', storage}).bindPlayer(MATCH, ['A']);
  const view = createViewerStore({viewId: 'limited', storage});
  storage.setItem = () => { throw new Error('quota'); };
  const returned = view.bindPlayer(MATCH, ['B']); returned.actor_ids.push('C');
  const read = view.read(MATCH); read.actor_ids.push('D');
  assert.deepEqual(view.read(MATCH), binding('B'));
  assert.deepEqual(createViewerStore({viewId: 'limited', storage}).read(MATCH), binding('A'),
    'only successfully persisted state can survive reload');
});

test('a partial storage write cannot transfer a former fighter\'s fog preference to a new binding', () => {
  const storage = browserStorage();
  const view = createViewerStore({viewId: 'partial-quota', storage});
  view.bindPlayer(MATCH, ['A']); view.writeFog(MATCH, 'team');
  const setItem = storage.setItem;
  storage.setItem = (key, value) => {
    if (key.endsWith(',"fog"]')) throw new Error('quota');
    setItem(key, value);
  };
  view.bindPlayer(MATCH, ['B']);
  assert.equal(view.readFog(MATCH), 'own');
  const reload = createViewerStore({viewId: 'partial-quota', storage});
  assert.deepEqual(reload.read(MATCH), binding('B'));
  assert.equal(reload.readFog(MATCH), 'own');
});

test('fog cannot enter GM or create a binding, and an explicit role change resets player perception', () => {
  const storage = browserStorage([['tt-fog', 'off']]);
  const view = createViewerStore({viewId: 'roles', storage});
  assert.equal(view.readFog(MATCH), 'own', 'legacy origin-wide off is ignored');
  assert.equal(view.writeFog(MATCH, 'selected'), 'own');
  assert.equal(view.read(MATCH), null);
  assert.throws(() => view.writeFog(MATCH, 'off'), TypeError);
  view.bindPlayer(MATCH, ['A']); view.writeFog(MATCH, 'team');
  const gm = view.bindGM(MATCH);
  assert.deepEqual(gm, {version: 1, role: 'gm', actor_ids: []});
  assert.equal(view.readFog(MATCH), 'off');
  assert.equal(view.writeFog(MATCH, 'own'), 'off');
  assert.equal(view.read(MATCH).role, 'gm');
  assert.equal(resolveViewerIdentity(gm, null, null).status, 'gm');
  view.bindPlayer(MATCH, ['B']);
  assert.equal(view.readFog(MATCH), 'own');
});

test('unbound, malformed, empty, and stale bindings have no owned creatures or allied teams', () => {
  const roster = [fighter('A'), fighter('B')];
  for (const saved of [null, {}, binding(), binding('missing'), binding('A', 'missing'),
    {...binding('A'), version: 2}, {...binding('A'), role: 'off'}, {version: 1, role: 'gm', actor_ids: ['A']}]) {
    const result = resolveViewerIdentity(saved, roster, humanSeats);
    assert.equal(result.ready, false);
    assert.equal(result.role, 'player');
    assert.deepEqual(owned(result), []);
    assert.deepEqual([...result.teams], []);
    assert.equal(result.isOwned('A'), false);
  }
  assert.equal(resolveViewerIdentity(null, roster, humanSeats).status, 'unbound');
  assert.equal(resolveViewerIdentity(binding('A', 'missing'), roster, humanSeats).reason, 'fighters-changed');
});

test('corrupt session data stays stale and a malformed fog preference falls back to own', () => {
  const storage = browserStorage();
  const view = createViewerStore({viewId: 'corrupt', storage});
  view.bindPlayer(MATCH, ['A']); view.writeFog(MATCH, 'team');
  for (const key of storage.values.keys()) if (key.endsWith(',"fog"]')) storage.values.set(key, 'off');
  const reload = createViewerStore({viewId: 'corrupt', storage});
  assert.equal(reload.readFog(MATCH), 'own');
  for (const key of storage.values.keys()) if (key.endsWith(',"binding"]')) storage.values.set(key, '{');
  const broken = createViewerStore({viewId: 'corrupt', storage});
  assert.equal(resolveViewerIdentity(broken.read(MATCH), [fighter('A')], humanSeats).status, 'stale');
  assert.equal(broken.readFog(MATCH), 'own');
});

test('primary selection is explicit, with only a bounded legacy ownerless fallback', () => {
  const legacy = fighter('legacy'); delete legacy.primary_combatant;
  const absentSummon = summon('child', 'A'); delete absentSummon.primary_combatant;
  const falsePrimary = fighter('not-primary', {primary_combatant: false});
  assert.equal(isPrimaryFighter(legacy), true);
  assert.equal(isPrimaryFighter(fighter('A')), true);
  for (const row of [absentSummon, falsePrimary, fighter('wrong', {owner_id: 'A'}),
    fighter('wrong', {summon_status: 'waiting'}), null]) assert.equal(isPrimaryFighter(row), false);
  assert.deepEqual(owned(resolveViewerIdentity(binding('legacy'), [legacy], humanSeats)), ['legacy']);
  assert.equal(resolveViewerIdentity(binding('not-primary'), [falsePrimary], humanSeats).status, 'stale');
  assert.equal(resolveViewerIdentity(binding('child'), [fighter('A'), absentSummon], humanSeats).status, 'stale');
});

test('a player on either side owns only their selected primaries; shared teams follow all bound sides', () => {
  const roster = [fighter('A'), fighter('B'), fighter('C', {team_index: 2})];
  const b = resolveViewerIdentity(binding('B'), roster, humanSeats);
  assert.deepEqual(owned(b), ['B']);
  const mixed = resolveViewerIdentity(binding('A', 'C'), roster, humanSeats);
  assert.deepEqual(owned(mixed), ['A', 'C']);
  assert.deepEqual([...mixed.teams], [0, 2]);
  assert.equal(mixed.isOwned({...roster[2], position: {x: 20, y: 15}}), true, 'playback copies use canonical identity');
});

test('summons follow multihop owners, later arrivals, and off-map ancestors without changing the binding', () => {
  const primary = fighter('A'), child = summon('child', 'A'), late = summon('late', 'child');
  const roster = [primary, child];
  assert.deepEqual(owned(resolveViewerIdentity(binding('A'), roster, humanSeats)), ['A', 'child']);
  roster.push(late);
  assert.deepEqual(owned(resolveViewerIdentity(binding('A'), roster, humanSeats)), ['A', 'child', 'late']);
  child.active = false; child.summon_status = 'dismissed';
  assert.deepEqual(owned(resolveViewerIdentity(binding('A'), roster, humanSeats)), ['A', 'child', 'late'],
    'ownership is retained; each audience separately filters activity and presence');
});

test('missing, cyclic, and ambiguous owner chains fail closed without discarding an unrelated valid fighter', () => {
  const roster = [fighter('A'), summon('orphan', 'absent'), summon('self', 'self'),
    summon('cycle1', 'cycle2'), summon('cycle2', 'cycle1'),
    summon('duplicate', 'A'), summon('duplicate', 'A'), summon('ambiguous-child', 'duplicate')];
  const result = resolveViewerIdentity(binding('A'), roster, humanSeats);
  assert.equal(result.status, 'player');
  assert.deepEqual(owned(result), ['A']);
  assert.equal(resolveViewerIdentity(binding('A'), [...roster, fighter('A')], humanSeats).status, 'stale',
    'an ambiguous selected fighter invalidates the complete view');
});

test('unknown seat state is closed before first render and can become ready on a later read', () => {
  const roster = [fighter('A'), summon('child', 'A')];
  for (const seats of [null, undefined, {}, {seats: null}, {seats: []}]) {
    const result = resolveViewerIdentity(binding('A'), roster, seats);
    assert.equal(result.status, 'player');
    assert.equal(result.ready, false);
    assert.equal(result.reason, 'seats-unavailable');
    assert.deepEqual(result.primaryActors, [roster[0]]);
    assert.deepEqual(owned(result), []);
  }
  assert.equal(resolveViewerIdentity(binding('A'), roster, humanSeats).ready, true);
});

test('controller and MODEL transitions suppress eligibility while keeping the selected binding intact', () => {
  const store = createViewerStore({viewId: 'controller'});
  store.bindPlayer(MATCH, ['A']);
  const primary = fighter('A', {active: false});
  const child = summon('child', 'A');
  const roster = [primary, child];
  const resolve = seats => resolveViewerIdentity(store.read(MATCH), roster, seats);
  assert.deepEqual(owned(resolve(humanSeats)), ['A', 'child'], 'a down manual owner supports fallen-view fallback');
  assert.deepEqual(owned(resolve({seats: {A: {control: 'MODEL'}}})), [], 'down model owner never enables ally fallback');
  assert.deepEqual(owned(resolve({seats: {child: {control: 'MODEL'}}})), ['A']);
  primary.controller = 'LOCAL_AUTO';
  assert.deepEqual(owned(resolve(humanSeats)), []);
  assert.deepEqual(store.read(MATCH), binding('A'));
  primary.controller = 'SUGGESTED'; child.controller = 'MANUAL_AI_BRIDGE';
  assert.deepEqual(owned(resolve(humanSeats)), ['A', 'child']);
  child.controller = 'LOCAL_AUTO';
  assert.deepEqual(owned(resolve(humanSeats)), ['A']);
});

test('view and match keys cannot collide and actor IDs never determine URL handles', () => {
  const storage = browserStorage();
  const a = createViewerStore({viewId: 'a', storage});
  const b = createViewerStore({viewId: 'a-b', storage});
  a.bindPlayer('b-c', ['actor:factory.A']); b.bindPlayer('c', ['actor:factory.B']);
  assert.deepEqual(a.read('b-c'), binding('actor:factory.A'));
  assert.deepEqual(b.read('c'), binding('actor:factory.B'));
  assert.equal(isValidViewId('actor:factory.A'), false);
  assert.equal(isValidViewId('../other?actor=A'), false);
  assert.throws(() => createViewerStore({viewId: ''}), TypeError);
  assert.throws(() => a.bindPlayer(MATCH, []), TypeError);
  assert.throws(() => a.bindPlayer(MATCH, [' A ']), TypeError);
  const first = mintViewId(null), second = mintViewId(null);
  assert.equal(isValidViewId(first), true); assert.equal(isValidViewId(second), true);
  assert.notEqual(first, second);
  assert.equal(mintViewId({randomUUID: () => 'explicit-view'}), 'explicit-view');
  assert.equal(isValidViewId(mintViewId({randomUUID() { throw new Error('blocked'); }})), true);
});
