"""Insight priority cards stay compact and reflect changes from either control."""
import subprocess
from pathlib import Path

def test_insight_card_selection_and_expansion():
    js = (Path(__file__).resolve().parents[1] / "static/app.js").read_text()
    script = r"""
const assert = require("assert"), fs = require("fs"), js = fs.readFileSync(0, "utf8");
const part = name => { const start = js.indexOf("function " + name + "("); return js.slice(start, js.indexOf("\nfunction ", start + 1)); };
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.open = false; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.append(node); }
  setAttribute(k,v) { this.attributes[k] = v; }
  querySelectorAll(selector) { return this.children.flatMap(n => [...(n.className?.includes("insight-browse-card") ? [n] : []), ...n.querySelectorAll(selector)]); }
}
const document = {createElement: tag => new Node(tag), querySelectorAll: () => []};
const cards = new Node("div"), chips = new Node("div"), values = new Set();
const choice = {choice_id: "synthetic", name: "Silver Thought", player_card: {html: "<article class='player-card'><h3>Silver Thought</h3></article>"}};
const categoryFor = () => ({choices: [choice]}), categoryMaximum = () => null, choiceFor = () => choice;
const selectedSet = () => values, chipHostFor = () => chips, clearNode = node => {node.children = []};
const insightGroupLabel = () => "General", insightGroupId = () => "general", insightBrowseSubgroup = () => "";
const insightDisabledReason = () => "", planningIsEditable = () => true, guardPlanningMutation = () => true;
const PLANNING_FREEZE_MESSAGE = "", renderOwnerLockSummary = () => {}, renderPlanningFreeze = () => {}, evaluateGuidedReadiness = () => {}, setGuidedStatus = () => {};
const choices = Array.from({length: 25}, (_, i) => ({choice_id: "id" + i, name: "Name " + String(i).padStart(2, "0"), player_card: choice.player_card}));
choices[24] = choice;
const INSIGHT_BROWSER_PAGE_SIZE = 24, INSIGHT_GROUP_LABELS = {general: "General"};
document.getElementById = id => id === "sheetInsightCards" ? cards : null;
function renderInsightBrowser(preserve) { renderInsightCards(choices, choices, preserve); }
const renderedCards = () => cards.querySelectorAll(".insight-browse-card");
const insightOpenCardIds = new Set();
eval(part("recordCard") + part("appendInsightBrowseCard") + part("renderInsightCards") + part("renderChoiceChips") + part("addSheetChoice") + `
values.add(choice.choice_id);
renderInsightBrowser();
let card = renderedCards().find(n => n.dataset.insightId === choice.choice_id), details = card.tagName === "details" ? card : card.children.find(n => n.tagName === "details");
assert(details, "missing details: " + card.tagName);
assert(!details.open, "initial open=" + details.open);
const summary = details.children.find(n => n.tagName === "summary");
assert(summary, "missing summary");
const flatten = n => [n, ...n.children.flatMap(flatten)];
assert.equal(flatten(summary).filter(n => n.textContent === choice.name).length, 1, "summary name count");
assert(!flatten(summary).some(n => n.tagName === "button"), "button inside summary");
assert(flatten(details).some(n => n.innerHTML), "record missing from details");
let button = card.children.find(n => n.tagName === "button");
assert(button, "button missing outside summary");
details.open = true; details.ontoggle();
const position = renderedCards().findIndex(n => n.dataset.insightId === choice.choice_id);
chips.children.length = 0; renderChoiceChips("insight_priorities");
chips.children[0].children[1].onclick();
card = renderedCards()[position];
assert.equal(card?.dataset.insightId, choice.choice_id, "removed card at position=" + card?.dataset.insightId);
details = card.children.find(n => n.tagName === "details");
button = card.children.find(n => n.tagName === "button");
assert(details.open, "open after removal=" + details.open);
assert.equal(button.textContent, "Add priority");
button.onclick();
card = renderedCards()[position];
assert.equal(card?.dataset.insightId, choice.choice_id, "added card at position=" + card?.dataset.insightId); details = card.tagName === "details" ? card : card.children.find(n => n.tagName === "details");
button = card.children.find(n => n.tagName === "button");
assert(card.className.includes("selected"), "class=" + card.className);
assert.equal(button.textContent, "Remove priority", "button=" + button.textContent);
assert.equal(button.attributes["aria-pressed"], "true", "pressed=" + button.attributes["aria-pressed"]);
assert(flatten(card).some(n => n.textContent === "Chosen"), "chosen mark absent");
assert(details.open, "open after add=" + details.open);
chips.children[0].children[1].onclick();
card = renderedCards()[position]; assert.equal(card?.dataset.insightId, choice.choice_id); button = card.children.find(n => n.tagName === "button");
assert(!card.className.includes("selected"), "class after removal=" + card.className);
assert.equal(button.textContent, "Add priority", "button after removal=" + button.textContent);
`);
"""
    result = subprocess.run(["node", "-e", script], input=js, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
