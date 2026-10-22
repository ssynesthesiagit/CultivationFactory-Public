"""DOM-free Method Grow controls: no browser or model server."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_method_options_reasons_sources_preview_history_and_no_truncation():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for DOM-free UI check")
    source = (Path(__file__).resolve().parents[1] / "static/tabletop/grow.js").read_text().replace("export ", "")
    script = source + r"""
const assert=require("node:assert/strict");
let gmOn=false;
deps={h:(tag,props,...children)=>({tag,props,children}),$:(id)=>id === "grow-gm" ? {checked:gmOn} : null};
const options=Array.from({length:102},(_,i)=>({id:"method"+i,name:"Method "+i,legal:i!==101,
  reasons:i===101 ? ["This Method conflicts with your Quiet Heart Foundation."] : []}));
data={method_change:{primary:{id:"method0",name:"Old Method"},known:[],options,sources:["teacher","scripture","gm"],
 opportunities:["downtime training"],history:[],free_replacement:true}};
methodDraft={method_id:"method101",source:"teacher",note:"Willow",opportunity:"downtime training",completed:true};
const nodes=()=>{const out=[];function walk(n){if(n && typeof n==="object"){out.push(n);(n.children||[]).flat(Infinity).forEach(walk);}}walk(methodBlock());return out;};
assert.equal(nodes().filter(n=>n.tag==="option" && n.props.value?.startsWith("method")).length,102);
let tree=JSON.stringify(methodBlock());
for(const text of ["Change Primary Method","Attainment Points (AP)","proficiency bonus","Quiet Heart","not a risky change","short rest","GM grant","Preview Method change"]) assert.ok(tree.includes(text),text);
assert.equal(nodes().find(n=>n.props?.dataset?.methodAction === "preview").props.disabled,true);
gmOn=true;
assert.equal(nodes().find(n=>n.props?.dataset?.methodAction === "preview").props.disabled,null);
methodPreview={method:{display_name:"New Method"},change:{gm:true},statistics:{primary_resource:{definitions:[{name:"Qi",current:3,max:7}]}}};
tree=JSON.stringify(methodBlock());
assert.ok(tree.includes("3 current / 7 maximum; no refill."));
assert.ok(tree.includes("Record Primary Method change"));
data.method_change.history=[{name:"New Method",source:"teacher",note:"Willow",gm:true}];
data.method_change.known=[{display_name:"Old Method",state:"inactive"}];
tree=JSON.stringify(methodBlock());
assert.ok(tree.includes("Old Method (inactive)"));
assert.ok(tree.includes("Undo last Method change"));
assert.ok(tree.includes("teacher: Willow"));
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
