// Opt-in only: the lead runs Chromium outside the worker sandbox.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {join, resolve} from 'node:path';
import {flightStaticHandler} from './flight_ui_static_server.mjs';

test('aura height: flying over roof, beside roof, placed ground area and taller roof screenshots', {
  skip: process.env.RUN_AURALAYER1_BROWSER_TESTS !== '1',
}, async () => {
  const moduleRoot = process.env.PLAYWRIGHT_MODULES || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
  const require = createRequire(moduleRoot ? join(moduleRoot, 'aura-browser-loader.cjs') : import.meta.url);
  const {chromium} = require('playwright');
  const out = resolve(process.env.AURALAYER1_SCREENSHOTS || '/var/tmp/auto-audit/fix/AURALAYER1-browser');
  const server = createServer(flightStaticHandler());
  let browser;
  try {
    await new Promise((done, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', done);});
    browser = await chromium.launch({headless: true, executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
    await mkdir(out, {recursive: true});
    const page = await browser.newPage({viewport: {width: 1000, height: 820}}), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
      const {createBoard} = await import('/static/tabletop/board.js?v=auralayer1');
      const {map, actor, area} = await import('/tests/area_elevation_fixture.mjs');
      const host = document.querySelector('#board');
      host.style.width = '960px'; host.style.height = '760px';
      const board = createBoard(host);
      window.auraCase = name => {
        const ground = name === 'beside-roof', placed = name === 'placed-ground';
        const at = ground ? {...actor(0), x: 1, position: {x: 1, y: 4, z: 0}} : actor();
        const zone = area(placed ? {center: {x: 4, y: 4, z: 0}, trigger_profile: {
          name: 'Ground Fragrance', follows_owner: false, shape: 'sphere', visual: {material: 'vines', obscured: 'light'}}}
          : {center: at.position});
        board.setZones([]);
        board.setMap(name === 'taller-roof' ? {...map, roofs: {height_ft: 60}} : map);
        board.setTokens([at]); board.setRoofView({gm: false, viewers: []}); board.setZones([zone]); board.fit();
      };
    });
    for (const name of ['flying-over-roof', 'beside-roof', 'placed-ground', 'taller-roof']) {
      await page.evaluate(name => window.auraCase(name), name);
      await page.waitForTimeout(700); // zone retirement / natural material entrance
      const state = await page.evaluate(() => {
        const raised = document.querySelector('.tt-area-raised'), cloud = document.querySelector('.tt-area-cloud');
        return {raised: !!raised, height: raised?.dataset.heightFt, mask: raised?.style.maskImage || cloud?.style.maskImage,
          afterRoof: !!(document.querySelector('.tt-roofs').compareDocumentPosition(document.querySelector('.tt-zones-elevated')) & Node.DOCUMENT_POSITION_FOLLOWING)};
      });
      assert.equal(state.raised, ['flying-over-roof', 'taller-roof'].includes(name));
      if (state.raised) {assert.equal(state.height, '40'); assert.equal(state.afterRoof, true);}
      assert.equal(state.mask === 'none', name === 'flying-over-roof');
      await page.screenshot({path: join(out, `${name}.png`)});
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await new Promise(done => server.close(done));
  }
});
