// GHOSTMARK1: real board DOM and fog-memory lifecycle, without a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {installDOM} from '../../tests/objects_dom_stub.mjs';
import {createBoard} from './board.js';
import {emptyMemory, recordSeen, ghostCells} from './fog_memory.js';

installDOM('<body></body>');
const words = node => [node.textContent, ...node.children.map(words)].join(' ');
const saved = {tokens: [{id: 'stranger', name: 'Sun Taitian', label: 'ST'}]};
function fixture(record = saved) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const clicks = [];
  const board = createBoard(host, {onCellClick: cell => clicks.push(cell)});
  board.setMap({width: 4, height: 3, background: {style: 'plain'}, walls: [], trees: [], objects: []});
  const seen = new Uint8Array(12);
  board.setFog(seen);
  board.setRemembered({cells: {6: record}, ghosts: [6], changed: []});
  return {board, clicks};
}

test('GHOSTMARK1 remembers a ghost token with a known name, not bare initials', async () => {
  const {board} = fixture();
  const layer = board.element.querySelector('.tt-remembered-marks');
  assert.equal(layer.querySelectorAll('.tt-remembered-mark').length, 0);
  const ghost = layer.querySelector('.tt-remembered-token');
  assert.ok(ghost, 'remembered creature must have a ghost token');
  assert.equal(ghost.querySelector('.tt-remembered-token-label').textContent, 'ST');
  assert.ok(ghost.querySelector('circle'), 'initials belong inside the token face');
  assert.ok(Number(ghost.getAttribute('opacity')) <= 0.35);
  assert.ok(ghost.querySelector('circle').getAttribute('stroke-dasharray'));
  assert.match(ghost.getAttribute('style'), /grayscale/);
  assert.equal(ghost.getAttribute('pointer-events'), 'none');
  const timer = globalThis.setTimeout;
  globalThis.setTimeout = cb => { cb(); return 0; };
  try {
    await board.viewport.dispatch('pointermove', {clientX: 160, clientY: 96, buttons: 0});
    const card = document.body.querySelector('.tt-zone-tip');
    assert.ok(card, 'resting on the square opens the board hover card');
    assert.match(words(card), /Sun Taitian was here when you last saw this square\. They may have moved\./);
  } finally { globalThis.setTimeout = timer; }
});

test('GHOSTMARK1 visible tokens win, hidden truth does not change the memory', () => {
  const {board} = fixture();
  const ghost = board.element.querySelector('.tt-remembered-token');
  const token = {id: 'other', name: 'Hidden true name', x: 1, y: 0, size: 2};
  board.setTokens([token]);
  assert.equal(ghost.style.display, 'none', 'large visible token covers the remembered square');
  board.setTokens([{...token, hidden: true}]);
  assert.equal(ghost.style.display, '');
  assert.doesNotMatch(words(ghost), /Hidden true name/);
  board.setTokens([{...token, unseen: true}]);
  assert.equal(ghost.style.display, '');
  board.setTokens([]);
  assert.equal(ghost.style.display, '');
  board.setTokens([{...token, x: 2, y: 1, size: 1}]);
  board.setRemembered({cells: {6: saved}, ghosts: [6], changed: []});
  assert.equal(board.element.querySelector('.tt-remembered-token').style.display, 'none', 'also works when memory arrives after live tokens');
  board.setTokens([{...token, id: 'stranger', x: 0, y: 0, size: 1}]);
  assert.equal(board.element.querySelector('.tt-remembered-token').style.display, 'none', 'the same creature seen anywhere suppresses its old mark');
});

test('GHOSTMARK1B a saved portrait is drawn as a clipped ghost with its sight-time name', () => {
  const {board} = fixture({tokens: [{id: 'masked', name: 'A masked traveler', image: '/saved-portrait.png'}]});
  const ghost = board.element.querySelector('.tt-remembered-token');
  assert.equal(ghost.querySelector('image').getAttribute('href'), '/saved-portrait.png');
  assert.match(ghost.querySelector('image').getAttribute('clip-path'), /^url\(#tt-remembered-token-/);
  assert.equal(ghost.querySelector('.tt-remembered-token-label'), null);
  assert.match(ghost.querySelector('title').textContent, /^A masked traveler was here/);
  board.setTokens([{id: 'masked', name: 'Secret true name', image: '/new-portrait.png', hidden: true, x: 0, y: 0}]);
  assert.doesNotMatch(words(ghost), /Secret true name/);
  assert.equal(ghost.querySelector('image').getAttribute('href'), '/saved-portrait.png');
});

test('GHOSTMARK1 re-sighting an empty square erases the ghost, including later fog', () => {
  const {board} = fixture();
  const seen = new Uint8Array(12); seen[6] = 1;
  const memory = recordSeen(emptyMemory(), seen, () => saved);
  const refreshed = recordSeen(memory, seen, () => ({tokens: []}));
  board.setFog(seen);
  board.setRemembered({cells: refreshed.cells, ghosts: ghostCells(refreshed, seen), changed: []});
  assert.equal(board.element.querySelector('.tt-remembered-token'), null);
  seen.fill(0);
  board.setFog(seen);
  board.setRemembered({cells: refreshed.cells, ghosts: ghostCells(refreshed, seen), changed: []});
  assert.equal(board.element.querySelector('.tt-remembered-token'), null);
});

test('GHOSTMARK1B perceived creature outside the seen anchor clears memories without changing hidden identities', () => {
  const cells = {6: saved, 7: {tokens: [{id: 'hidden', name: 'A masked traveler'}]}};
  const seen = new Uint8Array(12);
  const next = recordSeen({version: 3, cells}, seen, () => ({}), {visibleTokenIds: ['stranger']});
  assert.deepEqual(next.cells[6].tokens, []);
  assert.equal(next.cells[7], cells[7], 'unseen creature keeps only its sight-time identity');
  assert.equal(cells[6], saved, 'previous snapshot is immutable');
});

test('GHOSTMARK1 ghost square still receives normal map clicks', async () => {
  const {board, clicks} = fixture();
  const event = {pointerId: 1, clientX: 160, clientY: 96, button: 0};
  await board.viewport.dispatch('pointerdown', event);
  await board.viewport.dispatch('pointerup', event);
  assert.deepEqual(clicks, [{x: 2, y: 1}]);
});
