from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gate2_mechanics_lock import (
    AttackSpec,
    DamageSpec,
    DiceExpression,
    DurationSpec,
    Economy,
    EffectSpec,
    ExecutableMechanicProfile,
    ExecutableMechanicsLock,
    LockOverallStatus,
    MechanicsLockStatus,
    ProfileKind,
    ResourceCost,
    SaveSpec,
    SourceBundleIdentity,
    TargetingSpec,
    write_executable_mechanics_lock,
)
from .gate2a import ALLOWED_PRIMITIVES, build_gate2a_lock


GATE2A_PARENT_SHA256 = "54677a3b32a587d8a3aebc7c17905c7405d242659ba2674ba24c91029ec78f53"
CHARACTER_AUTHORITY_BUNDLE_SHA256 = "eeca6dd3de4d2bfb2237cad086aa2b085375b4edd17321e765c4a7ecdb3e964b"
CONTINUATION_PROMPT_SHA256 = "34a2b126c1690759e4973d57ba94925ce80a8a4a3da0dcfd4d953c284df01c38"
CHARACTER_PACKAGES = {
    "an_eui": ("AnEui_CL5_Phase2H_Final.zip", "508a86b32e6c23a9a22726114c2c3019f90fb064c59c6a734ef0d5d400a4e7ce", 533925),
    "lee_jia": ("LeeJia_CL5_Phase2H_Final.zip", "534f87d323b087b97088d83e26b65b1f9d6521b16150d92fd32b762dccac11a5", 521616),
    "ling_qi": ("LingQi_CL5_HF05ZVK_R1G_Phase2H_GM_Candidate.zip", "395f5548b4ba27bb51cfcfc5df7f06eb4267adcc9afe50f13f70ea09cd8e393f", 501099),
    "bai_meizhen": ("BaiMeizhen_CL5_Cmd6.zip", "99a4a2592f1b8a30c67f79cfef32b57a85dc4ddf905a83e873ceee545c129d3a", 1081209),
}


def _authority(character: str, locator: str) -> tuple[str, str]:
    filename, sha256, _ = CHARACTER_PACKAGES[character]
    return f"Exact character package {filename} SHA-256 {sha256}", locator


def _effect(gate: str, primitive: str, **parameters: Any) -> EffectSpec:
    return EffectSpec(gate=gate, primitive_id=primitive, parameters=parameters)


def _duration(expiration: str, *, source: bool = False, target: bool = False) -> DurationSpec:
    return DurationSpec(expiration=expiration, source_actor_bound=source, target_actor_bound=target)


def _resolved(profile: ExecutableMechanicProfile, **updates: Any) -> ExecutableMechanicProfile:
    updates.setdefault("status", MechanicsLockStatus.LOCKED_EXECUTABLE)
    updates.setdefault("unresolved_fields", ())
    updates.setdefault("resolution_request", None)
    if "primitive_ids" in updates:
        updates["primitive_ids"] = tuple(sorted(updates["primitive_ids"]))
    return profile.model_copy(update=updates)


def _exact_authority_for_profile(profile: ExecutableMechanicProfile) -> dict[str, Any]:
    sid = profile.source_definition_id
    if "an_eui" in sid:
        authority, _ = _authority("an_eui", "Complete character package")
        return {"source_authority": authority}
    if "lee_jia" in sid:
        authority, _ = _authority("lee_jia", "Complete character package")
        return {"source_authority": authority}
    if "ling_qi" in sid:
        authority, _ = _authority("ling_qi", "Complete character package")
        return {"source_authority": authority}
    if "bai_meizhen" in sid or sid == "creature:bai_cui" or sid in {
        "condition:core.dose_marked", "condition:core.soaked"
    }:
        authority, _ = _authority("bai_meizhen", "Complete character package")
        return {"source_authority": authority}
    return {}


def _updates() -> dict[str, dict[str, Any]]:
    A, L, Q, B = "an_eui", "lee_jia", "ling_qi", "bai_meizhen"
    updates: dict[str, dict[str, Any]] = {}

    # Universal profiles resolved from exact character statistics plus the separately recorded defaults lock.
    updates["system:combat.initiative"] = dict(
        source_authority="Exact character Canonical_Stats_Resource_Block records plus Gate2 Universal Defaults Lock",
        source_locator="initiative_generation for all four characters; default:combat.initiative_ties",
        primitive_ids=(),
        effects=(
            _effect("ALWAYS", "primitive:schedule_expiration", rule="ROLL_1D20_PLUS_EXACT_INITIATIVE", tie_policy="DEFAULT_LOCK", companion="CUI_AFTER_BAI"),
        ),
        fidelity_consequence="Uses each exact initiative bonus while preserving a deterministic local tie order and Cui's source-controlled slot.",
    )
    updates["system:combat.opportunity_attack"] = dict(
        source_authority="Gate2 Universal Defaults Lock",
        source_locator="default:combat.opportunity_attack",
        reaction_checkpoint="LEAVE_REACH",
        primitive_ids=("primitive:attack_roll", "primitive:damage", "primitive:resolve_reaction"),
        effects=(
            _effect("ALWAYS", "primitive:resolve_reaction", trigger="VISIBLE_VOLUNTARY_LEAVE_REACH", disengage_prevents=True, forced_or_teleport=False),
        ),
        fidelity_consequence="Makes route risk deterministic while using only an actor's source-authorized basic melee profile.",
    )
    updates["system:combat.saving_throw_modifiers"] = dict(
        source_authority="Exact four-character Canonical_Stats_Resource_Block records and Cui stat block",
        source_locator="saving_throws and companion ability scores",
        primitive_ids=("primitive:save_roll",),
        effects=(
            _effect("ALWAYS", "primitive:save_roll", modifiers={
                "an_eui_early_book1_cl5": {"STR": -1, "DEX": 4, "CON": 3, "INT": 0, "WIS": 1, "CHA": 0},
                "lee_jia_early_outer_sect_cl5": {"STR": -1, "DEX": 4, "CON": 1, "INT": 3, "WIS": 0, "CHA": 0},
                "ling_qi_early_outer_sect_cl5": {"STR": -1, "DEX": 3, "CON": 2, "INT": -1, "WIS": 0, "CHA": 4},
                "bai_meizhen_early_outer_sect_cl5": {"STR": -1, "DEX": 2, "CON": 2, "INT": 0, "WIS": 1, "CHA": 4},
                "bai_cui": {"STR": 1, "DEX": 3, "CON": 2, "INT": -2, "WIS": 2, "CHA": 0},
            }),
        ),
        fidelity_consequence="All saves, concentration checks, zones, and companion defenses use the exact package modifiers.",
    )
    updates["system:combat.temporary_hit_points"] = dict(
        source_authority="Gate2 Universal Defaults Lock",
        source_locator="default:combat.temporary_hit_points",
        primitive_ids=("primitive:grant_temp_hp",),
        effects=(
            _effect("ALWAYS", "primitive:grant_temp_hp", stacking="DO_NOT_ADD", replacement="KEEP_GREATER", absorption="BEFORE_HP", source_end_removes=False),
        ),
        fidelity_consequence="Keep the Measure and other grants cannot stack or erase a larger retained buffer.",
    )

    # Shared conditions.
    auth, loc = _authority(A, "State_Effect_Registry.json / STATE_RUIN_TEMPERED_ARMAMENT")
    updates["condition:an_eui.ruin_tempered"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("CONCENTRATION_OR_10_ROUNDS_OR_WEAPON_UNUSABLE_OR_DISMISSED", source=True),
        concentration=True,
        primitive_ids=("primitive:add_modifier", "primitive:remove_modifier", "primitive:schedule_expiration"),
        effects=(
            _effect("ALWAYS", "primitive:add_modifier", target="SELECTED_WEAPON_INSTANCE", damage_type="SLASHING_DESTRUCTION", critical_bonus="2d6", enables="action:an_eui.first_arm"),
            _effect("ON_CONCENTRATION_END", "primitive:remove_modifier", target="SELECTED_WEAPON_INSTANCE"),
        ),
        fidelity_consequence="Binds the imbuement to actual weapon instances, controls critical damage, and gates First Arm.",
    )
    auth, loc = _authority(A, "State_Effect_Registry.json / STATE_BREAK_THE_GUARD")
    updates["condition:core.break_the_guard"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("START_OF_AN_EUI_NEXT_TURN", source=True, target=True),
        primitive_ids=("primitive:add_modifier", "primitive:remove_modifier", "primitive:schedule_expiration"),
        effects=(
            _effect("ALWAYS", "primitive:add_modifier", choose_exactly_one=["AC_MINUS_1", "NEXT_ATTACK_ADVANTAGE_CONSUMED", "NO_HALF_COVER"], only_one=True),
        ),
        fidelity_consequence="Preserves An Eui's explicit guard-opening choice rather than collapsing it to generic advantage.",
    )
    updates["condition:core.dodging"] = dict(
        source_authority="Gate2 Universal Defaults Lock", source_locator="default:combat.dodge",
        duration=_duration("START_OF_TARGET_NEXT_TURN", target=True),
        primitive_ids=("primitive:add_modifier", "primitive:remove_modifier", "primitive:schedule_expiration"),
        effects=(
            _effect("ALWAYS", "primitive:add_modifier", attacks="DISADVANTAGE_IF_VISIBLE", dexterity_saves="ADVANTAGE", ends_early=["INCAPACITATED", "SPEED_ZERO"]),
        ),
        fidelity_consequence="Makes Cui's default defense executable and bounded.",
    )
    auth, loc = _authority(B, "State_Effect_Registry.json / ST_DOSE_MARKED")
    updates["condition:core.dose_marked"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("MATCH_SCENE_OR_EXACT_ANTIDOTE", target=True),
        primitive_ids=("primitive:apply_condition", "primitive:remove_condition"),
        effects=(
            _effect("ALWAYS", "primitive:apply_condition", stacking="COUNT_PER_SOURCE_TARGET", maximum=None, direct_effect="NONE_WITHOUT_SOURCE_TECHNIQUE"),
        ),
        fidelity_consequence="Tracks poison accumulation exactly without inventing an unsupported generic stack penalty.",
    )
    auth, loc = _authority(B, "State_Effect_Registry.json / ST_SOAKED")
    updates["condition:core.soaked"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("END_OF_BAI_MEIZHEN_NEXT_TURN", source=True, target=True),
        primitive_ids=("primitive:apply_condition", "primitive:remove_condition", "primitive:schedule_expiration"),
        effects=(
            _effect("ALWAYS", "primitive:apply_condition", qualification=["WATER_SHIELD_MOVE", "WATER_WHIP_INTERACTION"], direct_stat_change="NONE"),
        ),
        fidelity_consequence="Retains the Water setup state without inventing vulnerability or damage changes.",
    )

    # An Eui.
    auth, loc = _authority(A, "Complete_Action_Surface.json / ACT_RA_SIX_ARMS_FIRST_ARM")
    updates["action:an_eui.first_arm"] = dict(
        source_authority=auth, source_locator=loc,
        profile_kind=ProfileKind.ATTACK_THEN_SAVE, economy=Economy.ACTION,
        targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", reach_ft=5, requires_line_of_sight=True),
        prerequisites=("condition:an_eui.ruin_tempered", "SELECTED_RUIN_TEMPERED_BI_SHOU_UNSTRESSED"),
        costs=(ResourceCost(resource_id="resource:an_eui.stamina", amount=3, timing="ON_SELECTION"),),
        attack=AttackSpec(bonus=7), post_hit_save=SaveSpec(ability="DEX", dc=14),
        damage=DamageSpec(dice=DiceExpression(count=1, sides=4, modifier=4), damage_type="SLASHING_DESTRUCTION"),
        effects=(
            _effect("ON_HIT", "primitive:damage", dice="3d6", damage_type="SLASHING_DESTRUCTION"),
            _effect("ON_HIT", "primitive:save_roll", ability="DEX", dc=14, fail=["REACTION_DENIED", "BREAK_THE_GUARD"]),
            _effect("ALWAYS", "primitive:remove_condition", condition_id="condition:an_eui.ruin_tempered", target="USED_WEAPON"),
            _effect("ALWAYS", "primitive:save_roll", ability="CON", dc=14, actor="SELF", fail_damage="1d6_UNAVOIDABLE"),
            _effect("ALWAYS", "primitive:save_roll", ability="CON", dc=14, target="WEAPON_INTEGRITY", fail="WEAPON_UNUSABLE"),
            _effect("ON_MISS", "primitive:damage", dice="1d6", damage_type="UNAVOIDABLE", target="SELF"),
        ),
        primitive_ids=("primitive:attack_roll", "primitive:damage", "primitive:save_roll", "primitive:apply_condition", "primitive:remove_condition", "primitive:spend_resource"),
        fidelity_consequence="Executes First Arm as the exact high-risk standalone release, including self/weapon checks and state consumption.",
    )
    auth, loc = _authority(A, "Complete_Action_Surface.json / ACT_PAIRED_STRIKE")
    updates["action:an_eui.paired_strike"] = dict(
        source_authority=auth, source_locator=loc,
        prerequisites=("USED_ATTACK_ACTION_WITH_LIGHT_BI_SHOU", "BONUS_ACTION_AVAILABLE"),
        effects=(
            _effect("ON_HIT", "primitive:gain_resource", resource_id="resource:an_eui.severance_edge", amount=1, once_per_round=True, after_hit=True),
            _effect("ALWAYS", "primitive:gain_resource", resource_id="resource:an_eui.martial_focus", amount=1, condition="BOTH_PAIRED_WEAPONS_HIT_AFTER_ANY_EXPENDITURE"),
        ),
        primitive_ids=("primitive:attack_roll", "primitive:damage", "primitive:gain_resource"),
        fidelity_consequence="Preserves the Light-weapon prerequisite and paired-rhythm resource loop without requiring the same target.",
    )
    auth, loc = _authority(A, "Complete_Action_Surface.json / ACT_RUIN_TEMPERED_ARMAMENT_QUICK and ACT_RUIN_TEMPERED_ARMAMENT")
    updates["action:an_eui.ruin_tempered_armament_quick"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="OWNED_WEAPON_INSTANCE", reach_ft=0, requires_line_of_sight=False),
        costs=(), duration=_duration("CONCENTRATION_OR_10_ROUNDS", source=True), concentration=True,
        effects=(
            _effect("ALWAYS", "primitive:apply_condition", condition_id="condition:an_eui.ruin_tempered", targets=1, optional_second_weapon_cost={"resource_id":"resource:an_eui.stamina","amount":1}),
        ),
        primitive_ids=("primitive:apply_condition", "primitive:add_modifier", "primitive:schedule_expiration", "primitive:spend_resource"),
        fidelity_consequence="Allows free single-weapon or 1-Stamina paired imbuement and correctly replaces prior concentration.",
    )
    auth, loc = _authority(A, "Complete_Action_Surface.json / ACT_DESTRUCTION_BLAST")
    updates["action:an_eui.scouring_destruction_blast"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(
            _effect("ON_HIT", "primitive:damage", base="2d6", optional_deepen={"cost":"1_STAMINA","damage":"3d6"}),
            _effect("ON_HIT", "primitive:save_roll", ability="DEX", dc=14, on_fail=["REACTION_DENIED_UNTIL_AN_NEXT_TURN", "CHOOSE_BREAK_THE_GUARD"], on_success="NO_RIDERS_DAMAGE_REMAINS"),
        ),
        duration=_duration("RIDERS_START_OF_AN_EUI_NEXT_TURN", source=True, target=True),
        primitive_ids=("primitive:attack_roll", "primitive:damage", "primitive:save_roll", "primitive:apply_condition", "primitive:add_modifier", "primitive:spend_resource", "primitive:schedule_expiration"),
        fidelity_consequence="Preserves An Eui's choice to deepen damage and the exact failed-save guard-opening riders.",
    )
    auth, loc = _authority(A, "Foundation_Detail_Ledger.json / Severance Edge")
    updates["passive:an_eui.severance_edge"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ON_HIT", "primitive:gain_resource", resource_id="resource:an_eui.severance_edge", amount=1, once_per_round=True, qualifying="WEAPON_OR_CUTTING_TECHNIQUE", same_event_spend=False),),
        duration=_duration("END_OF_AN_EUI_NEXT_TURN", source=True),
        primitive_ids=("primitive:gain_resource", "primitive:schedule_expiration"),
        fidelity_consequence="Preserves once-per-round delayed Severance generation and expiration refresh.",
    )
    auth, loc = _authority(A, "Foundation_Detail_Ledger.json / Sheath-Bone Guard")
    updates["reaction:an_eui.sheath_bone_guard"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="SELF", requires_line_of_sight=False),
        effects=(_effect("ON_DAMAGE_COMMIT", "primitive:resolve_reaction", reduction=6, damage_packet="ANY_SELF_DAMAGE", floor_zero=True),),
        primitive_ids=("primitive:spend_resource", "primitive:resolve_reaction"),
        fidelity_consequence="Spends a previously generated Edge to reduce any self damage by PB plus cultivation modifier (6).",
    )
    for rid, locator, effect, status in [
        ("resource:an_eui.destruction_dice", "Complete_Action_Surface.json / ACT_DESTRUCTION_BLAST", {"current":2,"maximum":2,"role":"SCALING_ENTITLEMENT_NOT_SPENT","blast_base_dice":2,"deepened_dice":3}, MechanicsLockStatus.LOCKED_TRACKED_PASSIVE),
        ("resource:an_eui.martial_focus", "Complete_Action_Surface.json / paired rhythm and Recorded Arts", {"current":1,"maximum":1,"gain":"BOTH_PAIRED_WEAPONS_HIT_AFTER_EXPENDITURE","selected_gate2_spend":"NONE"}, MechanicsLockStatus.LOCKED_TRACKED_PASSIVE),
        ("resource:an_eui.severance_edge", "Foundation_Detail_Ledger.json / foundation_resource", {"current":0,"maximum":1,"gain":"ONCE_PER_ROUND_AFTER_QUALIFYING_HIT","expires":"END_OF_AN_NEXT_TURN","same_event_spend":False}, MechanicsLockStatus.LOCKED_EXECUTABLE),
    ]:
        auth, loc = _authority(A, locator)
        updates[rid] = dict(source_authority=auth, source_locator=loc, status=status,
                            effects=(_effect("ALWAYS", "primitive:gain_resource", **effect),),
                            primitive_ids=() if status == MechanicsLockStatus.LOCKED_TRACKED_PASSIVE else ("primitive:gain_resource","primitive:spend_resource","primitive:schedule_expiration"),
                            fidelity_consequence="Tracks the exact An Eui resource lifecycle and permits only source-declared uses.")

    # Lee Jia.
    auth, loc = _authority(L, "Complete_Action_Surface.json / ACT_LIGHTNING_LASH and ACT_GATHER_CHARGE")
    updates["action:lee_jia.lightning_lash"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True, geometry="70 feet only after at least 10 feet Spark Step movement this turn"),
        duration=_duration("START_OF_LEE_JIA_NEXT_TURN", source=True, target=True),
        effects=(
            _effect("ON_HIT", "primitive:apply_condition", choose_one=["CHARGE_CREATE", "JOLT_NO_REACTIONS_AGAINST_LEE", "FLASH_DENY_UNSEEN_BENEFITS_AGAINST_LEE", "ARC_3_LIGHTNING_SECONDARY_WITHIN_5"]),
        ),
        primitive_ids=("primitive:attack_roll", "primitive:damage", "primitive:apply_condition", "primitive:gain_resource", "primitive:schedule_expiration"),
        fidelity_consequence="Charge is created after hit resolution; Lash never silently discharges unrelated Charges.",
    )
    auth, loc = _authority(L, "Complete_Action_Surface.json / ACT_RA_AURA_READING_COUNTERCURRENT; State_Effect_Registry.json / STATE_COUNTERCURRENT_READ")
    updates["talent:lee_jia.aura_reading_countercurrent"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="VISIBLE_MAINTAINED_PATTERN", range_ft=30, requires_line_of_sight=True),
        duration=_duration("END_OF_LEE_JIA_NEXT_TURN", source=True),
        effects=(
            _effect("ALWAYS", "primitive:apply_condition", condition="COUNTERCURRENT_READ", fact_scope="ONE_SOURCE_LIMITED_FACT", concealed_check={"bonus":6,"dc":14}, next_check="ADVANTAGE_IDENTIFY_OR_PREDICT_SAME_PATTERN"),
        ),
        primitive_ids=("primitive:apply_condition", "primitive:add_modifier", "primitive:schedule_expiration"),
        fidelity_consequence="Makes Jia's reading tactical and inspectable without granting exact hidden statistics or prophecy.",
    )
    auth, loc = _authority(L, "State_Effect_Registry.json / STATE_LIGHTNING_CHARGE; Complete_Action_Surface.json / ACT_GATHER_CHARGE")
    updates["resource:lee_jia.lightning_charge"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ALWAYS", "primitive:gain_resource", storage="TARGETED_STATE_SELF_OBJECT_WEAPON_WILLING_CREATURE_OR_SPACE", maximum=3, expiration="START_OF_LEE_NEXT_TURN", over_cap="END_EXISTING_CHARGE_CHOSEN_BY_LEE", discharge={"weapon":"PB_LIGHTNING_ON_NEXT_HIT","self":"ADVANTAGE_NEXT_QUALIFYING_DEX_SAVE","space":"3_LIGHTNING_FIRST_ENTRY"}),),
        primitive_ids=("primitive:gain_resource", "primitive:remove_condition", "primitive:damage", "primitive:add_modifier", "primitive:schedule_expiration"),
        fidelity_consequence="Tracks Charges on exact targets, caps them at three, and separates creation from source-specific discharge.",
    )
    auth, loc = _authority(L, "Complete_Action_Surface.json / ACT_DASH, ACT_DISENGAGE, paired focus records")
    updates["resource:lee_jia.martial_focus"] = dict(
        source_authority=auth, source_locator=loc, status=MechanicsLockStatus.LOCKED_TRACKED_PASSIVE,
        effects=(_effect("ALWAYS", "primitive:gain_resource", current=1, maximum=1, recovery="DASH_OR_DISENGAGE_ACTION_IF_ABSENT", selected_gate2_spend="NONE"),),
        primitive_ids=(),
        fidelity_consequence="Retains the exact focus state without inventing a spend on the accepted Gate 2 action surface.",
    )
    auth, loc = _authority(L, "Canonical_Stats_Resource_Block.json and Complete_Action_Surface.json")
    updates["resource:lee_jia.qi"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ALWAYS", "primitive:spend_resource", current=18, maximum=18, legal_spends={"reaction:ling_qi.qi_armor":"NOT_OWNER", "reaction:lee_jia.qi_armor":2, "OTHER_SELECTED_GATE2_ACTIONS":"AS_PROFILED"}),),
        primitive_ids=("primitive:spend_resource", "primitive:gain_resource"),
        fidelity_consequence="Binds Jia's 18 Qi to declared action and reaction costs only.",
    )
    auth, loc = _authority(L, "Foundation/Passive records / Weak Reed Common Expression")
    updates["passive:lee_jia.reed_flex"] = dict(
        source_authority=auth, source_locator=loc, status=MechanicsLockStatus.LOCKED_NO_GATE2_USE,
        effects=(), primitive_ids=(),
        fidelity_consequence="The exact package marks the active Reed Flex expression unavailable; its passive speed contribution is already included in Jia's 45-foot speed.",
    )

    # Ling Qi.
    auth, loc = _authority(Q, "Complete_Action_Surface.json / ACT_DISSONANT_NOTE")
    updates["action:ling_qi.dissonant_note"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("END_OF_TARGET_NEXT_TURN_OR_CONSUMED", target=True),
        effects=(
            _effect("ON_SAVE_FAIL", "primitive:damage", dice="2d6+4", damage_type="PSYCHIC"),
            _effect("ON_SAVE_FAIL", "primitive:add_modifier", target="NEXT_ATTACK", operation="DISADVANTAGE", consumed=True),
            _effect("ON_SAVE_SUCCESS", "primitive:damage", dice="HALF_OF_2d6+4_FLOOR", damage_type="PSYCHIC"),
        ),
        primitive_ids=("primitive:spend_resource", "primitive:save_roll", "primitive:damage", "primitive:add_modifier", "primitive:remove_modifier", "primitive:schedule_expiration"),
        fidelity_consequence="Preserves half damage on success and the failed-save one-attack disruption window.",
    )
    auth, loc = _authority(Q, "Complete_Action_Surface.json / ACT_FGT_FORGOTTEN_VALE_NOCTURNE; State_Effect_Registry.json")
    updates["action:ling_qi.forgotten_vale_nocturne"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("CONCENTRATION_OR_10_ROUNDS_OR_DISPERSED", source=True), concentration=True,
        effects=(
            _effect("ALWAYS", "primitive:create_zone", center="VISIBLE_POINT_WITHIN_60", radius_ft=20, sight="HEAVILY_OBSCURED_SIGHT_RELIANT", difficult_terrain=False),
            _effect("ALWAYS", "primitive:save_roll", timing=["ZONE_APPEARS", "END_OF_AFFECTED_TURN_WHILE_INSIDE"], once_per_timing=True, ability="WIS", dc=15, fail={"speed_delta":-10,"reaction_denied":True,"perception_disadvantage":True}, success="NO_HINDRANCE_OBSCUREMENT_REMAINS", leave_removes_hindrance=True),
        ),
        primitive_ids=("primitive:spend_resource", "primitive:create_zone", "primitive:remove_zone", "primitive:save_roll", "primitive:add_modifier", "primitive:remove_modifier", "primitive:apply_condition", "primitive:remove_condition", "primitive:schedule_expiration"),
        fidelity_consequence="Executes the exact smoke-and-music control zone without adding unprinted damage or difficult terrain.",
    )
    auth, loc = _authority(Q, "Complete_Action_Surface.json / ACT_KEEP_THE_MEASURE; State_Effect_Registry.json")
    updates["action:ling_qi.keep_the_measure"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="SELF_AND_ONE_PERCEIVING_CREATURE", range_ft=None, requires_line_of_sight=False, geometry="PERCEIVABLE_PERFORMANCE"),
        duration=_duration("10_ROUNDS_OR_INCAPACITATED_OR_SOUND_SUPPRESSED", source=True),
        effects=(
            _effect("ALWAYS", "primitive:apply_condition", condition="KEEP_THE_MEASURE", enables=["reaction:ling_qi.rhythmic_guard"]),
            _effect("ALWAYS", "primitive:grant_temp_hp", amount=7, target="ONE_PERCEIVING_CREATURE", limit="ONCE_PER_SHORT_REST"),
        ),
        primitive_ids=("primitive:apply_condition", "primitive:grant_temp_hp", "primitive:schedule_expiration"),
        fidelity_consequence="Preserves Ling's rhythmic support posture and a single exact 7-temp-HP grant.",
    )
    auth, loc = _authority(Q, "Complete_Action_Surface.json / ACT_SOUND_RESONANT_NOTE")
    updates["action:ling_qi.sound_resonant_note"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("START_OF_LING_QI_NEXT_TURN_OR_CONSUMED", source=True, target=True),
        effects=(
            _effect("ON_SAVE_FAIL", "primitive:damage", dice="1d6+4", damage_type="PSYCHIC_OR_THUNDER_CHOSEN"),
            _effect("ON_SAVE_FAIL", "primitive:add_modifier", target="NEXT_ATTACK", operation="SUBTRACT_1d4", consumed=True),
            _effect("ON_SAVE_SUCCESS", "primitive:damage", dice="HALF_OF_1d6+4_FLOOR", damage_type="PSYCHIC_OR_THUNDER_CHOSEN"),
        ),
        primitive_ids=("primitive:spend_resource", "primitive:save_roll", "primitive:damage", "primitive:add_modifier", "primitive:remove_modifier", "primitive:schedule_expiration"),
        fidelity_consequence="Preserves the successful-save half damage and the failed-save one-attack penalty.",
    )
    auth, loc = _authority(Q, "Foundation_Detail_Ledger.json and Complete_Action_Surface.json / Mirror Trace")
    updates["passive:ling_qi.mirror_trace"] = dict(
        source_authority=auth, source_locator=loc,
        duration=_duration("END_OF_LING_QI_NEXT_TURN", source=True),
        effects=(_effect("ALWAYS", "primitive:gain_resource", once_per_round=True, qualifying="HOSTILE_MISS_OR_FAILED_SAVE_WITHIN_FIXED_MIRROR_SCOPE", amount=1, maximum=1, same_event_spend=False),),
        primitive_ids=("primitive:gain_resource", "primitive:schedule_expiration"),
        fidelity_consequence="Keeps the narrow Dream-Mirror trigger scope instead of treating every defense as a Trace.",
    )
    auth, loc = _authority(Q, "Complete_Action_Surface.json / Mirror Trace actions; State_Effect_Registry.json")
    updates["resource:ling_qi.mirror_trace"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ALWAYS", "primitive:spend_resource", current=0, maximum=1, expiration="END_OF_LING_NEXT_TURN", uses={"REFLECTION_CUT":"+3_PSYCHIC_OR_FORCE_LATER_HIT_OR_FAILED_SAVE","FALSE_IMAGE_GUARD":"REACTION_REDUCE_7","TRUE_NAME_WITNESS":"ADD_PB_TO_FIXED_SCOPE_CHECK_OR_SAVE"}, same_event_spend=False),),
        primitive_ids=("primitive:gain_resource", "primitive:spend_resource", "primitive:damage", "primitive:resolve_reaction", "primitive:schedule_expiration"),
        fidelity_consequence="Makes all exact Mirror Trace spends available without broadening the source's fixed scope.",
    )
    auth, loc = _authority(Q, "Complete_Action_Surface.json / Smoke Trace and Smoke Veil")
    updates["resource:ling_qi.smoke_trace"] = dict(
        source_authority=auth, source_locator=loc, status=MechanicsLockStatus.LOCKED_NO_GATE2_USE,
        effects=(), primitive_ids=(),
        fidelity_consequence="Smoke Trace requires Smoke Veil, which is not in the accepted Gate 1 projection for this fight; no Gate 2 candidate can generate it.",
    )
    auth, loc = _authority(Q, "Character resource records / Martial Focus")
    updates["resource:ling_qi.martial_focus"] = dict(
        source_authority=auth, source_locator=loc, status=MechanicsLockStatus.LOCKED_TRACKED_PASSIVE,
        effects=(_effect("ALWAYS", "primitive:gain_resource", current=1, maximum=1, independent_recovery="NONE", selected_gate2_spend="NONE"),), primitive_ids=(),
        fidelity_consequence="Retains Ling's exact focus state without inventing a spend on the accepted Gate 2 projection.",
    )

    # Bai Meizhen and Cui.
    auth, loc = _authority(B, "Complete_Action_Surface.json / ACT_FT_BLACKWATER_SERPENT_COURT")
    updates["action:bai_meizhen.blackwater_serpent_court"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="POINT_OR_CELL", range_ft=60, radius_ft=20, requires_line_of_sight=True, geometry="20_FOOT_RADIUS_SPHERE"),
        duration=_duration("CONCENTRATION_OR_10_ROUNDS_OR_DISPERSED", source=True), concentration=True,
        effects=(
            _effect("ALWAYS", "primitive:create_zone", hostile_difficult_terrain=True, allies_immune_by_target_relationship=True),
            _effect("ALWAYS", "primitive:save_roll", timing=["ZONE_APPEARS", "FIRST_ENTRY_PER_TURN", "TURN_START_PER_TURN"], once_per_actor_turn=True, ability="CON", dc=15, fail={"damage":"2d6+4_POISON","dose":1,"reaction_denied":"START_OF_TARGET_NEXT_TURN"}, success={"damage":"HALF_FLOOR","dose":0,"reaction_denied":False}),
        ),
        primitive_ids=("primitive:spend_resource", "primitive:create_zone", "primitive:remove_zone", "primitive:save_roll", "primitive:damage", "primitive:apply_condition", "primitive:schedule_expiration"),
        fidelity_consequence="Implements the exact hostile-only court, once-per-turn pulse, Dose, and reaction denial.",
    )
    auth, loc = _authority(B, "Complete_Action_Surface.json / ACT_COMP_COMMAND_CUI; Companion_Execution_Coverage.json")
    updates["action:bai_meizhen.command_cui"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="OWNED_COMPANION", range_ft=120, requires_line_of_sight=False, geometry="BOND_COMMUNICATION"),
        effects=(_effect("ALWAYS", "primitive:resolve_reaction", nested_activation={"actor":"bai_cui","timing":"IMMEDIATELY_AFTER_BAI","movement_ft":40,"action":1,"reaction":1,"bonus_action":0}, invalid_default="DODGE_AND_STAY_NEAR_BAI", bai_inactive="GUARD_AND_RESCUE"),),
        primitive_ids=("primitive:resolve_reaction", "primitive:movement"),
        fidelity_consequence="Keeps Cui first-class with her own movement/action and exact command/default behavior.",
    )
    auth, loc = _authority(B, "Complete_Action_Surface.json / ACT_ART_NUMBING_VENOM_PALM")
    updates["action:bai_meizhen.numbing_venom_palm"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", reach_ft=5, requires_line_of_sight=True),
        damage=DamageSpec(dice=DiceExpression(count=1, sides=6, modifier=4), damage_type="POISON"),
        duration=_duration("START_OF_BAI_MEIZHEN_NEXT_TURN", source=True, target=True),
        effects=(
            _effect("ON_SAVE_FAIL", "primitive:apply_condition", dose_mark=1, speed_delta=-10, reaction_denied=True),
            _effect("ON_SAVE_SUCCESS", "primitive:add_modifier", optional_lesser_result=True, speed_delta=-5),
        ),
        primitive_ids=("primitive:spend_resource", "primitive:attack_roll", "primitive:damage", "primitive:save_roll", "primitive:apply_condition", "primitive:add_modifier", "primitive:schedule_expiration"),
        fidelity_consequence="Executes the exact touch strike, Dose, failed-save numb, and fixed lesser success result.",
    )
    auth, loc = _authority(B, "Rules_Selection_Packets.json / Water Whip; Complete_Action_Surface.json / ACT_WATER_LASH")
    updates["action:bai_meizhen.water_whip"] = dict(
        source_authority=auth, source_locator=loc,
        profile_kind=ProfileKind.ON_HIT_OPTION, economy=Economy.ON_HIT_OPTION,
        targeting=TargetingSpec(target_kind="WATER_LASH_HIT_TARGET", requires_line_of_sight=False),
        prerequisites=("CURRENT_TRANSACTION_WATER_LASH_HIT", "TRIGGER_WINDOW_OPEN"),
        costs=(ResourceCost(resource_id="resource:bai_meizhen.qi", amount=1, timing="ON_FOLLOW_UP_SELECTION", optional=True),),
        save=SaveSpec(ability="STR", dc=15),
        duration=_duration("END_OF_BAI_MEIZHEN_NEXT_TURN", source=True, target=True),
        effects=(
            _effect("ALWAYS", "primitive:apply_condition", condition_id="condition:core.soaked"),
            _effect("ON_SAVE_FAIL", "primitive:apply_condition", condition_id="condition:core.grappled", escape={"economy":"ACTION","check":["ATHLETICS","ACROBATICS"],"dc":15}, ends=["DURATION","ESCAPE","WATER_SUPPRESSED"]),
            _effect("ON_SAVE_SUCCESS", "primitive:remove_condition", condition_id="condition:core.grappled", no_effect_if_absent=True),
        ),
        primitive_ids=("primitive:spend_resource", "primitive:save_roll", "primitive:apply_condition", "primitive:remove_condition", "primitive:schedule_expiration"),
        fidelity_consequence="Preserves Water Whip as a post-hit optional rider; no Qi is charged on a miss or declined rider.",
    )
    auth, loc = _authority(B, "Complete_Action_Surface.json / ACT_TALENT_SPIRIT_INTERCESSION")
    updates["reaction:bai_meizhen.spirit_intercession"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="OWNED_COMPANION", range_ft=30, requires_line_of_sight=True),
        effects=(
            _effect("ALWAYS", "primitive:resolve_reaction", attack_modifier="DISADVANTAGE", re_evaluate=True, if_still_hits={"choose":"SPEND_1_QI_OR_GAIN_1_BOND_STRAIN"}),
        ),
        primitive_ids=("primitive:resolve_reaction", "primitive:spend_resource", "primitive:gain_resource"),
        fidelity_consequence="Protects Cui by imposing disadvantage rather than substituting targets or inventing damage prevention.",
    )
    auth, loc = _authority(B, "Companion_Execution_Coverage.json / companion bai_cui")
    updates["creature:bai_cui"] = dict(
        source_authority=auth, source_locator=loc,
        targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", reach_ft=5, requires_line_of_sight=True),
        attack=AttackSpec(bonus=6), post_hit_save=SaveSpec(ability="CON", dc=15),
        damage=DamageSpec(dice=DiceExpression(count=2, sides=8, modifier=3), damage_type="PIERCING"),
        effects=(
            _effect("ON_SAVE_FAIL", "primitive:apply_condition", condition_id="condition:core.dose_marked", stacks=1, once_per_turn=True),
            _effect("ALWAYS", "primitive:schedule_expiration", actor_state={"ac":15,"hp":40,"speed":{"walk":40,"climb":40,"swim":20},"primary":False,"initiative":"AFTER_BAI"}, uncommanded="DODGE_STAY_NEAR_BAI", bai_inactive="GUARD_AND_RESCUE"),
        ),
        primitive_ids=("primitive:attack_roll", "primitive:damage", "primitive:save_roll", "primitive:apply_condition", "primitive:movement", "primitive:schedule_expiration"),
        fidelity_consequence="Cui is a complete first-class actor with exact stats, venom, command timing, and autonomous guard behavior.",
    )
    auth, loc = _authority(B, "Companion and subpath records / Serpent Kinship")
    updates["passive:bai_meizhen.serpent_kinship"] = dict(
        source_authority=auth, source_locator=loc, status=MechanicsLockStatus.LOCKED_TRACKED_PASSIVE,
        effects=(_effect("ALWAYS", "primitive:add_modifier", effects=["POISON_RESISTANCE", "CUI_BOND_COMMUNICATION", "COMPANION_CONSENT_AND_CARE_OBLIGATIONS"]),),
        primitive_ids=(),
        fidelity_consequence="Retains Bai's poison lineage and bonded-companion relationship without inventing a free combat trigger.",
    )
    auth, loc = _authority(B, "Character_Master_Ledger.json / RES_ANCESTRAL_RESONANCE; Modifier_Ledger.json / MOD_BLOODLINE_STRIKE_POISON")
    updates["resource:bai_meizhen.ancestral_resonance"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ALWAYS", "primitive:gain_resource", current=0, maximum=3, gain="ONCE_PER_TURN_AFTER_GRAPPLE_RESTRAIN_POISON_MARK_OR_SUCCESSFUL_TRACK_HOSTILE", reset="END_OF_MATCH_SCENE", spend={"amount":1,"once_per_turn":True,"trigger":"AUTHORIZED_QI_FEATURE_DEALS_DAMAGE","effect":"+1d8_POISON_ONE_TARGET"}),),
        primitive_ids=("primitive:gain_resource", "primitive:spend_resource", "primitive:damage"),
        fidelity_consequence="Preserves Bai's lineage accumulation and exact once-per-turn Bloodline Strike spend.",
    )
    auth, loc = _authority(B, "Companion stat block and Spirit Intercession / RES_CUI_BOND_STRAIN")
    updates["resource:bai_meizhen.cui_bond_strain"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ALWAYS", "primitive:gain_resource", current=0, maximum=3, gain=["SPIRIT_INTERCESSION_HIT_WITHOUT_QI", "CONSENT_OR_NEEDLESS_DANGER_ADJUDICATION"], threshold_3="BOND_CRISIS_BEFORE_NORMAL_MANIFESTATION", recovery="OUT_OF_GATE2_OFFERING_OR_REST"),),
        primitive_ids=("primitive:gain_resource",),
        fidelity_consequence="Tracks the exact companion cost and crisis threshold; no ordinary combat shortcut clears it.",
    )
    auth, loc = _authority(B, "Foundation_Detail_Ledger.json / Moon-Sea Radiance")
    updates["resource:bai_meizhen.moon_sea_radiance"] = dict(
        source_authority=auth, source_locator=loc,
        effects=(_effect("ALWAYS", "primitive:gain_resource", current=0, maximum=1, gain="ONCE_PER_ROUND_AFTER_ELIGIBLE_VISIBLE_MANIFESTATION_FAILED_HOSTILE_CONTEST_OR_PROTECTION_EVENT", expiration="END_OF_BAI_NEXT_TURN", same_event_spend=False, uses={"SEA_MOON_INTERPOSITION":"REACTION_REDUCE_7_PLUS_3_DIRECT_CONTEST","MOON_DISC_DESCENT":"+7_DAMAGE_AND_SPEED_MINUS_10","SEA_RISEN_BEARING":"BONUS_ACTION_TEMP_HP_7_AND_10FT_EMANATION"}),),
        primitive_ids=("primitive:gain_resource", "primitive:spend_resource", "primitive:damage", "primitive:resolve_reaction", "primitive:grant_temp_hp", "primitive:add_modifier", "primitive:schedule_expiration"),
        fidelity_consequence="Keeps the complete Awakened Foundation resource and its three exact spend forms available to manual choices.",
    )

    return updates


def build_reconciled_gate2_lock() -> ExecutableMechanicsLock:
    base = build_gate2a_lock()
    update_map = _updates()
    profiles: list[ExecutableMechanicProfile] = []
    for profile in base.profiles:
        common = _exact_authority_for_profile(profile)
        specific = update_map.get(profile.source_definition_id, {})
        merged = {**common, **specific}
        if profile.status == MechanicsLockStatus.MATERIAL_UNRESOLVED:
            if not specific:
                raise ValueError(f"unresolved profile lacks exact reconciliation: {profile.source_definition_id}")
            profiles.append(_resolved(profile, **merged))
        else:
            profiles.append(profile.model_copy(update=merged) if merged else profile)
    unresolved = [p.source_definition_id for p in profiles if p.status == MechanicsLockStatus.MATERIAL_UNRESOLVED]
    if unresolved:
        raise ValueError(f"reconciliation left material unresolved profiles: {unresolved}")
    source_identities = (
        SourceBundleIdentity(role="SOLE_FACTORY_SOURCE_PARENT", filename="Tianxia_Factory_R6_1_Hybrid_Combat_Gate2A_Blocked_Source_Checkpoint.zip", sha256=GATE2A_PARENT_SHA256, size_bytes=2300605, availability="VERIFIED", note="Exact blocked Gate 2A continuation parent; Gate 1 was not re-extracted as source."),
        SourceBundleIdentity(role="CHARACTER_AUTHORITY_BUNDLE", filename="Tianxia_CL5_Four_Character_Gate2_Authority_Bundle_R1.zip", sha256=CHARACTER_AUTHORITY_BUNDLE_SHA256, size_bytes=2613333, availability="VERIFIED", note="Authenticated container for the exact four fight-test character packages."),
        SourceBundleIdentity(role="CONTINUATION_DIRECTIVE", filename="Tianxia_Gate2A_Four_Character_Continuation_Prompt_R1.md", sha256=CONTINUATION_PROMPT_SHA256, size_bytes=1945, availability="VERIFIED", note="Authorizes separate normal-use universal defaults and direct Gate 2B continuation after zero gaps."),
        *tuple(SourceBundleIdentity(role=f"CHARACTER_AUTHORITY_{key.upper()}", filename=value[0], sha256=value[1], size_bytes=value[2], availability="VERIFIED", note="Exact inner character-rule authority package.") for key, value in sorted(CHARACTER_PACKAGES.items())),
    )
    lock = ExecutableMechanicsLock(
        gate1_registry_snapshot_sha256=base.gate1_registry_snapshot_sha256,
        source_bundle_identities=source_identities,
        allowed_primitive_ids=ALLOWED_PRIMITIVES,
        profiles=tuple(sorted(profiles, key=lambda p: p.source_definition_id)),
        material_unresolved_count=0,
        status=LockOverallStatus.PASS,
    )
    # Re-parse the complete document so model_copy updates receive the same strict
    # validation as externally loaded locks.
    return ExecutableMechanicsLock.model_validate(lock.model_dump(mode="json", by_alias=True))


def write_reconciled_gate2_lock(path: Path) -> ExecutableMechanicsLock:
    return write_executable_mechanics_lock(build_reconciled_gate2_lock(), path)
