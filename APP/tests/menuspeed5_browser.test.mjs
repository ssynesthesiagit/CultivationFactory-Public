// Lead-only: MENUSPEED5_BROWSER_URL must name the scratch table fight URL.
import test from 'node:test';
import assert from 'node:assert/strict';

test('scratch table consumes compact route grids', {skip: !process.env.MENUSPEED5_BROWSER_URL}, async () => {
  const {chromium} = await import('playwright');
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const response = page.waitForResponse(r => r.url().includes('/state?') && r.status() === 200);
    await page.goto(process.env.MENUSPEED5_BROWSER_URL);
    const state = await (await response).json();
    assert.ok(state.menu?.movement_grid?.layers?.length > 0);
    assert.equal(state.menu.moves.length, 0);
    await page.waitForFunction(() => !document.body.textContent.includes('Loading choices'));
    assert.ok(!(await page.locator('body').innerText()).includes('Costs undefined'));
  } finally {
    await browser.close();
  }
});
