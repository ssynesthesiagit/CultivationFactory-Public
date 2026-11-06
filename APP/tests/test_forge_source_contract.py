"""Real Grow/creation producers must obey the Sphere-effect request contract.

Use only public authority and synthetic characters; no owner data or services.
"""
from copy import deepcopy
import json

import pytest

from app.core import FoundryError
from combat.forged import mechanic_for
from combat.table_advance import forge_request
from character_creation.constructed_arts.forged_technique import normalize_forged_technique_request
from character_creation.constructed_arts.records import build_forged_technique_record, validate_forged_technique_record
from tests.test_forge_secondary_fit import MECHANICS
from tests.test_forge_secondary_fit_round3 import DISEASE, _creation, _design, _service
from tests.test_grow1_abilities import PID, ROOT, growth_service

DISEASE_SPHERE = "tianxia.sphere.disease"
VARIANTS = [
    ("tianxia.sphere.yin", "TAL_YIN_MARKING_A_CREATURE#withdrawing_thread"),
    ("tianxia.sphere.yang", "TAL_YANG_APPLYING_A_RISING_MARK#rising_thread"),
]
PRINTED = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_bytes())


def _assert_binding(row):
    binding = MECHANICS[row["talent_id"]]["source"]
    assert row["source"]["source_hash"] == binding["text_sha256"]
    assert row["source"]["path"] == binding["path"]
    assert row["record_hash"] == binding["text_sha256"]


@pytest.mark.parametrize("sphere", ["yin", "yang", "wax"])
def test_table_unrelated_design_checks_saves_and_reloads_with_all_known_sources(tmp_path, sphere):
    service = _service(tmp_path, [DISEASE_SPHERE, "tianxia.sphere." + sphere])
    offered = {row["id"] for row in service.advancement(PID)["forge"]["sources"]}
    design = _design(DISEASE, None)
    checked = service.forge(PID, design)
    saved = service.forge(PID, design, save=True)
    assert saved["technique"] == checked["technique"]
    cold = growth_service(tmp_path)
    sheet = cold.combat._factory_owner_sheet(PID)
    [technique] = sheet["forged_techniques"]
    assert technique == saved["technique"]
    known = {row["talent_id"]: row for row in technique["construction"]["request"]["known_talents"]}
    assert offered == known.keys()  # no silent dropping/renaming of difficult rows
    for row in known.values():
        _assert_binding(row)
    # Full source blocks, including Yang (6330) and Wax (4291), survive storage.
    for effect_id, row in known.items():
        assert row["published_text"] == PRINTED.get(effect_id, "").strip()
    assert mechanic_for(technique, MECHANICS)


@pytest.mark.parametrize("sphere", ["yin", "yang", "wax"])
def test_creation_unrelated_design_retains_known_sources_and_long_printed_text(tmp_path, sphere):
    # Version 3 keeps this explicit design unrelated: version 2 fills empty
    # selections with random secondaries/Augments, which may not fit Disease.
    concept = {**_design(DISEASE, None), "generator_version": 3}
    [(technique, record)] = _creation(
        [DISEASE_SPHERE, "tianxia.sphere." + sphere], concept, tmp_path)
    assert technique["secondary_sphere_effects"] == []
    assert technique["augments"] == []
    assert record["record_id"]
    known = technique["construction"]["request"]["known_talents"]
    assert any(row["sphere_id"] == "tianxia.sphere." + sphere for row in known)
    for row in known:
        _assert_binding(row)
        assert row["published_text"] == PRINTED.get(row["talent_id"], "").strip()
    if sphere in {"yang", "wax"}:
        [long_row] = [row for row in known if row["talent_id"] == "TAL_" + sphere.upper() + "_BASE_SPHERE_ABILITIES"]
        assert len(long_row["published_text"]) > 4000
    assert validate_forged_technique_record(build_forged_technique_record(technique), root_dir=ROOT) == technique


@pytest.mark.parametrize("sphere,effect_id", VARIANTS)
@pytest.mark.parametrize("slot", ["primary", "secondary"])
def test_table_selected_variant_keeps_exact_identity_through_save_reload_and_compile(tmp_path, sphere, effect_id, slot):
    service = _service(tmp_path, [DISEASE_SPHERE, sphere])
    offered = {row["id"] for row in service.advancement(PID)["forge"]["sources"]}
    assert effect_id in offered
    design = _design(effect_id, DISEASE) if slot == "primary" else _design(DISEASE, effect_id)
    checked = service.forge(PID, design)
    saved = service.forge(PID, design, save=True)
    assert checked["technique"] == saved["technique"]
    [technique] = growth_service(tmp_path).combat._factory_owner_sheet(PID)["forged_techniques"]
    selected = technique["primary_sphere_effect"] if slot == "primary" else technique["secondary_sphere_effects"][0]
    assert selected["talent_id"] == effect_id
    assert selected["source"]["source_hash"] == MECHANICS[effect_id]["source"]["text_sha256"]
    assert mechanic_for(technique, MECHANICS)


@pytest.mark.parametrize("sphere,effect_id", VARIANTS)
@pytest.mark.parametrize("slot", ["primary", "secondary"])
def test_creation_selected_variant_compiles_with_original_binding(tmp_path, sphere, effect_id, slot):
    design = _design(effect_id, DISEASE) if slot == "primary" else _design(DISEASE, effect_id)
    [(technique, _)] = _creation([DISEASE_SPHERE, sphere], design, tmp_path)
    selected = technique["primary_sphere_effect"] if slot == "primary" else technique["secondary_sphere_effects"][0]
    assert selected["talent_id"] == effect_id
    assert selected["source"]["source_hash"] == MECHANICS[effect_id]["source"]["text_sha256"]
    assert validate_forged_technique_record(build_forged_technique_record(technique), root_dir=ROOT) == technique
    assert mechanic_for(technique, MECHANICS)


def test_every_offered_yin_yang_variant_is_accepted_in_both_concept_slots(tmp_path):
    service = _service(tmp_path, [DISEASE_SPHERE, *[sphere for sphere, _ in VARIANTS]])
    sheet = service.combat._factory_owner_sheet(PID)
    request = forge_request(sheet, _design(DISEASE, None), [], project_id=PID)
    normalized = normalize_forged_technique_request(request)
    offered = {row["id"] for row in service.advancement(PID)["forge"]["sources"]}
    variants = [row for row in normalized["known_talents"] if "#" in row["talent_id"]]
    assert len(variants) >= 15
    for row in variants:
        _assert_binding(row)
        assert row["talent_id"] in offered
        for slot in ("primary", "secondary"):
            selected = deepcopy(request)
            selected["concept"] = (_design(row["talent_id"], DISEASE) if slot == "primary"
                                   else _design(DISEASE, row["talent_id"]))
            assert normalize_forged_technique_request(selected)["concept"] == {
                **selected["concept"], "intent": None, "augment_ids": [], "drawback_ids": []}


def test_effect_contract_does_not_relax_other_ids_or_free_text_limits(tmp_path):
    service = _service(tmp_path, [DISEASE_SPHERE])
    request = forge_request(service.combat._factory_owner_sheet(PID), _design(DISEASE, None), [], project_id=PID)
    for mutation in ("path", "form", "intent", "malformed_variant", "oversized_source", "control_character"):
        invalid = deepcopy(request)
        if mutation == "path":
            invalid["path_id"] += "#variant"
        elif mutation == "form":
            invalid["concept"]["base_form"] += "#variant"
        elif mutation == "intent":
            invalid["concept"]["intent"] = "x" * 4001
        elif mutation == "malformed_variant":
            invalid["known_talents"][0]["talent_id"] += "#bad#variant"
        elif mutation == "oversized_source":
            invalid["known_talents"][0]["published_text"] = "x" * 16_001
        else:
            invalid["known_talents"][0]["published_text"] = "source\x00text"
        with pytest.raises(FoundryError) as rejected:
            normalize_forged_technique_request(invalid)
        assert rejected.value.code == "FORGED_TECHNIQUE_REQUEST_INVALID"
