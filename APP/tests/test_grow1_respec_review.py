"""Cold service and production UI regressions for the GROW1 independent review.

Synthetic sealed packages only; no owner data, history reads or model servers.
"""
from copy import deepcopy
import hashlib
import json
import shutil
import subprocess
import zipfile

import pytest

from combat import table_advance as ta
from combat.tabletop import TabletopError
from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class
from stage2.formulas import evaluate_formula
from tests.test_grow1_abilities import ROOT, PID, growth_service, installed_sheet


def seal(root, sheet):
    package = root / "portable_characters" / PID / "current.zip"
    package.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    return package


def history(selections):
    """Producer-shaped duplicate views share a persistent selection event ID."""
    return {
        "canonical_allocations": [
            {"event_id": row["event"]["event_id"], "advancement_kind": row["choice_kind"], "target_cl": cl}
            for cl, row in selections
        ],
        "levels": [{"cl": cl, "earned_feature_occurrences": [
            {"selection": deepcopy(row)}, {"selection": deepcopy(row)}
        ]} for cl, row in selections],
    }


def selection(event_id, kind, **fields):
    return {"choice_kind": kind, "event": {"event_id": event_id, "kind": kind}, **fields}


def reset(key="CON"):
    return {"reason": "gm_respec", "cl": 4, "changes": ta.default_spread(key)}


def test_sealed_insight_increases_survive_respec_and_cold_service_reload(tmp_path):
    base = installed_sheet()
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    base["advancement_history"] = history([
        (4, selection("insight-4", "cultivation_insight_acquisition", ability="CON", amount=1)),
        (8, selection("insight-8", "cultivation_insight_acquisition", ability="CON", amount=1)),
        (12, selection("asi-12", "ability_score_change", deltas={"WIS": 2})),
        # Acquiring an Insight does not imply a level-selection increase.
        (13, selection("manual-insight", "cultivation_insight_acquisition", ability="INT")),
    ])
    package = seal(tmp_path, base)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    result = growth_service(tmp_path).add_ability(PID, reset())
    assert result["ability_panel"]["respec_bonuses"] == dict.fromkeys(ta.ABILITIES, 0) | {"CON": 3, "WIS": 2}
    cold = growth_service(tmp_path)
    scores = ta.current_scores(cold.combat._factory_owner_sheet(PID))
    assert scores == ta.default_spread("CON") | {"CON": 18, "WIS": 15}
    assert cold.buttons.get(PID)["advancement"]["abilities"][0]["gm"] is False
    assert cold.advancement(PID)["added"]["abilities"][0]["status"]["legal"]
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("source", ["sealed", "table", "mixed"])
def test_respec_final_cap_includes_all_preserved_increases(tmp_path, source):
    base = installed_sheet()
    # The reset is taken after both CL4/CL8 choices, not backdated before CL8.
    base["identity"]["cultivation_level"] = 12
    reset_entry = {**reset(), "cl": 12}
    # Creation background +2, two sealed level choices +2, or prior table +2s:
    # six earned CON points make a legal 15 base become an illegal final 21.
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 2}}}
    sealed_count = {"sealed": 2, "mixed": 1, "table": 0}[source]
    base["advancement_history"] = history([
        (4 + i * 4, selection(f"asi-{i}", "ability_score_change", deltas={"CON": 2}))
        for i in range(sealed_count)
    ])
    seal(tmp_path, base)
    service = growth_service(tmp_path)
    service.buttons.save_advancement(PID, {"abilities": [
        {"reason": "level_increase", "cl": 4 + i * 4, "changes": {"CON": 2}}
        for i in range(sealed_count, 2)
    ]})
    before = deepcopy(service.buttons.get(PID)["advancement"])
    with pytest.raises(TabletopError, match="cap"):
        service.add_ability(PID, reset_entry)
    assert growth_service(tmp_path).buttons.get(PID)["advancement"] == before

    result = growth_service(tmp_path).add_ability(PID, reset_entry, gm=True)
    assert result["added"]["abilities"][-1]["gm"] is True
    assert result["added"]["abilities"][-1]["status"]["legal"] is False
    cold = growth_service(tmp_path)
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID))["CON"] == 21

    # A later legal reset remains valid and doesn't count earlier resets as gains.
    safe = {**reset_entry, "changes": {"STR": 8, "DEX": 15, "CON": 14, "INT": 13, "WIS": 12, "CHA": 10}}
    result = cold.add_ability(PID, safe)
    assert result["added"]["abilities"][-1]["gm"] is False
    assert result["added"]["abilities"][-1]["status"]["legal"] is True
    assert result["ability_panel"]["respec_bonuses"]["CON"] == 6
    assert ta.current_scores(growth_service(tmp_path).combat._factory_owner_sheet(PID))["CON"] == 20


def test_owned_ac_bonus_survives_path_baseline_path_across_cold_resets(tmp_path):
    base = installed_sheet()
    base["identity"].update(cultivation_level=6, path_ids=["tianxia.path.body_refining"])
    path = "tianxia.path.body_refining.feature.unarmored_defense"
    tempered = "tianxia.subpath.body.iron_shirt.feature.tempered_flesh"
    baseline = {"rule_id": "tianxia.core.unarmored_ac.owner_r1", "formula": {
        "formula_id": "tianxia.core.baseline.unarmored_ac.owner_r1",
        "root": {"op": "add", "terms": [
            {"op": "constant", "value": 10}, {"op": "ability_modifier", "ability": "DEX"}]}}}
    scores = ta.current_scores(base)
    context = {"cl": 6, "pb": 2, "ability_modifiers": {a: ta.ability_modifier(n) for a, n in scores.items()}}
    trace = evaluate_formula(baseline["formula"]["root"], context)
    produced = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), [path, tempered],
        baseline_rule=baseline, baseline_value=trace.value, baseline_trace=trace.trace, context=context)
    assert produced["ac_generation"]["conditional_bonus_sources"] == []
    base["ability_scores_and_statistics"]["armor_class"] = {
        "base_value": produced["ac_base"], "value": produced["ac_active"],
        "formula_trace": produced["ac_generation"]["trace"], "generation": produced["ac_generation"]}
    seal(tmp_path, base)

    # DEX +2 beats CON -1 + PB 2: bonus becomes inactive, never unowned.
    low = {"reason": "gm_respec", "cl": 6, "changes": {"STR": 13, "DEX": 15, "CON": 8, "INT": 14, "WIS": 12, "CHA": 10}}
    growth_service(tmp_path).add_ability(PID, low)
    middle = growth_service(tmp_path).combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["armor_class"]
    assert middle["value"] == 12
    assert middle["generation"]["always_on_bonuses"] == []
    assert [r["feature_id"] for r in middle["generation"]["conditional_bonus_sources"]] == [tempered]

    growth_service(tmp_path).add_ability(PID, {**reset(), "cl": 6})
    final = growth_service(tmp_path).combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["armor_class"]
    assert final["base_value"] == 14
    assert final["value"] == 15
    assert [r["feature_id"] for r in final["generation"]["always_on_bonuses"]] == [tempered]
    assert final["generation"]["conditional_bonus_sources"] == []


def test_grow_respec_renders_base_earned_and_final_scores_and_cap(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the DOM-free production UI regression")
    base = installed_sheet()
    base["identity"]["cultivation_level"] = 8
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 1}}}
    base["advancement_history"] = history([
        (4, selection("insight", "cultivation_insight_acquisition", ability="CON", amount=1)),
    ])
    seal(tmp_path, base)
    service = growth_service(tmp_path)
    service.buttons.save_advancement(PID, {"abilities": [
        # The CL4 Insight has already spent that level choice.
        {"reason": "level_increase", "cl": 8, "changes": {"CON": 1, "WIS": 1}}]})
    payload = service.advancement(PID)
    script = """
      const assert = require('node:assert/strict');
      const fs = require('node:fs');
      const source = fs.readFileSync(process.argv[1], 'utf8');
      // Preserve the complete planning response without an OS argument-size limit.
      const data = JSON.parse(fs.readFileSync(0, "utf8"));
      const handlers = {};
      let rendered = [];
      const root = {addEventListener: (kind, fn) => handlers[kind] = fn,
        replaceChildren: (...nodes) => rendered = nodes};
      const h = (tag, attrs, ...children) => ({tag, attrs, children});
      const text = node => node == null ? '' : typeof node === 'object'
        ? (node.children || []).map(text).join('') : String(node);
      (async () => {
        const grow = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
        grow.initGrow({h, $: id => id === 'grow-root' ? root : null,
          fetchJson: async () => data, projectId: () => 'synthetic'});
        await grow.loadGrow();
        handlers.click({target: {closest: selector => selector === '[data-grow-ability-mode]'
          ? {dataset: {growAbilityMode: 'gm_respec'}} : null}});
        let output = rendered.map(text).join('');
        assert.ok(output.includes('Constitution: base 15 +3 earned = final 18'), output);
        assert.ok(output.includes('Point-buy legal: 27 points.'), output);
        // Reload a server panel after further earned increases.
        data.ability_panel.respec_bonuses.CON = 6;
        await grow.loadGrow();
        output = rendered.map(text).join('');
        assert.ok(output.includes('Constitution: base 15 +6 earned = final 21'), output);
        assert.ok(output.includes('Final scores, including earned increases, must be between 1 and 20.'), output);
        assert.ok(output.includes('GM override'), output);
      })().catch(error => {console.error(error); process.exitCode = 1});
    """
    subprocess.run([node, "-e", script, str(ROOT / "static/tabletop/grow.js")],
                   input=json.dumps(payload), check=True, capture_output=True, text=True)
