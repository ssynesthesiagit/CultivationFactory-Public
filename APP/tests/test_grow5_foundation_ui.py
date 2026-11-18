"""Grow Foundation draft checks without launching a browser or a model."""
import shutil
import subprocess

import pytest

from pathlib import Path


def source():
    return (Path(__file__).resolve().parents[1] / "static/tabletop/grow.js").read_text().replace("export ", "")


def test_foundation_options_stages_deferral_history_and_local_preview():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the DOM-free Grow check")
    script = source() + r"""
const assert=require("node:assert/strict");
deps={h:(tag,props,...children)=>({tag,props,children}),$:()=>null};
const root={op:"pb"};
const foundations={options:[
  {id:"anchor",name:"Empty Bowl Soul Anchor",summary:"Hold spiritual pressure.",legal:true,stage_options:["Awakened","Unstable"],
    preview_by_stage:{Awakened:{hp:[],resource:[root]},Unstable:{hp:[],resource:[]}}},
  {id:"body",name:"Sacred Body",legal:true,stage_options:["Awakened"],preview_by_stage:{Awakened:{hp:[root],resource:[]}}},
  {id:"blocked",name:"Blocked Foundation",legal:false,reasons:["This Foundation does not support your active Paths: Qi Cultivation."],stage_options:["Awakened"]}
]};
const menus=[4,5,6].map(cl=>({cl,foundation:cl>=5 ? foundations : null,talent_count:0,
  statistics:{hp:{maximum:30+cl},resource:{maximum:12+cl},pb:3},scores:{CON:16,INT:16}}));
data={level_up:{cl:4,available:true,planning:menus,history:[]}};
levelDraft={target:6,rows:{},filters:{},addPath:{}};
let plan=levelPlan();
assert.deepEqual(plan.map(p=>p.foundationOffered),[false,true,true]);
let tree=JSON.stringify(levelBlock());
assert.ok(tree.includes("Not yet"));
assert.ok(tree.includes("Blocked Foundation")); // No legal-only filter hides disabled Foundations.
assert.ok(tree.includes("Qi Cultivation"));
const optionTree=foundationBlock(menus[1],{});
const nodes=[];
function walk(n) {if(n && typeof n==="object"){nodes.push(n);(n.children||[]).flat(Infinity).forEach(walk);}}
walk(optionTree);
assert.equal(nodes.find(n=>n.tag==="input" && n.props.value==="blocked").props.disabled,true);
onChange({target:{value:"anchor",dataset:{levelPick:"foundation",levelCl:"5"}}});
plan=levelPlan();
assert.equal(levelDraft.rows[5].foundation_initial_stage,undefined); // No default for a multi-stage record.
assert.equal(plan[2].foundationOffered,false);
tree=JSON.stringify(levelBlock());
assert.ok(tree.includes("Choose Empty Bowl Soul Anchor's initial stage"));
onChange({target:{value:"Awakened",dataset:{levelPick:"foundationStage",levelCl:"5"}}});
plan=levelPlan();
assert.equal(plan[1].statistics.resource.maximum,20);
assert.equal(plan[2].statistics.resource.maximum,21);
onChange({target:{value:"body",dataset:{levelPick:"foundation",levelCl:"5"}}});
levelPlan(); // The fake DOM has no mounted panel; the real renderer calls this during patching.
assert.equal(levelDraft.rows[5].foundation_initial_stage,"Awakened"); // Unique stage only.
assert.equal(levelPlan()[1].statistics.hp.maximum,38);
onChange({target:{value:"",dataset:{levelPick:"foundation",levelCl:"5"}}});
assert.equal(levelPlan()[2].foundationOffered,true);
data.level_up.history=[{cl:5,foundation:{name:"Sacred Body",stage:"Awakened"}}];
assert.ok(JSON.stringify(levelBlock()).includes("Foundation: Sacred Body — Awakened"));
// A pending multi-Path addition supplies compatibility for later draft levels too.
data.level_up.add_templates={extra:{subpaths:[],feature_choices:[],features:[],foundation_options:{options:[]}}};
levelDraft.addPath={path_id:"extra"};
assert.equal(levelPlan()[1].menu.foundation.options.length,0);
"""
    subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
