"""The Grow tab's Golden Core block, rendered from the server panel by the real grow.js.

The panel (combat/ext/qi_path.py GoldenCoreChoice.panel) decides what a character sees: whether it owns the
feature, which Forms are recorded, which choices are legal and why, and whether the printed window is closed.
These tests run the real ``goldenCoreBlock`` offline with stubbed DOM helpers, so they check behaviour instead
of the file's text: a character without the feature gets no block, a recorded Form is shown with its benefit,
an illegal choice is disabled with its reason, and only a GM can record a use that closed the window.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
GROW = APP / "static/tabletop/grow.js"
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"

STABLE = {
    "id": "stable", "name": "Stable Golden Core", "slot": 1, "allowed": False,
    "reason": "That is already your first Form.",
    "benefit": "When Initiative is rolled, if your Qi is below your Proficiency Bonus you regain Qi up to it.",
    "perfected": "From Cultivation Level 17: recover up to 2 x Proficiency Bonus on Initiative.",
}
RESERVOIR = {
    "id": "reservoir", "name": "Golden Core Reservoir", "slot": 2, "allowed": True,
    "reason": "Choose as your second Form.",
    "benefit": "Bonus Action, once per scene: regain Qi equal to your Proficiency Bonus plus your key ability modifier.",
    "perfected": "From Cultivation Level 17 you regain 2 x Proficiency Bonus plus your key ability modifier.",
}
RECORDED_FORM = {
    "slot": 1, "id": "circulating", "name": "Circulating Golden Core", "source": "sheet", "cl": 10, "at": None,
    "benefit": "Once per turn, after you spend Qi on a feature that resolves successfully, choose one benefit.",
    "perfected": "From Cultivation Level 17 you choose two different benefits.",
}


def _panel(**over):
    panel = {"cl": 10, "owned": True, "forms": [], "options": [STABLE, RESERVOIR], "breakthrough": None,
             "nascent_used": False, "nascent_feature_id": NASCENT}
    panel.update(over)
    return panel


FIXTURE = {
    "non_owner": _panel(owned=False, forms=[], options=[]),
    "no_record": _panel(cl=10, forms=[], options=[
        {**STABLE, "allowed": True, "reason": "Choose as your first Form."}, RESERVOIR]),
    "recorded": _panel(cl=10, forms=[RECORDED_FORM], options=[STABLE, RESERVOIR]),
    "cl15_open": _panel(cl=15, forms=[RECORDED_FORM],
                        options=[{**STABLE, "reason": "Record your successful Cultivation Level 15 breakthrough first."},
                                 RESERVOIR],
                        breakthrough={"cl": 15, "recorded": False}),
    "nascent_used": _panel(cl=15, forms=[RECORDED_FORM],
                           options=[{**STABLE, "reason": "You have already used your Nascent Soul feature."}, RESERVOIR],
                           breakthrough={"cl": 15, "recorded": True}, nascent_used=True),
}

NODE_SCRIPT = r"""
import fs from 'node:fs';
import assert from 'node:assert/strict';
(async () => {
  const fixture = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  let source = fs.readFileSync(process.argv[2], 'utf8');
  source += '\n;globalThis.__grow = { setDeps: (v) => { deps = v; }, setData: (v) => { data = v; }, goldenCoreBlock };';
  await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const G = globalThis.__grow;
  let gmOn = false;
  const h = (tag, props, ...kids) => ({ tag, props: props || {}, children: kids.flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false) });
  const text = (node) => node == null ? '' : typeof node !== 'object' ? String(node) : (node.children || []).map(text).join(' ');
  const walk = (node, out) => { if (node && typeof node === 'object') { out.push(node); (node.children || []).forEach((c) => walk(c, out)); } return out; };
  G.setDeps({ h, $: (id) => (id === 'grow-gm' ? { checked: gmOn } : null), fetchJson: async () => { throw new Error('no fetch'); },
    toast() {}, reloadSheet() {}, projectId: 'p' });
  const render = (panel) => { G.setData({ build_choices: { golden_core: panel } }); return G.goldenCoreBlock(); };
  const out = {};

  // A character without the Golden Core Form feature sees no block at all.
  out.nonOwnerNull = render(fixture.non_owner) === null;
  assert.equal(out.nonOwnerNull, true, 'a non-owner must get no Golden Core block');

  // A character with the feature and no record is told it holds no Form (never a Stable default) and offered the choice.
  const noRecord = render(fixture.no_record);
  out.noRecordText = text(noRecord);
  assert.match(out.noRecordText, /No Form is recorded yet/);
  assert.match(out.noRecordText, /you hold no Golden Core Form in combat/);
  assert.ok(!out.noRecordText.includes('Stable Golden Core is used in combat'));
  const noRecordButtons = walk(noRecord, []).filter((n) => n.props && n.props.dataset && n.props.dataset.growGoldenForm);
  out.noRecordButtons = noRecordButtons.map((n) => text(n));
  assert.ok(noRecordButtons.some((n) => n.props.dataset.growGoldenForm === 'stable' && n.props.disabled !== true));

  // A recorded Form is shown with what it does, and an illegal choice stays visible but disabled with its reason.
  const recorded = render(fixture.recorded);
  out.recordedText = text(recorded);
  assert.match(out.recordedText, /Recorded Form: Circulating Golden Core \(recorded at cultivation level 10\)/);
  assert.match(out.recordedText, /choose one benefit/);
  assert.match(out.recordedText, /From Cultivation Level 17 you choose two different benefits/);
  assert.match(out.recordedText, /That is already your first Form/);
  const nodes = walk(recorded, []);
  const stableButton = nodes.find((n) => n.props && n.props.dataset && n.props.dataset.growGoldenForm === 'stable');
  assert.equal(stableButton.props.disabled, true, 'an illegal choice must be disabled, not hidden');
  assert.equal(stableButton.props.title, 'That is already your first Form.');

  // The CL15 breakthrough record is offered only while a replacement is possible.
  const cl15 = walk(render(fixture.cl15_open), []);
  out.breakthroughButton = cl15.some((n) => n.props && n.props.dataset && n.props.dataset.growBreakthrough === '15');

  // Only a GM records a use that happened away from the table; a player is told to ask the GM.
  gmOn = false;
  const playerView = text(render(fixture.cl15_open));
  out.playerAsksGm = /ask your GM to record it/.test(playerView);
  const playerUse = walk(render(fixture.cl15_open), []).filter((n) => n.props && n.props.dataset && n.props.dataset.growFeatureUse);
  out.playerUseButtons = playerUse.length;
  gmOn = true;
  const gmView = walk(render(fixture.cl15_open), []);
  const gmButton = gmView.find((n) => n.props && n.props.dataset && n.props.dataset.growFeatureUse);
  out.gmUseId = gmButton ? gmButton.props.dataset.growFeatureUse : '';
  assert.equal(out.gmUseId, fixture.cl15_open.nascent_feature_id);

  // Once the window is closed the block says so and offers no use button.
  gmOn = true;
  const closed = render(fixture.nascent_used);
  out.closedText = text(closed);
  assert.match(out.closedText, /window to replace your first Form is closed/);
  out.closedUseButtons = walk(closed, []).filter((n) => n.props && n.props.dataset && n.props.dataset.growFeatureUse).length;
  assert.equal(out.closedUseButtons, 0);

  process.stdout.write(JSON.stringify(out));
})().catch((error) => { console.error(error); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_grow_golden_core_block_behaviour(tmp_path):
    fixture = tmp_path / "panel.json"
    fixture.write_text(json.dumps(FIXTURE), encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(NODE_SCRIPT, encoding="utf-8")
    result = subprocess.run(["node", str(script), str(GROW), str(fixture)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["nonOwnerNull"] is True
    assert out["noRecordButtons"] and any("Stable Golden Core" in label for label in out["noRecordButtons"])
    assert out["breakthroughButton"] is True
    assert out["playerAsksGm"] is True and out["playerUseButtons"] == 0
    assert out["gmUseId"] == NASCENT
    assert out["closedUseButtons"] == 0
