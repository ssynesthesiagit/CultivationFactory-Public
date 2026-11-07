"""Ritual casting and effect clocks stay distinct from authority to client."""
import copy
import json
from pathlib import Path
import re
import subprocess

import pytest

from combat import hover_text
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET

APP = Path(__file__).resolve().parents[1]
RITUALS = [
    ("TAL_DEATH_FUNERARY_PRESERVATION", "Funerary Preservation"),
    ("TAL_DEATH_CORPSE_SERVANT", "Corpse Servant"),
]


@pytest.fixture(params=RITUALS, ids=[name for _, name in RITUALS])
def ritual_entry(request, tmp_path):
    record, name = request.param
    printed = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())[record]
    sheet = copy.deepcopy(SHEET)
    sheet["selected_record_sections"] = {"talents": [
        {"record_id": record, "display_name": name, "full_description": printed}]}
    bundle = compile_character(sheet, actor_id="actor:factory.mmx104r4")
    before = copy.deepcopy((sheet, bundle))

    class CompiledTable(TabletopService):
        def _bundle_and_summary(self, project_id):
            return sheet, bundle, {"cultivation_level": 17}

    response = CompiledTable(CombatService(APP, tmp_path), tmp_path).sheet("00000000-abcdef")
    entries = []
    for group in response["library"]["groups"]:
        entries.extend(group.get("entries") or [])
        for sphere in group.get("spheres") or []:
            entries.extend(sphere.get("entries") or [])
    entry = next(entry for entry in entries if entry["id"] == record)
    assert (sheet, bundle) == before
    return entry, printed


def test_sheet_service_separates_authority_clocks(ritual_entry):
    entry, printed = ritual_entry
    # Read the printed lines independently, without the formatter's alias map.
    casting = re.search(r"^Time: (.+)$", printed, re.M)[1]
    duration = re.search(r"^Duration: (.+)$", printed, re.M)[1]
    fields = entry["hover"]["fields"]
    assert [f["value"] for f in fields if f["label"] == "Casting Time"] == [casting]
    assert [f["value"] for f in fields if f["label"] == "Duration"] == [duration]
    assert f"Casting Time: {casting}" in entry["hover"]["text"]
    assert f"Duration: {duration}" in entry["hover"]["text"]
    assert hover_text.printed_duration_of([(f["label"], f["value"]) for f in fields]) == duration


def test_authority_clocks_survive_shipped_sheet_client(ritual_entry):
    entry, _ = ritual_entry
    result = subprocess.run(
        ["node", str(APP / "tests/solfmmx104r4_library.test.mjs")],
        input=json.dumps(entry), text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shipped_sheet_client_rejects_supplied_entry_without_id():
    result = subprocess.run(
        ["node", str(APP / "tests/solfmmx104r4_library.test.mjs")],
        input="{}", text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "Supplied library entry must include an id" in result.stdout + result.stderr


@pytest.mark.parametrize("label, shown", [
    ("Time", "Casting Time"), ("Casting Time", "Casting Time"), ("Ritual Time", "Ritual Time")])
def test_casting_fields_never_feed_effect_duration(label, shown):
    _, fields = hover_text.split_fields(f"**{label}:** 1 hour")
    assert fields == [(shown, "1 hour")]
    assert hover_text.printed_duration_of(fields) == ""
    assert hover_text.settle_duration("until dismissed", fields) == "until dismissed"
