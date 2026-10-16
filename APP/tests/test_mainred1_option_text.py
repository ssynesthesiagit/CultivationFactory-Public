"""MAINRED1: selector cost and hover wording stay consistent after projection."""
import json
from pathlib import Path
import subprocess

import pytest

from combat.option_text import _cost_explained_once
from tests.option_tooltip_support import rows


@pytest.mark.parametrize("cost", [
    "2 CP", "2 CP (cultivation points, your Path resource)",
    "2 cultivation points (your Path resource)", "2 cultivation points",
])
def test_selector_cost_projection_is_idempotent(cost):
    expected = "Cost: 2 CP (cultivation points, your Path resource) or 2 Stamina"
    text = _cost_explained_once(f"Cost: {cost} or 2 Stamina")
    assert text == expected
    assert _cost_explained_once(text) == expected


def test_compiled_selector_description_and_hover_have_no_additional_rules():
    script = """
import {additionalRuleText} from './static/tabletop/rules.js';
for (const row of JSON.parse(process.env.MAINRED1_ROWS)) {
  const extra = additionalRuleText(row.hover.text, row.description);
  if (extra) {
    console.error(JSON.stringify({label: row.label, description: row.description, hover: row.hover.text}));
    process.exitCode = 1;
  }
}
"""
    import os
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True,
        env={**os.environ, "MAINRED1_ROWS": json.dumps(rows())})
    assert result.returncode == 0, result.stderr
