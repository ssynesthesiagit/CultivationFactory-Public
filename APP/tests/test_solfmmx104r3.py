"""Complete owner rules must survive the sheet service and shipped client."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

from combat.action_text import layout_action
from combat import hover_text
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET

APP = Path(__file__).resolve().parents[1]
RECORDS = {
    "tianxia.path.body_refining.feature.core_tempering_expression": "Core Tempering Expression",
    "TAL_UNMAKING_BLACK_TRACE": "Black Trace",
}


@pytest.fixture
def library_entries(tmp_path):
    # Expectations come directly from owner authority, never from the formatter.
    printed = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())
    sheet = copy.deepcopy(SHEET)
    sheet["selected_record_sections"] = {"path_features": [], "talents": []}
    for record, name in RECORDS.items():
        section = "talents" if record.startswith("TAL_") else "path_features"
        sheet["selected_record_sections"][section].append({
            "record_id": record, "display_name": name, "full_description": printed[record]})
    bundle = compile_character(sheet, actor_id="actor:factory.mmx104r3")
    before = copy.deepcopy((sheet, bundle))

    class CompiledTable(TabletopService):
        def _bundle_and_summary(self, project_id):
            return sheet, bundle, {"cultivation_level": 17}

    table = CompiledTable(CombatService(APP, tmp_path), tmp_path)
    response = table.sheet("00000000-abcdef")
    entries = []
    for group in response["library"]["groups"]:
        entries.extend(group.get("entries") or [])
        for sphere in group.get("spheres") or []:
            entries.extend(sphere.get("entries") or [])
    assert (sheet, bundle) == before
    return [entry for entry in entries if entry["id"] in RECORDS]


def test_service_preserves_complete_sections_lists_and_tables(library_entries):
    printed = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())
    assert {entry["id"] for entry in library_entries} == set(RECORDS)
    for entry in library_entries:
        expected = printed[entry["id"]].strip()
        assert entry["text"] == expected
        assert entry["hover"]["text"] == expected
        assert entry["hover"]["body"] == [expected]
        # Multi-option rules cannot be assigned to a single preceding Cost field.
        assert entry["hover"]["fields"] == []


def test_service_rules_survive_actual_client_library_renderer(library_entries):
    result = subprocess.run(
        ["node", str(APP / "tests/solfmmx104r3_library.test.mjs"), "--service"],
        input=json.dumps(library_entries), text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unlabelled_structural_rules_and_caller_notes_survive():
    markup = "# Choices\n\n## First\n- Gain +2 AC.\n\n## Second\n1. Regain 3 Hit Points."
    hover = layout_action({"label": "Choices", "parameters": {"description": markup}},
                          extra=["Available again on your next turn."])
    assert hover["text"] == markup + "\nAvailable again on your next turn."
    assert hover["body"] == [markup, "Available again on your next turn."]


def test_mark_reading_and_enforced_lifetime_survive_structural_source():
    markup = "# Mark source\n\n**Effect:** Choose one:\n- Protect an ally.\n- Damage an enemy."
    summary = "A mark Mei placed. It does nothing on its own."
    hover = hover_text.layout(subject="Mark", kind="mark", markup=markup,
                              summary=summary, applied_by="Mei", duration="until removed")
    assert hover["summary"] == summary
    assert hover["text"].startswith(markup + "\n" + summary)
    assert hover["footer"] == "Applied by Mei. Lasts until removed."
