import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {sourceInputsButton} from '../static/tabletop/source-inputs-button.js';

test('toolbar entry tracks forms and ignores obsolete reads', async () => {
  const html = await readFile(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  assert.match(html, /<button id="ttSourceInputs"[^>]*class="tt-tool"[^>]*hidden disabled/);
  const button = {hidden: true, disabled: true};
  const pending = [];
  const update = sourceInputsButton({button, enc: encodeURIComponent, api: path =>
    new Promise((resolve, reject) => pending.push({path, resolve, reject}))});
  let read = update('fight 1');
  assert.equal(pending[0].path, '/api/tabletop/matches/fight%201/source-inputs');
  pending.shift().resolve({forms: [{}]});
  await read;
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  read = update('fight 1');
  pending.shift().resolve({forms: []});
  await read;
  assert.equal(button.hidden, true);
  assert.equal(button.disabled, true);
  const old = update('old');
  const next = update('new');
  pending.pop().resolve({forms: [{}]});
  await next;
  pending.pop().resolve({forms: []});
  await old;
  assert.equal(button.hidden, false);
  await update(null);
  assert.equal(button.hidden, true);
  assert.equal(button.disabled, true);
});
