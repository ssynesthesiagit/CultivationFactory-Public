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
import {blockerSegments, fogPointVisible, fogTokenCells, paintFogMask, visibilityPolygons, roofPresentationPolygons} from '../static/tabletop/fog_polygon.js';
import {cellSegments, viewerSegments, rayVisible} from '../static/tabletop/sight-lines.js';
import {wallSightCells} from '../static/tabletop/zones.js';
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
function insidePath(subpaths, x, y, rule = 'nonzero') {
  const hits = subpaths.filter(points => insideSubpath(points, x, y)).length;
  return rule === 'evenodd' ? hits % 2 === 1 : hits > 0;
}

// Records the actual Canvas2D path, fill, and clip commands, then samples the
// rendered pixel centres. Clip regions gate a fill exactly as the browser does,
// so a clip reintroduced into the painter would still be measured.
function makeRecorder() {
  const shapes = [];
  let subpaths = [], clips = [];
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
      fill() { shapes.push({points: subpaths, clips}); },
      fillRect(x, y, w, h) { shapes.push({points: [[[x, y], [x + w, y], [x + w, y + h], [x, y + h]]], clips}); },
      save() { stack.push(clips); },
      restore() { clips = stack.pop() ?? []; },
      clip(rule = 'nonzero') { clips = [...clips, {paths:subpaths, rule}]; },
    },
    sample(px, py) {
      const x = px + 0.5, y = py + 0.5;
      return shapes.some(shape => shape.clips.every(clip => insidePath(clip.paths,x,y,clip.rule)) && insidePath(shape.points, x, y));
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
  const bound = render([[4, 3]]), fullSquare = renderMask(12,8,[],{polygons:visibilityPolygons(
    [{x:1.5,y:3.5}],[[[4,3],[5,3]],[[5,3],[5,4]],[[5,4],[4,4]],[[4,4],[4,3]]],12,8)});
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
  const document = {createElement: () => ({width: width * SCALE, height: height * SCALE,
    getContext: () => recorder.context, toDataURL: () => 'data:image/png;base64,mask'})};
  const tokens = new Map(tokenData.map(token => [token.id ?? 't', {data: token}]));
  const bindings = {fog, tokens, map: {width, height}, CELL: SCALE, document, gridSvg: {style: {}}, fogTokenCells, paintFogMask, updateSightBlockers() {},
    softFogCut: mask => mask, // Test the exact authoritative geometry, not the wash.
    fogPresentationCut: () => ({width:width*SCALE,height:height*SCALE}),
    ...fogBindings(tokens)};
  new Function(...Object.keys(bindings), 'let zoneSeen;\n' + source.slice(start, end) + '\nreturn setFog;')(...Object.values(bindings))(
    seen, null, geometry);
  return {shapes: recorder.shapes, pixel: (px, py) => recorder.sample(px, py)};
}

// Use the server's bound-source shape and the production board mask. No token
// exceptions or approved-square mask can light the ground for these probes.
const screenSource = (cells, kind = 'SIGHT_BLOCKED') => ({
  kind, cells, scale: 2, bottom_ft: 0, top_ft: 10,
  segments: cellSegments(cells).map(s => s.map(p => p.map(n => n * 2))),
});
const screenFog = (sources, origin = {x: 4.5, y: 4.5}) => ({polygons: visibilityPolygons(
  [origin], blockerSegments({sources}), 10, 10)});

for (const staticSources of [[], [screenSource([[8, 1]], 'BLOCKED')]]) {
  test(`LOSLINES3F5: production fog and board retain obscures-only walls with ${staticSources.length} bound sources`, () => {
    const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
    const start = source.indexOf('function fogGeometry(');
    const end = source.indexOf('\n}', start) + 2;
    const zone = {zone_id:'smoke', active:true, affected_cells:[[4,4]],
      trigger_profile:{wall:{obscures:'all'}}};
    const p = {zones:[zone],actors:[]};
    const viewers=[{entity_id:'viewer',team_index:0,position:{x:2,y:4}}];
    const app = {state:{objects:[], fog_geometry:{lines:staticSources, volumes:[]}}};
    const board = {map:{width:10, height:10, walls:[], trees:[], centerlineCells:[],
      cells:{blocked:[], sight:[]}}};
    const bindings = {app, board, presentation:()=>p,
      fogAudience:()=>viewers,
      treeCells:()=>[], wallCells, wallSightCells, altitudeFogKey, viewerEye,
      blockerSegments, visibilityPolygons, altitudeVisibilityPolygons, squareFogDebug:()=>false};
    const geometry = new Function(...Object.keys(bindings),
      source.slice(start,end)+'\nreturn fogGeometry;')(...Object.values(bindings));
    const fog = geometry([]), mask = renderBoard(10,10,[],fog);
    assert.equal(fogPointVisible(6.5,4.5,10,10,[],fog.polygons),false,'smoke hides distant floor');
    assert.equal(mask.pixel(6.5*SCALE,4.5*SCALE),false,'board hides distant scenery');
    assert.equal(mask.pixel(3.5*SCALE,4.5*SCALE),true,'near floor stays visible');
    assert.equal(geometry([]).polygons,fog.polygons,'unchanged geometry uses cache');
    zone.trigger_profile.openings=[{cell:[4,4]}];
    const opened=geometry([]);
    assert.equal(renderBoard(10,10,[],opened).pixel(6.5*SCALE,4.5*SCALE),true,'opening invalidates cached shadow');
    zone.trigger_profile.openings=[];
    assert.equal(renderBoard(10,10,[],geometry([])).pixel(6.5*SCALE,4.5*SCALE),false,'restored wall blocks again');
    zone.active=false;
    assert.equal(renderBoard(10,10,[],geometry([])).pixel(6.5*SCALE,4.5*SCALE),true,'expired wall leaves no shadow');
    zone.active=true;
    zone.trigger_profile.wall={blocks_movement:true};
    assert.equal(renderBoard(10,10,[],geometry([])).pixel(6.5*SCALE,4.5*SCALE),true,
      'physical wall cells omitted by authoritative geometry must stay omitted');
    zone.trigger_profile.wall={blocks_sight:true};
    assert.equal(renderBoard(10,10,[],geometry([])).pixel(6.5*SCALE,4.5*SCALE),true,
      'bound physical screens must not be recreated by the supplement');
    zone.trigger_profile.wall={obscures:'hostile'};
    zone.owner_id='owner';
    p.actors=[{entity_id:'owner',team_index:0}];
    assert.equal(renderBoard(10,10,[],geometry([])).pixel(6.5*SCALE,4.5*SCALE),true,'allied eyes see through Monsoon Wall');
    p.actors[0].team_index=1;
    assert.equal(renderBoard(10,10,[],geometry([])).pixel(6.5*SCALE,4.5*SCALE),false,'owner team change invalidates cached hostility');
    viewers.push({entity_id:'ally',team_index:1,position:{x:2,y:4}});
    const shared=geometry([]);
    assert.equal(fogPointVisible(6.5,4.5,10,10,[],[shared.polygons[0]]),false,'hostile viewer remains obscured');
    assert.equal(fogPointVisible(6.5,4.5,10,10,[],[shared.polygons[1]]),true,'allied viewer remains clear');
    assert.equal(renderBoard(10,10,[],shared).pixel(6.5*SCALE,4.5*SCALE),true,'shared sight unions observer-specific masks');
  });
}

test('LOSLINES3F5: bound screens retain occupied-cell exemptions without supplemental walls', () => {
  const cells=[[4,4],[4,5],[4,6]], sources=[screenSource(cells)];
  const segments=blockerSegments({sources,dynamicCells:[]});
  assert.equal(segments.length,sources[0].segments.length,'no duplicate cell barriers');
  const fog={polygons:visibilityPolygons([{x:4.5,y:4.5}],segments,10,10)};
  const mask=renderBoard(10,10,[],fog);
  assert.equal(mask.pixel(6.5*SCALE,4.5*SCALE),true,'occupied screen remains open outward');
  assert.equal(mask.pixel(4.5*SCALE,7.5*SCALE),false,'remaining screen still blocks');
});

test('LOSLINES3F5: supplemental cells respect caller hostility and ignore elevated bound coverage', () => {
  const zone={zone_id:'rain',affected_cells:[[4,4]],trigger_profile:{wall:{obscures:'hostile'}}};
  const sources=[{...screenSource([[4,4]],'BLOCKED'),bottom_ft:10,top_ft:20}];
  for(const hostile of [false,true]) {
    const dynamicCells=wallSightCells([zone],{hostile:()=>hostile});
    const fog={polygons:visibilityPolygons([{x:2.5,y:4.5}],blockerSegments({sources,dynamicCells}),10,10)};
    assert.equal(renderBoard(10,10,[],fog).pixel(6.5*SCALE,4.5*SCALE),!hostile);
  }
});

test('LOSLINES3F5: overlapping sparse bound scenery cannot erase an independent obscuring wall', () => {
  const sources=[{cells:[[4,4]],kind:'BLOCKED',bottom_ft:0,top_ft:20,scale:10,
    segments:[[[41,40],[41,45]]]}];
  const fog=dynamicCells=>({polygons:visibilityPolygons([{x:2.5,y:4.5}],
    blockerSegments({sources,dynamicCells}),10,10)});
  assert.equal(renderBoard(10,10,[],fog([])).pixel(6.5*SCALE,5.5*SCALE),true,'ray clears the skinny scenery');
  assert.equal(renderBoard(10,10,[],fog([[4,4]])).pixel(6.5*SCALE,5.5*SCALE),false,'independent smoke remains a barrier');
});

test('LOSLINES3F12: split sight segments retain screen metadata for adjacent-cell viewer clipping', () => {
  const cells=[[2,4],[3,4],[4,4]], segments=cellSegments(cells).map(s=>Object.assign(s,{screenCells:cells}));
  const origin={x:2.5,y:4.5}, target=[3.5,4.5];
  assert.equal(rayVisible(origin,target,viewerSegments({x:target[0],y:target[1]},viewerSegments(origin,segments))),true,
    'a viewer in one occupied screen cell sees the adjoining cell');
});

test('LOSLINES3F12: paint exempt screen pixels even when outside that obstacle shadow', () => {
  const shadow=Object.assign([[5,0],[9,0],[9,10],[5,10]],{screenCells:[[4,4]]});
  const mask=renderMask(10,10,[],{polygons:[{origin:{x:2.5,y:4.5},
    points:[[0,0],[10,0],[10,10],[0,10]],shadows:[shadow]}]});
  assert.equal(mask.pixel(4.5*SCALE,4.5*SCALE),true,'the exempt cell stays lit outside the projected shadow');
  assert.equal(mask.pixel(6.5*SCALE,4.5*SCALE),false,'the same shadow remains dark beyond the exemption');
});

test('LOSLINES3F17RSC: screen-cell exemptions respect surface footprint clips', () => {
  const surface = Object.assign([[1,1],[2,1],[2,2],[1,2]], {roof: true});
  const outside = Object.assign([[5,0],[9,0],[9,10],[5,10]], {screenCells: [[4,4]]});
  const inside = Object.assign([[0,0],[3,0],[3,3],[0,3]], {screenCells: [[1,1]]});
  const mask = renderMask(10, 10, [], {polygons: [{origin: {x: 2.5, y: 4.5},
    points: [[0,0],[10,0],[10,10],[0,10]], clips: [surface], shadows: [outside, inside]}]});
  assert.equal(mask.pixel(1.5 * SCALE, 1.5 * SCALE), true, 'an exemption inside the surface footprint stays visible');
  assert.equal(mask.pixel(4.5 * SCALE, 4.5 * SCALE), false, 'an exemption outside the surface footprint stays dark');
});

test('LOSLINES3F18RSC: overlapping shadows keep each other\'s exemptions for the same screen cell', () => {
  // Three shadows exempt (4,4); two overlap the sampled pixel and one misses it.
  // The pixel is visible in the sampler, so the painter must light it too.
  const exempt = (shadow) => Object.assign(shadow, {screenCells: [[4, 4]]});
  const board = [[0,0],[10,0],[10,10],[0,10]];
  const sample = [4.7, 4.47];
  const shadows = [
    exempt([[4.4,0],[4.9,0],[4.9,10],[4.4,10]]),
    exempt([[4.5,0],[4.8,0],[4.8,10],[4.5,10]]),
    exempt([[6,0],[7,0],[7,10],[6,10]]),
  ];
  const polygons = [{origin: {x: 2.5, y: 4.5}, points: board, shadows}];
  assert.equal(fogPointVisible(...sample, 10, 10, [], polygons), true, 'sampler: exempt pixel is visible');
  const mask = renderMask(10, 10, [], {polygons});
  assert.equal(mask.pixel(sample[0] * SCALE, sample[1] * SCALE), true,
    'painter: a pixel exempt by every shadow that covers it stays lit');
  // An independent, non-exempt blocker over the same pixel still darkens it.
  const blocked = renderMask(10, 10, [], {polygons: [{origin: {x: 2.5, y: 4.5}, points: board,
    shadows: [...shadows, [[4.6,4],[4.8,4],[4.8,5],[4.6,5]]]}]});
  assert.equal(fogPointVisible(...sample, 10, 10, [], [{origin: {x: 2.5, y: 4.5}, points: board,
    shadows: [...shadows, [[4.6,4],[4.8,4],[4.8,5],[4.6,5]]]}]), false, 'sampler: independent blocker darkens');
  assert.equal(blocked.pixel(sample[0] * SCALE, sample[1] * SCALE), false,
    'painter: an independent non-exempt blocker still darkens the exempt cell');
});

test('LOSLINES3R: paint occupied screen exemption without relighting the blocked square behind it', () => {
  const fog=screenFog([screenSource([[4,4]])],{x:2.5,y:4.5});
  const mask=renderBoard(10,10,[],fog);
  assert.equal(mask.pixel(4.5*SCALE,4.5*SCALE),true,'visible screen cell is lit without a token');
  assert.equal(mask.pixel(6.5*SCALE,4.5*SCALE),false,'the screen still shades the square behind it');
});

test('LOSLINES3F2: occupied screen lights clear ground in sampling and the production board mask', () => {
  const sources = [screenSource([[4, 4]])], fog = screenFog(sources);
  const mask = renderBoard(10, 10, [], fog);
  for (const [x, y] of [[3.5, 4.5], [5.5, 4.5], [4.5, 3.5], [4.5, 5.5], [3.5, 3.5], [5.5, 5.5]]) {
    assert.equal(fogPointVisible(x, y, 10, 10, [], fog.polygons), true, `clear ground ${x},${y}`);
    assert.equal(mask.pixel(x * SCALE, y * SCALE), true, `board mask lights ${x},${y}`);
  }
  // Geometry is shared between viewers. An outside viewer must still see the
  // screen's shadow, even after the occupied viewer has been computed.
  const outside = screenFog(sources, {x: 2.5, y: 4.5});
  assert.equal(fogPointVisible(6.5, 4.5, 10, 10, [], outside.polygons), false);
  assert.equal(renderBoard(10, 10, [], outside).pixel(6.5 * SCALE, 4.5 * SCALE), false);
});

test('LOSLINES3F3: off-centre viewer exits a horizontal screen without erasing its remaining shadow', () => {
  const sources = [screenSource([[3, 4], [4, 4], [5, 4]])];
  const unchanged = JSON.stringify(sources);
  const fog = screenFog(sources, {x: 4.2, y: 4.7});
  const mask = renderBoard(10, 10, [], fog);
  for (const [x, y, visible] of [[4.2, 2.5, true], [4.2, 6.5, true],
    [1.5, 4.7, false], [7.5, 4.7, false]]) {
    assert.equal(fogPointVisible(x, y, 10, 10, [], fog.polygons), visible, `sampling ${x},${y}`);
    assert.equal(mask.pixel(Math.floor(x * SCALE), Math.floor(y * SCALE)), visible, `board ${x},${y}`);
  }
  assert.equal(JSON.stringify(sources), unchanged, 'viewer clipping must not alter shared bound sources');
});

test('LOSLINES3F2: clip only the occupied screen cell and retain independent barriers', () => {
  for (const cells of [[[4, 4], [4, 5], [4, 6]], [[4, 4], [4, 6]]]) {
    const fog = screenFog([screenSource(cells)]), mask = renderBoard(10, 10, [], fog);
    assert.equal(fogPointVisible(5.5, 4.5, 10, 10, [], fog.polygons), true, 'outward sight stays clear');
    assert.equal(mask.pixel(5.5 * SCALE, 4.5 * SCALE), true, 'clear ground is painted');
    for (const [x, y] of [[4.5, 7.5], [4.6, 7.5]]) {
      assert.equal(fogPointVisible(x, y, 10, 10, [], fog.polygons), false, 'other screen cells still intervene');
      assert.equal(mask.pixel(x * SCALE, y * SCALE), false, 'intervening screen still shades the board');
    }
  }
  for (const sources of [
    [screenSource([[4, 4]]), screenSource([[4, 4]], 'BLOCKED')],
    [screenSource([[4, 4]]), screenSource([[6, 4]], 'BLOCKED')],
  ]) {
    const fog = screenFog(sources);
    assert.equal(fogPointVisible(7.5, 4.5, 10, 10, [], fog.polygons), false, 'solid sources keep blocking');
    assert.equal(renderBoard(10, 10, [], fog).pixel(7.5 * SCALE, 4.5 * SCALE), false);
  }
});

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
  // A line-and-cap doorway still paints a continuous wedge. A cell mask would
  // replace its diagonal boundary with square steps and lose the opening.
  const {walls, blockers} = corridorMap();
  // Full-depth caps close the old steep diagonal peek from y=6.5. At y=10.5
  // there is a genuine narrow view through the aperture between y=13 and 14.
  const seen = new Uint8Array(40*20);seen[10*40+1]=1;
  const mask = renderBoard(40, 20, seen, {polygons: visibilityPolygons([{x: 1.5, y: 10.5}], blockers, 40, 20)});
  for (let py = 5 * SCALE; py < 11 * SCALE; py++) {
    assert.equal(mask.pixel(7.5 * SCALE - 1, py), true,'near half of the wall is lit');
    assert.equal(mask.pixel(7.5 * SCALE, py), false,'shadow starts at its centre');
  }
  // A staircase would hold the transition fixed across each square instead
  // of following the ray from (1.5,10.5) through the cap tip (7,13).
  for (let px = 8 * SCALE + 2; px < 9 * SCALE; px++) {
    // The raster footprint includes the authored endpoint cell: its end cap
    // is y=13, spanning x=7..8. Rays meet its near tip (7,13).
    const boundary=(10.5+((px+.5)/SCALE-1.5)*2.5/5.5)*SCALE;
    assert.equal(mask.pixel(px, Math.floor(boundary)-1), false, `above end-cap wedge at px=${px}`);
    assert.equal(mask.pixel(px, Math.ceil(boundary)+1), true, `below end-cap wedge at px=${px}`);
  }
  // These samples lie inside and above the continuous aperture respectively;
  // neither square is present in the supplied seen-cell mask.
  assert.equal(mask.pixel(543, 900), true, 'the continuous wedge clears below the end cap');
  assert.equal(mask.pixel(543, 857), false, 'the same square stays dark above the continuous edge');
  // And the wedge keeps running: the service approves neither (9,13) nor (9,14),
  // so a mask clipped to its squares would dark there, and this one does not.
  assert.equal(Boolean(seen[14 * 40 + 9]), false);
  assert.equal(mask.pixel(591, 920), true, 'the continuous wedge keeps running');
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
  const canvas = () => ({width: 640, height: 640, hidden: false, toDataURL: () => 'data:image/png;base64,mask', getContext: () => ({
    clearRect() {}, fillRect() {}, beginPath() {}, rect() {}, fill() {}, drawImage() {}, set fillStyle(v) {},
  })});
  const fog = canvas(), tokens = new Map([['shown', {data: {x: 6, y: 5}}], ['hidden', {data: {x: 8, y: 5, hidden: true}}]]);
  let actual;
  const bindings = {fog, tokens, map: {width: 10, height: 10}, gridSvg: {style: {}}, CELL: SCALE, updateSightBlockers() {},
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
      assert.equal(left.pixel(7.5 * SCALE - 1, py), true);
      assert.equal(left.pixel(7.5 * SCALE, py), false);
      assert.equal(right.pixel(30.5 * SCALE - 1, py), false);
      // The horizontal branch at y=8.5 rasterizes into row 8. Its end cap
      // reaches x=31 and must close that join too.
      if(py<8*SCALE || py>=9*SCALE) assert.equal(right.pixel(30.5*SCALE,py),true);
      else {assert.equal(right.pixel(31*SCALE-1,py),false);assert.equal(right.pixel(31*SCALE,py),true);}
    }
    // The lowest start defines the union boundary through the far cap tip (8,13).
    for (let px = 8 * SCALE + 2; px < 9 * SCALE; px++) {
      const y = (14.5 + ((px + 0.5) / SCALE - 1.5) * (13 - 14.5) / (8 - 1.5)) * SCALE;
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
    teamIndex: () => 0, enc: encodeURIComponent, currentViewer: h.currentViewer, isGMView: h.isGMView, isOwnedActor: h.isOwnedActor,
    viewerStore: h.viewerStore, actors: () => app.state.presentation.actors};
  const built = new Function(...Object.keys(bindings),
    source.slice(start, end) + '\nreturn {fogGeometry, tabletopUrl};')(...Object.values(bindings));
  const {fogGeometry, tabletopUrl} = built;
  const seen = new Uint8Array(100).fill(1);
  const normal = fogGeometry(seen);
  assert.equal(Math.max(...normal.polygons[0].points.map(([x]) => x)), 5.5);
  assert.equal(normal.squareFog, undefined);
  assert.equal(tabletopUrl('match:abc'), '/tabletop?match=match%3Aabc&view=view-one');
  location.search = '?fogSquares=1';
  const diagnostic=fogGeometry(seen);
  assert.equal(diagnostic.squareFog,true);
  assert.equal(diagnostic.polygons,undefined);
  assert.equal(diagnostic.blockerGeometry,normal.blockerGeometry,'same sources in square diagnostic mode');
  assert.equal(diagnostic.blockerHeights,app.state.fog_geometry);
  assert.deepEqual(fogGeometry(null), {polygons: []}, 'non-GM view without a perception mask keeps main\'s empty geometry');
  // Loading a fight rewrites the address bar; the debug flag has to survive it.
  assert.equal(tabletopUrl('match:abc'), '/tabletop?match=match%3Aabc&view=view-one&fogSquares=1');
  location.search = '?fogSquares=0';
  assert.equal(fogGeometry(seen).polygons, normal.polygons, 'cached geometry remains independent of debug mask');
  assert.equal(tabletopUrl('match:abc'), '/tabletop?match=match%3Aabc&view=view-one');
});
