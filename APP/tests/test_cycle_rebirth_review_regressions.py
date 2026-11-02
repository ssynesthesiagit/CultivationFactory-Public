"""Public regressions for Cycle accounting and acquisition UI review findings.

All fixtures are synthetic; these tests do not read repository history or private
content packs.
"""
from types import SimpleNamespace
import json
from pathlib import Path
import shutil
import subprocess

from combat import ext
from combat.ext import mgr_t14_cycle_rebirth as R


def test_activation_accounting_is_inert_for_cl3_to_cl5_knowledge(monkeypatch):
    actor = SimpleNamespace(entity_id="actor:cl5")
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}))
    monkeypatch.setattr(R, "knowledge", lambda _engine, _actor: {
        "block": "five_elements_knowledge", "cycle": 0,
    })
    assert R.accounting(engine) is None
    monkeypatch.setattr(R, "knowledge", lambda _engine, _actor: {
        "block": "five_elements_knowledge", "cycle": 1,
    })
    assert R.accounting(engine) is True


def test_technique_completion_queue_is_idempotent_per_context(monkeypatch):
    import combat.paid_relocation as accounting
    actor = SimpleNamespace(entity_id="actor:cycle")
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}))
    tracker = accounting._Tracker(engine, actor, "action:cycle")
    ctx = SimpleNamespace(engine=engine, actor=actor,
        action=SimpleNamespace(source_definition_id="action:cycle"))
    monkeypatch.setattr(ext, "run_strict", lambda *_args: [True])
    token = accounting._TRACKER.set(tracker)
    try:
        accounting.technique_completed(ctx)
        accounting.technique_completed(ctx)
    finally:
        accounting._TRACKER.reset(token)
    assert tracker.completed_techniques == [(ctx, tracker.owner)]


def test_builder_acquisition_controls_keep_all_options_without_node():
    from character_creation.acquisition_choices import definitions
    choices = next(row for row in definitions().values() if row["parent_id"] == R.PARENT)
    assert set(choices["options"]) == set(R.ELEMENTS)
    source = (Path(__file__).resolve().parents[1] / "static/app.js").read_text()
    assert 'const empty = document.createElement("option"); empty.value = "";' in source
    assert "for (const value of row.options)" in source


def test_builder_acquisition_controls_keep_all_options_and_require_selection():
    if not shutil.which("node"):
        # The adjacent Python test preserves these essential public assertions
        # where node is unavailable; do not silently skip the builder contract.
        test_builder_acquisition_controls_keep_all_options_without_node()
        return
    app = Path(__file__).resolve().parents[1]
    script = r'''
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.value = ''; }
  appendChild(node) { this.children.push(node); return node; }
  after(node) { nodes[node.id] = node; }
}
nodes.sheetSubpath = new Element('select');
const selected = new Set();
const all = node => [node, ...node.children.flatMap(all)];
const document = {getElementById: key => nodes[key] || null, createElement: tag => new Element(tag),
 querySelectorAll: () => Object.values(nodes).flatMap(all).filter(n => n.dataset.acquisitionChoice)};
const context = {document, characterBuilderOptions: {acquisition_choices: input.definitions},
 selectedSet: () => selected, planningIsEditable: () => true, clearNode: node => {node.children = [];}};
vm.createContext(context);
const source = fs.readFileSync(input.source, 'utf8');
for (const name of ['renderAcquisitionChoices', 'collectAcquisitionChoices']) {
 const start = source.indexOf(`function ${name}(`), end = source.indexOf('\nfunction ', start + 1);
 vm.runInContext(source.slice(start, end < 0 ? source.length : end), context);
}
context.renderAcquisitionChoices();
if (document.querySelectorAll().length) throw Error('unowned choices shown');
selected.add(input.parent); context.renderAcquisitionChoices();
let select = document.querySelectorAll()[0];
if (select.value !== '' || select.children.length !== 6) throw Error('missing choice or options cut');
select.value = 'water'; context.renderAcquisitionChoices();
if (context.collectAcquisitionChoices().five_elements_start !== 'water') throw Error('choice lost');
selected.clear(); context.renderAcquisitionChoices();
if (Object.keys(context.collectAcquisitionChoices()).length) throw Error('unowned selection leaked');
console.log('All five choices remain available; no selection is fabricated.');
'''
    from character_creation.acquisition_choices import definitions
    result = subprocess.run(["node", "-e", script], input=json.dumps({
        "source": str(app / "static/app.js"), "definitions": definitions(), "parent": R.PARENT}),
        text=True, capture_output=True, check=True)
    assert "All five choices" in result.stdout


def test_builder_restore_renders_choice_selects_before_restoring_them():
    source = (Path(__file__).resolve().parents[1] / "static/app.js").read_text()
    restore = source[source.index("function restoreCharacterSheet("):]
    refresh = restore.index("refreshPathSubpathChoices(")
    restore_choices = restore.index('querySelectorAll("[data-acquisition-choice]")')
    assert refresh < restore_choices
