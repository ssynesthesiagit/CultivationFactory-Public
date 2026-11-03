"""Powering Path Records (owner 2026-09-25, rulebook ruling Q19): a generic CP cost is paid from
the feature's recorded Powering Path — a Path feature always uses its own Path; otherwise, with
more than one Path pool, the player chooses which pool powers it."""

import pytest

from combat.factory_compiler import compile_character
from combat.tabletop import ButtonStore, TabletopError, normalize_powering

ACTOR = "actor:factory.powering"


def _mechanic(mechanic_id: str, name: str, cost: int, path_id: str | None = None) -> dict:
    return {
        "mechanic_id": mechanic_id, "name": name, "activation": {"economy": "action"},
        "effects": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"]}],
        "riders": [], "range": {"kind": "feet", "feet": 30}, "area": None,
        "duration": {"kind": "instant"}, "cost": [[{"resource": "cp", "amount": cost}]],
        **({"path_id": path_id} if path_id else {}),
    }


AUTHORITY = {"mechanics": {
    "TAL_GENERIC": _mechanic("TAL_GENERIC", "Sphere Trick", 3),
    "PATH_FEAT": _mechanic("PATH_FEAT", "Path Trick", 2, path_id="tianxia.path.spirit_awakening"),
}}

# Qi (primary, 24) and Resonance (44): a Spirit + Qi character, the owner's test case
# (Lianhui of the Flowing Grave).
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 24, "definitions": [{"name": "Resonance", "max": 44}]},
        "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30},
        "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["TAL_GENERIC"]},
    "path_and_subpath": {"path_feature_record_ids": ["PATH_FEAT"]},
}


def _cost_resource(bundle: dict, display_name: str) -> str:
    row = next(r for r in bundle["action_catalog"] if r["display_name"] == display_name)
    return row["costs"][0][0]


def test_two_pools_with_no_choice_pay_from_the_primary_pool():
    bundle = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY)
    assert bundle["powering"]["pools"] == ["Qi", "Resonance"]
    assert _cost_resource(bundle, "Sphere Trick") == "resource:core.qi"
    action_id = next(row["source_definition_id"] for row in bundle["action_catalog"] if row["display_name"] == "Sphere Trick")
    choice = bundle["powering"]["choices"][action_id]
    assert choice == {"name": "Sphere Trick", "pool": "Qi"}


def test_a_saved_choice_moves_the_sphere_talent_to_the_chosen_pool():
    plain = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY)
    action_id = next(row["source_definition_id"] for row in plain["action_catalog"] if row["display_name"] == "Sphere Trick")
    bundle = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY, powering={action_id: "resonance"})
    assert _cost_resource(bundle, "Sphere Trick") == "resource:core.resonance"
    assert bundle["powering"]["choices"][action_id]["pool"] == "Resonance"


def test_a_path_feature_always_uses_its_own_path_and_is_not_choosable():
    plain = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY)
    path_action_id = next(row["source_definition_id"] for row in plain["action_catalog"] if row["display_name"] == "Path Trick")
    assert _cost_resource(plain, "Path Trick") == "resource:core.resonance"
    assert path_action_id not in plain["powering"]["choices"]
    # Naming the wrong pool for it changes nothing: rule (1) overrides any saved choice.
    bundle = compile_character(SHEET, actor_id=ACTOR, typed_authority=AUTHORITY, powering={path_action_id: "qi"})
    assert _cost_resource(bundle, "Path Trick") == "resource:core.resonance"


def test_a_forged_technique_follows_the_saved_choice():
    technique = {"technique_id": "tianxia.constructed.forged_technique.test_powering", "name": "Channeled Strike",
                "action_type": "action", "primary_sphere_effect": {"talent_id": "TAL_GENERIC"}, "cp_cost": {"final": 5}}
    sheet = {**SHEET, "forged_techniques": [technique]}
    plain = compile_character(sheet, actor_id=ACTOR, typed_authority=AUTHORITY)
    assert _cost_resource(plain, "Channeled Strike") == "resource:core.qi"  # no choice made: primary pool
    forged_action_id = next(row["source_definition_id"] for row in plain["action_catalog"] if row["display_name"] == "Channeled Strike")
    assert plain["powering"]["choices"][forged_action_id] == {"name": "Channeled Strike", "pool": "Qi"}
    bundle = compile_character(sheet, actor_id=ACTOR, typed_authority=AUTHORITY, powering={forged_action_id: "resonance"})
    assert _cost_resource(bundle, "Channeled Strike") == "resource:core.resonance"


def test_button_store_round_trips_buttons_and_powering(tmp_path):
    store = ButtonStore(tmp_path)
    project_id = "aaaaaaaa"
    assert store.get(project_id) == {"schema": "TianxiaSheetButtons.v1", "buttons": [], "layout": {"hidden": [], "pinned": []},
                                     "powering": {}, "reactions": {}}
    store.save(project_id, {"buttons": [], "layout": {"hidden": ["x"], "pinned": []}}, known_ids=set())
    saved = store.save_powering(project_id, {"choices": {"act:a": "resonance"}}, {"act:a": ["qi", "resonance"]})
    assert saved["powering"] == {"act:a": "resonance"} and saved["layout"]["hidden"] == ["x"]  # buttons/layout preserved
    kept = store.save(project_id, {"buttons": [], "layout": {"hidden": [], "pinned": []}}, known_ids=set())
    assert kept["powering"] == {"act:a": "resonance"}  # saving buttons again keeps the powering choice
    # The reaction order (owner 2026-09-26) round-trips and survives the other saves too.
    mine = {"stamina_guard", "cloud_sleeve", "spines"}
    plan = {"mode": "custom", "order": ["stamina_guard", "cloud_sleeve"], "off": ["spines"]}
    assert store.save_reactions(project_id, plan, mine)["reactions"] == {"order": ["stamina_guard", "cloud_sleeve"], "off": ["spines"]}
    assert store.save(project_id, {"buttons": [], "layout": {"hidden": [], "pinned": []}}, known_ids=set())["reactions"]["off"] == ["spines"]
    assert store.save_reactions(project_id, {"mode": "auto"}, mine)["reactions"] == {}  # back to Auto
    held = store.save_reactions(project_id, {"hold": "spines"}, mine)["reactions"]  # the first version's single hold
    assert held["order"] == ["spines"] and set(held["off"]) == {"stamina_guard", "cloud_sleeve"}
    with pytest.raises(TabletopError) as unknown:
        store.save_reactions(project_id, {"mode": "custom", "order": ["not_mine"]}, mine)
    assert unknown.value.code == "TABLETOP_REACTION_UNKNOWN"


def test_an_unknown_action_or_pool_is_rejected():
    with pytest.raises(TabletopError) as unknown:
        normalize_powering({"choices": {"act:nope": "qi"}}, {"act:a": ["qi", "resonance"]})
    assert unknown.value.code == "POWERING_UNKNOWN_ACTION"
    with pytest.raises(TabletopError) as invalid:
        normalize_powering({"choices": {"act:a": "fire"}}, {"act:a": ["qi", "resonance"]})
    assert invalid.value.code == "POWERING_INVALID_POOL"
    assert normalize_powering({"choices": {"act:a": "Resonance"}}, {"act:a": ["qi", "resonance"]}) == {"act:a": "resonance"}
