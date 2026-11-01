"""GROWLVLMSG1: the Grow tab's ability block says when a level increase is open and where the next one is, and shows how
each score is made up. Synthetic sheets only (no owner data), so this runs in public CI.

The server (combat/tabletop_service.py advancement) reports availability and per-score sources; the UI (static/tabletop/grow.js)
hides the entry boxes when no increase is open, keeps them under the GM override, and redraws only the ability block.
"""

import json
import shutil
import subprocess

import pytest

from combat import table_advance as ta
from combat.tabletop_service import TabletopService
from tests.test_grow1_abilities import OLD, ROOT, sheet as make_sheet


def service_for(base, saved=None):
    """A TabletopService over an in-memory record; the sheet is the real table overlay (ta.apply)."""
    record = {"advancement": ta.normalized(saved or {})}

    class Buttons:
        def get(self, _project):
            return record

        def save_advancement(self, _project, value):
            record["advancement"] = value

    class Combat:
        def _factory_owner_sheet(self, _project, *, apply_table=True):
            return ta.apply(base, record["advancement"]) if apply_table else base

    service = TabletopService.__new__(TabletopService)
    service.combat, service.buttons = Combat(), Buttons()
    service._talents_cache = []
    service._spheres_cache = {}
    return service


def panel_of(base, saved=None):
    return service_for(base, saved).advancement("synthetic-project")["ability_panel"]


def parts_text(parts):
    first, *rest = parts
    tail = "".join(f" {'+' if row['value'] >= 0 else '−'} {abs(row['value'])} {row['label']}" for row in rest)
    return f"{first['value']} {first['label']}{tail}"


def test_cl10_has_no_open_increase_and_next_is_12():
    rule = panel_of(make_sheet(cl=10))["level_increase"]
    assert rule["current_cl"] == 10
    assert rule["available_now"] is False
    assert rule["next_cl"] == 12


def test_cl12_with_no_increase_recorded_is_open():
    rule = panel_of(make_sheet(cl=12))["level_increase"]
    assert rule["available_now"] is True
    assert rule["next_cl"] == 16


def test_cl12_after_recording_is_not_open_and_next_is_16():
    saved = {"abilities": [{"reason": "level_increase", "cl": 12, "changes": {"CON": 1, "WIS": 1}}]}
    panel = panel_of(make_sheet(cl=12), saved)
    assert 12 in panel["level_increase"]["recorded_cls"]
    assert panel["level_increase"]["available_now"] is False
    assert panel["level_increase"]["next_cl"] == 16
    assert panel["scores"]["CON"] == OLD["CON"] + 1


def test_breakdown_sums_to_each_shown_score_for_increases():
    base = make_sheet(cl=12)
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    saved = {"abilities": [{"reason": "level_increase", "cl": 12, "changes": {"CON": 1, "WIS": 1}}]}
    panel = panel_of(base, saved)
    for a, score in panel["scores"].items():
        parts = panel["sources"][a]
        assert sum(row["value"] for row in parts) == score, (a, parts)
    assert [row["label"] for row in panel["sources"]["CON"]] == ["base", "background", "CL 12"]
    assert parts_text(panel["sources"]["CON"]).endswith("+ 1 background + 1 CL 12")


def test_breakdown_sums_after_a_reset_keeps_earned_increases():
    base = make_sheet(cl=12)
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    saved = {"abilities": [
        {"reason": "level_increase", "cl": 8, "changes": {"STR": 1, "DEX": 1}},
        {"reason": "gm_respec", "cl": 12, "changes": ta.default_spread("CON"), "gm": True},
    ]}
    panel = panel_of(base, saved)
    for a, score in panel["scores"].items():
        assert sum(row["value"] for row in panel["sources"][a]) == score, (a, panel["sources"][a])
    assert panel["sources"]["CON"][0] == {"label": "reset", "value": ta.default_spread("CON")["CON"]}
    assert panel["sources"]["STR"][-1] == {"label": "CL 8", "value": 1}


def test_breakdown_sums_for_a_table_insight_increase_and_names_it():
    base = make_sheet(cl=12)
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    rule = {"allowed_abilities": ["CON", "WIS"], "amount": 1, "cap": 20}
    saved = {"abilities": [{"reason": "insight_selection", "cl": 12, "changes": {"CON": 1},
                            "insight_rule": rule}]}
    panel = panel_of(base, saved)
    assert panel["scores"]["CON"] == OLD["CON"] + 1      # the background is already in OLD's replay; the Insight adds 1
    for a, score in panel["scores"].items():
        assert sum(row["value"] for row in panel["sources"][a]) == score, (a, panel["sources"][a])
    assert [row["label"] for row in panel["sources"]["CON"]] == ["base", "background", "Insight at CL 12"]
    assert parts_text(panel["sources"]["CON"]).endswith("+ 1 background + 1 Insight at CL 12")


def _run_grow_ui(payload, gm_on):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the DOM-free Grow UI regression")
    script = """
      const assert = require('node:assert/strict');
      const fs = require('node:fs');
      const source = fs.readFileSync(process.argv[1], 'utf8');
      const gmOn = process.argv[2] === 'on';
      const handlers = {};
      let replaced = [], rootRenders = 0, rendered = [];
      const root = {addEventListener: (kind, fn) => handlers[kind] = fn,
        replaceChildren: (...nodes) => { rootRenders += 1; rendered = nodes; }};
      const abilities = {replaceWith: node => replaced.push(node)};
      const els = {'grow-root': root, 'grow-gm': {checked: gmOn}, 'grow-abilities': abilities};
      const h = (tag, attrs, ...children) => ({tag, attrs: attrs || {}, children});
      const text = node => node == null || node === false ? '' : Array.isArray(node) ? node.map(text).join('')
        : typeof node === 'object' ? (node.children || []).map(text).join('') : String(node);
      const find = (node, test) => {
        if (Array.isArray(node)) { for (const child of node) { const hit = find(child, test); if (hit) return hit; } return null; }
        if (!node || typeof node !== 'object') return null;
        if (test(node)) return node;
        for (const child of [].concat(node.children || [])) { const hit = find(child, test); if (hit) return hit; }
        return null;
      };
      const hasInput = (nodes, a) => nodes.some(n => find(n, m => m.attrs && m.attrs.id === 'grow-ability-' + a));
      (async () => {
        const input = await new Promise(resolve => { let value = ''; process.stdin.setEncoding('utf8');
          process.stdin.on('data', chunk => value += chunk); process.stdin.on('end', () => resolve(value)); });
        const data = JSON.parse(input);
        const grow = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
        grow.initGrow({h, $: id => els[id] ?? {focus() {}, checked: false}, fetchJson: async () => data,
          projectId: () => 'synthetic', toast() {}, reloadSheet: async () => {}});
        await grow.loadGrow();
        const out = {};
        out.inputsLevel = hasInput(rendered, 'CON');
        out.text = rendered.map(text).join('');
        out.breakdown = rendered.flatMap(n => find(n, m => m.attrs && m.attrs.id === 'grow-abilities') ? [text(n)] : []).join('');
        handlers.click({target: {closest: s => s === '[data-grow-ability-mode]' ? {dataset: {growAbilityMode: 'gm_respec'}} : null}});
        out.replacedAfterMode = replaced.length;
        out.rootRendersAfterMode = rootRenders;
        out.inputsRespec = replaced.length ? hasInput([replaced[replaced.length - 1]], 'CON') : null;
        handlers.input({target: {id: 'grow-ability-CON', type: 'number', value: '15', selectionStart: null, selectionEnd: null,
          dataset: {growAbility: 'CON'}}});
        out.replacedAfterTyping = replaced.length;
        out.rootRendersAfterTyping = rootRenders;
        console.log(JSON.stringify(out));
      })().catch(error => { console.error(error); process.exitCode = 1; });
    """
    result = subprocess.run([node, "-e", script, str(ROOT / "static/tabletop/grow.js"), "on" if gm_on else "off"],
                            input=json.dumps(payload), check=True, capture_output=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def _ui_payload(cl, saved=None):
    base = make_sheet(cl=cl)
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    service = service_for(base, saved)
    return service.advancement("synthetic-project")


def test_closed_level_increase_hides_entry_and_gm_override_keeps_it():
    payload = _ui_payload(10)
    closed = _run_grow_ui(payload, gm_on=False)
    assert closed["inputsLevel"] is False
    assert "The next level increase is at CL 12." in closed["text"]
    assert "No level increase is open at CL 10." in closed["text"]
    overridden = _run_grow_ui(payload, gm_on=True)
    assert overridden["inputsLevel"] is True
    assert "GM override is on" in overridden["text"]


def test_mode_and_typing_redraw_only_the_ability_block_and_show_breakdown():
    saved = {"abilities": [{"reason": "level_increase", "cl": 12, "changes": {"CON": 1, "WIS": 1}}]}
    payload = _ui_payload(12, saved)
    state = _run_grow_ui(payload, gm_on=False)
    assert state["replacedAfterMode"] == 1
    assert state["rootRendersAfterMode"] == 1          # only the initial load rendered the whole tab
    assert state["inputsRespec"] is True
    assert state["replacedAfterTyping"] == 2
    assert state["rootRendersAfterTyping"] == 1
    parts = payload["ability_panel"]["sources"]["CON"]
    assert "= " + parts_text(parts) in state["breakdown"]
