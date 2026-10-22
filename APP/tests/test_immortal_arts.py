"""Immortal Arts fight (owner 2026-09-26): combat/factory_compiler.py delivers each art's source
talent's typed core at the art's own economy and printed activation cost, with its Factor layer mapped
where it fits and everything else preserved as a GM rider.  Fixtures below are trimmed copies of real
constructed Immortal Art records (Ye Yi, Ning Kai, Lingyue Frostveil at CL20) and their source mechanics
from Tianxia_Typed_Mechanics_Authority_R1.json, read from
~/.local/state/cultivation-factory/portable_characters/<project_id>/current.zip.
"""

from pathlib import Path

from combat.factory_compiler import _art_save_dc, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind

ROOT = Path(__file__).resolve().parents[1]

# Trimmed real mechanics (source talents the Immortal Arts below reference).
DOMAIN_PRESSURE = {
    "mechanic_id": "tianxia.path.spirit_awakening.feature.domain_pressure", "name": "Domain Pressure",
    "activation": {"economy": "action", "trigger": None}, "cost": [[{"resource": "resonance", "amount": 2}]],
    "use_limit": None, "range": None, "area": {"shape": "special", "size_ft": None, "text": "Cone originating from you"},
    "duration": {"kind": "instant"}, "path_id": "tianxia.path.spirit_awakening",
    "effects": [{"type": "save", "ability": "wis", "dc": "technique_save_dc",
                "on_fail": [{"type": "condition", "applies_to": "target", "condition": "frightened",
                            "evidence": "Frightened of you until the end of your next turn"}], "on_success": []}],
    "riders": ["Area: Cone originating from you."],
}
IRON_VOICE = {
    "mechanic_id": "tianxia.path.body_refining.feature.iron_voice", "name": "Iron Voice",
    "activation": {"economy": "bonus_action", "trigger": None}, "cost": [[{"resource": "stamina", "amount": 1}]],
    "use_limit": None, "range": {"kind": "feet", "feet": 30}, "area": None,
    "duration": {"kind": "instant"}, "path_id": "tianxia.path.body_refining",
    "effects": [{"type": "save", "ability": "con", "dc": "technique_save_dc",
                "on_fail": [{"type": "condition", "applies_to": "target", "condition": "frightened",
                            "evidence": "Frightened of you until the end of your next turn"}], "on_success": []}],
    "riders": ["Iron Voice does not require shared language."],
}
QI_ARMOR = {
    "mechanic_id": "tianxia.path.qi_cultivation.feature.qi_armor", "name": "Qi Armor",
    "activation": {"economy": "reaction", "trigger": "You are hit by a ranged attack roll."},
    "cost": [[{"resource": "qi", "amount": 2}]], "use_limit": None, "range": None, "area": None,
    "duration": {"kind": "instant"}, "path_id": "tianxia.path.qi_cultivation",
    "effects": [{"type": "ac_bonus", "applies_to": "self", "flat": 3, "evidence": "Gain +3 AC"}],
    "riders": ["Applies to ranged attacks only."],
}
FEATHERFALL = {
    "mechanic_id": "tianxia.path.qi_cultivation.feature.featherfall", "name": "Featherfall",
    "activation": {"economy": "reaction", "trigger": "You or a creature within 60 feet begins falling."},
    "cost": [[{"resource": "text", "text": "1 Qi per target"}]], "use_limit": None, "range": None, "area": None,
    "duration": {"kind": "minutes", "amount": 1}, "path_id": "tianxia.path.qi_cultivation",
    "effects": [{"type": "movement", "applies_to": "target", "distance_ft": 60, "evidence": "Descends no more than 60 feet per round."}],
    "riders": ["Does not grant flight or horizontal movement."],
}
SOUL_GAZE = {
    "mechanic_id": "tianxia.path.spirit_awakening.feature.soul_gaze", "name": "Soul Gaze",
    "activation": {"economy": "action", "trigger": None}, "cost": [[{"resource": "resonance", "amount": 1}]],
    "use_limit": None, "range": {"kind": "feet", "feet": 60}, "area": None,
    "duration": {"kind": "instant"}, "path_id": "tianxia.path.spirit_awakening",
    "effects": [], "riders": ["Learn the target's current and maximum Hit Points and broad Path."],
}
AUTHORITY = {"mechanics": {row["mechanic_id"]: row for row in
                          (DOMAIN_PRESSURE, IRON_VOICE, QI_ARMOR, FEATHERFALL, SOUL_GAZE)}}

# Trimmed real Immortal Art records (action_surface.factor_application.effective_effect.factor_refinement
# is copied verbatim from the sealed sheet; only "path": "LocalSources/..." rules-text blobs are dropped).
DOMAIN_PRESSURE_ART = {
    "art_id": "tianxia.constructed.immortal_art.8b0a0e7dcef601facc3dfc1b965f3bc449ae4e68",
    "name": "Domain Pressure — Binding Immortal Art", "display_name": "Domain Pressure — Binding Immortal Art",
    "source_record_id": "tianxia.path.spirit_awakening.feature.domain_pressure", "path_id": "tianxia.path.spirit_awakening",
    "key_ability": "WIS", "activation_cp": 5,
    "factors": [{"factor_id": "speed_reduction", "display_name": "Speed Reduction", "mechanical_chassis": "Use Fettered Movement."}],
    "action_surface": {
        "action_type": "action", "dc_basis": "8 + Proficiency Bonus + Wisdom modifier",
        "factor_application": {"factor_id": "speed_reduction", "effective_effect": {"factor_refinement": {
            "binding_save": "Strength saving throw against art save DC",
            "failed_save": "Speed reduced by 10 feet × PB for 1 minute",
            "failure_by_5": "Speed becomes 0 until start of binder's next turn",
            "successful_save": "No additional Speed reduction",
        }}},
    },
}
IRON_VOICE_ART = {
    "art_id": "tianxia.constructed.immortal_art.6c63ce99135d10435ab250c2b895828a8eee7152",
    "name": "Iron Voice — Binding Immortal Art", "display_name": "Iron Voice — Binding Immortal Art",
    "source_record_id": "tianxia.path.body_refining.feature.iron_voice", "path_id": "tianxia.path.body_refining",
    "key_ability": "CON", "activation_cp": 4,
    "factors": [{"factor_id": "speed_reduction", "display_name": "Speed Reduction", "mechanical_chassis": "Use Fettered Movement."}],
    "action_surface": {
        "action_type": "bonus action", "dc_basis": "8 + Proficiency Bonus + Constitution modifier",
        "factor_application": {"factor_id": "speed_reduction", "effective_effect": {"factor_refinement": {
            "failed_save": "Speed reduced by 10 feet × PB for 1 minute",
        }}},
    },
}
QI_ARMOR_ART = {
    "art_id": "tianxia.constructed.immortal_art.27c34031c2fff13a02797f0212b58c14c35000d9",
    "name": "Qi Armor — Fortification Immortal Art", "display_name": "Qi Armor — Fortification Immortal Art",
    "source_record_id": "tianxia.path.qi_cultivation.feature.qi_armor", "path_id": "tianxia.path.qi_cultivation",
    "key_ability": "INT", "activation_cp": 5,
    "factors": [{"factor_id": "temporary_hp_fortification", "display_name": "Temporary HP Fortification",
                "mechanical_chassis": "Default: target gains one Fortification Package temporary HP."}],
    "action_surface": {
        "action_type": "reaction", "dc_basis": "none",
        "factor_application": {"factor_id": "temporary_hp_fortification", "effective_effect": {"factor_refinement": {
            "temporary_hp": "PBd6", "duration": "1 minute", "stacking": "Does not stack with the same source",
        }}},
    },
}
FEATHERFALL_ART = {
    "art_id": "tianxia.constructed.immortal_art.featherfall.test",
    "name": "Featherfall — Fortification Immortal Art", "display_name": "Featherfall — Fortification Immortal Art",
    "source_record_id": "tianxia.path.qi_cultivation.feature.featherfall", "path_id": "tianxia.path.qi_cultivation",
    "key_ability": "INT", "activation_cp": 5,
    "factors": [{"factor_id": "temporary_hp_fortification", "display_name": "Temporary HP Fortification",
                "mechanical_chassis": "Default: target gains one Fortification Package temporary HP."}],
    "action_surface": {
        "action_type": "reaction", "dc_basis": "none",
        "factor_application": {"factor_id": "temporary_hp_fortification", "effective_effect": {"factor_refinement": {"temporary_hp": "PBd6"}}},
    },
}
SOUL_GAZE_ART = {
    "art_id": "tianxia.constructed.immortal_art.soul_gaze.test",
    "name": "Soul Gaze — Revelation Immortal Art", "display_name": "Soul Gaze — Revelation Immortal Art",
    "source_record_id": "tianxia.path.spirit_awakening.feature.soul_gaze", "path_id": "tianxia.path.spirit_awakening",
    "key_ability": "WIS", "activation_cp": 4,
    "factors": [{"factor_id": "detect_presence", "display_name": "Detect Presence", "mechanical_chassis": "Detect whether a target category is present."}],
    "action_surface": {"action_type": "action", "dc_basis": "The protecting effect's DC",
                       "factor_application": {"factor_id": "detect_presence", "effective_effect": {}}},
}

SHEET = {
    "identity": {"proficiency_bonus": 6, "cultivation_level": 20},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 10 + 2 * m, "modifier": m} for a, m in
                      (("STR", 1), ("DEX", 2), ("CON", 4), ("INT", 3), ("WIS", 4), ("CHA", 0))],
        "armor_class": {"base_value": 15}, "hit_points": {"maximum": 150}, "speed": {"walking_ft": 30},
        "technique_save_dc": 18, "technique_attack_bonus": 10,
        "primary_resource": {"name": "Resonance", "maximum": 20, "definitions": [
            {"name": "Resonance", "max": 20}, {"name": "Stamina", "max": 30}, {"name": "Qi", "max": 25}]},
    },
    "spheres_and_talents": {},
}


def test_action_immortal_art_delivers_source_effects_own_cost_and_factor_on_fail():
    """Domain Pressure (Ye Yi, CL15, Spirit Awakening): the save+Frightened core survives, the Speed
    Reduction Factor rides the failed save as a real Speed penalty, and its unmapped nuances (a separate
    Strength binding save, escalation by margin) are never dropped -- they land as a rider."""
    sheet = {**SHEET, "immortal_arts": [DOMAIN_PRESSURE_ART]}
    bundle = compile_character(sheet, actor_id="actor:test.domain_pressure", typed_authority=AUTHORITY)
    action = next(row for row in bundle["action_catalog"] if "Domain Pressure" in row["display_name"])
    assert action["economy"] == "ACTION"
    assert action["source_definition_id"].startswith("action:typed.") and ".immortal." in action["source_definition_id"]
    assert list(action["costs"]) == [["resource:core.resonance", 5]]  # activation_cp, its own Path pool
    typed = action["parameters"]["typed"]
    save = typed["effects"][0]
    assert save["type"] == "save" and save["on_fail"][0]["condition"] == "frightened"
    speed = next(row for row in save["on_fail"] if row["type"] == "speed")
    assert speed["amount"] == -60  # 10 ft x PB(6)
    assert any("not automated" in rider and "binding_save" in rider for rider in typed["riders"])


def test_bonus_action_immortal_art_uses_its_own_path_pool():
    sheet = {**SHEET, "immortal_arts": [IRON_VOICE_ART]}
    bundle = compile_character(sheet, actor_id="actor:test.iron_voice", typed_authority=AUTHORITY)
    action = next(row for row in bundle["action_catalog"] if "Iron Voice" in row["display_name"])
    assert action["economy"] == "BONUS_ACTION"
    assert list(action["costs"]) == [["resource:core.stamina", 4]]


def test_reaction_immortal_art_compiles_when_its_trigger_is_runnable():
    """Qi Armor's reaction trigger ("hit by a ranged attack") is one the engine already runs; the
    Temporary HP Fortification Factor is added as a real temp_hp effect alongside the source's +3 AC."""
    sheet = {**SHEET, "immortal_arts": [QI_ARMOR_ART]}
    bundle = compile_character(sheet, actor_id="actor:test.qi_armor", typed_authority=AUTHORITY)
    assert not any(".immortal." in row["source_definition_id"] for row in bundle["action_catalog"])  # not an action
    reaction = next(row for row in bundle["typed_reactions"] if "Qi Armor" in row["name"])
    assert reaction["kind"] == "hit" and reaction["ranged_only"] is True
    assert reaction["costs"] == [{"resource_id": "resource:core.qi", "amount": 5}]
    temp_hp = next(row for row in reaction["effects"] if row["type"] == "temp_hp")
    assert temp_hp["dice"] == {"count_formula": "pb", "sides": 6}
    assert any(row["type"] == "ac_bonus" for row in reaction["effects"])


def test_reaction_immortal_art_with_unsupported_trigger_is_a_reported_gap():
    """Featherfall's trigger ("begins falling") has no engine hook: a reported gap, not a silent drop
    and not a crash."""
    sheet = {**SHEET, "immortal_arts": [FEATHERFALL_ART]}
    bundle = compile_character(sheet, actor_id="actor:test.featherfall", typed_authority=AUTHORITY)
    assert not any(".immortal." in row["source_definition_id"] for row in bundle["action_catalog"])
    assert not any("Featherfall" in row["name"] for row in bundle["typed_reactions"])
    assert "Featherfall — Fortification Immortal Art" in bundle["diagnostics"]["skipped"]["reaction"]


def test_immortal_art_with_no_typed_source_is_a_reported_gap():
    """Soul Gaze's source mechanic has no typed effects at all (pure information); reported, not dropped."""
    sheet = {**SHEET, "immortal_arts": [SOUL_GAZE_ART]}
    bundle = compile_character(sheet, actor_id="actor:test.soul_gaze", typed_authority=AUTHORITY)
    assert not any(".immortal." in row["source_definition_id"] for row in bundle["action_catalog"])
    assert "Soul Gaze — Revelation Immortal Art" in bundle["diagnostics"]["skipped"]["not_typed"]


def test_owner_sheet_immortal_arts_may_be_a_single_dict_or_null():
    """owner_sheet["immortal_arts"] is a list, a single dict, or null (the gap description); either shape compiles."""
    as_dict = compile_character({**SHEET, "immortal_arts": IRON_VOICE_ART}, actor_id="actor:test.dict", typed_authority=AUTHORITY)
    assert any("Iron Voice" in row["display_name"] for row in as_dict["action_catalog"])
    as_null = compile_character({**SHEET, "immortal_arts": None}, actor_id="actor:test.null", typed_authority=AUTHORITY)
    assert not any(".immortal." in row["source_definition_id"] for row in as_null["action_catalog"])


def test_art_save_dc_uses_its_own_ability_when_it_differs_from_the_sheet_default():
    mods = {"WIS": 5, "STR": 1}
    assert _art_save_dc("8 + Proficiency Bonus + Wisdom modifier", mods, 6) == 19  # 8 + 6 + 5
    assert _art_save_dc("8 + Proficiency Bonus + Strength modifier", mods, 6) == 15
    assert _art_save_dc("none", mods, 6) is None
    assert _art_save_dc("The protecting effect's DC", mods, 6) is None


def _engine_with(typed: dict, seed: str) -> tuple[Gate2Engine, str]:
    engine = Gate2Engine(ROOT, match_seed=seed)
    actor = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id="action:typed.immortal.test", display_name="Immortal test", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                              range_ft=500, parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    return engine, actor.entity_id


def test_a_compiled_immortal_art_runs_in_the_engine_without_crashing():
    sheet = {**SHEET, "immortal_arts": [DOMAIN_PRESSURE_ART]}
    bundle = compile_character(sheet, actor_id="actor:test.engine", typed_authority=AUTHORITY)
    action = next(row for row in bundle["action_catalog"] if "Domain Pressure" in row["display_name"])
    engine, actor_id = _engine_with(action["parameters"]["typed"], "IMMORTAL-ART-ENGINE-TEST")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.immortal.test")
    engine.execute_intent(ActionIntent(intent_id="test:immortal", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=candidate.actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    mine = [e.event_type for e in engine.events if e.source_definition_id == "action:typed.immortal.test"]
    assert "SAVE_ROLLED" in mine or "CONDITION_APPLIED" in mine or "GM_RIDER" in mine
