// Phase 6 (owner 2026-10-08: different walls, Ancient China and cultivation): every wall look draws along its line at
// the wall thickness, keeps flush ends and butt-cut door joins, fills blocks with its own tiles, and a wall without a look
// is left to the original drawing.
import test from 'node:test';
import assert from 'node:assert/strict';
import {WALL_LOOKS, wallLook, wallLookMarkup, wallPatternDefs} from './wall-art.js';

const line = (look, extra = {}) => ({shape: 'line', points: [[1, 1], [4, 1], [4, 3]], filled: false, blocks: 'sight_and_movement', look, ...extra});

test('a wall without a look (or with an unknown one) keeps the original drawing', () => {
  assert.equal(wallLook({shape: 'line', points: [[0, 0], [1, 0]]}), null);
  assert.equal(wallLookMarkup({shape: 'line', points: [[0, 0], [1, 0]]}), null);
  assert.equal(wallLookMarkup(line('pagoda')), null);
});

test('every look draws its layers along the whole line: square ends, mitred corners, butt-cut at a door', () => {
  assert.ok(Object.keys(WALL_LOOKS).length >= 10);
  for (const look of Object.keys(WALL_LOOKS)) {
    const markup = wallLookMarkup(line(look));
    assert.match(markup, new RegExp(`data-wall-look="${look}"`));
    const layers = markup.match(/<polyline /g).length;
    assert.ok(layers >= 3, `${look}: ${layers} layers`);
    assert.equal((markup.match(/points="1,1 4,1 4,3"/g) || []).length, layers, `${look}: every layer follows the corner`);
    assert.match(markup, /stroke-linecap="square"/, `${look}: flush square ends`);
    assert.doesNotMatch(markup, /NaN|undefined/);
    const widths = [...markup.matchAll(/stroke-width="([\d.]+)"/g)].map(m => Number(m[1]));
    assert.ok(widths.some(w => Math.abs(w - 0.22) < 0.07), `${look}: drawn at the wall thickness`);
    const joined = wallLookMarkup(line(look, {door_join: true}));
    assert.doesNotMatch(joined, /stroke-linecap="square"/, `${look}: a wall cut by a door ends butt-on to the jamb`);
  }
});

test('filled blocks and outlines use the look; sight-only walls are drawn see-through', () => {
  for (const look of Object.keys(WALL_LOOKS)) {
    const block = wallLookMarkup({shape: 'rect', points: [[1, 1], [2, 3]], filled: true, blocks: 'sight_and_movement', look});
    assert.match(block, new RegExp(`fill="url\\(#tt-wall-pat-${look}-v\\)"`));
    assert.match(wallPatternDefs(), new RegExp(`id="tt-wall-pat-${look}"`));
    const ring = wallLookMarkup({shape: 'circle', points: [[3, 3], [5, 3]], filled: false, blocks: 'sight_and_movement', look});
    assert.match(ring, /<circle cx="3" cy="3" r="2"/);
  }
  assert.match(wallLookMarkup(line('timber_lattice', {blocks: 'sight'})), /opacity="0.85"/);
  const ids = [...wallPatternDefs().matchAll(/id="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length);
});
