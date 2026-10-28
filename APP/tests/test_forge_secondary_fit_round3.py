"""Round 3: exercise the real Forge producers and mounted edit handlers, offline."""
from copy import deepcopy
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from combat.forged import fit_table, mechanic_for, secondary_fit
from combat.tabletop import TabletopError
from character_creation.service import CharacterCreationExecutionService
from tests.test_forge_secondary_fit import MECHANICS, PRIMARY, SELF_MOVE, rules
from tests.test_grow1_abilities import PID, ROOT, growth_service, installed_sheet
from tests.test_grow1_respec_review import seal

DISEASE = "DISEASE_BASE_SOW_THE_FEVER_SEED"
POISON = "POISON_BASE_DELIVER_THE_DOSE"
IGNITE = "FIRE_BASE_IGNITE"
FIRE_SPHERE = "tianxia.sphere.fire"
SPHERES = ["tianxia.sphere.disease", "tianxia.sphere.poison"]


def _service(root, spheres=SPHERES):
    sheet = installed_sheet()
    sheet["identity"].update(cultivation_level=6, proficiency_bonus=3)
    sheet["spheres_and_talents"] = {"sphere_record_ids": list(spheres)}
    seal(root, sheet)
    service = growth_service(root)
    service._spheres_cache = dict(zip(SPHERES, ["Disease", "Poison"]))
    return service


def _design(primary=DISEASE, secondary=POISON):
    return {"name": "Fever Dose", "base_form": "strike", "primary_talent_id": primary,
            "secondary_talent_ids": [secondary] if secondary else []}


def test_table_dropdown_choices_check_save_and_reload_with_source_bindings(tmp_path):
    service = _service(tmp_path, [*SPHERES, FIRE_SPHERE])
    forge = service.advancement(PID)["forge"]
    sources = {row["id"]: row for row in forge["sources"]}
    assert {DISEASE, POISON} <= sources.keys()
    assert sources[DISEASE]["kind"] == sources[POISON]["kind"] == "base_ability"
    assert sources[DISEASE]["sphere"] == "Disease"
    assert sources[POISON]["sphere"] == "Poison"
    # The exact requested pair now reaches design validation, rather than
    # failing "unknown source". Its source-specific Poison save is deliberately
    # not portable; the ordinary Secondary list hides it with that reason.
    with pytest.raises(TabletopError) as rejected:
        service.forge(PID, _design())
    assert rejected.value.code == "FORGING_DESIGN_REJECTED"
    checked = service.forge(PID, _design(DISEASE, IGNITE))
    saved = service.forge(PID, _design(DISEASE, IGNITE), save=True)
    assert saved["technique"] == checked["technique"]
    cold = growth_service(tmp_path)
    [entry] = cold.advancement(PID)["added"]["forged"]
    assert entry["technique_id"] == saved["technique"]["technique_id"]
    sheet = cold.combat._factory_owner_sheet(PID)
    [technique] = sheet["forged_techniques"]
    assert technique["primary_sphere_effect"]["talent_id"] == DISEASE
    assert technique["secondary_sphere_effects"][0]["talent_id"] == IGNITE
    request = technique["construction"]["request"]
    rows = {row["talent_id"]: row for row in request["known_talents"]}
    for effect_id in (DISEASE, POISON):
        assert rows[effect_id]["source"]["source_hash"] == MECHANICS[effect_id]["source"]["text_sha256"]
        assert rows[effect_id]["source"]["path"] == MECHANICS[effect_id]["source"]["path"]
        assert rows[effect_id]["published_text"]
    # A supported base-effect design compiles after the real commit + reload.
    assert mechanic_for(technique, MECHANICS)
    bundle = compile_character(sheet, actor_id="actor:factory." + PID)
    actions = bundle["action_catalog"]
    rows = actions.values() if isinstance(actions, dict) else actions
    assert any((row if isinstance(row, dict) else row.model_dump())["display_name"] == "Fever Dose" for row in rows)


@pytest.mark.parametrize("spheres,missing", [([], DISEASE), ([SPHERES[1]], DISEASE), ([SPHERES[0]], POISON)])
def test_unknown_sphere_base_effect_is_absent_and_cannot_be_forged(tmp_path, spheres, missing):
    service = _service(tmp_path, spheres)
    assert missing not in {row["id"] for row in service.advancement(PID)["forge"]["sources"]}
    with pytest.raises(TabletopError):
        service.forge(PID, _design())


def test_poison_source_bound_save_is_hidden_for_all_forms_after_reload(tmp_path):
    service = _service(tmp_path)
    service.forge(PID, _design(DISEASE, None), save=True)
    for current in (service, growth_service(tmp_path)):
        table = current.advancement(PID)["forge"]["fit"]
        for form_id in rules()["forms"]:
            fits, reason = table[form_id][POISON]
            assert not fits
            assert "Constitution save" in reason and "Dose Mark" in reason
            assert "Disadvantage" in reason
    # Real Primary + candidate receives the same refusal, not only a probe.
    fits, reason = secondary_fit("strike", DISEASE, POISON, MECHANICS)
    assert not fits and "forged delivery" in reason


@pytest.mark.parametrize("form", ["ward", "movement"])
def test_extracted_ally_modifier_dropped_by_delivery_is_not_offered(form):
    from combat.forged import payload
    assert payload(MECHANICS[SELF_MOVE])["effects"]
    technique = {"name": "Probe", "base_form": {"form_id": form},
                 "primary_sphere_effect": {"talent_id": PRIMARY},
                 "secondary_sphere_effects": [{"talent_id": SELF_MOVE}]}
    before = deepcopy(MECHANICS[SELF_MOVE])
    combined = mechanic_for(technique, MECHANICS)
    solo = mechanic_for({**technique, "secondary_sphere_effects": []}, MECHANICS)
    assert combined["effects"] == solo["effects"]  # concrete discarded payload
    fits, reason = secondary_fit(form, PRIMARY, SELF_MOVE, MECHANICS)
    assert not fits and "drops" in reason
    assert not fit_table([SELF_MOVE], MECHANICS)[form][SELF_MOVE][0]
    assert MECHANICS[SELF_MOVE] == before
    assert "_forge_fit_probe" not in json.dumps(combined)


def test_saved_talent_technique_keeps_its_existing_combat_payload():
    # Expected legacy tree comes directly from these public printed mechanics,
    # not from a second call to the compiler being tested.
    saved = {"name": "Old Flame and Ash", "base_form": {"form_id": "strike"},
             "primary_sphere_effect": {"talent_id": PRIMARY},
             "secondary_sphere_effects": [{"talent_id": "ASH_TAL_ASHEN_BURIAL"}]}
    primary_hits = deepcopy(MECHANICS[PRIMARY]["effects"][0]["on_hit"])
    ash = deepcopy(MECHANICS["ASH_TAL_ASHEN_BURIAL"]["effects"][0]["on_fail"])
    expected = [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": [
        primary_hits[0],
        {"type": "save", "ability": "str", "dc": "technique_save_dc",
         "on_fail": [*primary_hits[1:], *ash], "on_success": []},
    ]}]
    assert mechanic_for(saved, MECHANICS)["effects"] == expected
    fit_table(["ASH_TAL_ASHEN_BURIAL", SELF_MOVE, POISON], MECHANICS)
    assert mechanic_for(saved, MECHANICS)["effects"] == expected


def _creation(spheres, concept, tmp_path):
    service = object.__new__(CharacterCreationExecutionService)
    service.db = SimpleNamespace(settings=SimpleNamespace(root_dir=ROOT, vendor_dir=tmp_path))
    path = "tianxia.path.qi_cultivation"
    records = {path: {"content_type": "path"}}
    records.update({sid: {"content_type": "sphere", "display_name": sid.split(".")[-1].title()} for sid in spheres})
    rows = [{"kind": "path_acquisition", "record_id": path}]
    rows += [{"kind": "background_sphere_acquisition", "record_id": sid} for sid in spheres]
    return service._forged_technique_constructions(
        {"project_id": "synthetic-forger"}, {}, {"acquisition_intent": {"forged_technique_concepts": [concept]}},
        rows, records, 6, intent_hash="a" * 64)


def test_creation_service_produces_base_sources_for_both_effect_slots(tmp_path):
    for primary, secondary in ((DISEASE, IGNITE), (IGNITE, DISEASE)):
        [(technique, record)] = _creation([*SPHERES, FIRE_SPHERE], _design(primary, secondary), tmp_path)
        assert technique["primary_sphere_effect"]["talent_id"] == primary
        assert technique["secondary_sphere_effects"][0]["talent_id"] == secondary
        assert record["record_id"]
        known = {row["talent_id"]: row for row in technique["construction"]["request"]["known_talents"]}
        for effect_id in (DISEASE, POISON, IGNITE):
            assert known[effect_id]["source"]["source_hash"] == MECHANICS[effect_id]["source"]["text_sha256"]
        with pytest.raises(FoundryError):
            _creation([MECHANICS[primary]["sphere_id"]], _design(primary, secondary), tmp_path)
    with pytest.raises(FoundryError) as rejected:
        _creation(SPHERES, _design(), tmp_path)
    assert rejected.value.details["cause"] == "FORGING_DESIGN_REJECTED"


def test_mounted_forge_edits_preserve_controls_and_ui_state(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    candidates = [key for key, row in MECHANICS.items() if row.get("kind") == "talent" and row.get("effects")][:60]
    candidates = sorted(set(candidates + [PRIMARY, SELF_MOVE, DISEASE, POISON]))
    forms = [dict(row, form_id=key, display_name=key.title(), complexity=1)
             for key, row in rules()["forms"].items()]
    sources = [{"id": key, "name": MECHANICS[key]["name"], "kind": MECHANICS[key]["kind"],
                "sphere_id": MECHANICS[key]["sphere_id"], "sphere": MECHANICS[key]["sphere_id"]} for key in candidates]
    fixture = {"available": True, "forms": forms, "sources": sources, "max_spheres": 3,
               "max_complexity": 6, "sphere_complexity": 1, "fit": fit_table(candidates, MECHANICS),
               "augments": [{"augment_id": "major_condition", "complexity": 2, "legal": True}],
               "drawbacks": [], "choices": {"major_condition": ["blinded", "restrained"]}}
    fixture_path = tmp_path / "forge.json"
    fixture_path.write_text(json.dumps(fixture))
    run = subprocess.run([node, str(ROOT / "tests/forge_mounted_edits.mjs"),
                          str(ROOT / "static/tabletop/grow.js"), str(fixture_path)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "mounted Forge edits: PASS" in run.stdout
