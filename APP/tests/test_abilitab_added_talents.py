"""ABILTAB1 (owner 2026-10-21): talents and Spheres added through Grow's add-talents section must appear on the
sheet's Abilities tab. The sealed build's ``selected_record_sections`` cannot carry a table addition, so the
library view merges the sheet's applied ``spheres_and_talents`` known set (combat/table_advance.py) with the
build rows. Synthetic sheet only, so this runs in public CI."""

import json
import zipfile
from copy import deepcopy
from pathlib import Path

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET

ROOT = Path(__file__).resolve().parents[1]
PID = "ab1ab1ab-0000-4000-8000-000000000001"

BASE = deepcopy(SHEET)
BASE["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.brute"],
                                "learned_talent_record_ids": ["TAL_BRUTE_MOUNTAIN_MOVING_PALM"]}
BASE["ability_scores_and_statistics"]["primary_resource"] = {"name": "Stamina", "maximum": 40}
BASE["selected_record_sections"] = {
    "spheres": [{"record_id": "tianxia.sphere.brute", "display_name": "Brute",
                 "full_description": "# Sphere of Brute\nForce."}],
    "talents": [{"record_id": "TAL_BRUTE_MOUNTAIN_MOVING_PALM", "display_name": "Mountain-Moving Palm",
                 "full_description": "### Mountain-Moving Palm\nPush them 30 feet.", "acquisition_cl": 1}],
}


def _install(userdata: Path) -> None:
    folder = userdata / "portable_characters" / PID
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(BASE))


def _service(userdata: Path) -> TabletopService:
    service = TabletopService(CombatService(ROOT, userdata), userdata)
    service.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return service


def _spheres(sheet: dict) -> list[dict]:
    return next(group for group in sheet["library"]["groups"] if group["key"] == "spheres")["spheres"]


def _entries(sheet: dict) -> dict[str, dict]:
    return {entry["id"]: entry for sphere in _spheres(sheet) for entry in sphere["entries"]}


def test_table_added_talent_and_sphere_join_the_abilities_library(tmp_path):
    _install(tmp_path)
    table = _service(tmp_path)
    before = _entries(table.sheet(PID))
    assert set(before) == {"TAL_BRUTE_MOUNTAIN_MOVING_PALM"}
    assert before["TAL_BRUTE_MOUNTAIN_MOVING_PALM"]["kind"] == "Talent"

    table.add_advancement(PID, "sphere", "tianxia.sphere.the_piercing_needle", gm=True)
    table.add_advancement(PID, "talent", "TAL_FENCING_FATAL_OPENING", gm=True)
    sheet = table.sheet(PID)
    entries = _entries(sheet)

    # The talent the table added is listed with its printed name, the CL it was added at, and the
    # same automatic badge a build entry of the same record gets (Fatal Opening is a passive).
    opening = entries["TAL_FENCING_FATAL_OPENING"]
    assert opening["name"] == "Fatal Opening" and opening["kind"] == "Talent"
    assert opening["cl"] == 17 and opening["status"] == "auto"
    assert opening["text"].strip()  # its printed rules come with the record, as on a build entry

    # The Sphere learned at the table is its own block, holding its base ability and the new talent.
    needle = next(sphere for sphere in _spheres(sheet) if sphere["id"] == "tianxia.sphere.the_piercing_needle")
    assert needle["name"] == "The Piercing Needle" and needle["text"].strip()
    needle_entries = {entry["id"]: entry for entry in needle["entries"]}
    assert set(needle_entries) == {"TAL_FENCING_FEINT", "TAL_FENCING_FATAL_OPENING"}
    assert needle_entries["TAL_FENCING_FEINT"]["kind"] == "Base ability"

    # Counts on the group are the union of build rows and table additions, with no duplicate.
    assert sum(len(sphere["entries"]) for sphere in _spheres(sheet)) == 3
    assert [entry["id"] for sphere in _spheres(sheet) for entry in sphere["entries"]
            if entry["name"] == "Mountain-Moving Palm"] == ["TAL_BRUTE_MOUNTAIN_MOVING_PALM"]

    # A table save is a commit: a fresh service must build the same library from disk.
    reloaded = _service(tmp_path)
    assert {"TAL_FENCING_FATAL_OPENING", "TAL_FENCING_FEINT"} <= set(_entries(reloaded.sheet(PID)))

    # Undoing the additions removes them again.
    table.remove_advancement(PID, "talent", "TAL_FENCING_FATAL_OPENING")
    table.remove_advancement(PID, "sphere", "tianxia.sphere.the_piercing_needle")
    assert set(_entries(table.sheet(PID))) == {"TAL_BRUTE_MOUNTAIN_MOVING_PALM"}
    assert [sphere["id"] for sphere in _spheres(table.sheet(PID))] == ["tianxia.sphere.brute"]


def test_a_technique_built_at_the_table_is_listed_and_the_none_marker_is_kept():
    from combat import table_advance
    from combat.tabletop import sheet_library

    technique = {"technique_id": "tianxia.constructed.forged_technique.test", "name": "Magma Court",
                 "record_text": "Magma Court (Forged Technique, CL 17)\nBase Form: Zone", "cl_created": 17}
    applied = table_advance.apply(deepcopy(BASE), {"forged": [{"technique": technique, "source": "campaign", "cl": 17, "gm": True}]})
    group = next(group for group in sheet_library(applied, [], set())["groups"] if group["key"] == "techniques")
    assert [(entry["id"], entry["name"], entry["cl"]) for entry in group["entries"]] == [
        ("tianxia.constructed.forged_technique.test", "Magma Court", 17)]
    assert "Base Form: Zone" in group["entries"][0]["text"]

    # A sealed "no technique" marker must not be replaced by its own keys when other additions are applied,
    # but a technique built at the table does replace it.
    sealed = deepcopy(BASE)
    sealed["forged_techniques"] = {"state": "none", "reason": "No forged techniques were selected."}
    assert table_advance.apply(sealed, {"talents": [{"id": "TAL_FENCING_FATAL_OPENING", "cl": 17}]})["forged_techniques"] == sealed["forged_techniques"]
    built = table_advance.apply(sealed, {"forged": [{"technique": technique, "source": "campaign", "cl": 17, "gm": True}]})
    assert built["forged_techniques"] == [technique]

