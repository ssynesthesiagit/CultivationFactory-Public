"""Read-only stock evidence inspector; no history reads or capture subprocesses.

Run after the unchanged stock comparison file in the same queued chunk. Alone
it skips: that is also its public-CI path when stock artifacts are not supplied.
The stock harness itself verifies native replay of both complete captures.
"""
import json
import os
from pathlib import Path

import pytest

SEEDS = ("LOCK5-A", "LOCK5-B", "LOCK5-C", "GATE4-TEST", "GATE4-AN-1", "GATE4-LEE")


def accepted(events):
    event = next((e for e in events if e["event_type"] == "INTENT_ACCEPTED"), None)
    if event is None:
        return None
    payload = event.get("payload", {})
    return {**{k: event.get(k) for k in ("actor_id", "source_definition_id", "target_ids")},
            "kind": payload.get("kind"), "destination": payload.get("destination"),
            "options": payload.get("option_ids", [])}


def outcomes(events):
    # Core mechanics only, not saved snapshots or controller accounting.
    return [{**{k: e.get(k) for k in ("event_type", "actor_id", "source_definition_id", "target_ids")},
             "payload": {k: v for k, v in e.get("payload", {}).items() if not k.startswith("gate3_")}}
            for e in events if e["event_type"] in {
                "MOVEMENT_COMMITTED", "DAMAGE_COMMITTED", "RESOURCE_SPENT", "CONDITION_APPLIED",
                "TYPED_AREA_RESOLVED", "ZONE_CREATED", "ATTACK_ROLLED", "SAVE_ROLLED"}]


def test_explain_each_supplied_stock_capture(tmp_path_factory, capsys):
    default = Path(os.environ["TMPDIR"]) / "stock" if os.environ.get("TMPDIR") else tmp_path_factory.getbasetemp() / "stock"
    evidence = Path(os.environ.get("CF_STOCK_EVIDENCE") or os.environ.get("CF_STOCK_EVIDENCE_DIR")
                    or os.environ.get("CF_STOCK_EVIDENCE_ROOT") or default)
    if not all((evidence / f"{seed}-{arm}.json").exists() for seed in SEEDS for arm in ("base", "head")):
        pytest.skip("Run after the stock comparison in the same queued chunk to inspect its artifacts")
    reports = []
    for seed in SEEDS:
        base, head = [json.loads((evidence / f"{seed}-{arm}.json").read_text()) for arm in ("base", "head")]
        pairs = list(zip(base["events"], head["events"]))
        choice_index = next((i for i, (a, b) in enumerate(pairs) if accepted(a) != accepted(b)), None)
        outcome_index = next((i for i, (a, b) in enumerate(pairs) if outcomes(a) != outcomes(b)), None)
        menu_index = next((i for i, (a, b) in enumerate(zip(base["choices"], head["choices"])) if a != b), None)
        report = {"seed": seed, "steps": [base["steps"], head["steps"]],
            "zones": [base["zones"], head["zones"]], "summons": [base["summons"], head["summons"]],
            "terminal": [base["state"]["terminal_result"], head["state"]["terminal_result"]],
            "first_choice_step": None if choice_index is None else choice_index + 1,
            "first_menu_step": None if menu_index is None else menu_index + 1,
            "first_outcome_step": None if outcome_index is None else outcome_index + 1}
        if choice_index is not None:
            a, b = pairs[choice_index]
            report.update(base_choice=accepted(a), head_choice=accepted(b))
        if outcome_index is not None:
            a, b = pairs[outcome_index]
            report.update(base_outcomes=outcomes(a), head_outcomes=outcomes(b))
        reports.append(report)
    with capsys.disabled():
        for report in reports:
            print("AIUP1 STOCK DIFF " + json.dumps(report, sort_keys=True), flush=True)
    # A changed rules result before a changed decision would need investigation.
    for report in reports:
        if report["first_outcome_step"] is not None:
            assert report["first_choice_step"] is not None, report
            assert report["first_outcome_step"] >= report["first_choice_step"], report
