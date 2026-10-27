"""Drive the editor's actual operations without opening a browser."""
from pathlib import Path
import json
import subprocess
from combat.tabletop import TabletopMapStore

ROOT = Path(__file__).resolve().parents[1]


def test_mixed_bamboo_count_remove_save_reopen(tmp_path):
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('static/tabletop/mapeditor.js','utf8');
const extract=name=>{const start=source.indexOf('function '+name+'(');return source.slice(start,source.indexOf('\n}',start)+2);};
const doc={width_squares:8,height_squares:8,walls:[],starts:{team1:[],team2:[]},trees:[],materials:[
 {material:'terrain:bamboo thicket',occluder:'cell',cells:[[1,1],[2,1]]},
 {material:'terrain:bamboo thicket',occluder:'centerline',cells:[[5,5],[6,5]]}]};
const stats={innerHTML:''},list={replaceChildren(){}},tree={value:'clear'};
const ctx={editor:{doc,cells:{blocked:[],sight:[]}},BAMBOO:'terrain:bamboo thicket',
 $:s=>s==='#meStats'?stats:s==='#meWallList'?list:tree,treeAt:()=>-1,render:()=>{},paintMaterial:()=>{throw Error('unexpected paint');}};
vm.createContext(ctx);vm.runInContext(extract('renderStats')+'\n'+extract('paintBamboo'),ctx);
ctx.renderStats();assert.match(stats.innerHTML,/Bamboo squares<\/dt><dd>4/);
for(const cell of [[5,5],[1,1]]) {
 ctx.paintBamboo(cell);
 ctx.editor.doc=JSON.parse(JSON.stringify(ctx.editor.doc)); // saved and reopened editor document
 assert.ok(!ctx.editor.doc.materials.some(row=>row.cells.some(c=>c[0]===cell[0]&&c[1]===cell[1])));
}
ctx.renderStats();assert.match(stats.innerHTML,/Bamboo squares<\/dt><dd>2/);
assert.deepEqual(JSON.parse(JSON.stringify(ctx.editor.doc.materials)).map(row=>row.occluder),['cell','centerline']);
console.log(JSON.stringify(ctx.editor.doc));
'''
    document = json.loads(subprocess.check_output(["node", "-e", script], cwd=ROOT, text=True))
    document.update(map_id="mixed-bamboo", display_name="Mixed bamboo")
    store = TabletopMapStore(tmp_path)
    saved = store.save(document)
    assert store.get("mixed-bamboo")["materials"] == saved["materials"] == [
        {"material": "terrain:bamboo thicket", "occluder": "cell", "cells": [[2, 1]]},
        {"material": "terrain:bamboo thicket", "occluder": "centerline", "cells": [[6, 5]]},
    ]
