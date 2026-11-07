// The GM's private-declaration entry (#ttSourceInputs) follows the fight state the poll already returned:
// state.source_inputs_available. It never asks the /source-inputs endpoint itself, so an unchanged poll costs
// no extra request. The dialog (source-inputs.js) still reads the forms it needs when the GM opens it.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {sourceInputsButton} from '../static/tabletop/source-inputs-button.js';
import {actor, createTableHarness, tableState, IN, OUT} from './viewer_identity_harness.mjs';

const roster = () => [actor('A', OUT), actor('B', IN)];
const entry = h => h.document.getElementById('ttSourceInputs');

test('the Game Master entry follows the state availability, synchronously and with no read of its own', async () => {
  const html = await readFile(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  assert.match(html, /<button id="ttSourceInputs"[^>]*class="tt-tool"[^>]*hidden disabled/);
  const css = await readFile(new URL('../static/tabletop/tabletop.css', import.meta.url), 'utf8');
  assert.match(css, /\.tt-tool\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}/);
  const button = {hidden: true, disabled: true};
  let gm = true;
  const show = sourceInputsButton({button, allowed: () => gm});
  show(true);
  // No promise and no await: the entry has no request to wait for.
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  show(false);
  assert.equal(button.hidden, true);
  assert.equal(button.disabled, true);
  show(true);
  assert.equal(button.hidden, false);
  gm = false;
  show(false);
  assert.equal(button.hidden, true, 'owner declarations stay out of a player view');
  assert.equal(button.disabled, true);
});

test('the table shows the declaration entry only for a GM fight that has declarations', () => {
  const states = {withForms: true, withoutForms: false};
  for (const [name, available] of Object.entries(states)) {
    const state = {...tableState(roster()), source_inputs_available: available};
    const list = createTableHarness({gm: true, roster: roster(), state});
    assert.equal(list.currentViewer().status, 'gm');
    assert.equal(entry(list).hidden, !available, `GM table with ${name}`);
    assert.equal(entry(list).disabled, !available, `GM table with ${name}`);
    assert.deepEqual(list.calls.filter(call => String(call.url).includes('/source-inputs')), [],
      'drawing the table never reads the declaration endpoint');
    const player = createTableHarness({boundIds: ['A'], roster: roster(), state});
    assert.equal(entry(player).hidden, true, 'a player view never shows owner declarations');
    assert.equal(entry(player).disabled, true);
    assert.deepEqual(player.calls.filter(call => String(call.url).includes('/source-inputs')), []);
  }
});

test('the Game Master entry has the correct computed display', {skip: !process.env.SOURCE_INPUTS_BROWSER}, async () => {
  const {chromium} = createRequire(join(process.env.PLAYWRIGHT_MODULES, 'noop.js'))('playwright');
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const css = await readFile(new URL('../static/tabletop/tabletop.css', import.meta.url), 'utf8');
    const html = await readFile(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
    const button = html.match(/<button id="ttSourceInputs"[^>]*>.*?<\/button>/)[0];
    await page.setContent(`<style>${css}</style>${button}`);
    const displays = await page.evaluate(async (factory) => {
      const button = document.querySelector('#ttSourceInputs');
      const show = (0, eval)(`(${factory})`)({button});
      show(false);
      const empty = getComputedStyle(button).display;
      show(true);
      return [empty, getComputedStyle(button).display];
    }, sourceInputsButton.toString());
    assert.deepEqual(displays, ['none', 'inline-flex']);
  } finally {
    await browser.close();
  }
});
