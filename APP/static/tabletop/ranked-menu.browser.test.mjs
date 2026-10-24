// Lead must run outside the sandbox: EMBEDMENU_BROWSER=1 node --test this-file.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
test('Assisted slot controls render and expand in Chromium', {skip: process.env.EMBEDMENU_BROWSER !== '1'}, async () => {
  const {chromium} = await import('playwright');
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
  try {
    const page = await browser.newPage();
    // Serve real sibling modules in-memory; relative flight UI imports need
    // an HTTP module base, and no live table/server is involved.
    await page.route('http://embedmenu.test/**', route => {
      const path = new URL(route.request().url()).pathname.slice(1);
      if (!path) return route.fulfill({contentType:'text/html',body:'<main></main>'});
      assert.match(path, /^[a-z0-9.-]+\.(js|json)$/);
      return route.fulfill({contentType:path.endsWith('.json') ? 'application/json' : 'text/javascript',
        body:readFileSync(new URL('./' + path, import.meta.url), 'utf8')});
    });
    await page.goto('http://embedmenu.test/');
    await page.evaluate(async () => {
      const {renderRankedMenu} = await import('/ranked-menu.js');
      const menu = {moves:[],ranked_slots:{Action:['a0','a1','a2','a3','a4']},actions:[
        {label:'Strike',economy:'ACTION',options:Array.from({length:8},(_,i)=>({candidate_id:`a${i}`,label:`foe ${i}`}))}]};
      document.querySelector('main').appendChild(renderRankedMenu(menu,{onAct:id=>window.chosen=id,onMove:()=>{}}));
    });
    assert.equal(await page.locator('.tt-btn').count(), 5);
    await page.getByRole('button', {name:'More… (+3)'}).click();
    assert.equal(await page.locator('.tt-btn').count(), 8);
    await page.locator('.tt-btn').last().click();
    assert.equal(await page.evaluate(()=>window.chosen), 'a7');
    // ACTIONAUDIT1: no-action uses are reachable under their own heading.
    await page.evaluate(async () => {
      const {renderRankedMenu} = await import('/ranked-menu.js');
      document.querySelector('main').replaceChildren(renderRankedMenu({ranked_slots:{'No action':['n0']},actions:[
        {label:'Verdant Response: Shelter',economy:'NONE',options:Array.from({length:8},(_,i)=>({candidate_id:`n${i}`}))}]},
        {onAct:id=>window.chosen=id,onMove:()=>{}}));
    });
    const section = page.locator('.tt-ab-group').filter({has:page.getByRole('heading',{name:'No action',exact:true})});
    assert.equal(await section.locator('.tt-btn').count(), 1);
    await section.getByRole('button',{name:'More… (+7)'}).click();
    await section.locator('.tt-btn').last().click();
    assert.equal(await page.evaluate(()=>window.chosen), 'n7');
  } finally { await browser.close(); }
});
