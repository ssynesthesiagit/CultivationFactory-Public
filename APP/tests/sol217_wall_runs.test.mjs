import test from 'node:test';
import assert from 'node:assert/strict';
import {installDOM} from './objects_dom_stub.mjs';
import {createBoard} from '../static/tabletop/board.js';
import {tableObjectTokens} from '../static/tabletop/object-presentation.js';
import {readdirSync, readFileSync} from 'node:fs';

const section = (x, y, state = 'intact', kind = 'wall_section') =>
  ({id: `${x}:${y}`, kind, x, y, state, hp: state === 'destroyed' ? 0 : 27, max_hp: 27, name: 'Stone wall'});
function render(rows, authored = rows) {
  installDOM('<body></body>');
  const clicks = [];
  const board = createBoard(document.body, {onTokenClick: id => clicks.push(id)});
  board.setMap({width: 20, height: 20, objects: authored});
  const tokens = tableObjectTokens(rows, new Set(rows.filter(r => r.hp).map(r => r.id)), [], null, 20);
  board.setTokens(tokens);
  return {board, clicks, tokens, faces: board.element.querySelectorAll('.tt-token-face').map(f => f.innerHTML)};
}
const edges = markup => /data-wall-edges="([^"]*)"/.exec(markup)?.[1];

test('table and editor map projections pass authored geometry to the real board', () => {
  const rows = [section(3, 2), section(3, 3), section(3, 4)];
  // Execute only the production map projections, without booting either UI.
  const table = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const projection = table.slice(table.indexOf('function mapFromState(state) {'), table.indexOf('\nfunction groveCells(state)'));
  const mapFromState = new Function('centerlineTerrain', 'groveCells', `${projection}; return mapFromState;`)(() => [], () => new Set());
  const tableMap = mapFromState({map: {objects: rows}, presentation: {battlefield: {width_squares: 20, height_squares: 20}}});
  assert.deepEqual(tableMap.objects, rows);
  const editor = readFileSync(new URL('../static/tabletop/mapeditor.js', import.meta.url), 'utf8');
  const expression = /board\.setMap\((\{[\s\S]*?\n  \})\);/.exec(editor)[1];
  const editorMap = new Function('doc', 'width', 'height', 'centerlineCells', 'cells', '$', 'cellsFromTerrain', 'GROUND', `return (${expression});`)(
    {objects: rows, walls: [], materials: []}, 20, 20, [], {blocked: [], sight: []}, () => ({checked: false}), () => [], {});
  assert.deepEqual(editorMap.objects, rows);
  for (const map of [tableMap, editorMap]) {
    const {faces} = render([rows[0], rows[2]], map.objects);
    faces.forEach(f => assert.match(f, /data-wall-axis="v"/));
    assert.deepEqual(faces.map(edges), ['wnes', 'wnes']);
  }
});

test('vertical sections rotate the real board-space pattern and meet without gaps', () => {
  const {faces} = render([section(3, 2), section(3, 3), section(3, 4)]);
  for (const face of faces) {
    assert.match(face, /data-wall-axis="v"/);
    assert.match(face, /patternTransform="rotate\(90\)"/);
    assert.match(face, /patternUnits="userSpaceOnUse"/);
    assert.match(face, /width="1" height="1" style="fill:url\(#[^)]+-v\);stroke:none"/);
  }
  assert.deepEqual(faces.map(edges), ['wne', 'we', 'wes']);
  faces.forEach((f, i) => assert.match(f, new RegExp(`viewBox="3 ${2+i} 1 1"`)));
});
test('horizontal sections retain horizontal courses and no internal end edges', () => {
  const {faces} = render([section(2, 3), section(3, 3), section(4, 3)]);
  faces.forEach(f => assert.match(f, /data-wall-axis="h"/));
  assert.deepEqual(faces.map(edges), ['wns', 'ns', 'nes']);
});
test('corner and T joins cover the whole joint without an internal outline', () => {
  const {faces} = render([section(2, 2), section(3, 2), section(3, 3)]);
  assert.deepEqual(faces.map(edges), ['wns', 'ne', 'wes']);
  const tee = render([section(2, 2), section(3, 2), section(4, 2), section(3, 3)]);
  assert.equal(edges(tee.faces[1]), 'n');
});
test('destroying the middle section opens exactly one square and preserves separate targets', async () => {
  const rows = [section(3, 2), section(3, 3), section(3, 4)];
  const {board, clicks, tokens} = render(rows);
  for (const node of board.element.querySelectorAll('.tt-token')) await node.click();
  assert.deepEqual(clicks, rows.map(r => r.id));
  board.setTokens(tableObjectTokens(rows.map((r, i) => i === 1 ? {...r, state: 'DESTROYED', hp: 0} : r), new Set([rows[0].id, rows[2].id]), [], null, 20));
  const faces = board.element.querySelectorAll('.tt-token-face').map(f => f.innerHTML);
  assert.equal(faces.filter(f => f.includes('data-wall-rubble')).length, 1);
  assert.doesNotMatch(faces[1], /style="fill:url/);
  assert.deepEqual([edges(faces[0]), edges(faces[2])], ['wnes', 'wnes']);
  assert.match(faces[0], /data-wall-axis="v"/); // destroyed neighbours retain the run's direction, not its fill
  assert.deepEqual(tokens.map(t => [t.id, t.hp, t.maxHp, t.targetable]), rows.map(r => [r.id, 27, 27, true]));
  // The production service omits destroyed objects altogether. This path must
  // leave a breach too, including on a fresh board (no prior rendering cache).
  board.setTokens(tableObjectTokens([rows[0], rows[2]], new Set([rows[0].id, rows[2].id]), [], null, 20));
  const updated = board.element.querySelectorAll('.tt-token-face').map(f => f.innerHTML);
  updated.forEach(f => assert.match(f, /data-wall-axis="v"/));
  const missing = render([rows[0], rows[2]], rows);
  assert.equal(missing.faces.length, 2);
  assert.deepEqual(missing.faces.map(edges), ['wnes', 'wnes']);
  missing.faces.forEach(f => assert.match(f, /data-wall-axis="v"/));
  assert.match(missing.faces[0], /viewBox="3 2 1 1"/);
  assert.match(missing.faces[1], /viewBox="3 4 1 1"/);
});

test('fogged or omitted neighbours affect exposed edges, never the authored axis', () => {
  for (const kind of ['wall_section', 'sandbag_wall']) {
    const rows = [section(3, 2, 'intact', kind), section(3, 3, 'intact', kind), section(3, 4, 'intact', kind)];
    const {board} = render(rows);
    const seen = new Uint8Array(400);
    seen[2 * 20 + 3] = seen[4 * 20 + 3] = 1;
    board.setTokens(tableObjectTokens(rows, new Set(), [], seen, 20));
    const faces = board.element.querySelectorAll('.tt-token-face').map(f => f.innerHTML);
    for (const i of [0, 2]) {
      assert.match(faces[i], /data-wall-axis="v"/);
      assert.equal(edges(faces[i]), 'wnes');
    }
    const fresh = render([rows[0], rows[2]], rows);
    fresh.faces.forEach(f => assert.match(f, /data-wall-axis="v"/));
    // Editor deletion changes authored geometry, unlike a combat breach or fog.
    fresh.board.setMap({width: 20, height: 20, objects: [rows[0], rows[2]]});
    fresh.board.setTokens(fresh.tokens);
    fresh.board.element.querySelectorAll('.tt-token-face').forEach(f => assert.match(f.innerHTML, /data-wall-axis="h"/));
  }
});

test('sandbag ramparts join too; unrelated or shared props retain their original art', () => {
  const bags = render([section(2, 2, 'intact', 'sandbag_wall'), section(2, 3, 'intact', 'sandbag_wall')]);
  bags.faces.forEach(f => assert.match(f, /rammed_earth-v/));
  const crates = render([section(2, 2, 'intact', 'crate'), section(2, 3, 'intact', 'crate')]);
  crates.faces.forEach(f => assert.doesNotMatch(f, /data-wall-axis/));
  const {board} = render([]);
  board.setTokens([{...section(2, 2), object: true, shared: true, scale: .5}]);
  assert.doesNotMatch(board.element.querySelector('.tt-token-face').innerHTML, /data-wall-axis/);
});

test('every shipped map uses the same seam-free section path, without altering its data', () => {
  const dir = new URL('../combat/maps/', import.meta.url);
  let sections = 0;
  for (const file of readdirSync(dir).filter(f => f.endsWith('.json'))) {
    const original = readFileSync(new URL(file, dir), 'utf8');
    const map = JSON.parse(original);
    const rows = (map.objects || []).map(r => ({...r, hp: r.hp ?? 27, max_hp: r.hp ?? 27}));
    const {faces} = render(rows);
    rows.forEach((r, i) => {
      if (r.kind !== 'wall_section' && r.kind !== 'sandbag_wall') return;
      sections++;
      assert.match(faces[i], /width="1" height="1" style="fill:url/);
    });
    assert.equal(readFileSync(new URL(file, dir), 'utf8'), original);
  }
  assert.ok(sections >= 35);
});
