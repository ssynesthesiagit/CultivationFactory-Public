import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {sourceInputsButton} from '../static/tabletop/source-inputs-button.js';

test('toolbar entry tracks forms and ignores obsolete reads', async () => {
  const html = await readFile(new URL('../static/tabletop/tabletop.html', import.meta.url), 'utf8');
  assert.match(html, /<button id="ttSourceInputs"[^>]*class="tt-tool"[^>]*hidden disabled/);
  const css = await readFile(new URL('../static/tabletop/tabletop.css', import.meta.url), 'utf8');
  assert.match(css, /\.tt-tool\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}/);
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

test('toolbar entry has the correct computed display', {skip: !process.env.SOURCE_INPUTS_BROWSER}, async () => {
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
      let forms = [];
      const update = (0, eval)(`(${factory})`)({button, enc: encodeURIComponent, api: async () => ({forms})});
      await update('fight');
      const empty = getComputedStyle(button).display;
      forms = [{}];
      await update('fight');
      return [empty, getComputedStyle(button).display];
    }, sourceInputsButton.toString());
    assert.deepEqual(displays, ['none', 'inline-flex']);
  } finally {
    await browser.close();
  }
});
