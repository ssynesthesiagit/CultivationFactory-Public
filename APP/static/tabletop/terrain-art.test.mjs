import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {TERRAIN_LOOKS, terrainCellMarkup, terrainLook, terrainPresentation, terrainTooltip} from './terrain-art.js';
import {ruleTerrainEntriesAt, ruleTerrainTransform} from './board.js';

const types = ['DIFFICULT', 'SIMPLE_COVER', 'QI_HAZARD'];
const hasStrokeDeclaration = rule => /stroke(?:-width)?\s*:/.test(rule);

test('border assertion recognizes ordinary SVG stroke declarations', () => {
  assert.equal(hasStrokeDeclaration('stroke: red'), true);
  assert.equal(hasStrokeDeclaration('stroke-width: 1.92'), true);
  assert.equal(hasStrokeDeclaration('fill: none'), false);
});

test('each rule terrain type paints natural art without a rules frame, hatch, or label by default', () => {
  for (const type of types) {
    const presentation = terrainPresentation(type);
    const markup = terrainCellMarkup(type, terrainLook({type}, 'mountain'));
    assert.deepEqual([presentation.edge, presentation.hatch, presentation.label], [false, false, false]);
    assert.match(markup, /<g class="tt-rule-terrain/);
    assert.doesNotMatch(markup, /tt-cell-|tt-zone-(?:outline|halo|hatch|label)|<rect/);
  }
});

test('the rules overlay marks rules squares without restoring the removed border grid', () => {
  for (const type of types) {
    const presentation = terrainPresentation(type, true);
    const markup = terrainCellMarkup(type, 'stones', true);
    assert.deepEqual([presentation.edge, presentation.hatch, presentation.label], [true, type === 'DIFFICULT', false]);
    assert.match(markup, new RegExp(`class="tt-cell-${type === 'SIMPLE_COVER' ? 'cover' : type === 'QI_HAZARD' ? 'hazard' : 'difficult'}"`));
    assert.match(markup, /<rect x="0" y="0" width="64" height="64"/);
  }
  const css = readFileSync(new URL('./tabletop.css', import.meta.url), 'utf8');
  for (const cls of ['cover', 'hazard', 'difficult']) {
    const rule = new RegExp(`\\.tt-cell-${cls}\\s*\\{([^}]*)`).exec(css)?.[1] || '';
    assert.equal(hasStrokeDeclaration(rule), false, `.tt-cell-${cls} remains borderless`);
  }
  assert.equal(ruleTerrainTransform(6, 2), 'translate(6 2) scale(0.015625)');
});

test('the loaded Sect Trial Platform board keeps every overlapping terrain rule for hover', () => {
  const map = JSON.parse(readFileSync(new URL('../../combat/maps/builtin-sect-trial-platform.json', import.meta.url), 'utf8'));
  const terrain = [...map.terrain, {type: 'DIFFICULT', cells: [[6, 2]]}];
  assert.deepEqual(ruleTerrainEntriesAt(terrain, 6, 2, map.background?.style).map(entry => entry.type), ['SIMPLE_COVER', 'DIFFICULT']);
});

test('all built-in map rule terrain entries declare a supported look without changing their rules', () => {
  const names = ['bamboo-forest-ravine', 'mist-courtyard', 'mountain-pass', 'pillar-arena', 'ruined-spirit-shrine', 'sect-trial-platform'];
  for (const name of names) {
    const map = JSON.parse(readFileSync(new URL(`../../combat/maps/builtin-${name}.json`, import.meta.url), 'utf8'));
    for (const row of map.terrain) {
      assert.ok(TERRAIN_LOOKS.includes(row.look), `${name}: unsupported or missing ${row.type} look`);
      assert.ok(types.includes(row.type), `${name}: unknown rule terrain type ${row.type}`);
      assert.ok(Array.isArray(row.cells) && row.cells.length > 0);
    }
  }
});

test('floor materials choose sensible default art for each rules terrain type', () => {
  assert.equal(terrainLook({type: 'DIFFICULT'}, 'mountain'), 'scree');
  assert.equal(terrainLook({type: 'DIFFICULT'}, 'bamboo'), 'roots');
  assert.equal(terrainLook({type: 'SIMPLE_COVER'}, 'shrine'), 'pillar_rubble');
  assert.equal(terrainLook({type: 'SIMPLE_COVER'}, 'pillar'), 'statue_plinth');
});

test('terrain hover explains movement, cover, and hazard rules in player language', () => {
  assert.match(terrainTooltip('DIFFICULT').line, /each foot of movement.*one extra foot/i);
  assert.match(terrainTooltip('SIMPLE_COVER').line, /creature protected.*\+2 AC/i);
  assert.match(terrainTooltip('QI_HAZARD').line, /trigger and save rules/i);
});

// MAPART1 (owner playtest 2026-10-13): a big block of one look (the fortress wall's rubble field) must
// not draw the exact same icon on every square -- board.js hands each square its own seed from a hash
// of its x,y, so a run of neighbouring cells should get visibly different markup.
test('a big field of one look never repeats the same drawing square to square', () => {
  // the same per-cell seed formula board.js uses, over a 10x10 run the size of a real rubble field
  const seedAt = (x, y) => 1 + Math.abs((x * 73856093) ^ (y * 19349663)) % 997;
  for (const look of ['rubble', 'scree', 'roots', 'boulder', 'stones', 'low_wall', 'bamboo_clump', 'mangrove_roots',
    'pillar_rubble', 'broken_tiles', 'statue_plinth', 'lantern', 'loose_gravel']) {
    const seeds = new Set(), drawings = new Set();
    for (let x = 0; x < 10; x += 1) for (let y = 0; y < 10; y += 1) {
      seeds.add(seedAt(x, y));
      drawings.add(terrainCellMarkup('DIFFICULT', look, false, seedAt(x, y)));
    }
    // Two squares that land on the same hashed seed may legitimately share a drawing; the bug was every
    // square sharing one, so what matters is that distinct seeds keep drawing distinct art.
    assert.equal(drawings.size, seeds.size, `${look}: two different seeds drew the same square`);
    assert.ok(seeds.size > 80, `${look}: the sample seed spread is too narrow to prove anything`);
  }
});

// MAPART1 round 2 (owner playtest 2026-10-13): round 1's fix still read as "the same rock-cluster icon
// centred in every square" -- distinct markup strings (the test above) can come from nothing more than
// the per-square nudge/wobble, which is invisible at normal zoom. This test proves the rocks themselves
// move: it counts actual rock bodies per square (two `stroke-linejoin="round"` paths per rock() call) and
// the position of the first rock's first vertex, and requires both to range widely across a real field.
test('rock-pile looks vary rock count and position across a field, not just a shared icon nudged slightly', () => {
  const seedAt = (x, y) => 1 + Math.abs((x * 73856093) ^ (y * 19349663)) % 997;
  for (const look of ['rubble', 'scree', 'boulder']) {
    const counts = new Set(), firstX = [], firstY = [];
    for (let x = 0; x < 10; x += 1) for (let y = 0; y < 10; y += 1) {
      const markup = terrainCellMarkup('DIFFICULT', look, false, seedAt(x, y));
      counts.add((markup.match(/stroke-linejoin="round"/g) || []).length / 2);
      const vertex = /<path d="M(-?[\d.]+) (-?[\d.]+)L/.exec(markup);
      if (vertex) { firstX.push(Number(vertex[1])); firstY.push(Number(vertex[2])); }
    }
    assert.ok(counts.size > 1, `${look}: rock count never varies across the field`);
    const spread = arr => Math.max(...arr) - Math.min(...arr);
    assert.ok(spread(firstX) > 20, `${look}: rock x-position barely moves across the field (spread ${spread(firstX)})`);
    assert.ok(spread(firstY) > 20, `${look}: rock y-position barely moves across the field (spread ${spread(firstY)})`);
  }
});

// MAPART1 round 3 (owner playtest 2026-10-13): round 2's fix gave the rockField-based looks (rubble,
// scree, boulder) real position/count/size variety, but the fixed hand-drawn pieces -- a toppled
// pillar, a dry-stone wall -- still drew the exact same silhouette every time (only their small internal
// rock facets changed), so two of them side by side read as "paired identical blocks". This proves the
// actual geometry moves, the same way the rock-pile test above proves it for the rockField looks.
test('small fixed-shape pieces (pillar, wall, tiles) vary their own geometry, not just a shared icon nudged', () => {
  const seedAt = (x, y) => 1 + Math.abs((x * 73856093) ^ (y * 19349663)) % 997;
  const innerArt = markup => /rotate\([^)]* 32 32\)">(.*)<\/g><\/g>$/s.exec(markup)?.[1];
  for (const look of ['pillar_rubble', 'broken_tiles', 'statue_plinth']) {
    const transforms = new Set();
    for (let x = 0; x < 10; x += 1) for (let y = 0; y < 10; y += 1) {
      const art = innerArt(terrainCellMarkup('SIMPLE_COVER', look, false, seedAt(x, y)));
      assert.ok(art, `${look}: could not isolate artwork from the generic per-square wrapper`);
      const variant = /<g transform="(translate\([^)]+\) rotate\([^)]+ 32 32\) translate\(32 32\) scale\([^)]+\) translate\(-32 -32\))">/.exec(art);
      assert.ok(variant, `${look}: expected its own seeded geometry transform`);
      transforms.add(variant[1]);
    }
    assert.ok(transforms.size > 20, `${look}: inner variant transform barely varies (${transforms.size} distinct)`);
  }
  // low_wall uses seeded stone positions, counts and sizes instead of variantWrap. Inspect its actual
  // geometry after removing the generic outer nudge so that wrapper-only changes cannot satisfy this.
  // low_wall lays its stones out from the seed (jittered positions/sizes, ~1 in 8 stones
  // dropped), so the actual stone bodies -- their count and where each one sits -- must vary.
  // Counting distinct full artwork strings is not enough: the old fixed-centre layout still
  // varied every stone's facets with the seed and would pass that weaker check.
  const stoneCounts = new Set();
  const stoneLayouts = new Set();
  for (let x = 0; x < 10; x += 1) for (let y = 0; y < 10; y += 1) {
    const art = innerArt(terrainCellMarkup('SIMPLE_COVER', 'low_wall', false, seedAt(x, y)));
    assert.ok(art, 'low_wall: could not isolate artwork from the generic per-square wrapper');
    const stones = [...art.matchAll(/<path d="M(-?[\d.]+) (-?[\d.]+)L[^"]*?" fill="[^"]*" stroke="[^"]*" stroke-width="1\.1" stroke-linejoin="round"\/>/g)];
    stoneCounts.add(stones.length);
    stoneLayouts.add(`${stones.length}:${stones.map(m => `${m[1]},${m[2]}`).join(';')}`);
  }
  assert.ok(stoneCounts.size > 1, `low_wall: stone count never varies across the field (${[...stoneCounts]})`);
  assert.ok(Math.min(...stoneCounts) < 9, `low_wall: no seed ever drops a stone (counts ${[...stoneCounts]})`);
  assert.ok(stoneLayouts.size > 20, `low_wall: stone layout barely varies (${stoneLayouts.size} distinct counts/positions)`);
});

// Pre-merge review finding (MAPART1.review.r1.md, P3, terrain-art.js:153): the art cache was keyed by
// the raw `look` argument, but the geometry drawn was resolved from `type` whenever `look` was missing or
// unsupported -- so whichever terrain type rendered a given seed FIRST decided the cached fallback art for
// every other type that reused that seed afterwards. Both call orders, and an explicitly unsupported look
// string, must resolve consistently.
test('variant art resolves its fallback look once, independent of which terrain type rendered that seed first', () => {
  const artOf = markup => /rotate\([^)]* 32 32\)">(.*)<\/g><\/g>$/s.exec(markup)?.[1];
  for (const [seed, first, second] of [[711, 'DIFFICULT', 'SIMPLE_COVER'], [712, 'SIMPLE_COVER', 'DIFFICULT']]) {
    const expectedFirst = first === 'DIFFICULT' ? 'stones' : 'low_wall';
    const expectedSecond = second === 'DIFFICULT' ? 'stones' : 'low_wall';
    const firstArt = artOf(terrainCellMarkup(first, undefined, false, seed));
    const secondArt = artOf(terrainCellMarkup(second, undefined, false, seed));
    assert.equal(firstArt, artOf(terrainCellMarkup(first, expectedFirst, false, seed)), `${first}: missing look must draw its own expected fallback`);
    assert.equal(secondArt, artOf(terrainCellMarkup(second, expectedSecond, false, seed)), `${second}: cache order must not change its expected fallback`);
  }
  for (const [type, look] of [['DIFFICULT', 'stones'], ['SIMPLE_COVER', 'low_wall'], ['QI_HAZARD', 'broken_tiles']]) {
    const seed = 716;
    const expected = artOf(terrainCellMarkup(type, look, false, seed));
    assert.equal(artOf(terrainCellMarkup(type, 'not-a-real-look', false, seed)), expected, `${type}: unsupported look must use ${look}`);
    assert.equal(artOf(terrainCellMarkup(type, undefined, false, seed)), expected, `${type}: missing look must use ${look}`);
  }
});

// MAPART1 round 3: loose_gravel used to fill a flat margin on all four sides of every square, so a field
// of them read as a pasted rectangular tile with a dead straight edge. Each pebble now fades out as it
// nears its own square's (rippled) edge, and pebbles past the fade threshold are dropped outright, so
// both pebble count and opacity should vary a lot across a field instead of being the same fixed stamp.
test('loose gravel feathers near its own edges instead of filling a hard-edged rectangle', () => {
  const seedAt = (x, y) => 1 + Math.abs((x * 73856093) ^ (y * 19349663)) % 997;
  const counts = new Set();
  for (let x = 0; x < 10; x += 1) for (let y = 0; y < 10; y += 1) {
    const markup = terrainCellMarkup('DIFFICULT', 'loose_gravel', false, seedAt(x, y));
    counts.add((markup.match(/<ellipse/g) || []).length);
  }
  assert.ok(counts.size > 1, 'loose_gravel: pebble count never varies -- edges never feather or cull');
  const markup = terrainCellMarkup('DIFFICULT', 'loose_gravel', false, 777);
  const opacities = [...markup.matchAll(/opacity="([\d.]+)"/g)].map(m => Number(m[1]));
  const distinct = new Set(opacities.map(o => o.toFixed(2)));
  assert.ok(distinct.size > 5, `loose_gravel: pebble opacity barely varies (${distinct.size} distinct) -- no soft feathering toward the edge`);
});

test('the per-square nudge never disturbs the rules overlay, which stays the plain square it always was', () => {
  const seedAt = (x, y) => 1 + Math.abs((x * 73856093) ^ (y * 19349663)) % 997;
  const overlays = new Set();
  for (let x = 0; x < 5; x += 1) for (let y = 0; y < 5; y += 1) overlays.add(terrainCellMarkup('DIFFICULT', 'rubble', true, seedAt(x, y)));
  assert.equal(overlays.size, 1, 'the overlay square ignores the seed, same as before');
  assert.match([...overlays][0], /<rect x="0" y="0" width="64" height="64" class="tt-cell-difficult"\/>/);
});
