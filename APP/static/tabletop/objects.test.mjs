import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {durability} from '../../tests/object_defaults_fixture.mjs';
import {OBJECT_FACE, objectArt} from './object-art.js?v=sol201';
import {handleObjectToolClick} from './object-delete.js?v=r24';
import {editorObjectStats, objectFacing, tableObjectTokens} from './object-presentation.js?v=rel6-2';

test('every object face has a top-down drawing or an intentional glyph fallback', () => {
  for (const kind of Object.keys(OBJECT_FACE)) {
    assert.doesNotThrow(() => objectArt(kind));
    assert.ok(objectArt(kind) === null || objectArt(kind).startsWith('<svg '), kind);
  }
  assert.equal(objectArt('future_kind'), null);
});

// Owner 2026-10-08: "half of them arent even in a form that represents the label". Every kind except the door,
// gate and window (another lane's) is a real top-down drawing: no glyph or emoji face, turned by its rotation.
const DRAWN = ['barricade', 'wall_section', 'pillar', 'statue', 'ice_block', 'crate', 'barrel', 'chest', 'cart', 'banner', 'rope', 'vine', 'bell', 'custom'];
const EMOJI = /\p{Extended_Pictographic}/u;

test('every placed prop kind is a top-down SVG drawing, never a glyph', () => {
  for (const kind of DRAWN) {
    const art = objectArt(kind);
    assert.ok(art && art.startsWith('<svg viewBox="0 0 64 64"'), kind);
    assert.match(art, /<path|<rect|<circle|<ellipse/, kind);
    assert.ok(art.length > 900, `${kind} is too sparse to be a drawing`);
    assert.doesNotMatch(art, EMOJI, kind);
    assert.doesNotMatch(OBJECT_FACE[kind], EMOJI, `${kind} falls back to an emoji face`);
    assert.match(art, /feGaussianBlur/, `${kind} stands on a soft contact shadow`);
  }
});

test('prop drawings honour rotation and facing, and keep their own ids apart', () => {
  for (const kind of DRAWN.filter(kind => kind !== 'bell')) {
    assert.match(objectArt(kind, {rotation: 90}), /rotate\(90 32 32\)/, kind);
    assert.match(objectArt(kind, {facing: 'west'}), /rotate\(180 32 32\)/, kind);
    assert.doesNotMatch(objectArt(kind), /rotate\(\d+ 32 32\)/, kind);
  }
  // The bell is drawn from a little to the south, so it hangs upright however it is turned.
  assert.doesNotMatch(objectArt('bell', {rotation: 90}), /rotate\(90 32 32\)/);
  const ids = art => [...art.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
  const first = ids(objectArt('barrel')), second = ids(objectArt('barrel'));
  assert.ok(first.length > 0);
  assert.equal(first.filter(id => second.includes(id)).length, 0, 'two barrels on one map must not share gradient ids');
});

test('the chest opens: lid back and coins showing', () => {
  const closed = objectArt('chest'), open = objectArt('chest', {open: true}), byState = objectArt('chest', {state: 'open'});
  const strip = art => art.replace(/tto\d+/g, 'ID');
  assert.notEqual(strip(open), strip(closed));
  assert.equal(strip(byState), strip(open));
});

test('door art changes from closed to open and honors facing', () => {
  const closed = objectArt('door');
  const open = objectArt('door', {open: true});
  assert.notEqual(open, closed);
  assert.match(open, /class="tt-art-arc"/);
  assert.match(objectArt('door', {facing: 'south'}), /rotate\(90 32 32\)/);
});

test('editor hover shows authoritative defaults and partial/full overrides', () => {
  const defaults = editorObjectStats({kind: 'door'}, 'Wooden door', durability);
  assert.equal(defaults.hp, 18);
  assert.equal(defaults.maxHp, 18);
  assert.match(defaults.detail, /18 HP \(default\)/);
  assert.match(defaults.detail, /15 AC \(default\)/);
  assert.doesNotMatch(defaults.detail, /1 HP|\? AC/);
  const partial = editorObjectStats({kind: 'door', hp: 9}, 'Wooden door', durability);
  assert.match(partial.detail, /9 HP \(override\).*15 AC \(default\)/);
  const acOnly = editorObjectStats({kind: 'door', ac: 12}, 'Wooden door', durability);
  assert.match(acOnly.detail, /18 HP \(default\).*12 AC \(override\)/);
  const material = editorObjectStats({kind: 'door', material: 'iron', size: 'small', resilient: false}, 'Iron door', durability);
  assert.match(material.detail, /3 HP \(default\).*19 AC \(default\)/);
  const overridden = editorObjectStats({kind: 'door', hp: 9, ac: 12}, 'Wooden door', durability);
  assert.equal(overridden.hp, 9);
  assert.match(overridden.detail, /9 HP \(override\)/);
  assert.match(overridden.detail, /12 AC \(override\)/);
});

test('every undrawn production object retains its kind glyph', () => {
  for (const kind of Object.keys(OBJECT_FACE).filter(kind => !objectArt(kind))) {
    const [token] = tableObjectTokens([{id: 'object:map.1', kind, x: 1, y: 1, name: kind, hp: 5, max_hp: 5}], new Set(), [], null, 8);
    assert.equal(token.label, OBJECT_FACE[kind], kind);
  }
});

test('editor and table infer the same door facing from wall cells', () => {
  const door = {id: 'object:map.1', kind: 'door', x: 3, y: 3};
  const blocked = [[3, 2], [3, 4]];
  const table = tableObjectTokens([door], new Set([door.id]), blocked, null, 8)[0];
  assert.equal(objectFacing(door, blocked), 'south');
  assert.equal(table.facing, 'south');
  assert.equal(table.targetable, true);
});

test('table and editor both consume the shared board object art module', async () => {
  const [board, table, editor] = await Promise.all([
    readFile(new URL('./board.js', import.meta.url), 'utf8'),
    readFile(new URL('./tabletop.js', import.meta.url), 'utf8'),
    readFile(new URL('./mapeditor.js', import.meta.url), 'utf8'),
  ]);
  assert.match(board, /from "\.\/object-art\.js\?v=sol201"/);
  assert.match(table, /from "\.\/board\.js\?v=ruler2"/);
  assert.match(editor, /from "\.\/board\.js\?v=ruler2"/);
});

for (const tool of ['object', 'erase']) test(`${tool} token click removes object and undo restores it`, () => {
  const original = {objects: [{id: 8, kind: 'door'}]};
  const history = [];
  const doc = structuredClone(original);
  const change = mutator => { history.push(JSON.stringify(doc)); mutator(doc); };
  assert.equal(handleObjectToolClick(tool, doc, 8, change), true);
  assert.deepEqual(doc.objects, []);
  Object.assign(doc, JSON.parse(history.pop()));
  assert.deepEqual(doc, original);
});
