// node --test APP/static/tabletop/board-frames.test.mjs
//
// What the table actually DRAWS round ground and round a cast effect (owner 2026-10-03, lane MMX111f1).
//
// The source guards in tests/test_terrain_no_frames.py can only check what board.js says; this renders the real
// board through createBoard and looks at the nodes it produces, which is the level the owner's complaint was
// visible at: a frame round a patch of ground.  Three things are held here.
//
// 1. Ground the map itself painted (combat/zones.py map_zones) gets no halo and no outline.
// 2. An area a character cast keeps its coloured edge, INCLUDING the two that paint flat ground art and would
//    otherwise be mistaken for the landscape: Guarded Threshold (sealed stone) and Grove Domain's Living Claims
//    (foliage).  They are actor-owned and existed at the base revision; losing their edge makes those squares
//    indistinguishable from ordinary terrain.
// 3. The table grid the owner asked to keep is still drawn, and the per-square ground washes still fill.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from '../../tests/objects_dom_stub.mjs';
import {previewTerrainZones} from './mapeditor-zones.js';

const terrainRules = JSON.parse(readFileSync(new URL('../../combat/rules/terrain.json', import.meta.url), 'utf8'));
const terrains = Object.entries(terrainRules.terrains).map(([name, rule]) => ({name, ...rule}));

installDOM('<html><body><div id="ttBoard"></div></body></html>');
const {createBoard} = await import('./board.js?v=rel6-2');

// --- the areas, copied from the code that really produces them (see tests/test_terrain_no_frames.py, which fails if
// --- one of those producers changes shape, material or provenance, so these copies cannot quietly go stale).
const cells = [[6, 6], [7, 6], [8, 6]];

// combat/zones.py:471-479 -- a terrain area painted by the map editor, read from the fight's sealed arena.
const MAP_TERRAIN = {
  zone_id: 'zone:map:1',
  source_definition_id: 'system:battlefield.terrain',
  owner_id: 'map',
  active: true,
  center: {x: 6, y: 6},
  affected_cells: cells.map(([x, y]) => ({x, y})),
  trigger_profile: {
    kind: 'TYPED', name: 'Loose Rubble', terrain: ['loose rubble'], difficult: 'all', obscured: null,
    color: null, follows_owner: false, shape: 'painted', size_ft: 5, triggers: [], move_through: null,
    talents: [], inside: [], map: true, natural_haze: false, visual: {material: 'rubble'}, numbers: {},
  },
};

// combat/ext/vermilion_gate.py:169-172 -- Guardian at the Gate's Guarded Threshold: a character cast it, its art is
// flat stone ("sealed" is not a known material, so it paints as the zone's own colour), and it must stay findable.
const GUARDED_THRESHOLD = {
  zone_id: 'zone:gate:hero:12:0',
  source_definition_id: 'tianxia.subpath.body.vermilion_gate_guardian_body.feature.guardian_at_the_gate',
  owner_id: 'hero',
  active: true,
  center: {x: 6, y: 6},
  affected_cells: cells.map(([x, y]) => ({x, y})),
  trigger_profile: {
    kind: 'TYPED', name: 'Guarded Threshold', terrain: [], difficult: 'hostile', obscured: null,
    color: '#c0392b', follows_owner: false, shape: 'painted', size_ft: 5, triggers: [], talents: [], inside: [],
    visual: {material: 'sealed'}, gate_threshold: true, numbers: {},
  },
};

// combat/ext/verdant_chassis.py:1221-1225 -- Grove Domain's Living Claims: an aura on the caster's own claims.
const LIVING_CLAIMS = {
  zone_id: 'zone:aura:hero:verdant_grove_claims',
  source_definition_id: 'TAL_VERDANT_GROWTH_GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH',
  owner_id: 'hero',
  active: true,
  center: {x: 6, y: 6},
  affected_cells: cells.map(([x, y]) => ({x, y})),
  trigger_profile: {
    kind: 'TYPED', name: 'Grove Domain: Living Claims are difficult terrain for enemies', terrain: [],
    difficult: 'hostile', obscured: null, color: '#6b8f3a', follows_owner: false, shape: 'painted', size_ft: 5,
    triggers: [], move_through: null, talents: [], inside: [], aura: true, visual: {material: 'foliage'},
    numbers: {},
  },
};

// A plain area effect, for the ordinary case: it keeps its edge too.
const CAST_EFFECT = {
  zone_id: 'zone:effect:7',
  source_definition_id: 'action:typed.factory.spores.BASE_SPORECLOUD',
  owner_id: 'foe',
  active: true,
  center: {x: 6, y: 6},
  affected_cells: cells.map(([x, y]) => ({x, y})),
  trigger_profile: {
    kind: 'TYPED', name: 'Spore Cloud', terrain: [], difficult: null, obscured: 'light', color: '#9bc43a',
    follows_owner: false, shape: 'sphere', size_ft: 20, triggers: [], talents: [], inside: [],
    visual: {material: 'poison'}, numbers: {},
  },
};

const MAP = {
  width: 12,
  height: 10,
  background: {style: 'plain', opacity: 1},
  display: {detail: 1, gridOpacity: 0.35, gridColor: '#d8c9a3'},
  cells: {cover: [[6, 6], [7, 6], [8, 6]], difficult: [[6, 6], [7, 6], [8, 6]]},
  floors: [],
};

// The nodes one zone drew, as classes: what the player can see round those squares.
function edgeClasses(zone) {
  const board = createBoard(document.getElementById('ttBoard'));
  board.setMap(MAP);
  board.setZones([zone], {round: 3, teamOf: () => ({color: '#4a90d9', owner: 'Cai', foe: false})});
  const out = new Set();
  for (const name of ['tt-zone-halo', 'tt-zone-outline', 'tt-zone-hatch']) {
    for (const node of board.element.querySelectorAll(`.tt-zone-lines .${name}`)) out.add(node.getAttribute('class'));
  }
  return out;
}

test('natural ground the map painted is drawn with no frame round it', () => {
  const classes = edgeClasses(MAP_TERRAIN);
  // The frame is the halo and its coloured outline: a line running round the patch.  The hatch is left alone on
  // purpose (the lane's own open item, and the review's "Inherited" note) -- it is a marking inside the squares
  // telling the player movement costs double there, not a border drawn round them.
  assert.equal([...classes].filter(name => /halo|outline/.test(name)).length, 0,
    `a frame was drawn round loose rubble: ${[...classes].join(', ')} -- that is the frame the owner is reporting`);
  // The ground is still there to be seen -- this is not "hide the terrain", it is "stop boxing it in".
  assert.ok(board_has_ground(MAP_TERRAIN), 'the terrain is not painted on the ground layer any more');
});

test('an effect a character cast keeps its coloured edge, even when it paints flat ground art', () => {
  for (const [what, zone] of [['Guarded Threshold', GUARDED_THRESHOLD], ["Grove Domain's Living Claims", LIVING_CLAIMS],
                             ['an ordinary area effect', CAST_EFFECT]]) {
    const classes = edgeClasses(zone);
    assert.ok([...classes].some(name => name.includes('tt-zone-halo')), `${what} lost its halo: its squares are no longer findable`);
    assert.ok([...classes].some(name => name.includes('tt-zone-outline')), `${what} lost its team-coloured outline`);
  }
});

// Exercise the editor's actual producer with the same terrain rules its API supplies.
for (const name of ['loose rubble', 'bamboo thicket']) {
  test(`editor preview of ${name} keeps ground art without terrain frames`, () => {
    const [zone] = previewTerrainZones([{material: `terrain:${name}`, cells}], terrains);
    const board = createBoard(document.getElementById('ttBoard'));
    board.setMap(MAP);
    board.setZones([zone], {round: 3, teamOf: () => '#4a90d9'});
    assert.ok(board.element.querySelector('.tt-zones-ground .tt-zone'), `${name} lost its ground art`);
    for (const selector of ['.tt-zone-halo', '.tt-zone-outline',
      ...(name === 'bamboo thicket' ? ['.tt-zone-air', '.tt-zone-hatch', '.tt-zone-hatch-shadow', '.tt-zone-label'] : [])]) {
      assert.equal(Boolean(board.element.querySelector(selector)), false, `${name} unexpectedly drew ${selector}`);
    }
  });
}

test('the table grid the owner kept is still drawn, over frameless ground', () => {
  const board = createBoard(document.getElementById('ttBoard'));
  board.setMap(MAP);
  board.setZones([MAP_TERRAIN, GUARDED_THRESHOLD], {round: 3, teamOf: () => '#4a90d9'});
  const grid = board.element.querySelector('.tt-grid');
  assert.ok(grid, 'the grid layer is gone');
  assert.ok(grid.querySelector('#tt-grid-cell') || grid.innerHTML.includes('tt-grid-cell'),
    'the grid squares are not drawn any more');
  // LIVE paints natural ground art by default; its opt-in rules overlay retains
  // the per-square washes. Verify both presentations remain populated.
  const art = board.element.querySelectorAll('.tt-terrain g').filter(node => node.innerHTML.includes('tt-rule-terrain'));
  assert.ok(art.length >= 3, `the ground art is missing (${art.length})`);
  board.setRulesOverlay(true);
  const washes = board.element.querySelectorAll('.tt-terrain g').filter(node => /class="tt-cell-(?:cover|difficult)"/.test(node.innerHTML));
  assert.ok(washes.length >= 3, `the ground washes are missing (${washes.length})`);
  for (const wash of washes) assert.doesNotMatch(wash.innerHTML, /\bstroke=/, 'a wash drew its own border');
});

// The terrain's material ground is painted into the .tt-zones-ground band, not the edge band.
function board_has_ground(zone) {
  const board = createBoard(document.getElementById('ttBoard'));
  board.setMap(MAP);
  board.setZones([zone], {round: 3, teamOf: () => '#4a90d9'});
  return board.element.querySelectorAll('.tt-zones-ground .tt-zone').length > 0;
}
