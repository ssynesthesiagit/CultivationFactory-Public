// Lead-only visual acceptance: MAPART2_BROWSER=1 MAPART2_PLAYWRIGHT_MODULES=<node_modules>
// MAPART2_SCREENSHOTS=<disposable output directory> node --test tests/mapart2_round2.browser.test.mjs
// Run outside the sandbox. Serves only this checkout on an ephemeral port, with all APIs faked.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {resolve, join, sep} from 'node:path';

test('MAPART2 round-2 map editor screenshots', {skip: process.env.MAPART2_BROWSER !== '1'}, async () => {
  assert.ok(process.env.MAPART2_PLAYWRIGHT_MODULES && process.env.MAPART2_SCREENSHOTS,
    'Set the Playwright module directory and a disposable screenshot output directory.');
  const {chromium} = createRequire(join(process.env.MAPART2_PLAYWRIGHT_MODULES, 'noop.js'))('playwright');
  const root = fileURLToPath(new URL('../', import.meta.url));
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, path === '/tabletop/maps' ? 'static/tabletop/mapeditor.html' : `.${path}`);
    if (!file.startsWith(resolve(root) + sep)) { response.writeHead(404); response.end(); return; }
    try {
      const data = await readFile(file);
      response.writeHead(200, {'content-type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/octet-stream'});
      response.end(data);
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  let browser;
  try {
    await mkdir(process.env.MAPART2_SCREENSHOTS, {recursive: true});
    browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
    for (const name of ['mountain-pass', 'bamboo-forest-ravine', 'realm-waterfall-gorge', 'sunken-cavern-lake', 'realm-maple-shrine', 'ruined-spirit-shrine', 'ricefield-bamboo-valley']) {
      const map = JSON.parse(await readFile(join(root, `combat/maps/builtin-${name}.json`), 'utf8'));
      const page = await browser.newPage({viewport: {width: 1800, height: 1400}});
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        const result = path === '/api/session' ? {token: 'test'} : path === '/api/tabletop/terrains' ? {terrains: []}
          : path === '/api/tabletop/conditions' ? {conditions: {}} : path === '/api/tabletop/maps' ? {maps: [map], builtin: [], object_defaults: {}}
          : path === `/api/tabletop/maps/${map.map_id}` ? map : null;
        if (result) await route.fulfill({json: result}); else await route.abort();
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/tabletop/maps?map=${map.map_id}`);
      await page.waitForFunction(() => window.mapEditor);
      await page.waitForTimeout(500);
      assert.deepEqual(errors, [], name);
      assert.ok(await page.locator('.tt-board').count(), name);
      await page.screenshot({path: join(process.env.MAPART2_SCREENSHOTS, `builtin-${name}.png`), fullPage: true});
      await page.close();
    }
  } finally {
    await browser?.close();
    await new Promise(done => server.close(done));
  }
});
