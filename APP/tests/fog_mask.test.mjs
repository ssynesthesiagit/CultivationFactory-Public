// Static canvas-command render checks. No browser, GUI, or canvas dependency.
// Private Wooden Dungeon geometry stays outside the repository; the lead can
// supply a map export with FOG_MAP_FIXTURE=/path/to/wooden-dungeon.save.json.
//
// The contract under test is documented at the top of static/tabletop/fog_polygon.js:
// the DRAWN mask is the continuous visibility polygon, and the service's square
// decision governs TOKENS. These tests drive real map geometry and the engine's
// own line-of-sight rule through the production board.setFog -> paintFogMask path,
// then inspect the actual Canvas2D commands, so a regression that quantises the
// drawn mask back to the square grid fails here.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {blockerSegments, fogTokenCells, paintFogMask, visibilityPolygons, roofPresentationPolygons} from '../static/tabletop/fog_polygon.js';
import {altitudeVisibilityPolygons, altitudeFogKey, viewerEye} from '../static/tabletop/fog-altitude.js';
import {lineOfSight, opacityGrid, perceivedCells, rasterizeWalls, tokenHiddenByFog, wallCells}
  from '../static/tabletop/vision.js';
import {fogOn, fogViewers} from '../static/tabletop/fog_view.js';
import {createTableHarness, actor} from './viewer_identity_harness.mjs';

// setFog also updates roof visibility and the cloud mask. Use the real board
// helper; only the canvas recording surface and cloud element have no layout.
function fogBindings(tokens) {
  const h = createTableHarness({gm: true});
  h.board.setTokens([...tokens.values()].map(entry => entry.data));
  const source = readFileSync(new URL('../static/tabletop/board.js', import.meta.url), 'utf8');
  const start = source.indexOf('  function zoneMask(');
  const end = source.indexOf('\n  }', start) + 4;
  const zoneMask = new Function('document', source.slice(start, end) + '\nreturn zoneMask;')(h.document);
  return {setRoofView: h.board.setRoofView, zoneMask, zoneClouds: {style: {}}, openRoofCells: new Set(),
    closedRoofTops: new Map(), roofPresentationPolygons};
}

const SCALE = 64;

// Even/odd scan of one closed subpath.
function insideSubpath(points, x, y) {
  let crossings = 0;
  for (let i = 0; i < points.length; i++) {
    const [a, b] = [points[i], points[(i + 1) % points.length]];
    if ((a[1] > y) !== (b[1] > y) && x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])) crossings++;
  }
  return crossings % 2 === 1;
}

// Each moveTo opens a new closed subpath, exactly as Canvas2D does, and a path
// covers the union of its subpaths. Sampling pixel centres (x+0.5) keeps probes
// off shared cell edges, so a grid of cell rectangles reads as one region.
function insidePath(subpaths, x, y) {
  return subpaths.some(points => insideSubpath(points, x, y));
}

// Records the actual Canvas2D path, fill, and clip commands, then samples the
// rendered pixel centres. Clip regions gate a fill exactly as the browser does,
// so a clip reintroduced into the painter would still be measured.
function makeRecorder() {
  const shapes = [];
  let subpaths = [], clip = null;
  const stack = [];
  return {
    shapes,
    context: {
      clearRect() {},
      drawImage() {},
      fillStyle: '#fff',
      beginPath() { subpaths = []; },
      moveTo(x, y) { subpaths.push([[x, y]]); },
      lineTo(x, y) { (subpaths[subpaths.length - 1] ??= []).push([x, y]); },
      closePath() {},
      fill() { shapes.push({points: subpaths, clip}); },
      fillRect(x, y, w, h) { shapes.push({points: [[[x, y], [x + w, y], [x + w, y + h], [x, y + h]]], clip}); },
      save() { stack.push(clip); },
      restore() { clip = stack.pop() ?? null; },
      clip() { clip = subpaths; },
    },
    sample(px, py) {
      const x = px + 0.5, y = py + 0.5;
      return shapes.some(shape => (!shape.clip || insidePath(shape.clip, x, y)) && insidePath(shape.points, x, y));
    },
  };
}

// Direct painter checks (no board).
function renderMask(width, height, seen, geometry) {
  const recorder = makeRecorder();
  paintFogMask(recorder.context, width, height, seen, geometry, SCALE);
  return {shapes: recorder.shapes, pixel: (px, py) => recorder.sample(px, py)};
}

test('FOGLOOK: a bound tree cross casts its actual footprint, never its canopy or full-square perimeter', () => {
  const tree = {x: 4, y: 3, size: 1};
  const render = centerlineCells => renderMask(12, 8, [], {polygons: visibilityPolygons(
    [{x: 1.5, y: 3.5}], blockerSegments({trees: [tree], centerlineCells}), 12, 8)});
  const bound = render([[4, 3]]), fullSquare = render([]);
  const sample = mask => mask.pixel(5 * SCALE, Math.floor(4.14 * SCALE));
  assert.equal(sample(bound), true, 'clear beside the projected cross tip');
  assert.equal(sample(fullSquare), false, 'a full square would cast an overly broad shadow here');
  assert.equal(bound.pixel(5 * SCALE, 3.5 * SCALE), false, 'the actual trunk still blocks');
});

// The production path: service perception -> board.setFog -> paintFogMask.
function renderBoard(width, height, seen, geometry, tokenData = []) {
  const source = readFileSync(new URL('../static/tabletop/board.js', import.meta.url), 'utf8');
  const start = source.indexOf('  function setFog(');
  const end = source.indexOf('\n  }', start) + 4;
  const recorder = makeRecorder();
  const fog = {width: width * SCALE, height: height * SCALE, hidden: false,
    getContext: () => ({clearRect() {}, fillRect() {}, beginPath() {}, rect() {}, fill() {}, drawImage() {}, set globalCompositeOperation(v) {}, set fillStyle(v) {}})};
  const document = {createElement: () => ({width: width * SCALE, height: height * SCALE, getContext: () => recorder.context})};
  const tokens = new Map(tokenData.map(token => [token.id ?? 't', {data: token}]));
  const bindings = {fog, tokens, map: {width, height}, CELL: SCALE, document, fogTokenCells, paintFogMask,
    softFogCut: mask => mask, // Test the exact authoritative geometry, not the wash.
    fogPresentationCut: () => ({width:width*SCALE,height:height*SCALE}),
    ...fogBindings(tokens)};
  new Function(...Object.keys(bindings), 'let zoneSeen;\n' + source.slice(start, end) + '\nreturn setFog;')(...Object.values(bindings))(
    seen, null, geometry);
  return {shapes: recorder.shapes, pixel: (px, py) => recorder.sample(px, py)};
}

// The service's own square decision, computed the way combat/senses.py builds
// fog_perception: it asks the engine's line-of-sight rule for every square of the
// map. vision.js is the browser's port of that same rule, so the approved set
// here comes from the code the table ships instead of hand-picked cells - a
// doorway fixture that hides the cell it must hide is caught, not assumed.
function serviceCells(width, height, viewerCell, walls) {
  const raster = rasterizeWalls(walls, width, height);
  const opaque = opacityGrid(width, height, [raster.blocked, raster.sight]);
  const seen = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++)
    if (lineOfSight(width, opaque, viewerCell.x, viewerCell.y, x, y)) seen[y * width + x] = 1;
  return seen;
}

// tabletop.js renderTokens: every token carries the service's own fog decision,
// made by the same production helper the page uses (vision.js tokenHiddenByFog
// reads entity_id, so the rows are shaped like the actor rows it is given).
function boardTokens(rows, viewers, perception) {
  return rows.map(row => {
    const actor = {entity_id: row.id, x: row.x, y: row.y};
    return {...row, hidden: tokenHiddenByFog(actor, viewers, perception, true)};
  });
}

// A 10x10 map split by a full-height wall at x=5: rooms to the left and right.
function splitMap() {
  const walls = [{shape: 'line', points: [[5, 0], [5, 10]], cells: [...wallCells({shape: 'line', points: [[5, 0], [5, 10]]}, 10, 10)]
    .map(index => [index % 10, Math.floor(index / 10)])}];
  return {walls, blockers: blockerSegments({walls, width: 10, height: 10})};
}

// A 40x20 map with a wall at x=7 and a doorway gap from y=12 to y=14: the shape
// the pre-merge review used. A diagonal view through the gap meets the wall
// corners at an angle, so a square mask steps along the gap edge and a polygon
// does not.
function corridorMap() {
  const shapes = [{shape: 'line', points: [[7, 0], [7, 12]]}, {shape: 'line', points: [[7, 14], [7, 20]]}];
  const walls = shapes.map(wall => ({...wall,
    cells: [...wallCells(wall, 40, 20)].map(index => [index % 40, Math.floor(index / 40)])}));
  return {walls, blockers: blockerSegments({walls, width: 40, height: 20})};
}

const cellPixel = (x, y) => [x * SCALE + 2, y * SCALE + 2];

test('drawn mask is the continuous polygon, with lit squares only for service-perceived tokens', () => {
  const seen = serviceCells(10, 10, {x: 2, y: 5}, splitMap().walls);
  const polygons = visibilityPolygons([{x: 2.5, y: 5.5}], [[[5, 0], [5, 10]]], 10, 10);
  const tokens = [{x: 6, y: 5, size: 2, height: 1}, {x: 8, y: 5, hidden: true}];
  const mask = renderMask(10, 10, seen, {polygons, tokenCells: fogTokenCells(tokens)});
  assert.equal(mask.pixel(5 * SCALE - 1, 3 * SCALE), true);
  assert.equal(mask.pixel(5 * SCALE, 3 * SCALE), false, 'no light leaks into the wall line');
  assert.equal(mask.pixel(6 * SCALE, 5 * SCALE), true, 'perceived token fully lit beyond wall');
  assert.equal(mask.pixel(8 * SCALE - 1, 6 * SCALE - 1), true, 'entire large footprint');
  assert.equal(mask.pixel(8 * SCALE, 5 * SCALE), false, 'a token the service withheld adds no light');
  const debug = renderMask(10, 10, seen, {polygons, squareFog: true});
  assert.equal(debug.pixel(9 * SCALE, 3 * SCALE), false, 'debug mask is the service squares, not the polygon');
  assert.equal(debug.pixel(...cellPixel(2, 5)), true, 'debug mask shows the square the service approved');
  const empty = renderMask(10, 10, seen, {});
  assert.equal(empty.shapes.length, 0, 'empty polygon union cannot fall back to all seen squares');
});

test('a doorway gap is one continuous wedge, not a staircase of service squares', () => {
  // The review's case, on the service's own squares: sight to (8,13) is blocked
  // by the wall cell (7,12), so the service approves (8,14) and not (8,13).
  // Clipping the drawn mask to those squares would drop a horizontal step at
  // y=14 and restart the slope at y=15 in the next square; the continuous
  // polygon keeps one straight edge from the viewer through the wall corner.
  const {walls, blockers} = corridorMap();
  const seen = serviceCells(40, 20, {x: 1, y: 6}, walls);
  assert.equal(Boolean(seen[13 * 40 + 8]), false, 'the service does not approve (8,13)');
  assert.equal(Boolean(seen[14 * 40 + 8]), true, 'the service does approve (8,14)');
  const mask = renderBoard(40, 20, seen, {polygons: visibilityPolygons([{x: 1.5, y: 6.5}], blockers, 40, 20)});
  for (let py = 5 * SCALE; py < 11 * SCALE; py++) {
    assert.equal(mask.pixel(7 * SCALE - 1, py), true);
    assert.equal(mask.pixel(7 * SCALE, py), false);
  }
  // From (1.5,6.5) through (7,12) the upper wedge boundary is y=x+5, so in
  // pixels py = px + 5*SCALE. A staircase would hold that transition fixed
  // across each 64-pixel square instead of sliding one pixel per pixel.
  for (let px = 7 * SCALE + 2; px < 9 * SCALE; px++) {
    const boundary = px + 5 * SCALE;
    assert.equal(mask.pixel(px, boundary - 1), false, `wedge edge above y=x+5 at px=${px}`);
    assert.equal(mask.pixel(px, boundary + 1), true, `wedge edge below y=x+5 at px=${px}`);
  }
  // The exact square the old clip blanked: the wedge reaches y=13.5 at x=8.5, so
  // the lower half of the unapproved square (8,13) is lit instead of stepping
  // down to the approved square's edge at y=14.
  assert.equal(mask.pixel(543, 876), true, 'the wedge clears the unapproved part of square (8,13)');
  assert.equal(mask.pixel(543, 857), false, 'the same square stays dark above the continuous edge');
  // And the wedge keeps running: the service approves neither (9,13) nor (9,14),
  // so a mask clipped to its squares would dark there, and this one does not.
  assert.equal(Boolean(seen[14 * 40 + 9]), false);
  assert.equal(mask.pixel(591, 943), true, 'the wedge reaches into (9,14) as well');
});

test('a service-limited viewer: the floor is its continuous view, its tokens follow the service', () => {
  // senses.perception for a Blinded fighter returns its own square and nothing
  // else (see APP/tests/test_tabletop_fog_blinded.py), so the drawn floor no
  // longer follows the approved squares: the contract puts the square decision
  // on tokens. The viewer's own room is still drawn as the map's own terrain,
  // with no terrain invented and the wall still stopping the light.
  const {walls, blockers} = splitMap();
  const viewers = [{entity_id: 'blind'}];
  // Blindsight or Spiritual Sense pinpoints one creature, so the service still
  // reports it even though it approves no other square.
  const perception = {blind: {cells: [[2, 5]], creatures: ['pinpointed']}};
  const seen = perceivedCells(10, 10, viewers, perception);
  const polygons = visibilityPolygons([{entity_id: 'blind', position: {x: 2.5, y: 5.5}}], blockers, 10, 10);
  const mask = renderBoard(10, 10, seen, {polygons});
  assert.equal(mask.pixel(...cellPixel(2, 5)), true, 'own square is lit');
  assert.equal(mask.pixel(...cellPixel(4, 5)), true, 'the continuous view is not chopped into approved squares');
  assert.equal(mask.pixel(...cellPixel(7, 5)), false, 'the wall still stops the light for a limited viewer');
  // The service's creatures decide the tokens, and nothing on the page can
  // override that: a pinpointed creature gets its square lit, and one the
  // service withholds adds nothing at all.
  const lit = renderBoard(10, 10, seen, {polygons},
    boardTokens([{id: 'pinpointed', x: 6, y: 5}], viewers, perception));
  assert.equal(lit.pixel(...cellPixel(6, 5)), true, 'a creature the service reports is lit beyond the fog edge');
  const withheld = renderBoard(10, 10, seen, {polygons},
    boardTokens([{id: 'ghost', x: 3, y: 5}], viewers, perception));
  assert.deepEqual(withheld.shapes, mask.shapes, 'a creature the service withholds adds no shape at all');
});

test('mixed viewers reveal each room from its own view, and their tokens from the service', () => {
  const {walls, blockers} = splitMap();
  const viewers = [{entity_id: 'blind'}, {entity_id: 'mate'}];
  const right = [];
  for (let y = 0; y < 10; y++) for (let x = 5; x < 10; x++) right.push([x, y]);
  // The service keeps teammates known, so each viewer reports the other.
  const perception = {blind: {cells: [[2, 5]], creatures: ['blind', 'mate']}, mate: {cells: right, creatures: ['mate', 'blind']}};
  const seen = perceivedCells(10, 10, viewers, perception);
  const polygons = visibilityPolygons([
    {entity_id: 'blind', position: {x: 2.5, y: 5.5}},
    {entity_id: 'mate', position: {x: 7.5, y: 5.5}},
  ], blockers, 10, 10);
  const mask = renderBoard(10, 10, seen, {polygons},
    boardTokens([{id: 'mate', x: 7, y: 5}, {id: 'foe', x: 3, y: 5}], viewers, perception));
  assert.equal(mask.pixel(...cellPixel(9, 9)), true, 'the unrestricted viewer reveals its room in full');
  assert.equal(mask.pixel(...cellPixel(0, 0)), true, 'the limited viewer still draws its own room as plain terrain');
  assert.equal(mask.pixel(...cellPixel(7, 5)), true, 'the teammate is lit in its own room');
  // Each viewer's own light still stops at the wall, so neither room is reached
  // through it even though both rooms are drawn.
  const blindAlone = renderBoard(10, 10, perceivedCells(10, 10, [{entity_id: 'blind'}], perception),
    {polygons: visibilityPolygons([{entity_id: 'blind', position: {x: 2.5, y: 5.5}}], blockers, 10, 10)});
  assert.equal(blindAlone.pixel(...cellPixel(6, 5)), false, 'the limited viewer sees nothing through the wall');
  const tokens = boardTokens([{id: 'mate', x: 7, y: 5}, {id: 'foe', x: 3, y: 5}], viewers, perception);
  assert.equal(tokens[0].hidden, false, 'the service reports the teammate, so its token is drawn');
  assert.equal(tokens[1].hidden, true, 'no selected viewer reports the foe, so its token is hidden');
  const withoutFoe = renderBoard(10, 10, seen, {polygons}, boardTokens([{id: 'mate', x: 7, y: 5}], viewers, perception));
  assert.deepEqual(mask.shapes, withoutFoe.shapes, 'the hidden foe contributes nothing to the drawn mask');
});

test('a token the service perceives keeps its square lit, a hidden one does not', () => {
  const {blockers} = splitMap();
  const viewers = [{entity_id: 'left'}];
  const perception = {left: {cells: [[2, 5]], creatures: ['foe']}};
  const seen = perceivedCells(10, 10, viewers, perception);
  const polygons = visibilityPolygons([{entity_id: 'left', position: {x: 2.5, y: 5.5}}], blockers, 10, 10);
  const visible = renderBoard(10, 10, seen, {polygons}, boardTokens([{id: 'foe', x: 6, y: 5}], viewers, perception));
  assert.equal(visible.pixel(...cellPixel(6, 5)), true, 'a creature the service reports is lit');
  const hidden = renderBoard(10, 10, seen, {polygons},
    boardTokens([{id: 'ghost', x: 6, y: 5, hidden: true}], viewers, perception));
  assert.equal(hidden.pixel(...cellPixel(6, 5)), false, 'a token the service did not report adds no light');
});

test('the Invisible condition dims a token without blanking the floor it stands on', () => {
  // `unseen` is a rules decision about the token - the board draws it at 45%
  // opacity - while `hidden` is the service's own answer and the board drops the
  // token altogether. Only the second one is a fog decision, so it is the only
  // one that may switch a square off.
  const {blockers} = splitMap();
  const viewers = [{entity_id: 'left'}];
  const perception = {left: {cells: [[2, 5]], creatures: ['veiled']}};
  const seen = perceivedCells(10, 10, viewers, perception);
  const polygons = visibilityPolygons([{entity_id: 'left', position: {x: 2.5, y: 5.5}}], blockers, 10, 10);
  const styles = readFileSync(new URL('../static/tabletop/tabletop.css', import.meta.url), 'utf8');
  assert.match(styles, /\.tt-token\.is-unseen \{ opacity: 0\.45; \}/,
    'the condition dims the token instead of removing it from the table');
  const dimmed = renderBoard(10, 10, seen, {polygons},
    boardTokens([{id: 'veiled', x: 3, y: 5, unseen: true}], viewers, perception));
  assert.equal(dimmed.pixel(...cellPixel(3, 5)), true, 'the floor a viewer can see stays lit under a dimmed token');
  const bare = renderBoard(10, 10, seen, {polygons});
  const withheld = renderBoard(10, 10, seen, {polygons},
    boardTokens([{id: 'veiled', x: 3, y: 5}], viewers, {left: {cells: [[2, 5]], creatures: []}}));
  assert.deepEqual(withheld.shapes, bare.shapes, 'a token the service withholds lights no square of its own');
});

test('board draws the shared mask with perceived token exceptions at display resolution', () => {
  const source = readFileSync(new URL('../static/tabletop/board.js', import.meta.url), 'utf8');
  const start = source.indexOf('  function setFog(');
  const end = source.indexOf('\n  }', start) + 4;
  const canvas = () => ({width: 640, height: 640, hidden: false, getContext: () => ({
    clearRect() {}, fillRect() {}, beginPath() {}, rect() {}, fill() {}, drawImage() {}, set fillStyle(v) {},
  })});
  const fog = canvas(), tokens = new Map([['shown', {data: {x: 6, y: 5}}], ['hidden', {data: {x: 8, y: 5, hidden: true}}]]);
  let actual;
  const bindings = {fog, tokens, map: {width: 10, height: 10}, CELL: SCALE,
    softFogCut: mask => mask, // Geometry recorder; presentation pixels have their own raster gate.
    fogPresentationCut: () => canvas(),
    document: {createElement: canvas}, fogTokenCells,
    paintFogMask: (...args) => { actual = args; }, ...fogBindings(tokens)};
  new Function(...Object.keys(bindings), 'let zoneSeen;\n' + source.slice(start, end) + '\nreturn setFog;')(...Object.values(bindings))(
    new Uint8Array(100), null, {polygons: [{points: [[0, 0], [5, 0], [5, 10]]}]});
  assert.deepEqual(actual[4].tokenCells, [[6, 5]]);
  assert.equal(actual[4].polygons.length, 1);
  assert.equal(actual[5], SCALE);
});

test('the map editor previews its own eye with the square mask, not an empty polygon union', () => {
  // The editor passes visible cells without viewer geometry, so it must ask for
  // the square mask explicitly; otherwise its whole preview goes dark.
  const editor = readFileSync(new URL('../static/tabletop/mapeditor.js', import.meta.url), 'utf8');
  assert.match(editor, /setFog\(visibleCells\([^)]*\), null, \{squareFog: true\}\)/,
    'the editor requests the square mask explicitly');
  const seen = new Uint8Array(100); seen[5 * 10 + 2] = 1; seen[5 * 10 + 3] = 1;
  const editorMask = renderMask(10, 10, seen, {squareFog: true});
  assert.equal(editorMask.pixel(...cellPixel(2, 5)), true, 'visible floor is previewed');
  assert.equal(editorMask.pixel(...cellPixel(7, 5)), false, 'hidden floor stays dark');
  assert.equal(renderMask(10, 10, seen, {}).shapes.length, 0, 'no silent fallback when geometry is absent');
});

const mapPath = process.env.FOG_MAP_FIXTURE || '/var/tmp/auto-audit/wooden-dungeon.save.json';
test('Wooden Dungeon export: mask edges at start positions meet actual corridor lines and door gap within one pixel',
  {skip: !existsSync(mapPath) ? 'Set FOG_MAP_FIXTURE to an existing Wooden Dungeon map export' : false}, () => {
    const exportData = JSON.parse(readFileSync(mapPath, 'utf8'));
    const map = exportData.map || exportData;
    assert.equal(map.map_id, 'wooden-dungeon');
    const width = map.width_squares, height = map.height_squares;
    const walls = map.walls.map(wall => ({...wall, cells: [...wallCells(wall, width, height)]
      .map(index => [index % width, Math.floor(index / width)])}));
    const blockers = blockerSegments({walls, trees: map.trees, width, height});
    const renderSide = side => {
      // The service's squares for the real start positions, so this is the same
      // production path a player sees and not an all-visible grid.
      const seen = new Uint8Array(width * height);
      for (const [x, y] of map.starts[side]) {
        const cells = serviceCells(width, height, {x, y}, map.walls);
        for (let index = 0; index < cells.length; index++) if (cells[index]) seen[index] = 1;
      }
      return renderMask(width, height, seen, {polygons: visibilityPolygons(
        map.starts[side].map(([x, y]) => ({x: x + 0.5, y: y + 0.5})), blockers, width, height)});
    };
    const left = renderSide('team1'), right = renderSide('team2');
    for (let py = 4 * SCALE; py < 11 * SCALE; py++) {
      assert.equal(left.pixel(7 * SCALE - 1, py), true);
      assert.equal(left.pixel(7 * SCALE, py), false);
      assert.equal(right.pixel(30 * SCALE - 1, py), false);
      assert.equal(right.pixel(30 * SCALE, py), true);
    }
    // The lowest start at y=14.5 defines the union's upper boundary through (7,12).
    for (let px = 7 * SCALE + 2; px < 9 * SCALE; px++) {
      const y = (14.5 + ((px + 0.5) / SCALE - 1.5) * (12 - 14.5) / (7 - 1.5)) * SCALE;
      assert.equal(left.pixel(px, Math.floor(y) - 1), false);
      assert.equal(left.pixel(px, Math.ceil(y)), true);
    }
    console.log(`Wooden Dungeon: ${walls.length} walls, ${map.starts.team1.length + map.starts.team2.length} starts; 1px wall/gap probes passed`);
  });

test('tabletop geometry excludes rasterized walls, keeps ?fogSquares=1, and preserves it across the address rewrite', () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  // fogAudience (which names the viewers, fog_view.js) through fogGeometry, the real shipped code.
  const start = source.indexOf('function fogAudience(');
  const end = source.indexOf('\n}', source.indexOf('function fogGeometry(')) + 2;
  const map = {width: 10, height: 10, trees: [],
    walls: [{shape: 'line', points: [[5, 0], [5, 10]]}], cells: {blocked: [[5, 5]], sight: []}};
  const h = createTableHarness({boundIds: ['viewer'], fog: 'team',
    roster: [actor('viewer', {x: 2, y: 5})]});
  const app = h.app;
  const location = {search: ''};
  const bindings = {app, board: {map}, location, URLSearchParams, wallCells, blockerSegments, visibilityPolygons,
    altitudeVisibilityPolygons, altitudeFogKey, viewerEye,
    perceivedCells, fogViewers, fogOn, treeCells: () => [], wallSightCells: () => [], presentation: () => ({}),
    teamIndex: () => 0, enc: encodeURIComponent, currentViewer: h.currentViewer, isOwnedActor: h.isOwnedActor,
    viewerStore: h.viewerStore, actors: () => app.state.presentation.actors};
  const built = new Function(...Object.keys(bindings),
    source.slice(start, end) + '\nreturn {fogGeometry, tabletopUrl};')(...Object.values(bindings));
  const {fogGeometry, tabletopUrl} = built;
  const seen = new Uint8Array(100).fill(1);
  const normal = fogGeometry(seen);
  assert.equal(Math.max(...normal.polygons[0].points.map(([x]) => x)), 5);
  assert.equal(normal.squareFog, undefined);
  assert.equal(tabletopUrl('match:abc'), '/tabletop?match=match%3Aabc&view=view-one');
  location.search = '?fogSquares=1';
  assert.deepEqual(fogGeometry(seen), {squareFog: true});
  // Loading a fight rewrites the address bar; the debug flag has to survive it.
  assert.equal(tabletopUrl('match:abc'), '/tabletop?match=match%3Aabc&view=view-one&fogSquares=1');
  location.search = '?fogSquares=0';
  assert.equal(fogGeometry(seen).polygons, normal.polygons, 'cached geometry remains independent of debug mask');
  assert.equal(tabletopUrl('match:abc'), '/tabletop?match=match%3Aabc&view=view-one');
});
