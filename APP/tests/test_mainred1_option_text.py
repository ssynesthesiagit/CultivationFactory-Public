"""MAINRED1: selector cost and hover wording stay consistent after projection."""
import json
from pathlib import Path
import re
import subprocess

from tests.option_tooltip_support import rows


def test_compiled_nullifying_options_keep_both_printed_payments():
    options = [row for row in rows() if row["label"].startswith("Nullifying Strike")]
    assert options
    for row in options:
        for text in (row["description"], row["hover"]["text"]):
            if text:
                assert re.search(r"Cost: 2 (?:cultivation points|CP \(cultivation points, your Path resource\)) or 2 Stamina", text)


def test_compiled_selector_description_and_hover_have_no_additional_rules():
    script = """
import {additionalRuleText} from './static/tabletop/rules.js';
for (const row of JSON.parse(process.env.MAINRED1_ROWS)) {
  const extra = additionalRuleText(row.hover.text, row.description);
  if (extra) {
    const words = text => text.toLowerCase().replace(/[^\\p{L}\\p{N}]+/gu, ' ').trim().split(/\\s+/);
    const description = words(row.description), hover = words(row.hover.text);
    let at = 0;
    while (at < Math.min(description.length, hover.length) && description[at] === hover[at]) at++;
    console.error(JSON.stringify({label: row.label, at,
      description: description.slice(at, at + 18).join(' '), hover: hover.slice(at, at + 18).join(' ')}));
    process.exitCode = 1;
  }
}
"""
    import os
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True,
        env={**os.environ, "MAINRED1_ROWS": json.dumps(rows())})
    assert result.returncode == 0, result.stderr
