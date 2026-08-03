from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"
INDEX_HTML = ROOT / "static" / "index.html"


def test_substantive_commit_rule_distinguishes_empty_and_real_receipts() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(
        r"^function hasSubstantiveCommit\(commit\) \{.*?^\}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    cases = {
        "empty": [
            None,
            {},
            {"schema": "", "outputs": {}, "receipt": None},
            {"nested": {"values": [None, "", {}]}},
            [],
            "",
            False,
            0,
        ],
        "substantive": [
            {"schema": "TianxiaFoundry.CharacterCreationCanonicalCommit.v2"},
            {"approved_candidate_identity": "candidate.sha256"},
            {"outputs": {"portable_character": "artifact.sha256"}},
        ],
    }
    script = (
        match.group(0)
        + "\nconst cases = "
        + json.dumps(cases)
        + ";\n"
        + "if (cases.empty.some(hasSubstantiveCommit)) process.exit(2);\n"
        + "if (!cases.substantive.every(hasSubstantiveCommit)) process.exit(3);\n"
    )
    subprocess.run(["node", "-e", script], check=True)


def test_provider_fallback_surface_keeps_exact_warning_and_backend_mode() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="guidedProviderFallbackWarning"' in html
    assert 'value="${guidedRun.execution_mode}"' in source
    assert "fallbackWarning.textContent = fallbackWarnings.map" in source
    assert "warnings: guidedRun.warnings || []" in source
    assert "The provider call failed or was unavailable." in source
    assert 'canonical_mutation: "None"' in source
    assert 'row.code.endsWith("_FALLBACK_MANUAL")' in source


def test_normal_wizard_uses_one_commit_rule_for_review_and_finalization() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert source.count("function hasSubstantiveCommit(") == 1
    assert 'const commitPresent = hasSubstantiveCommit(run.commit);' in source
    assert 'commitPresent ? "Unexpected commit present" : "None"' in source
    assert "!hasSubstantiveCommit(guidedRun.commit)" in source
    assert 'appendCandidateLine(host, "Canonical commit", pretty(run.commit)' in source
