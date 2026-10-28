"""Public, offline regressions for the F4 review's evidence and tier-button bugs."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from tests import ai_stock_audit
from tests.test_ai_tiers_stock_evidence import SEEDS, test_explain_each_supplied_stock_capture as inspect_stock

EVIDENCE_VARS = ("CF_STOCK_EVIDENCE", "CF_STOCK_EVIDENCE_DIR", "CF_STOCK_EVIDENCE_ROOT", "TMPDIR")


def clear_evidence_environment(monkeypatch):
    for name in EVIDENCE_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("changed_damage", [False, True])
def test_capture_writer_and_inspector_share_default_without_tmpdir(tmp_path, monkeypatch, capsys, changed_damage):
    clear_evidence_environment(monkeypatch)
    # Real stock layout: <basetemp>/<pytest case>/<base|head>.
    scratch = tmp_path / "stock-case" / "head"
    capture = {"steps": 1, "events": [[{
        "sequence": 1, "state_version": 1, "event_type": "DAMAGE_COMMITTED",
        "actor_id": "a", "source_definition_id": "test:attack", "target_ids": ["b"],
        "payload": {"hp_damage": 6},
    }]], "rolls": [[{"total": 6}]], "choices": [["attack"]],
        "zones": 0, "summons": 0, "state": {"terminal_result": {"kind": "DURATION_LIMIT"}}}
    decisions = [{"primary": {"kind": "ACTION", "source_definition_id": "test:attack"}, "reactions": []}]
    for seed in SEEDS:
        for arm in ("base", "head"):
            # The capture executable uses this same writer, not an independent
            # test-side reconstruction of its environment/default path logic.
            ai_stock_audit.write_decision_evidence(scratch.with_name(arm), seed, decisions)
            row = json.loads(json.dumps(capture))
            if changed_damage and arm == "head":
                row["events"][0][0]["payload"]["hp_damage"] = 7
            (tmp_path / "stock" / f"{seed}-{arm}.json").write_text(json.dumps(row))
    factory = SimpleNamespace(getbasetemp=lambda: tmp_path)
    try:
        if changed_damage:
            with pytest.raises(AssertionError):
                inspect_stock(factory, capsys)
        else:
            inspect_stock(factory, capsys)
    except pytest.skip.Exception as exc:
        pytest.fail(f"Inspector skipped capture-side artifacts: {exc}")
    reports = json.loads((tmp_path / "stock" / "ai-choice-differences.json").read_text())
    assert len(reports) == 6
    assert all(row["rules_equal_before_choice"] is not changed_damage for row in reports)


@pytest.mark.parametrize("selected", EVIDENCE_VARS)
def test_shared_evidence_resolver_preserves_environment_precedence(tmp_path, monkeypatch, selected):
    clear_evidence_environment(monkeypatch)
    # Populate the selected override and all lower-priority aliases.
    for name in EVIDENCE_VARS[EVIDENCE_VARS.index(selected):]:
        monkeypatch.setenv(name, str(tmp_path / name))
    expected = tmp_path / selected / ("stock" if selected == "TMPDIR" else "")
    assert ai_stock_audit.stock_evidence_dir(tmp_path / "basetemp") == expected


def test_tier_click_keeps_stored_control_mode():
    node = shutil.which("node")
    assert node, "Node is required for the offline desktop click regression"
    script = Path(__file__).with_name("ai_tier_control.test.mjs")
    result = subprocess.run([node, "--test", str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
