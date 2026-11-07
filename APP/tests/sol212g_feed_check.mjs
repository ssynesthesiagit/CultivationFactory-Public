// Run by pytest with real TabletopService journal feed on stdin; no browser.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mapObjectFeed} from '../static/tabletop/feed-presentation.js';
const rows = JSON.parse(readFileSync(0, 'utf8'));
const original = JSON.stringify(rows);
const placements = rows.filter(row => row.event_type === 'OBJECT_UPDATED'
  && row.source_definition_id === 'system:battlefield.object' && !row.actor_id);
assert.ok(placements.length > 1);
const compact = mapObjectFeed(rows);
assert.equal(JSON.stringify(rows), original, 'presentation never mutates journal rows');
assert.equal(mapObjectFeed(rows, true), rows, 'All events preserves every individual record');
assert.equal(compact.length, rows.length - placements.length + 1);
const summary = compact.find(row => row.hover);
assert.ok(summary.summary.startsWith('Breakable here: '));
for (const row of placements) assert.ok(summary.hover.includes(row.summary));
const expected = new Map();
for (const row of placements) {
  const obj = row.raw.payload.object;
  const name = obj.component.name.toLowerCase();
  const key = JSON.stringify([name, obj.ac, obj.maximum_hp]);
  expected.set(key, (expected.get(key) || 0) + 1);
}
for (const [key, count] of expected) {
  const [name, ac, hp] = JSON.parse(key);
  const label = count === 1 || name.endsWith('s') ? name
    : name.endsWith('shelf') ? name.slice(0, -1) + 'ves' : name + 's';
  assert.ok(summary.summary.includes(`${count} ${label} (AC ${ac}, ${hp} HP)`));
}
const sample = placements[0];
for (const [singular, plural] of [['stone bench', 'stone benches'], ['sutra shelf', 'sutra shelves'], ['supply box', 'supply boxes']]) {
  const row = {...sample, raw: {payload: {object: {...sample.raw.payload.object, component: {name: singular}}}}};
  assert.ok(mapObjectFeed([row, row])[0].summary.includes(`2 ${plural} (AC `));
}
for (const change of [{actor_id: 'fighter'}, {source_definition_id: 'ability:new'},
  {raw: {payload: {...sample.raw.payload, damage: {taken: 3}}}}]) {
  const changed = {...sample, ...change};
  assert.equal(mapObjectFeed([changed])[0], changed, 'actions/damage are never grouped');
}
// Execute the shipped appendFeed function, including checkbox filtering and hover.
const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const start = source.indexOf('function appendFeed(rows)');
const code = source.slice(start, source.indexOf('\nfunction appendTableLine', start));
const feed = {children: [], appendChild(item) { this.children.push(item); }};
const checkbox = {checked: false};
const document = {createElement: () => ({dataset: {}, style: {}, addEventListener() {}})};
const append = new Function('$', 'document', 'NOISE', 'feedClass', 'settleFeed', 'mapObjectFeed',
  code + '; return appendFeed;')(id => id === '#ttFeed' ? feed : checkbox,
    document, new Set(), () => '', () => {}, mapObjectFeed);
append(rows);
assert.equal(feed.children.length, compact.length);
assert.ok(feed.children.some(item => item.title === summary.hover));
checkbox.checked = true;
feed.children = [];
append(rows);
assert.equal(feed.children.length, rows.length);
assert.equal(feed.children.filter(item => item.dataset.type === 'OBJECT_UPDATED').length, placements.length);
console.log('real table feed: grouping, hover, All events and immutable rows PASS');
