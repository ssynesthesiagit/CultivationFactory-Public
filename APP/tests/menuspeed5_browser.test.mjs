// Lead-only: URL must name a scratch table with a bound manual fighter on turn.
// This check commits a real move. Never point it at a live owner fight.
import test from 'node:test';
import assert from 'node:assert/strict';
import {expandTableTexts} from '../static/tabletop/table-text-pool.js';

test('scratch table renders a destination, previews its route and commits movement', {skip: !process.env.MENUSPEED5_BROWSER_URL}, async () => {
  const {chromium} = await import('playwright');
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 720}});
    const response = page.waitForResponse(r => r.url().includes('/state?') && r.status() === 200);
    await page.goto(process.env.MENUSPEED5_BROWSER_URL);
    const state = expandTableTexts(await (await response).json());
    assert.ok(state.menu?.movement_grid?.layers?.length > 0);
    assert.equal(state.menu.moves.length, 0);
    await page.waitForFunction(() => {
      const bar = document.getElementById('ttActionBar');
      return bar && !bar.textContent.includes('Loading your choices…')
        && [...bar.querySelectorAll('button')].some(b => !b.disabled && b.textContent.includes('Show moves'));
    });
    const showMoves = page.getByRole('button', {name: /Show moves/});
    assert.equal(await showMoves.count(), 1, 'A usable movement control must render');
    await showMoves.click();
    await page.locator('.tt-mark-move').first().waitFor({state: 'visible'});
    const menu = state.menu;
    const actor = state.presentation.actors.find(a => a.entity_id === menu.actor_id);
    assert.ok(actor, 'The active fighter must be present');
    const token = page.locator('.tt-token').filter({has: page.locator('.tt-token-name', {hasText: actor.display_name})}).first();
    const before = await token.boundingBox();
    assert.ok(before, 'The active fighter must render');
    let destination, square;
    for (const layer of menu.movement_grid.layers) {
      const [z, , mode] = layer;
      const cells = layer.at(-1);
      const hazardous = menu.movement_grid.format === 'layers-v2' && layer[4];
      if (z !== 0 || mode !== 'walk' || hazardous) continue;
      for (let i = 0; i < cells.length; i += 2) {
        const x = cells[i], y = cells[i + 1];
        const marker = page.locator(`.tt-mark-move[x="${x + .06}"][y="${y + .06}"]`).first();
        const box = await marker.boundingBox();
        if (!box || box.x < 0 || box.y < 0 || box.x + box.width > 1280 || box.y + box.height > 720) continue;
        destination = {x, y, z}; square = box; break;
      }
      if (square) break;
    }
    assert.ok(square, 'At least one safe walking destination must be rendered and reachable');
    const preview = page.waitForResponse(r => r.url().endsWith('/movement-destination/preview') && r.request().method() === 'POST');
    const commit = page.waitForResponse(r => r.url().endsWith('/movement-path/commit') && r.request().method() === 'POST');
    await page.mouse.click(square.x + square.width / 2, square.y + square.height / 2);
    const quoted = await preview;
    assert.equal(quoted.status(), 200, await quoted.text());
    assert.deepEqual(quoted.request().postDataJSON().destination, destination);
    const candidate = (await quoted.json()).candidate;
    assert.ok(candidate.canonical_path.length >= 2);
    const committed = await commit;
    assert.equal(committed.status(), 200, await committed.text());
    assert.equal(committed.request().postDataJSON().candidate_id, candidate.candidate_id);
    assert.deepEqual(committed.request().postDataJSON().waypoints, candidate.canonical_path);
    const result = await committed.json();
    assert.equal(result.status, 'COMMITTED');
    const position = result.state.presentation.actors.find(a => a.entity_id === menu.actor_id).position;
    assert.deepEqual({...position, z: position.z ?? 0}, destination);
    // Wait for the committed animation as well as the authoritative response.
    await page.waitForFunction(({name, before}) => [...document.querySelectorAll('.tt-token')].some(node => {
      if (node.querySelector('.tt-token-name')?.textContent !== name) return false;
      const box = node.getBoundingClientRect();
      return Math.abs(box.x - before.x) > 2 || Math.abs(box.y - before.y) > 2;
    }), {name: actor.display_name, before});
    assert.ok(!(await page.locator('body').innerText()).includes('Costs undefined'));
  } finally {
    await browser.close();
  }
});
