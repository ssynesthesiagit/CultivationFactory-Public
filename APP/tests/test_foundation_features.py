"""Foundation features (owner 2026-09-25): a finished character's Foundation stage
contributes its printed features to combat and the sheet, not just the numeric
passives already folded into the sheet at creation."""
import json

from combat.factory_compiler import compile_character
from combat.tabletop import sheet_library
from non_sphere_authority import foundation_mechanics as fm
from non_sphere_authority.foundation_features import feature_id, features_for_stage

FOUNDATION_ID = "dream_mirror_soul_anchor_v0_2B"
AWAKENED_NAMES = {"Mirror-Root Reserve", "Reflection Cut", "True-Name Witness", "False-Image Guard", "Generate Mirror Trace"}
REFINED_ONLY_NAMES = {"Truth Behind the Mask", "Mirror-Step Reflex", "Dream-Reflection Counter", "Stable True Name"}
PERFECTED_ONLY_NAMES = {"Dream-Mirror Domain"}


def _sheet(stage: str) -> dict:
    return {
        "identity": {"display_name": "Test Cultivator", "cultivation_level": 17, "proficiency_bonus": 6, "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": json.dumps([{"ability": a, "modifier": m, "score": 10 + 2 * m} for a, m in
                                     (("STR", 4), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))]),
            "armor_class": json.dumps({"base_value": 14}), "hit_points": json.dumps({"maximum": 120}),
            "initiative": json.dumps({"bonus": 2}), "speed": json.dumps({"walking_ft": 30}),
            "primary_resource": json.dumps({"name": "Qi", "maximum": 40}),
            "technique_attack_bonus": 10, "technique_save_dc": 18,
        },
        "spheres_and_talents": {
            "sphere_record_ids": ["tianxia.sphere.brute"],
            "learned_talent_record_ids": ["TAL_BRUTE_MOUNTAIN_MOVING_PALM"],
        },
        "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}],
        "foundation": {
            "foundation_id": FOUNDATION_ID, "stage": stage,
            "resource": {"name": "Mirror Trace", "resource_id": f"foundation.resource.{FOUNDATION_ID}",
                         "current": 0, "initial_current": 0, "maximum": 1},
        },
        "selected_record_sections": {"other": [{
            "section": "other", "subsection": "Foundation", "record_id": FOUNDATION_ID,
            "display_name": "Dream-Mirror Soul Anchor",
            "one_line_description": "Dreams, mirrors, masks, reflections, and false selves carry spiritual weight for you.",
            "full_description": "Dreams, mirrors, masks, reflections, and false selves carry spiritual weight for you.",
        }]},
    }


def _mentioned_names(bundle: dict) -> set[str]:
    """Every Foundation feature name that shows up anywhere in a compiled bundle: unautomated
    (skipped), a modifier report, or -- owner 2026-09-26, since False-Image Guard and Generate Mirror
    Trace now compile as generic reaction rows instead of being skipped -- typed_reactions/typed_passives."""
    skipped = bundle["diagnostics"]["skipped"]
    automated_names = {row["name"] for row in [*bundle.get("typed_reactions", []), *bundle.get("typed_passives", [])]
                       if str(row.get("feature_id") or "").startswith(f"foundation.{FOUNDATION_ID}.")}
    return {*skipped["reaction"], *skipped["passive"]} | automated_names | {row["name"] for row in bundle["modifiers"] if row["id"].startswith(f"foundation.{FOUNDATION_ID}.")}


def test_catalog_parser_finds_dream_mirror_features_by_stage():
    record = fm.verified_foundation_records()[FOUNDATION_ID]
    awakened = {row["name"] for row in features_for_stage(FOUNDATION_ID, "Awakened")}
    refined = {row["name"] for row in features_for_stage(FOUNDATION_ID, "Refined")}
    perfected = {row["name"] for row in features_for_stage(FOUNDATION_ID, "Perfected")}
    assert awakened == AWAKENED_NAMES
    assert refined == AWAKENED_NAMES | REFINED_ONLY_NAMES
    assert perfected == AWAKENED_NAMES | REFINED_ONLY_NAMES | PERFECTED_ONLY_NAMES
    # An unrecognized/unstable initial state grants none (it cannot claim stable benefits).
    assert features_for_stage(FOUNDATION_ID, "Unstable") == []
    assert record["catalog_number"] == 24


def test_awakened_sheet_compiles_the_foundation_resource_and_only_awakened_features():
    bundle = compile_character(_sheet("Awakened"), actor_id="actor:factory.test")
    resources = {row["resource_id"]: row["maximum"] for row in bundle["actor_template"]["resources"]}
    assert resources["resource:foundation.mirror_trace"] == 1  # named for the table ("Mirror Trace")
    mentioned = _mentioned_names(bundle)
    assert AWAKENED_NAMES <= mentioned
    assert not (REFINED_ONLY_NAMES | PERFECTED_ONLY_NAMES) & mentioned
    # Printed Reflection Cut spends Trace after a hit/failed damaging save.
    # Its existing plug-in owns that conversion; an upfront variant would pay
    # too early and duplicate the post-hit route.
    cut_id = feature_id(FOUNDATION_ID, "Reflection Cut")
    reflection_cut = next(row for row in bundle["typed_passives"] if row["feature_id"] == cut_id)
    assert reflection_cut["block"] == "dream_mirror_conversion"
    assert reflection_cut["kind"] == "reflection_cut"
    assert not any(row["id"] == cut_id for row in bundle["modifiers"])


def test_refined_sheet_gets_awakened_and_refined_features():
    bundle = compile_character(_sheet("Refined"), actor_id="actor:factory.test")
    mentioned = _mentioned_names(bundle)
    assert AWAKENED_NAMES <= mentioned
    assert REFINED_ONLY_NAMES <= mentioned
    assert not PERFECTED_ONLY_NAMES & mentioned


def test_sheet_library_lists_the_foundations_features():
    sheet = _sheet("Refined")
    bundle = compile_character(sheet, actor_id="actor:factory.test")
    passives = [row.get("feature_id") for row in bundle.get("typed_passives") or []]
    reactions = [row.get("feature_id") for row in bundle.get("typed_reactions") or []]
    automated = {value for value in passives + reactions if value}
    automated |= {row["id"] for row in bundle.get("modifiers") or [] if row.get("status") == "applied"}
    library = sheet_library(sheet, [], automated)
    cultivation = next(group for group in library["groups"] if group["key"] == "cultivation")
    by_name = {entry["name"]: entry for entry in cultivation["entries"]}
    for name in AWAKENED_NAMES | REFINED_ONLY_NAMES:
        assert name in by_name, name
        assert by_name[name]["text"]
        assert by_name[name]["status"] in {"auto", "gm", "action", "partial"}
    assert by_name["Reflection Cut"]["status"] == "auto"
    assert not PERFECTED_ONLY_NAMES & by_name.keys()
