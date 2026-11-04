import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {AFTERIMAGE_DETAIL, afterimageGhostArt, isAfterimageMarker} from './afterimage-ghost.js';
import {tableObjectTokens} from './object-presentation.js?v=afterimage-ghost-1';

// Owner-neutral row as the table sends an Afterimage (combat/tabletop_service.py map_marker rows): no HP, no owner.
const marker = {id: 'image:1', x: 4, y: 5, name: 'Afterimage', kind: 'TEMPORARY_IMAGE', altitude_ft: 0, height_ft: null,
  hp: null, max_hp: null, ac: null, blocks: false, map_marker: 1, footprint: 'medium',
  detail: 'A visible image left by movement. Creator: Sera the Owl'};
const crate = {id: 'crate:1', x: 1, y: 1, name: 'Crate', kind: 'crate', altitude_ft: 0, hp: 12, max_hp: 15, detail: 'AC 13'};

test('an Afterimage marker is flagged as an afterimage and gets the generic card, with no HP and no owner text', () => {
  const [token] = tableObjectTokens([marker], new Set(), [], null, 10, '', null);
  assert.equal(token.afterimage, true);
  assert.equal(token.hp, null);
  assert.equal(token.maxHp, null);
  assert.equal(token.detail, AFTERIMAGE_DETAIL);
  assert.equal(token.name, 'Afterimage');
  assert.doesNotMatch(JSON.stringify(token), /Sera|Owl/);
  assert.match(AFTERIMAGE_DETAIL, /disappears when successfully targeted or at the start of its creator's next turn/);
});

test('ordinary objects keep their own stats and are not afterimages', () => {
  const [token] = tableObjectTokens([crate], new Set(), [], null, 10, '', null);
  assert.equal(token.afterimage, false);
  assert.equal(token.hp, 12);
  assert.equal(token.maxHp, 15);
  assert.equal(isAfterimageMarker(crate), false);
  assert.equal(isAfterimageMarker(marker), true);
});

test('the Afterimage art is a translucent humanoid ghost, not a square or a glyph', () => {
  const art = afterimageGhostArt();
  assert.ok(art.startsWith('<svg viewBox="0 0 64 64" class="tt-afterimage-ghost"'));
  assert.match(art, /<path class="tt-afterimage-body"/);
  assert.match(art, /<path class="tt-afterimage-trail" transform="translate\(-3 1\)"/);
  assert.doesNotMatch(art, /<rect|<text|▣|\bid=/);
  assert.doesNotMatch(art, /\p{Extended_Pictographic}/u);
});

test('the board draws the ghost for Afterimage tokens and the stylesheet hides their HP and name plate', async () => {
  const board = await readFile(new URL('./board.js', import.meta.url), 'utf8');
  assert.match(board, /const ghost = Boolean\(data\.object && data\.afterimage\);/);
  assert.match(board, /const art = ghost \? afterimageGhostArt\(\)/);
  const css = await readFile(new URL('./tabletop.css', import.meta.url), 'utf8');
  const rule = css.match(/\.tt-token\.is-afterimage \.tt-token-ring[^{]*\{ display: none; \}/);
  assert.ok(rule, 'is-afterimage must hide the ring, HP bar and name plate');
  assert.match(rule[0], /\.tt-token-hp/);
  assert.match(rule[0], /\.tt-token-name/);
});
