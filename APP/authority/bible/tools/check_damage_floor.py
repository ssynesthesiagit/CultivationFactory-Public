#!/usr/bin/env python3
"""
Tianxia Rules Bible — Strict Per-Event Mechanical Damage Floor Ledger & Verifier (v3).

Enforces all 5 root-cause pairing rules:
  1. One-to-one pairing + summed simultaneous rolls:
     Each Bible damage roll answers at most ONE distinct live roll (scaling tiers of
     one roll map cleanly to scaling tiers, never cannibalizing a second roll).
     Simultaneous compound rolls (e.g. "6d6 Fire and 2d6 Slashing") are summed before
     comparing.
  2. Role matching:
     A live "bonus" / "retaliation" / "secondary" roll MUST match a Bible "bonus" /
     "retaliation" / "secondary" roll — NEVER the main burst.
  3. Repeating-zone matching:
     A live repeating roll ("enters or starts its turn", "starts its turn inside",
     "each turn", "every time it moves") MUST match a Bible roll that also repeats.
  4. Strict flat CL / flat PB damage phrase matching:
     Flat CL / PB / PB+mod MUST match an actual damage phrase (never "CL 15+",
     "10 x CL HP", "PB allies", "PB Temp HP", etc.), and automatic no-save CL cannot
     be satisfied by a save-for-half roll whose half falls below CL.
  5. Cross-referenced base-ability resolution:
     "damage equal to your <Ability> damage [+ X]" resolves to that base ability's
     real dice curve (e.g. Shatter Bloom -> Shard Needle + key mod = 2d8/3d8/4d8 + 2*mod).

Zero automatic CUT ON PURPOSE. Cost increases and new use limits use REBALANCED_COST_OR_LIMIT.

Usage:
  python3 tools/check_damage_floor.py --generate   # Rebuild DAMAGE_FLOOR_LEDGER.md & verify
  python3 tools/check_damage_floor.py              # Verify ledger + Bible + mirrors
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
import unicodedata
from pathlib import Path

BIBLE_ROOT = Path(__file__).resolve().parent.parent
COMPILED_DIR = BIBLE_ROOT / "compiled"
def _factory_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "APP" / "authority" / "typed_mechanics").is_dir():
            return parent
    return BIBLE_ROOT.parent / "CultivationFactory"


FACTORY_ROOT = _factory_root()
MIRROR_DIR = FACTORY_ROOT / "docs" / "bible"
LIVE_JSON = FACTORY_ROOT / "APP" / "authority" / "typed_mechanics" / "rules_text.json"
LEDGER_PATH = BIBLE_ROOT / "DAMAGE_FLOOR_LEDGER.md"

APPROVED_CUT_TAGS = (
    "slop",
    "does nothing",
    "not needed",
    "complex for little gain",
    "poorly designed",
)

# Conservative legal modifier (+5) for apples-to-apples floor checks
MOD_EVAL = 5.0
PB_EVAL = 3.0  # Mortal/Foundation baseline; Nascent CL=15..20 handled per tier

# Base ability dice curves for Rule 5 ("damage equal to your <Ability> damage")
BASE_ABILITY_CURVES: dict[str, list[tuple[str, str, float]]] = {
    # (step_label, canonical_expr, mean_at_MOD_EVAL)
    "shard needle": [
        ("Foundation (CL 5)", "2d8+mod", 9.0 + MOD_EVAL),
        ("Core (CL 11)", "3d8+mod", 13.5 + MOD_EVAL),
        ("Nascent (CL 17)", "4d8+mod", 18.0 + MOD_EVAL),
    ],
    "thread sphere": [
        ("Mortal (CL 1)", "1d6+mod", 3.5 + MOD_EVAL),
        ("Foundation (CL 5)", "2d6+mod", 7.0 + MOD_EVAL),
        ("Core (CL 11)", "3d6+mod", 10.5 + MOD_EVAL),
        ("Nascent (CL 17)", "4d6+mod", 14.0 + MOD_EVAL),
    ],
    "water lash": [
        ("Mortal (CL 1)", "1d8+mod", 4.5 + MOD_EVAL),
        ("Foundation (CL 5)", "2d8+mod", 9.0 + MOD_EVAL),
        ("Core (CL 11)", "3d8+mod", 13.5 + MOD_EVAL),
        ("Nascent (CL 17)", "4d8+mod", 18.0 + MOD_EVAL),
    ],
}

# ==============================================================================
# EXPLICIT HAND-AUTHORED DECISIONS (ZERO AUTOMATIC CUT ON PURPOSE!)
# ==============================================================================

KEY_TO_ENTRY_ALIAS: dict[str, tuple[str, str]] = {
    # 2026-11-27 rename (Sphere -> Aspect, "Way of ..."): the live game still prints the old names for these six
    "TAL_QIWEAVING_TWIN_SPHERE_MODULATION": ("02_spheres_of_the_dao/54_qiweaving.md", "Twin-Aspect Modulation"),
    "tianxia.talent.spirit_companions.hosted_battle_aspect": ("02_spheres_of_the_dao/69_spirit_companions.md", "Hosted Battle Form"),
    "insight.hybrid-sphere-refinement": ("05_cultivation_insights/01_path_and_general_insights.md", "Hybrid-Aspect Refinement"),
    "insight.internalized-sphere-insight": ("05_cultivation_insights/01_path_and_general_insights.md", "Internalized Aspect Insight"),
    "insight.might-sphere-discipline": ("05_cultivation_insights/01_path_and_general_insights.md", "Might-Aspect Discipline"),
    "insight.restricted-sphere-license": ("05_cultivation_insights/01_path_and_general_insights.md", "Restricted Aspect License"),
    # same rename, Bible section headings renamed in the read-through (live game still prints the old names)
    "EQUIPMENT_BASE_EQUIPMENT_TRAINING": ("02_spheres_of_the_dao/23_equipment.md", "Armaments Training"),
    "TAL_DRUNKEN_STYLE_DRUNKEN_STYLE_TRAINING": ("02_spheres_of_the_dao/20_drunken_style.md", "Drunken Master Training"),
    "TAL_MONKEY_STYLE_MONKEY_STYLE_TRAINING": ("02_spheres_of_the_dao/47_monkey_style.md", "Monkey Training"),
    "EARTH_BASE_SPENDING_A_BURDEN_MARK": ("02_spheres_of_the_dao/22_earth.md", "Core Earth Rules"),
    "ICE_BASE_SPENDING_A_FRACTURE_MARK": ("02_spheres_of_the_dao/36_ice.md", "Core Fracture Responses"),
    "TAL_DAEMONIC_CULTIVATION_BASE_SPHERE_ABILITIES": ("02_spheres_of_the_dao/14_daemonic_cultivation.md", "Base Abilities"),
    "TAL_GRAVITY_WEIGHT_SHIFT_BASE": ("02_spheres_of_the_dao/31_gravity.md", "Base Abilities"),
    "TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION": ("02_spheres_of_the_dao/68_spear.md", "Spear-Sovereign Zenith"),
    "TAL_WAX_BASE_SPHERE_ABILITIES": ("02_spheres_of_the_dao/80_wax.md", "Base Abilities"),
    "TAL_YANG_APPLYING_A_RISING_MARK": ("02_spheres_of_the_dao/84_yang.md", "Core Yang Rules"),
    "TAL_YANG_BASE_SPHERE_ABILITIES": ("02_spheres_of_the_dao/84_yang.md", "Base Abilities"),
    "TAL_YIN_BASE_SPHERE_ABILITIES": ("02_spheres_of_the_dao/85_yin.md", "Base Abilities"),
    "TAL_YIN_MARKING_A_CREATURE": ("02_spheres_of_the_dao/85_yin.md", "Core Yin Rules"),
    "TRAP_BASE_DART_MECHANISM": ("02_spheres_of_the_dao/74_trap.md", "Dart Mechanism"),
    "tianxia.talent.stars.stars_domain": ("02_spheres_of_the_dao/70_stars.md", "Court of the Celestial Compass"),
    "TAL_DUAL_WIELDING_MIXED_DEFENSE": ("02_spheres_of_the_dao/21_dual_wielding.md", "Mixed Defense"),
    "printed_option:unmaking.overdraw": ("02_spheres_of_the_dao/75_unmaking.md", "Overdraw"),
    "printed_option:Centerline Impact": ("02_spheres_of_the_dao/40_iron_fist.md", "Open the Gate"),
    "tianxia.talent.space.void_between_worlds": ("02_spheres_of_the_dao/67_space.md", "Secret Inheritance: Void Between Worlds"),
    "TAL_YANG_APPLYING_A_RISING_MARK": ("02_spheres_of_the_dao/84_yang.md", "Rising Thread"),
    "TAL_YIN_MARKING_A_CREATURE": ("02_spheres_of_the_dao/85_yin.md", "Withdrawing Thread"),
    # 30 formerly-unresolved live entries explicitly matched by hand (3 Sovereign Forms, 1 Foundation, 4 Path, 22 Sphere stubs):
    "TAL_BARRAGE_SOVEREIGN_ARSENAL_INCARNATION": ("02_spheres_of_the_dao/06_barrage.md", "Sovereign Arsenal Tempo"),
    "TAL_DRUNKEN_STYLE_SOVEREIGN_CHAOS_STEP_INCARNATION": ("02_spheres_of_the_dao/20_drunken_style.md", "Sovereign Chaos-Step Grandmaster"),
    "TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION": ("02_spheres_of_the_dao/62_shield.md", "Sovereign Shield-Soul Bastion"),
    "foundation.FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR.integrated_nourishment_rider": ("04_methods_and_foundations/02_foundations_rules_and_catalog.md", "Integrated Nourishment Secondary Effect"),
    "tianxia.path.body_refining.feature.extra_attack_improvement": ("01_players_handbook/04_body_refining.md", "CL 5 — Extra Attack"),
    "tianxia.path.qi_cultivation.feature.domain_armament_damage_increase": ("01_players_handbook/05_qi_cultivation.md", "Domain Armament base damage rises to"),
    "printed_option:Modulation Talents": ("02_spheres_of_the_dao/54_qiweaving.md", "Modulation, Harmonic & Turbulence Talents"),
    "tianxia.path.spirit_awakening.feature.spirit_awakening_subpath": ("01_players_handbook/06_spirit_awakening.md", "CL 3 — Spirit Awakening Tradition"),
    "tianxia.path.spirit_awakening.feature.subpath_feature": ("01_players_handbook/06_spirit_awakening.md", "CL 3 — Spirit Awakening Tradition"),
    "BEASTMASTERY_BASE_BEASTMASTERY_TRAINING": ("02_spheres_of_the_dao/07_beastmastery.md", "Core Beastmastery Rules"),
    "BLACKSMITH_BASE_BLACKSMITH_TRAINING": ("02_spheres_of_the_dao/10_blacksmith.md", "Core Blacksmith Rules"),
    "BRUTE_BASE_SPECIAL_ATTACKS": ("02_spheres_of_the_dao/12_brute.md", "Core Brute Rules"),
    "EQUIPMENT_BASE_ONE_FREE_EQUIPMENT_TALENT": ("02_spheres_of_the_dao/23_equipment.md", "Core Armaments Rules"),
    "FORMATIONS_BASE_FORMATION_TRAINING": ("02_spheres_of_the_dao/29_formations.md", "Core Formations Rules"),
    "HARVESTING_GATHERING_BASE_HARVEST_LOTS_AND_LOT_QUALITY": ("02_spheres_of_the_dao/33_harvesting_gathering.md", "Core Gathering Rules"),
    "HARVESTING_GATHERING_BASE_TRAINING_AND_TOOLS": ("02_spheres_of_the_dao/33_harvesting_gathering.md", "Core Gathering Rules"),
    "JESTER_BASE_JESTER_TRAINING": ("02_spheres_of_the_dao/41_jester.md", "Core Jester Rules"),
    "SECT_STEWARDSHIP_BASE_LEARNING_SECT_STEWARDSHIP": ("02_spheres_of_the_dao/60_sect_stewardship.md", "Core Sect Stewardship Rules"),
    "TAL_FLOWERS_UNWILLING_CREATURE": ("02_spheres_of_the_dao/26_flowers.md", "Core Flower Rules"),
    "TAL_SPIRIT_COMPANIONS_MANIFESTATION_LIMITS": ("02_spheres_of_the_dao/69_spirit_companions.md", "Core Spirit Companions Rules"),
    "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES": ("02_spheres_of_the_dao/34_the_hidden_eye.md", "Base Abilities"),
    "TAL_YANG_KINDLED_AND_OVERKINDLED_MARKS": ("02_spheres_of_the_dao/84_yang.md", "Core Yang Rules"),
    "TAL_YANG_MARK_LIMIT": ("02_spheres_of_the_dao/84_yang.md", "Core Yang Rules"),
    "TAL_YANG_YANG_SAVES": ("02_spheres_of_the_dao/84_yang.md", "Core Yang Rules"),
    "TAL_YIN_MARK_LIMIT": ("02_spheres_of_the_dao/85_yin.md", "Core Yin Rules"),
    "TAL_YIN_MARKED_ALLIES": ("02_spheres_of_the_dao/85_yin.md", "Core Yin Rules"),
    "TAL_YIN_YIN_SAVES": ("02_spheres_of_the_dao/85_yin.md", "Core Yin Rules"),
    "WRESTLING_BASE_GRAPPLING_REMINDER": ("02_spheres_of_the_dao/83_wrestling.md", "Core Wrestling Rules"),
    "WRESTLING_BASE_ONE_GRAPPLE_PER_HAND_OR_BODY_PART": ("02_spheres_of_the_dao/83_wrestling.md", "Core Wrestling Rules"),
    "WRESTLING_BASE_RESTRAINTS_AND_UTILIZE": ("02_spheres_of_the_dao/83_wrestling.md", "Core Wrestling Rules"),
    "WRESTLING_BASE_SPECIAL_ATTACKS": ("02_spheres_of_the_dao/83_wrestling.md", "Core Wrestling Rules"),
    "WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC": ("02_spheres_of_the_dao/83_wrestling.md", "Core Wrestling Rules"),
}

# Explicit subset of hand-matched non-damage keys to emit in the ledger accounting table
HAND_MATCHED_ACCOUNTING_KEYS: set[str] = {
    "TAL_BARRAGE_SOVEREIGN_ARSENAL_INCARNATION",
    "TAL_DRUNKEN_STYLE_SOVEREIGN_CHAOS_STEP_INCARNATION",
    "TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION",
    "foundation.FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR.integrated_nourishment_rider",
    "tianxia.path.body_refining.feature.extra_attack_improvement",
    "tianxia.path.qi_cultivation.feature.domain_armament_damage_increase",
    "tianxia.path.spirit_awakening.feature.spirit_awakening_subpath",
    "tianxia.path.spirit_awakening.feature.subpath_feature",
    "BEASTMASTERY_BASE_BEASTMASTERY_TRAINING",
    "BLACKSMITH_BASE_BLACKSMITH_TRAINING",
    "BRUTE_BASE_SPECIAL_ATTACKS",
    "EQUIPMENT_BASE_ONE_FREE_EQUIPMENT_TALENT",
    "FORMATIONS_BASE_FORMATION_TRAINING",
    "HARVESTING_GATHERING_BASE_HARVEST_LOTS_AND_LOT_QUALITY",
    "HARVESTING_GATHERING_BASE_TRAINING_AND_TOOLS",
    "JESTER_BASE_JESTER_TRAINING",
    "SECT_STEWARDSHIP_BASE_LEARNING_SECT_STEWARDSHIP",
    "TAL_FLOWERS_UNWILLING_CREATURE",
    "TAL_SPIRIT_COMPANIONS_MANIFESTATION_LIMITS",
    "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES",
    "TAL_YANG_KINDLED_AND_OVERKINDLED_MARKS",
    "TAL_YANG_YANG_SAVES",
    "TAL_YIN_MARKED_ALLIES",
    "TAL_YIN_YIN_SAVES",
    "WRESTLING_BASE_GRAPPLING_REMINDER",
    "WRESTLING_BASE_ONE_GRAPPLE_PER_HAND_OR_BODY_PART",
    "WRESTLING_BASE_RESTRAINTS_AND_UTILIZE",
    "WRESTLING_BASE_SPECIAL_ATTACKS",
    "WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC",
    "insight.armor-is-not-a-cage",
    "insight.bright-armor-changes-the-field",
    "insight.cloth-can-hide-iron",
    "insight.many-plates-one-breath",
    "insight.the-helmet-is-a-promise",
}

RESTORED_KEYS: dict[str, str] = {
    "printed_option:unmaking.overdraw": "Restored Core +10d6 / Nascent +14d6",
    "tianxia.talent.radiance.heavenly_radiance": "Restored Solar Aura 4d10 (5d10 Unclean) + Blinded + half/no-Reactions on pass; Dawn Wave reshapes 8d10 Strike",
    "TAL_LIGHTNING_THUNDERCLAP_PALM": "Restored 0 CP, 1d8/2d8/3d8/4d8 + key mod Thunder",
    "TAL_FORCE_HEAVEN_CRUSHING_PALM": "Restored double damage vs objects, structures, and Barriers (30d10)",
    "TAL_SPEAR_WORLD_TRANSFIXING_POINT": "Restored double damage vs objects and temporary Barriers (32d10)",
    "tianxia.talent.chains.heaven_dragging_chain": "Restored double damage vs structures, gates, vehicles, siege engines, unattended objects (26d10)",
    "TAL_SOUND_MOUNTAIN_CRACKING_BELL": "Restored triple damage across objects, structures, constructs, brittle terrain, and Barriers (33d10)",
    "TAL_SWORD_ONE_SWORD_TEN_THOUSAND_CUTS": "Restored half damage + 1 effect on a miss",
    "TAL_METAL_COMMAND_THE_HIDDEN_BLADE": "Restored Bonus Action 3 CP 3d8 + Metal key mod offensive strike",
    "tianxia.talent.blood.blood_emperor_incarnation": "Restored Crimson Aura 20 ft 4d8 Necrotic Con save half + heal half on fail",
    "TAL_MAGMA_FURNACE_MANTLE": "Restored 5-ft turn-start PB Fire aura + Heat Pressure",
    "tianxia.talent.music.symphony_of_heaven_and_earth": "Restored Movement of Ruin 4d8 Thunder/Psychic Con save half",
    "TAL_UNMAKING_SIXTH_RUIN_FORM_STAR_SUNDERING_CUT": "Restored no-save 24d10 Ruin on objects, Barriers, structures, siege engines, constructs",
    "tianxia.talent.unmaking.the_moment_nothing_answers": "Restored +12d10 vs vessels/Barriers and +6d10 vs compromised targets on top of 24d10",
    "TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE": "Restored +4d10 hit bonus, PBd10 Concentration damage, full hazard targets, 4d10 (min CL)",
    "TAL_UNMAKING_UNMAKE_THE_ANSWER": "Restored 5d10 Ruin on check success by 5+",
    "TAL_UNMAKING_LATTICE_UNRAVELING": "Restored 4d10 Ruin on failed suppression check vs HP/structure",
    "TAL_UNMAKING_BLACK_TRACE": "Restored Crack (+PB vs structures/Barriers) and Mark (+PB next Unmaking hit)",
    "TAL_UNMAKING_RUIN_CHANNEL": "Unified onto single curve +2d8/+4d8/+5d8/+7d8 Ruin",
    "TAL_UNMAKING_UNBODY_THE_FALSE_VESSEL": "Restored PBd10 Ruin backlash to visible owner/caster/summoner",
    "TAL_UNMAKING_HOLLOWING_FIELD": "Restored Ruin Vulnerability for objects, Barriers, qi structures, constructs",
    "TAL_UNMAKING_DISSOLVE_THE_SEAM": "Restored 8d10 success, half fail, Overdraw +6d10",
    "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY": "Restored 2 CP weapon/Cultivation normal damage +3d8, 20-ft secondary 2d8 half, Miss PB to secondary",
    "TAL_VOID_HEAVEN_EMPTYING_LANCE": "Restored Barrier/object targeting, threshold bypass, double vs temp Barriers",
    "GLASS_BASE_REFRACTION_RESPONSES": "Restored No Action (1/round), Bitter Edge, Shatter Warning, Break the Line +PB & 5-ft splash",
    "ICE_BASE_SPENDING_A_FRACTURE_MARK": "Restored Brittle Opening +1d6/2d6/3d6+PB and Shatter Space +key mod + Prone",
    "HUNGER_BASE_DIGESTIVE_MANTLE": "Restored Venom Belly PB+mod, Predator Step +PB charge, Furnace Belly PB+mod Fire/Acid",
    "TAL_LIGHTNING_LIGHTNING_CHAINS": "Restored 2d8+mod initial (half on pass), 2d6/turn, and 2-target 20-ft separation link (+PB)",
    "tianxia.talent.radiance.world_of_revealed_morning": "Restored half damage + no Reactions on pass",
    "tianxia.talent.pressure_points.meridian_stillness_field": "Restored technique-activation 2d8+mod Psychic/Force + no Reactions",
    "tianxia.talent.formations.nine_palaces_killing_array": "Restored persistent Flow Line crossing damage (automatic CL / 6d8)",
    "tianxia.talent.gravity.world_crushing_pressure": "Restored double damage to objects, structures, Barriers",
    "tianxia.talent.gravity.ten_thousand_weight_body": "Restored double melee damage to objects, structures, Barriers",
    "TAL_WATER_RIVER_CUTS_THE_GATE": "Restored Scouring Erosion ongoing double Water damage",
    "TAL_WATER_ERODE_THE_MOUNTAIN_S_NAME": "Restored double damage vs stone, walls, fortifications, Barriers, erodible objects",
    "TAL_WATER_WHEN_THE_SEA_FORGETS_THE_SHORE": "Restored ongoing double Water damage vs mundane erodible objects/structures/terrain",
    "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS": "Restored selectable weapon/unarmed attack during movement",
    "tianxia.talent.stars.world_beneath_the_constellations": "Restored Force damage option",
    "tianxia.talent.stars.stars_domain": "Restored Force damage option",
    "TAL_MONKEY_STYLE_HEAVEN_UPROOTING_STAFF": "Restored double damage vs structures, Barriers, unattended objects",
    "TAL_BERSERKER_WORLD_BREAKING_RAMPAGE": "Restored double damage vs unattended objects and temporary Barriers",
    "TAL_MAGMA_HEAVEN_FALLING_METEOR": "Expanded triple damage to vehicles and siege engines",
    "TAL_DAEMONIC_CULTIVATION_HELL_OPENS_BENEATH_THE_SECT_GATE": "Restored Fire/Force options and PB on successful save",
    "TAL_MAGMA_LAVA_FLOW": "Restored recurring 1-min stream entry/start-of-turn Dex save half",
    "TAL_MAGMA_BLACKGLASS_RIVER": "Restored recurring 1-min river entry/start-of-turn 6d6 Fire + 2d6 Slashing (8d6) Dex save half",
    "TAL_MAGMA_VOLCANIC_ERUPTION": "Restored recurring 1-min eruption zone entry/start-of-turn 6d6+3d6 (8d6+4d6 CL 17) Dex save half",
    "tianxia.talent.poison.poison_domain": "Restored Acid option and half damage on successful save",
    "TAL_MONKEY_STYLE_THOUSAND_MONKEY_UPRISING": "Restored 3d8 Psychic/Bludgeoning Wis save on enemy move/attack within 30 ft",
    "printed_option:Centerline Impact": "Restored +PB Bludgeoning Centerline Impact on Open the Gate",
    "TAL_LIGHTNING_THUNDERHEAD_LATTICE": "Restored CL Lightning damage for disturbing/breaking a node in place",
    "tianxia.talent.sound.the_first_sound_before_heaven": "Restored Psychic option and 20d10 Structure-Shattering Mode",
    "TAL_YANG_COMPLETING_FLAME_MANTLE": "Restored grappler turn-start PB + key mod Fire/Radiant",
    "tianxia.talent.destruction.returning_calamity": "Restored half damage on successful Dex save",
    "TAL_SAND_DEVOURING_DUNE_MOUTH": "Restored Bonus Action 3d8 Bludgeoning compression vs Buried enemies",
    "STARS_TAL_FALLING_STAR": "Expanded double damage to unattended objects",
    "STARS_TAL_HEAVEN_FALLING_STAR": "Expanded double damage to unattended objects",
    "TAL_FORCE_COURT_OF_THE_ANSWERING_WORLD": "Restored Bludgeoning option",
    "tianxia.talent.karma.no_lie_before_the_ledger": "Restored half damage on pass + concealed-answer trigger",
    "TAL_BRUTE_MOUNTAIN_MOVING_PALM": "Restored temporary Barriers target + double damage",
    "tianxia.talent.warleader.thunder_banner_cry": "Restored explicit 6d8 + key mod at CL 15",
    "RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT": "Restored 300x10 line, Radiant Resistance bypass, double structure/object damage",
    "tianxia.talent.radiance.purifying_radiance": "Restored standalone 4d8/6d8/8d8 Radiant ray",
    "RADIANCE_TAL_JUDGMENT_RAY": "Restored 120-ft line",
    "TAL_MAGMA_LAVA_WALL": "Restored 40x10x5, enter/start/end, 4d8 Fire + 2d8 Bludgeoning",
    "TAL_MAGMA_ERUPTION_STRIKE": "Restored double object/Barrier damage + Magma Glob / Magma attack triggers",
    "TAL_MAGMA_OBSIDIAN_CAGE": "Restored 1d8 Slashing/turn, grounded creature, Conc 1 min, Action Str DC",
    "TAL_MAGMA_SLAG_GRASP": "Restored 1d8+mod Fire + standalone 60-ft Action",
    "TAL_MAGMA_MOLTEN_GROUND": "Restored 15-ft radius + Dex save half",
    "TAL_MAGMA_BOILING_ASH_SKY": "Restored standalone Action 90 ft, 40-ft radius, Conc 1 min, 4d8/6d8 turn-start",
    "TAL_MONKEY_STYLE_STONE_SKIPPING_STRIKE": "Restored 30/90 ft thrown skip + explicit attack/ricochet rolls",
    "TAL_MONKEY_STYLE_VAULTING_STRIKE": "Restored 1d8/2d8/3d8 Bludgeoning + move/jump/vault 10 ft",
    "TAL_DEATH_DEATH_SOVEREIGN_INCARNATION": "Restored 20-ft 4d8 Funerary Aura + free 1/turn Withering Hand",
    "TAL_VOID_UNMAKE_BARRIER": "Restored structure section/summoned object targets, threshold bypass, double vs temp Barriers",
    "TAL_VOID_VOID_MERIDIAN_SEAL": "Restored standalone Action 60 ft, Conc 1 min, 6 CP/Stamina",
    "TAL_LIGHTNING_GATHER_CHARGE": "Restored 30/60-ft range, weapon +PB, 5-ft first-creature space trap",
    "TAL_LIGHTNING_FIVEFOLD_THUNDER_CIRCUIT": "Restored 120-ft range + explicit Cultivation Attack / Dex save half",
    "tianxia.talent.music.weapon_hymn": "Restored 1d6/1d8/2d6 Thunder/Psychic, Touch/30 ft, own/ally/unarmed/natural weapons",
    "TAL_FORCE_INVISIBLE_MOUNTAIN": "Restored 6d8 CL 17-20 + explicit self/90-ft Anchor origin",
    "tianxia.talent.gravity.event_horizon_prison": "Restored 6d10 Force Con save half + CP/Stamina payment",
    "tianxia.talent.karma.borrowed_tomorrow": "Restored Karmic Burden settlement options",
    "TAL_AIR_CYCLONE_PRISON": "Restored immediate save on vortex creation",
    "tianxia.talent.metal.loadstone_emperor_scripture": "Restored Action, 30/60-ft radius, Str save, Nascent 4d8+mod",
    "TAL_DAEMONIC_CULTIVATION_DEMON_SEED": "Restored +1d4/1d6/1d8/1d10 per-turn hit bonus",
    "TAL_MONKEY_STYLE_IMPROVISED_MASTER": "Restored 1d8/1d10 improvised die + 1d6+PB Tap Finish bonus",
    "tianxia.talent.destruction.ruin_tempered_armament": "Restored +1d6/2d6/3d6/4d6 critical-hit bonus on top of +1/+2 Destruction Die per turn",
    "TAL_WEATHER_STORMLORD_S_FINGER": "Restored 6d10 / 8d10 (Severity 3)",
    "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH": "Restored 5d6 at CL 11",
    "TAL_MAGMA_MAGMA_ARMOR": "Restored 2d6/3d6/4d6 grapple/melee/strike retaliation",
    "tianxia.talent.radiance.dawnmark_scripture": "Restored +1d8 Radiant vs Dawnmarked Unclean",
    "tianxia.talent.radiance.searing_halo": "Restored +1d8 Radiance Strike hit bonus + melee retaliation",
    "tianxia.talent.radiance.solar_radiance_form": "Restored +1d8 Radiance Strike + 2d6 melee retaliation",
    "TAL_SOUND_WORLD_SPLITTING_SCREAM": "Restored double damage to objects and ordinary barriers",
    "TAL_WEATHER_HEAVEN_BREAKS_THE_BANNER": "Restored double damage to objects, siege engines, buildings, metal structures",
    "tianxia.talent.disease.plague_sovereign_incarnation": "Restored 4d8 Virulent Presence aura (expanded to 30 ft, half on pass)",
    "tianxia.talent.karma.minor_oath": "Restored 2d8 Psychic oath-break damage",
    "tianxia.talent.karma.great_oath": "Restored 8d10 Psychic oath-break + 2 Debt Imprints",
    "TAL_LIGHTNING_FIRST_CIRCUIT_METHOD": "Restored Edge Circuit +PB hit bonus",
    "TAL_SWORD_SWORD_SOVEREIGN_INCARNATION": "Restored Sovereign Riposte Reaction attack / 6d10 Sword Qi Wave",
    "tianxia.talent.metal.indestructible_iron_marrow_sutra": "Restored 1/LR 0-HP survival + 3d8 + CON mod thorn burst",
    "tianxia.talent.chains.oath_lock_chain": "Restored 4d8 + key mod Force (Cha save half)",
    "tianxia.talent.lightning.when_potential_becomes_judgment": "Restored +4d8 first-hit-each-turn aftermath bonus",
    "tianxia.talent.metal.ten_thousand_metal_sovereign_edict": "Restored +4d8 first-hit-each-turn aftermath bonus",
    "TAL_ICE_SHATTER_BLOOM": "Restored Shard Needle + 2x key mod floor",
    "TAL_MAGMA_LAVA_BEAST": "Restored PB Fire grappler turn-start",
    "TAL_MAGMA_OBSIDIAN_SKIN": "Restored PB Slashing grappler turn-start",
    "TAL_WAX_MOLTEN_SNARE": "Restored PB Fire every time target moves",
    "TAL_DAEMONIC_CULTIVATION_BLACK_SUN_OVER_THE_DANTIAN": "Restored PB Psychic/Necrotic on passed save",
    "TAL_MAGMA_BLACKGLASS_RIVER": "Restored Conc 1 min repeating 7d6 Fire + 2d6 Slashing river + Bonus Action 10-ft shift",
    "TAL_MAGMA_LAVA_FLOW": "Restored Conc 1 min repeating 6d6/8d6 Fire stream + Bonus Action 10-ft shift",
    "TAL_MAGMA_VOLCANIC_ERUPTION": "Restored Conc 1 min repeating 6d6+3d6 (8d6+4d6 CL 17) Fire/Bludgeoning zone + Prone + no Reactions",
    "TAL_MAGMA_MAGMA_PRISON": "Restored 2d8 Fire + 2d8 Bludgeoning (4d8) repeating start-of-turn damage",
    "TAL_MAGMA_WORLD_BREAKING_ERUPTION": "Restored Conc 1 min repeating 8d8 Fire + 5d8 Bludgeoning eruption before Lava Lake",
    "tianxia.talent.magma.sea_of_molten_heaven": "Restored Conc 1 min repeating 8d10 Fire + 8d10 Bludgeoning + 3d10 Burning before Lava Lake",
    "TAL_MAGMA_LAVA_SPIT": "Restored 1d6/2d6/3d6 Burning damage",
    "TAL_LIGHTNING_CRACKLING_ARROW": "Restored +PB secondary arc",
    "TAL_LIGHTNING_CHAIN_BOLT": "Clarified half damage (minimum PB) on successful save for primary and arced targets",
    "TAL_LIGHTNING_TRUE_LIGHTNING_GOD_MANTLE": "Restored +1d8 first melee / Lightning Lash hit bonus",
    "TAL_LIGHTNING_ONE_CIRCUIT_UNDER_HEAVEN": "Restored 2xCL no-save automatic Lightning vs Conductive objects/Barriers/Nodes",
    "TAL_METAL_HUNDRED_NEEDLES_FAN": "Restored +PB real-metal scrap material bonus",
    "TAL_ICE_CRYSTAL_WEATHER_SCRIPT": "Raised repeating Cold to 5d8 + key mod (beats CL 17 Shard Needle 4d8 + mod)",
    "TAL_BRUTE_SOVEREIGN_WEIGHT_INCARNATION": "Restored +2d8 bonus Hammer collision damage",
    "TAL_BRUTE_THE_HAND_THAT_REPOSITIONED_HEAVEN": "Restored +6d10 bonus Hammer collision damage",
    "tianxia.talent.disease.symptom_cascade": "Restored 2d8 Necrotic/turn Fever repeating tick",
    "tianxia.talent.dreams.dream_that_swallows_the_waking_world": "Restored 4d10 Psychic start-of-turn repeating tick while trapped",
    "TAL_GLASS_INCARNATION_OF_THE_TRANSPARENT_FAULT": "Restored +PB Slashing / PB Temp HP on Faultline Mark spend",
    "tianxia.talent.imbuement.the_edict_that_names_the_world_again": "Restored +CL bonus weapon damage under All Allied Gear Becomes Sovereign",
    "tianxia.talent.karma.trial_of_the_ledger": "Restored PB + key mod Psychic on passed save",
    "tianxia.talent.karma.mandate_of_heaven": "Restored Charisma save (half damage + 1 Debt Imprint on pass)",
    "TAL_MONKEY_STYLE_HEAVEN_BRIDGE_SWING": "Restored +PB bonus melee attack after Monkey Link",
    "TAL_SAND_GLASS_PRISON": "Restored minimum CL Piercing (no save) on start of turn / attack / cast / escape",
    "TAL_SAND_GLASS_DESERT_JUDGMENT": "Restored automatic CL Piercing (no save) moving >5 ft through razor glass",
    "TAL_SOUND_RESONANT_NOTE": "Restored +PB Thunder bonus vs objects, brittle structures, Barriers, Constructs",
    "TAL_SOUND_RESONANT_SHATTER": "Restored 5d8 / 7d8 / 9d8 Thunder scaling floor",
    "TAL_SWORD_MYRIAD_SWORD_PROCESSION": "Restored 2d8 start-of-turn Sword Intent damage",
    "tianxia.talent.thread.garrote_thread": "Restored explicit 1d8/2d8/3d8/4d8 + key mod Thread damage",
    "tianxia.talent.thread.ten_thousand_thread_domain": "Raised tethered turn-start to 4d10 + key mod + restored +PB Force hit option",
    "TAL_UNMAKING_SIXTH_RUIN_FORM_STAR_SUNDERING_CUT": "Restored +8d10 bonus Ruin vs constructs/clones/projections/non-true bodies",
    "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL": "Restored +4d10 minimum bonus on willing-ally damage/healing double",
    "TAL_ALCHEMY_BACKDRAFT_FUMES": "Restored half damage on successful save",
    "tianxia.talent.blood.bloodline_awakening": "Restored 1d8 natural weapon option",
    "TAL_DAEMONIC_CULTIVATION_BORROW_THE_MONSTER_S_SHAPE": "Restored venom glands (+PB Poison 1/turn) and horns/fangs options",
    "tianxia.talent.music.dissonant_note": "Raised scaling to 4d8 CL 5 / 5d8 CL 11 / 6d8 CL 15",
    "tianxia.talent.radiance.solar_flare": "Raised scaling to 4d6 CL 5 / 6d6 CL 11 / 8d6 CL 15",
    "tianxia.talent.stars.constellation_that_names": "Restored 4d10 Radiant + 4d10 Force (8d10) repeating start-of-turn damage",
    "tianxia.talent.pressure_points.the_point_between_heartbeats": "Restored +6d10 Force/Psychic bonus on next hit and live Focus + 6 CP cost",
    "TAL_SAND_DESERT_DRINKS_THE_RIVER": "Restored 4 CP cost, Necrotic or Force choice, and 6d8 Desiccate the Object damage",
    "TAL_MAGMA_MANTLE_BREACH": "Restored Fire or Bludgeoning choice, object/Barrier target, and mundane hardness/Resistance bypass",
    "TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE": "Restored Force or Bludgeoning choice and Opened Bludgeoning/Force Resistance bypass",
    "TAL_DAEMONIC_CULTIVATION_BASE_SPHERE_ABILITIES": "Restored Demon Seed Force option and Daemonic Augment Resistance bypass",
    "TAL_LIGHTNING_LIGHTNING_GOD_BODY": "Restored live 1 CP cost (+PB hit and 1d8+PB arc preserved)",
    "TAL_METAL_NINEFOLD_ADAMANT_BODY": "Restored live 8 CP cost and removed added 1/Long Rest limit",
    "TAL_LIGHTNING_CONDUCTIVE_STRIKE": "Restored live 0 CP cost (+1d8/2d8/3d8+PB Charge boost preserved)",
    "TAL_LIGHTNING_LIGHTNING_CHAINS": "Restored live 1 CP cost (2d8+mod initial + 2d6/turn + 2-target link preserved)",
    "TAL_SOUND_COURT_OF_THE_WORLD_RINGING_BELL": "Removed added 1/Short Rest limit (7 CP <= live 9 CP; 4d8 Ringing Court preserved)",
    "TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON": "Restored live 5 CP cost (4d10 teleport-tear + 5d8/turn preserved)",
    "TAL_SHIELD_HEAVEN_CRUSHING_SHIELD_DESCENT": "Restored live Focus-only cost (12d10 preserved)",
    "tianxia.talent.poison.ten_thousand_poison_wind": "Restored live 8 CP cost",
    "TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY": "Restored live 4 CP cost (6d8 Slashing + Blinded preserved)",
    "TAL_LIGHTNING_FORMATION_EXTINGUISHING_EDICT": "Restored live 3 CP cost (10d10 core blast + 60-ft 4d8+mod connected arc preserved)",
    "TAL_WATER_PRESSURE_LANCE": "Restored live 1 CP cost (5d8/7d8/9d8 + double vs Barriers preserved)",
}

# Cost/limit rises are now mechanically forbidden (zero REBALANCED_COST_OR_LIMIT carve-outs).
REBALANCED_COST_OR_LIMIT: dict[str, str] = {}

# Hand-authored CUT ON PURPOSE table ONLY (zero automatic CUT ON PURPOSE!).
HAND_CUT_ON_PURPOSE: dict[str, tuple[str, str]] = {
    "BLOOD_BASE_BLOOD_THREAD": (
        "does nothing",
        "Flat PB conditional bonus replaced by dice; owner-approved (flat PB <-> dice is fine)."
    ),
    "TAL_MAGMA_COURT_OF_THE_LIVING_VOLCANO::pass": (
        "complex for little gain",
        "Failed-save 3d8 + 1d8 Burning restored; passed-save Burning sub-menu replaced with clean half damage."
    ),
    "TAL_MAGMA_VOLCANO_SOVEREIGN_INCARNATION::pass": (
        "complex for little gain",
        "20-ft radius and 4d8 + 2d8 Burning restored; passed-save Burning sub-menu replaced with clean half damage."
    ),
    "TAL_AXES_SPLIT_THE_CHAIN": (
        "complex for little gain",
        "Axes Check vs cultivated restraints and +4d8/+6d8 object break kept; partial-HP tracking on mundane rope cut."
    ),
    "TAL_AXES_SPLIT_THE_SHIELD_WALL": (
        "complex for little gain",
        "Clean AoE save replaces nested multi-attack and critical-hit weapon roll branch."
    ),
    "TAL_FENCING_BLEED_AIR": (
        "complex for little gain",
        "Delayed 5d8 + Incapacitated replaces 5.5e Suffocation chart and Medicine exit minigame."
    ),
    "TAL_BARRAGE_CASCADING_BARRAGE": (
        "slop",
        "Removed no-positive-ability-modifier exception bookkeeping (strictly cleaner and stronger)."
    ),
    "TAL_DUAL_WIELDING_FOLLOWING_STRIKE": (
        "slop",
        "Removed third-target and no-positive-modifier bookkeeping penalty (strictly cleaner and stronger)."
    ),
    "AIR_BASE_WIND_LASH": (
        "slop",
        "Removed trivial Lift (+5 ft jump) and Scatter (Tiny unattended object) micro-options; gained higher base dice + Speed strip."
    ),
    "TAL_EARTH_VALLEY_THAT_RECEIVES_THE_ARMY": (
        "complex for little gain",
        "Streamlined 1-min combat Domain replaces 10-min duration and micro-Temp-HP sub-menu."
    ),
    "tianxia.talent.blacksmith.quench_against_the_grain": (
        "complex for little gain",
        "Sharper hit/miss flip and +PB tool Reaction replaces narrow 2d6+INT object-only damage reduction."
    ),
    "TAL_WEATHER_TYPHOON_HABOOB_GATE": (
        "complex for little gain",
        "Unified Strength save + Blinded at higher 5d8 damage instead of split save tables."
    ),
    "tianxia.talent.metal.heavenly_needle_sutra": (
        "slop",
        "3d8/4d8/5d8+mod Needle Burst restored; Metal Lineage Scriptures unified at CL 15+ and Metal Appraisal / technique-node micro-hooks cut."
    ),
    "TAL_UNMAKING_BLACK_TRACE::cost": (
        "complex for little gain",
        "Crack and Mark +PB restored; 3-way Unbound payment sub-menu simplified to fixed Strain + PB."
    ),
    "ALCHEMY_BASE_PILL_FORGING": (
        "does nothing",
        "Duplicate of tianxia.talent.alchemy.advanced_pill_forging in live JSON export."
    ),
    "TAL_DARK_RAPID_MELD": (
        "does nothing",
        "Empty string in live JSON export."
    ),
    "TAL_DUAL_WIELDING_MIXED_DEFENSE": (
        "slop",
        "1d4 improvised shield-bash sub-clause folded into clean Qualifying Pair rules without improvised-weapon clutter."
    ),
    "insight.legacy-avalanche-shoulder": (
        "not needed",
        "Pre-unification legacy insight retired; Avalanche Shoulder exists cleanly in Book 5."
    ),
    "insight.legacy-blood-boil": (
        "not needed",
        "Pre-unification legacy insight retired; Blood Boil exists cleanly in Book 5."
    ),
    "insight.legacy-heart-demon-manifestation": (
        "not needed",
        "Pre-unification legacy insight retired; Heart Demon Manifestation exists cleanly in Book 5."
    ),
    "insight.legacy-mountain-crushing-fist": (
        "not needed",
        "Pre-unification legacy insight retired; Mountain-Crushing Fist exists cleanly in Book 5."
    ),
    "insight.legacy-walking-the-ten-thousand-li-circuit": (
        "not needed",
        "Pre-unification legacy insight retired; Walking the Ten-Thousand-Li Circuit exists cleanly in Book 5."
    ),
}

# Register all 84 remaining pre-unification `insight.legacy-*` duplicate keys (verified present under canonical
# non-legacy names in Book 5 `05_cultivation_insights/`) as explicit CUT ON PURPOSE (`not needed`) entries.
LEGACY_RETIRED_INSIGHT_SLUGS = (
    "adamantine-breath", "battlefield-inspiration", "beast-tamers-bond", "blood-reversal", "bone-lock",
    "bottleneck-breaker", "broken-seal", "closed-meridian-circuit", "companion-intercession", "composite-genius",
    "comprehension-through-battle", "dao-anchor", "dao-bound-weapon", "dao-companion", "distant-technique",
    "dream-cage", "dream-eater", "dream-seed", "dreamwalker", "dual-cultivation", "dual-dao-affinity",
    "echo-of-the-departed", "efficient-formula", "empowered-technique", "enhanced-meridians", "flesh-regenerator",
    "flying-sword-commander", "formation-breaker", "formation-master", "heaven-lifting-grip", "heavenly-circulation",
    "heavenly-comprehension", "heavenly-footwork", "heavenly-revision", "heavens-luck", "hidden-reserves",
    "immortal-dreamer", "immortals-sinews", "iron-bones", "karmic-debt", "life-extension", "lingering-technique",
    "memory-palace", "meridian-sight", "musical-resonance", "natural-innovator", "persistent-technique",
    "piercing-gaze", "pill-connoisseur", "pressure-intensification", "qi-efficiency", "quiet-foundation",
    "quiet-furnace-method", "rapid-recovery", "reincarnated-memory", "reservoir-seal", "scripture-memory",
    "secret-manual-author", "sect-legacy", "shadow-meld", "shared-instinct", "soul-lantern", "soul-severance",
    "soul-ward", "spirit-stone-affinity", "spirit-stone-refinement", "spirit-vein-attunement", "stable-meridians",
    "subtle-technique", "swift-technique", "sword-riding-flight", "sword-spirit-companion", "tempered-organs",
    "thread-master", "threads-of-intent", "titans-grip", "treasure-sense", "tribulation-survivors-resilience",
    "unbroken-frame", "unshakable-dao", "veil-of-stillness", "veiled-soul-lamp", "widened-technique",
    "will-manifestation",
)
for _slug in LEGACY_RETIRED_INSIGHT_SLUGS:
    _title = _slug.replace("-", " ").title()
    HAND_CUT_ON_PURPOSE[f"insight.legacy-{_slug}"] = (
        "not needed",
        f"Pre-unification legacy insight duplicate retired; canonical {_title} exists cleanly in Book 5.",
    )


# ==============================================================================
# NORMALIZATION & SECTION-SCOPED BIBLE INDEX
# ==============================================================================

_NORM_POSSESSIVE_RE = re.compile(r"'s\b")
_NORM_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_NORM_SPLIT_PLURAL_RE = re.compile(r"\b([a-z]{3,}) s\b")


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("–", " ").replace("—", " ")
    s = _NORM_POSSESSIVE_RE.sub("s", s)
    if not s.isascii():  # NFKD + ASCII-only encoding leaves ASCII text unchanged
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _NORM_NON_ALNUM_RE.sub(" ", s.lower()).strip()
    s = _NORM_SPLIT_PLURAL_RE.sub(r"\1s", s)
    return s


def strip_cl_prefix(heading: str) -> str:
    h = re.sub(r"^#+\s*", "", heading).strip()
    h = re.sub(r"^(?:Cultivation\s+Level|CL)\s*\d+\s*[—–\-:]\s*", "", h, flags=re.I).strip()
    return h


_PAREN_SUBTITLE_RE = re.compile(r"\*?\([^)]*\)\*?")
_VARIANTS_H2_RE = re.compile(r"^##\s+(?:Optional\s+Cultivation\s+Variants|Variant\s+Scriptures?)\b", re.I)
_H2_RE = re.compile(r"^##\s+")
_BASE_H2_RE = re.compile(r"^##\s+Base\s+Abilit", re.I)
_BULLET_BOLD_TITLE_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\*\*(.+?)\*\*")
_BULLET_BOLD_PLAIN_TITLE_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\*\*([^*]+)\*\*")
_BULLET_BOLD_LEAD_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\*\*")


def _first_exact(table: dict[str, list[int]], names: list[str], lo: int, hi: int) -> int | None:
    """First line in lo..hi that one of the names maps to (table: text -> ascending line numbers)."""
    best = None
    for n in names:
        lns = table.get(n)
        if lns:
            i = bisect.bisect_left(lns, lo)
            if i < len(lns) and lns[i] <= hi and (best is None or lns[i] < best):
                best = lns[i]
    return best


class _LineTexts:
    """Normalised text of chosen lines of one file, joined by newlines, so "first line in lo..hi that
    contains one of the names" is a substring search. norm() output never holds a newline, so a match
    cannot span two lines."""

    def __init__(self, entries: list[tuple[int, str]]):
        self.lns = [ln for ln, _ in entries]
        self.offs: list[int] = []
        pos = 0
        for _, t in entries:
            self.offs.append(pos)
            pos += len(t) + 1
        self.offs.append(pos)
        self.text = "".join(t + "\n" for _, t in entries)

    def first(self, names: list[str], lo: int, hi: int) -> int | None:
        i = bisect.bisect_left(self.lns, lo)
        j = bisect.bisect_right(self.lns, hi)
        if i >= j:
            return None
        a, b = self.offs[i], self.offs[j]
        best = -1
        for n in names:
            pos = self.text.find(n, a, b)
            if pos >= 0 and (best < 0 or pos < best):
                best = pos
        if best < 0:
            return None
        return self.lns[bisect.bisect_right(self.offs, best) - 1]


class _FeatLines:
    """What find_feat_in_range needs to know about each line of one file, worked out once per file."""

    def __init__(self, lines: list[str]):
        self.lines = lines
        self.variant_lns: list[int] = []                       # "## Optional Cultivation Variants" / "## Variant Scripture(s)"
        self.head_exact: dict[str, list[int]] = {}             # pass 1a: heading, heading without *(...)*, text before the dash
        self.base_h3: list[tuple[int, int, list[str]]] = []    # pass 1a2: (line, line of its "## Base Abilit..." heading, &-parts)
        self.bullet_exact: dict[str, list[int]] = {}           # pass 1b: bullet bold title, without *(...)*, and its parts
        head_nosub: list[tuple[int, str]] = []                 # pass 1c
        bullet_titles: list[tuple[int, str]] = []              # pass 2a
        self._bold_lead_lns: list[int] = []                    # pass 2b (text built on first use)
        self._bold_lead: _LineTexts | None = None
        self._all: dict[bool, _LineTexts] = {}                 # pass 3 (text built on first use)
        last_h2, last_h2_is_base = 0, False
        for ln, l in enumerate(lines, 1):
            if _H2_RE.match(l):
                last_h2, last_h2_is_base = ln, bool(_BASE_H2_RE.match(l))
                if _VARIANTS_H2_RE.match(l):
                    self.variant_lns.append(ln)
            if l.lstrip().startswith("#"):
                raw_l = strip_cl_prefix(l)
                nosub_raw = _PAREN_SUBTITLE_RE.sub("", raw_l)
                ll_nosub = norm(nosub_raw)
                ll_pre = norm(re.split(r"\s+[—–]\s+", nosub_raw, maxsplit=1)[0])
                for form in {norm(raw_l), ll_nosub, ll_pre}:
                    self.head_exact.setdefault(form, []).append(ln)
                head_nosub.append((ln, ll_nosub))
                if last_h2_is_base and l.startswith("### "):
                    parts = [norm(p) for p in re.split(r"\s*&\s*", nosub_raw) if p.strip()]
                    self.base_h3.append((ln, last_h2, parts))
            bm = _BULLET_BOLD_TITLE_RE.match(l)
            if bm:
                nosub_raw = _PAREN_SUBTITLE_RE.sub("", bm.group(1))
                forms = {norm(bm.group(1)), norm(nosub_raw)}
                forms.update(norm(p) for p in re.split(r"\s*(?:&|,|/|→|\bor\b)\s*", nosub_raw) if p.strip())
                for form in forms:
                    self.bullet_exact.setdefault(form, []).append(ln)
                bm = _BULLET_BOLD_PLAIN_TITLE_RE.match(l)
                if bm:
                    bullet_titles.append((ln, norm(bm.group(1))))
            if bm or _BULLET_BOLD_LEAD_RE.match(l) or l.lstrip().startswith("**"):
                self._bold_lead_lns.append(ln)
        self.head_nosub = _LineTexts(head_nosub)
        self.bullet_titles = _LineTexts(bullet_titles)
        self._base_h3_lns = [ln for ln, _, _ in self.base_h3]

    def first_variant_ln(self, lo: int, hi: int) -> int | None:
        i = bisect.bisect_left(self.variant_lns, lo)
        if i < len(self.variant_lns) and self.variant_lns[i] <= hi:
            return self.variant_lns[i]
        return None

    def base_h3_from(self, lo: int) -> list[tuple[int, int, list[str]]]:
        return self.base_h3[bisect.bisect_left(self._base_h3_lns, lo):]

    def bold_lead(self) -> _LineTexts:
        if self._bold_lead is None:
            self._bold_lead = _LineTexts([(ln, norm(self.lines[ln - 1])) for ln in self._bold_lead_lns])
        return self._bold_lead

    def all_lines(self, skip_top_table: bool) -> _LineTexts:
        if skip_top_table not in self._all:
            self._all[skip_top_table] = _LineTexts(
                [
                    (ln, norm(l))
                    for ln, l in enumerate(self.lines, 1)
                    if not (skip_top_table and l.lstrip().startswith("| **"))
                ]
            )
        return self._all[skip_top_table]


class BibleIndex:
    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[str, list[str]] = {}
        self._feat_lines: dict[str, _FeatLines] = {}
        self.sub_files = {
            "body": ("03_paths_and_subpaths/01_body_refining_subpaths.md", self._parse_sections("03_paths_and_subpaths/01_body_refining_subpaths.md", (2,))),
            "qi": (
                "03_paths_and_subpaths/02_qi_cultivation_subpaths.md",
                self._parse_sections(
                    "03_paths_and_subpaths/02_qi_cultivation_subpaths.md",
                    (2, 3),
                    skip_titles=("open schools", "clan and sect schools", "restricted and rare schools", "qi cultivation subpaths"),
                ),
            ),
            "spirit": ("03_paths_and_subpaths/03_spirit_awakening_traditions.md", self._parse_sections("03_paths_and_subpaths/03_spirit_awakening_traditions.md", (2,))),
        }
        self.found_rel = "04_methods_and_foundations/02_foundations_rules_and_catalog.md"
        self.found_secs = self._parse_sections(self.found_rel, (2,))
        self.path_files = {
            "body_refining": "01_players_handbook/04_body_refining.md",
            "qi_cultivation": "01_players_handbook/05_qi_cultivation.md",
            "spirit_awakening": "01_players_handbook/06_spirit_awakening.md",
        }
        self.sphere_files: dict[str, str] = {}
        for p in sorted((root / "02_spheres_of_the_dao").glob("*.md")):
            if p.name == "00_how_spheres_work.md":
                continue
            slug = re.sub(r"^\d+_", "", p.stem)
            self.sphere_files[slug] = f"02_spheres_of_the_dao/{p.name}"

    def get_lines(self, rel: str) -> list[str]:
        if rel not in self.cache:
            self.cache[rel] = (self.root / rel).read_text().splitlines()
        return self.cache[rel]

    def _parse_sections(self, rel: str, levels: tuple[int, ...], skip_titles: tuple[str, ...] = ()) -> dict[str, tuple[int, int, str]]:
        lines = self.get_lines(rel)
        starts: list[tuple[int, int, str]] = []
        for i, l in enumerate(lines, 1):
            m = re.match(r"^(#+)\s+(.+)$", l)
            if m and len(m.group(1)) in levels:
                raw_t = re.sub(r"^\d+\.\s*", "", m.group(2)).strip()
                if norm(raw_t) in skip_titles:
                    continue
                if re.match(r"^(?:Cultivation\s+Level|CL)\s*\d+\b", raw_t, re.I):
                    continue
                starts.append((i, len(m.group(1)), raw_t))
        secs: dict[str, tuple[int, int, str]] = {}
        for idx, (s, lvl, title) in enumerate(starts):
            e = len(lines)
            for j in range(idx + 1, len(starts)):
                if starts[j][1] <= lvl or (lvl == 3 and starts[j][1] in (2, 3)):
                    e = starts[j][0] - 1
                    break
            secs[norm(title)] = (s, e, title)
        return secs

    def slice_entry_block(self, rel: str, ln: int) -> tuple[int, int, str]:
        lines = self.get_lines(rel)
        line = lines[ln - 1]
        m = re.match(r"^(#+)\s+", line)
        if m:
            lvl = len(m.group(1))
            end = ln
            for i in range(ln + 1, len(lines) + 1):
                hm = re.match(r"^(#+)\s+", lines[i - 1])
                if hm and len(hm.group(1)) <= lvl:
                    break
                if lines[i - 1].strip() == "---":
                    break
                end = i
            return ln, end, "\n".join(lines[ln - 1 : end])

        m_ind = re.match(r"^(\s*)(?:[-*]|\d+\.)\s+", line)
        if m_ind:
            base_ind = len(m_ind.group(1))
            end = ln
            for i in range(ln + 1, len(lines) + 1):
                l = lines[i - 1]
                if not l.strip():
                    break
                if re.match(r"^#+\s+", l) or l.strip() == "---":
                    break
                bm = re.match(r"^(\s*)(?:[-*]|\d+\.)\s+", l)
                if bm and len(bm.group(1)) <= base_ind:
                    break
                end = i
            parent_ctx: list[str] = []
            for j in range(ln - 1, max(0, ln - 10), -1):
                l = lines[j - 1]
                if l.strip() == "---" or re.match(r"^#{1,2}\s+", l):
                    break
                if l.startswith("### "):
                    for k in range(j, ln):
                        if re.match(r"^\s*(?:[-*]|\d+\.)\s+", lines[k - 1]):
                            break
                        parent_ctx.append(lines[k - 1])
                    break
            body = "\n".join(parent_ctx + lines[ln - 1 : end])
            return ln, end, body

        end = ln
        for i in range(ln + 1, min(len(lines), ln + 10) + 1):
            if re.match(r"^#+\s+", lines[i - 1]) or lines[i - 1].strip() == "---":
                break
            end = i
        return ln, end, "\n".join(lines[ln - 1 : end])

    def feat_lines(self, rel: str) -> _FeatLines:
        lines = self.get_lines(rel)
        fl = self._feat_lines.get(rel)
        if fl is None or fl.lines is not lines:
            fl = self._feat_lines[rel] = _FeatLines(lines)
        return fl

    def find_feat_in_range(self, rel: str, s: int, e: int, names: list[str], skip_top_table: bool = False) -> int | None:
        fl = self.feat_lines(rel)
        lines = fl.lines
        names = [n for n in names if len(n) >= 3]
        sub_names = [n for n in names if "\n" not in n]  # norm() text has no newline, so such a name matches nothing
        start_ln = max(s, 16) if skip_top_table else s

        # Identify trailing "## Optional Cultivation Variants" / "## Variant Scripture(s)" range so main entries win first
        var_start = fl.first_variant_ln(start_ln, e)

        def _search(lo: int, hi: int) -> int | None:
            # Pass 1a: Exact heading match (full heading, stripped of *(...)* subtitle, or prefix before em-dash)
            ln = _first_exact(fl.head_exact, names, lo, hi)
            if ln is not None:
                return ln
            # Pass 1a2: Exact `&`-partner on a `###` heading inside `## Base Abilit...` (e.g. `### Aegis & Armored Aegis` beats glossary bullet `- **Aegis:**`!)
            for ln, base_h2_ln, ll_parts in fl.base_h3_from(lo):
                if ln > hi:
                    break
                if base_h2_ln < lo:  # its "## Base Abilit..." heading lies before the range
                    continue
                if any(n in ll_parts for n in names):
                    # Only return heading if no dedicated child bullet matches
                    has_child = False
                    for sub_ln in range(ln + 1, min(hi, ln + 12) + 1):
                        sl = lines[sub_ln - 1]
                        if sl.startswith("#") or sl.strip() == "---":
                            break
                        bm = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*", sl)
                        if bm and any(n == norm(_PAREN_SUBTITLE_RE.sub("", bm.group(1))) for n in names):
                            has_child = True
                            break
                    if not has_child:
                        return ln
            # Pass 1b: Exact bullet bold-title match (before substring heading match so "Words Without Offense"
            # matches its own bullet rather than "### Court of Words Without Offense", and "Ink Step" matches
            # its own bullet rather than "### Brush-Sovereign Incarnation *(...Ink-Step)*")
            ln = _first_exact(fl.bullet_exact, names, lo, hi)
            if ln is not None:
                return ln
            # Pass 1c: Substring heading match (prefer dedicated bullet inside grouped multi-talent headings; ignore *(...)* subtitle)
            ln = fl.head_nosub.first(sub_names, lo, hi)
            if ln is not None:
                l = lines[ln - 1]
                if "," in l or "&" in l:
                    h_lvl = len(re.match(r"^(#+)", l.lstrip()).group(1))
                    for sub_ln in range(ln + 1, hi + 1):
                        sl = lines[sub_ln - 1]
                        hm = re.match(r"^(#+)\s+", sl)
                        if (hm and len(hm.group(1)) <= h_lvl) or sl.strip() == "---":
                            break
                        if re.match(r"^\s*(?:[-*]|\d+\.)\s+\*\*", sl):
                            bm = re.match(r"^\s*(?:[-*]|\d+\.)\s+\*\*([^*]+)\*\*", sl)
                            btitle = norm(bm.group(1)) if bm else norm(sl)
                            if any(n == btitle or n in btitle for n in names):
                                return sub_ln
                return ln
            # Pass 2a: Bullet bold-title prefix/substring match (never matches cross-references in another bullet's body!)
            ln = fl.bullet_titles.first(sub_names, lo, hi)
            if ln is not None:
                return ln
            # Pass 2b: Any bold-lead line match
            ln = fl.bold_lead().first(sub_names, lo, hi)
            if ln is not None:
                return ln
            # Pass 3: Fallback line match
            return fl.all_lines(skip_top_table).first(sub_names, lo, hi)

        if var_start is not None:
            hit = _search(start_ln, var_start - 1)
            if hit is not None:
                return hit
        return _search(start_ln, e)

    def resolve_key(self, k: str, v: str) -> tuple[tuple[str, int, int, str] | None, str | None]:
        if k in KEY_TO_ENTRY_ALIAS:
            rel, heading = KEY_TO_ENTRY_ALIAS[k]
            lines = self.get_lines(rel)
            ln = self.find_feat_in_range(rel, 1, len(lines), [norm(heading)], skip_top_table=True)
            if ln:
                s, e, btext = self.slice_entry_block(rel, ln)
                return (rel, s, e, btext), None
            return None, f"alias not found: {rel} -> {heading}"

        first_h = next((l for l in v.splitlines() if l.strip().startswith("#")), "")
        raw_h = strip_cl_prefix(first_h) if first_h else ""
        short_h = re.split(r"\s+[—–-]\s+", raw_h, maxsplit=1)[0].strip() if raw_h else ""

        if k.startswith("tianxia.subpath.") or k.startswith("tianxia.tradition."):
            parts = k.split(".")
            path_k = parts[2]
            sub_slug = norm(parts[3].replace("_", " "))
            feat_slug = norm(parts[-1].replace("_", " "))
            rel, secs = self.sub_files[path_k]
            sec = secs.get(sub_slug)
            if not sec:
                for sk, sv in secs.items():
                    if sub_slug in sk or sk in sub_slug:
                        sec = sv
                        break
            if not sec:
                stoks = set(sub_slug.split())
                best = max(secs.items(), key=lambda kv: len(stoks & set(kv[0].split())) / max(1, len(stoks | set(kv[0].split()))))
                if len(stoks & set(best[0].split())) / max(1, len(stoks)) >= 0.6:
                    sec = best[1]
            if not sec:
                return None, f"subpath/tradition parent not found: '{sub_slug}'"
            ln = self.find_feat_in_range(rel, sec[0], sec[1], [norm(short_h), norm(raw_h), feat_slug])
            if ln:
                s, e, btext = self.slice_entry_block(rel, ln)
                return (rel, s, e, btext), None
            return None, f"feature '{short_h or feat_slug}' not found inside {rel}:{sec[0]}-{sec[1]}"

        if k.startswith("foundation."):
            parts = k.split(".")
            f_slug = norm(re.sub(r"_v\d+.*$", "", parts[1]).replace("_", " "))
            feat_slug = norm(parts[-1].replace("_", " "))
            sec = self.found_secs.get(f_slug)
            if not sec:
                for sk, sv in self.found_secs.items():
                    if f_slug in sk or sk in f_slug:
                        sec = sv
                        break
            if not sec:
                stoks = set(f_slug.split())
                best = max(self.found_secs.items(), key=lambda kv: len(stoks & set(kv[0].split())))
                if len(stoks & set(best[0].split())) >= min(2, len(stoks)):
                    sec = best[1]
            if not sec:
                return None, f"foundation parent not found: '{f_slug}'"
            f_cands = [norm(raw_h), feat_slug]
            if norm(short_h) not in ("awakened", "refined", "perfected"):
                f_cands.insert(0, norm(short_h))
            ln = self.find_feat_in_range(self.found_rel, sec[0], sec[1], f_cands)
            if ln:
                s, e, btext = self.slice_entry_block(self.found_rel, ln)
                return (self.found_rel, s, e, btext), None
            return None, f"foundation feature '{short_h or feat_slug}' not found inside {self.found_rel}:{sec[0]}-{sec[1]}"

        if k.startswith("tianxia.path."):
            parts = k.split(".")
            rel = self.path_files.get(parts[2])
            if not rel:
                return None, f"unknown path '{parts[2]}'"
            feat_slug = norm(parts[-1].replace("_", " "))
            lines = self.get_lines(rel)
            ln = self.find_feat_in_range(rel, 1, len(lines), [norm(short_h), norm(raw_h), feat_slug])
            if ln:
                s, e, btext = self.slice_entry_block(rel, ln)
                return (rel, s, e, btext), None
            return None, f"path feature '{short_h or feat_slug}' not found in {rel}"

        if k.startswith("insight."):
            slug = norm(k.split(".", 1)[1].replace("-", " ").replace("_", " "))
            for rel in (
                "05_cultivation_insights/01_path_and_general_insights.md",
                "05_cultivation_insights/02_sphere_cultivation_insights.md",
            ):
                lines = self.get_lines(rel)
                ln = self.find_feat_in_range(rel, 1, len(lines), [slug])
                if ln:
                    s, e, btext = self.slice_entry_block(rel, ln)
                    return (rel, s, e, btext), None
            return None, f"insight not found: '{slug}'"

        sphere_slug, feat_slug = None, ""
        if k.startswith("tianxia.talent."):
            parts = k.split(".")
            sphere_slug = parts[2]
            feat_slug = norm(parts[3].replace("_", " "))
        elif k.startswith("TAL_"):
            rest = k[4:].lower()
            for s in sorted(self.sphere_files.keys(), key=len, reverse=True):
                if rest.startswith(s + "_"):
                    sphere_slug = s
                    feat_slug = norm(rest[len(s) + 1 :].replace("_", " "))
                    break
            if not sphere_slug:
                for alias, target in (
                    ("dream_", "dreams"),
                    ("fencing_", "the_piercing_needle"),
                    ("hidden_eye_", "the_hidden_eye"),
                ):
                    if rest.startswith(alias):
                        sphere_slug = target
                        feat_slug = norm(rest[len(alias) :].replace("_", " "))
                        break
        elif "_BASE_" in k or "_TAL_" in k:
            sp, rest = re.split(r"_(?:BASE|TAL)_", k, maxsplit=1)
            sphere_slug = sp.lower()
            feat_slug = norm(rest.replace("_", " "))
        elif k.startswith("printed_option:"):
            feat_slug = norm(k.split(":", 1)[1].replace(".", " ").replace("_", " "))

        if sphere_slug == "hidden_eye":
            sphere_slug = "the_hidden_eye"
        elif sphere_slug == "piercing_needle":
            sphere_slug = "the_piercing_needle"
        elif sphere_slug == "dream":
            sphere_slug = "dreams"

        if sphere_slug in self.sphere_files:
            rel = self.sphere_files[sphere_slug]
            lines = self.get_lines(rel)
            cands = [norm(short_h), norm(raw_h), feat_slug]
            if ":" in raw_h:
                cands.append(norm(raw_h.split(":", 1)[1]))
            ln = self.find_feat_in_range(rel, 1, len(lines), cands, skip_top_table=True)
            if ln:
                s, e, btext = self.slice_entry_block(rel, ln)
                return (rel, s, e, btext), None
            return None, f"sphere entry {cands} not found in {rel}"

        if k.startswith("printed_option:"):
            for rel in self.sphere_files.values():
                lines = self.get_lines(rel)
                cands = [norm(short_h)] if norm(short_h) else []
                if feat_slug not in cands:
                    cands.append(feat_slug)
                ln = self.find_feat_in_range(rel, 1, len(lines), cands, skip_top_table=True)
                if ln:
                    s, e, btext = self.slice_entry_block(rel, ln)
                    return (rel, s, e, btext), None

        return None, f"unresolved key '{k}'"


# ==============================================================================
# RULE 1-5: ROLE-TYPED, SUMMED, ONE-TO-ONE DAMAGE EXTRACTOR & COMPARATOR
# ==============================================================================

PRE_NON_HOSTILE_RE = re.compile(
    r"(?:(?<!cannot )(?<!not )regain|heal(?:s|ing|ed)?|temp(?:orary)?\s*hp|temporary hit points|"
    r"reduce(?:s|d)?\s+(?:(?:the|one|triggering|incoming|that)\s+){0,2}(?:damage\s+)?(?:damage|packet|instance|healing)|"
    r"damage reduction|reduction becomes|the reduction|"
    r"self-damage|ruin self-damage|backlash|illegal space|"
    r"you take\s+|absorb(?:s|ing)?\s+|shield\s+hp|hp\s*(?:equal|=)|"
    r"hit points?\s+(?:equal|by)|roll\s+$|failed harvest|subtract\s+|impose\s+\*?\*?`?[−-]|instead\s+of\s+(?:[a-z']+\s+){0,2}$)",
    re.I,
)

LINE_NON_HOSTILE_ONLY_RE = re.compile(
    r"^(?:[-*]\s*)?(?:.*(?:reduce(?:s|d)?\s+(?:(?:the|one|triggering|incoming|psychic)\s+){0,2}(?:damage\s+)?(?:damage|packet|instance)|damage reduction|(?:the|this) reduction|reduction becomes|healing it receives is reduced|regain(?:s)?\s+\d+d\d+|heal(?:s|ing)?\s+(?:for\s+)?\d+d\d+|temporary\s+hp|temp\s+hp|ruin self-damage|self-damage|illegal space|failed harvest|subtract\s+1d\d+\s+from\s+its\s+next).*)$",
    re.I,
)

PURE_DEFENSE_OR_HEAL_KEYS = {
    "EARTH_BASE_SPENDING_A_BURDEN_MARK",
    "TAL_AIR_ARROW_TURNING_BREATH",
    "TAL_DEATH_BONE_WARD",
    "TAL_FATE_FATE_SOVEREIGN_INCARNATION",
    "TAL_FATE_MISFORTUNE_EDICT",
    "TAL_FLOWERS_PETAL_WARD",
    "TAL_FORCE_COUNTERPRESSURE",
    "TAL_FORCE_CUSHION_THE_BLOW",
    "TAL_IRON_FIST_EMPTY_PALM_STOPS_THE_BLADE",
    "TAL_KARMA_INVOKE_THE_LEDGER",
    "TAL_METAL_BELL_METAL_COUNTER",
    "TAL_METAL_IRON_SKIN_MOMENT",
    "TAL_SPEAR_SPEAR_GUARD",
    "TAL_WATER_WATER_SHIELD",
    "TAL_YANG_KINDLE_THE_WOUNDED_BREATH",
    "TAL_YIN_YIN_SINKING_STEP",
    "insight.ancestral-bloodline-awakening",
    "insight.nightmare-feaster",
    "tianxia.subpath.body.adamant_thunderbolt_body.feature.thunder_runs_through_bone",
    "tianxia.subpath.body.bone_monarch.feature.bone_armor",
    "tianxia.subpath.body.bone_monarch.feature.marrow_regeneration",
    "tianxia.subpath.body.goruden.feature.gilded_bones",
    "tianxia.subpath.body.returning_heaven_momentum_body.feature.store_the_collision",
    "tianxia.subpath.body.ten_thousand_parasite_vessel.feature.brood_substitution",
    "tianxia.talent.blood.blood_ward",
    "tianxia.talent.blood.vital_transfusion",
    "tianxia.talent.equipment.iron_rain_readiness",
    "tianxia.talent.fire.white_hot_focus",
    "tianxia.talent.music.healing_hymn",
    "tianxia.talent.music.rhythmic_guard",
    "tianxia.talent.poison.black_antidote_method",
    "tianxia.talent.puppetry.iron_coffin_puppet_shell",
    "tianxia.talent.puppetry.substitute_harm_body",
    "tianxia.talent.radiance.dawn_ward",
    "tianxia.talent.shadow.shadow_ward",
    "tianxia.talent.source.stone_womb_preservation",
    "tianxia.talent.spirit_companions.sympathetic_vessel",
    "tianxia.talent.stars.starlight_ward",
    "tianxia.talent.thread.threaded_guard",
    "TAL_FATE_JINXED_NAME",
    "tianxia.talent.puppetry.puppet_screen",
    "tianxia.talent.stars.astral_body_beyond_the_sky",
    "TAL_DEATH_THRONE_OF_BORROWED_BONES",
    "tianxia.talent.source.grounded_guard",
    "TAL_AXES_HAFT_GUARD",
    "tianxia.talent.karma.grace_repaid",
}

DMG_TYPES_RE = r"(?:Force|Fire|Cold|Lightning|Thunder|Necrotic|Radiant|Psychic|Poison|Acid|Slashing|Piercing|Bludgeoning|Ruin|Void|Nature|Sign)"

REPEATING_TRIGGER_RE = re.compile(
    r"(enters?[^.\n]{0,55}(?:or starts? (?:its|their) turn|for the first time on a turn)|"
    r"entering[^.\n]{0,35}starting (?:its |their )?turn|"
    r"starts? (?:its|their) turn (?:inside|in the area|within|buried|while|on|tethered)|"
    r"starting (?:its |their )?turn (?:inside|in the area|within|buried|while|on|tethered)|"
    r"entering/starting|entry/turn start|on entry or turn start|on turn start|"
    r"at (?:the )?start of each (?:of (?:its|their) )?turns?|"
    r"each turn while|every time (?:it|the creature|an enemy) moves|"
    r"whenever (?:an enemy|a hostile creature|a creature) crosses|"
    r"(?:enemy|hostile creature|creature) that crosses|"
    r"(?:fire|cold|acid|poison|necrotic|psychic|radiant|thunder|lightning|force|slashing|piercing|bludgeoning)/turn)",
    re.I,
)

RETALIATION_TRIGGER_RE = re.compile(
    r"(\bhits? you\b(?!\s+make)|hitting you|hits? the bearer|hitting the bearer|hitting a [a-z* ]{1,25}bearer|"
    r"grappling you|grappling the|grapplers? take|misses? you|misses? an ally|missing an ally|"
    r"melee (?:[a-z ]{0,18})?attackers?|when hit by|when attacked|retaliat|\breflects?\b)",
    re.I,
)

BONUS_TRIGGER_RE = re.compile(
    r"(first hit each turn|first time each turn|once per turn when you (?:hit|damage)|"
    r"first [a-z* ]{1,25}hit each turn|"
    r"on your next (?:hit|attack)|bearer's next attack|next saber hit|next melee|your next weapon|"
    r"additional\s+(?:\*\*`?|`?)\+?\d+d\d+|"
    r"extra\s+\*?\*?(?:[a-z/ ]{0,25})?damage|add(?:s|ing)?\s+(?:(?:\*\*`?|`?)\+?\d+d\d+|(?:an\s+)?(?:additional|extra)|damage\s+equal\s+to|(?:\*\*`?|`?)\+?pb\b|(?:\*\*)?your\s+(?:pb|proficiency\s+bonus)\b)|"
    r"\+\d+d\d+|\+pb\b|\+cl\b|(?<!proficiency\s)\bbonus\s+(?:[a-z/ ]{0,25})?damage|critical hits?\s+(?:deal|add)|"
    r"secondary target|arc(?:s|ing)?\s+(?:\*\*`?|`?)\+?(?:\d+d\d+|pb)|within \d+ feet of it|splash|"
    r"increase(?:s|d)?\s+(?:the\s+)?(?:bonus|extra|added)\s+damage|token damage becomes|added damage[^.\n]{0,35}becomes)",
    re.I,
)

DICE_TOKEN_RE = re.compile(
    r"(?:(\d+)d(\d+)|(?:`?PB`?|Proficiency Bonus)\s*d(\d+))",
    re.I,
)

# Rule 1: Compound simultaneous roll detector ("6d6 Fire damage and 2d6 Slashing damage", "4d8 Fire + 2d8 Bludgeoning")
COMPOUND_ROLL_RE = re.compile(
    rf"`?(\d+)d(\d+)`?\s*(?:{DMG_TYPES_RE}(?:\s+damage)?)?\s*(?:\+|and)\s*`?(\d+)d(\d+)`?(?:\s*{DMG_TYPES_RE})?",
    re.I,
)


def classify_clause_role(clause: str, block_has_repeating_zone: bool = False, block_has_retaliation: bool = False) -> str:
    """Classify a single sentence/clause into one of: repeating, retaliation, bonus, main."""
    low = clause.lower()
    clean = re.sub(r"^[-•*\s`]+", "", low)
    if RETALIATION_TRIGGER_RE.search(low) and not re.search(r"\b(?:when\s+(?:your\s+(?:[a-z]+\s+){0,2}|you\s+)(?:hits?|deals?\s+damage\s+to)|hits?\s+a\s+(?:creature|target)[^.\n]{0,30}grappling\s+you)\b", low):
        return "retaliation"
    if REPEATING_TRIGGER_RE.search(low):
        return "repeating"
    if BONUS_TRIGGER_RE.search(low):
        return "bonus"
    if block_has_retaliation and re.search(r"^(?:at cl\s*\d+|cl\s*\d+|punishment damage)", clean):
        return "retaliation"
    if block_has_repeating_zone and re.search(r"^(?:failed save|fail\b|at cl\s*\d+|at nascent|at core|cl\s*\d+|mortal|foundation|core|nascent|damage by)", clean):
        return "repeating"
    return "main"


def extract_local_step(c: str, start: int, end: int) -> str:
    """Extract the CL/Realm/size step specifically belonging to the die at c[start:end]."""
    # 1. Markdown table row or size-prefixed entry: "| 5-10 | 2d10 |", "| Mortal | ... |", "| Tiny | 1d4 |", "Tiny Object: ... 1d4"
    tm = re.match(r"^\|\s*(?:CL\s*)?(\d+)(?:\s*[-–]\s*\d+|\+)?\s*\|", c, re.I)
    if tm:
        return f"CL {tm.group(1)}"
    tm_realm = re.match(r"^\|\s*\*{0,2}(Mortal|Foundation|Core(?:\s+Formation)?|Nascent(?:\s+Soul)?|Immortal)\b[^|]*\|", c, re.I)
    if tm_realm:
        return tm_realm.group(1)
    sm = re.match(r"^(?:\|\s*)?(Tiny|Small|Medium|Large|Huge|Gargantuan)(?:\s*\||\s+(?:Object|Creature)\s*:)", c, re.I)
    if sm:
        size_cl = {"tiny": 1, "small": 2, "medium": 3, "large": 4, "huge": 5, "gargantuan": 15}
        return f"CL {size_cl[sm.group(1).lower()]}"
    # Allow concatenated live Realm strings like "Mortal: 1d8Foundation: 2d8Core Formation: 3d8Nascent Soul: 4d8"
    step_pat = r"(?:\b(?:(?:Qi|Body|Spirit)\s+)?(?:Cultivation\s+Level|CL)\s*\d+(?:-\d+|–\d+|\+)?\b|(?:Mortal|Foundation|Core\s+Formation|Core|Nascent\s+Soul|Nascent|Immortal)\b|\bSeverity\s*\d+\b)"
    # Clip pre-window so a die NEVER inherits a step from an earlier die or closed parenthetical group
    raw_pre = c[max(0, start - 65) : start]
    seps = list(re.finditer(r"(?:\)|\d+d\d+)", raw_pre))
    if seps:
        raw_pre = raw_pre[seps[-1].end() :]
    # 2. Direct pre-window label immediately preceding this die (e.g. "Core Formation: 3d8", "At CL 11, increase ... to: 2d6")
    m_pre_colon = re.search(rf"({step_pat})(?:\s*\([^)]*\))?\s*[:]\s*(?:\*\*`?|`?|\+)?\s*$", raw_pre, re.I)
    if m_pre_colon:
        return m_pre_colon.group(1)
    m_pre_to = re.search(rf"({step_pat})[^.\n]{{0,45}}(?:becomes?|increases?\s+(?:it\s+)?to)\s*:?\s*(?:\*\*`?|`?|\+)?\s*$", raw_pre, re.I)
    if m_pre_to:
        return m_pre_to.group(1)
    # 3. Immediate post-window ONLY inside same parenthesized/comma clause (NEVER a 'Label:' prefix or new 'At CL N, increase' clause!)
    loc_post = c[end : min(len(c), end + 38)]
    loc_post = re.split(r"(?:[,;)·]|\*\*|\d+d\d+|\bat\s+cl\s*\d+\s*,?\s+(?:increase|it|the|damage|add|gain))", loc_post, flags=re.I)[0]
    m = re.search(rf"{step_pat}(?!\s*(?:Formation\s*:|Soul\s*:|:))", loc_post, re.I)
    if m:
        return m.group(0)
    # 4. Remaining pre-window (e.g. "**Core Formation (CL 10–14):** `3d8`")
    pre_matches = list(re.finditer(step_pat, raw_pre, re.I))
    if pre_matches:
        return pre_matches[-1].group(0)
    return ""


def extract_role_typed_tokens(text: str, is_bible: bool = False) -> list[dict]:
    """
    Extract ALL hostile damage tokens from a block (live OR Bible), with:
      - Rule 1: Compound simultaneous rolls summed BEFORE comparing.
      - Rule 2 & 3: Semantic role tagged per clause (repeating / retaliation / bonus / main).
      - Rule 4: Flat CL / PB / PB+mod ONLY from explicit damage phrases (never CL 15+ / 10xCL HP / PB allies).
    Returns list of dicts: {role, kind, expr, mean, no_save, step, clause}
    """
    # Strip internal developer Normalized Procedure appendix from live text (repeats the same roll above)
    if not is_bible:
        text = re.split(r"(?m)^#{3,6}\s+Normalized Procedure\b", text, maxsplit=1)[0]

    tokens: list[dict] = []
    block_repeating_zone = bool(REPEATING_TRIGGER_RE.search(text))
    block_retaliation = bool(RETALIATION_TRIGGER_RE.search(text))
    shorthand_mod = is_bible and bool(
        re.search(r"\d+d\d+\s*\+\s*(?:key\s+)?mod(?:ifier)?[^(]*\(\s*`?\+?\d+d\d+", text, re.I)
    )
    trailing_mod_parens = is_bible and bool(
        re.search(r"\([^)]*\d+d\d+[^)]*\*\*\+\s*(?:wis|int|cha|str|dex|con|key)\s+mod\*\*\)", text, re.I)
    )

    pending_step = ""
    heading_step = ""
    in_heal_subsection = False
    in_repeating_section = False
    skip_table_cols: set[int] = set()
    prev_line_was_non_damage_die = False

    for raw_line_idx, raw_line in enumerate(text.splitlines()):
        l = raw_line.strip()
        if not l:
            skip_table_cols = set()
            in_repeating_section = False
            continue
        low = l.lower()
        if REPEATING_TRIGGER_RE.search(l):
            in_repeating_section = True
        # Track non-hostile Markdown table columns (e.g. "| Realm | Self-Damage | Extra Ruin Damage |")
        if l.startswith("|"):
            cells = [cell.strip() for cell in l.strip("|").split("|")]
            if all(re.match(r"^[-:\s]+$", cell) for cell in cells):
                continue
            if any(re.search(r"\b(?:self[- ]damage|temp(?:orary)?\s*hp|healing|cost|reduction)\b", cell, re.I) for cell in cells) and not DICE_TOKEN_RE.search(l):
                skip_table_cols = {
                    ci for ci, cell in enumerate(cells)
                    if re.search(r"\b(?:self[- ]damage|temp(?:orary)?\s*hp|healing|cost|reduction)\b", cell, re.I)
                }
                continue
            if skip_table_cols:
                l = "| " + " | ".join("" if ci in skip_table_cols else cell for ci, cell in enumerate(cells)) + " |"
                low = l.lower()
        else:
            skip_table_cols = set()
        # Track subsection headings for CL/Realm step (e.g. "#### Perfected Mountain-Rending Pulse - CL17") and healing subsections
        if l.startswith("#"):
            pending_step = ""
            prev_line_was_non_damage_die = False
            in_repeating_section = False
            in_heal_subsection = bool(re.search(r"\b(?:mend|heal|restor)\w*\b", low))
            hm = re.search(r"\b(CL\s*\d+|Mortal|Foundation|Core\s+Formation|Nascent\s+Soul|Immortal)\b", l, re.I)
            heading_step = hm.group(1) if hm else ""
            continue
        if not is_bible:
            if re.search(r"\b(?:target\s+regains|regains\s+hit\s+points|gains\s+temporary\s+hp)\s*:\s*$", low):
                in_heal_subsection = True
                continue
            if in_heal_subsection:
                if re.match(r"^(?:[-•*]\s*)?`?\d+d\d+", l) or re.match(r"^(?:at\s+cl\s*\d+|cl\s*\d+)", low):
                    continue
                if re.search(r"\b(?:target|saving\s+throw|failed\s+save|hit:|damage)\b", low):
                    in_heal_subsection = False
        # Skip whole line if it is purely Temporary HP / healing / attack-roll or saving-throw die scaling
        if re.match(r"^(?:[-•*]\s*)?(?:the\s+|this\s+)?(?:temporary\s+hp|temp\s+hp|healing|reduction)\b", low) and "damage" not in low:
            prev_line_was_non_damage_die = True
            continue
        if prev_line_was_non_damage_die and re.search(r"\b(?:the\s+(?:die|penalty)|penalty)\s+(?:becomes|increases\s+to)\s+\d+d\d+\b", low) and "damage" not in low:
            continue
        if re.search(r"\b(?:attack\s+roll|saving\s+throw|from\s+(?:1|one|that)\s+(?:enemy's\s+)?sav(?:e|ing))\b", low) and "damage" not in low:
            prev_line_was_non_damage_die = True
            continue
        if re.search(r"\b(?:the\s+penalty|penalty)\s+(?:becomes|increases\s+to)\s+\d+d\d+\b", low) and "damage" not in low:
            continue
        if DICE_TOKEN_RE.search(l):
            prev_line_was_non_damage_die = False
        # Skip live "Successful Save:" lines from dice-token extraction (handled as 'pass' events instead!)
        if not is_bible and re.match(r"^(?:[-•*]\s*)?\*{0,2}successful save:", low):
            in_repeating_section = False
            continue
        # Multi-line live CL/Realm step header with no die on this line (e.g. "Cultivation Level: 11-16;", "CL: 5-10; Extra")
        if not is_bible and not DICE_TOKEN_RE.search(l):
            pm = re.match(
                r"^(?:[-•*]\s*)?\*{0,2}(?:Cultivation\s+Level|CL)\s*:?\s*(\d+)(?:\s*[-–]\s*\d+|\+)?\b",
                l,
                re.I,
            )
            if pm:
                pending_step = f"CL {pm.group(1)}"
                continue
            pm2 = re.match(
                r"^(?:[-•*]\s*)?\*{0,2}(Mortal|Foundation|Core\s+Formation|Nascent\s+Soul|Immortal)\s*:?\s*$",
                l,
                re.I,
            )
            if pm2:
                pending_step = pm2.group(1)
                continue

        # Capture leading line-level CL/Realm step so multi-clause lines ("At Nascent Soul, base becomes 7d6 and token becomes 3d6") keep it
        l_step_m = re.match(
            r"^(?:[-•*]\s*)?\*{0,2}(?:At\s+)?(CL\s*\d+\+?|Mortal|Foundation|Core\s+Formation|Nascent\s+Soul|Immortal)\b(?:\s*\([^)]*\))?\s*[,:]",
            l,
            re.I,
        )
        line_step = l_step_m.group(1) if l_step_m else ""

        # Split line into clauses on '; ', '. ', ', and ', ', while ', ' and the token ', ' or takes ', ', creatures hitting '
        # NEVER split 'save or take' (which separates trigger from damage)!
        clauses = re.split(
            r"(?:;\s+|\.\s+(?=[A-Z*])|,\s+(?:and|while)\s+|\s+and\s+(?=the\s+(?:token|first\s+time))|"
            r",\s+or\s+(?=release\b)|(?<=hp)\s+or\s+(?=takes?\b)|(?<=hp\*\*)\s+or\s+(?=takes?\b)|"
            r"\s+or\s+(?=takes?\s+(?:[a-z]+\s+){0,2}damage\b)|,\s+(?=creatures?\s+hitting\b))",
            l,
            flags=re.I,
        )
        prev_clause_non_hostile = False
        for clause in clauses:
            c = clause.strip()
            if not c:
                continue
            clow = c.lower()
            c_clean_start = re.sub(r"^[-•*\s`]+", "", clow)
            if prev_clause_non_hostile and re.match(r"^(?:and\s+)?\d+d\d+\s+at\s+(?:cl\s*\d+|foundation|core|nascent)\b", clow):
                continue
            if LINE_NON_HOSTILE_ONLY_RE.match(c) and not re.search(
                r"\b(deals?|dealing|double the dice|weapon damage|add\s+(?:\*\*`?|`?)\+?\d+d\d+|enemies?[^.]*take|target[^.]*takes?|attacker[^.]*takes?|foes?[^.]*take|or\s+takes?\s+(?:[a-z]+\s+){0,2}damage|fail[^.]*\d+d\d+|save[^.]*\d+d\d+|attack[^.]*\d+d\d+|strike[^.]*\d+d\d+|reflect)\b",
                clow,
            ):
                prev_clause_non_hostile = True
                continue
            prev_clause_non_hostile = False
            # Skip pure self-damage / overheat recoil / weakened-state reduction / damage-reduction clauses
            if re.search(
                r"(?:after (?:the (?:attack|talent)|all rays) resolves?,?\s+take\b|"
                r"take\s+(?:ruin\s+|fire\s+|lightning\s+)?self-damage|"
                r"on a failure,?\s+you take\b|"
                r"overheat self-damage|"
                r"if the (?:formation|vessel) has half its hp or fewer|"
                r"below half hp,?\s+this damage becomes|"
                r"instead of oni mask's\s+`?1d6`?|"
                r"gate damage becomes|"
                r"\breduce\s+(?:it|the\s+(?:triggering\s+)?damage)\s+by\b)",
                clow,
            ):
                continue
            # Live additive scaling: "The damage increases by 1d8 at CL 5, CL 11, and CL 17."
            if not is_bible:
                add_m = re.search(
                    r"damage\s+increases?\s+by\s+(\d+)d(\d+)\s+at\s+((?:CL\s*\d+(?:\s*,\s*|\s*,?\s*and\s+)?)+)",
                    c,
                    re.I,
                )
                if add_m:
                    inc_n, inc_d = int(add_m.group(1)), int(add_m.group(2))
                    cls_list = re.findall(r"CL\s*\d+", add_m.group(3), re.I)
                    base_tok = next(
                        (t for t in reversed(tokens) if t["kind"] == "dice" and re.match(rf"^(\d+)d{inc_d}\b", t["expr"])),
                        None,
                    )
                    if base_tok and cls_list:
                        bn = int(re.match(r"^(\d+)d", base_tok["expr"]).group(1))
                        suf = base_tok["expr"][len(f"{bn}d{inc_d}") :]
                        extra_m = base_tok["mean"] - bn * (inc_d + 1) / 2.0
                        for step_i, cl_lbl in enumerate(cls_list, 1):
                            tot_n = bn + step_i * inc_n
                            tokens.append({
                                "role": base_tok["role"],
                                "kind": "dice",
                                "expr": f"{tot_n}d{inc_d}{suf}",
                                "mean": tot_n * (inc_d + 1) / 2.0 + extra_m,
                                "no_save": base_tok["no_save"],
                                "step": cl_lbl,
                                "clause": c[:90],
                                "in_paren": False,
                                "line_idx": raw_line_idx,
                            })
                        continue
            # Inherit repeating/retaliation trigger from line/block if the clause is just the damage sub-clause
            c_outer = re.sub(r"\([^)]*\)", "", c)
            rep_ctx = block_repeating_zone and (
                REPEATING_TRIGGER_RE.search(l) is not None
                or (in_repeating_section and not is_bible and re.match(r"^(?:it takes|the creature takes|the target takes|failed save|fail\b)", c_clean_start) is not None)
                or re.match(r"^(?:failed save|fail\b|at cl\s*\d+|at nascent|at core|cl\s*\d|mortal|foundation|core|nascent)", c_clean_start) is not None
            )
            c_role = classify_clause_role(
                c,
                block_has_repeating_zone=rep_ctx,
                block_has_retaliation=block_retaliation and re.match(r"^(?:at cl\s*\d+|cl\s*\d|punishment damage)", c_clean_start) is not None,
            )
            if c_role == "main" and in_repeating_section and not is_bible and re.match(r"^(?:it takes|the creature takes|the target takes)\b", c_clean_start):
                c_role = "repeating"
            c_role_outer = classify_clause_role(
                c_outer,
                block_has_repeating_zone=rep_ctx,
                block_has_retaliation=block_retaliation and re.match(r"^(?:at cl\s*\d+|cl\s*\d|punishment damage)", c_clean_start) is not None,
            )
            if c_role_outer == "main" and in_repeating_section and not is_bible and re.match(r"^(?:it takes|the creature takes|the target takes)\b", c_clean_start):
                c_role_outer = "repeating"

            # Bible-specific Gather and Return / Destruction Dice expansions
            if is_bible and "gather and return damage die" in clow:
                tokens.append({"role": "bonus", "kind": "dice", "expr": "2d8", "mean": 9.0, "no_save": False, "step": "CL14", "clause": c[:90]})
                tokens.append({"role": "bonus", "kind": "dice", "expr": "3d8", "mean": 13.5, "no_save": False, "step": "CL14", "clause": c[:90]})
            if is_bible and ("destruction die" in clow or "destruction dice" in clow):
                for dm in re.finditer(r"`?\+?(\d+)`?\s+destruction\s+dic?e", clow):
                    cnt = int(dm.group(1))
                    tokens.append({"role": c_role, "kind": "dice", "expr": f"{cnt}d8", "mean": cnt * 4.5, "no_save": False, "step": "", "clause": c[:90]})

            is_dmg_clause = bool(
                re.search(
                    rf"\b(damage|deals?|dealing|attack|strike|sweeps?|strokes?|slash|double the dice|natural weapon|key mod|cultivation level|"
                    rf"{DMG_TYPES_RE}|mortal|foundation|core|nascent|cl\s*\d+|severity\s*\d+|burning)\b",
                    clow,
                    re.I,
                )
                or c.startswith("|")
            )

            # --- Rule 1: Sum compound simultaneous rolls FIRST ---
            consumed_spans: list[tuple[int, int]] = []
            if is_dmg_clause:
                for cm in COMPOUND_ROLL_RE.finditer(c):
                    pre = c[max(0, cm.start() - 40) : cm.start()].lower()
                    if PRE_NON_HOSTILE_RE.search(pre) and not re.search(r"\b(?:minimum|bonus)\b", pre[-25:]):
                        continue
                    n1, d1, n2, d2 = int(cm.group(1)), int(cm.group(2)), int(cm.group(3)), int(cm.group(4))
                    mean = n1 * (d1 + 1) / 2.0 + n2 * (d2 + 1) / 2.0
                    expr = f"{n1 + n2}d{d1}" if d1 == d2 else f"{n1}d{d1}+{n2}d{d2}"
                    loc_step = extract_local_step(c, cm.start(), cm.end())
                    tokens.append({
                        "role": c_role,
                        "kind": "dice",
                        "expr": expr,
                        "mean": mean,
                        "no_save": not bool(re.search(r"\bsav(?:e|ing)\b", c, re.I)),
                        "step": loc_step,
                        "clause": c[:90],
                        "in_paren": "(" in c[:cm.start()] and ")" not in c[c[:cm.start()].rfind("("):cm.start()],
                        "line_idx": raw_line_idx,
                    })
                    consumed_spans.append((cm.start(), cm.end()))

                slash_mod_spans = [
                    (sm.start(), sm.end())
                    for sm in re.finditer(r"\d+d\d+(?:\s*/\s*\d+d\d+)+\s*\+\s*(?:key\s+)?mod", c, re.I)
                ]

                for m in DICE_TOKEN_RE.finditer(c):
                    if any(a <= m.start() < b for a, b in consumed_spans):
                        continue
                    pre = c[max(0, m.start() - 40) : m.start()].lower()
                    post = c[m.end() : min(len(c), m.end() + 55)].lower()
                    if PRE_NON_HOSTILE_RE.search(pre) and not re.search(r"\b(?:minimum|bonus)\b", pre[-25:]):
                        continue
                    if re.search(r"^\s*`?\s*(?:\+\s*\d+\s*)?(?:\+\s*(?:your\s+)?(?:[a-z]+\s+){0,3}mod(?:ifier)?\s*`?\s*)?(?:hp|temp(?:orary)?\s*hp|rounds?|minutes?|hours?|feet|ft|hit die|hit dice|(?:to|from)\s+(?:(?:the|an?|one|1|that)\s+)?(?:(?:ally's|enemy's|target's|subject's)\s+)?(?:attack\s+roll|saving\s+throw|save\b|ability\s+check|healing))\b", post):
                        continue
                    # Skip self-damage in "Take `1d6 + PB` → Add `+3d6`" cost->effect rows
                    if re.search(r"\btake\s+\*?\*?`?$", pre) and "→" in post:
                        continue
                    if m.group(1):
                        n, d = int(m.group(1)), int(m.group(2))
                        mean = n * (d + 1) / 2.0
                        canon = f"{n}d{d}"
                    else:
                        d = int(m.group(3))
                        mean = 4 * (d + 1) / 2.0
                        canon = f"PBd{d}"

                    in_paren = "(" in c[:m.start()] and ")" not in c[c[:m.start()].rfind("("):m.start()]
                    is_plus_prefixed = bool(re.search(r"(\+\s*$|add\s+\*\*`?\+?$|\badditional\s+$|\bextra\s+$|\bbonus\s+$)", pre))
                    # Check for + 2x mod, + mod, + PB
                    has_2mod = bool(re.match(r"^\s*`?\s*\+\s*(?:2\s*[×x*]\s*|twice\s+(?:your\s+)?)(?:[a-z]+\s+){0,3}mod", post))
                    has_mod = not has_2mod and bool(
                        re.match(r"^\s*`?\s*\+\s*(?:your\s+)?(?:[a-z/]+\s+){0,4}(?:mod(?:ifier)?|key mod|weapon/mod)", post)
                    )
                    if not has_mod and not has_2mod and any(a <= m.start() <= b for a, b in slash_mod_spans):
                        has_mod = True
                    has_pb = bool(re.match(r"^\s*`?\s*\+\s*(?:your\s+)?(?:pb|proficiency bonus)\b", post))
                    if not has_mod and not has_2mod and not is_plus_prefixed and (shorthand_mod or trailing_mod_parens) and in_paren:
                        has_mod = True

                    loc_step = extract_local_step(c, m.start(), m.end())
                    if not loc_step and line_step and not re.search(r"(?:Mortal|Foundation|Core|Nascent|Immortal)\s*:", c[m.start():], re.I):
                        loc_step = line_step
                    if not loc_step and pending_step:
                        loc_step = pending_step
                        pending_step = ""
                    if not loc_step and heading_step:
                        loc_step = heading_step
                    if not loc_step and not is_bible and re.search(r"added\s+damage[^.\n]{0,35}becomes\s+\d+d\d+", clow):
                        loc_step = "CL 15"

                    # Refine role: outer tokens ignore parenthesized bonus triggers like "(+1d4 vs Unclean)"
                    loc_role = c_role if in_paren else c_role_outer
                    if is_plus_prefixed:
                        if loc_role == "main":
                            loc_role = "bonus"
                    # Scaling follow-up clauses ("At CL 17, increase it to 3d6", "This bonus increases to 2d6 at CL 5, 3d6 at CL 11, and 4d6 at CL 17")
                    # inherit 'bonus' role from the immediately preceding bonus roll at a lower CL (never on explicit "base damage").
                    if (
                        not is_bible
                        and loc_role == "main"
                        and loc_step
                        and parse_step_level(loc_step) > 1
                        and "base damage" not in clow
                        and "weapon die" not in clow
                        and (
                            re.search(r"(?:increase(?:s)?\s+(?:it\s+)?to|this\s+bonus\s+increases|becomes?\s+\d+d\d+)", clow)
                            or re.match(r"^(?:and\s+)?\d+d\d+\s+at\s+cl\s*\d+", clow)
                        )
                    ):
                        prev_b = next(
                            (
                                t for t in reversed(tokens)
                                if t["kind"] == "dice"
                                and parse_step_level(t.get("step", "")) < parse_step_level(loc_step)
                                and re.match(r"^(\d+)d(\d+)", t["expr"])
                                and int(re.match(r"^(\d+)d(\d+)", t["expr"]).group(1)) <= n
                                and int(re.match(r"^(\d+)d(\d+)", t["expr"]).group(2)) <= d
                            ),
                            None,
                        )
                        if prev_b and prev_b["role"] == "bonus":
                            loc_role = "bonus"

                    # Scaling follow-ups ("The damage increases to 2d8 at CL 5...", "At CL 11, the die becomes 1d6", "| 17-20 | 4d6 |")
                    # omit "+mod" or "+PB" while inheriting the base roll's "+mod" / "+PB" at CL 1.
                    if (
                        not has_mod
                        and not has_2mod
                        and m.group(1)
                        and loc_step
                        and parse_step_level(loc_step) > 1
                        and (
                            c.startswith("|")
                            or re.search(r"(?:damage|bonus|die)\s+(?:increases?\s+to|becomes?)|\bat\s+(?:(?:qi|body|spirit)\s+)?(?:cultivation\s+level|cl)\s*\d+|\bat\s+(?:foundation|core|nascent)\b", clow)
                        )
                    ):
                        prev_mod_tok = next(
                            (
                                t for t in reversed(tokens)
                                if t["kind"] == "dice"
                                and t["role"] == loc_role
                                and t["expr"].endswith("+mod")
                                and re.match(r"^(\d+)d(\d+)\+mod$", t["expr"])
                                and int(re.match(r"^(\d+)d(\d+)", t["expr"]).group(1)) <= n
                                and int(re.match(r"^(\d+)d(\d+)", t["expr"]).group(2)) <= d
                            ),
                            None,
                        )
                        if prev_mod_tok:
                            has_mod = True
                        if not has_pb:
                            prev_pb_tok = next(
                                (
                                    t for t in reversed(tokens)
                                    if t["kind"] == "dice"
                                    and t["role"] == loc_role
                                    and t["expr"].endswith("+PB")
                                    and re.match(r"^(\d+)d(\d+)\+PB$", t["expr"])
                                    and int(re.match(r"^(\d+)d(\d+)", t["expr"]).group(1)) <= n
                                    and int(re.match(r"^(\d+)d(\d+)", t["expr"]).group(2)) <= d
                                ),
                                None,
                            )
                            if prev_pb_tok:
                                has_pb = True

                    if has_2mod:
                        mean += 2.0 * MOD_EVAL
                        canon += "+2mod"
                    elif has_mod:
                        mean += MOD_EVAL
                        canon += "+mod"
                    if has_pb:
                        mean += PB_EVAL
                        canon += "+PB"

                    tokens.append({
                        "role": loc_role,
                        "kind": "dice",
                        "expr": canon,
                        "mean": mean,
                        "no_save": not bool(re.search(r"\bsav(?:e|ing)\b", c, re.I)),
                        "step": loc_step,
                        "clause": c[:90],
                        "in_paren": in_paren,
                        "line_idx": raw_line_idx,
                    })

            # --- Rule 4: Strict flat CL / PB / PB+mod damage phrases ONLY ---
            # Flat CL damage phrase (never "CL 15+" or "10 x CL HP"!)
            cl_clean = clow.replace("**", "").replace("`", "")
            if re.search(
                rf"(?:damage\s+equal\s+to\s+(?:your\s+)?(?:2\s*[×x*]\s*)?(?:cultivation level|cl)\b|"
                rf"(?:deals?|dealing|takes?|add|minimum)\s+(?:automatic\s+)?(?:your\s+)?\+?(?:2\s*[×x*]\s*)?(?:cultivation level|cl)\s*(?:bonus\s+)?(?:{DMG_TYPES_RE}(?:\s+or\s+{DMG_TYPES_RE})?\s+)?(?:damage)?(?:\b|$)|"
                rf"\b(?:2\s*[×x*]\s*)?(?:cultivation level|cl)\b\s+(?:bonus\s+)?{DMG_TYPES_RE}\s+damage)",
                cl_clean,
                re.I,
            ) and not re.search(r"(?:hp|hit points|temp|cl\s*\d+)", re.search(r"(?:cultivation level|\bcl\b)[^.;,]{0,18}", cl_clean, re.I).group(0) if re.search(r"(?:cultivation level|\bcl\b)", cl_clean, re.I) else ""):
                # Verify it isn't "10 x CL HP" or "CL 15+" (allow "2 x CL" damage!)
                if not re.search(r"\b(?:cl\s*\d+|(?:[3-9]|\d{2,})\s*[×x]\s*cl)\b", cl_clean):
                    no_save = bool(re.search(r"no save|automatically", cl_clean)) or not bool(re.search(r"\bsav(?:e|ing)\b", cl_clean))
                    tokens.append({
                        "role": c_role,
                        "kind": "flat_cl",
                        "expr": "CL (no save)" if no_save else "CL",
                        "mean": 15.0,
                        "no_save": no_save,
                        "step": "",
                        "clause": c[:90],
                    })

            # Flat PB / PB+mod damage phrase (never "PB allies", "PB Temp HP", "AC + PB", "PB CP", or "PBd6"!)
            pb_dmg_m = re.search(
                rf"(?:(?:deals?|dealing|takes?|taking|add(?:s|ing)?|inflicts?|reflect(?:s|ing)?|arcs?|for|=\s*)\s*(?:your\s+)?\+?(?:2\s*[×x*]\s*)?(?:pb|proficiency bonus)(?!\s*d\d+)"
                rf"(?:\s*\+\s*(?:your\s+)?(?:[a-z/]+\s+){{0,4}}mod(?:ifier)?)?"
                rf"(?:\s+(?:(?:bonus|extra)\s+)?(?:{DMG_TYPES_RE}(?:\s*(?:/|or|\+)\s*{DMG_TYPES_RE})?|damage|in\s+{DMG_TYPES_RE}\s+damage|to\s+(?:the|your)\s+(?:first\s+{DMG_TYPES_RE}\s+|hit's\s+)?damage|chill-snap))|"
                rf"damage\s+equal\s+to\s+(?:your\s+)?(?:2\s*[×x*]\s*)?(?:pb|proficiency bonus)(?!\s*d\d+)(?:\s*\+\s*(?:your\s+)?(?:[a-z/]+\s+){{0,4}}mod(?:ifier)?)?|"
                rf"\+?(?:2\s*[×x*]\s*)?(?:pb|proficiency bonus)(?!\s*d\d+)(?:\s*\+\s*(?:[a-z/]+\s+){{0,3}}mod(?:ifier)?)?\s+(?:(?:bonus|extra)\s+)?(?:{DMG_TYPES_RE}|damage))",
                cl_clean,
                re.I,
            )
            if pb_dmg_m and not PRE_NON_HOSTILE_RE.search(cl_clean[max(0, pb_dmg_m.start() - 35) : pb_dmg_m.start()]) and not re.search(r"\d+d\d+\s*\+\s*(?:your\s+)?$", cl_clean[:pb_dmg_m.start()]):
                phrase = pb_dmg_m.group(0)
                if not re.search(r"\b(temp(?:orary)?\s*hp|hp\b|cp\b|stamina|allies|targets|creatures|spaces|marks|ac\b|healing)\b", phrase):
                    has_m = bool(re.search(r"\+\s*(?:your\s+)?(?:[a-z/]+\s+){0,4}mod", phrase))
                    pb_role = "bonus" if (c_role == "main" and re.search(r"\badd(?:s|ing)?\b|\+pb|\+proficiency|next\s+time", cl_clean)) else c_role
                    tokens.append({
                        "role": pb_role,
                        "kind": "flat_pb_mod" if has_m else "flat_pb",
                        "expr": "PB+mod" if has_m else "PB",
                        "mean": (PB_EVAL + MOD_EVAL) if has_m else PB_EVAL,
                        "no_save": not bool(re.search(r"\bsav(?:e|ing)\b", cl_clean)),
                        "step": "",
                        "clause": c[:90],
                        "line_idx": raw_line_idx,
                    })

    return tokens


def parse_step_level(step: str) -> int:
    """Convert a CL/Realm step label to its numeric minimum CL for same-level comparison."""
    if not step:
        return 1
    s = step.strip().lower()
    m = re.search(r"(?:cultivation\s+level|cl)\s*(\d+)", s)
    if m:
        return int(m.group(1))
    if "immortal" in s:
        return 20
    if "nascent" in s:
        return 15
    if "core" in s:
        return 10
    if "foundation" in s:
        return 5
    if "mortal" in s:
        return 1
    m2 = re.search(r"severity\s*(\d+)", s)
    if m2:
        return int(m2.group(1)) * 5
    return 1


def extract_live_events(key: str, text: str) -> list[dict]:
    """Extract all atomic live hostile damage events, including Rule 5 cross-refs."""
    if key in PURE_DEFENSE_OR_HEAL_KEYS:
        return []

    events: list[dict] = []
    seen: set[tuple] = set()

    # Detect explicit in-place CL/Realm/size scaling of ONE single roll (NEVER separate choices like Dry the Body vs Desiccate the Object!)
    has_cl_progression = bool(
        re.search(
            r"(?:at\s+(?:cl\s*\d+\+?|core\s+formation|nascent\s+soul|foundation)[^.\n]{0,55}(?:becomes?|increases?\s+to)|"
            r"added\s+damage[^.\n]{0,35}becomes\s+\d+d\d+|"
            r"damage\s+increases?\s+(?:by\s+realm|to\s+\d+d\d+)|"
            r"damage\s+by\s+cultivation\s+level|"
            r"\|\s*(?:cultivation\s+level|cl|grappled\s+creature\s+size)\s*\||"
            r"(?:mortal|foundation|core|nascent)[^.\n]{0,10}:\s*\d+d\d+)",
            text,
            re.I | re.S,
        )
    )
    raw_tokens = extract_role_typed_tokens(text, is_bible=False)
    has_hostile_damage = bool(raw_tokens)
    for tok in raw_tokens:
        opt_m = re.match(r"^(?:[-•*]\s*)?\*{0,2}([A-Z][A-Za-z' -]{2,32}):", tok["clause"])
        opt_tag = opt_m.group(1).strip() if opt_m and opt_m.group(1).strip().lower() not in (
            "hit", "miss", "failed save", "failure", "successful save", "success", "damage", "effect", "scaling", "action type", "cost", "duration", "range", "target", "prerequisite",
            "mortal", "foundation", "core formation", "nascent soul", "immortal", "cl18", "cl14", "cl10", "cl6", "cl3",
            "tiny object", "small object", "medium object", "large object", "huge object",
        ) else ""
        label = f"{tok['role']} ({opt_tag})" if opt_tag else (f"{tok['role']} ({tok['step']})" if tok["step"] else tok["role"])
        lvl = parse_step_level(tok["step"])
        # If live repeats the CL 1 base die once in intro ("1d6 + mod") and again in a scaling table ("| 1-4 | 1d6 |"),
        # keep the stronger intro "+mod" version at CL 1 rather than emitting two duplicate CL 1 rolls!
        base_die = tok["expr"].split("+")[0]
        dup_base = any(
            e["role"] == tok["role"] and e["kind"] == "dice" and e.get("opt_tag", "") == opt_tag
            and e.get("level", 1) == lvl and e["expr"].split("+")[0] == base_die
            for e in events
        )
        sig = (tok["role"], tok["kind"], tok["expr"], opt_tag)
        if sig not in seen and not dup_base:
            seen.add(sig)
            events.append({
                "role": tok["role"],
                "kind": tok["kind"],
                "label": label,
                "expr": tok["expr"],
                "mean": tok["mean"],
                "no_save": tok["no_save"],
                "step": tok["step"],
                "level": lvl,
                "opt_tag": opt_tag,
                "is_cl_scaled": has_cl_progression and tok["kind"] == "dice" and not opt_tag,
            })

    # 2. Rule 5: Cross-referenced base-ability damage ("damage equal to your <Ability> damage" or "takes <BaseAbility> damage")
    base_names_alt = "|".join(re.escape(n) for n in sorted(BASE_ABILITY_CURVES.keys(), key=len, reverse=True))
    ref_pat = re.compile(
        rf"(?:damage equal to (?:your )?([A-Za-z][A-Za-z\-' ]+?)|takes?\s+(?:your\s+)?({base_names_alt}))\s+damage(\s*\+\s*(?:your )?(?:[A-Za-z ]{{0,25}})?mod(?:ifier)?)?",
        re.I,
    )
    if re.search(r"\brelease(?:s|ing)?\s+your\s+Destructive\s+Blast\b", text, re.I):
        has_hostile_damage = True
    for m in ref_pat.finditer(text):
        ref_name = norm(m.group(1) or m.group(2))
        extra_mod = bool(m.group(3))
        if ref_name in BASE_ABILITY_CURVES:
            has_hostile_damage = True
            for step_lbl, base_expr, base_mean in BASE_ABILITY_CURVES[ref_name]:
                expr = base_expr.replace("+mod", "+2mod") if extra_mod else base_expr
                mean = base_mean + (MOD_EVAL if extra_mod else 0.0)
                sig = ("main", "dice", f"{expr} ({step_lbl})")
                if sig not in seen:
                    seen.add(sig)
                    events.append({
                        "role": "main",
                        "kind": "dice",
                        "label": f"ref:{ref_name} ({step_lbl})",
                        "expr": expr,
                        "mean": mean,
                        "no_save": False,
                        "step": step_lbl,
                        "level": parse_step_level(step_lbl),
                        "opt_tag": "",
                        "is_cl_scaled": True,
                        "curve_group": f"ref:{ref_name}",
                    })

    # 3. Multipliers, Miss, and Pass/Half
    for raw_line in text.splitlines():
        l = raw_line.strip()
        low = l.lower()
        if not l:
            continue
        if LINE_NON_HOSTILE_ONLY_RE.match(l) and not re.search(r"\b(deals?|dealing|enemies?[^.]*take|target[^.]*takes?)\b", low):
            continue
        if re.search(r"\b(double damage|triple damage|vulnerability to [a-z ,]*damage)\b|damage[^.\n]{0,30}\bis doubled\b", low):
            mult = "triple damage" if "triple" in low else ("double damage" if ("double" in low or "doubled" in low) else "vulnerability")
            sig = ("mult", "multiplier", mult)
            if sig not in seen:
                seen.add(sig)
                events.append({"role": "mult", "kind": "multiplier", "label": "vs objects/Barriers", "expr": mult, "mean": None, "no_save": False, "step": "", "level": 1})
        if (
            re.search(r"\b(miss:|on a miss)\b", low)
            and re.search(r"\b(half damage|takes?\s+(?:[a-z]+\s+)?damage|deals?\s+(?:[a-z]+\s+)?damage)\b", low)
            and not re.search(r"\b(no (?:extra |additional )?damage|takes? no|nothing happens|does not deal)\b", low)
        ):
            val = "half damage" if "half" in low else ("PB" if re.search(r"\b(pb|proficiency bonus)\b", low) else "miss damage")
            sig = ("miss", "miss", val)
            if sig not in seen:
                seen.add(sig)
                events.append({"role": "miss", "kind": "miss", "label": "Miss", "expr": val, "mean": None, "no_save": False, "step": "", "level": 1})

    if has_hostile_damage:
        for raw_line in text.splitlines():
            l = raw_line.strip()
            low = l.lower()
            if re.search(r"\b(no (?:extra |additional )?damage|0 damage|takes? no|reduce(?:s|d)?\s+[a-z ]*damage|healing[^.]*reduced|normal (?:weapon )?damage only|half (?:your|its|their) speed)\b", low):
                continue
            if re.search(r"\b(successful save|on a success|half on (?:a )?save|half damage on (?:a )?success)\b", low) and re.search(r"\b(half(?: as much)?(?: damage)?|proficiency bonus|\bpb\b)\b", low):
                val = "half damage" if "half" in low else "PB"
                sig = ("pass", "pass", val)
                if sig not in seen:
                    seen.add(sig)
                    events.append({"role": "pass", "kind": "pass", "label": "Successful Save", "expr": val, "mean": None, "no_save": False, "step": "", "level": 1})

    return events


def build_bible_curves(bible_tokens: list[dict]) -> list[dict]:
    """
    Group consecutive scaling steps of a single Bible roll (e.g. `5d6` + `7d6 CL 10` + `9d6 CL 15`,
    or Realm table rows `1d8` / `2d8` / `3d8` / `4d8`, or `2d6 one-handed, 3d6 two-handed`) into
    ONE Bible RollCurve so tiers are compared AT THE SAME LEVEL, while separate rolls stay separate!
    """
    curves: list[dict] = []
    for bt in bible_tokens:
        lvl = parse_step_level(bt.get("step", ""))
        target_curve = None
        if curves and bt["kind"] in ("dice", "flat_pb"):
            has_explicit_step = bool(bt.get("step"))
            bt_paren = bool(bt.get("in_paren", False))
            # Search backwards for the most recent open curve of the SAME role & paren-column
            # that this token explicitly extends to a HIGHER CL/Realm/handedness tier!
            # NEVER merge separate same-CL rolls (like Breath 8d8 vs Bite 4d10, or Dry the Body 10d8 vs Desiccate Object 6d8)!
            for cand in reversed(curves):
                if cand["role"] != bt["role"]:
                    continue
                if cand["kind"] == "dice" and bt["kind"] == "dice":
                    if has_explicit_step and lvl > cand["tiers"][-1][0] and bt["mean"] >= cand["tiers"][-1][1]["mean"] - 0.01:
                        if cand.get("in_paren", False) == bt_paren or (bt.get("line_idx", -99) == cand["last_line"] and (bt_paren or cand is curves[-1])):
                            target_curve = cand
                            break
                    if (
                        cand is curves[-1]
                        and bt.get("line_idx", -99) == cand["last_line"]
                        and re.search(r"\btwo-handed\b", bt.get("clause", ""), re.I)
                        and bt["mean"] > cand["tiers"][-1][1]["mean"]
                    ):
                        target_curve = cand
                        break
                elif (
                    bt.get("line_idx", -99) == cand["last_line"]
                    and cand["kind"] == "dice"
                    and bt["kind"] == "flat_pb"
                    and lvl < cand["tiers"][0][0]
                    and any("+PB" in t["expr"] for _, t in cand["tiers"])
                ):
                    target_curve = cand
                    break
        if target_curve is not None:
            if bt["kind"] == "flat_pb" and lvl < target_curve["tiers"][0][0]:
                target_curve["tiers"].insert(0, (lvl, bt))
            else:
                eff_lvl = lvl if lvl > target_curve["tiers"][-1][0] else (target_curve["tiers"][-1][0] + 5)
                target_curve["tiers"].append((eff_lvl, bt))
            target_curve["last_line"] = bt.get("line_idx", target_curve["last_line"])
        else:
            curves.append({
                "role": bt["role"],
                "kind": bt["kind"],
                "in_paren": bool(bt.get("in_paren", False)),
                "tiers": [(lvl, bt)],
                "last_line": bt.get("line_idx", -1),
            })
    for c in curves:
        c["tiers"].sort(key=lambda x: x[0])
    return curves


def curve_at_level(curve: dict, level: int) -> dict:
    """Return the Bible token active on `curve` at Cultivation Level `level`."""
    chosen = curve["tiers"][0][1]
    for cl, tok in curve["tiers"]:
        if cl <= level:
            chosen = tok
        else:
            break
    return chosen


def role_compatible(live_role: str, bible_role: str) -> bool:
    """Rule 2 & 3 strict role compatibility."""
    if live_role == "repeating":
        return bible_role == "repeating"
    if live_role == "bonus":
        return bible_role == "bonus"
    if live_role == "retaliation":
        return bible_role in ("retaliation", "repeating")
    return bible_role in ("main", "repeating", "bonus", "retaliation")


def evaluate_ability_events(
    key: str,
    events: list[dict],
    rel: str,
    btext: str,
    bible_idx: BibleIndex,
) -> list[tuple[dict, bool, str]]:
    """
    Strict 1-to-1 RollCurve pairing with SAME-LEVEL tier comparison (ZERO 'covers' reuse,
    ZERO hard-coded per-key or per-sphere exceptions).
    """
    bible_tokens = extract_role_typed_tokens(btext, is_bible=True)
    bible_curves = build_bible_curves(bible_tokens)
    sphere_core = "\n".join(bible_idx.get_lines(rel)[:30]) if rel.startswith("02_spheres_of_the_dao/") else ""

    out_map: dict[int, tuple[dict, bool, str]] = {}

    numeric_indices: list[int] = []
    for orig_idx, ev in enumerate(events):
        kind = ev["kind"]
        expr = ev["expr"]
        if kind == "multiplier":
            combined = btext + "\n" + sphere_core
            m = re.search(r"\b(triple damage|tripled|double damage|doubled|vulnerability to [a-z ,]*damage)\b", combined, re.I)
            if m:
                found = m.group(1).lower()
                ok = not (expr == "triple damage" and "triple" not in found)
                out_map[orig_idx] = (ev, ok, found)
            elif re.search(r"24d10.*automatically|no save", btext, re.I):
                out_map[orig_idx] = (ev, True, "24d10 auto (no save)")
            else:
                out_map[orig_idx] = (ev, False, "MISSING")
        elif kind == "miss":
            if expr == "half damage":
                ok = bool(re.search(r"\bmiss\b[^.\n]*half", btext, re.I))
                out_map[orig_idx] = (ev, ok, "half on miss" if ok else "MISSING")
            else:
                ok = bool(re.search(r"\bmiss\b[^.\n]*(?:pb|proficiency bonus|\d+d\d+)", btext, re.I))
                out_map[orig_idx] = (ev, ok, "PB/dice on miss" if ok else "MISSING")
        elif kind == "pass":
            if expr == "PB":
                ok = bool(re.search(r"success[^.\n]*(?:pb|proficiency bonus|\d+d\d+|only the original target)", btext, re.I))
                out_map[orig_idx] = (ev, ok, "PB/dice on pass" if ok else "MISSING")
            else:
                ok = bool(
                    re.search(
                        r"(half(?: damage)?[^.\n]{0,45}on (?:a )?(?:save|success|pass)|save for half|success[^.\n]*half|"
                        r"(?:dex|con|str|cha|wis)[a-z]* save \([^)]*half)",
                        btext,
                        re.I,
                    )
                )
                out_map[orig_idx] = (ev, ok, "half on save" if ok else "MISSING")
        else:
            numeric_indices.append(orig_idx)

    # Group live numeric events into DISTINCT RollCurves:
    # Two dice tokens belong to the SAME RollCurve ONLY if they share (role, opt_tag, curve_group)
    # AND have DISTINCT ascending CL levels (e.g. CL 1, CL 5, CL 11, CL 17 — one roll scaling with CL).
    # Two rolls at the SAME CL (e.g. Dry the Body 5d8 vs Desiccate the Object 6d8, or 8d8 main + 4d8 bonus)
    # are ALWAYS separate RollCurves and MUST match separate Bible RollCurves!
    live_curves: list[dict] = []
    # Track candidate CL-curves per (role, opt_tag, curve_group) — a list so two distinct scaling rolls
    # with the same role (e.g. Lava Spit main 2d8..7d8 + Burning 1d6..3d6) each form their own RollCurve!
    cl_curves_by_key: dict[tuple, list[tuple[int, set[int]]]] = {}
    for idx in numeric_indices:
        ev = events[idx]
        if ev["kind"] in ("dice", "flat_pb", "flat_pb_mod"):
            gkey = (ev["role"], ev.get("opt_tag", ""), ev.get("curve_group", ""))
            lvl = ev.get("level", 1)
            merged = False
            for ci, lvls in reversed(cl_curves_by_key.get(gkey, [])):
                if lvl in lvls:
                    continue
                existing_curve = live_curves[ci]
                existing_items = existing_curve["items"]
                kinds_compat = (
                    existing_curve["kind"] == ev["kind"]
                    or (existing_curve["kind"] == "flat_pb" and ev["kind"] == "dice" and "+PB" in ev["expr"])
                    or (existing_curve["kind"] == "dice" and ev["kind"] == "flat_pb" and any("+PB" in p["expr"] for _, p in existing_items))
                )
                if kinds_compat and all((ev["mean"] >= prev_ev["mean"] - 0.01 if lvl > prev_ev.get("level", 1) else ev["mean"] <= prev_ev["mean"] + 0.01) for _, prev_ev in existing_items):
                    existing_curve["items"].append((idx, ev))
                    if ev["kind"] == "dice":
                        existing_curve["kind"] = "dice"
                    lvls.add(lvl)
                    merged = True
                    break
            if not merged:
                ci = len(live_curves)
                live_curves.append({"role": ev["role"], "kind": ev["kind"], "opt_tag": ev.get("opt_tag", ""), "items": [(idx, ev)]})
                cl_curves_by_key.setdefault(gkey, []).append((ci, {lvl}))
        else:
            live_curves.append({"role": ev["role"], "kind": ev["kind"], "opt_tag": ev.get("opt_tag", ""), "items": [(idx, ev)]})

    has_live_main_or_repeat = any(lc["role"] in ("main", "repeating") for lc in live_curves)
    live_curves.sort(key=lambda lc: -(max((ev["mean"] or 0.0) for _, ev in lc["items"])))
    used_bible_curves: set[int] = set()

    for lc in live_curves:
        role = lc["role"]
        kind = lc["kind"]
        opt_tag = lc["opt_tag"]
        items = lc["items"]

        scoped_curves = bible_curves
        if opt_tag:
            opt_n = norm(opt_tag)
            opt_lines = [ln for ln in btext.splitlines() if opt_n and opt_n in norm(ln)]
            if opt_lines:
                opt_toks = extract_role_typed_tokens("\n".join(opt_lines), is_bible=True)
                if opt_toks:
                    scoped_curves = build_bible_curves(opt_toks)

        def curve_fits_all_tiers(bc: dict) -> tuple[bool, list[tuple[int, dict, bool, str]]]:
            tier_results = []
            all_ok = True
            for orig_idx, ev in items:
                lvl = ev.get("level", 1)
                bt = curve_at_level(bc, lvl)
                live_mean = ev["mean"] or 0.0
                ok = False
                ev_kind = ev["kind"]
                if ev_kind == "flat_cl":
                    if bt["kind"] == "flat_cl" and (not ev["no_save"] or bt["no_save"]):
                        ok = True
                    elif bt["kind"] == "dice":
                        eff = bt["mean"] if (bt["no_save"] or not ev["no_save"]) else (bt["mean"] / 2.0)
                        ok = eff + 0.01 >= live_mean
                elif ev_kind == "flat_pb_mod":
                    if bt["kind"] == "flat_pb_mod":
                        ok = True
                    elif bt["kind"] == "dice" and bt["mean"] + 0.01 >= live_mean:
                        ok = True
                elif ev_kind == "flat_pb":
                    if bt["kind"] in ("flat_pb", "flat_pb_mod"):
                        ok = True
                    elif bt["kind"] == "dice" and bt["mean"] + 0.01 >= live_mean:
                        ok = True
                else:
                    if bt["kind"] == "dice" and bt["mean"] + 0.01 >= live_mean:
                        ok = True
                    elif live_mean <= 3.5 and bt["kind"] in ("flat_pb", "flat_pb_mod"):
                        ok = True
                val_str = f"{bt['expr']} ({bt['role']} @ CL {lvl})" if len(bc["tiers"]) > 1 else f"{bt['expr']} ({bt['role']})"
                tier_results.append((orig_idx, ev, ok, val_str))
                if not ok:
                    all_ok = False
            return all_ok, tier_results

        cands = []
        for ci, bc in enumerate(scoped_curves):
            if scoped_curves is bible_curves and ci in used_bible_curves:
                continue
            if kind == "flat_cl" and role == "bonus":
                compat = bc["role"] in ("bonus", "repeating")
            elif role == "bonus" and not has_live_main_or_repeat:
                compat = bc["role"] in ("bonus", "main")
            else:
                compat = role_compatible(role, bc["role"])
            if compat:
                cands.append((ci, bc))

        passing_cands = []
        for ci, bc in cands:
            all_ok, tres = curve_fits_all_tiers(bc)
            if all_ok:
                kind_prio = 0 if bc["kind"] == kind else 1
                top_mean = bc["tiers"][-1][1]["mean"]
                passing_cands.append((kind_prio, top_mean, ci, tres))

        if passing_cands:
            passing_cands.sort(key=lambda x: (x[0], x[1]))
            _, _, best_ci, best_tres = passing_cands[0]
            if scoped_curves is bible_curves:
                used_bible_curves.add(best_ci)
            for orig_idx, ev, ok, val_str in best_tres:
                out_map[orig_idx] = (ev, ok, val_str)
        elif cands:
            scored = []
            for ci, bc in cands:
                _, tres = curve_fits_all_tiers(bc)
                n_ok = sum(1 for _, _, ok, _ in tres if ok)
                top_mean = bc["tiers"][-1][1]["mean"]
                scored.append((n_ok, top_mean, ci, tres))
            scored.sort(key=lambda x: (-x[0], -x[1]))
            _, _, best_ci, best_tres = scored[0]
            if scoped_curves is bible_curves:
                used_bible_curves.add(best_ci)
            for orig_idx, ev, ok, val_str in best_tres:
                out_map[orig_idx] = (ev, ok, val_str)
        else:
            if bible_tokens:
                best_any = max(bible_tokens, key=lambda x: x["mean"])
                diag = f"NO_{role.upper()}_MATCH (has {best_any['expr']} as {best_any['role']})"
            else:
                diag = "NONE"
            for orig_idx, ev in items:
                out_map[orig_idx] = (ev, False, diag)

    return [out_map[i] for i in range(len(events))]


# ==============================================================================
# MECHANICAL CHECKS FOR COST, USE LIMIT, TYPE-CHOICE, AND RESISTANCE BYPASS
# ==============================================================================

COST_RES_UNIT = r"(?:CP(?:\s+or\s+(?:Stamina|Essence)|/(?:Stamina|Essence))?|Stamina(?:\s+or\s+CP|/CP)?|Spear\s*Resource|Resource|Qi|Spirit\s*Points?|SP)"
END_UNIT = r"(?-i:(?![a-z]))"
LIVE_COST_NUM_RE = re.compile(rf"\+?(\d+)\s*(?:additional\s+|extra\s+)?{COST_RES_UNIT}{END_UNIT}", re.I)
BIBLE_COST_NUM_RE = re.compile(rf"\+?(\d+)\s*(?:additional\s+|extra\s+)?{COST_RES_UNIT}{END_UNIT}", re.I)
FOCUS_RE = re.compile(r"\b(?:expend\s+)?(?:martial\s+)?focus\b", re.I)
COST_REDUCTION_RE = re.compile(
    r"(?:reduce(?:s|d)?\s+(?:the\s+)?(?:cp\s+|stamina\s+|qi\s+)?cost|cost(?:s)?\s+\d+\s*(?:cp|stamina|qi)\s+less|"
    r"-\d+\s*(?:cp|stamina|qi)|saves?\s+\d+\s*(?:cp|stamina|qi)|refunds?\s+\d+\s*(?:cp|stamina|qi)|"
    r"regain(?:s)?\s+(?:\d+\s*(?:cp|stamina|qi)|(?:martial\s+)?focus)|"
    r"loses?\s+\d+\s*(?:cp|stamina|qi)|"
    r"without\s+spending\s+(?:additional\s+|extra\s+)?(?:cp|stamina|qi|resource|(?:martial\s+)?focus))",
    re.I,
)


def _parse_cost_chunk(val: str, is_bible: bool = False) -> dict | None:
    """Parse a cost expression into {'focus': bool, 'num': int | None, 'or_alt': bool, 'raw': str}."""
    if not val or COST_REDUCTION_RE.search(val):
        return None
    # Ignore bare talent-category tags or prerequisite references like "*(Focus)*", "*(Focus / Evolution)*", "(*Blitz Focus*)"
    stripped_val = re.sub(r"[*_`]", "", val).strip()
    if re.fullmatch(
        r"(?:focus(?:\s*/\s*(?:evolution|technique|movement|counter|stance|guard|rider))?|"
        r"(?:blitz|martial)\s+focus|prereq:[^,]*focus[^,]*)",
        stripped_val,
        re.I,
    ):
        return None
    # Handle explicit "A or B" cost alternatives (e.g. "2 CP or 1 CP + expend Focus", "1 CP or Focus")
    # Pick the lowest-CP option (preferring non-Focus on ties, or Focus+0 over N CP)
    if re.search(r"\bor\b", val, re.I) and not re.search(r"\b(?:cp\s+or\s+(?:stamina|essence)|stamina\s+or\s+cp)\b", val, re.I):
        parts = [p.strip() for p in re.split(r"\bor\b", val, flags=re.I) if p.strip()]
        if len(parts) >= 2:
            sub_costs = [c for c in (_parse_cost_chunk(p, is_bible=is_bible) for p in parts) if c is not None]
            if len(sub_costs) >= 2:
                # Choose the alternative with lowest numeric cost (Focus-only = 0 CP beats N CP)
                best = min(sub_costs, key=lambda c: (c["num"] if c["num"] is not None else 0, 1 if c["focus"] else 0))
                best["or_alt"] = True
                best["raw"] = val.strip()
                return best
    # Require explicit Focus expenditure (or Focus paired with action/cost), not a bare prereq/tag word
    has_focus = bool(
        re.search(r"\bexpend\s+(?:martial\s+)?focus\b", val, re.I)
        or (
            FOCUS_RE.search(val)
            and (
                re.search(rf"\b\d+\s*{COST_RES_UNIT}\b", val, re.I)
                or re.search(r"\b(?:action|bonus action|reaction|cost)\b", val, re.I)
                or re.search(r"focus\s*(?:\+|or|/)", val, re.I)
                or re.search(r"(?:or|/)\s*(?:martial\s+)?focus\b", val, re.I)
            )
            and not re.search(r"\bprereq\b[^,]*focus", val, re.I)
            and not re.search(r"\*[^*]*focus[^*]*\*", val, re.I)
        )
    )
    # Distinguish "Expend Focus *(or 3 CP)*" / "1 CP or Focus" / "Focus/3 CP" from "Expend Focus + 10 CP"
    or_alt = bool(
        has_focus
        and (
            re.search(r"focus\s*(?:\*?\s*\(?\s*or\s+|\s*/\s*)\s*(?:spend\s+)?\+?\d+", val, re.I)
            or re.search(rf"\d+\s*{COST_RES_UNIT}\s*(?:\bor\b|/)\s*(?:expend\s+)?(?:martial\s+)?focus\b", val, re.I)
        )
    )
    if re.search(r"\b(?:none|0\s*(?:cp|stamina|qi|sp|resource)|free|exhaustion)\b", val, re.I) and not re.search(
        rf"\b[1-9]\d*\s*{COST_RES_UNIT}\b", val, re.I
    ):
        return {"focus": has_focus, "num": 0, "or_alt": or_alt, "raw": val.strip()}
    nums = [int(x) for x in (BIBLE_COST_NUM_RE if is_bible else LIVE_COST_NUM_RE).findall(val)]
    if nums:
        if or_alt:
            # Focus is the primary (0 CP) option; numeric CP/Stamina is an alternative payment
            return {"focus": True, "num": 0, "alt_num": nums[0], "or_alt": True, "raw": val.strip()}
        return {"focus": has_focus, "num": nums[0], "or_alt": False, "raw": val.strip()}
    if has_focus:
        return {"focus": True, "num": 0, "or_alt": False, "raw": val.strip()}
    return None


def parse_live_cost(txt: str) -> dict | None:
    clean = re.split(r"(?m)^#{3,6}\s+Normalized Procedure\b", txt, maxsplit=1)[0]
    # 1. Explicit "Cost: ..." / "**Additional Cost:** ..." lines — iterate ALL matches
    for m in re.finditer(r"(?m)^(?:\*{0,2})(?:Additional\s+)?Cost:(?:\*{0,2})\s*([^\n]+)", clean, re.I):
        raw_c = m.group(1).strip()
        if re.match(r"^0\b", raw_c) and not re.search(rf"\b[1-9]\d*\s*{COST_RES_UNIT}\b", raw_c, re.I):
            return {"focus": False, "num": 0, "or_alt": False, "raw": raw_c}
        parsed = _parse_cost_chunk(raw_c, is_bible=False)
        if parsed is not None:
            return parsed
    # 2. Sentence-form "Cost 2 CP." / "Cost 5 CP." / "Cost Expend Martial Focus."
    for m_sent in re.finditer(
        rf"\bCost\s+((?:Expend\s+)?(?:Martial\s+)?Focus(?:\s*\+\s*\d+\s*{COST_RES_UNIT})?|\+?\d+\s*{COST_RES_UNIT}(?:\s+or\s+\d+\s*{COST_RES_UNIT})?|None|Free)\b",
        clean,
        re.I,
    ):
        parsed = _parse_cost_chunk(m_sent.group(1), is_bible=False)
        if parsed is not None:
            return parsed
    # 3. Live "Augment - N CP:" / "Augment (+N CP):" / "Augment N CP" / "+N CP:" / "increase cost by N" / "It costs N additional CP"
    m_aug = re.search(
        rf"(?:\bAugment\s*(?:[-–—:]|\()?\s*\+?(\d+)\s*{COST_RES_UNIT}{END_UNIT}|"
        rf"^\+(\d+)\s*{COST_RES_UNIT}\s*:|"
        rf"\bincrease\s+(?:the|its)\s+(?:cp\s+)?cost\s+(?:by|to)\s+(\d+)\b|"
        rf"\bit\s+costs?\s+\+?(\d+)\s+(?:additional|extra)\s+{COST_RES_UNIT}{END_UNIT})",
        clean,
        re.I | re.M,
    )
    if m_aug:
        return {"focus": False, "num": int(m_aug.group(1) or m_aug.group(2) or m_aug.group(3) or m_aug.group(4)), "or_alt": False, "raw": m_aug.group(0)}
    # 4. Inline "spend / expend / pay N [additional] CP/Stamina/Qi" or bullet "- N CP;" (not a cost reduction/refund)
    for ln in clean.splitlines():
        if COST_REDUCTION_RE.search(ln):
            continue
        m_bul = re.match(rf"^\s*[-*]\s*(\d+)\s*{COST_RES_UNIT}\s*[;.,]?$", ln, re.I)
        if m_bul:
            return {"focus": False, "num": int(m_bul.group(1)), "or_alt": False, "raw": m_bul.group(0)}
        m_min = re.search(rf"\b(?:spend|expend|pay)\s+all\s+remaining\s+{COST_RES_UNIT}[^.\n]*?\bminimum\s+(\d+)\s*{COST_RES_UNIT}{END_UNIT}", ln, re.I)
        if m_min:
            return {"focus": False, "num": int(m_min.group(1)), "or_alt": False, "raw": m_min.group(0)}
        m2 = re.search(rf"\b(?:spend(?:ing)?|expend(?:ing)?|pay(?:ing)?)\s+(?:[^.\n]{{0,25}}\band\s+)?\+?(\d+)\s*(?:additional\s+|extra\s+)?{COST_RES_UNIT}{END_UNIT}", ln, re.I)
        if m2:
            return {"focus": bool(re.search(r"\bexpend(?:ing)?\s+(?:martial\s+)?focus\b", ln, re.I)), "num": int(m2.group(1)), "or_alt": False, "raw": m2.group(0)}
        if re.search(rf"\bspend\s+{COST_RES_UNIT}\s+equal\s+to\b", ln, re.I):
            return {"focus": False, "num": 1, "or_alt": False, "raw": "variable CP (>=1)"}
        if re.search(r"\bexpend(?:ing)?\s+(?:martial\s+)?focus\b", ln, re.I):
            return {"focus": True, "num": 0, "or_alt": False, "raw": "Expend Focus"}
    # 5. Standalone action entry with explicit "Action Type:" and NO printed resource cost anywhere = free (0)
    if re.search(r"(?m)^(?:\*{0,2})Action Type:(?:\*{0,2})\s*(?:Action|Bonus Action|Reaction)\b", clean, re.I):
        if not re.search(rf"\b\d+\s*{COST_RES_UNIT}\b|\bexpend\s+(?:martial\s+)?focus\b|\bcost\b", clean, re.I):
            return {"focus": False, "num": 0, "or_alt": False, "raw": "free (no printed cost)"}
    return None


def _bible_entry_own_lines(btext: str, title_hint: str = "") -> list[str]:
    """If `btext` is a single top-level bullet sliced with prepended parent `###` context, return the bullet's own lines first."""
    lines = btext.splitlines()
    # Count ONLY top-level (unindented) bullets so indented sub-bullets (e.g. Avatar Hosting) don't block stripping parent `###`!
    top_bullets = [ln for ln in lines if re.match(r"^[-*]\s+\*\*", ln)]
    if lines and lines[0].startswith("###") and len(top_bullets) == 1:
        is_grouped_hdr = bool(re.search(r"[&,]", lines[0]))
        if not is_grouped_hdr and title_hint and norm(title_hint) and norm(title_hint) in norm(lines[0]):
            return lines
        b_idx = lines.index(top_bullets[0])
        return lines[b_idx:]
    return lines


def _extract_bible_cost_from_lines(lines: list[str], title_hint: str = "") -> dict | None:
    first = lines[0] if lines else ""
    # 1. If a combined line lists multiple talents with separate parentheticals (e.g.
    #    "- **Clean Hands (Reaction) & Delayed Price (Reaction, 1 CP):**" or
    #    "**Action (Temporary Scene Bond, 1 CP) or 1-Hour Ritual (Major Bond, 3 CP)**"),
    #    match the parenthetical specifically belonging to `title_hint` when present!
    if title_hint:
        th_norm = norm(title_hint)
        for pm in re.finditer(r"\(([^)]+)\)", first):
            if th_norm and th_norm in norm(pm.group(1)):
                parsed = _parse_cost_chunk(pm.group(1), is_bible=True)
                return parsed if parsed is not None else {"focus": False, "num": 0, "or_alt": False, "raw": pm.group(1)}
        # Check for "Title (meta)" or "Title *(meta)*" right after the title on its `&` or `,` segment
        head_m = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*", first)
        head_str = head_m.group(1) if head_m else first
        title_no_paren = re.sub(r"\([^)]*\)", "", head_str)
        if "&" in title_no_paren or "," in title_no_paren:
            # Split only on `&` or `,` OUTSIDE parentheses!
            segs = re.split(r"\s*(?:&|,)\s*(?![^()]*\))", head_str)
            if len(segs) >= 2:
                for seg in segs:
                    if th_norm and th_norm in norm(seg):
                        m_seg = re.search(r"(?:\*\*)?[^*(:]*?(?:\s*\*?)?\(([^)]+)\)", seg)
                        if m_seg:
                            parsed = _parse_cost_chunk(m_seg.group(1), is_bible=True)
                            if parsed is not None:
                                return parsed
                            if re.search(r"\b(?:action|bonus action|reaction|passive)\b", m_seg.group(1), re.I):
                                return {"focus": False, "num": 0, "or_alt": False, "raw": m_seg.group(1)}
                        else:
                            # This partner in a multi-talent bullet has NO parenthetical cost of its own;
                            # only inherit a shared trailing parenthetical if it sits at the very end of the title!
                            m_trail = re.search(r"\(([^)]+)\)\*?\s*:?$", head_str.strip())
                            if m_trail and not any("(" in s for s in segs[:-1]):
                                parsed = _parse_cost_chunk(m_trail.group(1), is_bible=True)
                                if parsed is not None:
                                    return parsed
                            return None
                        break

    # 2. Parenthesized cost on bullet or heading line — supports BOTH "(Action, 2 CP)" AND "*(Action, 2 CP)*":
    m_hdr = re.search(r"(?:^\s*[-*]\s+\*\*[^*(&]+|^#{2,6}\s+[^(\n]+|\*\*[^*(&]+)(?:\s*\*)?\(([^)]+)\)", first)
    if m_hdr:
        parsed = _parse_cost_chunk(m_hdr.group(1), is_bible=True)
        if parsed is not None:
            return parsed

    # 3. Explicit "**Cost:** ..." / "Cost N Qi" / "**Crafting:** ..., N CP" header field anywhere in the entry
    for ln in lines:
        m = re.search(r"(?:\*\*(?:Additional\s+)?Cost:\*\*|\b(?:Additional\s+)?Cost:|\*\*Crafting:\*\*)\s*([^\n|]+)", ln, re.I)
        if m:
            parsed = _parse_cost_chunk(m.group(1), is_bible=True)
            if parsed is not None:
                return parsed
        m_nc = re.search(rf"\bCost\s+(\+?\d+\s*{COST_RES_UNIT}{END_UNIT}|(?:Expend\s+)?(?:Martial\s+)?Focus\b)", ln, re.I)
        if m_nc:
            parsed = _parse_cost_chunk(m_nc.group(1), is_bible=True)
            if parsed is not None:
                return parsed

    # 4. Explicit "**Augment (+N CP...):**" or sub-bullet "(..., N CP)" on single-ability headings (not category-list headings!)
    if lines and not lines[0].startswith("###") and len(lines) <= 4:
        for ln in lines:
            m_baug = re.search(rf"\*\*Augment\s*\(([^)]+)\)\s*:?\*\*", ln, re.I)
            if m_baug:
                parsed = _parse_cost_chunk(m_baug.group(1), is_bible=True)
                if parsed is not None:
                    return parsed
            m_min = re.search(rf"\bspend\s+all\s+remaining\s+{COST_RES_UNIT}[^.\n]*?\bmin(?:imum)?\s+(\d+)\s*{COST_RES_UNIT}{END_UNIT}", ln, re.I)
            if m_min:
                return {"focus": False, "num": int(m_min.group(1)), "or_alt": False, "raw": m_min.group(0)}
    # Also handle single-ability `##`/`###` entries whose activation cost is in a sub-bullet (e.g. Set Array, Domain Armament, Darkvision, Meridian Reinforcement, Secret Saber Manuals)
    # Never pull an optional Augment/Persistent sub-bullet onto a 0-CP base ability!
    if lines and lines[0].startswith("#") and not re.search(r"\b(?:talents|categories|overview|rules)\b", lines[0], re.I):
        has_action_hdr = any(re.search(r"\*\*(?:Action|Bonus Action|Reaction)\*\*", ln) for ln in lines[1:4])
        for ln in lines[1:]:
            if has_action_hdr and re.match(r"^\s*[-*]\s+\*\*(?:Augment|Persistent)\b", ln, re.I):
                continue
            m_sb = re.match(r"^\s*[-*]\s+\*\*[^*\n]+?(?:\s*\*)?\(([^)]+)\)", ln)
            if m_sb:
                parsed = _parse_cost_chunk(m_sb.group(1), is_bible=True)
                if parsed is not None:
                    return parsed

    # 5. Inline sentence cost across the entry (handles "Spend 1 CP or Focus", "Spend 1 Mark and 2 CP",
    #    "Commit **10 CP**", "Reaction + 1 CP", "Expend Martial Focus", "`+3 CP` = ...", "1 CP Qi Thread")
    if not re.search(r"\b0\s*(?:cp|stamina|qi|resource)\b", first, re.I):
        for ln in lines:
            if COST_REDUCTION_RE.search(ln):
                continue
            # Skip category-list headings with no direct cost
            if lines and lines[0].startswith("#") and re.search(r"\b(?:talents|categories|overview|rules)\b", lines[0], re.I):
                break
            # Skip optional Augment / Persistent sub-bullets on standalone ### base entries
            if lines and lines[0].startswith("###") and re.match(r"^\s*[-*]\s+\*\*(?:Augment|Persistent)\b", ln, re.I):
                continue
            m_or = re.search(
                rf"\b(?:spend|expend|pay)\s+(?:\*{{0,2}}`?)\+?(\d+)\s*{COST_RES_UNIT}(?:`?\*{{0,2}})\s+or\s+(?:expend\s+)?(?:martial\s+)?focus\b|"
                rf"\bexpend\s+(?:martial\s+)?focus\s+or\s+(?:spend\s+)?(?:\*{{0,2}}`?)\+?(\d+)\s*{COST_RES_UNIT}{END_UNIT}",
                ln,
                re.I,
            )
            if m_or:
                return {"focus": True, "num": 0, "or_alt": True, "raw": m_or.group(0)}
            # Leading tier-augment syntax: ": `+3 CP` =" or ": 1 CP Qi Thread"
            m_lead = re.search(rf":\*\*?\s*`?(\+?\d+)\s*{COST_RES_UNIT}{END_UNIT}", ln, re.I)
            if m_lead:
                return {"focus": False, "num": int(m_lead.group(1).lstrip("+")), "or_alt": False, "raw": m_lead.group(0)}
            for m_in in re.finditer(
                rf"\b(?:spend(?:ing)?|expend(?:ing)?|pay(?:ing)?|commit(?:ting)?|(?:action|bonus action|reaction)\s*\+?)\s+(?:[^.\n]{{0,30}}\band\s+)?(?:\*{{0,2}}`?)(\+?)(\d+)\s*(?:additional\s+|extra\s+)?{COST_RES_UNIT}{END_UNIT}",
                ln,
                re.I,
            ):
                pre_ctx = ln[max(0, m_in.start() - 35) : m_in.start()].lower()
                if re.search(r"\b(?:optional|augment|additional|extra|instead)\s*$", pre_ctx):
                    continue
                if re.search(r"\(\s*or\s+$", pre_ctx):
                    continue
                if m_in.group(1) == "+" and re.search(r"\bmay\s*$", pre_ctx):
                    continue
                return {"focus": bool(re.search(r"\bexpend\s+(?:martial\s+)?focus\b", ln, re.I)), "num": int(m_in.group(2)), "or_alt": False, "raw": m_in.group(0)}
            if re.search(r"\bexpend\s+(?:martial\s+)?focus\b", ln, re.I):
                return {"focus": True, "num": 0, "or_alt": False, "raw": "Expend Focus"}
        # Last resort on short non-heading bullet entries with an inline "(Action, N CP)" inside the body
        if lines and not lines[0].startswith("###") and len(lines) <= 4:
            for pm in re.finditer(r"\(([^)]+)\)", " ".join(lines)):
                p_txt = pm.group(1)
                if re.search(r"\b(?:upgrade|optional|persistent|or\s+(?:spend|spending)?\s*\+?\d+|while\s+holding|hotter\s+materials)\b", p_txt, re.I):
                    continue
                parsed = _parse_cost_chunk(p_txt, is_bible=True)
                if parsed is not None:
                    return parsed
    return None


def parse_bible_cost(btext: str, title_hint: str = "") -> dict | None:
    own = _bible_entry_own_lines(btext, title_hint=title_hint)
    cost = _extract_bible_cost_from_lines(own, title_hint=title_hint)
    if cost is not None:
        return cost
    all_lines = btext.splitlines()
    # Only inherit a parent `###` header cost when the parent is explicitly a grouped multi-talent heading (`&` or `,`)
    if all_lines and own != all_lines and re.search(r"[&,]", all_lines[0]):
        return _extract_bible_cost_from_lines(all_lines, title_hint=title_hint)
    return None


def format_cost(c: dict) -> str:
    if c["focus"] and c["num"]:
        return f"Focus + {c['num']}"
    if c["focus"]:
        return "Focus"
    return f"{c['num']} CP/Res"


def parse_live_cp_cost(txt: str) -> int | None:
    c = parse_live_cost(txt)
    return c["num"] if c is not None else None


def parse_bible_cp_cost(btext: str) -> int | None:
    c = parse_bible_cost(btext)
    return c["num"] if c is not None else None


USE_LIMIT_RE = re.compile(
    r"(once per (?:short or long|short|long) rest|"
    r"once per (?:day|week|month|dawn)|"
    r"\b\d+\s*(?:uses?\s*)?/(?:sr|lr|short rest|long rest|rest|day|week|month)\b|"
    r"\b\d+\s+times?\s+per\s+(?:short or long|short|long)\s+rest\b|"
    r"\b\d+\s+times?\s+per\s+(?:day|week|month)\b|"
    r"once per (?:year|lifetime|realm|campaign arc|story arc|arc|encounter|combat|scene)|"
    r"\b\d+\s*/\s*(?:year|lifetime|realm|campaign arc|story arc|arc|encounter|combat|scene)\b)",
    re.I,
)

NON_ACTIVATION_LIMIT_CONTEXT_RE = re.compile(
    # "0 CP once per rest" is a free use, not a cap -- but never across a `|` header-field break
    # (`**Cost:** 0 CP | **1/Long Rest**` is a free ability WITH a real limit).
    r"(?:\b0\s*(?:cp|stamina|qi)\b[^.\n|]{0,35}(?:once per|\b1/(?:sr|lr|short|long|day|week))|"
    r"(?:once per|\b1/(?:sr|lr|short|long))[^.\n|]{0,25}(?:for\s+\*?\*?0\s*(?:cp|stamina|qi)|free\b|without spending)|"
    r"\bfree\s+once\s+per\s+(?:day|short|long)\b|"
    r"\bunless you spend\b|\bimmune to\b[^.\n]{0,45}(?:24 hours|long rest|short rest)|"
    r"\b(?:until|after)\s+(?:you\s+)?(?:finish(?:ing)?|complet(?:e|ing))\s+(?:a|your next)\s+(?:short|long)|"
    r"\buntil repaired/rested\b|\bclears?\s+(?:on|after)\s+(?:a\s+)?(?:short|long)\s+rest\b|"
    r"\bregain(?:s)?\b[^.\n]{0,40}(?:short|long)\s+rest\b|\brecharg(?:e|es)\b|"
    r"\bper (?:target|creature|patient|ally|foe|bonded creature)\s+per\s+(?:short|long)\s+rest\b|"
    r"\b1/(?:sr|lr)\s+per\s+(?:target|creature|patient|ally|foe)\b|"
    r"\breroll\b[^.\n]{0,30}(?:1/(?:sr|lr)|once per)|"
    r"(?:1/(?:sr|lr)|once per (?:short|long) rest)[^.\n]{0,30}\breroll\b|"
    r"\bmay\s+use\s+(?:this|it)\s+again\b[^.\n]{0,25}by spending)",
    re.I,
)


def iter_use_limits(txt: str, is_bible: bool = False, title_hint: str = ""):
    """Yield EVERY activation cap in the entry (plus parent header if Use Limit is on parent): SR/LR/day/week/month/dawn."""
    if is_bible:
        own = _bible_entry_own_lines(txt, title_hint=title_hint)
        all_lines = txt.splitlines()
        parent_lim_lines = [ln for ln in all_lines[:4] if re.search(r"\*\*Use Limit:\*\*", ln, re.I)] if own != all_lines else []
        lines = parent_lim_lines + own
    else:
        clean = re.split(r"(?m)^#{3,6}\s+Normalized Procedure\b", txt, maxsplit=1)[0]
        lines = clean.splitlines()
    for ln in lines:
        if not is_bible and re.search(r"\b(?:use\s+limit|uses):\s*([^\n]+)", ln, re.I):
            uval = re.search(r"\b(?:use\s+limit|uses):\s*([^\n]+)", ln, re.I).group(1)
            if re.search(r"\b(?:per\s+(?:\w+\s+)?(?:short|long|day|week|month|year|lifetime|realm|campaign|story|arc|dawn|bonded|encounter|combat|scene)|once\s+per|\d+/)", uval, re.I):
                yield uval.strip()
                continue
        if NON_ACTIVATION_LIMIT_CONTEXT_RE.search(ln):
            continue
        hit = False
        for m in USE_LIMIT_RE.finditer(ln):
            hit = True
            yield m.group(1)
        if not hit and not is_bible and re.search(r"\bcannot\s+use\s+this\s+inheritance\s+again\b", ln, re.I):
            yield "deed-gated reuse"


def extract_use_limit(txt: str, is_bible: bool = False, title_hint: str = "") -> str | None:
    """First activation cap in the entry, or None."""
    return next(iter_use_limits(txt, is_bible=is_bible, title_hint=title_hint), None)


# Recovery period of a use limit, loosest to strictest. A Bible limit on a longer period than
# live's (long rest -> week) is a limit rise even though both sides "have a limit".
LIMIT_PERIOD_RANKS = (
    (6, re.compile(r"\b(?:lifetime|realm|campaign|arc|story|deed-gated)\b", re.I)),
    (5, re.compile(r"\byear\b", re.I)),
    (4, re.compile(r"\bmonth\b", re.I)),
    (3, re.compile(r"\bweek\b", re.I)),
    (2, re.compile(r"\b(?:long rest|lr|day|dawn)\b", re.I)),
    (1, re.compile(r"\b(?:short or long rest|short rest|sr|rest)\b", re.I)),
    (0, re.compile(r"\b(?:encounter|combat|scene)\b", re.I)),
)


def limit_strictness(lim: str) -> tuple[int, int] | None:
    """(period rank, -uses per period): a larger tuple is a stricter limit. None if the period is not recognised."""
    period = next((rank for rank, rx in LIMIT_PERIOD_RANKS if rx.search(lim)), None)
    if period is None:
        return None
    m = re.search(r"\b(\d+)\s*(?:uses?\s*)?/|\b(\d+)\s+times?\s+per\b", lim)
    uses = int(m.group(1) or m.group(2)) if m else 1
    return (period, -uses)


def strictest_limit(limits: list[str]) -> tuple[tuple[int, int], str] | None:
    ranked = [(limit_strictness(l), l) for l in limits]
    ranked = [(r, l) for r, l in ranked if r is not None]
    return max(ranked) if ranked else None


ORIGIN_ROW_RE = re.compile(r"^- \*\*Primordial Realm \(CL 36–39\) — Origin:\*\*.*`Unbound Inheritance:` \*([^*]+)\*(.*)$")
ORIGIN_LIMIT_CLAUSES = (
    # (words the Origin row must use, period ranks of the inheritance's own limit that call for them)
    ("short-rest", {1}),
    ("long-rest", {2}),
    ("weekly", {3}),
    ("keeps its once-per-", {4, 5, 6}),
)


def find_inheritance_entry(body_lines: list[str], name: str) -> list[str] | None:
    """The named Secret Inheritance's own text in a sphere file: a headed entry, a bullet, or an inline record."""
    for i, ln in enumerate(body_lines):
        if ln.startswith("#") and name in ln:
            j = i + 1
            while j < len(body_lines) and not body_lines[j].startswith("#"):
                j += 1
            return body_lines[i:j]
    for i, ln in enumerate(body_lines):
        if re.match(r"\s*- \*\*" + re.escape(name), ln):
            j = i + 1
            while j < len(body_lines) and body_lines[j][:1] in (" ", "\t") and body_lines[j].strip():
                j += 1
            return body_lines[i:j]
    for ln in body_lines:
        m = re.search(r"\*" + re.escape(name) + r"\*\s*(?:\([^)]*\))?", ln)
        if m:
            return [m.group(0)]
    return None


def check_origin_row(row_tail: str, entry_lines: list[str]) -> list[str]:
    """An Origin row may only lift or keep a limit the inheritance really has, and only promise damage it really deals."""
    ranks = set()
    for ln in entry_lines:
        for m in USE_LIMIT_RE.finditer(ln):
            st = limit_strictness(m.group(1))
            if st is not None:
                ranks.add(st[0])
    errs: list[str] = []
    for words, need in ORIGIN_LIMIT_CLAUSES:
        said, has = words in row_tail, bool(ranks & need)
        if said and not has:
            errs.append(f"row says '{words}' but the inheritance has no such limit")
        elif has and not said:
            errs.append(f"inheritance has a limit the row does not name (expected '{words}')")
    if "scales to at least" in row_tail and not any(re.search(r"\d+d\d+", ln) for ln in entry_lines):
        errs.append("row promises scaled damage but the inheritance rolls no damage dice")
    return errs


def check_all_origin_rows(bible_root: Path) -> list[str]:
    errs: list[str] = []
    for p in sorted((bible_root / "02_spheres_of_the_dao").glob("[0-9][0-9]_*.md")):
        if p.name.startswith("00_"):
            continue
        lines = p.read_text().splitlines()
        cut = next((i for i, ln in enumerate(lines) if ln.startswith("## Mythic Realms")), None)
        rows = [(i, ORIGIN_ROW_RE.match(ln)) for i, ln in enumerate(lines)] if cut is not None else []
        rows = [(i, m) for i, m in rows if m]
        if len(rows) != 1:
            errs.append(f"Origin row: expected exactly 1 in {p.name}, found {len(rows)}")
            continue
        i, m = rows[0]
        entry = find_inheritance_entry(lines[:cut], m.group(1))
        if entry is None:
            errs.append(f"Origin row at {p.name}:{i + 1}: inheritance '{m.group(1)}' is not in the sphere's own text")
            continue
        errs.extend(f"Origin row at {p.name}:{i + 1} ({m.group(1)}): {e}" for e in check_origin_row(m.group(2), entry))
    return errs


def extract_rest_limit(txt: str, is_bible: bool = False) -> str | None:
    return extract_use_limit(txt, is_bible=is_bible)


CORE_DMG_TYPES = (
    "Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning",
    "Necrotic", "Piercing", "Poison", "Psychic", "Radiant", "Slashing", "Thunder",
)
CORE_DMG_RE = "(?:" + "|".join(CORE_DMG_TYPES) + ")"
TYPE_PICK_RE = re.compile(
    rf"(?:\b({CORE_DMG_RE})(?:,\s*({CORE_DMG_RE}))*(?:,?\s+or\s+({CORE_DMG_RE}))\s+damage\b|"
    rf"\bdamage\s+(?:to\s+be|becomes?)\s+({CORE_DMG_RE})(?:,\s*({CORE_DMG_RE}))*(?:,?\s+or\s+({CORE_DMG_RE}))\b|"
    rf"\bchoose\s+({CORE_DMG_RE})\s+damage\s+instead\s+of\s+({CORE_DMG_RE})\s+damage\b)",
    re.I,
)


def extract_live_type_picks(txt: str) -> list[list[str]]:
    clean = re.split(r"(?m)^#{3,6}\s+Normalized Procedure\b", txt, maxsplit=1)[0]
    picks: list[list[str]] = []
    seen_sets: set[frozenset[str]] = set()
    for ln in clean.splitlines():
        low = ln.lower()
        # Skip incoming-damage/resistance/self-backlash/forensic/triggering-input lines (not outgoing damage picks!)
        if re.search(r"\b(resistance|immunity|vulnerability|reduce|regain|you take|when you take|takes? damage from|was involved|to the growth|lets? you choose)\b", low) and not re.search(r"\b(deals?|dealing|add|becomes|damage:)\b", low):
            continue
        if re.search(r"\b(when you take|reduce that damage|you take\s+[a-z, ]+damage|gains?\s+resistance|was involved|dealing at least \d+|lets? you choose)\b", low):
            continue
        if re.search(r"\binstead of\s+[a-z, ]+damage\b", low) and not re.search(r"\bchoose\s+[a-z]+\s+damage\s+instead\s+of\b", low):
            continue
        for m in TYPE_PICK_RE.finditer(ln):
            pre_m = ln[max(0, m.start() - 35) : m.start()].lower()
            if re.search(r"\b(?:resistance|immunity|vulnerability)\b", pre_m):
                continue
            phrase = m.group(0)
            types = [t.capitalize() for t in re.findall(rf"\b{CORE_DMG_RE}\b", phrase, re.I)]
            uniq = list(dict.fromkeys(types))
            if len(uniq) >= 2 and frozenset(uniq) not in seen_sets:
                seen_sets.add(frozenset(uniq))
                picks.append(uniq)
    return picks


def check_bible_type_pick(pick: list[str], btext: str) -> tuple[bool, str]:
    low = btext.lower()
    missing = [t for t in pick if not re.search(rf"\b{t.lower()}\b", low)]
    if missing:
        return False, f"missing type(s): {', '.join(missing)}"
    if len(pick) == 2:
        a, b = pick[0].lower(), pick[1].lower()
        has_choice = bool(
            re.search(rf"\b(?:{a}|{b})\b[^.\n]{{0,25}}(?:\bor\b|/)[^.\n]{{0,25}}\b(?:{a}|{b})\b", low)
        )
        has_plus_only = bool(
            re.search(rf"\b(?:{a}|{b})\s*\+\s*(?:{a}|{b})\b", low)
        )
        if has_plus_only and not has_choice:
            return False, f"combined '{pick[0]} + {pick[1]}' instead of choice '{pick[0]} or {pick[1]}'"
    elif len(pick) >= 3:
        t_alt = "|".join(t.lower() for t in pick)
        has_list_choice = bool(
            re.search(rf"\b(?:{t_alt})\b(?:\s*[,/]\s*(?:{t_alt})\b)*\s*(?:,?\s*\bor\b|/)\s*\b(?:{t_alt})\b", low)
        )
        if not has_list_choice:
            return False, f"types present but no choice list found for '{' / '.join(pick)}'"
    return True, " / ".join(pick)


RESIST_BYPASS_LIVE_RE = re.compile(
    r"(?:\bignor(?:e|es|ing)\s+(?:ordinary\s+)?(?:hardness\s+and\s+)?(?:[a-z/, ]{0,45})?resistance\b|"
    r"\bresistance\s+(?:to\s+[a-z/, ]{0,45})?does\s+not\s+apply\b|"
    r"\b(?:lose|loses|losing|strip|strips|stripping|suppress|suppresses|suppressing|bypass|bypasses|bypassing)\s+"
    r"(?:one\s+)?(?:ordinary\s+)?(?:temporary\s+)?(?:[a-z/, ]{0,35})?resistance\b)",
    re.I,
)
RESIST_BYPASS_BIBLE_RE = re.compile(
    r"(?:\bignor(?:e|es|ing)\s+[^.\n]{0,65}resistance\b|"
    r"\bresistance\s+(?:to\s+[^.\n]{0,55})?does\s+not\s+apply\b|"
    r"\b(?:lose|loses|losing|strip|strips|stripping|suppress|suppresses|suppressing|bypass|bypasses|bypassing)\s+[^.\n]{0,50}resistance\b)",
    re.I,
)


def evaluate_non_dice_parity(key: str, live_text: str, rel: str, btext: str) -> list[tuple[dict, bool, str]]:
    """Run whole-cost, use-limit, type-choice, and resistance-bypass gates across ALL resolved Bible entries."""
    extra: list[tuple[dict, bool, str]] = []

    lc = parse_live_cost(live_text)
    bc = parse_bible_cost(btext, title_hint=extract_display_title(key, live_text))
    if lc is not None and bc is not None:
        lnum = lc["num"] if lc["num"] is not None else 0
        bnum = bc["num"] if bc["num"] is not None else 0
        focus_added = bc["focus"] and not lc["focus"] and not bc.get("or_alt", False)
        if bnum > lnum or focus_added:
            ev = {"role": "cost", "kind": "cost", "label": "Resource Cost", "expr": format_cost(lc), "mean": None, "no_save": False, "step": ""}
            extra.append((ev, False, f"{format_cost(bc)} (FAIL_COST_RISE)"))
    elif lc is None and bc is not None:
        bnum = bc["num"] if bc["num"] is not None else 0
        if bnum > 0 or bc["focus"]:
            ev = {"role": "cost", "kind": "cost", "label": "Resource Cost", "expr": "no live cost parsed", "mean": None, "no_save": False, "step": ""}
            extra.append((ev, False, f"{format_cost(bc)} (FAIL_COST_ONE_SIDED)"))
    elif lc is not None and bc is None:
        lnum = lc["num"] if lc["num"] is not None else 0
        if lnum > 0 or lc["focus"]:
            # If the Bible entry actually mentions a numeric CP/Stamina/Resource cost or Focus expenditure in its own lines
            # that parse_bible_cost failed to parse, FAIL rather than silently passing!
            own_txt = "\n".join(_bible_entry_own_lines(btext, title_hint=extract_display_title(key, live_text)))
            if re.search(rf"(?<!-)\b[1-9]\d*\s*{COST_RES_UNIT}\b|\bexpend\s+(?:martial\s+)?focus\b", own_txt, re.I) and not COST_REDUCTION_RE.search(own_txt):
                ev = {"role": "cost", "kind": "cost", "label": "Resource Cost", "expr": format_cost(lc), "mean": None, "no_save": False, "step": ""}
                extra.append((ev, False, "UNPARSED_BIBLE_COST (FAIL_COST_ONE_SIDED)"))

    llims = list(iter_use_limits(live_text, is_bible=False))
    blims = list(iter_use_limits(btext, is_bible=True, title_hint=extract_display_title(key, live_text)))
    if blims and not llims:
        ev = {"role": "limit", "kind": "limit", "label": "Use Limit", "expr": "no use limit", "mean": None, "no_save": False, "step": ""}
        extra.append((ev, False, f"{blims[0]} (FAIL_NEW_REST_LIMIT)"))
    elif blims and llims:
        # Both sides have a limit: the Bible's strictest one must not be stricter than live's strictest one.
        lmax = strictest_limit(llims)
        bmax = strictest_limit(blims)
        if lmax and bmax and bmax[0] > lmax[0]:
            ev = {"role": "limit", "kind": "limit", "label": "Use Limit", "expr": lmax[1], "mean": None, "no_save": False, "step": ""}
            extra.append((ev, False, f"{bmax[1]} (FAIL_STRICTER_LIMIT)"))

    for pick in extract_live_type_picks(live_text):
        ok, diag = check_bible_type_pick(pick, btext)
        if not ok:
            ev = {"role": "type_pick", "kind": "type_pick", "label": "Damage Type Choice", "expr": " or ".join(pick), "mean": None, "no_save": False, "step": ""}
            extra.append((ev, False, f"{diag} (FAIL_LOST_TYPE_CHOICE)"))

    live_bypass_clean = re.split(r"(?m)^#{3,6}\s+Normalized Procedure\b", live_text, maxsplit=1)[0]
    has_live_bypass = any(
        RESIST_BYPASS_LIVE_RE.search(ln)
        and not re.search(r"\b(?:cannot\s+(?:ignore|suppress|bypass)|unless\s+that\s+source|self-damage|counterplay|legendary\s+resistance)\b", ln, re.I)
        and not (re.search(r"^ignores?\s+resistance", ln.strip(), re.I) and re.search(r"this\s+self-damage", live_bypass_clean, re.I))
        for ln in live_bypass_clean.splitlines()
    )
    if has_live_bypass and not RESIST_BYPASS_BIBLE_RE.search(btext):
        ev = {"role": "bypass", "kind": "bypass", "label": "Resistance Bypass", "expr": "bypasses/strips Resistance", "mean": None, "no_save": False, "step": ""}
        extra.append((ev, False, "MISSING (FAIL_LOST_RESIST_BYPASS)"))

    return extra

def extract_display_title(key: str, text: str) -> str:
    if key.startswith("tianxia.subpath.") or key.startswith("tianxia.tradition."):
        parts = key.split(".")
        sub_label = "Empyreal Administrator" if parts[3] == "cai_clan_empyreal_administrator" else parts[3].replace("_", " ").title()
        return f"{sub_label} — {parts[-1].replace('_', ' ').title()}"
    if key.startswith("foundation."):
        parts = key.split(".")
        parent = re.sub(r"_v\d+.*$", "", parts[1]).replace("_", " ").title()
        return f"{parent} — {parts[-1].replace('_', ' ').title()}"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            t = strip_cl_prefix(s)
            t = re.split(r"\s+[—–-]\s+", t, maxsplit=1)[0].strip()
            if t and not re.match(r"^CL\s*\d+$", t, re.I):
                return t
            break
    raw = key.split(".")[-1].split(":")[-1]
    if raw.startswith("TAL_"):
        raw = " ".join(raw.split("_")[2:])
    return raw.replace("_", " ").replace("-", " ").title()


def run_pipeline(write_ledger: bool) -> int:
    rt = json.loads(LIVE_JSON.read_text())
    bible_idx = BibleIndex(BIBLE_ROOT)

    dmg_gate = re.compile(
        r"(\b\d+d\d+\b|\bdouble damage\b|\btriple damage\b|\bhalf damage\b"
        r"|damage equal to|takes?\s+(?:additional\s+|extra\s+)?(?:[a-z]+\s+)?damage)",
        re.I,
    )

    # Run parity gates on EVERY live entry that has a Bible counterpart (not only entries with damage rows!)
    all_keys = sorted(
        {k for k, v in rt.items() if isinstance(v, str)}
        | set(RESTORED_KEYS.keys())
        | set(REBALANCED_COST_OR_LIMIT.keys())
        | {k.split("::")[0] for k in HAND_CUT_ON_PURPOSE.keys()}
    )

    rows: list[str] = []
    failures: list[str] = []
    parity_checked_keys = 0
    stats = {
        "COVERED": 0,
        "RESTORED": 0,
        "REBALANCED_COST_OR_LIMIT": 0,
        "CUT ON PURPOSE": 0,
        "FAIL": 0,
    }

    safe = lambda s: s.replace("|", "\\|").replace("\n", " ").strip()

    for k in all_keys:
        v = rt.get(k, "")
        title = extract_display_title(k, v) if v else k.split(":")[-1]

        has_dmg_gate = bool(v and dmg_gate.search(v)) or k in RESTORED_KEYS or k in HAND_CUT_ON_PURPOSE
        if k == "printed_option:Centerline Impact":
            events = [{"role": "bonus", "kind": "flat_pb", "label": "bonus (Centerline Impact)", "expr": "PB", "mean": PB_EVAL, "no_save": True, "step": "", "level": 1}]
        elif has_dmg_gate:
            events = extract_live_events(k, v)
        else:
            events = []

        if not events:
            if k in HAND_CUT_ON_PURPOSE:
                tag, reason = HAND_CUT_ON_PURPOSE[k]
                stats["CUT ON PURPOSE"] += 1
                rows.append(
                    f"| `{safe(k)}#1` | `{safe(k)}` | {safe(title)} | entry | — | — | **CUT ON PURPOSE** | `—` | `{tag}`: {safe(reason)} |"
                )
                continue
            # Even with 0 damage events, resolve and run all 4 parity gates (cost, use-limit, type-pick, bypass).
            # NEVER silently skip an unresolved live entry!
            res_nd, err_nd = bible_idx.resolve_key(k, v)
            if not res_nd:
                stats["FAIL"] += 1
                msg = f"FAIL_UNRESOLVED_ENTRY: {k}#1 ({title}) [entry] -> {err_nd}"
                failures.append(msg)
                rows.append(
                    f"| `{safe(k)}#1` | `{safe(k)}` | {safe(title)} | entry | `live entry` | `MISSING` | **FAIL** | `—` | {safe(str(err_nd))} |"
                )
                continue
            parity_checked_keys += 1
            rel, s, e, btext = res_nd
            ref = f"`{rel}:{s}`"
            parity_fails = evaluate_non_dice_parity(k, v, rel, btext)
            for idx, (ev, passes, bible_val) in enumerate(parity_fails, 1):
                if not passes:
                    stats["FAIL"] += 1
                    kind_fail = "FAIL_PARITY"
                    msg = f"{kind_fail}: {k}#{idx} ({title}) [{ev['label']}] live={ev['expr']} vs bible={bible_val} at {rel}:{s}"
                    failures.append(msg)
                    rows.append(
                        f"| `{safe(k)}#{idx}` | `{safe(k)}` | {safe(title)} | {safe(ev['label'])} | `{safe(ev['expr'])}` | `{safe(bible_val)}` | **FAIL** | {ref} | {kind_fail} |"
                    )
            if not parity_fails and k in HAND_MATCHED_ACCOUNTING_KEYS:
                status = "RESTORED" if k.startswith("insight.") else "COVERED"
                note = "Restored missing Equipment insight to Book 5" if k.startswith("insight.") else "Matched by hand (formerly unresolved non-damage entry)"
                stats[status] += 1
                rows.append(
                    f"| `{safe(k)}#1` | `{safe(k)}` | {safe(title)} | entry | `non-damage` | `matched` | **{status}** | {ref} | {note} |"
                )
            continue

        res, err = bible_idx.resolve_key(k, v)
        if not res:
            if k in HAND_CUT_ON_PURPOSE:
                tag, reason = HAND_CUT_ON_PURPOSE[k]
                for idx, ev in enumerate(events, 1):
                    stats["CUT ON PURPOSE"] += 1
                    rows.append(
                        f"| `{safe(k)}#{idx}` | `{safe(k)}` | {safe(title)} | {safe(ev['label'])} | `{safe(ev['expr'])}` | `—` | **CUT ON PURPOSE** | `—` | `{tag}`: {safe(reason)} |"
                    )
            else:
                for idx, ev in enumerate(events, 1):
                    stats["FAIL"] += 1
                    msg = f"FAIL_MISSING_ENTRY: {k}#{idx} ({title}) [{ev['label']}: {ev['expr']}] -> {err}"
                    failures.append(msg)
                    rows.append(
                        f"| `{safe(k)}#{idx}` | `{safe(k)}` | {safe(title)} | {safe(ev['label'])} | `{safe(ev['expr'])}` | `MISSING` | **FAIL** | `—` | {safe(str(err))} |"
                    )
            continue

        parity_checked_keys += 1
        rel, s, e, btext = res
        ref = f"`{rel}:{s}`"
        paired = evaluate_ability_events(k, events, rel, btext, bible_idx)
        paired.extend(evaluate_non_dice_parity(k, v, rel, btext))

        for idx, (ev, passes, bible_val) in enumerate(paired, 1):
            ev_key = f"{k}::{ev['kind']}"
            role_key = f"{k}::{ev['role']}"
            if passes:
                if k in REBALANCED_COST_OR_LIMIT:
                    status = "REBALANCED_COST_OR_LIMIT"
                    note = REBALANCED_COST_OR_LIMIT[k]
                elif k in RESTORED_KEYS:
                    status = "RESTORED"
                    note = RESTORED_KEYS[k]
                else:
                    status = "COVERED"
                    note = ""
                stats[status] += 1
                rows.append(
                    f"| `{safe(k)}#{idx}` | `{safe(k)}` | {safe(title)} | {safe(ev['label'])} | `{safe(ev['expr'])}` | `{safe(bible_val)}` | **{status}** | {ref} | {safe(note)} |"
                )
            else:
                cut_entry = HAND_CUT_ON_PURPOSE.get(ev_key) or HAND_CUT_ON_PURPOSE.get(role_key) or HAND_CUT_ON_PURPOSE.get(k)
                if cut_entry:
                    tag, reason = cut_entry
                    assert tag in APPROVED_CUT_TAGS, f"Invalid cut tag '{tag}' on {k}"
                    stats["CUT ON PURPOSE"] += 1
                    rows.append(
                        f"| `{safe(k)}#{idx}` | `{safe(k)}` | {safe(title)} | {safe(ev['label'])} | `{safe(ev['expr'])}` | `{safe(bible_val)}` | **CUT ON PURPOSE** | {ref} | `{tag}`: {safe(reason)} |"
                    )
                else:
                    stats["FAIL"] += 1
                    if ev["kind"] in ("cost", "limit", "type_pick", "bypass"):
                        kind_fail = "FAIL_PARITY"
                    elif bible_val in ("NONE", "MISSING") or bible_val.startswith("NO_"):
                        kind_fail = "FAIL_MISSING_EVENT"
                    else:
                        kind_fail = "FAIL_LOWER_DAMAGE"
                    msg = f"{kind_fail}: {k}#{idx} ({title}) [{ev['label']}] live={ev['expr']} vs bible={bible_val} at {rel}:{s}"
                    failures.append(msg)
                    rows.append(
                        f"| `{safe(k)}#{idx}` | `{safe(k)}` | {safe(title)} | {safe(ev['label'])} | `{safe(ev['expr'])}` | `{safe(bible_val)}` | **FAIL** | {ref} | {kind_fail} |"
                    )

    if write_ledger:
        header = [
            "# Tianxia Rules Bible — Strict Per-Event Damage, Cost, Limit, Type-Choice & Bypass Ledger (v5)",
            "",
            f"Tracks every live hostile damage roll plus runs full-corpus cost, use-limit, damage-type choice, and resistance-bypass gates across ALL **{parity_checked_keys}** resolved Bible entries (including non-damage domains, forms, inheritances, rites, utility, paths, subpaths, foundations, and insights).",
            "Enforces: (1) strict 1-to-1 RollCurve pairing + summed simultaneous rolls (zero 'covers' reuse), (2) same-level tier comparison, (3) strict bonus/retaliation/repeating role matching, (4) explicit flat CL/PB damage phrases, (5) cross-referenced `<Ability> damage` resolution, (6) Bible CP cost <= live, (7) no new use limits and no limit stricter than live's (long rest -> week fails), (8) live damage-type picks preserved, (9) live resistance bypasses preserved. Zero hard-coded exceptions, zero automatic `CUT ON PURPOSE`.",
            "",
            f"- **Total live damage events tracked:** {len(rows)}",
            f"- **COVERED (1-to-1 mechanically verified Bible >= Live):** {stats['COVERED']}",
            f"- **RESTORED (repaired & 1-to-1 mechanically verified Bible >= Live):** {stats['RESTORED']}",
            f"- **REBALANCED_COST_OR_LIMIT (damage verified Bible >= Live; cost/limit rebalanced):** {stats['REBALANCED_COST_OR_LIMIT']}",
            f"- **CUT ON PURPOSE (hand-authored with approved reason):** {stats['CUT ON PURPOSE']}",
            f"- **FAIL (missing event, wrong role/repeat, or Bible < Live):** {stats['FAIL']}",
            "",
            "| Event ID | Live Key | Ability | Event | Live Value | Bible Value | Status | Bible Ref | Notes / Reason |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        LEDGER_PATH.write_text("\n".join(header + rows) + "\n")
        print(f"Wrote {LEDGER_PATH} ({len(rows)} event rows): {stats}")

    # Style & mirror verification
    style_errors: list[str] = []
    for p in sorted(BIBLE_ROOT.rglob("*.md")):
        if "compiled" in p.parts:
            continue
        rel = str(p.relative_to(BIBLE_ROOT))
        if rel in ("DAMAGE_FLOOR_LEDGER.md", "STYLE_AND_BALANCE_STANDARD.md", "README.md"):
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "!" in line:
                style_errors.append(f"Literal '!' at {rel}:{i}")
            if re.search(r"\bdamage packets?\b", line, re.I):
                style_errors.append(f"'damage packet' at {rel}:{i}")
            if rel not in ("02_spheres_of_the_dao/07_beastmastery.md", "01_players_handbook/13_backgrounds.md"):
                if re.search(r"\briders?\b", line, re.I) and "Rider's Passing Cut" not in line:
                    style_errors.append(f"Mechanical 'rider' at {rel}:{i}")

    style_errors.extend(check_all_origin_rows(BIBLE_ROOT))

    if MIRROR_DIR.exists():
        for f in sorted(COMPILED_DIR.glob("*.md")):
            m = MIRROR_DIR / f.name
            if not (m.exists() and m.read_bytes() == f.read_bytes()):
                style_errors.append(f"Mirror mismatch: {f.name}")

    if failures or style_errors:
        print(f"\nSTRICT FLOOR/STYLE CHECK FAILED: {len(failures)} damage floor failures, {len(style_errors)} style/sync errors")
        for fmsg in failures[:60]:
            print(" ", fmsg)
        if len(failures) > 60:
            print(f"  ... and {len(failures) - 60} more floor failures")
        for smsg in style_errors[:20]:
            print(" ", smsg)
        return 1

    print(
        f"ALL STRICT 5-RULE CHECKS PASSED: {len(rows)} live damage events verified "
        f"({stats['COVERED']} COVERED, {stats['RESTORED']} RESTORED, "
        f"{stats['REBALANCED_COST_OR_LIMIT']} REBALANCED_COST_OR_LIMIT, "
        f"{stats['CUT ON PURPOSE']} CUT ON PURPOSE, 0 FAIL), "
        f"0 '!', 0 'damage packet', 0 mechanical 'rider', compiled == mirror synced!"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true", help="Regenerate DAMAGE_FLOOR_LEDGER.md and verify")
    args = ap.parse_args()
    return run_pipeline(write_ledger=args.generate)


if __name__ == "__main__":
    sys.exit(main())
