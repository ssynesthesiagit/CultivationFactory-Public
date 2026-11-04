// Lead-only visual check. Run MULTIPATH_BROWSER=1 node tests/sol197_browser.mjs
// --playwright-modules <node_modules dir>   (or set PLAYWRIGHT_MODULES)
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import assert from "node:assert/strict";

if (process.env.MULTIPATH_BROWSER !== "1") {
  console.log("SKIPPED: lead must set MULTIPATH_BROWSER=1 outside the sandbox");
  process.exit(0);
}
const flag = process.argv.indexOf("--playwright-modules");
const modules = flag >= 0 ? process.argv[flag + 1] : process.env.PLAYWRIGHT_MODULES || os.homedir() + "/Projects/hermes-agent/node_modules";
const require = createRequire(path.join(modules, "sol197-loader.cjs"));
const {chromium} = require("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../static");
const read = file => fs.readFileSync(path.join(root, file), "utf8");
const out = "/var/tmp/auto-audit/fix/SOL197-browser";
fs.mkdirSync(out, {recursive: true});
const summary = "Spirit Awakening (Soulstring Dancer) + Body Refining (Göruden)";
const row = {project_id: "sol197", name: "Two Paths", path: "Spirit Awakening", current_cl: 10,
  path_summary: summary, workflow: {}, lifecycle: {persistence_state: "completed"}};
const snapshot = JSON.parse(read("../tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json"));
const browser = await chromium.launch({executablePath: "/usr/bin/chromium", args: ["--no-sandbox"], headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1126, height: 900}});
  // Isolated static rendering: no live service or character writes, no API calls.
  await page.route("**/*", route => route.abort());
  await page.setContent(read("index.html").replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<link\b[^>]*>/gi, ""));
  await page.addStyleTag({content: read("themes.css") + read("styles.css")});
  await page.evaluate(() => {
    window.fetch = async () => { throw Error("SOL197 visual fixture: network disabled"); };
    window.setInterval = () => 0;
    window.setTimeout = () => 0;
  });
  for (const file of ["sphere_talent_logic.js", "sheet_view_model.js", "complete_request_save.js", "app.js"])
    await page.addScriptTag({content: read(file)});
  await page.evaluate(({row, summary, snapshot}) => {
    gmRenderCharacterLibraryRows([row, {...row, project_id: "single", name: "One Path", path_summary: null}]);
    renderOwnerSheet({project_id: row.project_id, name: row.name, identity: {name: row.name, current_cl: 10},
      path_summary: summary, owner_character_sheet: snapshot, sections: {}, readiness: {}, gm_export: {available: false}});
    // Make the actual Character Sheets panel visible without invoking app/API navigation.
    const list = document.getElementById("characterCardList");
    for (let p = list; p; p = p.parentElement) { p.hidden = false; p.style.display = "block"; }
    document.querySelectorAll("body > *").forEach(el => {
      if (!el.contains(list) && el.tagName !== "STYLE") el.style.display = "none";
    });
    list.style.width = "170px";
  }, {row, summary, snapshot});
  const detail = page.locator('.character-library-card[data-character-project-id="sol197"] .character-card-detail');
  assert.ok((await detail.innerText()).includes(summary));
  assert.ok(await detail.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  assert.ok(await detail.evaluate(el => el.getBoundingClientRect().height > parseFloat(getComputedStyle(el).lineHeight) * 1.5));
  await page.screenshot({path: path.join(out, "character-sheets-list.png"), fullPage: true});
  const header = page.locator(".gm-path-summary");
  assert.equal(await header.innerText(), summary);
  assert.ok(await header.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.locator("#ownerCharacterSheet").screenshot({path: path.join(out, "multipath-sheet-header.png")});
  // Also exercise the pop-out's actual header function and CSS, without its live channels.
  await page.setContent(read("tabletop/sheet.html").replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<link\b[^>]*>/gi, ""));
  await page.addStyleTag({content: read("themes.css") + read("tabletop/sheet.css")});
  const sheetSource = read("tabletop/sheet.js");
  const headerSource = sheetSource.slice(sheetSource.indexOf("function renderHeader()"), sheetSource.indexOf("// 2024 Carrying Capacity"));
  await page.addScriptTag({content: `const state = {sheet: {}, summary: ${JSON.stringify({name: "Two Paths", cultivation_level: 10, path_summary: summary})}};
    const $ = id => document.getElementById(id); const initials = () => 'TP'; const showToken = () => {};
    ${headerSource}\nrenderHeader();`});
  assert.equal(await page.locator("#char-sub").innerText(), `CL 10 · ${summary}`);
  assert.ok(await page.locator("#char-sub").evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path: path.join(out, "multipath-popout-header.png"), fullPage: true});
  console.log(`PASS: 1126px Character Sheets list, 170px cards and multi-Path header; screenshots ${out}`);
} finally {
  await browser.close();
}
