// node --test APP/static/tabletop/zones.test.mjs
// Zones on the table (owner 2026-09-27): the pure parts of zones.js, and that every material,
// layer, tile and floor paints deterministically without Math.random (zonepaint.js, textures.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';

test('zone labels retain shape talents and every augment', () => {
  const zone = {trigger_profile: {kind: 'TYPED', name: 'Darkness', talents: ['Hungry Darkness'],
    augments: ['Directional Darkness', 'Greater Darkness']}};
  const look = zoneLook(zone);
  assert.equal(look.name, 'Darkness · Hungry Darkness + Directional Darkness + Greater Darkness');
  assert.equal(zoneTooltip(zone, look).title, look.name);
  assert.equal(zoneLook({trigger_profile: {name: 'Hungry Darkness', talents: ['Hungry Darkness'],
    augments: ['Directional Darkness']}}).name, 'Hungry Darkness · Directional Darkness');
});
import {
  MATERIALS, MATERIAL_TINT, DARKNESS_FILL, darknessComposition, hashSeed, zoneList, zoneLook, zonePresentation, roundsLeft, zoneTooltip, cellOutline, outlinePath, hatchPath, labelAnchor,
  cellBounds, normalizeLight, wallRule, wallSightCells, wallAxis, effectText,
} from './zones.js?v=r24';
import {paintMaterial, paintLayer, paintTile, paintWall, materialLayers, hazeTint} from './zonepaint.js?v=r24';
import {opacityGrid, visibleCells, lineOfSight} from './vision.js?v=rel6-2';
import {STYLES, paintFloor} from './textures.js';
import {createBoard, CELL} from './board.js';
import {previewTerrainZones} from './mapeditor-zones.js';

test('current map scenery metadata uses natural presentation in both table and editor', () => {
  const [preview] = previewTerrainZones([{material: 'terrain:ash', cells: [[2, 3]]}], [{name: 'ash', material: 'ash'}]);
  assert.deepEqual(zonePresentation(preview), {mapTerrain: true, hatch: false, label: false, softRim: false});
  assert.deepEqual(zonePresentation(preview, true), {mapTerrain: true, hatch: true, label: true, softRim: false});
  assert.equal(zonePresentation({...preview, owner_id: 'actor:a'}).mapTerrain, true);
  assert.equal(zonePresentation({...preview, owner_id: 'actor:a', source_definition_id: 'action:typed.ash'}).mapTerrain, false);
});

test('painted zones are classified by map provenance; techniques and blockers keep their identities', () => {
  const mapTerrain = {zone_id: 'zone:map:1', source_definition_id: 'system:battlefield.terrain', owner_id: 'map', trigger_profile: {shape: 'painted'}};
  const preview = {zone_id: 'preview:ash', source_definition_id: 'system:battlefield.terrain', owner_id: 'map', trigger_profile: {shape: 'painted'}};
  const technique = {zone_id: 'zone:gate:actor:a:12:0', source_definition_id: 'action:typed.vermilion_gate.guardian_at_the_gate', owner_id: 'actor:a', trigger_profile: {shape: 'painted', difficult: 'hostile'}};
  const objectWall = {zone_id: 'zone:object:door', source_definition_id: 'system:battlefield.object', owner_id: 'map', trigger_profile: {shape: 'painted', wall: {blocks_movement: true}}};
  const legacy = {zone_id: 'old-zone', trigger_profile: {shape: 'painted'}};
  assert.deepEqual(zonePresentation(mapTerrain), {mapTerrain: true, hatch: false, label: false, softRim: false});
  assert.equal(zonePresentation(preview).mapTerrain, true);
  assert.deepEqual(zonePresentation(technique), {mapTerrain: false, hatch: false, label: false, softRim: true});
  assert.deepEqual(zonePresentation(objectWall), {mapTerrain: false, hatch: false, label: false, softRim: false});
  assert.equal(zonePresentation(legacy).mapTerrain, false);
  assert.deepEqual(zonePresentation(mapTerrain, true), {mapTerrain: true, hatch: true, label: true, softRim: false});
  assert.deepEqual(zonePresentation(technique, true), {mapTerrain: false, hatch: true, label: true, softRim: false});
  assert.deepEqual(zonePresentation(objectWall, true), {mapTerrain: false, hatch: true, label: true, softRim: false});
});

// Supplementary wiring check: it reads the sources to confirm the branches, handlers, cache
// tokens and CSS rule are still spelled as expected.  It does not render anything, so the
// behaviour those branches produce is asserted by the DOM tests further down.
test('wiring: the renderer branches, controls and cache tokens are present in the sources', async () => {
  const [board, css, tabletop, editor, tableHtml, editorHtml] = await Promise.all([
    readFile(new URL('./board.js', import.meta.url), 'utf8'),
    readFile(new URL('./tabletop.css', import.meta.url), 'utf8'),
    readFile(new URL('./tabletop.js', import.meta.url), 'utf8'),
    readFile(new URL('./mapeditor.js', import.meta.url), 'utf8'),
    readFile(new URL('./tabletop.html', import.meta.url), 'utf8'),
    readFile(new URL('./mapeditor.html', import.meta.url), 'utf8'),
  ]);
  assert.match(board, /presentation\.softRim \? " tt-zone-edge-natural"/);
  assert.match(board, /presentation\.hatch && look\.difficult/);
  assert.match(board, /if \(!presentation\.label\) label\.classList\.add\("tt-zone-label-hover"\)/);
  assert.match(board, /localStorage\.setItem\("tt-rules-overlay", String\(rulesOverlay\)\)/);
  assert.match(board, /setZones\(lastZones, lastZoneOptions\)/);
  assert.match(board, /zoneTooltip\(entry\.zone, entry\.look/);
  assert.match(css, /\.tt-zone-edge-natural \.tt-zone-outline \{[^}]*stroke-width: \.055;/);
  const rimSquares = Number(css.match(/\.tt-zone-edge-natural \.tt-zone-outline \{[^}]*stroke-width: ([.\d]+);/)?.[1]);
  assert.ok(rimSquares > 0 && rimSquares < 1, 'SVG rim width is a fraction of one square');
  assert.equal(rimSquares * 64, 3.52, '0.055 square is 3.52 screen pixels at zoom 1');
  for (const [source, button] of [[tabletop, '#ttRulesOverlay'], [editor, '#meRulesOverlay']]) {
    assert.match(source, new RegExp(`${button.slice(1)}.*addEventListener\\("click"`));
    assert.match(source, /event\.shiftKey && event\.key\.toLowerCase\(\) === "r"/);
    assert.match(source, /board\.setRulesOverlay\(/);
  }
  assert.match(tabletop, /readPreference\("tt-rules-overlay"\) === "true"/);
  assert.match(editor, /localStorage\.getItem\("tt-rules-overlay"\) === "true"/);
  for (const html of [tableHtml, editorHtml]) {
    assert.match(html, /<button id="(?:tt|me)RulesOverlay"[^>]*>Show rules on map<\/button>/);
  }
  assert.match(tableHtml, /tabletop\.css\?v=rel6-2/);
  assert.match(editorHtml, /tabletop\.css\?v=rel6-2/);
  assert.match(editorHtml, /mapeditor\.js\?v=rel6-2/);
  assert.match(editor, /board\.setZones\(previewTerrainZones\(doc\.materials, TERRAINS, doc\.natural_haze === true\)\)/);
  const preview = await readFile(new URL('./mapeditor-zones.js', import.meta.url), 'utf8');
  assert.match(preview, /owner_id: null/);
  assert.match(preview, /map: true, natural_haze: naturalHaze === true/);
});

const ashfall = {
  zone_id: 'zone:typed:actor:factory.x:412', source_definition_id: 'action:typed.factory.x.ASH_BASE_ASHFALL', owner_id: 'actor:factory.x',
  center: {x: 9, y: 6}, radius_cells: 1, affected_cells: [{x: 9, y: 5}, {x: 8, y: 6}, {x: 9, y: 6}, {x: 10, y: 6}, {x: 9, y: 7}],
  concentration_link: true, duration_rounds: 10, created_round: 2, active: true,
  trigger_profile: {kind: 'TYPED', name: 'Ashfall', terrain: ['ash terrain'], difficult: 'hostile', obscured: 'light', shape: 'sphere',
    size_ft: 15, follows_owner: false, color: '#9a8f86', visual: {material: 'ash', obscured: 'light', light: null, darkness: false}},
};

// A small deterministic generator for property tests.
function lcg(seed) { let s = seed >>> 0; return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296); }

const loopArea = loop => loop.reduce((sum, [x, y], i) => { const [nx, ny] = loop[(i + 1) % loop.length]; return sum + (x * ny - nx * y); }, 0) / 2;

test('hashSeed is stable, 32-bit and spreads ids', () => {
  assert.equal(hashSeed('zone:a'), hashSeed('zone:a'));
  assert.notEqual(hashSeed('zone:a'), hashSeed('zone:b'));
  assert.ok(Number.isInteger(hashSeed('x')) && hashSeed('x') >= 0 && hashSeed('x') < 2 ** 32);
});

test('zoneList accepts an array or an id-keyed object and skips what cannot be drawn', () => {
  const inactive = {...ashfall, zone_id: 'z2', active: false};
  const empty = {...ashfall, zone_id: 'z3', affected_cells: []};
  assert.deepEqual(zoneList([ashfall, inactive, empty, 'zone:id-only', null]).map(z => z.zone_id), [ashfall.zone_id]);
  assert.deepEqual(zoneList({[ashfall.zone_id]: ashfall}).map(z => z.zone_id), [ashfall.zone_id]);
  assert.deepEqual(zoneList(undefined), []);
});

test('zoneLook reads a typed zone and defaults everything else', () => {
  const look = zoneLook(ashfall);
  assert.equal(look.material, 'ash');
  assert.equal(look.difficult, 'hostile');
  assert.equal(look.obscured, 'light');
  assert.equal(look.darkness, false);
  assert.equal(look.light, null);
  assert.equal(look.name, 'Ashfall');
  assert.equal(look.color, '#9a8f86');
  assert.equal(look.concentration, true);

  const legacy = zoneLook({zone_id: 'z', source_definition_id: 'spell.cloud_of_daggers', trigger_profile: {kind: 'SPELL'}});
  assert.equal(legacy.material, 'generic');
  assert.equal(legacy.typed, false);
  assert.equal(legacy.name, 'Cloud Of Daggers');
  assert.equal(legacy.color, '#8f97a3');

  const odd = zoneLook({zone_id: 'z', trigger_profile: {kind: 'TYPED', difficult: true, color: 'red', visual: {material: 'plasma', obscured: 'Heavily', darkness: true,
    light: {radius_ft: 20, color: '#ffd28a', level: 'dim'}}}});
  assert.equal(odd.material, 'generic');
  assert.equal(odd.difficult, 'all');
  assert.equal(odd.obscured, 'heavy');
  assert.equal(odd.darkness, true);
  assert.equal(odd.color, '#8f97a3');  // "red" is not a hex colour: fall back to the material tint
  assert.deepEqual(odd.light, {radiusFt: 20, radiusCells: 4, color: '#ffd28a', level: 'dim'});
});

test('normalizeLight rejects unusable lights and defaults colour and level', () => {
  assert.equal(normalizeLight(null), null);
  assert.equal(normalizeLight({radius_ft: 0}), null);
  assert.equal(normalizeLight({radius_ft: 'far'}), null);
  assert.deepEqual(normalizeLight({radius_ft: 15}), {radiusFt: 15, radiusCells: 3, color: '#ffd28a', level: 'bright'});
});

test('roundsLeft counts down from the round the zone was made', () => {
  assert.equal(roundsLeft(ashfall, 2), 10);
  assert.equal(roundsLeft(ashfall, 5), 7);
  assert.equal(roundsLeft(ashfall, 40), 0);
  assert.equal(roundsLeft({...ashfall, duration_rounds: null}, 5), null);
});

test('zoneTooltip says what the zone does', () => {
  const tip = zoneTooltip(ashfall, zoneLook(ashfall), {round: 5, owner: 'Tang Wei'});
  assert.equal(tip.title, 'Ashfall');
  assert.deepEqual(tip.lines, ['Ash terrain', 'Difficult terrain (for foes)', "Lightly obscured: creatures inside are still visible. Attacks against creatures you can't see have Disadvantage. Senses that perceive the target without sight bypass this concealment within their range; senses that see through this effect bypass its sight blocking.", '7 rounds left', 'Concentration', 'From Tang Wei']);
  const lit = {...ashfall, duration_rounds: 3, concentration_link: false,
    trigger_profile: {kind: 'TYPED', name: 'Dawn Halo', difficult: 'all', visual: {material: 'radiance', obscured: 'heavy', darkness: true, light: {radius_ft: 20, level: 'bright'}}}};
  assert.deepEqual(zoneTooltip(lit, zoneLook(lit), {round: 4}).lines, ['Difficult terrain', "Heavily obscured (Dawn Halo): you can't see into it. Creatures inside cannot be seen from outside or by others inside. Attacks against creatures you can't see have Disadvantage. Senses that perceive the target without sight bypass this concealment within their range; senses that see through this effect bypass its sight blocking.", 'Magical darkness', 'Bright light, 20 ft', '1 round left']);
});

test('cellOutline traces square edges exactly', () => {
  assert.deepEqual(cellOutline([{x: 2, y: 3}]), [[[2, 3], [3, 3], [3, 4], [2, 4]]]);
  const block = cellOutline([[0, 0], [1, 0], [0, 1], [1, 1]]);
  assert.equal(block.length, 1);
  assert.equal(block[0].length, 4);
  const ell = cellOutline([[0, 0], [0, 1], [1, 1]]);
  assert.equal(ell.length, 1);
  assert.equal(ell[0].length, 6);
  // A ring: an outer loop and a hole, wound opposite ways.
  const ring = [];
  for (let y = 0; y < 3; y += 1) for (let x = 0; x < 3; x += 1) if (x !== 1 || y !== 1) ring.push([x, y]);
  const loops = cellOutline(ring);
  assert.equal(loops.length, 2);
  assert.deepEqual(loops.map(loopArea).sort((a, b) => a - b), [-1, 9]);
  // Squares touching only at a corner stay separate loops.
  assert.equal(cellOutline([[0, 0], [1, 1]]).length, 2);
  assert.match(outlinePath(cellOutline([[0, 0]])), /^M0 0L1 0L1 1L0 1Z$/);
});

test('cellOutline encloses exactly the squares for random shapes', () => {
  const rand = lcg(42);
  for (let trial = 0; trial < 200; trial += 1) {
    const cells = new Map();
    for (let index = 0; index < 1 + Math.floor(rand() * 30); index += 1) {
      const x = Math.floor(rand() * 7), y = Math.floor(rand() * 7);
      cells.set(`${x},${y}`, {x, y});
    }
    const loops = cellOutline([...cells.values()]);
    const area = loops.reduce((sum, loop) => sum + loopArea(loop), 0);
    assert.equal(area, cells.size, `trial ${trial}`);
    for (const loop of loops) for (const [x, y] of loop) assert.ok(Number.isInteger(x) && Number.isInteger(y));
  }
});

test('hatchPath, labelAnchor and cellBounds', () => {
  assert.equal(hatchPath([[1, 2]]), 'M1 2.5L1.5 2M1.5 3L2 2.5');
  assert.deepEqual(labelAnchor(ashfall.affected_cells), {x: 9.5, y: 5});
  assert.deepEqual(cellBounds(ashfall.affected_cells), {minX: 8, minY: 5, maxX: 10, maxY: 7, width: 3, height: 3});
});

// A 2D context that records every call, so painting can be compared run to run in node.
function recorder() {
  const log = [];
  const images = [];
  const round = value => (typeof value === 'number' ? Math.round(value * 1e6) / 1e6 : typeof value === 'object' ? 'obj' : value);
  const digest = data => { let h = 0x811c9dc5; for (let i = 0; i < data.length; i += 1) h = Math.imul(h ^ data[i], 0x01000193) >>> 0; return h; };
  const ctx = new Proxy({}, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (prop === 'createImageData') return (w, h) => { const image = {width: w, height: h, data: new Uint8ClampedArray(w * h * 4)}; images.push(image); return image; };
      if (prop === 'putImageData') return image => log.push(['putImageData', image.width, image.height, digest(image.data)]);
      if (prop === 'createLinearGradient' || prop === 'createRadialGradient') {
        return (...args) => { log.push([prop, ...args.map(round)]); return {addColorStop: (...stop) => log.push(['stop', ...stop.map(round)])}; };
      }
      return (...args) => log.push([prop, ...args.map(round)]);
    },
    set(target, prop, value) { target[prop] = value; log.push(['set', prop, round(value)]); return true; },
  });
  return {ctx, log, images};
}

function spec(seed) {
  const cells = [];
  for (let y = 4; y <= 8; y += 1) for (let x = 5; x <= 9; x += 1) if ((x - 7) ** 2 + (y - 6) ** 2 <= 6) cells.push([x, y]);
  return {x0: 4, y0: 3, w: 7, h: 7, ppc: 6, seed, cells, center: {x: 7, y: 6}, radius: 2, color: [154, 143, 134]};
}

function paintAll(material, seed) {
  const base = recorder();
  const kit = paintMaterial(base.ctx, material, spec(seed));
  const logs = [base.log];
  materialLayers(material).forEach((layer, index) => {
    const layerLog = recorder();
    if (layer.canvas) paintLayer(layerLog.ctx, layer.canvas, spec(seed), layer.variant || 0, kit);
    else paintTile(layerLog.ctx, layer.tile, 32, seed + index, layer.tint || hazeTint(material, [154, 143, 134]));
    logs.push(layerLog.log);
  });
  return {logs, images: base.images};
}

test('a leaf canopy uses the existing leafy vine material on the map', () => {
  const canopy = {zone_id: 'canopy', trigger_profile: {kind: 'TYPED', name: 'Canopy of Ten Thousand Leaves',
    visual: {material: 'vines'}}};
  const look = zoneLook(canopy);
  assert.equal(look.material, 'vines');
  assert.equal(look.color, MATERIAL_TINT.vines);
  const calls = paintAll(look.material, hashSeed(canopy.zone_id)).logs.flat();
  assert.ok(calls.some(call => call[0] === 'set' && call[1] === 'strokeStyle' && call[2] === 'rgb(62,104,40)'),
    'vine stems are stroked in the vine green');
  assert.ok(calls.some(call => call[0] === 'set' && call[1] === 'fillStyle' && String(call[2]).startsWith('rgb(')),
    'ivy leaves are filled');
  assert.ok(calls.some(call => call[0] === 'ellipse'), 'leaves are drawn as ellipses');
});

test('every material paints deterministically, without Math.random, and paints something', () => {
  const original = Math.random;
  Math.random = () => { throw new Error('Math.random used while painting'); };
  try {
    for (const material of MATERIALS) {
      const first = paintAll(material, hashSeed('zone:one'));
      const again = paintAll(material, hashSeed('zone:one'));
      const other = paintAll(material, hashSeed('zone:two'));
      assert.deepEqual(again.logs, first.logs, `${material} repaints identically`);
      assert.notDeepEqual(other.logs, first.logs, `${material} differs between zones`);
      const alpha = first.images[0].data.filter((_, index) => index % 4 === 3);
      assert.ok(alpha.some(value => value > 0), `${material} paints some pixels`);
    }
  } finally {
    Math.random = original;
  }
});

test('the sphere terrain materials the compiler emits are known and paint as themselves', () => {
  // Shatter Earth / Broken Ground, Falling Star, Glass Desert Judgment, the Wax sphere (2026-09-27).
  const generic = paintAll('generic', hashSeed('zone:one')).logs;
  for (const material of ['cracked', 'crater', 'glass', 'wax']) {
    assert.ok(MATERIALS.includes(material), `${material} is a known material`);
    const look = zoneLook({zone_id: 'z', trigger_profile: {kind: 'TYPED', visual: {material}}});
    assert.equal(look.material, material);
    assert.equal(look.color, MATERIAL_TINT[material]);
    assert.notDeepEqual(paintAll(material, hashSeed('zone:one')).logs, generic, `${material} has a painter of its own`);
  }
  for (const material of MATERIALS) assert.match(MATERIAL_TINT[material] || '', /^#[0-9a-f]{6}$/, `${material} has a fallback tint`);
  // Glass glints and wax candle flames come from the base's shared kit, so the layers draw something.
  for (const material of ['glass', 'wax']) assert.ok(paintAll(material, hashSeed('zone:one')).logs[1].length > 20, `${material} layer paints`);
});

test('the drifting tiles and haze tints cover every kind in use', () => {
  for (const kind of ['clouds', 'haze', 'heavy', 'caustics', 'embers', 'flakes', 'wisps', 'motes', 'sparkles', 'streaks', 'tentacles']) {
    const a = recorder(), b = recorder();
    paintTile(a.ctx, kind, 24, 7, [120, 120, 120]);
    paintTile(b.ctx, kind, 24, 7, [120, 120, 120]);
    assert.ok(a.log.length > 0, kind);
    assert.deepEqual(a.log, b.log, kind);
  }
  for (const material of MATERIALS) assert.equal(hazeTint(material, [10, 20, 30]).length, 3);
});

test('the new floor styles exist under their whitelisted keys and paint', () => {
  const added = {lava_rock: 'Volcanic rock', marsh: 'Marsh', bamboo: 'Bamboo forest floor', dirt_road: 'Dirt road', marble: 'Marble hall',
    dark_stone: 'Dark stone', ice: 'Frozen lake', shallows: 'Shallow water', mountain: 'Mountain rock', graveyard: 'Graveyard'};
  for (const [key, label] of Object.entries(added)) assert.equal(STYLES[key], label);
  for (const key of ['flagstone', 'tiles', 'wood', 'grass', 'sand', 'cave', 'snow', 'plain']) assert.ok(STYLES[key], key);
  const previous = globalThis.document;
  const painted = [];
  globalThis.document = {createElement: () => {
    const canvas = {width: 0, height: 0, getContext: () => { const r = recorder(); painted.push(r); return r.ctx; }};
    return canvas;
  }};
  try {
    for (const key of Object.keys(added)) {
      painted.length = 0;
      paintFloor(key, 5, 6, 4);
      const image = painted[0].images[0];
      const pixels = new Set();
      for (let index = 0; index < image.data.length; index += 4 * 97) pixels.add(image.data[index] * 65536 + image.data[index + 1] * 256 + image.data[index + 2]);
      assert.ok(pixels.size > 20, `${key} is textured, not flat`);
      assert.ok(image.data.every((value, index) => index % 4 !== 3 || value === 255), `${key} is opaque`);
    }
  } finally {
    globalThis.document = previous;
  }
});

// ---------------------------------------------------------------- walls (owner 2026-09-27)
const line = (x0, y0, w, h) => { const out = []; for (let y = y0; y < y0 + h; y += 1) for (let x = x0; x < x0 + w; x += 1) out.push({x, y}); return out; };
const wallZone = (id, material, cells, rule, extra = {}) => ({
  zone_id: id, source_definition_id: `action:typed.x.${id}`, owner_id: 'actor:a', center: cells[0], radius_cells: 0, affected_cells: cells,
  active: true, duration_rounds: 10, created_round: 1, ...extra,
  trigger_profile: {kind: 'TYPED', name: id, visual: {material, wall: true, darkness: material === 'darkness'}, ...(rule ? {wall: rule} : {})},
});
const lava = wallZone('Lava Wall', 'lava', line(8, 2, 1, 8), {blocks_movement: true, thick_ft: 5, length_ft: 40});
const smoke = wallZone('Smoke Wall', 'smoke', line(12, 2, 2, 3), {blocks_sight: true, thick_ft: 10, length_ft: 15});
const dune = wallZone('Dune Wall', 'sand', line(2, 12, 6, 1), {cover: true, move_cost: 4, thick_ft: 5, length_ft: 30});

test('wallRule reads a wall zone into solid, screen or low, and leaves other zones alone', () => {
  assert.deepEqual(wallRule(lava), {blocksMovement: true, blocksSight: false, obscures: null, seeThrough: false, cover: false, moveCost: null, kind: 'solid'});
  assert.deepEqual(wallRule(smoke), {blocksMovement: false, blocksSight: true, obscures: 'all', seeThrough: false, cover: false, moveCost: null, kind: 'screen'});
  assert.deepEqual(wallRule(dune), {blocksMovement: false, blocksSight: false, obscures: null, seeThrough: false, cover: true, moveCost: 4, kind: 'low'});
  // Drawn as a wall when only the visual says so, but it claims to block nothing.
  assert.equal(wallRule(wallZone('w', 'stone', line(0, 0, 2, 1), null)).kind, 'low');
  assert.equal(wallRule(wallZone('w', 'stone', line(0, 0, 2, 1), {move_cost: 1})).moveCost, null);
  assert.equal(wallRule(ashfall), null);
  assert.equal(wallRule({zone_id: 'z'}), null);
  assert.equal(zoneLook(lava).wall.kind, 'solid');
  assert.equal(zoneLook(ashfall).wall, null);
});

test('the tooltip says what a wall stops', () => {
  assert.deepEqual(zoneTooltip(lava, zoneLook(lava), {round: 1}).lines, ['Wall: blocks movement and sight', '10 rounds left']);
  assert.deepEqual(zoneTooltip(smoke, zoneLook(smoke), {round: 1}).lines, ['Wall: blocks sight, can be walked through', 'Attacks through it have Disadvantage', '10 rounds left']);
  assert.deepEqual(zoneTooltip(dune, zoneLook(dune), {round: 1}).lines, ['Gives cover', 'Costs 4× movement', '10 rounds left']);
});

test('wallSightCells: solid and sight-blocking walls hide, cover walls and other zones do not', () => {
  const inactive = {...lava, zone_id: 'gone', active: false, affected_cells: line(0, 0, 1, 1)};
  const cells = wallSightCells([lava, smoke, dune, ashfall, inactive]);
  assert.deepEqual(cells, [...line(8, 2, 1, 8), ...line(12, 2, 2, 3)].map(({x, y}) => [x, y]).sort((a, b) => a[1] - b[1] || a[0] - b[0]));
  // As in the engine: a fighter standing in a solid wall's square keeps it open; smoke hides even so.
  const standing = wallSightCells([lava, smoke], {occupied: [{x: 8, y: 5}, [12, 2]]});
  assert.ok(!standing.some(([x, y]) => x === 8 && y === 5));
  assert.ok(standing.some(([x, y]) => x === 12 && y === 2));
  // Overlapping walls give each square once; an id-keyed object works as the list does.
  assert.equal(wallSightCells({a: lava, b: {...lava, zone_id: 'Lava Wall 2'}}).length, 8);
  assert.deepEqual(wallSightCells([]), []);
  assert.deepEqual(wallSightCells(undefined), []);
});

test('walls block the fog and the line of sight hint; with no walls the map alone decides', () => {
  const width = 20, height = 14, viewer = {x: 3, y: 6};
  const mapOnly = opacityGrid(width, height, [[[5, 0]], []]);
  assert.deepEqual(opacityGrid(width, height, [[[5, 0]], [], wallSightCells([])]), mapOnly);
  assert.deepEqual(opacityGrid(width, height, [[[5, 0]], [], wallSightCells([dune, ashfall])]), mapOnly);
  const opaque = opacityGrid(width, height, [[[5, 0]], [], wallSightCells([lava, smoke])]);
  const seen = visibleCells(width, height, opaque, [viewer]);
  assert.equal(seen[6 * width + 12], 0, 'hidden behind the lava wall');
  assert.equal(seen[6 * width + 8], 1, 'the wall itself is seen');
  assert.equal(seen[12 * width + 9], 1, 'seen past the end of the wall');
  assert.equal(seen[3 * width + 16], 0, 'hidden behind the smoke wall');
  assert.equal(lineOfSight(width, opaque, 3, 6, 12, 6), false);
  assert.equal(lineOfSight(width, mapOnly, 3, 6, 12, 6), true);
});

test('wallAxis follows the long side', () => {
  assert.equal(wallAxis(line(2, 2, 8, 1).map(({x, y}) => [x, y])), 'x');
  assert.equal(wallAxis(line(2, 2, 2, 6).map(({x, y}) => [x, y])), 'y');
  assert.equal(wallAxis([[4, 4]]), 'x');
});

test('every wall paints deterministically, without Math.random, along either axis', () => {
  const wallSpec = (seed, axis) => {
    const cells = axis === 'x' ? [[3, 4], [4, 4], [5, 4], [6, 4], [3, 5], [4, 5], [5, 5], [6, 5]] : [[4, 2], [4, 3], [4, 4], [4, 5], [4, 6]];
    return {x0: 2, y0: 1, w: 6, h: 7, ppc: 6, seed, cells, center: {x: 4, y: 4}, radius: 0, color: [154, 143, 134]};
  };
  const paint = (material, seed, axis, kind) => {
    const r = recorder();
    paintMaterial(r.ctx, material, wallSpec(seed, axis));
    const before = r.log.length;
    paintWall(r.ctx, material, wallSpec(seed, axis), {kind}, axis);
    return {log: r.log, added: r.log.length - before};
  };
  const original = Math.random;
  Math.random = () => { throw new Error('Math.random used while painting'); };
  try {
    for (const material of ['lava', 'sand', 'ice', 'glass', 'wind', 'water', 'stone', 'glyphs', 'darkness', 'smoke', 'ash', 'generic']) {
      for (const axis of ['x', 'y']) for (const kind of ['solid', 'screen', 'low']) {
        const first = paint(material, hashSeed('zone:one'), axis, kind);
        assert.deepEqual(paint(material, hashSeed('zone:one'), axis, kind).log, first.log, `${material} ${axis} ${kind} repaints identically`);
        if (kind !== 'screen' || !['ash', 'generic'].includes(material)) assert.ok(first.added > 0, `${material} ${axis} ${kind} draws a wall`);
      }
    }
    for (const material of ['lava', 'sand', 'ice', 'wind', 'water', 'stone', 'glyphs', 'smoke', 'darkness']) {
      assert.notDeepEqual(paint(material, hashSeed('zone:one'), 'x', 'solid').log, paint(material, hashSeed('zone:two'), 'x', 'solid').log, `${material} wall differs between zones`);
    }
  } finally {
    Math.random = original;
  }
});

test('see-through walls, walls that hide only from foes, and openings (owner 2026-09-27)', () => {
  const force = wallZone('force', 'glass', line(20, 2, 1, 6), {blocks_movement: true, see_through: true});
  const monsoon = wallZone('monsoon', 'water', line(24, 2, 1, 6), {obscures: 'hostile', difficult: 'hostile'});
  const puzzle = {...wallZone('puzzle', 'stone', line(28, 2, 1, 3), {blocks_movement: true}), trigger_profile: {
    ...wallZone('puzzle', 'stone', line(28, 2, 1, 3), {blocks_movement: true}).trigger_profile, openings: [{cell: [28, 3], by: 'a'}]}};
  assert.deepEqual(wallSightCells([force]), []);  // you see through a Force Wall
  assert.equal(wallRule(monsoon).kind, 'screen');
  assert.deepEqual(wallSightCells([monsoon], {hostile: () => false}), []);  // its creator's side sees through it
  assert.equal(wallSightCells([monsoon], {hostile: () => true}).length, 6);
  assert.deepEqual(wallSightCells([puzzle]), [[28, 2], [28, 4]]);  // the opened section is clear
});

test('the tooltip says what the ground does to you (owner 2026-09-27)', () => {
  const ash = {zone_id: 'ash', active: true, owner_id: 'a', affected_cells: [{x: 1, y: 1}], trigger_profile: {
    kind: 'TYPED', name: 'Ashfall', terrain: ['ash terrain'], difficult: 'hostile', obscured: 'light', visual: {material: 'ash'},
    numbers: {save_dc: 16, pb: 4, cl: 10},
    triggers: [{name: 'Soot in the Lungs', on: ['enter', 'start'], who: 'hostile', effects: [{type: 'save', ability: 'con',
      on_fail: [{type: 'condition', condition: 'smothered'}], on_success: [{type: 'condition', condition: 'reaction_denied'}]}]}],
    move_through: {min_ft: 10, ability: 'CON', on_fail: [{type: 'condition', condition: 'reaction_denied'}]}}};
  const asFoe = zoneTooltip(ash, zoneLook(ash), {round: 1, foe: true}).lines;
  assert.ok(asFoe.includes('Difficult terrain for you'));
  assert.ok(asFoe.some(line => line.startsWith('Soot in the Lungs: Entering it or starting a turn in it (you')
    && line.includes('Constitution save DC 16: Soot fills its lungs')
    && line.includes("It can't take Reactions on a failure")
    && line.includes("take Reactions on a success")));
  assert.ok(asFoe.some(line => line.startsWith('Moving more than 10 ft through it (you') && line.includes('take Reactions')));
  const asOwner = zoneTooltip(ash, zoneLook(ash), {round: 1, foe: false}).lines;
  assert.ok(asOwner.includes('Difficult terrain for your foes (not you)'));
  assert.equal(effectText([{type: 'damage', dice: {count: 2, sides: 6}, damage_types: ['fire']}, {type: 'condition', condition: 'burning'}]),
    "2d6 fire damage, it is on fire: it takes Fire damage at the start of each of its turns for the effect's duration."
    + " It or an adjacent creature can use an Action to extinguish one Burn.");
  assert.equal(effectText([{type: 'damage', formula: 'pb', damage_types: ['slashing']}], {pb: 4}), '4 slashing damage');
});

// ---------------------------------------------------------------- rendering (owner 2026-09-29, natural terrain)
// The tests above read sources.  These drive the real renderer: a board is built, the
// fixtures are handed to it as presentation.zones, and the DOM it produces is inspected.
// board.js owns the painting, so "map scenery has no outline" is a claim about board.js.

// A DOM small enough to run in node, and faithful enough that board.js cannot tell the
// difference: real class lists, real attribute storage, real parent/child links.  Only the
// canvas is faked (with the recorder above), since no test here looks at pixels.
function stubStyle() {
  return {setProperty(name, value) { this[name] = value; }, getPropertyValue(name) { return this[name] ?? ''; }};
}

class StubElement {
  constructor(tag) {
    this.tagName = String(tag);
    this.className = '';
    this._text = '';
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.style = stubStyle();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.width = 0;
    this.height = 0;
    this.offsetWidth = 180;
    this.offsetHeight = 90;
    this._context = null;
  }
  // Like the real DOM: textContent reads back the descendants, and writing it replaces them.
  get textContent() { return this.childNodes.length ? this.childNodes.map(child => child.textContent).join('') : this._text; }
  set textContent(value) { for (const child of [...this.childNodes]) this.removeChild(child); this._text = String(value); }
  get classList() {
    const owner = this;
    const read = () => owner.className.split(/\s+/).filter(Boolean);
    const write = items => { owner.className = [...new Set(items)].join(' '); };
    return {
      add(...names) { write([...read(), ...names]); },
      remove(...names) { write(read().filter(item => !names.includes(item))); },
      contains(name) { return read().includes(name); },
      toggle(name, force) {
        const items = read();
        const next = force === undefined ? !items.includes(name) : Boolean(force);
        write(next ? [...items, name] : items.filter(item => item !== name));
        return next;
      },
    };
  }
  appendChild(child) { if (child.parentNode) child.parentNode.removeChild(child); child.parentNode = this; this.childNodes.push(child); return child; }
  removeChild(child) {
    const at = this.childNodes.indexOf(child);
    if (at >= 0) this.childNodes.splice(at, 1);
    if (child.parentNode === this) child.parentNode = null;
    return child;
  }
  replaceChildren(...nodes) { for (const child of [...this.childNodes]) this.removeChild(child); for (const node of nodes) this.appendChild(node); }
  remove() { this.parentNode?.removeChild(this); }
  // The real DOM keeps setAttribute("class", ...) and className in step; board.js paints its
  // SVG layers that way, so the stub has to as well or classList would never see an outline.
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === 'class') this.className = String(value);
  }
  getAttribute(name) { return name === 'class' ? this.className : (this.attributes.has(name) ? this.attributes.get(name) : null); }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { this.attributes.delete(name); }
  getBoundingClientRect() {
    if (this.classList.contains('tt-hovercard')) {
      const left = parseFloat(this.style.left) || 0, top = parseFloat(this.style.top) || 0;
      return {left, top, right: left + this.offsetWidth, bottom: top + this.offsetHeight,
        width: this.offsetWidth, height: this.offsetHeight};
    }
    return {left: 0, top: 0, right: 1280, bottom: 896, width: 1280, height: 896};
  }
  getContext() { if (!this._context) this._context = recorder().ctx; return this._context; }
  toDataURL() { return 'data:image/png;base64,stub'; }
  addEventListener(type, fn) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(fn); }
  removeEventListener(type, fn) { this.listeners.set(type, (this.listeners.get(type) || []).filter(one => one !== fn)); }
  setPointerCapture() {}
  // Test-side helpers.
  dispatch(type, event) { for (const fn of this.listeners.get(type) || []) fn({target: this, preventDefault() {}, ...event}); }
  walk(visit) { visit(this); for (const child of [...this.childNodes]) child.walk(visit); return this; }
  find(predicate) { const out = []; this.walk(node => { if (predicate(node)) out.push(node); }); return out; }
  findClass(name) { return this.find(node => node.classList.contains(name)); }
  findTag(name) { return this.find(node => node.tagName === name); }
}

// Installs the globals board.js reads at construction and rendering time, and hands back the
// stored preferences so a test can prove the choice was remembered.
function stubDom(stored = null) {
  const keys = ['document', 'localStorage', 'window', 'requestAnimationFrame'];
  const previous = Object.fromEntries(keys.map(key => [key, globalThis[key]]));
  const store = new Map(stored === null ? [] : [['tt-rules-overlay', stored]]);
  globalThis.localStorage = {
    getItem: key => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)); },
    removeItem: key => { store.delete(key); },
  };
  globalThis.document = {
    createElement: tag => new StubElement(tag),
    createElementNS: (_ns, tag) => new StubElement(tag),
    body: new StubElement('body'),
  };
  globalThis.window = {innerWidth: 1280, innerHeight: 896};
  globalThis.requestAnimationFrame = fn => { fn(); return 1; };  // no frames in node; the fade resolves at once
  return {store, restore() { for (const key of keys) globalThis[key] = previous[key]; }};
}

// A real board on a 20x14 map, with a team colour for the one actor-owned fixture.
function mountBoard(zones, {stored = null} = {}) {
  const dom = stubDom(stored);
  const viewport = new StubElement('div');
  const board = createBoard(viewport);
  board.setMap({width: 20, height: 14, background: {style: 'plain'}, floors: []});
  board.setZones(zones, {round: 3, teamOf: owner => (owner === 'actor:a' ? '#3d7ab8' : null)});
  return {dom, viewport, board, root: board.element, tip: document.body.findClass('tt-hovercard')[0]};
}

// The four kinds the renderer has to tell apart, each on squares of its own.  The scenery is
// deliberately not bamboo: the old code exempted bamboo by material name, so only a different
// terrain shows that the ground is now recognised by who owns it rather than what it looks like.
const scenery = {zone_id: 'zone:map:ford', source_definition_id: 'system:battlefield.terrain', owner_id: 'map',
  center: {x: 2, y: 2}, radius_cells: 0, active: true, duration_rounds: null, created_round: 0,
  affected_cells: [{x: 2, y: 2}, {x: 3, y: 2}, {x: 2, y: 3}, {x: 3, y: 3}],
  trigger_profile: {kind: 'TYPED', name: 'Muddy Ford', shape: 'painted', difficult: 'all', obscured: 'light',
    visual: {material: 'mud', obscured: 'light'}}};
const technique = {zone_id: 'zone:gate:actor:a:1:0', source_definition_id: 'action:typed.vermilion_gate.guardian_at_the_gate',
  owner_id: 'actor:a', center: {x: 9, y: 6}, radius_cells: 1, active: true, duration_rounds: 10, created_round: 1,
  affected_cells: [{x: 8, y: 6}, {x: 9, y: 6}, {x: 10, y: 6}],
  trigger_profile: {kind: 'TYPED', name: 'Guarded Threshold', shape: 'painted', difficult: 'hostile', visual: {material: 'glyphs'}}};
const objectWall = {zone_id: 'zone:object:door', source_definition_id: 'system:battlefield.object', owner_id: 'map',
  center: {x: 15, y: 4}, radius_cells: 0, active: true, duration_rounds: null, created_round: 0,
  affected_cells: [{x: 15, y: 3}, {x: 15, y: 4}, {x: 15, y: 5}],
  // A placed object that blocks: its wall rule rides on the profile, as combat/zones.py lays it.
  trigger_profile: {kind: 'TYPED', name: 'Stone Door', shape: 'painted', visual: {material: 'stone', wall: true},
    wall: {blocks_movement: true, blocks_sight: true}}};
const legacy = {zone_id: 'old-zone', center: {x: 5, y: 9}, radius_cells: 0, active: true, duration_rounds: 5, created_round: 1,
  affected_cells: [{x: 5, y: 9}], trigger_profile: {kind: 'SPELL', name: 'Cloud Of Daggers', shape: 'painted', difficult: 'hostile'}};

// Let the board swap one rendering for the next: a replaced zone is faded out, then removed.
const FADE_MS = 600;
const settle = t => t.mock.timers.tick(FADE_MS);

// mountBook is mountBoard with the standard four fixtures; kept separate so the tests read the same way.
function mountBook(options = {}) { return mountBoard([scenery, technique, objectWall, legacy], options); }

test('the board paints map terrain as bare ground: no outline, no hatching, no name, no haze', () => {
  const {dom, root} = mountBoard([scenery]);
  try {
    assert.equal(root.findClass('tt-zone-ground').length, 1, 'the material is still painted on the ground');
    assert.equal(root.findClass('tt-zone-edge').length, 0, 'scenery has no outline drawn over it');
    assert.equal(root.findClass('tt-zone-hatch').length, 0, 'scenery is never hatched as difficult ground');
    assert.equal(root.findClass('tt-zone-label').length, 0, 'scenery is not named on the map');
    assert.equal(root.findClass('tt-zone-air').length, 0, 'scenery keeps its own obscurement: no haze is laid over it');
  } finally {
    dom.restore();
  }
});

test('a painted technique and a legacy zone keep their own edge, and their names wait for a hover', () => {
  const {dom, root} = mountBook();
  try {
    // One edge for each of the three drawable zones; the map scenery drew none.
    assert.equal(root.findClass('tt-zone-edge').length, 3, 'every drawable patch but the scenery is outlined');
    assert.equal(root.findClass('tt-zone-edge-natural').length, 2, 'only the technique and the legacy zone get the soft rim');
    assert.equal(root.findClass('tt-zone-edge').filter(node => !node.classList.contains('tt-zone-edge-natural') && !node.classList.contains('tt-zone-edge-map')).length, 1,
      'the object wall keeps an ordinary edge of its own');
    assert.equal(root.findClass('tt-zone-hatch').length, 0, 'nothing is hatched until the rules overlay asks for it');
    assert.deepEqual(root.findClass('tt-zone-label').map(node => node.textContent),
      ['Guarded Threshold', 'Stone Door', 'Cloud Of Daggers'], 'the scenery is not named');
    assert.ok(root.findClass('tt-zone-label').every(node => node.classList.contains('tt-zone-label-hover')),
      'each name is hidden until the pointer rests on its squares');
  } finally {
    dom.restore();
  }
});

test('the rules overlay restores ordinary edges, hatching and names, and turning it off puts them back', t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {dom, root, board} = mountBook();
  try {
    board.setRulesOverlay(true);
    settle(t);
    assert.equal(dom.store.get('tt-rules-overlay'), 'true', 'the choice is remembered for the next visit');
    assert.equal(root.findClass('tt-zone-edge').length, 4, 'the scenery is outlined like every other patch');
    assert.equal(root.findClass('tt-zone-edge-natural').length, 0, 'the soft rim is gone: the overlay draws rule marks');
    assert.equal(root.findClass('tt-zone-edge-map').length, 1, 'terrain keeps its own edge class so it can be told apart');
    assert.equal(root.findClass('tt-zone-hatch').length, 3, 'each patch that slows movement is hatched');
    assert.deepEqual(root.findClass('tt-zone-label').map(node => node.textContent),
      ['Muddy Ford', 'Guarded Threshold', 'Stone Door', 'Cloud Of Daggers'], 'every zone is named at once');
    assert.ok(root.findClass('tt-zone-label').every(node => !node.classList.contains('tt-zone-label-hover')),
      'no name waits for a hover while the rules are shown');
    assert.equal(root.findClass('tt-zone-air').length, 1, 'the overlay shows the terrain\'s own obscurement');

    board.setRulesOverlay(false);
    settle(t);
    assert.equal(dom.store.get('tt-rules-overlay'), 'false', 'turning it off is remembered too');
    assert.equal(root.findClass('tt-zone-edge').length, 3, 'the scenery is left bare again');
    assert.equal(root.findClass('tt-zone-edge-natural').length, 2, 'the technique and legacy rim come back');
    assert.equal(root.findClass('tt-zone-hatch').length, 0, 'hatching is dropped again');
    assert.deepEqual(root.findClass('tt-zone-label').map(node => node.textContent),
      ['Guarded Threshold', 'Stone Door', 'Cloud Of Daggers']);
    assert.ok(root.findClass('tt-zone-label').every(node => node.classList.contains('tt-zone-label-hover')),
      'the names go back to waiting for a hover');
  } finally {
    dom.restore();
  }
});

test('a board built after a reload starts in whichever overlay state was left behind', () => {
  const {dom, root, board} = mountBook();
  let reopened;
  try {
    assert.equal(root.findClass('tt-zone-hatch').length, 0, 'a first visit shows the terrain, not the rules');
    board.setRulesOverlay(true);
    reopened = mountBook({stored: dom.store.get('tt-rules-overlay')});
    assert.equal(reopened.root.findClass('tt-zone-hatch').length, 3, 'the stored choice is read before the first paint');
    assert.equal(reopened.root.findClass('tt-zone-edge-natural').length, 0);
    reopened.board.setRulesOverlay(false);
    reopened = mountBook({stored: reopened.dom.store.get('tt-rules-overlay')});
    assert.equal(reopened.root.findClass('tt-zone-hatch').length, 0, 'turning it off is remembered too');
    assert.equal(reopened.root.findClass('tt-zone-edge-natural').length, 2);
  } finally {
    reopened?.dom.restore();
    dom.restore();
  }
});

test('resting the pointer on a zone names it and says what it does, and an empty square says nothing', t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {dom, root, viewport, tip, board} = mountBook();
  const restOn = (x, y) => {
    viewport.dispatch('pointermove', {clientX: (x + 0.5) * CELL, clientY: (y + 0.5) * CELL, buttons: 0});
    t.mock.timers.tick(2000);
  };
  const labelFor = name => root.findClass('tt-zone-label').find(node => node.textContent === name);
  try {
    restOn(9, 6);
    assert.equal(tip.hidden, false, 'the zone under the pointer is described');
    assert.deepEqual(tip.findClass('tt-zone-tip-item').map(node => node.findTag('b')[0]?.textContent), ['Guarded Threshold']);
    assert.deepEqual(tip.findTag('span').map(node => node.textContent), ['Difficult terrain (for foes)', '8 rounds left']);
    assert.equal(labelFor('Guarded Threshold').classList.contains('is-hovered'), true, 'the hovered name lights up');
    assert.equal(labelFor('Cloud Of Daggers').classList.contains('is-hovered'), false, 'a zone the pointer is not on stays dark');
    // The scenery has no name to light up, but it is still described when hovered.
    restOn(2, 2);
    assert.deepEqual(tip.findClass('tt-zone-tip-item').map(node => node.findTag('b')[0]?.textContent), ['Muddy Ford']);
    assert.equal(labelFor('Muddy Ford'), undefined, 'map scenery is described, never named on the map');

    // A blocking object still says what it stops, and still has no name waiting on the map edge.
    restOn(15, 4);
    assert.deepEqual(tip.findClass('tt-zone-tip-item').map(node => node.findTag('b')[0]?.textContent), ['Stone Door']);
    assert.deepEqual(tip.findTag('span').map(node => node.textContent),
      ['Wall: blocks movement and sight', 'Attacks through it have Disadvantage']);

    restOn(19, 13);
    assert.equal(tip.hidden, true, 'an empty square describes nothing');

    board.setRulesOverlay(true);
    settle(t);
    restOn(9, 6);
    assert.equal(tip.hidden, false, 'the rules overlay still explains the zone under the pointer');
    assert.equal(root.findClass('tt-zone-label').some(node => node.classList.contains('is-hovered')), false,
      'the overlay leaves the on-map names alone');
  } finally {
    dom.restore();
  }
});

// Owner 2026-10-03 03:38: a more transparent darkness for regular Darkness, still slightly transparent but almost
// pitch black for Pure Darkness, and dark tentacles you can barely see for an area that snags or clings to you.
// The engine says which one an area is (combat/ext/tabik_dark.py); the table only draws it.
test('each shade of Darkness is drawn with its own look', () => {
  const darkness = visual => ({zone_id: 'dark', active: true, owner_id: 'a', affected_cells: [{x: 1, y: 1}],
    trigger_profile: {kind: 'TYPED', name: 'Darkness', visual: {material: 'darkness', darkness: true, ...visual}}});
  const veil = zoneLook(darkness({darkness_look: 'veil'}));
  const pitch = zoneLook(darkness({darkness_look: 'pitch'}));
  const tentacled = zoneLook(darkness({darkness_look: 'tentacles', darkness_tentacles: true}));
  assert.deepEqual([veil.darknessLook, pitch.darknessLook, tentacled.darknessLook], ['veil', 'pitch', 'tentacles']);
  // An area the engine never tagged -- another sphere's darkness, or one saved before the looks existed -- has no
  // look at all, and keeps the drawing darkness has always had. Picking one for it would change every old area.
  assert.equal(zoneLook(darkness({})).darknessLook, null);
  // Pure Darkness with Clinging Darkness on it: pitch black, still waving.
  const both = zoneLook(darkness({darkness_look: 'pitch', darkness_tentacles: true}));
  assert.equal(both.darknessLook, 'pitch');
  assert.equal(both.darknessTentacles, true);
  // Only a darkness has a look: a cloud, a fog bank and a broken value are not dark.
  for (const visual of [{material: 'smoke', obscured: 'heavy'}, {material: 'fog', obscured: 'light'},
                        {material: 'darkness', darkness: true, darkness_look: 'nonsense'}]) {
    const look = zoneLook({zone_id: 'z', active: true, owner_id: 'a', affected_cells: [{x: 1, y: 1}],
      trigger_profile: {kind: 'TYPED', name: 'Veil', visual}});
    assert.equal(look.darknessTentacles, false);
  }
  assert.equal(zoneLook({zone_id: 'z', active: true, owner_id: 'a', affected_cells: [{x: 1, y: 1}],
    trigger_profile: {kind: 'TYPED', name: 'Smoke Veil', visual: {material: 'smoke', obscured: 'heavy'}}}).darknessLook, null);
  // The tentacle tile paints deterministically, without Math.random, and is faint.
  const original = Math.random;
  Math.random = () => { throw new Error('Math.random used while painting the tentacles'); };
  let tentacles;
  try {
    const a = recorder(), b = recorder();
    paintTile(a.ctx, 'tentacles', 32, 7, [4, 4, 10]);
    paintTile(b.ctx, 'tentacles', 32, 7, [4, 4, 10]);
    tentacles = a.log;
    assert.ok(tentacles.length > 0, 'the tentacle tile draws something');
    assert.deepEqual(tentacles, b.log, 'the tentacle tile paints the same way every time');
  } finally {
    Math.random = original;
  }
});

// ------------------------------------------------ the darkness looks as they are actually drawn
// Owner 2026-10-03 03:38: "a more transparent darkness for regular darkness and still slightly transparent but almost
// pitch black for pure darkness ... dark tentacles you can barely see waving in the area". The engine says which look
// an area gets (combat/ext/tabik_dark.py); the table only draws it. These measure the finished area -- the material
// on the ground AND the veil in the air, which is what a player sees -- rather than the payload that asked for it.

// A DOM small enough to draw one zone in. Every painting call is recorded and nothing is rendered, so a headless
// test can read the nodes createBoard really builds instead of trusting a number in the source.
function domNode(tag = 'div') {
  const node = {
    tagName: String(tag).toUpperCase(), children: [], parentNode: null, attrs: {}, dataset: {}, className: '', hidden: false,
    style: {setProperty(name, value) { this[name] = value; }, removeProperty(name) { delete this[name]; }},
    classList: {
      // className is the record, so a class set directly and one added here are the same thing.
      _list() { return String(this._owner.className || '').split(/\s+/).filter(Boolean); },
      _write(names) { this._owner.className = [...new Set(names)].join(' '); },
      add(...names) { this._write([...this._list(), ...names]); },
      remove(...names) { this._write(this._list().filter(one => !names.includes(one))); },
      contains(name) { return this._list().includes(name); },
      toggle(name, force) { const on = force === undefined ? !this.contains(name) : force; on ? this.add(name) : this.remove(name); },
    },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return this.attrs[name] ?? null; },
    hasAttribute(name) { return name in this.attrs; },
    removeAttribute(name) { delete this.attrs[name]; },
    querySelectorAll: () => [], querySelector: () => null, dispatchEvent() {},
    replaceChildren(...nodes) { this.children = nodes.filter(Boolean); for (const child of this.children) child.parentNode = this; },
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    removeChild(child) { this.children = this.children.filter(one => one !== child); child.parentNode = null; return child; },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    addEventListener() {}, removeEventListener() {}, setPointerCapture() {},
    getBoundingClientRect: () => ({left: 0, top: 0, right: 640, bottom: 480, width: 640, height: 480}),
  };
  node.classList._owner = node;
  return node;
}

function fakeCanvas(paints) {
  const canvas = domNode('canvas');
  const paint = recorder();
  canvas.toDataURL = () => {
    const url = `data:image/png;base64,recorded-${paints.size}`;
    paints.set(`url(${url})`, paint.log);
    return url;
  };
  canvas.getContext = () => paint.ctx;
  return canvas;
}

// Draws one zone on a real board and hands back the nodes the table built for it.
function drawZone(zone) {
  const saved = {document: globalThis.document, window: globalThis.window, raf: globalThis.requestAnimationFrame,
    storage: globalThis.localStorage};
  const paints = new Map();
  const document = {
    body: domNode('body'),
    createElement: tag => (tag === 'canvas' ? fakeCanvas(paints) : domNode(tag)),
    createElementNS: (_ns, tag) => domNode(tag),
  };
  globalThis.document = document;
  globalThis.localStorage = {getItem: () => null, setItem() {}, removeItem() {}};
  globalThis.window = {innerWidth: 1024, innerHeight: 768, addEventListener() {}, removeEventListener() {}};
  globalThis.requestAnimationFrame = () => 0;
  try {
    const board = createBoard(domNode('div'));
    board.setMap({width: 20, height: 14, background: {style: 'plain'}});
    board.setZones([zone], {round: 3});
    const layers = collect(board.element);
    layers.paints = paints;
    return layers;
  } finally {
    globalThis.document = saved.document;
    globalThis.window = saved.window;
    globalThis.requestAnimationFrame = saved.raf;
    globalThis.localStorage = saved.storage;
  }
}

// Every .tt-zone box anywhere under the board, in the order the table built them.
function collect(node, out = []) {
  for (const child of node.children || []) {
    if (/\btt-zone\b/.test(child.className || '')) out.push(child);
    collect(child, out);
  }
  return out;
}

const oneDarkness = visual => ({
  zone_id: 'dark:1', active: true, owner_id: 'actor:a', center: {x: 6, y: 5}, radius_cells: 1, duration_rounds: 10, created_round: 2,
  affected_cells: [{x: 5, y: 5}, {x: 6, y: 5}, {x: 7, y: 5}, {x: 6, y: 4}, {x: 6, y: 6}],
  trigger_profile: {kind: 'TYPED', name: 'Darkness', visual: {material: 'darkness', darkness: true, ...visual}},
});

// How much of the floor the darkness material on the ground covers, measured off the paint itself. A look that is
// meant to be see-through has to lift this, because the material is very nearly opaque on its own.
function materialCoverage(material = 'darkness') {
  const base = recorder();
  paintMaterial(base.ctx, material, spec(7));
  const image = base.images[0];
  let covered = 0;
  for (let index = 3; index < image.data.length; index += 4) covered += image.data[index] / 255;
  return covered / (image.data.length / 4);
}

// What the floor still shows through a finished area: the material on the ground, then the veil in the air, in that
// order. The drifting haze and the tentacles are children of the air box and ride inside its own opacity, so they
// darken the flat parts only where the tile itself is, and never below the veil's own share.
function floorVisible(layers) {
  const ground = layers.find(node => /tt-zone-ground/.test(node.className));
  const air = layers.find(node => /tt-zone-air/.test(node.className));
  assert.ok(ground && air, 'a darkness has a ground and a veil in the air');
  const fill = air.children.find(node => /tt-zone-fill/.test(node.className || ''));
  const fillAlpha = fill ? Number(String(fill.style.background).match(/[\d.]+\)$/)[0].slice(0, -1)) : 1;
  const layerAlpha = (node, alpha) => (node.style.opacity === undefined ? alpha : Number(node.style.opacity) * alpha);
  return {
    visible: (1 - layerAlpha(ground, materialCoverage())) * (1 - layerAlpha(air, fillAlpha)),
    ground: ground.style.opacity, air: air.style.opacity, fillAlpha,
  };
}

test('each Darkness look darkens the whole area, not just the veil over it', () => {
  // The material on the ground on its own is what made the old look almost opaque: nothing could see the floor.
  assert.ok(materialCoverage() > 0.9, 'the darkness material is nearly opaque by itself');
  // The share each layer spends, and what the two together leave of the floor. The owner's brief as ranges.
  const ranges = {veil: [0.45, 0.55], pitch: [0.08, 0.12], tentacles: [0.5, 0.62]};
  const seen = {};
  for (const look of ['veil', 'pitch', 'tentacles']) {
    const drawn = floorVisible(drawZone(oneDarkness({darkness_look: look})));
    const [low, high] = ranges[look];
    assert.ok(drawn.visible >= low && drawn.visible <= high,
      `${look} leaves ${(drawn.visible * 100).toFixed(1)}% of the floor showing, outside ${low}-${high}`);
    assert.equal(drawn.ground, String(darknessComposition(look).ground), 'the ground spends its share');
    assert.equal(drawn.air, String(darknessComposition(look).air), 'the air spends its share');
    assert.equal(drawn.fillAlpha, 1, 'the veil inside the air box is the whole share, not more');
    seen[look] = drawn.visible;
  }
  // The three are ordered as the owner described them, and no two of them are the same shade. Less showing through
  // is a darker shade: pitch black, then the see-through veil, then the faintest one with the strands over it.
  assert.ok(seen.pitch < seen.veil && seen.veil < seen.tentacles, `the three looks separate: ${JSON.stringify(seen)}`);
  // What the first version of these looks did: the material at full strength under a 0.5 veil. It is nowhere near
  // "a more transparent darkness", which is why the whole composition has to be measured, not one layer of it.
  const oldGround = materialCoverage();
  assert.ok((1 - oldGround) * (1 - 0.5) < 0.05, 'the material under one half-opaque veil hides all but a sliver of the floor');
  assert.ok(seen.veil > 0.45, 'and the fixed composition does not');
});

test('a Darkness screen wall is a cloud you can still see the floor through', () => {
  const wall = extra => ({
    ...oneDarkness(extra), affected_cells: [{x: 6, y: 2}, {x: 6, y: 3}, {x: 6, y: 4}, {x: 6, y: 5}],
    trigger_profile: {kind: 'TYPED', name: 'Darkness Wall', wall: {blocks_movement: false, blocks_sight: true, thick_ft: 10, length_ft: 15},
      visual: {material: 'darkness', darkness: true, wall: true, ...extra}},
  });  for (const look of ['veil', 'pitch', 'tentacles']) {
    const drawn = floorVisible(drawZone(wall({darkness_look: look})));
    const open = darknessComposition(look);
    assert.equal(drawn.ground, String(open.ground * 0.86), 'the standing cloud is drawn lighter than the open area');
    assert.equal(drawn.air, String(open.air * 0.5), 'and the veil in the air with it');
    assert.ok(drawn.visible > (1 - 0.86 * open.ground * materialCoverage()) * (1 - open.air),
      `${look} as a wall shows more of the floor than the same look on the ground`);
  }
});

test('darkness the engine never tagged is drawn exactly as it always was', () => {
  // Another sphere's darkness, an area saved before the looks existed, and an unreadable value: all three keep the
  // one drawing darkness has always had, which is why the ground is not lifted and the veil is still 0.80.
  for (const visual of [{}, {darkness_look: 'nonsense'}, {darkness: true, darkness_look: undefined}]) {
    const layers = drawZone(oneDarkness(visual));
    const ground = layers.find(node => /tt-zone-ground/.test(node.className));
    const air = layers.find(node => /tt-zone-air/.test(node.className));
    const fill = air.children.find(node => /tt-zone-fill/.test(node.className || ''));
    assert.equal(ground.style.opacity, undefined, 'the material on the ground is untouched');
    assert.equal(air.style.opacity, undefined, 'the veil in the air is not given a share');
    assert.equal(fill.style.background, 'rgba(4,4,10,0.8)', 'the old flat 80% wash');
    assert.equal(darknessComposition(zoneLook(oneDarkness(visual)).darknessLook), null, 'and no look is guessed for it');
    // Which is nearly opaque, as it always was: this is the rendering that must not change, not one to improve.
    const drawn = floorVisible(layers);
    assert.ok(drawn.visible < 0.05, `still the same near-opaque darkness (${(drawn.visible * 100).toFixed(1)}% showing)`);
  }
  // And an untagged screen wall keeps its own two old numbers as well.
  const wall = floorVisible(drawZone({
    ...oneDarkness({}), affected_cells: [{x: 6, y: 2}, {x: 6, y: 3}],
    trigger_profile: {kind: 'TYPED', name: 'Darkness Wall', wall: {blocks_movement: false, blocks_sight: true, thick_ft: 10, length_ft: 15},
      visual: {material: 'darkness', darkness: true, wall: true}},
  }));
  assert.equal(wall.ground, '0.86', 'the standing cloud keeps its old opacity');
  assert.equal(wall.air, undefined, 'and no share is given to the air box, as before');
  assert.equal(wall.fillAlpha, 0.42, 'the veil in it is still the old 42% wash a screen wall has always had');
});

test('recognized Darkness looks select their air mask while preserving LIVE ground feathering', () => {
  for (const visual of [{}, {darkness_look: 'nonsense'}, {darkness_look: null},
                        {darkness_look: 'veil'}, {darkness_look: 'pitch'}, {darkness_look: 'tentacles'},
                        {material: 'smoke', darkness: false, obscured: 'heavy'}]) {
    const layers = drawZone(oneDarkness(visual));
    const ground = layers.find(node => /tt-zone-ground/.test(node.className));
    const air = layers.find(node => /tt-zone-air/.test(node.className));
    const tagged = Boolean(darknessComposition(visual.darkness_look));
    const blur = image => layers.paints.get(image).find(row => row[0] === 'set' && row[1] === 'filter')[2];
    assert.equal(blur(ground.style.maskImage), 'blur(3px)');
    assert.equal(blur(air.style.maskImage), 'blur(3px)');
    assert.equal(air.style.webkitMaskImage, air.style.maskImage);
    if (!tagged) assert.equal(air.style.maskImage, ground.style.maskImage, 'the original mask is reused');
  }
});

test('painted tentacle strokes contrast faintly with the veil after source-over composition', () => {
  // Follow the real board's tile URL to its actual painting commands, rather than checking a chosen tint.
  // At a stroke's covered pixel, source-over the opaque fill and then apply the tile and air opacities.
  // The underlying board cancels out of the difference. This checks contrast mathematically, not rasterization.
  const rgba = text => String(text).match(/[\d.]+/g).map(Number);
  for (const visual of [{darkness_look: 'tentacles'}, {darkness_look: 'pitch', darkness_tentacles: true}]) {
    const layers = drawZone(oneDarkness(visual));
    const air = layers.find(node => /tt-zone-air/.test(node.className));
    const fill = rgba(air.children.find(node => /tt-zone-fill/.test(node.className)).style.background);
    assert.equal(fill[3], 1);
    const tiles = air.children.filter(node => /\btt-zone-fx\b/.test(node.className));
    assert.equal(tiles.length, 2);
    for (const tile of tiles) {
      let stroke, peak = 0, count = 0;
      for (const row of layers.paints.get(tile.style.backgroundImage)) {
        if (row[0] === 'set' && row[1] === 'strokeStyle') stroke = rgba(row[2]);
        if (row[0] === 'stroke') {
          count += 1;
          const contrast = Math.max(...fill.slice(0, 3).map((channel, i) => Math.abs(stroke[i] - channel)))
            * stroke[3] * Number(tile.style.opacity) * Number(air.style.opacity);
          peak = Math.max(peak, contrast);
        }
      }
      assert.ok(count > 0, 'the tile actually strokes strands');
      assert.ok(peak > 2 && peak < 20, `${visual.darkness_look} strand contrast ${peak.toFixed(2)}/255 is visible but faint`);
      assert.equal(tile.style.mixBlendMode, undefined, 'ordinary source-over composition');
    }
  }
});

test('the tentacle strands ride inside the look, so they stay barely visible', () => {
  // The veil is what hides the floor; the strands are drawn on top of it inside the same share, so adding them
  // never makes an area darker than the look the owner asked for.
  const strands = look => {
    const layers = drawZone(oneDarkness({darkness_look: look, darkness_tentacles: true}));
    const air = layers.find(node => /tt-zone-air/.test(node.className));
    const tiles = air.children.filter(node => /\btt-zone-fx\b/.test(node.className || ''));
    return {tiles, opacity: Number(air.style.opacity)};
  };
  const tentacled = strands('tentacles');
  assert.equal(tentacled.tiles.length, 2, 'two layers cross, so the strands read as waving rather than sliding');
  assert.ok(tentacled.tiles.every(node => /tt-anim-sway/.test(node.className)), 'both sway');
  assert.ok(tentacled.tiles.every(node => Number(node.style.opacity) < 0.6), 'each strand layer is faint');
  // Pitch black still waves: the strands are laid over the deeper shade, not traded for it.
  const pitch = strands('pitch');
  assert.equal(pitch.tiles.length, 2);
  assert.equal(pitch.opacity, darknessComposition('pitch').air, 'over the deeper shade, at its own share');
  assert.ok(pitch.opacity > tentacled.opacity, 'pitch is the deeper of the two');
  // An area with no tentacles drifts the ordinary haze instead.
  const plain = drawZone(oneDarkness({darkness_look: 'pitch'}));
  const air = plain.find(node => /tt-zone-air/.test(node.className));
  const drift = air.children.filter(node => /\btt-zone-fx\b/.test(node.className || ''));
  assert.equal(drift.length, 1);
  assert.ok(/background-image|data:image/.test(String(drift[0].style.backgroundImage || '')), 'the haze tile is drawn');
});

test('tentacle motion is continuous at both loop boundaries', () => {
  const css = readFileSync(new URL('./tabletop.css', import.meta.url), 'utf8');
  for (const visual of [{darkness_look: 'tentacles'},
                        {darkness_look: 'pitch', darkness_tentacles: true}]) {
    const air = drawZone(oneDarkness(visual)).find(node => /tt-zone-air/.test(node.className));
    const tiles = air.children.filter(node => /\btt-zone-fx\b/.test(node.className));
    assert.equal(tiles.length, 2);
    for (const tile of tiles) {
      const animationClass = tile.className.match(/\btt-anim-\S+/)[0];
      const rule = css.match(new RegExp(`\\.${animationClass}\\s*\\{([^}]+)\\}`))?.[1];
      assert.ok(rule, 'the real tile animation has a CSS rule');
      assert.match(rule, /animation:\s*tt-zone-drift ease-in-out infinite alternate\s*;/,
        'fractional travel reverses with zero endpoint speed instead of resetting to zero');
      assert.equal(tile.style.animationDirection, undefined, 'no inline direction overrides alternate');
      assert.ok(parseFloat(tile.style.animationDuration) > 0);
      assert.match(css, /@keyframes tt-zone-drift\s*\{ from \{ transform: translate3d\(0, 0, 0\); \} to \{ transform: translate3d\(var\(--tt-dx, 0px\), var\(--tt-dy, 0px\), 0\); \} \}/);
      // CSS alternate traversal meets at 1 after the forward iteration and at 0 after the return.
      // Check both axes of the actual rendered nodes, including their fractional-period travel.
      for (const axis of ['--tt-dx', '--tt-dy']) {
        const travel = parseFloat(tile.style[axis]);
        assert.ok(Number.isFinite(travel) && travel !== 0);
        const progress = t => { const phase = t % 2; return phase <= 1 ? phase : 2 - phase; };
        for (const boundary of [1, 2]) {
          assert.ok(Math.abs(travel * (progress(boundary - 1e-6) - progress(boundary + 1e-6))) < 1e-8,
            `${axis} joins at both the forward and return boundaries`);
        }
      }
    }
  }
});

test('the looks are one table, and the composition says what an unknown one gets', () => {
  assert.deepEqual(Object.keys(DARKNESS_FILL).sort(), ['pitch', 'tentacles', 'veil']);
  assert.equal(darknessComposition('nonsense'), null);
  assert.equal(darknessComposition(undefined), null);
  assert.equal(darknessComposition(null), null);
  // No look, no numbers at all: the drawing is the table's own business, not a zero opacity.
  assert.deepEqual(darknessComposition('veil'), {look: 'veil', fill: 0.5, share: 1 - Math.sqrt(0.5),
    ground: 1 - Math.sqrt(0.5), air: 1 - Math.sqrt(0.5)});
});

// The square card lists every zone covering the square under the pointer, perceived ones only.
const overlapA = {zone_id: 'zone:water:a', source_definition_id: 'action:typed.water.gate', owner_id: 'actor:a',
  center: {x: 5, y: 5}, radius_cells: 1, active: true, duration_rounds: 4, created_round: 1,
  affected_cells: [{x: 5, y: 5}, {x: 6, y: 5}],
  trigger_profile: {kind: 'TYPED', name: 'Gate Of The Inner Sea', shape: 'painted', difficult: 'hostile', visual: {material: 'water'}}};
const overlapB = {zone_id: 'zone:water:b', source_definition_id: 'action:typed.water.court', owner_id: 'actor:a',
  center: {x: 5, y: 5}, radius_cells: 1, active: true, duration_rounds: 4, created_round: 1,
  affected_cells: [{x: 5, y: 5}, {x: 5, y: 6}],
  trigger_profile: {kind: 'TYPED', name: "Court Of Ten Thousand Weapons", shape: 'painted', visual: {material: 'water'}}};
const hiddenZone = {zone_id: 'zone:water:hidden', source_definition_id: 'action:typed.water.pull', owner_id: 'actor:b',
  center: {x: 12, y: 9}, radius_cells: 0, active: true, duration_rounds: 4, created_round: 1,
  affected_cells: [{x: 12, y: 9}],
  trigger_profile: {kind: 'TYPED', name: "Moon's Pull", shape: 'painted', visual: {material: 'water'}}};

function hoverSquare(t, zones, x, y, seen = null) {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {dom, viewport, board, tip} = mountBoard(zones);
  if (seen) board.setFog(seen);
  viewport.dispatch('pointermove', {clientX: (x + 0.5) * CELL, clientY: (y + 0.5) * CELL, buttons: 0});
  t.mock.timers.tick(2000);
  const names = tip.findClass('tt-zone-tip-item').map(node => node.findTag('b')[0]?.textContent);
  dom.restore();
  return names;
}

test('a square inside two zones lists both, with the zone names', t => {
  assert.deepEqual(hoverSquare(t, [overlapA, overlapB], 5, 5), ['Gate Of The Inner Sea', 'Court Of Ten Thousand Weapons']);
});

test('a square outside every zone lists none', t => {
  assert.deepEqual(hoverSquare(t, [overlapA, overlapB], 0, 0), []);
});

test('a zone the viewer cannot perceive is not listed on the square card', t => {
  const seen = new Uint8Array(20 * 14).fill(1);
  seen[9 * 20 + 12] = 0;   // the square of Moon's Pull is out of sight
  assert.deepEqual(hoverSquare(t, [hiddenZone], 12, 9, seen), []);
});
