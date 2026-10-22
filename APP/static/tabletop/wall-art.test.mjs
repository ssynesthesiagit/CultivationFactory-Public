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

// MAPART2 (owner QA, 4a5521da): round walls drew as a flat tile-pattern disc with a thick edge --
// "no texture, no shading, like an unrendered placeholder" on mountain-pass and ruined-spirit-shrine.
// Every filled circle wall now gets real art: a faceted boulder for a natural look (or none at all,
// the old default), a masonry pillar/well for a built one.
const circle = (look, extra = {}) => ({id: 'c1', shape: 'circle', points: [[5, 5], [6, 5]], filled: true, blocks: 'sight_and_movement', look, ...extra});

test('a filled circle wall always gets real art, never the flat tile-pattern disc', () => {
  for (const look of [null, ...Object.keys(WALL_LOOKS)]) {
    const markup = wallLookMarkup(circle(look));
    assert.doesNotMatch(markup, /NaN|undefined/, `${look}: no bad numbers`);
    assert.doesNotMatch(markup, /fill="url\(#tt-wall-pat-/, `${look}: circles no longer use the flat tile pattern`);
    assert.match(markup, /<g class="tt-wall-look/, `${look}: still a recognisable wall-look group`);
  }
});

test('a circle wall reads as a boulder for a natural look (or none) and a pillar for a built one', () => {
  const boulder = wallLookMarkup(circle(null));
  assert.match(boulder, /class="tt-wall-look tt-wall-look-boulder"/, 'no look at all is still a boulder');
  const cliff = wallLookMarkup(circle('rock_cliff'));
  assert.match(cliff, /class="tt-wall-look tt-wall-look-rock_cliff"/, 'rock_cliff also reads as natural stone, not a pillar');
  const pillar = wallLookMarkup(circle('grey_brick'));
  assert.match(pillar, /class="tt-wall-look tt-wall-look-grey_brick"/, 'a built look is a round masonry pillar');
  assert.ok((pillar.match(/<ellipse/g) || []).length >= 3, 'the pillar is concentric ellipses, several courses');
});

test('circle-wall art varies by seed: two different walls never draw the identical boulder', () => {
  const a = wallLookMarkup({...circle(null), id: 'west-boulder', points: [[5, 5], [6, 5]]});
  const b = wallLookMarkup({...circle(null), id: 'east-boulder', points: [[5, 5], [6, 5]]});
  assert.notEqual(a, b, 'two differently-named boulders of the same size draw different rock facets');
});

// A small square filled wall (a "pillar" standing on the floor, e.g. maple-shrine's shrine-pillar
// squares) gets the same pillar-cap/boulder treatment as a circle instead of the brick-grid fill,
// which is too faint at one square to read as anything but a flat tinted marker.
const squarePillar = (look, extra = {}) => ({id: 'p1', shape: 'rect', points: [[21, 15], [22, 16]], filled: true, blocks: 'sight_and_movement', look, ...extra});

test('a small square filled wall reads as a pillar, not a flat tinted marker square', () => {
  const red = wallLookMarkup(squarePillar('red_palace'));
  assert.doesNotMatch(red, /fill="url\(#tt-wall-pat-/, 'no brick-grid fill at pillar scale');
  assert.match(red, /<ellipse /, 'a built-look square pillar still draws the masonry pillar art');
  const plain = wallLookMarkup(squarePillar(null));
  assert.match(plain, /<path /, 'an unlooked square pillar is a plain boulder');
  // A long, thin wall (not roughly square) keeps the ordinary brick-grid fill.
  const longWall = wallLookMarkup({shape: 'rect', points: [[0, 0], [5, 1]], filled: true, blocks: 'sight_and_movement', look: 'red_palace'});
  assert.match(longWall, /fill="url\(#tt-wall-pat-/, 'a wall run, not a pillar, keeps its tile pattern');
});

// A small square segment that only exists to join two longer wall runs (bandit-camp's wall-2/wall-4,
// ricefield-bamboo-valley's hut corner posts) must keep reading as part of that run, not sprout a
// round pillar where the run turns a corner.
test('a small square segment touching another wall stays a wall run, not a pillar', () => {
  const corner = {id: 'wall-2', shape: 'rect', points: [[16, 25], [17, 26]], filled: true, blocks: 'sight_and_movement', look: 'bamboo_fence'};
  const run = {id: 'wall-7', shape: 'rect', points: [[16, 25], [21, 26]], filled: true, blocks: 'sight_and_movement', look: 'bamboo_fence'};
  const markup = wallLookMarkup(corner, [corner, run]);
  assert.match(markup, /fill="url\(#tt-wall-pat-bamboo_fence/, 'overlaps a sibling wall: stays the ordinary tile fill');
  // The same square, with no touching sibling at all, is a standalone pillar.
  const lone = wallLookMarkup(corner, [corner]);
  assert.doesNotMatch(lone, /fill="url\(#tt-wall-pat-/, 'no touching sibling: reads as a standalone post');
});

// Bandit-camp's and ricefield-bamboo-valley's bamboo-fence huts rendered as a flat green brick grid
// ("reads exactly like a highlighted-path overlay", owner QA) because every look shared one brick
// pattern geometry. bamboo_fence now lays down vertical culms instead.
test('a bamboo-fence filled wall draws vertical culms, not the brick grid', () => {
  const defs = wallPatternDefs();
  const pattern = /<pattern id="tt-wall-pat-bamboo_fence"[^>]*>(.*?)<\/pattern>/.exec(defs)[0];
  assert.match(pattern, /width="4" height="1"/, 'four-square bank avoids repeating every square');
  assert.equal((pattern.match(/<rect/g) || []).length >= 4, true, 'several culm/node rects, not a 2x2 brick grid');
});

// mountain-pass's and ruined-spirit-shrine's stone looks (and the new rock_cliff look) get irregular
// cracked facets instead of the brick grid, so a cliff wall actually reads as rock (owner QA:
// "mountain-pass perimeter is brick ... should be able to read as rock cliff").
test('a natural stone look (ruined_stone, rock_cliff) draws cracked rock facets, not a brick grid', () => {
  for (const look of ['ruined_stone', 'rock_cliff']) {
    const defs = wallPatternDefs();
    const pattern = /<pattern id="tt-wall-pat-([a-z_]+)"[^>]*>(.*?)<\/pattern>/g;
    let body = null;
    for (const m of defs.matchAll(pattern)) if (m[1] === look) { body = m[0]; break; }
    assert.ok(body, `${look}: pattern exists`);
    assert.doesNotMatch(body, /M0 \.125H\.5/, `${look}: not the old brick-grid cross lines`);
    assert.match(body, /<path /, `${look}: irregular cracked facets`);
  }
});
