"""The table library reads the typed delivery of an installed Forged Technique."""

import io
import json
import zipfile

from character_creation.constructed_arts.forged_technique import construct_forged_technique, forged_technique_id
from character_creation.constructed_arts.forging_authority import load_forging_authority
from character_creation.constructed_arts.records import build_forged_technique_record
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from portable_character.service import PROJECT_MEMBER
from projector.v3_bridge import _forged_technique_projection_rows
from tests.h1_support import ROOT, sheet
from tests.test_constructed_forged_techniques import _request, _talent


def test_installed_combined_save_uses_the_locked_design_without_rewriting_the_sheet(tmp_path):
    project_id = "library-forge"
    talent_id = "AIR_BASE_WIND_LASH"
    sphere_id = "tianxia.sphere.air"
    technique = construct_forged_technique(load_forging_authority(ROOT), _request(
        project_id=project_id,
        known_spheres=[{"sphere_id": sphere_id, "display_name": "Air"}],
        known_talents=[_talent(talent_id, sphere_id, "Wind Lash")],
        concept={"name": "Gale Push", "base_form": "projection", "primary_talent_id": talent_id,
                 "augment_ids": ["forced_movement"]},
    ), generator_version=3)
    assert "One saving throw" in technique["attack_save_check"]
    # Save the design using the old prose, with its own original identity.
    technique["target_range_area"] = technique["target_range_area"].replace("Primary Aspect Effect", "Primary Sphere Effect")
    technique["technique_id"] = forged_technique_id(technique)
    record = build_forged_technique_record(technique)
    rid = record["record_id"]
    event = {"event_id": "event.test.forged", "advancement": {"target_cl": technique["cl_created"],
             "calculation": {"outputs": {"forged_technique": {"record_id": rid, "technique_id": technique["technique_id"]}}}}}
    projected, _ = _forged_technique_projection_rows(
        [event], event_records={event["event_id"]: record}, locked_records={rid: record},
        packet_by_event={event["event_id"]: "packet.test.forged"},
    )
    assert "design_policy" not in projected[0]

    installed_sheet = sheet(talent_id, name="Gale Adept")
    installed_sheet["forged_techniques"] = projected
    installed_sheet["selected_record_sections"] = {"other": [{
        "record_id": rid, "record_hash": record["record_hash"], "display_name": record["display_name"],
        "subsection": "Forged Technique Component", "full_description": projected[0]["record_text"],
    }]}
    export = io.BytesIO()
    with zipfile.ZipFile(export, "w") as nested:
        nested.writestr("locked-records.json", json.dumps([record]))
    package = tmp_path / "portable_characters" / project_id / "current.zip"
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, "w") as installed:
        installed.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(installed_sheet))
        installed.writestr(PROJECT_MEMBER, export.getvalue())
    original = package.read_bytes()

    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    library = table.sheet(project_id)["library"]
    group = next(group for group in library["groups"] if group["key"] == "techniques")
    card, = group["entries"]
    assert card["id"] == rid
    assert "One saving throw against your Cultivation Save DC resolves the technique and its riders together" in card["text"]
    assert "on a success, take half damage" in card["text"]
    assert "Hostile conditions require" not in card["text"]
    assert "the Primary Aspect Effect's printed range and targets apply" in card["text"]
    assert package.read_bytes() == original
