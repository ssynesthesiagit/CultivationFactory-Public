"""Inspect unchanged strict-stock captures; never waive their equality failure.

Run after the stock comparison in the same queued chunk. Alone this skips,
including on public CI when the native stock artifacts aren't supplied.
"""
import json

import pytest

from tests.ai_stock_audit import compare_capture, stock_evidence_dir

SEEDS = ("LOCK5-A", "LOCK5-B", "LOCK5-C", "GATE4-TEST", "GATE4-AN-1", "GATE4-LEE")


def test_explain_each_supplied_stock_capture(tmp_path_factory, capsys):
    evidence = stock_evidence_dir(tmp_path_factory.getbasetemp())
    if not all((evidence / f"{seed}-{arm}{suffix}.json").exists()
               for seed in SEEDS for arm in ("base", "head") for suffix in ("", "-decisions")):
        pytest.skip("Run after the stock comparison in the same queued chunk to inspect its artifacts")
    reports = []
    for seed in SEEDS:
        base, head = [json.loads((evidence / f"{seed}-{arm}.json").read_text()) for arm in ("base", "head")]
        choices = [json.loads((evidence / f"{seed}-{arm}-decisions.json").read_text()) for arm in ("base", "head")]
        reports.append(compare_capture(seed, base, head, *choices))
    (evidence / "ai-choice-differences.json").write_text(json.dumps(reports, indent=2) + "\n")
    with capsys.disabled():
        for report in reports:
            print("AIUP1 STOCK DIFF " + json.dumps(report, sort_keys=True), flush=True)
    # A changed rule/roll before a changed semantic decision needs investigation.
    for report in reports:
        assert report["rules_equal_before_choice"], report
