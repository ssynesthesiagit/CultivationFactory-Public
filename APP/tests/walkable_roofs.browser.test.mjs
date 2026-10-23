// Opt-in rendered QA on an isolated ephemeral port. No live Factory, user data
// or lead artifact paths are used. See docs for the command and browser setup.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {join, resolve} from 'node:path';
import {flightStaticHandler} from './flight_ui_static_server.mjs';

test('rendered roof badge, keyboard level selection and editor save/reopen', {
  skip: process.env.RUN_ROOF_BROWSER_TESTS !== '1',
}, async () => {
  const moduleRoot = process.env.PLAYWRIGHT_MODULES || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
  const require = createRequire(moduleRoot ? join(moduleRoot, 'roof-browser-loader.cjs') : import.meta.url);
  const {chromium} = require('playwright');
  const out = resolve(fileURLToPath(new URL('../../.work/roof-browser/', import.meta.url)));
  const server = createServer(flightStaticHandler());
  let browser;
  try {
    browser = await chromium.launch({headless: true, ...(process.env.ROOF_CHROMIUM_EXECUTABLE
      ? {executablePath: process.env.ROOF_CHROMIUM_EXECUTABLE} : {}), args: ['--no-sandbox']});
    await mkdir(out, {recursive: true});
    await new Promise((done, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', done);});
    const base = `http://127.0.0.1:${server.address().port}`;
    const page = await browser.newPage({viewport: {width: 1280, height: 900}}), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base);
    await page.evaluate(async () => {
      const {createBoard} = await import('/static/tabletop/board.js?v=rel6-2');
      const {heightControl, roofLevelsAt} = await import('/static/tabletop/flight-ui.js?v=rel6-2');
      const map = {width: 10, height: 10, background: {style: 'grass'},
        walls: [{shape: 'rect', points: [[2, 2], [7, 7]], filled: false}],
        floors: [{style: 'wood', cells: Array.from({length: 16}, (_, i) => [3 + i % 4, 3 + Math.floor(i / 4)])}]};
      const host = document.querySelector('#board'); host.style.width = '960px'; host.style.height = '700px';
      window.roofBoard = createBoard(host); roofBoard.setMap(map); roofBoard.fit();
      const actor = {id: 'walker', name: 'Roof walker', x: 3, y: 3, z: 2, position: {x: 3, y: 3, z: 2},
        fly_speed_ft: 0, hp: 10, maxHp: 10, conditions: []};
      window.roofAt = (x, y, z) => {
        roofBoard.setTokens([{...actor, x, y, z, position: {x, y, z}, altitudeFt: z * 5}]);
        roofBoard.setRoofView({gm: false, viewers: [{entity_id: actor.id, position: {x, y, z}}]});
      };
      const moves = [{candidate_id: 'jump-down', movement_mode: 'jump_down', destination: {x: 1, y: 3, z: 0}, cost_ft: 5},
        {candidate_id: 'climb-up', movement_mode: 'climb', destination: {x: 3, y: 3, z: 2}, cost_ft: 30}];
      document.querySelector('#controls').appendChild(heightControl(moves, 2, false, z => {
        const move = moves.find(row => row.destination.z === z);
        window.roofCandidate = move.candidate_id;
        roofAt(move.destination.x, move.destination.y, z);
      }, roofLevelsAt(map, actor)));
      roofAt(3, 3, 2);
      roofBoard.setHighlights({moves: [{x: 4, y: 3, z: 2}, {x: 5, y: 3, z: 2}], path: [{x: 3, y: 3, z: 2}, {x: 4, y: 3, z: 2}]});
    });
    const picker = page.getByLabel('Move to height');
    assert.equal(await picker.locator('option').last().textContent(), '10 ft · roof');
    assert.equal(await page.locator('.tt-token-height').innerText(), '10 ft');
    await page.locator('.tt-token').hover();
    assert.match(await page.locator('.tt-token-card').innerText(), /on the roof \(10 ft\)/);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('[data-roof]')).opacity === '1');
    assert.equal(await page.locator('.tt-roof-marks .tt-mark-move').count(), 2);
    await picker.focus(); await page.keyboard.press('Home'); await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => window.roofCandidate), 'jump-down');
    assert.equal(await page.locator('.tt-token-height').isVisible(), false);
    await picker.focus(); await page.keyboard.press('End'); await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => window.roofCandidate), 'climb-up');
    await page.locator('.tt-token').hover();
    await page.screenshot({path: join(out, 'roof-walk-table.png')});
    await page.evaluate(() => roofAt(3, 3, 0));
    await page.waitForFunction(() => getComputedStyle(document.querySelector('[data-roof]')).opacity === '0');
    await page.evaluate(() => roofBoard.setRoofView({viewers: [{entity_id: 'other', position: {x: 0, y: 0, z: 0}}]}));
    await page.waitForFunction(() => getComputedStyle(document.querySelector('[data-roof]')).opacity === '1');

    const cells = Array.from({length: 16}, (_, i) => [3 + i % 4, 3 + Math.floor(i / 4)]);
    let saved = {map_id: 'roof-browser', display_name: 'Roof browser fixture', width_squares: 10, height_squares: 10,
      background: {style: 'grass'}, walls: [{shape: 'rect', points: [[2, 2], [7, 7]], blocks: 'movement', filled: false}],
      materials: [{material: 'floor:wood', cells}], terrain: [], objects: [], trees: [], starts: {team1: [], team2: []}};
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let json;
      if (path === '/api/session') json = {token: 'roof-browser-test'};
      else if (path === '/api/tabletop/terrains') json = {terrains: [], ground: {}};
      else if (path === '/api/tabletop/maps' && route.request().method() === 'POST') {
        saved = {...route.request().postDataJSON().map, map_id: 'roof-browser'}; json = saved;
      } else if (path === '/api/tabletop/maps') json = {maps: [], builtin: [], object_defaults: {presets: {}, groups: {}, materials: {}, sizes: {}}};
      else if (path === '/api/tabletop/maps/roof-browser') json = saved;
      else throw Error('Unexpected fixture API ' + path);
      await route.fulfill({json});
    });
    await page.goto(base + '/static/tabletop/mapeditor.html');
    await page.waitForFunction(() => window.mapEditor);
    await page.evaluate(() => window.mapEditor.open('map:roof-browser'));
    await page.selectOption('#meRoofBuilding', '3,3');
    await page.fill('#meRoofHeight', '15'); await page.press('#meRoofHeight', 'Tab');
    await page.selectOption('#meRoofClimbCheck', 'few_handholds');
    await page.locator('.me-roof-openings summary').click();
    await page.fill('#meRoofOpeningX', '4'); await page.fill('#meRoofOpeningY', '4');
    await page.selectOption('#meRoofOpeningKind', 'skylight'); await page.check('#meRoofOpeningOpen');
    await page.click('#meRoofOpeningSave');
    await page.evaluate(async () => {await window.mapEditor.save(); await window.mapEditor.open('map:roof-browser');});
    assert.equal(await page.inputValue('#meRoofHeight'), '15');
    assert.equal(await page.inputValue('#meRoofClimbCheck'), 'few_handholds');
    assert.deepEqual(saved.roofs.openings, [{x: 3, y: 3, kind: 'skylight', open: true}]);
    await page.locator('#meRoofHeight').scrollIntoViewIfNeeded();
    await page.screenshot({path: join(out, 'roof-walk-editor-wide.png')});
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('#meRoofHeight').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('.me-tools').evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    await page.screenshot({path: join(out, 'roof-walk-editor-narrow.png')});
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    if (server.listening) await new Promise(done => server.close(done));
  }
});
