"""Creation policy and the owner's Poison-Hunger Projection at table level."""
from copy import deepcopy

import pytest

from character_creation.constructed_arts.forge_design import POLICY, design_issues, restructure
from tests.test_mmx107_forged_button_text import _compiled_typed, _fight, _technique


def saved(rows, ability="con"):
    return {"type": "save", "ability": ability, "dc": "technique_save_dc", "on_fail": rows, "on_success": []}


SLOW = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn"}
STUN = {"type": "condition", "condition": "stunned", "applies_to": "target",
        "duration": "until_end_of_next_turn", "repeat_save": {"ability": "CON", "when": "end"}}


def test_owner_chain_becomes_one_save_without_mutating_source():
    before = {"effects": [{"type": "attack", "on_hit": [saved([SLOW]), saved([STUN])]}],
              "cost": [[{"amount": 4}]]}
    original = deepcopy(before)
    assert design_issues(before) == ["independent_rider_gates", "stacked_gates"]
    after = restructure(before)
    assert not design_issues(after)
    assert after["effects"] == [saved([SLOW, STUN])]
    assert before == original
    assert restructure(after) == after


@pytest.mark.parametrize("mechanic,issue", [
    ({"effects": [{"type": "attack", "on_hit": [saved([SLOW])]}]}, "stacked_gates"),
    ({"effects": [{"type": "attack", "on_hit": [{"type": "sphere_check", "on_success": [SLOW]}]}]}, "stacked_gates"),
    ({"effects": [saved([SLOW]), saved([STUN])]}, "independent_rider_gates"),
    ({"effects": [saved([{**STUN, "repeat_save": None}])]}, "severe_without_recovery"),
    ({"effects": [saved([{**STUN, "duration": None}])]}, "severe_without_expiry"),
    ({"effects": [], "cost": [[{"amount": 4}]]}, "no_primary_payoff"),
    ({"effects": [saved([SLOW])], "cost": [[{"amount": 4}]]}, "weak_paid_payoff"),
])
def test_validator_rules(mechanic, issue):
    assert issue in design_issues(mechanic)


def test_damage_projection_keeps_attack_and_complex_sources_are_not_flattened():
    damage = {"effects": [{"type": "attack", "on_hit": [{"type": "damage", "flat": 8}]}]}
    assert restructure(damage) == damage
    complex_ = {"effects": [{"type": "attack", "on_hit": [{**saved([SLOW]), "requires_mark": True}]}]}
    assert restructure(complex_) == complex_
    assert "stacked_gates" in design_issues(complex_)


def test_save_success_keeps_partial_damage_and_self_cost_separate():
    damage = {"type": "damage", "flat": 8, "applies_to": "target"}
    cost = {"type": "damage", "flat": 2, "applies_to": "self"}
    after = restructure({"effects": [saved([damage]), saved([STUN]), cost]})
    assert after["effects"][0]["on_success"] == [{"type": "half_damage", "applies_to": "target"}]
    assert after["effects"][1] == cost
    assert not design_issues(after)


def test_mixed_ally_and_enemy_save_branches_are_rejected_not_combined():
    healing = {"type": "healing", "flat": 5, "applies_to": "ally"}
    before = {"effects": [saved([healing]), saved([SLOW])]}
    assert restructure(before) == before
    assert "independent_rider_gates" in design_issues(before)
    attacked = {"effects": [{"type": "attack", "on_hit": [healing, saved([SLOW])]}]}
    assert restructure(attacked) == attacked
    assert "stacked_gates" in design_issues(attacked)


def test_counter_keeps_one_gate_after_borrowing_primary_reaction():
    from combat.forged import as_reaction, mechanic_for
    source = {"mechanic_id": "test:reaction", "activation": {"economy": "reaction", "trigger": "A creature hits you"},
              "effects": [saved([SLOW])]}
    technique = _technique("Poison Counter", "counter", 4, talent="test:reaction", augments=("severe_hindrance",))
    technique.update(action_type="reaction", design_policy=POLICY)
    mechanics = {"test:reaction": source}
    action = mechanic_for(technique, mechanics)
    reaction = as_reaction(technique, action, mechanics)
    assert reaction["activation"]["trigger"] == source["activation"]["trigger"]
    assert not design_issues(reaction)
    assert [r["type"] for r in reaction["effects"]] == ["save"]


def test_owner_projection_table_button_has_one_gate_and_meaningful_payoff(tmp_path, monkeypatch):
    from tests import test_mmx107_forged_button_text as fixture
    original_sheet = fixture.sheet

    def body_sheet(*args, **kwargs):
        doc = original_sheet(*args, **kwargs, primary="Stamina")
        doc["identity"]["path"] = "Body Refining"
        return doc

    monkeypatch.setattr(fixture, "sheet", body_sheet)
    talent = "tianxia.talent.poison.coated_weapon"
    technique = _technique("Poison-Hunger Projection", "projection", 4, talent=talent,
                           augments=("minor_hindrance", "severe_hindrance", "mobility_rider"))
    technique["action_type"] = "action"
    technique["design_policy"] = POLICY
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[technique])
    from tests.test_mmx107_forged_button_text import _button, _compiled_typed
    text = _button(table, mid, "Poison-Hunger Projection")
    assert "Stunned" in text
    assert "10 feet" in text
    assert "On a hit" not in text
    assert text.count("makes a Constitution saving throw") == 1
    assert "4 Stamina" in text
    typed = _compiled_typed(combat, mid, "Poison-Hunger Projection")
    assert typed["effects"][0]["type"] == "save"
    assert not design_issues(typed)
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    reloaded = CombatService(ROOT, tmp_path)
    assert _compiled_typed(reloaded, mid, "Poison-Hunger Projection")["effects"] == typed["effects"]


def test_constructor_rejects_a_bad_design_before_making_a_record(monkeypatch):
    from app.core import FoundryError
    from character_creation.constructed_arts import forged_technique as composer
    from tests.test_constructed_forged_techniques import _request
    from character_creation.constructed_arts.forging_authority import load_forging_authority
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    request = _request(concept={"primary_talent_id": "TAL_BRUTE_BREAK_DEFENSES", "base_form": "projection",
                                "augment_ids": ["minor_hindrance", "extended_range", "mobility_rider"], "secondary_talent_ids": [], "drawback_ids": []})
    monkeypatch.setattr(composer, "design_mechanics", lambda: {"TAL_BRUTE_BREAK_DEFENSES": {
        "effects": [saved([SLOW])], "range": {"kind": "feet", "feet": 60}}})
    with pytest.raises(FoundryError) as error:
        composer.construct_forged_technique(load_forging_authority(root), request, generator_version=3)
    assert error.value.code == "FORGING_DESIGN_REJECTED"
    assert "weak_paid_payoff" in error.value.details["issues"]


def test_audit_scores_all_admitted_representative_foundation_designs_clean():
    from tools.forge_design_audit import audit_generated
    result = audit_generated(cls=(5,))
    assert result["produced"] > 0
    assert result["rejected"] > 0
    assert result["failures"] == []
    assert set(result["scores"]) == {"100"}


def test_bad_automatic_draft_falls_back_deterministically_and_rederives(monkeypatch):
    from app.core import FoundryError
    from character_creation.constructed_arts import forged_technique as composer
    from character_creation.constructed_arts.forging_authority import load_forging_authority
    from character_creation.constructed_arts.records import build_forged_technique_record, validate_forged_technique_record
    from tests.test_constructed_forged_techniques import _request, ROOT
    request = _request()
    before = deepcopy(request)
    mechanics = {t["talent_id"]: {"effects": [{"type": "damage", "flat": 8, "applies_to": "target"}],
                                  "range": {"kind": "feet", "feet": 60}} for t in request["known_talents"]}
    monkeypatch.setattr(composer, "design_mechanics", lambda: mechanics)
    validate = composer.validate_forged_design

    def reject_automatic_draft(technique):
        if not technique["construction"]["concept"]["primary_talent_id"]:
            raise FoundryError("FORGING_DESIGN_REJECTED", "Unusable random draft.")
        return validate(technique)

    monkeypatch.setattr(composer, "validate_forged_design", reject_automatic_draft)
    authority = load_forging_authority(ROOT)
    technique = composer.construct_forged_technique(authority, request)
    assert composer.construct_forged_technique(authority, request) == technique
    assert request == before
    assert technique["primary_sphere_effect"]["talent_id"] in mechanics
    assert validate_forged_technique_record(build_forged_technique_record(technique), root_dir=ROOT) == technique


def test_unmarked_legacy_record_still_rederives_exactly():
    from character_creation.constructed_arts.forged_technique import construct_forged_technique
    from character_creation.constructed_arts.forging_authority import load_forging_authority
    from character_creation.constructed_arts.records import build_forged_technique_record, validate_forged_technique_record
    from tests.test_constructed_forged_techniques import _request, ROOT
    technique = construct_forged_technique(load_forging_authority(ROOT), _request(), design_policy=None)
    assert "design_policy" not in technique
    assert validate_forged_technique_record(build_forged_technique_record(technique), root_dir=ROOT) == technique


def test_export_audit_proposes_a_repriced_known_source_without_changing_copy(tmp_path):
    import json
    from tools.forge_design_audit import audit_exports
    old = _technique("Weak Poison Projection", "projection", 4,
                     talent="tianxia.talent.poison.coated_weapon", augments=("minor_hindrance",))
    old["cl_created"] = 10
    path = tmp_path / "copied-sheet.json"
    path.write_text(json.dumps({"forged_techniques": [old]}))
    before = path.read_bytes()
    result = audit_exports([path])
    assert result["flagged_count"] == 1
    proposed = result["flagged"][0]["alternative_design"]
    assert proposed is not None
    assert proposed["primary_talent_id"] == old["primary_sphere_effect"]["talent_id"]
    assert not design_issues(proposed["mechanic"])
    assert path.read_bytes() == before


AURA_TEXT = ("A 10-foot aura around you for 1 minute (Concentration). It moves with you. "
             "A hostile creature that enters the area for the first time on a turn or starts its turn there "
             "makes a saving throw.")


def test_restructure_keeps_aura_zone_and_persistent_timing_words():
    """The form's timing words are executable inputs (factory_compiler._zone_spec), not flavor."""
    zones = [
        {"description": [AURA_TEXT]},
        {"description": ["A 20-foot-radius zone for 1 minute (Concentration). "
                         "A hostile creature that enters the area for the first time on a turn or starts its turn "
                         "there makes a saving throw."]},
        {"description": ["Enemies in a 15-foot radius make a saving throw.",
                         "The area remains for 1 minute (Concentration). A hostile creature that enters the area "
                         "for the first time on a turn or starts its turn there makes the saving throw again."]},
    ]
    for mechanic in zones:
        mechanic = {**mechanic, "effects": [saved([{"type": "damage", "flat": 8, "applies_to": "target"}])]}
        after = restructure(mechanic)
        assert after["description"] == mechanic["description"]
        assert [row["type"] for row in after["effects"]] == ["save"]


def test_restructure_still_replaces_a_converted_attack_text():
    attacked = {"effects": [{"type": "attack", "on_hit": [saved([SLOW])]}],
                "description": ["A ranged technique attack; on a hit, the Primary Sphere Effect."]}
    after = restructure(attacked)
    assert after["description"] == ["The target makes one saving throw against your Cultivation Save DC. "
                                    "On a failure, apply the technique's effects together; on a success, take half damage if any."]
    assert "attack" not in " ".join(after["description"]).lower()


@pytest.mark.parametrize("form,augments,follows", [
    ("aura", (), True),
    ("zone", (), False),
    ("burst", ("persistent_zone",), False),
])
def test_marked_record_keeps_persistent_area_triggers_and_reload(tmp_path, form, augments, follows):
    """A marked Aura/Zone/Burst + Persistent Zone still compiles to a lasting area:
    a creation save, recurring enter/start triggers, following, and a reload."""
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    label = "Marked Recurring Gale"
    technique = _technique(label, form, 4, talent="TAL_AIR_DOWNBURST_SEAL", augments=augments)
    technique["design_policy"] = POLICY
    combat, table, mid = _fight(tmp_path, talents=["TAL_AIR_DOWNBURST_SEAL"], forged=[technique])
    typed = _compiled_typed(combat, mid, label)
    spec = typed["zone_spec"]
    assert spec["triggers"]
    assert all(trigger["on"] == ["enter", "start"] and trigger["who"] == "hostile" for trigger in spec["triggers"])
    assert spec["follows_owner"] is follows
    assert typed["effects"][0]["type"] == "save" and not design_issues(typed)
    reloaded = CombatService(ROOT, tmp_path)
    assert _compiled_typed(reloaded, mid, label)["zone_spec"] == spec


def test_marked_aura_places_area_repeats_save_and_reloads(tmp_path):
    """The whole path at the table: the marked aura creates the area, its save
    repeats when a hostile creature starts its turn inside, and the area itself
    survives a commit/reload with its following flag."""
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT, script
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import RIGHT
    label = "Marked Recurring Gale"
    technique = _technique(label, "aura", 4, talent="TAL_AIR_DOWNBURST_SEAL")
    technique["design_policy"] = POLICY
    combat, table, mid = _fight(tmp_path, talents=["TAL_AIR_DOWNBURST_SEAL"], forged=[technique])
    engine = combat._load_session(mid).engine
    script(engine, [1])  # the aura's creation save fails against the adjacent foe
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"]
                 if ".forged." in g["source_definition_id"] and g["label"] == label)
    from tests.iron_fist_support import answering_iron_fist
    result = answering_iron_fist(lambda answers: table.act(
        mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
        state["last_sequence"], answers))()
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    zone = next(z for z in loaded.engine.state.zones.values() if z.trigger_profile.get("name") == label)
    assert zone.active and zone.trigger_profile.get("follows_owner") is True
    assert all(trigger["on"] == ["enter", "start"] for trigger in zone.trigger_profile["triggers"])
    # The save repeats on a hostile creature's later turn start, not only at creation.
    def repeated(events):
        return [e for e in events if e.event_type == "PASSIVE_TRIGGERED"
                and e.payload.get("moment") == "start" and e.payload.get("trigger") == label]
    for _ in range(8):
        if repeated(combat._load_session(mid).engine.events):
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    else:
        raise AssertionError("the marked aura never repeated its save on a later turn start")
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert repeated(reloaded.engine.events)
    still = next(z for z in reloaded.engine.state.zones.values() if z.trigger_profile.get("name") == label)
    assert still.active


def _converted_extra_damage_projection(tmp_path):
    """Sky-Cleaving Pressure carried by a marked Projection with a Forced Movement Augment:
    restructuring converts the attack into one save whose failure branch keeps the
    portable extra damage and promises half of it on a success."""
    talent = "TAL_AIR_SKY_CLEAVING_PRESSURE"
    label = "Pressure Projection"
    technique = _technique(label, "projection", 4, talent=talent, augments=("forced_movement",))
    technique["action_type"] = "action"
    technique["design_policy"] = POLICY
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[technique])
    typed = _compiled_typed(combat, mid, label)
    [row] = typed["effects"]
    assert row["type"] == "save"
    assert [effect["type"] for effect in row["on_fail"]] == ["extra_damage", "forced_movement"]
    assert row["on_success"] == [{"type": "half_damage", "applies_to": "target"}]
    return combat, table, mid, label, typed


def _use_forged(table, mid, label, target_id):
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"]
                 if ".forged." in g["source_definition_id"] and g["label"] == label)
    option = next(o for o in group["options"] if target_id in (o["target_ids"] or []))
    from tests.iron_fist_support import answering_iron_fist
    return answering_iron_fist(lambda answers: table.act(
        mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
        state["last_sequence"], answers))()


@pytest.mark.parametrize("natural,expect_half", [(1, False), (20, True)])
def test_converted_save_delivers_extra_damage_full_and_half_at_table(tmp_path, natural, expect_half):
    """The converted save's HP change matches its promise: the rolled extra damage
    in full on a failed save, half of the same roll on a successful one."""
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT, script
    from tests.test_tabletop_hunt6 import RIGHT
    combat, table, mid, label, typed = _converted_extra_damage_projection(tmp_path)
    engine = combat._load_session(mid).engine
    hp_before = engine.state.actors[RIGHT].current_hp
    d6s = (3, 4, 5, 4)
    script(engine, [natural, *d6s])
    result = _use_forged(table, mid, label, RIGHT)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"]
    assert saves and saves[-1].payload["success"] is expect_half
    dealt = hp_before - loaded.engine.state.actors[RIGHT].current_hp
    full = sum(d6s) + int(typed["numbers"]["pb"])
    assert dealt == (full // 2 if expect_half else full)
    assert loaded.mechanical.replay()["status"] == "PASS"
