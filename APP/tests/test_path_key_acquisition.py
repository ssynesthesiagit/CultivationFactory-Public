"""The permanent Path pick and the sheet numbers it actually controls."""
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core import FoundryError
from character_creation.creative_controller.linear_assembly import build_response
from character_creation.creative_controller.linear_menus import CommittedState, _ability_priority, build_step_menu
from character_creation.creative_controller.linear_walk import commit_option, next_step
from character_creation.service import CharacterCreationExecutionService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from non_sphere_authority.service import NonSphereAuthorityService
from path_keys import CHOICE_FIELD, acquisition_key, event_key, path_key_options, path_record_authority, sheet_key
from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class
from stage2.formulas import evaluate_formula
from stage2.service import RulesCausalStage2Service, _canonical_event_details, _state

ROOT = Path(__file__).resolve().parents[1]
BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
SPIRIT = "tianxia.path.spirit_awakening"
UNARMORED = BODY + ".feature.unarmored_defense"
PID = "ba5eb011-0000-4000-8000-000000000001"


def _walk_input(record):
    path_id = record["record_id"]
    authority = path_record_authority(record)
    envelope = {
        "choices_by_slot": {"path_choice": [{"id": path_id, "display_name": record["display_name"]}]},
        "typed_choice_authority_by_slot": {"path_choice": {"stage2_authority_by_choice": {
            path_id: {"key_ability_options": authority["key_ability_options"]}}}},
    }
    request = {"request_sha256": "a" * 64, "delegated_choice_envelope": envelope,
               "bounded_choice_contract": {"fields": {CHOICE_FIELD: {"options_by_path_id": {
                   path_id: authority["key_ability_options"]}}}}}
    state = CommittedState(by_slot={"path_choice": [path_id]}).with_identity(
        "Still Reed", "Winter Disciple", "A cultivator testing a new path.")
    return request, envelope, state


def _install(tmp_path, document):
    package = tmp_path / "portable_characters" / PID / "current.zip"
    package.parent.mkdir(parents=True)
    with ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    return package


@pytest.mark.parametrize("path_id,key,modifier,base", [
    (BODY, "STR", 2, 8),
    (BODY, "DEX", 3, 12),
    (BODY, "CON", 1, 4),
    (BODY, "STR", -1, 0),
    (QI, "CHA", 4, 16),
])
def test_creation_pick_round_trips_into_path_statistics_and_combat(tmp_path, path_id, key, modifier, base):
    record = NonSphereAuthorityService(root_dir=ROOT).project_locked_path_catalog_record(path_id)
    authority = path_record_authority(record)
    request, envelope, state = _walk_input(record)
    step_id = f"path_key_ability:{path_id}"
    step = next_step(request, envelope, state)
    assert step.step_id == step_id
    options = {option.choice_ids[0]: option.option_id for option in step.menu.options if not option.is_continuation}
    assert tuple(options) == (("STR", "DEX", "CON") if path_id == BODY else ("INT", "CHA"))
    chosen = commit_option(step.menu, options[key], step.committed)
    assert _ability_priority(chosen, request, envelope)[0] == key
    assert build_step_menu(request, envelope, chosen, step_id=step_id) is None
    with pytest.raises(FoundryError, match="cannot change"):
        commit_option(step.menu, next(option for code, option in options.items() if code != key), chosen)

    parsed, _ = CharacterCreationExecutionService._parse_plan(build_response(request, chosen))
    assert parsed["bounded_choices"][CHOICE_FIELD] == {path_id: key}
    picked = acquisition_key(path_id, authority, parsed["bounded_choices"][CHOICE_FIELD][path_id])
    event = {"event_id": "path-event", "subject": {"record_id": path_id}, "advancement": {
        "kind": "path_acquisition", "target_cl": 1,
        "details": _canonical_event_details("path_acquisition", {"key_ability": picked}),
        "calculation": {"outputs": {}}}}
    event = json.loads(json.dumps(event))
    assert event_key(event, authority) == key

    stage2 = object.__new__(RulesCausalStage2Service)
    state = stage2._apply_event(_state(PID), event)
    mods = {"STR": 2, "DEX": 3, "CON": 1, "INT": 0, "WIS": 0, "CHA": 4, key: modifier}
    scores = {a: 10 + 2 * mod for a, mod in mods.items()}
    state.update(ability_modifiers=mods, ability_scores=scores)
    pools, _, _ = stage2._resource_recalculation(None, PID, state, cl=4, pb=2, path=record, _single_native_path=True)
    resource = next(iter(pools.values()))
    assert resource["base_value"] == resource["maximum"] == base
    hp = 0
    for cl in range(1, 5):
        total, _, _ = stage2._hp_calculation(state, record, cl, previous_total=hp, pb=2)
        hp = total["total"]
    assert hp == (37 if path_id == BODY else 27)

    baseline = {"rule_id": "baseline", "formula": {"formula_id": "bare", "root": {"op": "add", "terms": [
        {"op": "constant", "value": 10}, {"op": "ability_modifier", "ability": "DEX"}]}}}
    context = {**stage2._formula_context(state, 4, 2), "path_key_abilities": state["path_key_abilities"]}
    bare = evaluate_formula(baseline["formula"]["root"], context)
    features = [UNARMORED] if path_id == BODY else []
    ac = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), features, baseline_rule=baseline,
                             baseline_value=bare.value, baseline_trace=bare.trace, context=context)
    if path_id == BODY:
        assert ac["ac_generation"]["alternatives_considered"][1]["value"] == 10 + modifier + 2

    name = "Stamina" if path_id == BODY else "Qi"
    document = {
        "identity": {"display_name": "Still Reed", "path_id": path_id, "path": record["display_name"],
                     "key_ability": key, "cultivation_level": 4, "proficiency_bonus": 2},
        "path_and_subpath": {"path_feature_record_ids": features},
        "spheres_and_talents": {},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": scores[a], "modifier": m} for a, m in mods.items()],
            "armor_class": {"base_value": ac["ac_base"], "value": ac["ac_active"], "generation": ac["ac_generation"]},
            "hit_points": {"maximum": hp}, "primary_resource": {"name": name, "maximum": resource["maximum"]},
            "technique_attack_bonus": 2 + mods[key], "technique_save_dc": 10 + mods[key], "speed": {"walking_ft": 30},
        },
    }
    _install(tmp_path, document)
    sheet = CombatService(ROOT, tmp_path)._factory_installed_sheet(PID)
    actor = compile_character(sheet, actor_id="actor:factory.path-key-test")["actor_template"]
    expected_ac = max(13, 10 + modifier + 2) if path_id == BODY else 13
    assert actor["armor_class"] == expected_ac
    assert actor["maximum_hp"] == hp
    assert actor["saving_throws"]["CON"] == 1
    assert next(pool["maximum"] for pool in actor["resources"] if pool["resource_id"] == f"resource:core.{name.lower()}") == base


def test_legacy_key_backfill_is_persisted_and_readers_do_not_guess(tmp_path):
    raw = {"identity": {"path_id": BODY, "display_name": "Old Reed"}}
    package = _install(tmp_path, raw)
    original = package.read_bytes()
    loaded = CombatService(ROOT, tmp_path)._factory_installed_sheet(PID)
    patch = package.with_name("sheet-path-key-migration.json")
    assert sheet_key(loaded) == "CON"
    assert json.loads(patch.read_bytes())["path_keys"] == {BODY: "CON"}
    stamp = patch.stat().st_mtime_ns
    assert sheet_key(CombatService(ROOT, tmp_path)._factory_installed_sheet(PID)) == "CON"
    assert patch.stat().st_mtime_ns == stamp
    assert package.read_bytes() == original
    del loaded["identity"]["key_ability"]
    loaded["ability_scores_and_statistics"] = {}
    with pytest.raises(FoundryError) as error:
        compile_character(loaded, actor_id="actor:factory.path-key-test")
    assert error.value.code == "PATH_KEY_ABILITY_MISSING"


def test_path_indexes_are_the_only_option_authority():
    master = ROOT / "non_sphere_authority/authority/Tianxia_Path_Index_Master_P2A.json"
    assert all("key_ability" not in entry for entry in json.loads(master.read_text())["paths"])
    service = NonSphereAuthorityService(root_dir=ROOT)
    for path_id, expected in ((BODY, ("STR", "DEX", "CON")), (QI, ("INT", "CHA")), (SPIRIT, ("WIS",))):
        record = service.project_locked_path_catalog_record(path_id)
        request, envelope, selected = _walk_input(record)
        authority = path_record_authority(record)
        assert "key_ability" not in authority
        assert tuple(authority["key_ability_options"]) == path_key_options(path_id) == expected
        if len(expected) == 1:
            assert build_step_menu(request, envelope, selected, step_id=f"path_key_ability:{path_id}") is None
            assert acquisition_key(path_id, authority) == expected[0]
        else:
            with pytest.raises(FoundryError) as error:
                acquisition_key(path_id, authority)
            assert error.value.code == "PATH_KEY_ABILITY_MISSING"
    for path in ("character_creation/constructed_arts/immortal_art.py",
                 "character_creation/creative_controller/linear_menus.py", "character_creation/service.py",
                 "factory_authoring/final_compiler/compile_character_v2.py"):
        text = (ROOT / path).read_text()
        assert all(name not in text for name in ("_ABILITY_BY_PATH", "_PATH_DEFAULT_KEY_ABILITY", '"key_abilities": {'))
