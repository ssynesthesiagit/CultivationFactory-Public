// Opt-in only. Lead runs outside sandbox; this file never launches by default.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {homedir} from 'node:os';
import {dirname} from 'node:path';
import {flightStaticHandler} from './flight_ui_static_server.mjs';

test('flight height selector and airborne token in the rendered board', {
  skip: process.env.RUN_TABLETOP_BROWSER_TESTS !== '1',
}, async () => {
  const require = createRequire(import.meta.url);
  const {chromium} = require(require.resolve('playwright', {paths: [
    process.env.PLAYWRIGHT_MODULES || homedir() + '/Projects/hermes-agent/node_modules',
  ]}));
  const server = createServer(flightStaticHandler());
  let browser;
  try {
    await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done); });
    browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
    const page = await browser.newPage();
    const moduleFailures = [];
    page.on('requestfailed', request => {
      if (/\.(?:m?js)(?:\?|$)/.test(request.url())) moduleFailures.push(`${request.url()}: ${request.failure()?.errorText}`);
    });
    page.on('response', response => {
      if (/\.(?:m?js)(?:\?|$)/.test(response.url()) && !response.ok()) moduleFailures.push(`${response.url()}: HTTP ${response.status()}`);
    });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
      const {createBoard} = await import('/static/tabletop/board.js');
      const {heightControl, flightText, movesAtHeight} = await import('/static/tabletop/flight-ui.js');
      const moves = [0, 1, 2].map(z => ({candidate_id: `move-${z}`, destination: {x: 1, y: 1, z}, cost_ft: z * 5}));
      const board = createBoard(document.querySelector('#board'));
      const token = {id: 'a', x: 1, y: 1, hp: 10, maxHp: 10, name: 'Sparrow flyer', conditions: [{name: 'Blinded'}]};
      const show = z => {
        window.selectedFlightCandidate = movesAtHeight(moves, z)[0].candidate_id;
        board.setTokens([{...token, altitudeFt: z * 5,
          flightDetail: flightText({altitude_ft: z * 5, fly_speed_ft: 15})}]);
      };
      const controls = document.querySelector('#controls');
      controls.className = 'tt-actionbar';
      controls.innerHTML = '<div class="tt-ab-group"><h3>Move</h3><div class="tt-ab-buttons"><button class="tt-btn"><b>Show moves</b><small>30 ft left</small></button></div></div>';
      window.normalFlightBarHeight = controls.getBoundingClientRect().height;
      const row = controls.querySelector('.tt-ab-buttons');
      row.appendChild(heightControl(moves, 0, true, show));
      const vertical = document.createElement('button');
      vertical.className = 'tt-btn';
      vertical.innerHTML = '<b>Move up here to 10 ft</b><small>Costs 10 ft movement</small>';
      row.appendChild(vertical);
      show(0);
    });
    assert.equal(await page.locator('.tt-flight-now').innerText(), 'Now 0 ft');
    assert.equal(await page.locator('#controls').evaluate(node => node.getBoundingClientRect().height),
      await page.evaluate(() => window.normalFlightBarHeight), 'flight controls keep the normal bar height');
    await page.getByLabel('Fly to height').selectOption('2');
    assert.equal(await page.evaluate(() => window.selectedFlightCandidate), 'move-2');
    assert.equal(await page.locator('.tt-token-height').innerText(), '↑10 ft');
    const badgeLayout = await page.locator('.tt-token').evaluate(node => {
      const badge = node.querySelector('.tt-token-height');
      const height = badge.getBoundingClientRect();
      const overlaps = selector => {
        const marker = node.querySelector(selector).getBoundingClientRect();
        return height.left < marker.right && height.right > marker.left
          && height.top < marker.bottom && height.bottom > marker.top;
      };
      return {display: getComputedStyle(badge).display, width: height.width,
        hp: overlaps('.tt-token-hp'), conditions: overlaps('.tt-token-conds')};
    });
    assert.notEqual(badgeLayout.display, 'none');
    assert.ok(badgeLayout.width > 0);
    assert.equal(badgeLayout.hp, false);
    assert.equal(badgeLayout.conditions, false);
    assert.equal(await page.locator('.tt-token').evaluate(node => getComputedStyle(node, '::before').content), '""');
    assert.equal(await page.locator('.tt-flight-now').innerText(), 'Now 0 ft', 'choosing a destination does not relabel current height');
    await page.locator('.tt-token').hover();
    await page.waitForSelector('.tt-token-card', {state: 'visible'});
    assert.match(await page.locator('.tt-token-card').innerText(), /Height: 10 ft.*Fly speed: 15 ft/);
    if (process.env.FLIGHTUI_SCREENSHOT) {
      await mkdir(dirname(process.env.FLIGHTUI_SCREENSHOT), {recursive: true});
      await page.screenshot({path: process.env.FLIGHTUI_SCREENSHOT});
    }
    await page.getByLabel('Fly to height').selectOption('0');
    assert.equal(await page.locator('.tt-token-height').isVisible(), false);
    assert.equal(await page.locator('.tt-token.is-airborne').count(), 0);
    // Browser linking/evaluation of the complete entry graphs, including real ?v= imports.
    // API data is empty: this is a module-load check, not a live fight acceptance test.
    await page.route('**/api/**', route => route.fulfill({json: {projects: [], characters: [], matches: [], maps: [], providers: []}}));
    for (const entry of ['tabletop', 'sheet']) {
      await page.goto(`http://127.0.0.1:${server.address().port}/module-check/${entry}.html`);
      try {
        await page.evaluate(async name => {
          await import(`/static/tabletop/${name}.js?v=${name === 'tabletop' ? 'flightui2' : 'flightui1'}`);
          // Both entry points load dice dynamically; await its graph explicitly too.
          await import('/static/tabletop/dice3d.js');
        }, entry);
      } catch (error) {
        throw new Error(`${entry}.js browser import failed; requests: ${moduleFailures.join('; ')}`, {cause: error});
      }
    }
    assert.deepEqual(moduleFailures, [], 'all entry-point module requests must succeed');
  } finally {
    await browser?.close();
    if (server.listening) await new Promise(done => server.close(done));
  }
});
