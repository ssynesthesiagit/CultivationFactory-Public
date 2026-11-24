"""Reviewed Background foreign keys, not display-text aliases.

Consumed by non_sphere_authority.service and tools/validate_background_route_links.py.
Order is the printed Background choice order. Route IDs also identify the granted
Background Talent; canonical and creator Sphere IDs are distinct explicit targets.
The legacy CAT2 rows remain immutable source evidence, including their four null
Sphere IDs. Source hashes bind this review to the original release; validate them
when releasing the catalog, never infer relationships from prose at runtime.
"""
from __future__ import annotations

from typing import Any

from app.core import FoundryError

SOURCE_SHA256 = {
    'non_sphere_authority/authority/Background_Core_Authority_v1.json': 'd0dd7e5eae00273985958f2fde2d8329bc4fa9329ad4fdb0ab795c449341f2e2',
    'catalog_authority/cat1/data/background_origin_talent_routes.v1.json': '6aa66a37174d1519112b3b5ad7adac508588f6b630bb497ddd6aa7a60c516ddc',
}

BACKGROUND_ROUTE_IDS = {
    'tianxia.background.abandoned_orphan': (
        'tianxia.background_talent.scoundrel.grifter_s_hands',
        'tianxia.background_talent.scoundrel.hidden_tool_cache',
        'tianxia.background_talent.equipment.hidden_plates',
    ),
    'tianxia.background.ancestral_shrine_keeper': (
        'tianxia.background_talent.spirit_companions.iron_courtesy',
        'tianxia.background_talent.karma.witness_seal',
        'tianxia.background_talent.talismans.warding_talisman',
    ),
    'tianxia.background.artisan_s_child': (
        'tianxia.background_talent.blacksmith.field_repair',
        'tianxia.background_talent.equipment.field_maintenance',
        'tianxia.background_talent.ink.concealing_script',
    ),
    'tianxia.background.beast_hunter': (
        'tianxia.background_talent.spear.rooted_spear_stance',
        'tianxia.background_talent.barrage.distracting_shot',
        'tianxia.background_talent.trap.noose',
        'tianxia.background_talent.beastmastery.lookout',
    ),
    'tianxia.background.border_scout': (
        'tianxia.background_talent.athletics.swift_movement',
        'tianxia.background_talent.trap.warning_trigger',
        'tianxia.background_talent.sniper.still_scope_posture',
    ),
    'tianxia.background.clan_heir': (
        'tianxia.background_talent.sect_stewardship.sect_token_etiquette',
        'tianxia.background_talent.equipment.reinforced_robes',
        'tianxia.background_talent.ink.binding_script',
        'tianxia.background_talent.sword.sword_guard',
    ),
    'tianxia.background.criminal_runner': (
        'tianxia.background_talent.scoundrel.hidden_tool_cache',
        'tianxia.background_talent.scoundrel.switcheroo',
        'tianxia.background_talent.equipment.hidden_plates',
    ),
    'tianxia.background.cursed_bloodline': (
        'tianxia.background_talent.dark.blindfold',
        'tianxia.background_talent.dark.hide_in_darkness',
        'tianxia.background_talent.dark.shadowed_mien',
    ),
    'tianxia.background.dream_touched': (
        'tianxia.background_talent.dreams.dream_whisper',
        'tianxia.background_talent.dreams.dream_ward',
        'tianxia.background_talent.dreams.shared_dream',
    ),
    'tianxia.background.exiled_noble': (
        'tianxia.background_talent.sword.sword_drawing_stance',
        'tianxia.background_talent.scoundrel.distracting_trickery',
        'tianxia.background_talent.equipment.hidden_plates',
        'tianxia.background_talent.sect_stewardship.quiet_apology_method',
    ),
    'tianxia.background.forest_hermit': (
        'tianxia.background_talent.harvesting_and_gathering.common_herbcraft',
        'tianxia.background_talent.harvesting_and_gathering.camp_gatherer',
        'tianxia.background_talent.athletics.strong_lungs',
    ),
    'tianxia.background.furnace_laborer': (
        'tianxia.background_talent.brute.focused_might',
        'tianxia.background_talent.blacksmith.field_repair',
        'tianxia.background_talent.equipment.field_maintenance',
        'tianxia.background_talent.athletics.mighty_conditioning',
    ),
    'tianxia.background.herb_gatherer': (
        'tianxia.background_talent.harvesting_and_gathering.common_herbcraft',
        'tianxia.background_talent.harvesting_and_gathering.farmer_s_eye',
        'tianxia.background_talent.alchemy.antidote_pill',
        'tianxia.background_talent.poison.poison_sense',
    ),
    'tianxia.background.imperial_scholar': (
        'tianxia.background_talent.ink.wet_ink_warning',
        'tianxia.background_talent.ink.revealing_script',
        'tianxia.background_talent.equipment.reinforced_robes',
    ),
    'tianxia.background.jambudvipan_mystic': (
        'tianxia.background_talent.alchemy.calming_heart_pill',
        'tianxia.background_talent.alchemy.antidote_pill',
        'tianxia.background_talent.flowing_river.reed_in_storm',
        'tianxia.background_talent.athletics.strong_lungs',
    ),
    'tianxia.background.merchant_clan_scion': (
        'tianxia.background_talent.sect_stewardship.clean_ledger_hand',
        'tianxia.background_talent.equipment.hidden_plates',
        'tianxia.background_talent.ink.binding_script',
    ),
    'tianxia.background.military_brat': (
        'tianxia.background_talent.equipment.armor_training',
        'tianxia.background_talent.equipment.shield_training',
        'tianxia.background_talent.spear.rooted_spear_stance',
        'tianxia.background_talent.warleader.battlefield_coordination',
    ),
    'tianxia.background.monastery_novice': (
        'tianxia.background_talent.iron_fist.focusing_breath',
        'tianxia.background_talent.iron_fist.merciful_hand',
        'tianxia.background_talent.flowing_river.empty_step',
        'tianxia.background_talent.spear.long_shaft_discipline',
    ),
    'tianxia.background.northern_steppe_rider': (
        'tianxia.background_talent.beastmastery.mount_training',
        'tianxia.background_talent.spear.pursuit_spear',
        'tianxia.background_talent.barrage.mobile_barrage',
        'tianxia.background_talent.warleader.rallying_speech',
    ),
    'tianxia.background.puppeteer_s_child': (
        'tianxia.background_talent.puppetry.little_servant_s_errand',
        'tianxia.background_talent.puppetry.hidden_thread',
        'tianxia.background_talent.equipment.field_maintenance',
    ),
    'tianxia.background.river_child': (
        'tianxia.background_talent.flowing_river.patient_water',
        'tianxia.background_talent.flowing_river.empty_step',
        'tianxia.background_talent.athletics.strong_lungs',
        'tianxia.background_talent.athletics.sure_grip',
    ),
    'tianxia.background.sect_servant': (
        'tianxia.background_talent.equipment.field_maintenance',
        'tianxia.background_talent.equipment.hidden_plates',
        'tianxia.background_talent.sect_stewardship.senior_brother_s_errand',
        'tianxia.background_talent.ink.wet_ink_warning',
    ),
    'tianxia.background.shinobi_apprentice': (
        'tianxia.background_talent.scoundrel.cut_and_run',
        'tianxia.background_talent.trap.warning_trigger',
        'tianxia.background_talent.equipment.hidden_plates',
        'tianxia.background_talent.poison.poison_sense',
    ),
    'tianxia.background.spirit_medium': (
        'tianxia.background_talent.spirit_companions.iron_courtesy',
        'tianxia.background_talent.spirit_companions.gentle_offering_method',
        'tianxia.background_talent.spirit_companions.ancestral_ear',
        'tianxia.background_talent.spirit_companions.vessel_mark',
    ),
    'tianxia.background.talisman_apprentice': (
        'tianxia.background_talent.talismans.talisman_master_s_ink',
        'tianxia.background_talent.talismans.hidden_sleeve_preparation',
        'tianxia.background_talent.ink.vermilion_correction',
        'tianxia.background_talent.equipment.reinforced_robes',
    ),
    'tianxia.background.temple_initiate': (
        'tianxia.background_talent.talismans.warding_talisman',
        'tianxia.background_talent.protection.ward',
        'tianxia.background_talent.radiance.consecrated_lantern',
        'tianxia.background_talent.spirit_companions.minor_spirit_agreements',
    ),
    'tianxia.background.traveling_performer': (
        'tianxia.background_talent.music.captivating_melody',
        'tianxia.background_talent.jester.false_opening',
        'tianxia.background_talent.puppetry.little_servant_s_errand',
        'tianxia.background_talent.equipment.hidden_plates',
    ),
    'tianxia.background.village_child': (
        'tianxia.background_talent.harvesting_and_gathering.drying_shed_method',
        'tianxia.background_talent.athletics.mighty_conditioning',
        'tianxia.background_talent.equipment.padded_layers',
    ),
    'tianxia.background.wandering_healer': (
        'tianxia.background_talent.alchemy.healing_pill',
        'tianxia.background_talent.alchemy.calming_heart_pill',
        'tianxia.background_talent.life.clear_physician_s_eye',
        'tianxia.background_talent.equipment.field_maintenance',
    ),
    'tianxia.background.war_refugee': (
        'tianxia.background_talent.equipment.sleep_in_armor',
        'tianxia.background_talent.equipment.padded_layers',
        'tianxia.background_talent.scoundrel.cut_and_run',
        'tianxia.background_talent.athletics.swift_movement',
    ),
    'tianxia.background.workshop_apprentice': (
        'tianxia.background_talent.blacksmith.field_repair',
        'tianxia.background_talent.blacksmith.workman_s_eye',
        'tianxia.background_talent.equipment.field_maintenance',
        'tianxia.background_talent.ink.revealing_script',
    ),
}

# route ID -> (canonical Sphere ID, existing creator Background Sphere choice ID)
# These are relationships, not names to normalize or aliases to resolve.
ROUTE_TARGETS = {
    'tianxia.background_talent.alchemy.antidote_pill': ('tianxia.sphere.alchemy', 'tianxia.background_sphere.alchemy'),
    'tianxia.background_talent.alchemy.calming_heart_pill': ('tianxia.sphere.alchemy', 'tianxia.background_sphere.alchemy'),
    'tianxia.background_talent.alchemy.healing_pill': ('tianxia.sphere.alchemy', 'tianxia.background_sphere.alchemy'),
    'tianxia.background_talent.athletics.mighty_conditioning': ('tianxia.sphere.athletics', 'tianxia.background_sphere.athletics'),
    'tianxia.background_talent.athletics.strong_lungs': ('tianxia.sphere.athletics', 'tianxia.background_sphere.athletics'),
    'tianxia.background_talent.athletics.sure_grip': ('tianxia.sphere.athletics', 'tianxia.background_sphere.athletics'),
    'tianxia.background_talent.athletics.swift_movement': ('tianxia.sphere.athletics', 'tianxia.background_sphere.athletics'),
    'tianxia.background_talent.barrage.distracting_shot': ('tianxia.sphere.barrage', 'tianxia.background_sphere.barrage'),
    'tianxia.background_talent.barrage.mobile_barrage': ('tianxia.sphere.barrage', 'tianxia.background_sphere.barrage'),
    'tianxia.background_talent.beastmastery.lookout': ('tianxia.sphere.beastmastery', 'tianxia.background_sphere.beastmastery'),
    'tianxia.background_talent.beastmastery.mount_training': ('tianxia.sphere.beastmastery', 'tianxia.background_sphere.beastmastery'),
    'tianxia.background_talent.blacksmith.field_repair': ('tianxia.sphere.blacksmith', 'tianxia.background_sphere.blacksmith'),
    'tianxia.background_talent.blacksmith.workman_s_eye': ('tianxia.sphere.blacksmith', 'tianxia.background_sphere.blacksmith'),
    'tianxia.background_talent.brute.focused_might': ('tianxia.sphere.brute', 'tianxia.background_sphere.brute'),
    'tianxia.background_talent.dark.blindfold': ('tianxia.sphere.dark', 'tianxia.background_sphere.dark'),
    'tianxia.background_talent.dark.hide_in_darkness': ('tianxia.sphere.dark', 'tianxia.background_sphere.dark'),
    'tianxia.background_talent.dark.shadowed_mien': ('tianxia.sphere.dark', 'tianxia.background_sphere.dark'),
    'tianxia.background_talent.dreams.dream_ward': ('tianxia.sphere.dreams', 'tianxia.background_sphere.dreams'),
    'tianxia.background_talent.dreams.dream_whisper': ('tianxia.sphere.dreams', 'tianxia.background_sphere.dreams'),
    'tianxia.background_talent.dreams.shared_dream': ('tianxia.sphere.dreams', 'tianxia.background_sphere.dreams'),
    'tianxia.background_talent.equipment.armor_training': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.equipment.field_maintenance': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.equipment.hidden_plates': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.equipment.padded_layers': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.equipment.reinforced_robes': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.equipment.shield_training': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.equipment.sleep_in_armor': ('tianxia.sphere.equipment', 'tianxia.background_sphere.equipment'),
    'tianxia.background_talent.flowing_river.empty_step': ('tianxia.sphere.flowing_river', 'tianxia.background_sphere.flowing_river'),
    'tianxia.background_talent.flowing_river.patient_water': ('tianxia.sphere.flowing_river', 'tianxia.background_sphere.flowing_river'),
    'tianxia.background_talent.flowing_river.reed_in_storm': ('tianxia.sphere.flowing_river', 'tianxia.background_sphere.flowing_river'),
    'tianxia.background_talent.harvesting_and_gathering.camp_gatherer': ('tianxia.sphere.harvesting_gathering', 'tianxia.background_sphere.harvesting_and_gathering'),
    'tianxia.background_talent.harvesting_and_gathering.common_herbcraft': ('tianxia.sphere.harvesting_gathering', 'tianxia.background_sphere.harvesting_and_gathering'),
    'tianxia.background_talent.harvesting_and_gathering.drying_shed_method': ('tianxia.sphere.harvesting_gathering', 'tianxia.background_sphere.harvesting_and_gathering'),
    'tianxia.background_talent.harvesting_and_gathering.farmer_s_eye': ('tianxia.sphere.harvesting_gathering', 'tianxia.background_sphere.harvesting_and_gathering'),
    'tianxia.background_talent.ink.binding_script': ('tianxia.sphere.ink', 'tianxia.background_sphere.ink'),
    'tianxia.background_talent.ink.concealing_script': ('tianxia.sphere.ink', 'tianxia.background_sphere.ink'),
    'tianxia.background_talent.ink.revealing_script': ('tianxia.sphere.ink', 'tianxia.background_sphere.ink'),
    'tianxia.background_talent.ink.vermilion_correction': ('tianxia.sphere.ink', 'tianxia.background_sphere.ink'),
    'tianxia.background_talent.ink.wet_ink_warning': ('tianxia.sphere.ink', 'tianxia.background_sphere.ink'),
    'tianxia.background_talent.iron_fist.focusing_breath': ('tianxia.sphere.iron_fist', 'tianxia.background_sphere.iron_fist'),
    'tianxia.background_talent.iron_fist.merciful_hand': ('tianxia.sphere.iron_fist', 'tianxia.background_sphere.iron_fist'),
    'tianxia.background_talent.jester.false_opening': ('tianxia.sphere.jester', 'tianxia.background_sphere.jester'),
    'tianxia.background_talent.karma.witness_seal': ('tianxia.sphere.karma', 'tianxia.background_sphere.karma'),
    'tianxia.background_talent.life.clear_physician_s_eye': ('tianxia.sphere.life', 'tianxia.background_sphere.life'),
    'tianxia.background_talent.music.captivating_melody': ('tianxia.sphere.music', 'tianxia.background_sphere.music'),
    'tianxia.background_talent.poison.poison_sense': ('tianxia.sphere.poison', 'tianxia.background_sphere.poison'),
    'tianxia.background_talent.protection.ward': ('tianxia.sphere.protection', 'tianxia.background_sphere.protection'),
    'tianxia.background_talent.puppetry.hidden_thread': ('tianxia.sphere.puppetry', 'tianxia.background_sphere.puppetry'),
    'tianxia.background_talent.puppetry.little_servant_s_errand': ('tianxia.sphere.puppetry', 'tianxia.background_sphere.puppetry'),
    'tianxia.background_talent.radiance.consecrated_lantern': ('tianxia.sphere.radiance', 'tianxia.background_sphere.radiance'),
    'tianxia.background_talent.scoundrel.cut_and_run': ('tianxia.sphere.scoundrel', 'tianxia.background_sphere.scoundrel'),
    'tianxia.background_talent.scoundrel.distracting_trickery': ('tianxia.sphere.scoundrel', 'tianxia.background_sphere.scoundrel'),
    'tianxia.background_talent.scoundrel.grifter_s_hands': ('tianxia.sphere.scoundrel', 'tianxia.background_sphere.scoundrel'),
    'tianxia.background_talent.scoundrel.hidden_tool_cache': ('tianxia.sphere.scoundrel', 'tianxia.background_sphere.scoundrel'),
    'tianxia.background_talent.scoundrel.switcheroo': ('tianxia.sphere.scoundrel', 'tianxia.background_sphere.scoundrel'),
    'tianxia.background_talent.sect_stewardship.clean_ledger_hand': ('tianxia.sphere.sect_stewardship', 'tianxia.background_sphere.sect_stewardship'),
    'tianxia.background_talent.sect_stewardship.quiet_apology_method': ('tianxia.sphere.sect_stewardship', 'tianxia.background_sphere.sect_stewardship'),
    'tianxia.background_talent.sect_stewardship.sect_token_etiquette': ('tianxia.sphere.sect_stewardship', 'tianxia.background_sphere.sect_stewardship'),
    'tianxia.background_talent.sect_stewardship.senior_brother_s_errand': ('tianxia.sphere.sect_stewardship', 'tianxia.background_sphere.sect_stewardship'),
    'tianxia.background_talent.sniper.still_scope_posture': ('tianxia.sphere.sniper', 'tianxia.background_sphere.sniper'),
    'tianxia.background_talent.spear.long_shaft_discipline': ('tianxia.sphere.spear', 'tianxia.background_sphere.spear'),
    'tianxia.background_talent.spear.pursuit_spear': ('tianxia.sphere.spear', 'tianxia.background_sphere.spear'),
    'tianxia.background_talent.spear.rooted_spear_stance': ('tianxia.sphere.spear', 'tianxia.background_sphere.spear'),
    'tianxia.background_talent.spirit_companions.ancestral_ear': ('tianxia.sphere.spirit_companions', 'tianxia.background_sphere.spirit_companions'),
    'tianxia.background_talent.spirit_companions.gentle_offering_method': ('tianxia.sphere.spirit_companions', 'tianxia.background_sphere.spirit_companions'),
    'tianxia.background_talent.spirit_companions.iron_courtesy': ('tianxia.sphere.spirit_companions', 'tianxia.background_sphere.spirit_companions'),
    'tianxia.background_talent.spirit_companions.minor_spirit_agreements': ('tianxia.sphere.spirit_companions', 'tianxia.background_sphere.spirit_companions'),
    'tianxia.background_talent.spirit_companions.vessel_mark': ('tianxia.sphere.spirit_companions', 'tianxia.background_sphere.spirit_companions'),
    'tianxia.background_talent.sword.sword_drawing_stance': ('tianxia.sphere.sword', 'tianxia.background_sphere.sword'),
    'tianxia.background_talent.sword.sword_guard': ('tianxia.sphere.sword', 'tianxia.background_sphere.sword'),
    'tianxia.background_talent.talismans.hidden_sleeve_preparation': ('tianxia.sphere.talismans', 'tianxia.background_sphere.talismans'),
    'tianxia.background_talent.talismans.talisman_master_s_ink': ('tianxia.sphere.talismans', 'tianxia.background_sphere.talismans'),
    'tianxia.background_talent.talismans.warding_talisman': ('tianxia.sphere.talismans', 'tianxia.background_sphere.talismans'),
    'tianxia.background_talent.trap.noose': ('tianxia.sphere.trap', 'tianxia.background_sphere.trap'),
    'tianxia.background_talent.trap.warning_trigger': ('tianxia.sphere.trap', 'tianxia.background_sphere.trap'),
    'tianxia.background_talent.warleader.battlefield_coordination': ('tianxia.sphere.warleader', 'tianxia.background_sphere.warleader'),
    'tianxia.background_talent.warleader.rallying_speech': ('tianxia.sphere.warleader', 'tianxia.background_sphere.warleader'),
}


def validated_route_records(
    backgrounds: dict[str, dict[str, Any]], routes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate foreign-key coverage for the runtime and catalog release check."""
    route_ids = [row.get("background_route_record_id") for row in routes]
    linked_ids = {route_id for ids in BACKGROUND_ROUTE_IDS.values() for route_id in ids}
    if (any(not isinstance(route_id, str) or not route_id for route_id in route_ids)
            or len(route_ids) != len(set(route_ids)) or set(route_ids) != set(ROUTE_TARGETS)
            or linked_ids != set(route_ids) or set(backgrounds) != set(BACKGROUND_ROUTE_IDS)):
        raise FoundryError(
            "NS1R_BACKGROUND_ROUTE_AUTHORITY_AMBIGUOUS",
            "Background route IDs must be unique and cover exactly the reviewed catalog.",
            status_code=500,
        )
    by_id = dict(zip(route_ids, routes))
    for background_id, route_ids in BACKGROUND_ROUTE_IDS.items():
        if len(route_ids) != len(set(route_ids)) or not set(route_ids) <= set(by_id):
            raise FoundryError(
                "NS1R_BACKGROUND_ROUTE_AUTHORITY_AMBIGUOUS",
                "A Background must declare its complete ordered set of unique route IDs.",
                details={"background_id": background_id}, status_code=500,
            )
    for route_id, route in by_id.items():
        declared = route.get("canonical_sphere_id")
        canonical_sphere_id, _ = ROUTE_TARGETS[route_id]
        if declared is not None and declared != canonical_sphere_id:
            raise FoundryError(
                "NS1R_BACKGROUND_ROUTE_CANONICAL_SPHERE_INVALID",
                "A Background route disagrees with its reviewed canonical Sphere target.",
                details={"route_id": route_id, "declared_canonical_sphere_id": declared,
                         "canonical_sphere_id": canonical_sphere_id}, status_code=500,
            )
    return by_id
