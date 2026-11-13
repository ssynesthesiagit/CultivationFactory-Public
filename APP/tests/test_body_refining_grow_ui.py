"""DOM-free Grow label/search regression. No browser or model process."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_grow_searches_base_and_variant_and_keeps_legal_learn():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the DOM-free UI check")
    source = (Path(__file__).resolve().parents[1] / "static/tabletop/grow.js").read_text()
    source = source.replace("export async function", "async function").replace("export function", "function")
    menu = {
        "cl": 1, "realm": "Mortal", "paths": [], "talents": [], "forge": {},
        "spheres": [{"id": "tianxia.sphere.dark", "name": "Dark", "legal": True, "gm": False, "reasons": [],
                     "body_refining_variant": {"id": "tianxia.brvariant.dark.night-bound-body",
                       "label": "Dark — Body Refining: Night-Bound Body", "gate_note": "Default version."}},
                    {"id": "tianxia.sphere.beauty", "name": "Beauty", "legal": False, "gm": False,
                     "reasons": ["Not available"]}],
        "ability_panel": {"scores": dict.fromkeys(["STR", "DEX", "CON", "INT", "WIS", "CHA"], 12)},
        "added": {"spheres": [], "talents": [], "forged": [], "abilities": [], "insights": [], "immortal_arts": []},
        "insights": [], "immortal_art": {"sources": [], "aspects": [], "known": 0, "limit": 0},
    }
    script = """
const assert = require("node:assert/strict");
const ids = {};
const root = {addEventListener() {}, replaceChildren(...children) { this.children = children; }};
ids["grow-root"] = root;
function h(tag, attrs, ...children) {
  const row = {tag, ...(attrs || {}), children, addEventListener() {}, replaceChildren() {}};
  if (attrs?.id) ids[attrs.id] = row;
  return row;
}
const document = {activeElement: null};
const nodes = node => node && typeof node === "object" ? [node, ...(node.children || []).flatMap(nodes)] : [];
const words = node => typeof node === "string" ? node : (node?.children || []).map(words).join(" ");
""" + source + """
(async () => {
 initGrow({h, $: id => ids[id], projectId: () => "synthetic", toast() {}, reloadSheet: async () => {},
           fetchJson: async () => (MENU)});
 await loadGrow();
 assert(words(root).includes("Dark — Body Refining: Night-Bound Body"));
 const learn = nodes(root).find(n => n.dataset?.growAdd === "sphere" && n.dataset?.id === "tianxia.sphere.dark");
 assert(learn && !learn.disabled);
 query.sphere = "Night-Bound";
 render();
 assert(words(ids["grow-spheres"]).includes("Night-Bound Body"));
 assert(!words(ids["grow-spheres"]).includes("Beauty"));
 query.sphere = "Dark";
 render();
 assert(words(ids["grow-spheres"]).includes("Night-Bound Body"));
})().catch(error => {console.error(error); process.exitCode = 1;});
""".replace("MENU", json.dumps(menu))
    subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
