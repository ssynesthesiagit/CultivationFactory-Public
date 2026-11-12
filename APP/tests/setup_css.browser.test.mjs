// Lead only, outside the sandbox:
// SETUPCSS_BROWSER=1 node --test --test-isolation=none APP/tests/setup_css.browser.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Script} from 'node:vm';
import {homedir} from 'node:os';

const root = new URL('../', import.meta.url);
const source = await readFile(new URL('static/tabletop/tabletop.js', root), 'utf8');
const start = source.indexOf('async function buildFightBuilder()');
const end = source.indexOf('// Both team and whole-setup saves', start);
assert.ok(start >= 0 && end > start, 'real builder source boundaries');
const builder = source.slice(start, end);
const css = await readFile(new URL('static/tabletop/tabletop.css', root), 'utf8');
const rule = /\.tt-slot select\s*\{[^}]*\}/g;
assert.equal([...css.matchAll(rule)].length, 1, 'one setup select rule to replace');
const oldCss = css.replace(rule, '.tt-slot select { min-width: 0; }');
const label = 'A very long installed model label — Qwen Large Local Reasoning Model';
const fixture = `
import {fighterPicker} from '/static/tabletop/fighter-picker.js';
import {canAddFighter} from '/static/tabletop/limits.js';
import {setupControlHtml, splitSetupControl, MODEL_PREFIX} from '/static/tabletop/seats.js';
let builderBuilt = false;
const app = {providers: [{id: 'long-model', label: ${JSON.stringify(label)}}]};
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const api = async path => path.endsWith('factory-characters')
  ? [{project_id: 'hero', display_name: 'Test Fighter', path: 'Martial', cultivation_level: 5}]
  : {maps: [], builtin: []};
// Only unrelated services/preset bars are stubbed; slot construction and face/options are real.
const loadProviders = async () => {};
const loadPrefight = async () => {};
const singleTeamBar = () => document.createElement('div');
const presetBar = () => document.createElement('div');
${builder}
await buildFightBuilder();
for (const team of document.querySelectorAll('.tt-team')) team.style.width = '262px';
for (const who of document.querySelectorAll('.tt-slot select[hidden]')) {
  who.value = 'hero'; who.dispatchEvent(new Event('change'));
}
window.setupCssReady = true;
`;

test('setup CSS fixture imports and real builder parse without a browser', () => {
  new Script(builder);
  // Parse the fixture body too; imports/top-level await belong to the module wrapper.
  new Script(`(async () => {${fixture.replace(/^import .*;$/gm, '')}})()`);
  assert.notEqual(css, oldCss);
});

function assertLayout(rows) {
  for (const row of rows) {
    const evidence = JSON.stringify(row);
    assert.equal(row.team.width, 262, evidence);
    assert.ok(row.face.width > 0 && row.face.height > 0, `face visible: ${evidence}`);
    assert.ok(row.face.right <= row.select.left + 0.5, `dropdown overlaps fighter face: ${evidence}`);
    assert.ok(row.portrait.right <= row.select.left + 0.5, `dropdown overlaps fighter portrait: ${evidence}`);
    assert.ok(row.name.width > 0 && row.name.height > 0 && row.nameVisible,
      `fighter name visible with non-zero width: ${evidence}`);
    assert.ok(row.name.left >= row.face.left && row.name.right <= row.face.right + 0.5,
      `fighter name inside face button: ${evidence}`);
  }
}

test('262px real setup slots preserve face/name for You, AI and a long model',
  {skip: process.env.SETUPCSS_BROWSER !== '1'}, async t => {
    const {chromium} = await import((process.env.PLAYWRIGHT_MODULES || homedir() + '/Projects/hermes-agent/node_modules') + '/playwright/index.mjs');
    const browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
    try {
      const page = await browser.newPage({viewport: {width: 900, height: 700}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('http://setupcss.test/**', async route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/') return route.fulfill({contentType: 'text/html', body:
          '<link rel="stylesheet" href="/static/themes.css"><link rel="stylesheet" href="/static/tabletop/tabletop.css">'
          + '<body class="tt-app"><div id="ttBuilder"></div><script type="module" src="/fixture.mjs"></script></body>'});
        if (path === '/fixture.mjs') return route.fulfill({contentType: 'text/javascript', body: fixture});
        // Serve only this checkout's static assets; no live service or data.
        if (!path.startsWith('/static/') || path.includes('..')) return route.abort();
        return route.fulfill({contentType: path.endsWith('.css') ? 'text/css' : 'text/javascript',
          body: await readFile(new URL('.' + path, root), 'utf8')});
      });
      await page.goto('http://setupcss.test/');
      await page.waitForFunction(() => window.setupCssReady);
      await page.evaluate(() => document.fonts.ready);
      assert.deepEqual(errors, []);
      const measure = () => page.evaluate(() => [...document.querySelectorAll('.tt-slot')].map(slot => {
        const face = slot.querySelector('.tt-slot-face');
        const name = face.querySelector('strong');
        const select = slot.querySelector('select:not([hidden])');
        const rect = node => {
          const {left, right, top, bottom, width, height} = node.getBoundingClientRect();
          return {left, right, top, bottom, width, height};
        };
        const style = getComputedStyle(name);
        return {selected: select.value, team: rect(slot.closest('.tt-team')), face: rect(face),
          portrait: rect(face.querySelector('.tt-pick-face')), name: rect(name), select: rect(select),
          nameVisible: style.display !== 'none' && style.visibility === 'visible' && Number(style.opacity) > 0};
      }));
      for (const value of ['MANUAL', 'LOCAL_AUTO', 'MODEL:long-model']) {
        for (const select of await page.locator('.tt-slot select:not([hidden])').all()) {
          await select.selectOption(value);
        }
        assert.equal(await page.locator('.tt-slot select:not([hidden]) option:checked').first().textContent(),
          value === 'MANUAL' ? 'You' : value === 'LOCAL_AUTO' ? 'AI' : label);
        const rows = await measure();
        assert.equal(rows.length, 2);
        assertLayout(rows);
        t.diagnostic(`current CSS ${value}: ${JSON.stringify(rows)}`);
      }
      // Replace the actual stylesheet rule, rather than override only min-width:
      // leaving max-width/field-sizing in place would not reproduce the old bug.
      await page.locator('link[href="/static/tabletop/tabletop.css"]').evaluate(node => node.remove());
      await page.addStyleTag({content: oldCss});
      const oldRows = await measure();
      assert.throws(() => assertLayout(oldRows), /dropdown overlaps|fighter name/,
        'the same geometry assertions must FAIL with the previous rule');
      t.diagnostic(`old-rule expected assertion FAILURE: ${JSON.stringify(oldRows)}`);
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  });
