"""Grow wizard UI: no browser is launched unless the lead opts in."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def source():
    return (ROOT / "static/tabletop/grow.js").read_text().replace("export ", "")


def test_single_panel_preserves_all_talent_options_and_draft_choices():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for this DOM-free UI check")
    script = source() + r"""
const assert = require("node:assert/strict");
deps = {h: (tag, props, ...children) => ({tag, props, children}), $: () => null};
data = {cl: 1, level_up: {cl: 2, available: true, history: [], talent_count: 1, subpaths: [],
  statistics: {pb: 2, hp: {maximum: 17}},
  talents: Array.from({length: 210}, (_, i) => ({id: "talent."+i, name: "Talent "+i, legal: true}))}};
levelDraft = {rows: {2: {cl:2, talent_ids:["talent.209"], subpaths:{}, feature_choices:{}, changes:{}}}, filters:{}, addPath:{path_id:"",access:"",source_id:"",confirmed:false}};
const tree = JSON.stringify(levelBlock());
for (let i = 0; i < 210; i++) assert.ok(tree.includes('"value":"talent.'+i+'"'), "missing "+i);
assert.ok(tree.includes('"checked":true'));
const review = JSON.stringify(levelBlock());
assert.ok(review.includes("cultivation level") || review.includes("Cultivation level"));
assert.ok(review.includes("17"));
assert.deepEqual(levelDraft.rows[2].talent_ids, ["talent.209"]);
assert.ok(JSON.stringify(levelBlock()).includes("Level up to CL"));
let calls=0;
deps.fetchJson=() => {calls++;throw Error("Selections must be local");};
onChange({target:{type:"radio",value:"talent.5",dataset:{levelPick:"talent",levelCl:"2"}}});
assert.deepEqual(levelDraft.rows[2].talent_ids,["talent.5"]);
assert.equal(calls,0);
const opts=abilityAllocations({key_ability:"INT",ability_rule:{budget:2,allowed_deltas:[1,2],cap:20}},
  {STR:12,DEX:14,CON:16,INT:16,WIS:12,CHA:8});
assert.deepEqual(opts[0].changes,{INT:2});
assert.ok(opts.some((r) => r.changes.CON === 1 && r.changes.WIS === 1));
assert.ok(!JSON.stringify(levelBlock()).includes("Next"));
const gained={id:"later",name:"Later talent",constraints:[{kind:"talent",target_id:"manual"}],legal:false};
assert.ok(talentLegal(gained,new Set(["manual"]),3));
data.level_up={cl:2,available:true,known:{talents:[],spheres:[],paths:[]},planning:[
  {cl:2,talent_count:1,talents:[{id:"first",name:"First",legal:true}],statistics:{}},
  {cl:3,talent_count:1,known:{talents:["manual"]},talents:[gained],statistics:{}}
]};
levelDraft={target:3,rows:{},filters:{},addPath:{path_id:"",access:"",source_id:"",confirmed:false}};
const plan=levelPlan();
assert.deepEqual(plan.map((r) => r.d.talent_ids),[["first"],["later"]]);
assert.equal(plan.length,2);
const projected=levelStatistics({cl:4,scores:{CON:16,INT:16},statistics:{hp:{maximum:30},pb:2,resource:{maximum:12}},
  resource_formulas:[{op:"multiply",terms:[{op:"cl"},{op:"ability_modifier",ability:"INT"}]}]}, {CON:18,INT:18},new Set());
assert.equal(projected.hp.maximum,34);
assert.equal(projected.resource.maximum,16);
assert.ok(render.toString().includes("patchGrowNode"));
assert.ok(onClick.toString().includes("render(true)"));
"""
    subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("GROW3_BROWSER") != "1", reason="Lead must run Chromium outside the sandbox")
def test_chromium_level_wizard_and_jade_source():
    from playwright.sync_api import sync_playwright
    view = {"cl": 1, "realm": "Mortal", "paths": [], "added": {"spheres": [], "talents": [], "forged": []},
            "sources": ["campaign", "manual", "jade tablet"], "ability_panel": {}, "forge": {},
            "level_up": {"cl": 2, "available": True, "history": [], "talent_count": 1,
                "subpaths": [], "features": [{"name": "Meridian Regulation", "text": "Recover Qi during a short rest."}],
                "statistics": {"pb": 2, "hp": {"maximum": 17}},
                "talents": [{"id": "practice", "name": "Water practice", "legal": True}]}}
    harness = r"""
window.posts = [];
function h(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === false) continue;
    if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "class") node.className = value;
    else if (key === "style") node.style.cssText = value;
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
initGrow({h, $: id => document.getElementById(id), projectId: () => "synthetic",
  toast() {}, reloadSheet: async () => {},
  fetchJson: async (url, options) => {
    if (url === "/api/session") return {token: "fake"};
    if (options) {
      window.posts.push(JSON.parse(options.body));
      window.view.cl = 2;
      window.view.added.talents = [{id:"practice", name:"Water practice", cl:2, source:"level"}];
      window.view.level_up = {...window.view.level_up, cl:3};
    }
    return window.view;
  }});
await loadGrow();
"""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.set_content('<div id="grow-root"></div>')
            page.evaluate("window.view = " + json.dumps(view))
            page.evaluate("(async () => {" + source() + harness + "})()")
            page.locator("#grow-source").select_option("jade tablet")
            assert page.get_by_text("Meridian Regulation — gained", exact=True).is_visible()
            page.get_by_label("Water practice", exact=False).check()
            assert page.evaluate("window.posts.length") == 0
            page.evaluate("window.savedInput = document.querySelector('[data-level-pick=talent]')")
            page.locator("#level-2-talent-q").fill("Water")
            assert page.evaluate("window.savedInput === document.querySelector('[data-level-pick=talent]')")
            page.get_by_role("button", name="Level up", exact=True).click()
            page.wait_for_function("window.posts.length === 1")
            assert page.evaluate("window.posts[0].levels[0].talent_ids") == ["practice"]
            assert page.evaluate("window.posts[0].cl") == 2
            assert page.get_by_text("CL 2 · Mortal", exact=False).is_visible()
            assert page.get_by_text("Added at the table (1)", exact=True).is_visible()
            assert not errors
        finally:
            browser.close()
