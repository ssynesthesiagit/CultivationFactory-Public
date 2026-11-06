// Board renderer check driven by REAL server output (see tests/test_scenery_sight_geometry.py).
//
// Fixture (written by that test): the normalized built-in boulder map, its arena terrain regions, the bound sight
// sources and centre-plus volumes from combat.terrain_occlusion.sight_geometry, a closed door's own wall source,
// the boulder cells and one real wall cell.
//
// What it proves, for the owner's 2026-10-23 report and the lead review:
//   * a built-in boulder wall paints no rule stroke over its art (F2-1);
//   * its invisible centre plus is still the sight geometry, and its hover entry names it (F2-1/F2-5);
//   * a real wall and a real door keep their visible strokes (F2-1);
//   * the editor preview (vision.mapCenterlines) and play (the arena regions) resolve the same occluder (lead1 1);
//   * the geometry.walls fallback classifies by the server kind and occluder, like the bound path (F2-4).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {sightBlockerLines, blockerCellStrokes} from '../static/tabletop/los-lines.js';
import {mapCenterlines, centerlineTerrain, rasterizeWalls} from '../static/tabletop/vision.js';

const fixture = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const {width, height, map, regions, sources, volumes, roofs, boulder_cells: boulderCells, wall_cells: wallCells, door} = fixture;
const cellKey = ([x, y]) => y * width + x;
const cellsOf = rows => new Set(rows.map(cellKey));

const bound = sightBlockerLines({sources}, [], {volumes, roofs});
const strokes = blockerCellStrokes(bound, width, height);
const drawn = entries => (entries || []).some(stroke => stroke.center || stroke.ticks || stroke.art);

// 1. The boulder's centre plus is the sight geometry, with its own kind and name.
const objectLines = bound.filter(line => line.kind === 'object').map(line => `${line.a}-${line.b}`);
for (const [x, y] of boulderCells) {
  const horizontal = `${x},${y + .5}-${x + 1},${y + .5}`;
  const vertical = `${x + .5},${y}-${x + .5},${y + 1}`;
  assert.ok(objectLines.includes(horizontal) && objectLines.includes(vertical),
    `boulder ${x},${y} keeps its centre plus as sight geometry`);
}
// 2. Nothing is painted over the boulder art, but a newcomer still gets the hover text.
for (const cell of boulderCells) {
  const entries = strokes.get(cellKey(cell));
  assert.ok(entries?.length, `boulder ${cell} keeps a blocker entry for hover`);
  assert.equal(drawn(entries), false, `boulder ${cell} paints no rule stroke over its art`);
  assert.ok(entries.every(entry => entry.name && entry.name.length), 'every blocker entry still names itself');
}
// 3. A real wall cell keeps its visible strokes, and a real closed door keeps its wall-line stroke.
assert.equal(drawn(strokes.get(cellKey(wallCells[0]))), true, 'the map wall still draws its rule stroke');
const doorStrokes = blockerCellStrokes(sightBlockerLines({sources: [door]}, [], {}), width, height);
assert.equal(drawn(doorStrokes.get(cellKey([door.cells[0][0], door.cells[0][1]]))), true, 'the closed door still draws a stroke');

// 4. Editor preview and play agree on every boulder cell, and a wall cell is a whole square in both.
const preview = new Set(mapCenterlines(map).map(cell => cell.join(',')));
const play = new Set(centerlineTerrain(regions, 'cross-v1').map(cell => cell.join(',')));
for (const cell of boulderCells) {
  assert.equal(preview.has(cell.join(',')), true, `editor preview gives boulder ${cell} the plus`);
  assert.equal(play.has(cell.join(',')), true, `play gives boulder ${cell} the plus`);
}
assert.equal(preview.has(wallCells[0].join(',')) || play.has(wallCells[0].join(',')), false, 'a wall keeps its footprint');

// 5. The geometry.walls fallback (board.js) takes the same server kind and occluder as the bound path.
const fallbackWalls = map.walls.map(wall => {
  const cells = rasterizeWalls([wall], width, height, map.objects);
  return {...wall, cells: [...cells.blocked, ...cells.sight]};
});
const fallback = sightBlockerLines({walls: fallbackWalls, trees: map.trees || [], objects: map.objects || [],
  blockedCells: [], centerlineCells: mapCenterlines(map)});
const fallbackStrokes = blockerCellStrokes(fallback, width, height);
for (const cell of boulderCells) assert.equal(drawn(fallbackStrokes.get(cellKey(cell))), false,
  `the fallback path paints nothing over boulder ${cell}`);
assert.equal(drawn(fallbackStrokes.get(cellKey(wallCells[0]))), true, 'the fallback path still draws the wall');
console.log('scenery sight real-map check: OK');
