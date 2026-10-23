// Real SVG painter geometry, without a DOM, canvas, or browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {WALL_LOOKS, wallLookMarkup, wallPatternDefs} from '../static/tabletop/wall-art.js';
import {wallPieces} from '../static/tabletop/wall-openings.js';

const rotate = ([x, y]) => [-y || 0, x];
const wall = (look, shape, points, filled = false) => ({look, shape, points, filled, blocks: 'sight_and_movement'});
const attrs = text => Object.fromEntries([...text.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
const definitions = () => new Map([...wallPatternDefs().matchAll(/<pattern\b([^>]*)>(.*?)<\/pattern>/g)]
  .map(m => [attrs(m[1]).id, {attrs: attrs(m[1]), body: m[2]}]));

// Resolve the actual fill URL and SVG pattern transform, then compare the tile
// geometry in pattern space. A board-space 90-degree turn must be cancelled by
// the pattern's inverse transform; testing only the wall outline misses this bug.
function patternPoint(markup, point) {
  const id = /fill="url\(#([^)]*)\)"/.exec(markup)?.[1];
  const pattern = definitions().get(id);
  assert.ok(pattern, `resolved pattern ${id}`);
  assert.equal(pattern.attrs.patternUnits, 'userSpaceOnUse');
  const transform = pattern.attrs.patternTransform || '';
  assert.match(transform, /^(rotate\(90\))?$/);
  const [x, y] = point;
  return {point: transform ? [y, -x] : [x, y], width: pattern.attrs.width,
    height: pattern.attrs.height, body: pattern.body};
}

for (const look of Object.keys(WALL_LOOKS)) {
  test(`${look}: filled vertical wall has the horizontal pattern rotated 90 degrees`, () => {
    const h = wall(look, 'rect', [[0, 0], [6, 1]], true);
    const v = {...h, points: h.points.map(rotate)};
    const horizontal = wallLookMarkup(h), vertical = wallLookMarkup(v);
    assert.match(vertical, /x="-1" y="0" width="1" height="6"/);
    for (const point of [[.03, .02], [.26, .13], [2.49, .88], [5.97, .98]]) {
      assert.deepEqual(patternPoint(vertical, rotate(point)), patternPoint(horizontal, point));
    }
    // Point order doesn't pick the orientation, and all vertical pieces share
    // the same board-anchored pattern, so adjacent pieces don't restart joints.
    assert.equal(wallLookMarkup({...v, points: [...v.points].reverse()}), vertical);
    const adjacent = wallLookMarkup(wall(look, 'rect', [[-1, 6], [0, 8]], true));
    assert.deepEqual(patternPoint(adjacent, [-.4, 6.3]), patternPoint(vertical, [-.4, 6.3]));
    assert.equal(wallLookMarkup(h), wallLookMarkup({...h, points: [...h.points].reverse()}));
  });
}

function layers(markup) {
  return [...markup.matchAll(/<polyline\b([^>]*)\/>/g)].map(m => attrs(m[1]));
}
function assertRotated(h, v) {
  const horizontal = layers(wallLookMarkup(h)), vertical = layers(wallLookMarkup(v));
  assert.ok(horizontal.length >= 3);
  assert.equal(vertical.length, horizontal.length);
  horizontal.forEach((layer, i) => {
    const points = layer.points.split(' ').map(p => p.split(',').map(Number));
    assert.deepEqual(vertical[i], {...layer, points: points.map(rotate).map(p => p.join(',')).join(' ')});
  });
}

test('every style turns its line details around a corner and cuts a vertical door flush', () => {
  for (const look of Object.keys(WALL_LOOKS)) {
    const corner = wall(look, 'line', [[1, 1], [5, 1], [5, 4]]);
    assertRotated(corner, {...corner, points: corner.points.map(rotate)});
    const h = wall(look, 'line', [[0, 0], [6, 0]]);
    const v = {...h, points: h.points.map(rotate)};
    const hp = wallPieces(h, [{kind: 'door', x: 2, y: 0, mount_axis: 'h', mount_line: 0}]);
    const vp = wallPieces(v, [{kind: 'door', x: 0, y: 2, mount_axis: 'v', mount_line: 0}]);
    assert.deepEqual(vp.map(p => p.points), [[[0, 0], [0, 2]], [[0, 3], [0, 6]]]);
    assert.equal(hp.length, vp.length);
    hp.forEach((piece, i) => {
      assertRotated(piece, vp[i]);
      for (const layer of layers(wallLookMarkup(vp[i]))) assert.equal(layer['stroke-linecap'], 'butt');
    });
  }
});

test('filled corner joins and gaps retain their geometry with the oriented pattern', () => {
  const bounds = markup => {
    const a = attrs(/<rect\b([^>]*)\/>/.exec(markup)[1]);
    return [Number(a.x), Number(a.y), Number(a.width), Number(a.height), a['stroke-width']];
  };
  for (const look of Object.keys(WALL_LOOKS)) {
    // A built-up L corner: the two blocks meet on x=1, y=1..2.
    const across = wallLookMarkup(wall(look, 'rect', [[1, 1], [6, 2]], true));
    const down = wallLookMarkup(wall(look, 'rect', [[0, 1], [1, 6]], true));
    assert.deepEqual(bounds(across), [1, 1, 5, 1, '0.08']);
    assert.deepEqual(bounds(down), [0, 1, 1, 5, '0.08']);
    assert.deepEqual(patternPoint(down, rotate([2.2, .4])), patternPoint(across, [2.2, .4]));
    // Filled-wall maps express an aperture as separated blocks. The pattern
    // rotates inside each block, without extending either fill across the gap.
    const upper = wallLookMarkup(wall(look, 'rect', [[3, 1], [4, 3]], true));
    const lower = wallLookMarkup(wall(look, 'rect', [[3, 4], [4, 8]], true));
    assert.deepEqual(bounds(upper), [3, 1, 1, 2, '0.08']);
    assert.deepEqual(bounds(lower), [3, 4, 1, 4, '0.08']);
    assert.deepEqual(patternPoint(upper, [3.4, 2.2]), patternPoint(lower, [3.4, 2.2]));
  }
});

test('no-look walls and horizontal wall-run fills keep their existing presentation', () => {
  assert.equal(wallLookMarkup(wall(null, 'rect', [[0, 0], [1, 6]], true)), null);
  for (const look of Object.keys(WALL_LOOKS)) {
    assert.match(wallLookMarkup(wall(look, 'rect', [[0, 0], [6, 1]], true)), new RegExp(`fill="url\\(#tt-wall-pat-${look}\\)"`));
  }
  const ids = [...definitions().keys()];
  assert.equal(ids.length, new Set(ids).size);
});

// MAPART2 (owner QA, 4a5521da): a small square or a circle is an object standing on the floor (a
// pillar, a boulder, a brazier), not a wall run -- the flat tile-pattern fill those used to share with
// a wall run read as "no texture, like a placeholder" at that scale. Both now draw real pillar/boulder
// art instead, for every look (wall-art.test.mjs covers the art itself in more depth).
test('a filled square or circle never uses the flat wall-run tile pattern, for any look', () => {
  for (const look of Object.keys(WALL_LOOKS)) {
    for (const [shape, points] of [['rect', [[0, 0], [1, 1]]], ['circle', [[0, 0], [0, 2]]]]) {
      const markup = wallLookMarkup(wall(look, shape, points, true));
      assert.doesNotMatch(markup, new RegExp(`fill="url\\(#tt-wall-pat-${look}\\)"`), `${look} ${shape}`);
      assert.doesNotMatch(markup, /NaN|undefined/, `${look} ${shape}`);
    }
  }
});
