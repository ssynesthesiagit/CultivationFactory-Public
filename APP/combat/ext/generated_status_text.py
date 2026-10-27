"""Presentation provenance for extension-generated settings and trackers.

Shared by the Body, Qi, Spirit, weapon and Hidden Eye extensions. This catalog
only describes their existing conditions, including old saved instances; it
does not change effects, lifetime, ownership or stored fight bytes.
"""
from . import hook

SOURCES = {
    "aimed_line": "TAL_SNIPER_RANGEFINDING_BREATH",
    "brute_court_grapple_size": "TAL_BRUTE_COURT_OF_THE_MOVING_MOUNTAIN",
    "brute_muscular_surge_grapple_size": "TAL_BRUTE_MUSCULAR_SURGE",
    "brute_sovereign_grapple_size": "TAL_BRUTE_SOVEREIGN_WEIGHT_INCARNATION",
    "daemonic_emperor_flight": "TAL_DAEMONIC_CULTIVATION_DEMON_EMPEROR_INCARNATION",
    "daemonic_inner_flight": "TAL_DAEMONIC_CULTIVATION_INNER_DEMON_INCARNATION",
    "drunken_sovereign_flight": "TAL_DRUNKEN_STYLE_SOVEREIGN_CHAOS_STEP_INCARNATION",
    "radiance_heavenly_flight": "tianxia.talent.radiance.heavenly_radiance",
    "shadow_sovereign_flight": "TAL_SHADOW_SHADOW_SOVEREIGN_INCARNATION",
    "void_sovereign_flight": "TAL_VOID_VOID_SOVEREIGN_INCARNATION",
    "body_dragon_step_clinch": "TAL_IRON_FIST_DRAGON_STEP_CLINCH",
    "core_tempering_expression": "tianxia.path.body_refining.feature.core_tempering_expression",
    "mountain_rending_choice": "tianxia.path.body_refining.feature.core_tempering_expression",
    "mountain_rending_ready": "tianxia.path.body_refining.feature.core_tempering_expression",
    "stance.golden_bell_circulation": "tianxia.path.body_refining.feature.core_tempering_expression",
    "thorn_flesh_armory_choice": "tianxia.subpath.body.black_thorn_demon_body.feature.thorn_flesh_armory",
    "black_vein_palm_choice": "TAL_UNMAKING_BLACK_VEIN_PALM",
    "blade_fist_choice": "tianxia.subpath.body.kensei.feature.blade_fist",
    "severing_palm_choice": "tianxia.subpath.body.kensei.feature.severing_palm",
    "severing_arm": "tianxia.subpath.body.kensei.feature.severing_palm",
    "pressure_point_choice": "tianxia.subpath.body.shinobi.feature.pressure_point_strike",
    "crawling_fever_choice": "tianxia.talent.disease.court_of_the_crawling_fever",
    "double_dip_pick": "TAL_SCOUNDREL_DOUBLE_DIP",
    "skewer_pick": "TAL_FENCING_SKEWER",
    "flowing_response_choice": "TAL_FLOWING_RIVER_FLOWING_RESPONSE",
    "flowing_response_step": "TAL_FLOWING_RIVER_FLOWING_RESPONSE",
    "return_the_grip_choice": "TAL_FLOWING_RIVER_RETURN_THE_GRIP",
    "turn_the_foot_choice": "TAL_FLOWING_RIVER_TURN_THE_FOOT",
    "hammer_rebuke_choice": "tianxia.talent.blacksmith.hammer_rebuke",
    "saint_body_rebuke_choice": "foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke",
    "golden_core_form": "tianxia.path.qi_cultivation.feature.golden_core_form",
    "domain_armament": "tianxia.path.qi_cultivation.feature.domain_armament",
    "spirit_awakening_pressure_choice": "tianxia.path.spirit_awakening.feature.domain_pressure",
    "demon_seed_overdraw_choice": "tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw",
    "deadly_strike_choice": "TAL_THE_HIDDEN_EYE_DEADLY_STRIKE",
    "eye_discern_illusions": "TAL_THE_HIDDEN_EYE_DISCERN_ILLUSIONS",
    "eye_modified_save": "TAL_THE_HIDDEN_EYE_MODIFY_CHARACTERISTICS",
    "eye_surface_thoughts": "tianxia.talent.the_hidden_eye.detect_surface_thoughts",
    "eye_court_ally": "TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE",
    "destruction_blast_type": "TAL_DESTRUCTION_DESTRUCTIVE_BLAST",
    "destruction_break_the_guard": "tianxia.talent.destruction.break_the_guard",
    "spend_depth_choice": "tianxia.subpath.qi.black_sea_leviathan_womb.feature.inner_sea_awakening",
    "wenxue.saber_line_guard_choice": "SABERS_BASE_SABER_LINE_PRESSURE",
    "river_named_guard": "TAL_FLOWING_RIVER_TURNING_GUARD",
    "shi_pp_point_pick": "PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING",
    "shi_pp_seal_pick": "PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING",
    "beauty_motion": "tianxia.talent.beauty.beauty_in_motion",
    "monkey_caper": "TAL_MONKEY_STYLE_CAPERING_FOOTWORK",
    "music_measure": "MUSIC_BASE_KEEP_THE_MEASURE",
    "wenxue.hard_draw_ready": "tianxia.talent.sabers.hard_draw_cut",
}


@hook("status_description")
def describe(engine, holder, row, data):
    from ..status_text import printed_excerpt
    from .analyze_readings import status_reading
    from .setting_choices import is_setting_action
    from .setting_status_text import selector_source_rules

    action = engine.action_catalog.get(row.get("source_definition_id"))
    if holder is not None and is_setting_action(action) and action.owner_id == holder.entity_id:
        bundle = next((b for b in engine.typed_bundle_documents if b.get("actor_id") == holder.entity_id), None)
        key = str(row.get("condition_id") or "").removeprefix("condition:typed.")
        if bundle is not None and selector_source_rules(bundle, action, data, SOURCES.get(key))[1]:
            return None  # The setting hook owns this more specific printed section.

    analyze = status_reading(engine, row, data)
    if analyze:
        return analyze

    key = str(row.get("condition_id") or "").removeprefix("condition:typed.")
    record = SOURCES.get(key)
    if key == "wall_plan":
        return {"text": "Wall layout: the next wall you raise runs through your selected squares, in order. "
                        "Choosing points costs no action or resource; raising the wall pays that ability's normal cost. "
                        "Clear wall points removes this saved layout.", "source_ability": "Wall layout"}
    if key == "next_attack_ac":
        return {"text": f"Armor Class changes by {int(data.get('amount') or 0):+d} for the next incoming attack. "
                        "The table removes this modifier after that attack is rolled, whether it hits or misses, "
                        "or when its printed deadline expires. No further payment is required for this modifier.",
                "source_ability": "Next-attack Armor Class modifier"}
    if key == "overdraw_ready":
        return {"text": "Overdraw is selected: once per turn, after an Unmaking talent damages a creature, "
                        "it deals extra Ruin damage and you take damage in return. By Realm, the extra damage "
                        "is 3d6, 6d6, 10d6 or 14d6 at Cultivation Levels 1–4, 5–9, 10–14 or 15–20; "
                        "the damage to you is respectively 1d6, 2d6, 4d6 or 6d6 plus your "
                        "Proficiency Bonus. You also gain 1 Vein Strain, the accumulating strain from Unmaking. "
                        "Selecting this setting costs no action or resource and keeps it until you turn it off.",
                "source_ability": "Overdraw"}
    if key == "save_against" and data.get("label"):
        return {"text": data["label"] + ". The table applies this benefit only to the listed saving throws while the status lasts."}
    if key == "destruction_deepen":
        return {"text": "Deepen the Calamity is selected: each Destructive Blast costs 1 additional point from "
                        "your Path's pool (Stamina, Qi or Resonance) and rolls one Destruction Die plus one per "
                        "two Cultivation Levels, rounded down, instead of its ordinary damage dice. "
                        "The setting stays selected until turned off; payment occurs on each release.",
                "source_ability": "Deepen the Calamity"}
    if key == "open_the_gate":
        return {"text": "Open the Gate records your choice for a qualifying unarmed hit, once per turn: "
                        "Centerline Impact adds your Proficiency Bonus to damage if the strike dealt damage; "
                        "Hooking Step lets you move 5 feet without provoking from the struck creature; "
                        "Breath-Checking Strike prevents its opportunity attacks until the start of your next turn. "
                        "Selecting this setting costs no action or resource and keeps it until changed.",
                "source_ability": "Open the Gate"}
    if key in {"exploit_pick", "gu_berserker_exertion_choice"}:
        from ..status_text import printed_rules
        selected = data.get("exploit") or data.get("talent") or data.get("choice") or ""
        slug = str(selected).upper().replace(" ", "_").replace("-", "_")
        candidate = ("TAL_FENCING_" if key == "exploit_pick" else "TAL_BERSERKER_") + slug
        record = selected if selected in printed_rules() else candidate
    if key.startswith("body_adrenaline_"):
        talent = key.removeprefix("body_adrenaline_")
        if talent == "active":
            return {"text": "Adrenaline: at the start of your turn, you may activate one Adrenaline talent you know "
                            "until the start of your next turn. While active, your Armor Class is reduced by 2. "
                            "No action or Stamina is required. The table keeps this setting until you turn it off; "
                            "choose again at the start of each turn as the printed rule requires.",
                    "source_ability": "Adrenaline"}
        record = "TAL_BERSERKER_" + talent.upper()
    if not record:
        return None
    text = printed_excerpt(record, source=True)
    if not text:
        return None
    label = data.get("label") or ""
    prefix = f"Selected setting: {label}. " if label else ""
    from ..status_text import printed_rules, plain
    import re

    action = engine.action_catalog.get(row.get("source_definition_id"))
    if (action is not None and not action.costs and not (action.parameters or {}).get("setting_only")
            and re.search(r"\b[1-9]\d* CP\b", text)):
        text += " This saved action has no recorded resource cost; the table does not automatically charge its printed resource payment."

    title = plain(printed_rules()[record].splitlines()[0])
    title = re.sub(r"^CL\s*\d+\s*[-—–]\s*", "", title)
    title = re.split(r"\s+[-—–]\s+", title)[0]
    from .resource_readings import paying_pool
    return {"text": prefix + text, "source_ability": title,
            "paying_pool": paying_pool(engine, holder, row, record)}
