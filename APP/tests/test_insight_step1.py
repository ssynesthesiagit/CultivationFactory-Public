"""Regression coverage for Insight planning in the owner creation flow."""

import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static/index.html").read_text()
JS = (ROOT / "static/app.js").read_text()


class Tree(HTMLParser):
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.nodes = {}
        self.feed(HTML)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        node = (tag, attrs, tuple(self.stack))
        if "id" in attrs:
            self.nodes[attrs["id"]] = node
        if tag not in self.void:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def run_node(script):
    subprocess.run(["node", "-e", script], input=JS, text=True, capture_output=True, check=True)


# Owner: Insight priorities must be visible on step 2 before request creation.
def test_insight_host_is_in_pre_freeze_step_two():
    tree = Tree()
    tag, attrs, ancestors = tree.nodes["ownerInsightHost"]
    ids = [node[1].get("id") for node in ancestors]
    assert "builderPaths" in ids
    assert "builderReview" not in ids
    assert attrs["data-owner-planning-host"] == "insights"
    assert any(node[0] == "section" and node[1].get("data-planning-phase") == "pre-request-freeze" for node in ancestors)


# Owner: the actual Insight choices, not an empty placeholder, must appear.
def test_shell_moves_the_insight_collection_into_the_host():
    tree = Tree()
    ancestors = tree.nodes["sheetInsightAdd"][2]
    assert any("choice-collection" in node[1].get("class", "").split() for node in ancestors)
    run_node(r"""
const assert = require("assert"), fs = require("fs"), js = fs.readFileSync(0, "utf8");
const source = js.slice(js.indexOf("function prepareProductionOwnerShell()"), js.indexOf("\nprepareProductionOwnerShell();"));
const collection = {}, host = {appendChild(node) { this.child = node; }};
const generic = {appendChild() {}, classList: {add() {}}};
const panel = {querySelector(sel) {
  if (sel === "#sheetInsightAdd") return {closest(s) { assert.equal(s, ".choice-collection"); return collection; }};
  return null;
}, classList: {add() {}}};
const document = {getElementById(id) { return id === "characterSheetPanel" ? panel : id === "ownerInsightHost" ? host : generic; }};
let productionOwnerShellReady = false;
function renderPlanningFreeze() {}
eval(source + "\nprepareProductionOwnerShell();");
assert.strictEqual(host.child, collection);
""")


# Owner: the picker must not disappear before the same freeze that locks Sphere choices.
def test_insight_host_uses_shared_freeze_without_hiding():
    stages = JS.split("function renderCompiledOwnerStages(", 1)[1].split("\nfunction ", 1)[0]
    assert 'getElementById("ownerInsightHost")' not in stages
    freeze = JS.split("function renderPlanningFreeze()", 1)[1].split("\nfunction ", 1)[0]
    assert "#ownerInsightHost [data-multi-slot]" in freeze
    assert "#ownerSphereHost [data-multi-slot]" in freeze
    assert "managePlanningDisabled(node, frozen)" in freeze


# Owner: a chosen Insight must actually reach the request rather than disappearing.
def test_selected_insight_reaches_create_request():
    run_node(r"""
const assert = require("assert"), fs = require("fs"), js = fs.readFileSync(0, "utf8");
const part = (a, b) => js.slice(js.indexOf(a), js.indexOf(b, js.indexOf(a)));
const selected = part("function selectedSet(", "\nfunction ");
const collect = part("function collectSheetSelections()", "\nfunction ");
const add = part("function addSheetChoice(", "\nfunction ");
// Create and Edit Brief share the form serializer; exercise it through the create submit handler.
const create = part("function guidedCreationForm(", '\ndocument.getElementById("guidedSaveDraft")');
const guidedBriefEdit = null;
let callback, captured;
const fields = {guidedName: "", guidedConcept: "", guidedSeed: "", guidedSource: "", guidedLevel: "1", guidedPower: "standard"};
const document = {
  getElementById(id) {
    if (id === "guidedCreate") return {addEventListener(event, fn) { callback = fn; }};
    return {value: fields[id] || ""};
  },
  querySelectorAll(selector) {
    if (selector === "[data-multi-slot]") return [{dataset: {multiSlot: "insight_priorities"}, value: ""}];
    return [];
  }
};
const sheetSelectedChoices = new Map();
let guidedWizardStep = 2, creationMode = "detailed", characterBuilderOptions = {};
function guardPlanningMutation() { return true; }
function categoryFor() { return {}; }
function categoryMaximum() { return null; }
function choiceFor() { return {}; }
function renderChoiceChips() {}
function setGuidedStatus() {}
function renderOwnerLockSummary() {}
function evaluateGuidedReadiness() { return {valid: true}; }
function collectAbilityScores() { return {}; }
function collectAcquisitionChoices() { return {}; }
function methodPlanningMode() { return "AUTO"; }
function methodRouteChoiceForSubmission() { return null; }
function selectedGearPreferences() { return []; }
function collectFeaturePicks() { return null; }
function renderPlanningFreeze() {}
function plainAPIError(e) { return String(e); }
async function api(url, options) {
  if (url === "/api/content-packs") return [{trust_state: "trusted_core", authority: "canonical", record_count: 1}];
  captured = JSON.parse(options.body);
  throw Error("request captured");
}
eval(selected + collect + add + create + `
addSheetChoice("insight_priorities", "insight.synthetic");
callback({preventDefault() {}}).then(() => {
  assert.deepStrictEqual(captured.selections.insight_priorities, ["insight.synthetic"]);
}).catch(e => { console.error(e); process.exitCode = 1; });
`);
""")
