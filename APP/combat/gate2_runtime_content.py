from __future__ import annotations

from .gate2_runtime_models import (
    ActionDefinition,
    ActorTemplate,
    DiceSpec,
    EconomyKind,
    ResourceDefinition,
    SaveDefinition,
)


AN = "an_eui_early_book1_cl5"
LEE = "lee_jia_early_book1_cl5"
LING = "ling_qi_early_outer_sect_cl5"
BAI = "bai_meizhen_early_outer_sect_cl5"
CUI = "bai_cui"

PROJECTION_HASHES = {
    AN: "a5fd4e994295c140e31a62338d39b12c417cba7052b601f73c36cf37eacedebd",
    LEE: "6a729a2d498b60f6a3a11c160084384b187f430333ac95817eb17e9c6053717d",
    LING: "8ff581145ec4a3ad03fd3ee4117daca238d40b929ef58199d7eb9624dbb096d9",
    BAI: "ef7762104aac5ac0df4abbaae0f3627cdc4a3cf0cdc6edcc057444494680db35",
}


def _resources(*rows: tuple[str, int, int]) -> tuple[ResourceDefinition, ...]:
    return tuple(ResourceDefinition(resource_id=rid, initial=initial, maximum=maximum) for rid, initial, maximum in rows)


ACTORS: dict[str, ActorTemplate] = {
    AN: ActorTemplate(
        entity_id=AN, display_name="An Eui", team_id="team:an_eui_lee_jia", primary_combatant=True,
        projection_sha256=PROJECTION_HASHES[AN], armor_class=17, maximum_hp=55, speed_ft=30,
        initiative_bonus=4, dexterity_score=18, proficiency_bonus=3,
        saving_throws={"STR":-1,"DEX":4,"CON":3,"INT":0,"WIS":1,"CHA":0},
        resources=_resources(
            ("resource:an_eui.stamina",21,21),
            ("resource:an_eui.battle_hands",3,3),
            ("resource:an_eui.destruction_dice",2,2),
            ("resource:an_eui.martial_focus",1,1),
            ("resource:an_eui.severance_edge",0,1),
        ),
        action_ids=(
            "action:an_eui.paired_bi_shou_assault", "action:an_eui.paired_strike",
            "action:an_eui.ruin_tempered_armament_quick", "action:an_eui.scouring_destruction_blast",
            "action:an_eui.first_arm", "talent:an_eui.stomping_step",
        ),
        reaction_ids=("reaction:an_eui.sheath_bone_guard", "reaction:core.stamina_guard"),
    ),
    LEE: ActorTemplate(
        entity_id=LEE, display_name="Lee Jia", team_id="team:an_eui_lee_jia", primary_combatant=True,
        projection_sha256=PROJECTION_HASHES[LEE], armor_class=14, maximum_hp=33, speed_ft=45,
        initiative_bonus=4, dexterity_score=18, proficiency_bonus=3,
        saving_throws={"STR":-1,"DEX":4,"CON":1,"INT":3,"WIS":0,"CHA":0},
        resources=_resources(
            ("resource:lee_jia.qi",18,18),
            ("resource:lee_jia.lightning_charge",0,3),
            ("resource:lee_jia.martial_focus",1,1),
            ("resource:lee_jia.prepared_talismans",8,8),
        ),
        action_ids=(
            "action:lee_jia.gather_charge", "action:lee_jia.lightning_lash",
            "action:lee_jia.hidden_sleeve_shock_talisman", "talent:lee_jia.aura_reading_countercurrent",
        ),
        reaction_ids=(),
    ),
    LING: ActorTemplate(
        entity_id=LING, display_name="Ling Qi", team_id="team:ling_qi_bai_meizhen", primary_combatant=True,
        projection_sha256=PROJECTION_HASHES[LING], armor_class=13, maximum_hp=38, speed_ft=30,
        initiative_bonus=3, dexterity_score=16, proficiency_bonus=3,
        saving_throws={"STR":-1,"DEX":3,"CON":2,"INT":-1,"WIS":0,"CHA":4},
        resources=_resources(
            ("resource:ling_qi.qi",23,23),
            ("resource:ling_qi.martial_focus",1,1),
            ("resource:ling_qi.mirror_trace",0,1),
            ("resource:ling_qi.smoke_trace",0,3),
        ),
        action_ids=(
            "action:ling_qi.forgotten_vale_nocturne", "action:ling_qi.dissonant_note",
            "action:ling_qi.sound_resonant_note", "action:ling_qi.music_resonant_note",
            "action:ling_qi.keep_the_measure",
        ),
        reaction_ids=("reaction:ling_qi.qi_armor", "reaction:ling_qi.rhythmic_guard"),
    ),
    BAI: ActorTemplate(
        entity_id=BAI, display_name="Bai Meizhen", team_id="team:ling_qi_bai_meizhen", primary_combatant=True,
        projection_sha256=PROJECTION_HASHES[BAI], armor_class=16, maximum_hp=38, speed_ft=30,
        initiative_bonus=2, dexterity_score=14, proficiency_bonus=3,
        saving_throws={"STR":-1,"DEX":2,"CON":2,"INT":0,"WIS":1,"CHA":4},
        resources=_resources(
            ("resource:bai_meizhen.qi",23,23),
            ("resource:bai_meizhen.ancestral_resonance",0,3),
            ("resource:bai_meizhen.cui_bond_strain",0,3),
            ("resource:bai_meizhen.moon_sea_radiance",0,1),
        ),
        action_ids=(
            "action:bai_meizhen.blackwater_serpent_court", "action:bai_meizhen.command_cui",
            "action:bai_meizhen.numbing_venom_palm", "action:bai_meizhen.water_lash",
            "action:bai_meizhen.sea_risen_bearing",
        ),
        reaction_ids=("reaction:bai_meizhen.water_shield", "reaction:bai_meizhen.spirit_intercession"),
    ),
    CUI: ActorTemplate(
        entity_id=CUI, display_name="Cui", team_id="team:ling_qi_bai_meizhen", primary_combatant=False,
        owner_id=BAI, armor_class=15, maximum_hp=40, speed_ft=40,
        initiative_bonus=3, dexterity_score=16, proficiency_bonus=3,
        saving_throws={"STR":1,"DEX":3,"CON":2,"INT":-2,"WIS":2,"CHA":0},
        resources=_resources(("resource:bai_meizhen.cui_bond_strain",0,3)),
        action_ids=("action:bai_cui.companion_strike",), reaction_ids=(),
    ),
}


def _action(source: str, name: str, owner: str, economy: EconomyKind, kind: str, target: str, **kw) -> ActionDefinition:
    return ActionDefinition(source_definition_id=source, display_name=name, owner_id=owner, economy=economy, resolution_kind=kind, target_kind=target, **kw)


ACTIONS: dict[str, ActionDefinition] = {
    "action:an_eui.paired_bi_shou_assault": _action(
        "action:an_eui.paired_bi_shou_assault", "Paired Bi Shou Assault", AN, EconomyKind.ACTION,
        "MULTI_ATTACK", "HOSTILE_ENTITY", reach_ft=5, attack_bonus=7, attack_count=2,
        damage=DiceSpec(count=1,sides=4,modifier=4), damage_type="PIERCING",
        parameters={"qualifies_paired_strike":True,"severance_generation":True,"basic_melee":True},
    ),
    "action:an_eui.paired_strike": _action(
        "action:an_eui.paired_strike", "Paired Strike", AN, EconomyKind.BONUS_ACTION,
        "ATTACK", "HOSTILE_ENTITY", reach_ft=5, attack_bonus=7,
        damage=DiceSpec(count=1,sides=4,modifier=4), damage_type="PIERCING",
        parameters={"requires_turn_flag":"paired_strike_enabled","severance_generation":True},
    ),
    "action:an_eui.ruin_tempered_armament_quick": _action(
        "action:an_eui.ruin_tempered_armament_quick", "Ruin-Tempered Armament — Quick", AN,
        EconomyKind.BONUS_ACTION, "STATE", "SELF", concentration=True,
        parameters={"condition":"condition:an_eui.ruin_tempered","duration_turns":10,"default_weapon":"bi_shou_primary","paired_option_cost":1},
    ),
    "action:an_eui.scouring_destruction_blast": _action(
        "action:an_eui.scouring_destruction_blast", "Scouring Destructive Blast", AN, EconomyKind.ACTION,
        "ATTACK_THEN_SAVE", "HOSTILE_ENTITY", range_ft=60, attack_bonus=6,
        damage=DiceSpec(count=2,sides=6,modifier=0), damage_type="SLASHING_DESTRUCTION",
        save=SaveDefinition(ability="DEX",dc=14),
        parameters={"deepen_cost":1,"deepen_dice_count":3,"break_guard_options":["AC_MINUS_1","NEXT_ATTACK_ADVANTAGE","NO_HALF_COVER"]},
    ),
    "action:an_eui.first_arm": _action(
        "action:an_eui.first_arm", "Six Arms — First Arm", AN, EconomyKind.ACTION,
        "FIRST_ARM", "HOSTILE_ENTITY", reach_ft=5, attack_bonus=7,
        damage=DiceSpec(count=1,sides=4,modifier=4), damage_type="SLASHING_DESTRUCTION",
        save=SaveDefinition(ability="DEX",dc=14), costs=(("resource:an_eui.stamina",3),),
        parameters={"requires_condition":"condition:an_eui.ruin_tempered","extra_damage":"3d6","self_miss_damage":"1d6","con_check_dc":14,"weapon_integrity_dc":14,"break_guard_options":["AC_MINUS_1","NEXT_ATTACK_ADVANTAGE","NO_HALF_COVER"]},
    ),
    "talent:an_eui.stomping_step": _action(
        "talent:an_eui.stomping_step", "Stomping Step", AN, EconomyKind.BONUS_ACTION,
        "STOMPING_STEP", "SELF", parameters={"options":["DASH","DISENGAGE"]},
    ),
    "action:lee_jia.gather_charge": _action(
        "action:lee_jia.gather_charge", "Gather Charge", LEE, EconomyKind.BONUS_ACTION,
        "GATHER_CHARGE", "LEGAL_CHARGE_TARGET", range_ft=60,
        parameters={"maximum":3,"expires":"START_OF_LEE_NEXT_TURN","self_spark_step_ft":10},
    ),
    "action:lee_jia.lightning_lash": _action(
        "action:lee_jia.lightning_lash", "Lightning Lash", LEE, EconomyKind.ACTION,
        "LIGHTNING_LASH", "HOSTILE_ENTITY", range_ft=60, attack_bonus=6,
        damage=DiceSpec(count=2,sides=8,modifier=6), damage_type="LIGHTNING",
        parameters={"modes":["CHARGE","JOLT","FLASH","ARC"],"spark_step_ft":5,"arc_damage":3,"extended_range_after_spark":70},
    ),
    "action:lee_jia.hidden_sleeve_shock_talisman": _action(
        "action:lee_jia.hidden_sleeve_shock_talisman", "Hidden-Sleeve Shock Talisman", LEE,
        EconomyKind.ACTION, "ATTACK", "HOSTILE_ENTITY", range_ft=60, attack_bonus=6,
        damage=DiceSpec(count=2,sides=10,modifier=6), damage_type="LIGHTNING",
        costs=(("resource:lee_jia.prepared_talismans",1),),
    ),
    "talent:lee_jia.aura_reading_countercurrent": _action(
        "talent:lee_jia.aura_reading_countercurrent", "Aura-Reading Countercurrent", LEE,
        EconomyKind.BONUS_ACTION, "COUNTERCURRENT", "VISIBLE_ACTIVE_PATTERN", range_ft=30,
        parameters={"duration":"END_OF_LEE_NEXT_TURN","benefit":"ADVANTAGE_NEXT_IDENTIFY_OR_PREDICT_SAME_PATTERN"},
    ),
    "action:ling_qi.forgotten_vale_nocturne": _action(
        "action:ling_qi.forgotten_vale_nocturne", "Forgotten Vale Nocturne", LING,
        EconomyKind.ACTION, "NOCTURNE_ZONE", "CELL", range_ft=60, radius_ft=20,
        save=SaveDefinition(ability="WIS",dc=15), costs=(("resource:ling_qi.qi",4),), concentration=True,
        parameters={"duration_turns":10,"heavily_obscured":True,"speed_delta":-10,"reaction_denied":True},
    ),
    "action:ling_qi.dissonant_note": _action(
        "action:ling_qi.dissonant_note", "Dissonant Note", LING, EconomyKind.ACTION,
        "SAVE_DAMAGE", "HOSTILE_ENTITY", range_ft=60, save=SaveDefinition(ability="WIS",dc=15),
        damage=DiceSpec(count=2,sides=6,modifier=4), damage_type="PSYCHIC", costs=(("resource:ling_qi.qi",2),),
        parameters={"success_half":True,"fail_modifier":"NEXT_ATTACK_DISADVANTAGE","expires":"END_OF_TARGET_NEXT_TURN_OR_CONSUMED"},
    ),
    "action:ling_qi.sound_resonant_note": _action(
        "action:ling_qi.sound_resonant_note", "Sound Resonant Note", LING, EconomyKind.BONUS_ACTION,
        "SAVE_DAMAGE", "HOSTILE_ENTITY", range_ft=60, save=SaveDefinition(ability="WIS",dc=15),
        damage=DiceSpec(count=1,sides=6,modifier=4), damage_type="PSYCHIC", costs=(("resource:ling_qi.qi",1),),
        parameters={"success_half":True,"fail_modifier":"NEXT_ATTACK_SUBTRACT_1D4","expires":"START_OF_LING_NEXT_TURN_OR_CONSUMED"},
    ),
    "action:ling_qi.music_resonant_note": _action(
        "action:ling_qi.music_resonant_note", "Music Resonant Note", LING, EconomyKind.ACTION,
        "ATTACK", "HOSTILE_ENTITY", range_ft=60, attack_bonus=7,
        damage=DiceSpec(count=2,sides=8,modifier=4), damage_type="PSYCHIC",
    ),
    "action:ling_qi.keep_the_measure": _action(
        "action:ling_qi.keep_the_measure", "Keep the Measure", LING, EconomyKind.BONUS_ACTION,
        "KEEP_MEASURE", "ALLY_OR_SELF", range_ft=60,
        parameters={"duration_turns":10,"temp_hp":7,"temp_hp_limit":"ONCE_PER_MATCH_GATE2","enables":"reaction:ling_qi.rhythmic_guard"},
    ),
    "action:bai_meizhen.blackwater_serpent_court": _action(
        "action:bai_meizhen.blackwater_serpent_court", "Blackwater Serpent Court", BAI,
        EconomyKind.ACTION, "BLACKWATER_ZONE", "CELL", range_ft=60, radius_ft=20,
        save=SaveDefinition(ability="CON",dc=15), damage=DiceSpec(count=2,sides=6,modifier=4),
        damage_type="POISON", costs=(("resource:bai_meizhen.qi",4),), concentration=True,
        parameters={"duration_turns":10,"hostile_difficult_terrain":True,"reaction_denied":True,"dose_on_fail":1,"success_half":True},
    ),
    "action:bai_meizhen.command_cui": _action(
        "action:bai_meizhen.command_cui", "Command Cui", BAI, EconomyKind.BONUS_ACTION,
        "COMMAND_CUI", "MODE_SPECIFIC_COMPANION_COMMAND", range_ft=120,
        parameters={"options":["STRIKE","DODGE","DASH","HOLD"],"cui_speed_ft":40},
    ),
    "action:bai_meizhen.numbing_venom_palm": _action(
        "action:bai_meizhen.numbing_venom_palm", "Numbing Venom Palm", BAI, EconomyKind.ACTION,
        "ATTACK_THEN_SAVE", "HOSTILE_ENTITY", reach_ft=5, attack_bonus=7,
        damage=DiceSpec(count=1,sides=6,modifier=4), damage_type="POISON",
        save=SaveDefinition(ability="CON",dc=15), costs=(("resource:bai_meizhen.qi",1),),
        parameters={"fail_dose":1,"fail_speed_delta":-10,"fail_reaction_denied":True,"success_speed_delta":-5,"expires":"START_OF_BAI_NEXT_TURN"},
    ),
    "action:bai_meizhen.water_lash": _action(
        "action:bai_meizhen.water_lash", "Water Lash", BAI, EconomyKind.ACTION,
        "WATER_LASH", "HOSTILE_ENTITY", range_ft=30, attack_bonus=7,
        damage=DiceSpec(count=1,sides=8,modifier=4), damage_type="BLUDGEONING",
        parameters={"soaked":True,"water_whip_rider":"action:bai_meizhen.water_whip","coiling_reach_ft":35},
    ),
    "action:bai_meizhen.sea_risen_bearing": _action(
        "action:bai_meizhen.sea_risen_bearing", "Sea-Risen Bearing", BAI, EconomyKind.BONUS_ACTION,
        "SEA_RISEN_BEARING", "SELF", costs=(("resource:bai_meizhen.moon_sea_radiance",1),),
        parameters={"temp_hp":7,"radius_ft":10,"speed_delta":-5,"expires":"START_OF_BAI_NEXT_TURN"},
    ),
    "action:bai_cui.companion_strike": _action(
        "creature:bai_cui", "Cui — Companion Strike", CUI, EconomyKind.ACTION,
        "CUI_STRIKE", "HOSTILE_ENTITY", reach_ft=5, attack_bonus=6,
        damage=DiceSpec(count=2,sides=8,modifier=3), damage_type="PIERCING",
        save=SaveDefinition(ability="CON",dc=15), parameters={"dose_on_fail":1,"once_per_turn":True},
    ),
    "system:combat.dodge": _action("system:combat.dodge","Dodge","*",EconomyKind.ACTION,"DODGE","SELF"),
    "system:combat.dash": _action("system:combat.dash","Dash","*",EconomyKind.ACTION,"DASH","SELF"),
    "system:combat.disengage": _action("system:combat.disengage","Disengage","*",EconomyKind.ACTION,"DISENGAGE","SELF"),
}

REACTION_PARAMETERS = {
    "reaction:core.stamina_guard": {"checkpoint":"DAMAGE_APPLICATION","target":"SELF","resource":"resource:an_eui.stamina","spend_min":1,"spend_max":"PB","reduction_per_spend":"1d10"},
    "reaction:an_eui.sheath_bone_guard": {"checkpoint":"DAMAGE_APPLICATION","target":"SELF","resource":"resource:an_eui.severance_edge","cost":1,"reduction":6},
    "reaction:ling_qi.qi_armor": {"checkpoint":"ATTACK_HIT_BEFORE_DAMAGE","target":"SELF","resource":"resource:ling_qi.qi","cost":2,"ac_bonus":3,"ranged_only":True},
    "reaction:ling_qi.rhythmic_guard": {"checkpoint":"DAMAGE_APPLICATION","target":"ALLY_OR_SELF_WITHIN_30","resource":"resource:ling_qi.qi","cost":1,"reduction":"1d8+4","requires":"KEEP_THE_MEASURE"},
    "reaction:bai_meizhen.water_shield": {"checkpoint":"DAMAGE_APPLICATION","target":"ALLY_OR_SELF_WITHIN_30","resource":"resource:bai_meizhen.qi","cost":1,"reduction":"1d10+4","optional_move_ft":10,"move_requires":"SOAKED_OR_BASIN_OR_CURRENT"},
    "reaction:bai_meizhen.spirit_intercession": {"checkpoint":"ALLY_OR_COMPANION_ATTACKED","target":"CUI_WITHIN_30","attack_mode":"DISADVANTAGE","if_hit":"SPEND_1_QI_OR_GAIN_1_BOND_STRAIN"},
    "reaction:ling_qi.false_image_guard": {"checkpoint":"DAMAGE_APPLICATION","target":"SELF","resource":"resource:ling_qi.mirror_trace","cost":1,"reduction":7},
    "reaction:bai_meizhen.sea_moon_interposition": {"checkpoint":"DAMAGE_APPLICATION","target":"ALLY_OR_SELF_WITHIN_30","resource":"resource:bai_meizhen.moon_sea_radiance","cost":1,"reduction":7},
}

BASIC_MELEE = {
    AN: {"source_definition_id":"action:an_eui.paired_bi_shou_assault","attack_bonus":7,"damage":DiceSpec(count=1,sides=4,modifier=4),"damage_type":"PIERCING","reach_ft":5},
    LEE: {"source_definition_id":"system:combat.basic_melee.lee_jia_small_knife","attack_bonus":7,"damage":DiceSpec(count=1,sides=4,modifier=4),"damage_type":"PIERCING","reach_ft":5},
    LING: {"source_definition_id":"system:combat.unarmed_strike","attack_bonus":2,"damage":DiceSpec(count=1,sides=1+1,modifier=0),"damage_type":"BLUDGEONING","reach_ft":5,"fixed_damage":0},
    BAI: {"source_definition_id":"system:combat.basic_melee.bai_ribbon_jian","attack_bonus":5,"damage":DiceSpec(count=1,sides=4,modifier=2),"damage_type":"SLASHING","reach_ft":5},
    CUI: {"source_definition_id":"creature:bai_cui","attack_bonus":6,"damage":DiceSpec(count=2,sides=8,modifier=3),"damage_type":"PIERCING","reach_ft":5},
}
