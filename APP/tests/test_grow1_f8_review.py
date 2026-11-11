"""Scoped GROW1F8 review regressions using synthetic packages and offline clients."""
from copy import deepcopy
import hashlib
import json
import shutil
import subprocess

import pytest

from app.core import FoundryError
from combat import table_advance as ta
from projector import path_feature_statistics as statistics
from stage2.formulas import evaluate_formula
from stage2.service import RulesCausalStage2Service, _state
from tests.test_grow1_abilities import PID, ROOT, growth_service, installed_sheet
from tests.test_grow1_respec_review import seal


BASELINE_ID = "tianxia.core.unarmored_ac.owner_r1"
PATH_FEATURE = "tianxia.path.body_refining.feature.unarmored_defense"
LOW_CON_RESET = {
    "reason": "gm_respec",
    "cl": 6,
    "changes": {"STR": 13, "DEX": 15, "CON": 8, "INT": 14, "WIS": 12, "CHA": 10},
}


def body_sheet():
    """A real producer-shaped AC generation record, without private character data."""
    sheet = installed_sheet()
    sheet["identity"].update(
        cultivation_level=6, path_ids=["tianxia.path.body_refining"],
        path_id="tianxia.path.body_refining",
    )
    pack = json.loads(
        (ROOT / "authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json").read_text()
    )
    baseline = next(rule for rule in pack["rules"] if rule["rule_id"] == BASELINE_ID)
    scores = ta.current_scores(sheet)
    context = {
        "cl": 6, "pb": 2,
        "ability_modifiers": {ability: ta.ability_modifier(n) for ability, n in scores.items()},
    }
    result = evaluate_formula(baseline["formula"]["root"], context)
    resolved = statistics.resolve_armor_class(
        statistics.load_path_feature_statistic_formulas(ROOT), [PATH_FEATURE],
        baseline_rule=baseline, baseline_value=result.value,
        baseline_trace=result.trace, context=context,
    )
    sheet["ability_scores_and_statistics"]["armor_class"] = {
        "base_value": resolved["ac_base"], "value": resolved["ac_active"],
        "formula_trace": resolved["ac_generation"]["trace"],
        "generation": resolved["ac_generation"],
    }
    return sheet


@pytest.mark.parametrize("failure", ["authority", "shape", "missing_baseline"])
def test_ac_reselection_failure_is_reported_without_saving_scores(tmp_path, monkeypatch, failure):
    """Exercise the HTTP mutation, error handler, and persisted table document."""
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    from combat.tabletop_service import TabletopService

    sheet = body_sheet()
    if failure == "missing_baseline":
        options = sheet["ability_scores_and_statistics"]["armor_class"]["generation"]["alternatives_considered"]
        options[:] = [row for row in options if row["calculation_id"] != BASELINE_ID]
    package = seal(tmp_path, sheet)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    before = deepcopy(growth_service(tmp_path).buttons.get(PID).get("advancement"))

    def fail_reselection(*args, **kwargs):
        if failure == "authority":
            raise FoundryError("TEST_AUTHORITY_FAILURE", "Synthetic formula authority is unavailable.")
        raise KeyError("synthetic malformed formula")

    if failure != "missing_baseline":
        monkeypatch.setattr(statistics, "resolve_armor_class", fail_reselection)
    monkeypatch.setattr(TabletopService, "_sphere_names", lambda self: {})
    monkeypatch.setattr(TabletopService, "_catalog_talents", lambda self: [])
    app = create_app(Settings.from_env(ROOT, tmp_path))
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        response = client.post(
            f"/api/tabletop/characters/{PID}/advancement/ability",
            headers={"X-Foundry-Token": token},
            json=LOW_CON_RESET,
        )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "TABLE_ADVANCE_ARMOR_CLASS_RECALCULATION_FAILED"
    assert "Armor Class" in error["message"]
    assert "No score change was applied" in error["message"]
    assert growth_service(tmp_path).buttons.get(PID).get("advancement") == before
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def test_renamed_baseline_still_wins_after_score_reset_and_cold_reload(tmp_path):
    sheet = body_sheet()
    options = sheet["ability_scores_and_statistics"]["armor_class"]["generation"]["alternatives_considered"]
    for option in options:
        if option["calculation_id"] == BASELINE_ID:
            option["display_name"] = "Ordinary defense (translated)"
        else:
            # A misleading display string must not turn a Path rule into the baseline.
            option["display_name"] = "Unarmored baseline"
    seal(tmp_path, sheet)

    growth_service(tmp_path).add_ability(PID, LOW_CON_RESET)
    cold = growth_service(tmp_path)
    armor = cold.combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["armor_class"]
    assert armor["base_value"] == 12
    assert armor["value"] == 12
    assert armor["generation"]["calculation_id"] == BASELINE_ID
    cold.remove_advancement(PID, "ability", "0")
    assert growth_service(tmp_path).combat._factory_owner_sheet(PID) == sheet


def test_path_formula_authority_is_loaded_once_for_repeated_overlays(tmp_path, monkeypatch):
    seal(tmp_path, body_sheet())
    real_loader = statistics.load_path_feature_statistic_formulas
    loads = []

    def counted_loader(root):
        loads.append(root)
        return real_loader(root)

    # Allow this test to run against the pre-fix uncached implementation too.
    cached_loader = getattr(ta, "_path_statistic_formulas", None)
    if cached_loader is not None:
        cached_loader.cache_clear()
    monkeypatch.setattr(statistics, "load_path_feature_statistic_formulas", counted_loader)
    try:
        growth_service(tmp_path).add_ability(PID, LOW_CON_RESET)
        for _ in range(3):
            adjusted = growth_service(tmp_path).combat._factory_owner_sheet(PID)
            armor = adjusted["ability_scores_and_statistics"]["armor_class"]
            assert armor["value"] == 12
        assert loads == [ROOT]
    finally:
        if cached_loader is not None:
            cached_loader.cache_clear()


@pytest.mark.parametrize(
    "cl,deltas,score,blocker",
    [
        (3, {"CON": 2}, 14, "ABILITY_CHANGE_AT_ILLEGAL_CL"),
        (4, {"CON": 1}, 14, "ARBITRARY_ABILITY_SCORE_DELTA"),
        (4, {"CON": 2}, 19, "ABILITY_SCORE_CAP_EXCEEDED"),
    ],
)
def test_stage2_blocked_allocations_keep_main_recalculation_and_return_state(
    monkeypatch, cl, deltas, score, blocker,
):
    """Main recalculates a candidate but rejects it without changing caller state."""
    service = object.__new__(RulesCausalStage2Service)
    rule = {"allowed_cls": [4, 8, 12, 16, 19], "budget": 2, "allowed_deltas": [1, 2], "cap": 20}
    record = {
        "record_id": "synthetic.asi", "record_hash": "r" * 64,
        "content_type": "path_feature",
        "source": {"source_id": "synthetic", "source_hash": "s" * 64, "anchor": "ASI"},
        "content_binding": {"pack_id": "synthetic", "pack_version": "1", "pack_hash": "p" * 64},
        "compatibility": {"factory": {"stage2_authority": {"ability_change": rule}}},
    }
    # Bypass catalog lookup only; execute the production choice reducer.
    monkeypatch.setattr(service, "_record", lambda *args, **kwargs: (record, []))
    monkeypatch.setattr(service, "_stage2_authority", lambda *args: [])
    monkeypatch.setattr(service, "_legality_relation_blockers", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(service, "_cardinality_blockers", lambda *args: [])
    candidates = []

    def recalculate(conn, project_id, candidate, prior_scores, **kwargs):
        candidates.append(deepcopy(candidate))
        return {}, {}, [], {}

    monkeypatch.setattr(service, "_recalculate_after_ability", recalculate)
    state = _state("synthetic")
    state.update(current_cl=cl, ability_scores=dict.fromkeys(ta.ABILITIES, 10))
    state["ability_scores"]["CON"] = score
    original = deepcopy(state)
    event, returned_state, blockers = service._choice_event(
        conn=None,
        row={"project_id": "synthetic", "proposal_id": "synthetic.asi"},
        project={}, state=state,
        choice={
            "kind": "ability_score_change", "record_id": record["record_id"],
            "acquisition_channel": "level", "effective_cl": cl,
            "parameters": {"deltas": deltas},
        },
        index=0, sequence=1, previous_hash="0" * 64, generic_prefix=[],
    )
    assert event is None
    assert [issue["code"] for issue in blockers] == [blocker]
    assert returned_state is state
    assert state == original
    assert len(candidates) == 1
    assert candidates[0]["ability_scores"]["CON"] == score + deltas["CON"]
    assert candidates[0]["ability_modifiers"]["CON"] == ta.ability_modifier(score + deltas["CON"])


def test_grow_preview_uses_only_server_point_buy_authority(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the offline production UI regression")
    payload = growth_service(tmp_path).advancement(PID)
    panel = payload["ability_panel"]
    assert panel["point_buy_cost"] == ta.POINT_BUY_COST
    assert panel["point_buy_budget"] == ta.POINT_BUY_BUDGET
    script = """
      const assert = require('node:assert/strict');
      const fs = require('node:fs');
      const source = fs.readFileSync(process.argv[1], 'utf8');
      const data = JSON.parse(process.argv[2]);
      const handlers = {};
      let rendered = [];
      const root = {
        addEventListener: (kind, fn) => handlers[kind] = fn,
        replaceChildren: (...nodes) => rendered = nodes,
      };
      const h = (tag, attrs, ...children) => ({tag, attrs, children});
      const text = node => node == null ? '' : typeof node === 'object'
        ? (node.children || []).map(text).join('') : String(node);
      (async () => {
        const grow = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
        grow.initGrow({
          h, $: id => id === 'grow-root' ? root : null,
          fetchJson: async () => data, projectId: () => 'synthetic',
        });
        await grow.loadGrow();
        handlers.click({target: {closest: selector => selector === '[data-grow-ability-mode]'
          ? {dataset: {growAbilityMode: 'gm_respec'}} : null}});
        assert.ok(rendered.map(text).join('').includes('Point-buy legal: 27 points.'));

        // No stale local price table may bless a panel without server authority.
        delete data.ability_panel.point_buy_cost;
        await grow.loadGrow();
        let output = rendered.map(text).join('');
        assert.ok(output.includes('Point-buy must be'), output);
        assert.ok(!output.includes('Point-buy legal:'), output);

        // The successful summary must also describe the server's actual budget.
        data.ability_panel.point_buy_cost = Object.fromEntries(
          Array.from({length: 8}, (_, i) => [i + 8, 1]));
        data.ability_panel.point_buy_budget = 6;
        await grow.loadGrow();
        output = rendered.map(text).join('');
        assert.ok(output.includes('Point-buy legal: 6 points.'), output);
      })().catch(error => {console.error(error); process.exitCode = 1});
    """
    subprocess.run(
        [node, "-e", script, str(ROOT / "static/tabletop/grow.js"), json.dumps(payload)],
        check=True, capture_output=True, text=True,
    )
