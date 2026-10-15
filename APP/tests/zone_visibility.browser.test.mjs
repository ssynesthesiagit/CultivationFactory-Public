// Opt-in: the lead must run outside the sandbox; never launch browsers here.
// RUN_TABLETOP_BROWSER_TESTS=1 node --test tests/zone_visibility.browser.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

test('visible clouds above overlapping darkness and fog, real browser',
  {skip: process.env.RUN_TABLETOP_BROWSER_TESTS !== '1'}, async () => {
    const {chromium} = await import('playwright');
    const root = resolve(fileURLToPath(new URL('../', import.meta.url)));
    const server = createServer(async (req, res) => {
      const path = new URL(req.url, 'http://localhost').pathname;
      if (path === '/') {
        res.setHeader('content-type', 'text/html');
        res.end(`<link rel="stylesheet" href="/static/themes.css">
          <link rel="stylesheet" href="/static/tabletop/tabletop.css">
          <link rel="stylesheet" href="/static/tabletop/hovercard.css">
          <style>#v {position:relative;width:800px;height:700px;overflow:hidden}</style><body class="tt-app"><div id="v"></div>
          <script type="module">
            import {createBoard,CELL} from '/static/tabletop/board.js';
            import {map,zones} from '/tests/zone_visibility_fixture.mjs';
            const board=createBoard(document.querySelector('#v')); board.setMap(map);
            board.setZones(zones,{round:4}); board.fit();
            window.sol144={board,CELL,zones};
          </script>`); return;
      }
      const file = resolve(root, '.' + path);
      if (!file.startsWith(root + sep)) {res.writeHead(404);res.end();return;}
      try {
        res.setHeader('content-type', file.endsWith('.css') ? 'text/css' : 'text/javascript');
        res.end(await readFile(file));
      } catch {res.writeHead(404);res.end();}
    });
    let browser;
    await new Promise(done => server.listen(0, '127.0.0.1', done));
    try {
      browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
      const page = await browser.newPage({viewport: {width: 1000, height: 800}});
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.waitForFunction(() => window.sol144);
      await page.addStyleTag({content: '* {animation-play-state: paused !important;}'});
      for (const fogOn of [false, true]) {
        await page.evaluate(fogOn => {
          const {board} = window.sol144;
          const seen = new Uint8Array(64); seen[27] = 1;
          board.setFog(fogOn ? seen : null, null, {squareFog: true});
        }, fogOn);
        await page.waitForTimeout(600); // finish zone enter transition
        const ordering = await page.evaluate(() => {
          const air = document.querySelector('.tt-zones-clouds'), fog = document.querySelector('.tt-fog');
          return {aboveFog: Boolean(fog.compareDocumentPosition(air) & Node.DOCUMENT_POSITION_FOLLOWING),
            clipped: getComputedStyle(air).maskImage !== 'none',
            dark: getComputedStyle(document.querySelector('.tt-zones-air .is-dark')).zIndex,
            clouds: [...air.querySelectorAll('.is-light,.is-heavy')].map(n => ({z: getComputedStyle(n).zIndex,
              mask: getComputedStyle(n).maskImage, opacity: getComputedStyle(n).opacity}))};
        });
        assert.ok(ordering.aboveFog); assert.equal(ordering.clipped, fogOn);
        assert.equal(ordering.dark, '0'); assert.equal(ordering.clouds.length, 3);
        for (const cloud of ordering.clouds) {assert.equal(cloud.z, '1'); assert.notEqual(cloud.mask, 'none'); assert.ok(Number(cloud.opacity) > 0);}
        // Compare rendered pixels with/without the cloud layer. Checking maskImage
        // alone misses intrinsic quarter-scale masks and their repeated leaks.
        // Freeze material animations so unseen pixels must be exactly unchanged.
        const painted = (await page.screenshot()).toString('base64');
        await page.locator('.tt-zones-clouds').evaluate(n => {n.style.visibility = 'hidden';});
        const bare = (await page.screenshot()).toString('base64');
        await page.locator('.tt-zones-clouds').evaluate(n => {n.style.visibility = '';});
        const differences = await page.evaluate(async ({painted, bare}) => {
          const pixels = async data => {
            const blob = await (await fetch('data:image/png;base64,' + data)).blob();
            const image = await createImageBitmap(blob), canvas = document.createElement('canvas');
            canvas.width = image.width; canvas.height = image.height;
            const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
            return {width: image.width, data: ctx.getImageData(0, 0, image.width, image.height).data};
          };
          const a = await pixels(painted), b = await pixels(bare);
          const {board, CELL} = window.sol144, rect = board.viewport.getBoundingClientRect(), v = board.view;
          return [[3, 3], [4, 3], [3, 4]].map(([x, y]) => {
            const cx = Math.round(rect.left + v.x + (x + .5) * CELL * v.zoom);
            const cy = Math.round(rect.top + v.y + (y + .5) * CELL * v.zoom);
            let changed = 0;
            for (let py = cy - 4; py <= cy + 4; py++) for (let px = cx - 4; px <= cx + 4; px++) {
              const i = (py * a.width + px) * 4;
              if ([0, 1, 2].some(c => Math.abs(a.data[i + c] - b.data[i + c]) > 2)) changed++;
            }
            return changed;
          });
        }, {painted, bare});
        assert.ok(differences[0] > 5, `off-origin visible cell must show cloud pixels: ${differences}`);
        for (const changed of differences.slice(1)) {
          if (fogOn) assert.equal(changed, 0, 'unseen cells must show no cloud pixels');
          else assert.ok(changed > 5, 'control: these cells contain rendered clouds without fog');
        }
        const point = await page.evaluate(() => {
          const {board, CELL} = window.sol144, rect = board.viewport.getBoundingClientRect(), v = board.view;
          return {x: rect.left + v.x + 3.5 * CELL * v.zoom, y: rect.top + v.y + 3.5 * CELL * v.zoom};
        });
        await page.mouse.move(point.x, point.y);
        await page.locator('.tt-hovercard:not([hidden])').waitFor();
        const text = await page.locator('.tt-hovercard').innerText();
        assert.match(text, /Dust Cloud/); assert.match(text, /Smoke Veil/); assert.match(text, /Darkness/);
        assert.match(text, /17% miss chance/); assert.match(text, /43% miss chance/);
        assert.match(text, /can't see have Disadvantage/);
        assert.match(text, /Cloud caster/); assert.match(text, /7 rounds left/); assert.match(text, /Concentration/);
        assert.doesNotMatch(text, /Ended cloud/);
        // Screenshots are evidence for the lead's visual review, not pixel assertions.
        if (process.env.SOL144_SCREENSHOT_DIR) {
          await mkdir(process.env.SOL144_SCREENSHOT_DIR, {recursive: true});
          await page.screenshot({path: resolve(process.env.SOL144_SCREENSHOT_DIR, `zones-${fogOn ? 'fog' : 'open'}.png`)});
        }
        await page.mouse.move(950, 750);
      }
      assert.deepEqual(errors, []);
    } finally {
      await browser?.close(); await new Promise(done => server.close(done));
    }
  });
