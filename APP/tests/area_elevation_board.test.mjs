import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';
import {map, actor, area} from './area_elevation_fixture.mjs';
import {areaHeightFt, areaOcclusionMask, wallSilhouette, cellPlaneFt} from '../static/tabletop/area-elevation.js';
import {treeLayerMarkup, treeShapeId} from '../static/tabletop/tree-art.js';

// Run the same tests against an older renderer without modifying the checkout.
// AURALAYER1_BOARD_SOURCE swaps board.js; AURALAYER1_ELEVATION_SOURCE swaps the
// area-elevation helper too, so the F2-tip renderer is reproduced exactly.
const url = new URL('../static/tabletop/board.js', import.meta.url);
const remap = source => source.replace(/from (["'])(\.\/[^"']+)\1/g,
  (_, quote, path) => `from ${quote}${new URL(path, url).href}${quote}`);
const elevationPath = process.env.AURALAYER1_ELEVATION_SOURCE;
const elevationOverride = elevationPath
  ? `data:text/javascript;base64,${Buffer.from(remap(readFileSync(elevationPath, 'utf8'))).toString('base64')}`
  : null;
const base = process.env.AURALAYER1_BOARD_SOURCE;
const original = base ? readFileSync(base, 'utf8') : null;
const source = original && original.replace(/from (["'])(\.\/[^"']+)\1/g,
  (_, quote, path) => `from ${quote}${elevationOverride && path.startsWith('./area-elevation.js')
    ? elevationOverride : new URL(path, url).href}${quote}`);
const {createBoard} = await import(source ? `data:text/javascript;base64,${Buffer.from(source).toString('base64')}` : url.href);
const maskXML = node => node.style.maskImage === 'none' ? ''
  : decodeURIComponent(node.style.maskImage.slice(node.style.maskImage.indexOf(',') + 1, -2));
function setup(at = actor(), zone = area(), scene = map, objects = []) {
  const doc = installDOM('<body></body>'), board = createBoard(doc.body);
  board.setMap(scene); board.setTokens([at, ...objects]);
  board.setRoofView({gm: false, viewers: []});
  board.setZones([zone]);
  return {doc, board, ground: doc.querySelector('.tt-zone-ground'), roof: doc.querySelector('.tt-roofs'),
    raised: doc.querySelector('.tt-area-raised'), elevated: doc.querySelector('.tt-zones-elevated')};
}
function above(board, higher, lower) {
  const siblings = board.element.children;
  assert.ok(siblings.indexOf(higher) > siblings.indexOf(lower), `${higher?.className} above ${lower?.className}`);
}

test('40 ft creature aura material, haze, rim and label sit above a 15 ft roof and below portraits', () => {
  const {board, ground, roof, raised, elevated} = setup();
  assert.ok(raised, 'source height creates a raised composition');
  assert.equal(raised.dataset.heightFt, '40');
  assert.ok(raised.contains(ground));
  for (const selector of ['.tt-zone-air', '.tt-zone-edge', '.tt-zone-label']) assert.ok(raised.querySelector(selector), selector);
  assert.equal(raised.style.maskImage, 'none', 'lower roofs/walls do not hide a flying aura');
  above(board, elevated, roof);
  above(board, board.tokenNode('caster').parentNode, elevated);
});

test('ground creature beside a building keeps aura material below the roof and clips cloud to roof art', () => {
  const at = {...actor(0), x: 1, position: {x: 1, y: 4, z: 0}};
  const {board, doc, ground, roof, raised} = setup(at, area({center: at.position}));
  assert.equal(raised, null);
  above(board, roof, ground.parentNode);
  assert.match(maskXML(doc.querySelector('.tt-area-cloud')), /area-roof-0/, 'haze cannot bleed across the closed roof');
});

test('ground-placed Fragrance remains below a roof when its owner flies at 40 ft', () => {
  const zone = area({center: {x: 4, y: 4, z: 0}, trigger_profile: {name: 'Placed Fragrance',
    shape: 'sphere', follows_owner: false, visual: {material: 'fog', obscured: 'light'}}});
  const {board, doc, roof, ground, raised} = setup(actor(), zone);
  assert.equal(raised, null, 'ownership alone never lifts a placed area');
  above(board, roof, ground.parentNode);
  assert.match(maskXML(doc.querySelector('.tt-area-cloud')), /area-roof-0/);
});

test('raised area is still occluded by a taller roof, and uses its openings and GM opacity', () => {
  const scene = {...map, roofs: {height_ft: 60, openings: [{x: 4, y: 4, kind: 'trapdoor', open: true}]}};
  const {board, raised} = setup(actor(), area(), scene);
  assert.match(maskXML(raised), /area-roof-0/);
  assert.match(maskXML(raised), /Open trapdoor/, 'same aperture artwork as roof painter');
  board.setRoofView({gm: true});
  assert.match(maskXML(raised), /opacity="0.28"/);
  board.setRoofView({gm: false, viewers: [{position: {x: 4, y: 4, z: 0}}]});
  assert.doesNotMatch(maskXML(raised), /area-roof-0/, 'roof hidden for interior audience stops occluding');
});

test('lower objects are behind raised art; taller objects mask their actual silhouette', () => {
  const object = (id, x, height_ft) => ({id, x, y: 8, z: 0, object: true, kind: 'test-pillar',
    height_ft, name: id, conditions: []});
  const {board, raised, elevated} = setup(actor(), area(), map, [object('low', 1, 5), object('high', 8, 60)]);
  above(board, elevated, board.tokenNode('low').parentNode);
  assert.doesNotMatch(maskXML(raised), /<rect x="1" y="8"/);
  assert.match(maskXML(raised), /<rect x="8" y="8"/);
});

test('height-only updates reparent existing canvases, clear stale masks, and keep fog clipping', () => {
  const {board, doc, ground, elevated} = setup(actor(0), area({center: {x: 4, y: 4, z: 0}}));
  board.setTokens([actor()]);
  const raised = doc.querySelector('.tt-area-raised');
  assert.ok(raised.contains(ground), 'ascent does not need another zone payload');
  assert.equal(raised.style.maskImage, 'none');
  const seen = new Uint8Array(100); seen[44] = 1;
  board.setFog(seen, null, {squareFog: true});
  assert.ok(elevated.style.maskImage.startsWith('url('));
  assert.equal(elevated.style.maskImage, doc.querySelector('.tt-zones-clouds').style.maskImage);
  board.setTokens([actor(0)]);
  assert.equal(ground.parentNode, doc.querySelector('.tt-zones-ground'));
  assert.match(maskXML(doc.querySelector('.tt-area-cloud')), /area-roof-0/);
  board.setFog(null);
  assert.equal(elevated.style.maskImage, 'none');
});

test('newly introduced object art replaces its temporary mask and absent heights use scenery defaults', () => {
  const {board, raised} = setup(actor(1), area({center: {x: 4, y: 4, z: 1}}), {...map, walls: [], floors: []});
  const pillar = {id: 'pillar', object: true, name: 'Pillar', kind: 'pillar', x: 8, y: 8,
    height_ft: undefined, conditions: []};
  board.setTokens([actor(1), pillar]);
  assert.match(maskXML(raised), /<svg x="8" y="8"/, 'default 10 ft pillar masks with its arranged art, not a temporary box');
  board.setTokens([actor(1), {...pillar, height_ft: 0}]);
  assert.equal(raised.style.maskImage, 'none', 'an explicit zero-height object does not cover an elevated area');
});

test('source height covers owner auras, anchors, emanations and independently placed areas without name checks', () => {
  const owner = {position: {z: 8}}, target = {position: {z: 3}};
  const lookup = id => ({caster: owner, target})[id];
  assert.equal(areaHeightFt(area(), lookup), 40);
  assert.equal(areaHeightFt(area({trigger_profile: {anchor_id: 'target'}}), lookup), 15);
  assert.equal(areaHeightFt(area({center: {z: 2}, trigger_profile: {follows_owner: true}}), lookup), 40);
  assert.equal(areaHeightFt(area({center: {z: 2}, trigger_profile: {shape: 'sphere'}}), lookup), 10);
  assert.equal(areaHeightFt(area({center: {z: 0}, trigger_profile: {shape: 'emanation'}}), lookup), 0);
  assert.equal(areaHeightFt(area({center: {z: 8}, affected_cells: [{x: 4, y: 4}],
    trigger_profile: {shape: 'painted'}}), lookup), 0, 'a painted ground area ignores its owner-centred centre');
});

test('a painted area is drawn on its recorded cells, never on a flying owner centre', () => {
  // Real producer payload (verdant_chassis.py grove_ground): centre = owner
  // position at z=8, cells are ground Positions that serialize without z.
  const payload = area({center: {x: 4, y: 4, z: 8},
    affected_cells: [{x: 1, y: 1}, {x: 2, y: 1}, {x: 2, y: 2}],
    trigger_profile: {shape: 'painted', follows_owner: false, aura: true}});
  assert.equal(cellPlaneFt(payload), 0);
  assert.equal(areaHeightFt(payload, () => null), 0, 'ground claims stay on the ground');
  // A claim painted on a roof follows its cells' height.
  assert.equal(areaHeightFt(area({center: {x: 4, y: 4, z: 0}, affected_cells: [{x: 1, y: 1, z: 3}],
    trigger_profile: {shape: 'painted'}}), () => null), 15);
  // The lowest cell wins when a painted area covers two levels.
  assert.equal(cellPlaneFt({affected_cells: [[1, 1, 2], [2, 1, 1]]}), 5);
});

for (const reverse of [false, true]) test(`raised mist remains above darkness regardless of arrival order (${reverse})`, () => {
  const {board, doc} = setup();
  const cloud = area(), dark = area({zone_id: 'dark', trigger_profile: {aura: true, name: 'Darkness',
    visual: {material: 'darkness', darkness: true}}});
  board.setZones(reverse ? [dark, cloud] : [cloud, dark]);
  const planes = doc.querySelectorAll('.tt-area-raised');
  assert.equal(planes.length, 1, 'one composition plane per source height');
  const mist = planes[0].querySelector('.is-light'), darkness = planes[0].querySelector('.is-dark');
  const cloudBand = mist.parentNode.parentNode, darkBand = darkness.parentNode;
  assert.ok(planes[0].children.indexOf(cloudBand) > planes[0].children.indexOf(darkBand));
  assert.equal(mist.parentNode.style.maskImage, 'none', 'raised cloud uses the shared scenery mask only once');
  board.setZones([cloud]);
  assert.ok(planes[0].contains(mist), 'retiring another area never retires a shared plane');
});

test('occlusion ignores lower/hidden scenery and wall outlines do not mask whole buildings', () => {
  assert.equal(areaOcclusionMask(10, 10, 40, [{top: 15, opacity: 1, markup: '<path/>'}]), 'none');
  assert.equal(areaOcclusionMask(10, 10, 40, [{top: 60, opacity: 0, markup: '<path/>'}]), 'none');
  assert.match(wallSilhouette(map.walls[0], map.walls), /fill="none"/);
  assert.match(wallSilhouette({shape: 'line', points: [[2, 2], [2, 6]], filled: true}, []), /fill="none"/);
});

// A ground claim as the real producer builds it: the owner may be flying, but
// the centre is the owner's position and the cells are ground squares (no z).
const groundCells = Array.from({length: 64}, (_, i) => ({x: 1 + i % 8, y: 1 + Math.floor(i / 8)}));
const groveClaim = ownerZ => area({center: {x: 4, y: 4, z: ownerZ}, affected_cells: groundCells,
  trigger_profile: {name: 'Grove Domain: Living Claims are difficult terrain for enemies',
    terrain: [], difficult: 'hostile', obscured: null, color: null, follows_owner: false, shape: 'painted',
    size_ft: 5, triggers: [], move_through: null, talents: [], inside: [], aura: true,
    visual: {material: 'foliage'}}});

test('Grove Domain Living Claims stay at ground height when their owner flies', () => {
  const {board, roof, ground, raised} = setup(actor(8), groveClaim(8));
  assert.equal(raised, null, 'an owner-centred painted ground claim does not rise with the owner');
  above(board, roof, ground.parentNode);
});

test('Grove Domain Living Claims do not rise when the owner height changes after placement', () => {
  const {board} = setup(actor(0), groveClaim(0));
  assert.equal(board.element.querySelector('.tt-area-raised'), null);
  // The engine re-sends the zone on the owner's turn: refresh token AND the
  // regenerated payload centred on the now-flying owner.
  board.setTokens([actor(8)]);
  board.setZones([groveClaim(8)]);
  assert.equal(board.element.querySelector('.tt-area-raised'), null, 'owner ascent does not lift the ground claims');
  const live = [...board.element.querySelectorAll('.tt-zone-ground')].filter(node => !node.classList.contains('tt-zone-leave'));
  assert.ok(live.length, 'the regenerated claim still renders on the ground plane');
});

test('a taller tree occludes an elevated aura by its silhouette while a lower tree does not', () => {
  const pine = {x: 1, y: 8, size: 1, look: 'pine'}, cherry = {x: 8, y: 8, size: 1, look: 'cherry'};
  const scene = {...map, trees: [pine, cherry]};
  const {raised} = setup(actor(5), area({center: {x: 4, y: 4, z: 5}}), scene);
  const mask = maskXML(raised);
  assert.match(mask, new RegExp(`<use href="#${treeShapeId(pine)}" x="1" y="8"`), '40 ft pine masks with its visible silhouette');
  assert.doesNotMatch(mask, /<rect x="1" y="8"/, 'the trunk-footprint rectangle is not the occluder');
  assert.doesNotMatch(mask, new RegExp(treeShapeId(cherry)), '20 ft cherry does not mask a 25 ft aura');
});

test('the tree silhouette reaches outside its trunk square so the mask covers the crown', () => {
  const pine = {x: 1, y: 8, size: 1, look: 'pine'};
  const layer = treeLayerMarkup([pine]);
  const shape = layer.match(new RegExp(`<g id="${treeShapeId(pine)}"[^>]*>[\\s\\S]*?</g>`))?.[0];
  assert.ok(shape, 'the shared pine drawing is emitted with its definitions');
  const coords = [...shape.matchAll(/\bd="([^"]+)"/g)]
    .flatMap(([, d]) => [...d.matchAll(/-?\d+(?:\.\d+)?/g)].map(n => Number(n[0])));
  assert.ok(Math.max(...coords) > 1 && Math.min(...coords) < 0,
    'the pine drawing spans beyond the unit trunk square, i.e. it draws canopy, not just the trunk');
});

test('changing a tree height rebuilds the occluder cache key', () => {
  const shortPine = {x: 1, y: 8, size: 1, look: 'pine', height_ft: 10};
  const scene = {...map, trees: [shortPine]};
  const {board, raised} = setup(actor(5), area({center: {x: 4, y: 4, z: 5}}), scene);
  assert.equal(raised.style.maskImage, 'none', 'a 10 ft tree does not mask a 25 ft aura');
  board.setMap({...scene, trees: [{...shortPine, height_ft: 40}]});
  const raisedAfter = board.element.querySelector('.tt-area-raised');
  assert.match(maskXML(raisedAfter), new RegExp(`<use href="#${treeShapeId(shortPine)}" x="1" y="8"`),
    'the taller authored tree now masks with its silhouette');
});
