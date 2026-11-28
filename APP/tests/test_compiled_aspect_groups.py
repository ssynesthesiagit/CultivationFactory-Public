"""The compiled review joins old saved Talent owners to current Aspect rows."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.api import _bounded_owner_scratch_sheet
from canonical_catalog.service import CanonicalCatalogAuthorityService


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node (no browser)")
def test_saved_talent_and_component_share_the_acquired_aspect_group(monkeypatch):
    armaments_id = "tianxia.sphere.equipment"
    fire_id = "tianxia.sphere.fire"
    # Isolate the catalog's labels from the bundled Factory archive.
    monkeypatch.setattr(CanonicalCatalogAuthorityService, "_load", lambda _: {
        "sphere_by_id": {fire_id: {"display_name": "Way of Fire"}},
    })
    compiled = {
        "owner_character_sheet": {
            "selected_record_sections": {
                "Spheres": [
                    {"record_id": "tianxia.background_sphere.equipment", "display_name": "Way of Armaments"},
                ],
                "Talents": [
                    # Abandoned Orphan's real grant; older scratch artifacts
                    # have no parent label on this Background Talent.
                    {"record_id": "tianxia.background_talent.equipment.hidden_plates", "display_name": "Hidden Plates"},
                    {"record_id": "talent.spark", "display_name": "Bright Spark"},
                ],
            },
            "spheres_and_talents": {
                "automatic_sphere_components": [
                    {"parent_sphere_id": armaments_id, "parent_sphere_name": "Equipment", "display_name": "Ready Shield"},
                ],
            },
        },
        # A saved scratch artifact predating canonical_sphere_id projection.
        "talent_sphere_names": {"talent.spark": "Sphere of Fire"},
    }
    original = deepcopy(compiled)
    sheet = _bounded_owner_scratch_sheet(compiled)
    assert compiled == original
    assert sheet["talents"][0]["canonical_sphere_id"] == armaments_id
    assert sheet["automatic_components"][0]["canonical_sphere_id"] == armaments_id
    assert sheet["talents"][1]["canonical_sphere_id"] == fire_id

    app = Path(__file__).resolve().parents[1] / "static/app.js"
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const {source, sheet} = JSON.parse(fs.readFileSync(0, "utf8"));
class Element {
  constructor() { this.children = []; this.textContent = ""; }
  appendChild(node) { this.children.push(node); return node; }
  append(...nodes) { this.children.push(...nodes); }
  get childElementCount() { return this.children.length; }
}
const nodes = {};
const context = vm.createContext({
  document: {createElement: () => new Element(), getElementById: id => nodes[id] ||= new Element()},
  ownerViewFor: run => run.owner_view,
  planningIsEditable: () => true,
  clearNode: node => { node.children = []; },
});
for (const name of ["ownerText", "appendCompiledRecord", "appendCompiledEmpty", "renderCompiledOwnerStages"]) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf("\nfunction ", start + 1);
  vm.runInContext(source.slice(start, end), context);
}
context.renderCompiledOwnerStages({owner_view: {scratch_candidate: {sheet}}});
console.log(JSON.stringify(nodes.ownerCompiledSpheresBody.children.map(({children: [summary, grid]}) => ({
  name: summary.children[0].textContent,
  records: grid.children.map(card => card.children[0].textContent),
}))));
"""
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"source": app.read_text(encoding="utf-8"), "sheet": sheet}),
        text=True, capture_output=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout) == [
        {"name": "Way of Armaments", "records": ["Way of Armaments", "Ready Shield", "Hidden Plates"]},
        {"name": "Way of Fire", "records": ["Bright Spark"]},
    ]
