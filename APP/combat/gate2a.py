from __future__ import annotations

from pathlib import Path
from typing import Any

from .gate2_mechanics_lock import (
    AttackSpec,
    DamageSpec,
    DiceExpression,
    DurationSpec,
    Economy,
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


GATE1_SOURCE_SHA256 = "3cbd473f682763b18c9378ed45ad82555b745dc44714afc54eaade448834c053"
GATE2_DESIGN_SHA256 = "ce1a5cc2cebdf34b4c9b8207e878be6034db391881c5adb50bbdfbc6676a7fe7"
GATE2_PROMPT_SHA256 = "1a7bbe019944794d9963db9900d76a542940bfe18235b651a1a8139f0daeeb7f"
REGISTRY_SHA256 = "c3ed7fa15650d105fe375a2b6f3a1caf00a5ebc01ea8ffc1c23608dea6d403b1"

ALLOWED_PRIMITIVES = tuple(sorted({
    "primitive:add_modifier",
    "primitive:apply_condition",
    "primitive:attack_roll",
    "primitive:create_zone",
    "primitive:damage",
    "primitive:gain_resource",
    "primitive:grant_temp_hp",
    "primitive:movement",
    "primitive:remove_condition",
    "primitive:remove_modifier",
    "primitive:remove_zone",
    "primitive:resolve_reaction",
    "primitive:save_roll",
    "primitive:schedule_expiration",
    "primitive:spend_resource",
}))

GATE1_AUTHORITY = "Exact Gate 1 source checkpoint SHA-256 " + GATE1_SOURCE_SHA256
DESIGN_AUTHORITY = "Gate 2 Design R1 SHA-256 " + GATE2_DESIGN_SHA256


def _profile(
    source_definition_id: str,
    display_name: str,
    *,
    profile_kind: ProfileKind,
    economy: Economy,
    status: MechanicsLockStatus,
    source_locator: str,
    authority: str = GATE1_AUTHORITY,
    fidelity: str,
    unresolved: tuple[str, ...] = (),
    request: str | None = None,
    targeting: TargetingSpec | None = None,
    prerequisites: tuple[str, ...] = (),
    costs: tuple[ResourceCost, ...] = (),
    attack: AttackSpec | None = None,
    save: SaveSpec | None = None,
    post_hit_save: SaveSpec | None = None,
    damage: DamageSpec | None = None,
    duration: DurationSpec | None = None,
    concentration: bool | None = None,
    checkpoint: str | None = None,
    follow_up: str | None = None,
    primitives: tuple[str, ...] = (),
) -> ExecutableMechanicProfile:
    return ExecutableMechanicProfile(
        source_definition_id=source_definition_id,
        display_name=display_name,
        source_authority=authority,
        source_locator=source_locator,
        profile_kind=profile_kind,
        economy=economy,
        targeting=targeting,
        prerequisites=prerequisites,
        costs=costs,
        attack=attack,
        save=save,
        post_hit_save=post_hit_save,
        damage=damage,
        duration=duration,
        concentration=concentration,
        reaction_checkpoint=checkpoint,
        optional_follow_up=follow_up,
        primitive_ids=tuple(sorted(primitives)),
        fidelity_consequence=fidelity,
        status=status,
        unresolved_fields=unresolved,
        resolution_request=request,
    )


def build_gate2a_lock() -> ExecutableMechanicsLock:
    L = MechanicsLockStatus.LOCKED_EXECUTABLE
    T = MechanicsLockStatus.LOCKED_TRACKED_PASSIVE
    N = MechanicsLockStatus.LOCKED_NO_GATE2_USE
    U = MechanicsLockStatus.MATERIAL_UNRESOLVED
    profiles: list[ExecutableMechanicProfile] = []

    # Universal and battlefield rules.
    profiles += [
        _profile("system:combat.action_economy", "Turn economy and reaction refresh", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §§8,14", fidelity="Prevents illegal action sequencing and reaction reuse.", primitives=()),
        _profile("system:combat.attack_natural_results", "Attack natural 1 and critical hit", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §9", fidelity="Preserves deterministic attack and critical damage behavior.", primitives=("primitive:attack_roll", "primitive:damage")),
        _profile("system:combat.concentration", "Concentration replacement and damage checks", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §16", fidelity="Controls mutually exclusive zones and damage-driven interruption.", primitives=("primitive:save_roll", "primitive:remove_zone")),
        _profile("system:combat.cover_and_line_of_sight", "Square-grid cover and line of sight", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §10", fidelity="Makes positioning and ranged legality mechanically meaningful.", primitives=("primitive:add_modifier",)),
        _profile("system:combat.initiative", "Initiative formula and tie-breaking", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=U, authority=DESIGN_AUTHORITY, source_locator="01 design §§4.1,21", fidelity="Initiative order materially changes opening geometry and reaction availability.", unresolved=("initiative ability/modifier formula", "tie-breaking hierarchy"), request="Supply exact Tianxia initiative authority for these four projections, including ties."),
        _profile("system:combat.nonlethal_defeat", "Sect Training Court nonlethal defeat", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §17", fidelity="Defines 0 HP behavior without death saves.", primitives=("primitive:remove_zone",)),
        _profile("system:combat.opportunity_attack", "Opportunity attack and Disengage", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.REACTION, status=U, authority=DESIGN_AUTHORITY, source_locator="01 design §§4.1,14", fidelity="Controls route risk and melee containment.", unresolved=("eligible attack source/profile", "reach selection when multiple profiles qualify", "target visibility/perception requirement"), request="Supply exact opportunity-attack contract or approve one named basic melee profile per eligible actor."),
        _profile("system:combat.saving_throw_modifiers", "Saving throw modifiers and proficiencies", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=U, authority=GATE1_AUTHORITY, source_locator="four generated projections / statistics.ability_scores", fidelity="Save bonuses materially alter zones, riders, concentration, and defeat timing.", unresolved=("save proficiency by ability for each actor", "companion save modifiers"), request="Supply exact four-character source bundle save proficiency and Cui saving-throw data."),
        _profile("system:combat.simultaneous_terminal", "Simultaneous primary defeat", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §17", fidelity="Prevents order-dependent winner selection inside one atomic resolution."),
        _profile("system:combat.temporary_hit_points", "Temporary hit point replacement and absorption", profile_kind=ProfileKind.SYSTEM_RULE, economy=Economy.SYSTEM, status=U, authority=DESIGN_AUTHORITY, source_locator="01 design §§4.1,7,15", fidelity="Temporary HP materially changes defensive sequencing and Keep the Measure value.", unresolved=("replacement/stacking rule", "expiration behavior", "whether source loss removes granted temporary HP"), request="Supply exact Tianxia temporary-HP rule used by the four-character source bundle."),
        _profile("system:hazard.sect_training_court.qi_disruption", "Sect Training Court Qi hazard", profile_kind=ProfileKind.ZONE, economy=Economy.SYSTEM, status=L, authority=DESIGN_AUTHORITY, source_locator="01 design §10", fidelity="Preserves the accepted battlefield's only hazard and movement tradeoff.", targeting=TargetingSpec(target_kind="ENTITY_IN_HAZARD_CELLS", requires_line_of_sight=False, geometry="Gate1 battlefield terrain region"), save=SaveSpec(ability="DEX", dc=12), damage=DamageSpec(dice=DiceExpression(count=1, sides=4), damage_type="FORCE_QI_DISRUPTION"), primitives=("primitive:damage", "primitive:save_roll")),
    ]

    # Shared conditions.
    profiles += [
        _profile("condition:an_eui.ruin_tempered", "Ruin-Tempered weapon state", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=U, source_locator="character projection mechanics creates/requires_existing_state", fidelity="Gates First Arm and An Eui's resource/action sequence.", unresolved=("target weapon instance", "duration", "exact mechanical benefit", "concentration-end cleanup"), request="Supply exact Ruin-Tempered Armament and First Arm text from An Eui's source bundle."),
        _profile("condition:core.break_the_guard", "Break the Guard", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=U, source_locator="core rules pack and Scouring Destruction projection", fidelity="Determines the opening created for An Eui and Lee Jia.", unresolved=("exact modifier beyond next-attack advantage", "expiration when no attack occurs", "eligible attacker/attack"), request="Supply exact Break the Guard condition text and duration."),
        _profile("condition:core.dodging", "Dodging", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=U, source_locator="core rules pack", fidelity="Defines Cui's default defense and the universal Dodge action.", unresolved=("exact expiration", "Dexterity-save benefit, if any", "attacker visibility requirement"), request="Supply exact Tianxia Dodge condition contract."),
        _profile("condition:core.dose_marked", "Dose Mark", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=U, source_locator="core rules pack and Bai projections", fidelity="Venom accumulation is central to Bai/Cui identity and target pressure.", unresolved=("stack consequences", "maximum stacks", "expiration/removal", "interaction with Emerald Fang and Numbing Venom Palm"), request="Supply exact Dose Mark and Emerald Fang source mechanics."),
        _profile("condition:core.grappled", "Grappled", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=L, source_locator="core rules pack", fidelity="Speed becomes zero while a valid grapple source remains.", primitives=("primitive:apply_condition", "primitive:remove_condition")),
        _profile("condition:core.reaction_denied", "Reaction denied", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=T, source_locator="core rules pack", fidelity="Suppresses all reaction candidates while present.", primitives=("primitive:apply_condition", "primitive:remove_condition")),
        _profile("condition:core.soaked", "Soaked", profile_kind=ProfileKind.CONDITION, economy=Economy.PASSIVE, status=U, source_locator="core rules pack and Water Whip projection", fidelity="A named Water mechanic may alter follow-up venom, lightning, movement, or defense.", unresolved=("mechanical effect", "duration", "removal"), request="Supply exact Soaked condition text for Bai's CL5 source."),
    ]

    # An Eui.
    profiles += [
        _profile("action:an_eui.first_arm", "First Arm", profile_kind=ProfileKind.ON_HIT_OPTION, economy=Economy.ON_HIT_OPTION, status=U, source_locator="An Eui projection/actions", fidelity="A defining resource conversion and finisher; omitting it changes action sequence and Dao expression.", prerequisites=("condition:an_eui.ruin_tempered",), costs=(ResourceCost(resource_id="resource:an_eui.battle_hands", amount=1, timing="ON_SELECTION", optional=True),), unresolved=("damage or rider effect", "triggering hit eligibility", "condition consumption/retention", "effect timing"), request="Supply exact First Arm executable text."),
        _profile("action:an_eui.paired_bi_shou_assault", "Paired Bi Shou Assault", profile_kind=ProfileKind.MULTI_ATTACK, economy=Economy.ACTION, status=L, source_locator="An Eui projection/actions", fidelity="Defines An Eui's close-range baseline and Severance setup.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", reach_ft=5, requires_line_of_sight=True), attack=AttackSpec(bonus=7, attack_count=2), damage=DamageSpec(dice=DiceExpression(count=1, sides=4, modifier=4), damage_type="PIERCING"), primitives=("primitive:attack_roll", "primitive:damage")),
        _profile("action:an_eui.paired_strike", "Paired Strike", profile_kind=ProfileKind.ATTACK, economy=Economy.BONUS_ACTION, status=U, source_locator="An Eui projection/actions", fidelity="Controls An Eui's three-strike action economy and close-range output.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", reach_ft=5, requires_line_of_sight=True), attack=AttackSpec(bonus=7), damage=DamageSpec(dice=DiceExpression(count=1, sides=4, modifier=4), damage_type="PIERCING"), unresolved=("exact prerequisite: attack action, paired routine, or successful hit", "whether same target is required"), request="Supply exact Paired Strike prerequisite text."),
        _profile("action:an_eui.ruin_tempered_armament_quick", "Ruin-Tempered Armament — Quick", profile_kind=ProfileKind.STATE_OR_STANCE, economy=Economy.BONUS_ACTION, status=U, source_locator="An Eui projection/actions", fidelity="Establishes the state required for First Arm and consumes Battle Hands.", costs=(ResourceCost(resource_id="resource:an_eui.battle_hands", amount=1, timing="ON_SELECTION"),), concentration=True, unresolved=("target weapon", "duration", "base mechanical benefit", "replacement/ending semantics"), request="Supply exact quick Ruin-Tempered Armament text."),
        _profile("action:an_eui.scouring_destruction_blast", "Scouring Destructive Blast", profile_kind=ProfileKind.ATTACK_THEN_SAVE, economy=Economy.ACTION, status=U, source_locator="An Eui projection/actions", fidelity="Primary ranged guard-breaking line and major team opener.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True), attack=AttackSpec(bonus=6), post_hit_save=SaveSpec(ability="DEX", dc=14), damage=DamageSpec(dice=DiceExpression(count=2, sides=6), damage_type="SLASHING_DESTRUCTION"), unresolved=("reaction-denial duration", "Break the Guard exact modifier and expiration", "successful-save rider result"), request="Supply exact Scouring Destruction rider and condition durations."),
        _profile("passive:an_eui.severance_edge", "Severance Edge generation", profile_kind=ProfileKind.PASSIVE_TRIGGER, economy=Economy.PASSIVE, status=U, source_locator="An Eui projection/passives", fidelity="Controls access to Sheath-Bone Guard and finish pressure.", unresolved=("qualifying hit definition", "gain quantity", "which paired attack can trigger", "refresh/reset behavior"), request="Supply exact Severance Edge generation text."),
        _profile("reaction:an_eui.sheath_bone_guard", "Sheath-Bone Guard", profile_kind=ProfileKind.REACTION_PREVENTION, economy=Economy.REACTION, status=U, source_locator="An Eui projection/reactions", fidelity="Distinct from generic reduction; exact prevention scope materially changes survival.", costs=(ResourceCost(resource_id="resource:an_eui.severance_edge", amount=1, timing="ON_REACTION_SELECTION"),), checkpoint="DAMAGE_APPLICATION", unresolved=("qualifying damage packet", "full prevention versus typed prevention", "self-only versus protectable target"), request="Supply exact Sheath-Bone Guard trigger and prevented packet classes."),
        _profile("reaction:core.stamina_guard", "Stamina Guard", profile_kind=ProfileKind.REACTION_REDUCTION, economy=Economy.REACTION, status=L, source_locator="core rules and An Eui projection", fidelity="Core Body Refiner defense with exact pending-damage timing.", targeting=TargetingSpec(target_kind="SELF_PENDING_DAMAGE"), checkpoint="DAMAGE_APPLICATION", primitives=("primitive:damage", "primitive:resolve_reaction", "primitive:spend_resource")),
        _profile("talent:an_eui.scouring_destruction", "Scouring Destruction talent identity", profile_kind=ProfileKind.PASSIVE_TRIGGER, economy=Economy.PASSIVE, status=N, source_locator="An Eui projection/talents", fidelity="The projected executable effect is entirely represented by action:an_eui.scouring_destruction_blast; no independent mutation is authorized."),
        _profile("talent:an_eui.stomping_step", "Stomping Step", profile_kind=ProfileKind.MOVE, economy=Economy.BONUS_ACTION, status=L, source_locator="An Eui projection/talents and core Dash/Disengage", fidelity="Preserves An Eui's mobile bruiser route control.", targeting=TargetingSpec(target_kind="SELF", requires_line_of_sight=False), primitives=("primitive:movement",)),
    ]
    for rid, name, status, unresolved, request in [
        ("resource:an_eui.battle_hands", "Battle Hands", L, (), None),
        ("resource:an_eui.destruction_dice", "Destruction Dice", U, ("spend triggers", "effect per die", "recovery/refresh"), "Supply exact CL5 Destruction Dice mechanics or an explicit no-use disposition."),
        ("resource:an_eui.martial_focus", "Martial Focus", U, ("gain/hold/spend behavior", "linked techniques"), "Supply exact CL5 Martial Focus mechanics or an explicit no-use disposition."),
        ("resource:an_eui.severance_edge", "Severance Edge", U, ("gain trigger and quantity", "reset/expiration"), "Resolve passive:an_eui.severance_edge."),
        ("resource:an_eui.stamina", "Stamina", L, (), None),
    ]:
        profiles.append(_profile(rid, name, profile_kind=ProfileKind.RESOURCE, economy=Economy.PASSIVE, status=status, source_locator="An Eui projection/resources", fidelity=f"Tracks {name} without underflow and binds its exact starting/cap values.", unresolved=unresolved, request=request, primitives=() if status != L else ("primitive:spend_resource", "primitive:gain_resource")))

    # Lee Jia.
    profiles += [
        _profile("action:lee_jia.gather_charge", "Gather Charge", profile_kind=ProfileKind.STATE_OR_STANCE, economy=Economy.BONUS_ACTION, status=L, source_locator="Lee Jia projection/actions", fidelity="Creates the charge cycle that defines Lee Jia's sequencing.", primitives=("primitive:gain_resource",)),
        _profile("action:lee_jia.hidden_sleeve_shock_talisman", "Hidden-Sleeve Shock Talisman", profile_kind=ProfileKind.ATTACK, economy=Economy.ACTION, status=L, source_locator="Lee Jia projection/actions", fidelity="Finite high-damage ranged option with exact talisman cost.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True), costs=(ResourceCost(resource_id="resource:lee_jia.prepared_talismans", amount=1, timing="ON_SELECTION"),), attack=AttackSpec(bonus=6), damage=DamageSpec(dice=DiceExpression(count=3, sides=8), damage_type="LIGHTNING"), primitives=("primitive:attack_roll", "primitive:damage", "primitive:spend_resource")),
        _profile("action:lee_jia.lightning_lash", "Lightning Lash", profile_kind=ProfileKind.ATTACK, economy=Economy.ACTION, status=U, source_locator="Lee Jia projection/actions", fidelity="Primary attack and the entire Lightning Charge loop.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True), attack=AttackSpec(bonus=6), damage=DamageSpec(dice=DiceExpression(count=2, sides=8, modifier=6), damage_type="LIGHTNING"), unresolved=("where on-hit charge is stored", "charge gain versus discharge ordering", "maximum charges discharged", "whether discharge is optional", "charge expiration"), request="Supply exact Lightning Lash and Lightning Charge text."),
        _profile("passive:lee_jia.reed_flex", "Reed-Flex Survival Line", profile_kind=ProfileKind.PASSIVE_TRIGGER, economy=Economy.PASSIVE, status=U, source_locator="Lee Jia projection/passives", fidelity="Named survival and route-flex behavior may change risk and positioning.", unresolved=("mechanical trigger", "mechanical effect", "duration/limit"), request="Supply exact Weak Reed/Reed-Flex CL5 combat mechanic or explicit presentation-only authority."),
        _profile("talent:lee_jia.aura_reading_countercurrent", "Aura-Reading Countercurrent", profile_kind=ProfileKind.STATE_OR_STANCE, economy=Economy.BONUS_ACTION, status=U, source_locator="Lee Jia projection/talents", fidelity="Pattern-reading changes target selection and counterplay; prose alone is insufficient.", unresolved=("eligible visible maintained pattern", "mechanical benefit", "duration", "target"), request="Supply exact Aura-Reading Countercurrent executable text."),
        _profile("talent:lee_jia.spark_step", "Spark Step", profile_kind=ProfileKind.MOVE, economy=Economy.RIDER, status=L, source_locator="Lee Jia projection/talents", fidelity="Preserves the movement attached to charge cycling.", targeting=TargetingSpec(target_kind="SELF", range_ft=15, requires_line_of_sight=False), prerequisites=("action:lee_jia.gather_charge",), primitives=("primitive:movement",)),
    ]
    for rid, name, status, unresolved, request in [
        ("resource:lee_jia.lightning_charge", "Lightning Charge", U, ("owner/target storage", "discharge count", "expiration"), "Resolve action:lee_jia.lightning_lash exact charge contract."),
        ("resource:lee_jia.martial_focus", "Martial Focus", U, ("gain/hold/spend behavior", "linked techniques"), "Supply exact CL5 Martial Focus mechanics or explicit no-use disposition."),
        ("resource:lee_jia.prepared_talismans", "Prepared Talismans", L, (), None),
        ("resource:lee_jia.qi", "Qi", U, ("Gate 2 spend/gain uses",), "Supply exact Gate 2 uses or explicit no-use disposition for Lee Jia's Qi."),
    ]:
        profiles.append(_profile(rid, name, profile_kind=ProfileKind.RESOURCE, economy=Economy.PASSIVE, status=status, source_locator="Lee Jia projection/resources", fidelity=f"Tracks {name} and its tactical scarcity.", unresolved=unresolved, request=request, primitives=() if status != L else ("primitive:spend_resource", "primitive:gain_resource")))

    # Ling Qi.
    profiles += [
        _profile("action:ling_qi.dissonant_note", "Dissonant Note", profile_kind=ProfileKind.SAVE, economy=Economy.ACTION, status=U, source_locator="Ling Qi projection/actions", fidelity="Core control/damage action and attack-disruption line.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True), costs=(ResourceCost(resource_id="resource:ling_qi.qi", amount=2, timing="ON_SELECTION"),), save=SaveSpec(ability="WIS", dc=15), damage=DamageSpec(dice=DiceExpression(count=2, sides=6, modifier=4), damage_type="PSYCHIC"), unresolved=("successful-save damage", "disadvantage duration/consumption", "whether damage occurs on both outcomes"), request="Supply exact Dissonant Note success/failure text."),
        _profile("action:ling_qi.forgotten_vale_nocturne", "Forgotten Vale Nocturne", profile_kind=ProfileKind.ZONE, economy=Economy.ACTION, status=U, source_locator="Ling Qi projection/actions", fidelity="Ling Qi's principal battlefield-control identity.", targeting=TargetingSpec(target_kind="POINT_OR_CELL", range_ft=60, radius_ft=20, requires_line_of_sight=True), costs=(ResourceCost(resource_id="resource:ling_qi.qi", amount=4, timing="ON_SELECTION"),), save=SaveSpec(ability="WIS", dc=15), concentration=True, unresolved=("center legality", "duration", "pulse timing", "sight rule", "pressure rider", "save timing/outcomes", "difficult-terrain affected entities"), request="Supply exact Forgotten Vale Nocturne text."),
        _profile("action:ling_qi.keep_the_measure", "Keep the Measure", profile_kind=ProfileKind.STATE_OR_STANCE, economy=Economy.BONUS_ACTION, status=U, source_locator="Ling Qi projection/actions", fidelity="Formation support and Rhythmic Guard context materially affect team defense.", unresolved=("target and range", "posture effect", "duration", "temporary-HP recipient", "repeat use"), request="Supply exact Keep the Measure text."),
        _profile("action:ling_qi.music_resonant_note", "Music Resonant Note", profile_kind=ProfileKind.ATTACK, economy=Economy.ACTION, status=L, source_locator="Ling Qi projection/actions", fidelity="Exact baseline ranged attack.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True), attack=AttackSpec(bonus=7), damage=DamageSpec(dice=DiceExpression(count=2, sides=8, modifier=4), damage_type="PSYCHIC"), primitives=("primitive:attack_roll", "primitive:damage")),
        _profile("action:ling_qi.sound_resonant_note", "Sound Cultivator Resonant Note", profile_kind=ProfileKind.SAVE, economy=Economy.BONUS_ACTION, status=U, source_locator="Ling Qi projection/actions", fidelity="Bonus-action damage and attack penalty define two-note sequencing.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=60, requires_line_of_sight=True), costs=(ResourceCost(resource_id="resource:ling_qi.qi", amount=1, timing="ON_SELECTION"),), save=SaveSpec(ability="WIS", dc=15), damage=DamageSpec(dice=DiceExpression(count=1, sides=6, modifier=4), damage_type="PSYCHIC"), unresolved=("successful-save damage", "-1d4 penalty duration/consumption", "whether damage occurs on both outcomes"), request="Supply exact Sound Resonant Note success/failure text."),
        _profile("passive:ling_qi.mirror_trace", "Mirror Trace", profile_kind=ProfileKind.PASSIVE_TRIGGER, economy=Economy.PASSIVE, status=U, source_locator="Ling Qi projection/passives", fidelity="Defensive reading/resource generation may change reaction and phase behavior.", unresolved=("successful defensive reading definition", "gain quantity", "spend use", "expiration/reset"), request="Supply exact Mirror Trace source mechanic."),
        _profile("reaction:ling_qi.qi_armor", "Qi Armor", profile_kind=ProfileKind.REACTION_AC, economy=Economy.REACTION, status=L, source_locator="Ling Qi projection/reactions", fidelity="Converts a provisional hit into a miss at a defined Qi cost.", costs=(ResourceCost(resource_id="resource:ling_qi.qi", amount=2, timing="ON_REACTION_SELECTION"),), checkpoint="ATTACK_HIT_BEFORE_DAMAGE", duration=DurationSpec(expiration="END_OF_TRIGGERING_ATTACK"), primitives=("primitive:add_modifier", "primitive:resolve_reaction", "primitive:spend_resource")),
        _profile("reaction:ling_qi.rhythmic_guard", "Rhythmic Guard", profile_kind=ProfileKind.REACTION_REDUCTION, economy=Economy.REACTION, status=L, source_locator="Ling Qi projection/reactions", fidelity="Exact damage-reduction reaction with Qi scarcity.", costs=(ResourceCost(resource_id="resource:ling_qi.qi", amount=1, timing="ON_REACTION_SELECTION"),), checkpoint="DAMAGE_APPLICATION", primitives=("primitive:damage", "primitive:resolve_reaction", "primitive:spend_resource")),
    ]
    for rid, name, status, unresolved, request in [
        ("resource:ling_qi.martial_focus", "Martial Focus", U, ("gain/hold/spend behavior", "linked techniques"), "Supply exact CL5 Martial Focus mechanics or explicit no-use disposition."),
        ("resource:ling_qi.mirror_trace", "Mirror Trace", U, ("gain/spend/reset behavior",), "Resolve passive:ling_qi.mirror_trace."),
        ("resource:ling_qi.qi", "Qi", L, (), None),
        ("resource:ling_qi.smoke_trace", "Smoke Trace", U, ("gain trigger", "spend effect", "expiration/reset"), "Supply exact Smoke Trace mechanics or explicit no-use disposition."),
    ]:
        profiles.append(_profile(rid, name, profile_kind=ProfileKind.RESOURCE, economy=Economy.PASSIVE, status=status, source_locator="Ling Qi projection/resources", fidelity=f"Tracks {name} and prevents unsupported resource mutation.", unresolved=unresolved, request=request, primitives=() if status != L else ("primitive:spend_resource", "primitive:gain_resource")))

    # Bai Meizhen and Cui.
    profiles += [
        _profile("action:bai_meizhen.blackwater_serpent_court", "Blackwater Serpent Court", profile_kind=ProfileKind.ZONE, economy=Economy.ACTION, status=U, source_locator="Bai Meizhen projection/actions", fidelity="Primary formation, venom, and reaction-denial engine.", targeting=TargetingSpec(target_kind="POINT_OR_CELL", radius_ft=20, requires_line_of_sight=True), costs=(ResourceCost(resource_id="resource:bai_meizhen.qi", amount=4, timing="ON_SELECTION"),), save=SaveSpec(ability="CON", dc=15), damage=DamageSpec(dice=DiceExpression(count=2, sides=6, modifier=4), damage_type="POISON"), concentration=True, unresolved=("cast range/center", "duration", "pulse timing", "entry/start-turn trigger", "successful-save rounding", "Dose Mark effect", "reaction-denial duration", "Bai/Cui/allied immunity"), request="Supply exact Blackwater Serpent Court text."),
        _profile("action:bai_meizhen.command_cui", "Command Cui", profile_kind=ProfileKind.COMMAND_COMPANION, economy=Economy.BONUS_ACTION, status=U, source_locator="Bai Meizhen projection/actions and Cui projection", fidelity="Defines companion timing and formation geometry.", targeting=TargetingSpec(target_kind="OWNED_COMPANION", requires_line_of_sight=False), unresolved=("command range", "required perception/communication", "strike target geometry", "nested activation movement/action budget", "behavior if Bai is inactive"), request="Supply exact Command Cui and companion activation text."),
        _profile("action:bai_meizhen.numbing_venom_palm", "Numbing Venom Palm", profile_kind=ProfileKind.ATTACK_THEN_SAVE, economy=Economy.ACTION, status=U, source_locator="Bai Meizhen projection/actions", fidelity="Named close-range venom action cannot be omitted without flattening Bai's choices.", costs=(ResourceCost(resource_id="resource:bai_meizhen.qi", amount=1, timing="ON_SELECTION"),), attack=AttackSpec(bonus=7), post_hit_save=SaveSpec(ability="CON", dc=15), unresolved=("reach", "damage", "damage type", "failed-save effect", "successful-save result", "Dose interaction"), request="Supply exact Numbing Venom Palm text."),
        _profile("action:bai_meizhen.water_lash", "Water Lash", profile_kind=ProfileKind.ATTACK, economy=Economy.ACTION, status=L, source_locator="Bai Meizhen projection/actions", fidelity="Exact medium-range baseline and Water Whip trigger.", targeting=TargetingSpec(target_kind="HOSTILE_ENTITY", range_ft=30, requires_line_of_sight=True), attack=AttackSpec(bonus=7), damage=DamageSpec(dice=DiceExpression(count=1, sides=8, modifier=4), damage_type="BLUDGEONING"), follow_up="action:bai_meizhen.water_whip", primitives=("primitive:attack_roll", "primitive:damage")),
        _profile("action:bai_meizhen.water_whip", "Water Whip", profile_kind=ProfileKind.ON_HIT_OPTION, economy=Economy.ON_HIT_OPTION, status=U, source_locator="Bai Meizhen projection/actions", fidelity="Converts Water Lash into Bai's defining control line.", prerequisites=("action:bai_meizhen.water_lash ON_HIT",), costs=(ResourceCost(resource_id="resource:bai_meizhen.qi", amount=1, timing="ON_SELECTION", optional=True),), save=SaveSpec(ability="STR", dc=15), unresolved=("Grappled/Soaked duration", "escape action/check", "range tether", "source ending conditions", "successful-save result"), request="Supply exact Water Whip duration and removal contract."),
        _profile("passive:bai_meizhen.serpent_kinship", "Serpent Kinship", profile_kind=ProfileKind.PASSIVE_TRIGGER, economy=Economy.PASSIVE, status=U, source_locator="Bai Meizhen projection/passives", fidelity="Bai/Cui kinship is explicitly team-role and Dao material.", unresolved=("mechanical effects", "eligible triggers", "limits"), request="Supply exact Serpent Kinship CL5 mechanics or explicit presentation-only authority."),
        _profile("reaction:bai_meizhen.spirit_intercession", "Spirit Intercession", profile_kind=ProfileKind.REACTION_PREVENTION, economy=Economy.REACTION, status=U, source_locator="Bai Meizhen projection/reactions", fidelity="Protector reaction determines ally/Cui survival and formation integrity.", checkpoint="ALLY_OR_COMPANION_ATTACKED", unresolved=("target substitution versus AC/reduction", "range", "eligible ally", "Cui requirement", "cost", "hit re-evaluation"), request="Supply exact Spirit Intercession text."),
        _profile("reaction:bai_meizhen.water_shield", "Water Shield", profile_kind=ProfileKind.REACTION_REDUCTION, economy=Economy.REACTION, status=L, source_locator="Bai Meizhen projection/reactions", fidelity="Exact Qi-funded defensive reduction.", costs=(ResourceCost(resource_id="resource:bai_meizhen.qi", amount=1, timing="ON_REACTION_SELECTION"),), checkpoint="DAMAGE_APPLICATION", primitives=("primitive:damage", "primitive:resolve_reaction", "primitive:spend_resource")),
        _profile("creature:bai_cui", "Cui, Jade Serpent Companion", profile_kind=ProfileKind.COMPANION, economy=Economy.PASSIVE, status=U, source_locator="Bai projection/companions and creature pack", fidelity="Cui is a first-class outcome-relevant entity and Bai's core team-role expression.", unresolved=("melee strike reach", "target rules", "saving throw modifiers", "Emerald Fang failed-save effect", "Dose Mark interaction", "behavior while Bai inactive"), request="Supply exact Cui companion stat block and command rules."),
    ]
    for rid, name, status, unresolved, request in [
        ("resource:bai_meizhen.ancestral_resonance", "Ancestral Resonance", U, ("gain trigger", "spend effect", "reset"), "Supply exact Ancestral Resonance mechanics or explicit no-use disposition."),
        ("resource:bai_meizhen.cui_bond_strain", "Cui Bond Strain", U, ("gain trigger", "threshold effects", "recovery"), "Supply exact Cui Bond Strain mechanics or explicit no-use disposition."),
        ("resource:bai_meizhen.moon_sea_radiance", "Moon-Sea Radiance", U, ("gain trigger", "spend effect", "reset"), "Supply exact Moon-Sea Radiance mechanics or explicit no-use disposition."),
        ("resource:bai_meizhen.qi", "Qi", L, (), None),
    ]:
        profiles.append(_profile(rid, name, profile_kind=ProfileKind.RESOURCE, economy=Economy.PASSIVE, status=status, source_locator="Bai Meizhen projection/resources", fidelity=f"Tracks {name} and prevents unsupported resource changes.", unresolved=unresolved, request=request, primitives=() if status != L else ("primitive:spend_resource", "primitive:gain_resource")))

    profiles.sort(key=lambda p: p.source_definition_id)
    unresolved_count = sum(p.status == U for p in profiles)
    return ExecutableMechanicsLock(
        gate1_registry_snapshot_sha256=REGISTRY_SHA256,
        source_bundle_identities=(
            SourceBundleIdentity(role="SOLE_FACTORY_SOURCE_PARENT", filename="Tianxia_Factory_R6_1_Hybrid_Combat_Gate1_Source_Checkpoint.zip", sha256=GATE1_SOURCE_SHA256, size_bytes=498222, availability="VERIFIED", note="Exact Gate 1 parent; R6.2 excluded."),
            SourceBundleIdentity(role="GATE2_DESIGN", filename="Tianxia_Factory_Hybrid_Combat_Gate2_Design_R1.zip", sha256=GATE2_DESIGN_SHA256, size_bytes=17164, availability="VERIFIED", note="Exact 5/5 design payload coverage."),
            SourceBundleIdentity(role="GATE2_PROGRAMMING_PROMPT", filename="Tianxia_Factory_Hybrid_Combat_Gate2_Programming_Prompt_R1.md", sha256=GATE2_PROMPT_SHA256, size_bytes=4871, availability="VERIFIED", note="External file is byte-identical to sidecar-verified design member 04_GATE2_PROGRAMMING_PROMPT.md."),
            SourceBundleIdentity(role="NEWEST_EXACT_FOUR_CHARACTER_SOURCE_BUNDLE", filename="NOT_SUPPLIED", availability="NOT_SUPPLIED", note="No exact four-character archive was attached or available as recoverable bytes; prior combat reports were not substituted."),
        ),
        allowed_primitive_ids=ALLOWED_PRIMITIVES,
        profiles=tuple(profiles),
        material_unresolved_count=unresolved_count,
        status=LockOverallStatus.BLOCKED_GATE2B if unresolved_count else LockOverallStatus.PASS,
    )


def write_gate2a_outputs(output_root: Path) -> ExecutableMechanicsLock:
    output_root.mkdir(parents=True, exist_ok=True)
    lock = write_executable_mechanics_lock(build_gate2a_lock(), output_root / "Gate2_Executable_Mechanics_Lock.json")
    return lock
