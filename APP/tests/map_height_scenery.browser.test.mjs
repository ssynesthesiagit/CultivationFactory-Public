// Lead-only rendering check: RUN_MAPHEIGHT_BROWSER_TESTS=1 node --test this file
// outside the sandbox. The default run skips before any server/browser starts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {homedir} from 'node:os';
import {flightStaticHandler} from './flight_ui_static_server.mjs';

test('rendered editor explains raised/zero spans and the complete grouped edit scope', {
  skip: process.env.RUN_MAPHEIGHT_BROWSER_TESTS !== '1',
}, async () => {
  const require = createRequire(import.meta.url);
  const {chromium} = require(require.resolve('playwright', {paths: [
    process.env.PLAYWRIGHT_MODULES || homedir() + '/Projects/hermes-agent/node_modules',
  ]}));
  const defaults = JSON.parse(readFileSync(new URL('../combat/rules/objects.json', import.meta.url)));
  let saved = {map_id: 'height-fixture', display_name: 'Scenery height yard',
    width_squares: 12, height_squares: 8, background: {style: 'flagstone'}, display: {},
    walls: [], objects: [], starts: {team1: [[1, 1]], team2: [[10, 6]]},
    trees: [{x: 4, y: 4, size: 1, height_ft: 11, base_altitude_ft: 10}],
    terrain: [{type: 'SIMPLE_COVER', look: 'handcart', cells: [[5, 5], [1, 6], [2, 6]],
      height_ft: 11, base_altitude_ft: 10}],
    materials: [{material: 'terrain:bamboo thicket', cells: [[8, 4], [9, 4], [8, 5], [9, 5]],
      height_ft: 11, base_altitude_ft: 10},
    {material: 'terrain:bamboo thicket', cells: [[1, 2], [2, 2], [1, 3], [2, 3], [8, 1], [9, 1], [8, 2], [9, 2]],
      height_ft: 13, base_altitude_ft: 10}]};
  const server = createServer(flightStaticHandler());
  let browser;
  try {
    await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done); });
    browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
    const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let result;
      if (path === '/api/session') result = {token: 'test'};
      else if (path === '/api/tabletop/terrains') result = {terrains: [], ground: {}};
      else if (path === '/api/tabletop/maps' && route.request().method() === 'POST') {
        saved = route.request().postDataJSON().map; result = saved;
      } else if (path === '/api/tabletop/maps') result = {maps: [], object_defaults: defaults};
      else if (path === '/api/tabletop/maps/height-fixture') result = saved;
      else throw Error('Unexpected mock API: ' + path);
      await route.fulfill({json: result});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/static/tabletop/mapeditor.html`);
    await page.waitForFunction(() => window.mapEditor);
    await page.evaluate(() => window.mapEditor.open('map:height-fixture'));
    const field = (family, index = 0) => page.locator(`.me-scenery-height[data-family="${family}"][data-index="${index}"]`);
    const row = (family, index = 0) => field(family, index).locator('xpath=ancestor::li');
    assert.match(await row('terrain').innerText(), /group · 3 squares · edits all 3 together/);
    assert.match(await row('material').innerText(), /group · 4 squares · edits all 4 together/);
    assert.match(await row('material', 1).innerText(), /group · 8 squares · edits all 8 together/);
    assert.match(await field('material', 1).getAttribute('aria-label'), /8 squares.*edits all 8 together/);
    async function hover(x, y) {
      const point = await page.evaluate(([x, y]) => {
        const {board} = window.mapEditor;
        board.closeHoverCard();
        const box = board.viewport.getBoundingClientRect(), view = board.view;
        return {x: box.left + view.x + (x + .5) * 48 * view.zoom,
          y: box.top + view.y + (y + .5) * 48 * view.zoom};
      }, [x, y]);
      // Moving away first also retriggers the card for the same square after an edit.
      await page.mouse.move(0, 0);
      await page.mouse.move(point.x, point.y);
      await page.locator('.tt-zone-tip').waitFor({state: 'visible'});
      return page.locator('.tt-zone-tip').innerText();
    }
    for (const [x, y] of [[4, 4], [5, 5], [8, 4]])
      assert.match(await hover(x, y), /from 10 ft up to, but not including, 21 ft above ground/);
    for (const family of ['tree', 'terrain', 'material']) {
      await field(family).fill('0'); await field(family).dispatchEvent('change');
    }
    assert.match(await hover(4, 4), /Zero height: this trunk does not block sight or movement/);
    assert.match(await hover(5, 5), /Zero height: this scenery provides no cover/);
    assert.match(await hover(8, 4), /Zero height: this bamboo does not block sight/);
    await field('material', 1).fill('12'); await field('material', 1).dispatchEvent('change');
    await page.evaluate(async () => { await window.mapEditor.save(); await window.mapEditor.open('map:height-fixture'); });
    assert.equal(await field('material', 1).inputValue(), '12');
    assert.match(await row('material', 1).innerText(), /group · 8 squares · edits all 8 together/);
    assert.equal(saved.materials[1].cells.length, 8);
  } finally {
    await browser?.close();
    if (server.listening) await new Promise(done => server.close(done));
  }
});
