// Lead-only Chromium acceptance. Never enabled by the ordinary node/pytest gate.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {createRequire} from 'node:module';
import {homedir} from 'node:os';
import {readFile} from 'node:fs/promises';
import {resolve, extname} from 'node:path';
import {flightStaticHandler, appRoot} from './flight_ui_static_server.mjs';

test('owner UI: real hit testing, left/right travel, scroll, refresh and one height badge', {
  skip: process.env.RUN_UIREGRESS_BROWSER !== '1',
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
    const page = await browser.newPage({viewport: {width: 1200, height: 700}});
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
      const {createBoard} = await import('/static/tabletop/board.js');
      const host = document.querySelector('#board');
      host.style.cssText = 'width:1100px;height:600px;position:relative';
      const board = window.contractBoard = createBoard(host);
      board.setMap({width: 16, height: 9, background: {style: 'plain'}});
      window.contractToken = {id: 'a', name: 'Guo Yuan', x: 2, y: 2, z: 8, hp: 12, maxHp: 12, conditions: []};
      window.contractZones = [4, 15].map(x => ({zone_id: `grove-${x}`, name: 'Grove Domain', affected_cells: [[x, 4]],
        detail: Array(80).fill('Enemies spend extra movement in Living Claims.').join('\n')}));
      board.setTokens([window.contractToken]); board.setZones(window.contractZones);
    });
    for (const x of [4, 15]) {
      const start = await page.evaluate(x => {
        const rect = window.contractBoard.viewport.getBoundingClientRect(), view = window.contractBoard.view;
        return {x: rect.left + view.x + (x + .5) * 64 * view.zoom,
          y: rect.top + view.y + 4.5 * 64 * view.zoom};
      }, x);
      await page.mouse.move(start.x, start.y);
      const card = page.locator('.tt-hovercard');
      await card.waitFor({state: 'visible'});
      const box = await card.boundingBox();
      assert.ok(x === 4 ? box.x > start.x : box.x < start.x, 'exercise actual right and left placement');
      await card.evaluate(node => { window.originalCardContent = node.firstChild; });
      const end = {x: box.x + box.width / 2, y: Math.min(box.y + box.height - 20, Math.max(box.y + 20, start.y))};
      for (let i = 1; i <= 12; i++) {
        await page.mouse.move(start.x + (end.x - start.x) * i / 12, start.y + (end.y - start.y) * i / 12);
        await page.evaluate(() => {
          window.contractBoard.setTokens([window.contractToken]);
          window.contractBoard.setZones(window.contractZones); window.contractBoard.setFog(null);
        });
        assert.equal(await card.isVisible(), true);
        assert.equal(await card.evaluate(node => node.firstChild === window.originalCardContent), true);
      }
      const zoom = await page.evaluate(() => window.contractBoard.view.zoom);
      await page.mouse.wheel(0, 250);
      await page.waitForFunction(() => document.querySelector('.tt-hovercard').scrollTop > 0);
      assert.equal(await page.evaluate(() => window.contractBoard.view.zoom), zoom);
      assert.equal(await card.evaluate(node => getComputedStyle(node).pointerEvents), 'auto');
      await page.keyboard.press('Escape');
      assert.equal(await card.isVisible(), false);
    }
    const token = page.locator('.tt-token');
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => window.contractBoard.setTokens([window.contractToken]));
      assert.equal(await token.count(), 1);
      assert.equal(await token.locator('.tt-token-height').count(), 1);
      assert.equal(await token.locator('.tt-token-height').innerText(), '↑40 ft');
    }

    // Optional owner's scratch copy. Serve this branch's UI over its read-only
    // state API; no deployment, service restart, action or model request.
    if (process.env.UIREGRESS_TABLE_URL || process.env.UIREGRESS_ORIGIN) {
      await page.route('**/static/**', async route => {
        const path = new URL(route.request().url()).pathname;
        const file = resolve(appRoot, `.${path}`);
        if (!file.startsWith(appRoot + '/')) return route.abort();
        try { await route.fulfill({body: await readFile(file), contentType:
          ({'.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
            '.png': 'image/png', '.svg': 'image/svg+xml'})[extname(file)] || 'application/octet-stream'}); }
        catch { await route.continue(); }
      });
      await page.route('**/api/**', route => route.request().method() === 'GET'
        ? route.continue() : route.fulfill({status: 403, json: {message: 'UI contract check is read-only.'}}));
      const origin = process.env.UIREGRESS_ORIGIN || new URL(process.env.UIREGRESS_TABLE_URL).origin;
      await page.goto(process.env.UIREGRESS_TABLE_URL || `${origin}/tabletop`);
      await page.waitForFunction(() => Boolean(window.tabletop));
      if (!process.env.UIREGRESS_TABLE_URL) {
        const matchId = await page.evaluate(async supplied => {
          if (supplied) return supplied;
          const rows = await (await fetch('/api/combat/matches')).json();
          for (const row of rows.slice().reverse().slice(0, 20)) {
            const response = await fetch(`/api/tabletop/matches/${encodeURIComponent(row.match_id)}/state?fog=true`);
            if (!response.ok) continue;
            const state = await response.json();
            if (/frozen[- _]fishing/i.test(JSON.stringify(state.map))) return row.match_id;
          }
          return null;
        }, process.env.UIREGRESS_MATCH_ID || null);
        assert.ok(matchId, 'Frozen Fishing Lake was not among the newest 20 saves; set UIREGRESS_MATCH_ID explicitly');
        await page.evaluate(id => window.tabletop.loadMatch(id), matchId);
      }
      await page.evaluate(() => document.querySelector('#ttViewerGM').click());
      await page.waitForSelector('.tt-token:not(.is-hidden)');
      const visibleTokens = page.locator('.tt-token:not(.is-hidden)');
      const ids = await visibleTokens.evaluateAll(nodes => nodes.map(node => node.dataset.tokenId));
      assert.equal(new Set(ids).size, ids.length, 'each visible entity is rendered once');
      for (const node of await visibleTokens.all()) {
        assert.equal(await node.locator('.tt-token-height').count(), 1);
      }
      // Living Claims are distinct entities and may share their owner's square
      // and altitude. Only duplicate entities/badges are invalid; overlap is not.
      const point = process.env.UIREGRESS_ZONE_POINT?.split(',').map(Number) || await page.evaluate(() => {
        const {app, board} = window.tabletop;
        const zone = app.state.presentation.zones.find(row => /Grove Domain/i.test(JSON.stringify(row)));
        if (!zone) return null;
        const occupied = new Set(app.state.presentation.actors.filter(row => row.position)
          .map(row => `${row.position.x},${row.position.y}`));
        const cell = zone.affected_cells.find(row => !occupied.has(`${row[0] ?? row.x},${row[1] ?? row.y}`));
        if (!cell) return null;
        const x = cell[0] ?? cell.x, y = cell[1] ?? cell.y;
        board.centerOn(x, y);
        const rect = board.viewport.getBoundingClientRect(), view = board.view;
        return [rect.left + view.x + (x + .5) * 64 * view.zoom,
          rect.top + view.y + (y + .5) * 64 * view.zoom];
      });
      assert.ok(point, 'No unoccupied Grove Domain square; set UIREGRESS_ZONE_POINT=x,y explicitly');
      const [sx, sy] = point;
      assert.ok(Number.isFinite(sx) && Number.isFinite(sy));
      await page.mouse.move(sx, sy);
      const card = page.locator('.tt-hovercard');
      await card.waitFor({state: 'visible'});
      assert.match(await card.innerText(), /Grove Domain/);
      const box = await card.boundingBox();
      await card.evaluate(node => { window.originalCardContent = node.firstChild; });
      await page.mouse.move(box.x + box.width / 2, Math.max(box.y + 15, Math.min(sy, box.y + box.height - 15)), {steps: 20});
      await page.waitForTimeout(4500); // includes a normal snapshot poll
      assert.equal(await card.isVisible(), true);
      assert.equal(await card.evaluate(node => node.firstChild === window.originalCardContent), true);
      await page.mouse.wheel(0, 250);
      await page.waitForFunction(() => document.querySelector('.tt-hovercard').scrollTop > 0);
    }
  } finally {
    await browser?.close();
    if (server.listening) await new Promise(done => server.close(done));
  }
});
