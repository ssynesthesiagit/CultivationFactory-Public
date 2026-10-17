from __future__ import annotations

import json
import subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIC = ROOT / "static/sphere_talent_logic.js"


def _node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_pure_ui_logic_dedupes_multi_sphere_talents_and_removes_only_orphans():
    result = _node(
        f"""
        const logic = require({json.dumps(str(LOGIC))});
        const index = {{
          by_sphere: {{s1: [\"t1\", \"multi\"], s2: [\"t2\", \"multi\"]}},
          by_talent: {{t1: [\"s1\"], t2: [\"s2\"], multi: [\"s1\", \"s2\"], legacy: []}}
        }};
        const first = logic.removeSphereSelection([\"s1\", \"s2\"], [\"t1\", \"multi\", \"multi\", \"legacy\"], \"s1\", index);
        const second = logic.removeSphereSelection(first.sphere_ids, first.talent_ids, \"s2\", index);
        console.log(JSON.stringify({{
          uniqueChoices: logic.uniqueChoices([{{choice_id:\"x\"}},{{choice_id:\"x\"}},{{choice_id:\"y\"}}]).map(x => x.choice_id),
          normalized: logic.normalizeLockedSelections({{sphere_priorities:[\"s1\",\"s1\"], advancement_skeleton:[\"multi\",\"multi\"]}}),
          first,
          second,
          s1Talents: logic.talentIdsForSphere(index, \"s1\")
        }}));
        """
    )
    assert result["uniqueChoices"] == ["x", "y"]
    assert result["normalized"] == {"sphere_priorities": ["s1"], "advancement_skeleton": ["multi"]}
    assert result["first"] == {
        "sphere_ids": ["s2"],
        "talent_ids": ["multi", "legacy"],
        "removed_talent_ids": ["t1"],
    }
    assert result["second"] == {
        "sphere_ids": [],
        "talent_ids": ["legacy"],
        "removed_talent_ids": ["multi"],
    }
    assert result["s1Talents"] == ["t1", "multi"]


def test_sphere_centered_ui_contract_and_javascript_syntax():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "static/styles.css").read_text(encoding="utf-8")

    class IdParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids: list[str] = []

        def handle_starttag(self, _tag, attrs):
            self.ids.extend(value for key, value in attrs if key == "id")

    parser = IdParser()
    parser.feed(html)
    assert not [item for item, count in Counter(parser.ids).items() if count > 1]
    subprocess.run(["node", "--check", str(LOGIC)], check=True)
    subprocess.run(["node", "--check", str(ROOT / "static/app.js")], check=True)

    assert html.index("sphere_talent_logic.js") < html.index("app.js")
    for expected in (
        'id="sheetSphereList"',
        'id="sheetTalentPanelTitle"',
        'id="sheetTalentSearch"',
        'id="sheetTalentOptions"',
        'id="sheetUnassignedTalentDetails"',
        "Unassigned / needs authority",
    ):
        assert expected in html
    assert "removeSheetSphere" in javascript
    assert "removed_talent_ids" in javascript
    assert "Talents for ${activeName}" in javascript
    assert "sphereTalentLogic.uniqueChoices" in javascript
    assert ".sphere-talent-workspace" in styles
    assert "@media (max-width: 980px)" in styles
