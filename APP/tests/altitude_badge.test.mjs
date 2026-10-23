// Production table presentation -> real board DOM. No browser or model server.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createTableHarness, tableState, actor} from './viewer_identity_harness.mjs';

const source = readFileSync(process.env.TOKENALT_TABLE_SOURCE
  || new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const map = {width: 10, height: 10, background: {style: 'plain'},
  walls: [{shape: 'rect', points: [[2, 2], [7, 7]], blocks: 'movement', filled: false}],
  floors: [{style: 'wood', cells: Array.from({length: 16}, (_, i) => [3 + i % 4, 3 + Math.floor(i / 4)])}]};

function table(extra = {}) {
  // This is the service presentation shape: x/y position plus altitude_ft.
  const fighter = actor('own', {x: 4, y: 4}, {altitude_ft: 40, ...extra});
  return createTableHarness({gm: true, source, state: tableState([fighter], {map})});
}
function badge(t, text) {
  const node = t.board.tokenNode('own'), height = node.querySelector('.tt-token-height');
  assert.equal(height.textContent, text);
  assert.equal(height.hidden, !text);
  return node;
}

for (const [mode, properties] of [
  ['flying', {fly_speed_ft: 40}], ['hovering', {fly_speed_ft: 40, hover: true}],
  ['levitating without fly speed', {fly_speed_ft: 0}],
]) {
  test(`${mode}: service altitude reaches the token badge without position.z`, () => {
    const t = table(properties);
    const node = badge(t, '↑40 ft');
    assert.match(node.getAttribute('aria-label'), /height 40 feet above the battlefield floor/);
    t.app.state.presentation.actors[0].altitude_ft = 0;
    t.renderTokens();
    badge(t, '');
  });
}

test('roof walker shows standing height with no flight capability', () => {
  const t = table({altitude_ft: 15, fly_speed_ft: 0, on_roof: true});
  const node = badge(t, '↑15 ft');
  assert.ok(node.classList.contains('is-on-roof'));
  assert.match(node.querySelector('.tt-token-height').title, /Standing on the roof \(15 ft\)/);
});

test('temporary movement z overrides the previous presentation altitude', () => {
  const t = table();
  t.app.movePositions.set('own', {sequence: 2, position: {x: 4, y: 4, z: 3}});
  t.renderTokens();
  badge(t, '↑15 ft');
  t.app.mapPick = {positions: new Map([['own', {x: 4, y: 4, z: 0}]])};
  t.renderTokens();
  badge(t, '');
  t.app.mapPick = null;
  t.app.state.last_sequence = 2;
  t.app.state.presentation.actors[0].altitude_ft = 25;
  t.renderTokens();
  badge(t, '↑25 ft');
});
