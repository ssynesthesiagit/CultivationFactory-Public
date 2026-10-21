"""Opt-in Grow-tab choice check. Lead runs outside the sandbox with Chromium."""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CF_RUN_BROWSER_TESTS") != "1",
                                reason="Lead must run browser checks outside the sandbox: CF_RUN_BROWSER_TESTS=1")


def test_grow_keeps_all_training_choices_and_submits_owner_selection():
    from playwright.sync_api import sync_playwright
    source = (Path(__file__).resolve().parents[1] / "static/tabletop/grow.js").read_text().replace("export ", "")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.set_content('<div id="grow-root"></div>')
            page.add_script_tag(content=source)
            page.evaluate('''async () => {
              window.sent = [];
              const choices = [{id:"skill", label:"Jester Training: choose a skill proficiency",
                options:[{id:"Performance",name:"Performance"},{id:"Deception",name:"Deception"},{id:"Acrobatics",name:"Acrobatics"}]},
                {id:"punchline",label:"Jester Training: choose a Mortal Realm Punchline talent (free)",
                  options:Array.from({length:205},(_,i)=>({id:"punchline:"+i,name:"Punchline "+i}))}];
              const result = {cl:1,realm:"Mortal",paths:[],talents:[],forge:{available:false,minimum_cl:5},
                added:{spheres:[],talents:[],forged:[]},spheres:[{id:"tianxia.sphere.jester",name:"Jester",legal:true,learning_choices:choices}]};
              const h = (tag, attrs, ...children) => {
                const e = document.createElement(tag);
                for(const [k,v] of Object.entries(attrs || {})) {
                  if(v == null || v === false) continue;
                  if(k === "dataset") Object.assign(e.dataset,v);
                  else if(k === "class") e.className=v;
                  else if(k in e) e[k]=v;
                  else e.setAttribute(k,v);
                }
                for(const c of children.flat(Infinity)) if(c != null) e.append(c instanceof Node ? c : String(c));
                return e;
              };
              initGrow({h,$:id=>document.getElementById(id),projectId:()=>"native-fixture",toast:()=>{},reloadSheet:async()=>{},
                fetchJson:async(url,options)=>{
                  if(url === "/api/session") return {token:"test"};
                  if(options) {
                    const body=JSON.parse(options.body); window.sent.push({url,body});
                    if(url.endsWith("learning-preview")) return {learning_choices:choices};
                  }
                  return result;
                }});
              await loadGrow();
            }''')
            select = page.locator('[data-learning-choice="punchline"]')
            assert select.locator("option").count() == 206
            page.locator('[data-learning-choice="skill"]').select_option("Performance")
            page.wait_for_function("window.sent.length >= 1")
            select.select_option("punchline:204")
            page.wait_for_function("window.sent.length >= 2")
            page.locator('[data-grow-add="sphere"]').click()
            page.wait_for_function("window.sent.some(r=>r.url.endsWith('/advancement'))")
            body = page.evaluate("window.sent.find(r=>r.url.endsWith('/advancement')).body")
            assert body["learning_choices"] == {"skill": "Performance", "punchline": "punchline:204"}
        finally:
            browser.close()
