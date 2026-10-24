"""F15 regression: the Living Painting command range must not be an unlimited (null) range.

The printed CL6 Living Painting text gives no command range. The F14 round changed the four
forms to null, which means "no range check" (combat/summons.py), an unsourced rule. F15 keeps
the documented 120-foot reading and marks it as a reading that needs an owner ruling.
Source-only: reads combat/rules/summons.json, no engine run.
"""
import json
from pathlib import Path

SUMMONS = Path(__file__).resolve().parents[1] / "combat" / "rules" / "summons.json"
FORMS = ("tiger", "crane", "tortoise", "serpent")


def _sources():
    return json.loads(SUMMONS.read_text(encoding="utf-8"))["sources"]


def test_living_painting_forms_keep_a_reading_not_unlimited_command_range():
    sources = _sources()
    for form in FORMS:
        row = sources[f"tianxia.subpath.qi.painting_cultivator.feature.living_painting#{form}"]
        assert row["command_range_ft"] is not None, form
        assert row["command_range_ft"] == 120, form
        assert "120 feet is a reading, not printed text" in row["evidence"], form
        assert "owner ruling" in row["evidence"], form
