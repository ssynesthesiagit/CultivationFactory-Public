"""The owner's 2026-10-08 object catalog expansion (42 new placeable kinds across temple/sect, village/market,
fortress/battlefield, alchemy/workshop, nature, water and interior settings, "give them hp ac etc all the
destructable and otherwise info"): every entry in combat/rules/objects.json has a complete, valid 2024 DMG stat
block, and the client-facing data the map editor's picker reads (name, description, group) is present too.

Node tests cover the art side (object-art-catalog.test.mjs). The table-behaviour half of this file (each
blocking/structure/threshold flag combination behaving correctly at the table, through a real fight, cold
reloaded) is test_son198_object_catalog_engine.py, using the same helpers tests/test_sysv2_objects.py already
established for this exact system."""
from __future__ import annotations

from combat import object_rules

NEW_KINDS = (
    "incense_burner", "prayer_wheel", "bronze_ding", "stone_guardian_lion", "sutra_shelf", "meditation_cushion",
    "temple_gong", "offering_table", "stone_lantern",
    "market_stall", "produce_cart", "woven_basket", "grain_sack", "water_barrel", "village_well", "haystack",
    "fence_section",
    "weapon_rack", "war_brazier", "palisade_section", "sandbag_wall", "ballista", "camp_banner", "army_tent",
    "ammo_crate",
    "alchemy_furnace", "pill_cabinet", "workbench", "blacksmith_anvil", "herb_drying_rack",
    "fallen_log", "tree_stump", "boulder_pile",
    "rowboat", "dock_section",
    "dining_table", "wooden_bed", "folding_screen", "bookcase", "carved_throne", "steamer_trunk", "lacquer_chest",
)
SETTING_GROUPS = {
    "incense_burner": "temple", "prayer_wheel": "temple", "bronze_ding": "temple", "stone_guardian_lion": "temple",
    "sutra_shelf": "temple", "meditation_cushion": "temple", "temple_gong": "temple", "offering_table": "temple",
    "stone_lantern": "temple",
    "market_stall": "village", "produce_cart": "village", "woven_basket": "village", "grain_sack": "village",
    "water_barrel": "village", "village_well": "village", "haystack": "village", "fence_section": "village",
    "weapon_rack": "fortress", "war_brazier": "fortress", "palisade_section": "fortress", "sandbag_wall": "fortress",
    "ballista": "fortress", "camp_banner": "fortress", "army_tent": "fortress", "ammo_crate": "fortress",
    "alchemy_furnace": "workshop", "pill_cabinet": "workshop", "workbench": "workshop",
    "blacksmith_anvil": "workshop", "herb_drying_rack": "workshop",
    "fallen_log": "nature", "tree_stump": "nature", "boulder_pile": "nature",
    "rowboat": "water", "dock_section": "water",
    "dining_table": "interior", "wooden_bed": "interior", "folding_screen": "interior", "bookcase": "interior",
    "carved_throne": "interior", "steamer_trunk": "interior", "lacquer_chest": "interior",
}
VALID_MATERIALS = frozenset(object_rules.rules()["materials"])
VALID_SIZES = frozenset(object_rules.rules()["sizes"])


def test_catalog_adds_at_least_40_new_kinds_and_this_file_names_them_all():
    assert len(NEW_KINDS) >= 40
    assert len(NEW_KINDS) == len(set(NEW_KINDS))
    assert set(NEW_KINDS) == set(SETTING_GROUPS)
    assert set(NEW_KINDS) <= set(object_rules.presets())


def test_every_new_preset_has_a_name_description_and_known_setting_group():
    presets = object_rules.presets()
    groups = object_rules.rules().get("groups", {})
    for kind in NEW_KINDS:
        preset = presets[kind]
        assert preset.get("name"), kind
        assert len(preset.get("description") or "") >= 20, f"{kind}: description too short to be newcomer-readable"
        assert preset.get("group") == SETTING_GROUPS[kind], f"{kind}: wrong picker group"
        assert preset["group"] in groups, f"{kind}: group {preset['group']!r} has no plain label"


def test_every_new_preset_resolves_to_a_complete_valid_2024_stat_block():
    for kind in NEW_KINDS:
        row = object_rules.stats({"kind": kind})
        assert row["kind"] == kind
        assert row["material"] in VALID_MATERIALS, f"{kind}: bad material {row['material']!r}"
        assert row["size"] in VALID_SIZES, f"{kind}: bad size {row['size']!r}"
        assert isinstance(row["resilient"], bool)
        assert isinstance(row["ac"], int) and row["ac"] > 0
        assert isinstance(row["hp"], int) and row["hp"] > 0
        assert row["threshold"] is None or (isinstance(row["threshold"], int) and row["threshold"] > 0)
        assert isinstance(row["blocks"], bool)
        assert isinstance(row["structure"], bool)
        assert isinstance(row["unattended"], bool)
        assert {"POISON", "PSYCHIC"} <= set(row["immune"]), f"{kind}: every object is immune to poison and psychic"
        assert isinstance(row["flammable"], bool)
        assert row["flammable"] == (row["material"] in object_rules.rules()["flammable"])


def test_every_new_preset_ac_and_hp_exactly_match_the_2024_material_and_size_tables():
    table = object_rules.rules()
    for kind in NEW_KINDS:
        preset = object_rules.presets()[kind]
        row = object_rules.stats({"kind": kind})
        assert row["ac"] == table["materials"][preset["material"]], kind
        assert row["hp"] == table["sizes"][preset["size"]]["resilient" if preset.get("resilient", True) else "fragile"], kind


def test_preset_level_damage_threshold_only_where_the_preset_sets_one_and_is_placement_overridable():
    with_threshold = {kind for kind in NEW_KINDS if object_rules.presets()[kind].get("threshold")}
    assert with_threshold == {
        "bronze_ding", "stone_guardian_lion", "village_well", "war_brazier", "sandbag_wall",
        "alchemy_furnace", "blacksmith_anvil", "boulder_pile",
    }
    for kind in with_threshold:
        preset_threshold = object_rules.presets()[kind]["threshold"]
        assert object_rules.stats({"kind": kind})["threshold"] == preset_threshold
        assert object_rules.stats({"kind": kind, "threshold": preset_threshold + 5})["threshold"] == preset_threshold + 5
    for kind in set(NEW_KINDS) - with_threshold:
        assert object_rules.stats({"kind": kind})["threshold"] is None


def test_editor_defaults_exposes_name_description_group_and_threshold_for_every_new_kind():
    defaults = object_rules.editor_defaults()
    for kind in NEW_KINDS:
        row = defaults["presets"][kind]
        preset = object_rules.presets()[kind]
        assert row["name"] == preset["name"]
        assert row["description"] == preset["description"]
        assert row["group"] == preset["group"]
        assert row["threshold"] == object_rules.stats({"kind": kind})["threshold"]
    assert set(defaults["groups"]) >= set(SETTING_GROUPS.values())
