"""Ability Enhancement Treasures from the Bible through character equipment."""

import pytest

from tools.build_treasure_catalog_authority import CONSUMABLES, WONDROUS, build


def test_catalog_keeps_published_ids_and_reads_printed_item_fields(tmp_path, monkeypatch):
    from factory_authoring import treasure_catalog

    treasure = tmp_path / WONDROUS
    treasure.parent.mkdir(parents=True)
    treasure.write_text(
        "# Tiny treasury\n\n"
        "### New gloves\n"
        "**Grade:** Saint · **Type:** Wondrous Item (Hands) · "
        "**Attunement:** 1 Attunement Slot(s) · **Appraisal:** 2,300 GT · *Spheres: Air*\n\n"
        "You gain a **+2 enhancement bonus to Dexterity**.\n\n"
        "### Old ring\n"
        "**Grade:** Spiritual · **Type:** Ring · "
        "**Attunement:** No Attunement · **Appraisal:** 300 GT · *Spheres: Space*\n\n"
        "Stores a scroll.\n\n"
        "### New amulet\n"
        "**Grade:** Sovereign · **Type:** Wondrous Item (Neck) · "
        "**Attunement:** 2 Attunement Slot(s) · **Appraisal:** 20,300 GT · *Spheres: Life*\n\n"
        "You gain a **+4 enhancement bonus to Constitution**.\n",
        encoding="utf-8",
    )
    (tmp_path / CONSUMABLES).write_text("", encoding="utf-8")
    baseline = {"wondrous": [{"name": "Old ring", "number": 1, "treasure_id": "published-id",
                              "grade": "Spiritual", "attunement_slots": 0, "text": "Stores a scroll."}],
                "consumables": [], "grade_order": ["Spiritual", "Saint", "Sovereign", "Imperial"]}
    built = build(tmp_path, baseline, expected_counts=(3, 0))
    ring, gloves, amulet = built["wondrous"]
    assert (ring["treasure_id"], ring["value_gt"]) == ("published-id", 300)
    assert (gloves["number"], gloves["body_slot"], gloves["attunement_slots"], gloves["value_gt"]) == (2, "Hands", 1, 2300)
    assert (amulet["number"], amulet["body_slot"], amulet["attunement_slots"], amulet["value_gt"]) == (3, "Neck", 2, 20300)

    monkeypatch.setattr(treasure_catalog, "authority", lambda: built)
    monkeypatch.setattr(treasure_catalog, "treasure_plan", lambda *_: {
        "realm_cap": "Imperial", "signature_used": False, "attunement_used": 0, "wondrous_budget_gt": 30_000,
    })
    purchases = treasure_catalog.resolve_treasure_catalog(
        target_cl=10, background_id="test", path_id="test", wondrous_ids=[gloves["treasure_id"]], consumable_ids=[],
    )
    [bought] = purchases["wondrous"]
    assert bought["ability_enhancement"] == {"ability": "DEX", "bonus": 2}
    assert _compile(_sheet(bought))["actor_template"]["dexterity_score"] == 16

    baseline["wondrous"][0]["text"] = "Stores two scrolls."
    with pytest.raises(SystemExit, match="STOPPED: 1 existing Wondrous rows differ from the Bible"):
        build(tmp_path, baseline, expected_counts=(3, 0))


def _enhancement(name, ability, bonus, slot, *, attunement_slots=1):
    return {"name": name, "treasure_id": name, "body_slot": slot, "attunement_slots": attunement_slots,
            "ability_enhancement": {"ability": ability, "bonus": bonus}}


def _sheet(*treasures, key="STR"):
    return {
        "identity": {"display_name": "Test cultivator", "cultivation_level": 10,
                     "proficiency_bonus": 4, "key_ability": key},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": "STR", "score": 20, "modifier": 5},
                          {"ability": "DEX", "score": 14, "modifier": 2},
                          {"ability": "CON", "score": 14, "modifier": 2}],
            "armor_class": {"base_value": 12, "value": 12}, "hit_points": {"maximum": 60},
            "initiative": {"ability": "DEX", "bonus": 2}, "speed": {"walking_ft": 30},
            "primary_resource": {"name": "Stamina", "maximum": 30},
            "saving_throws": {"STR": 9, "DEX": 2, "CON": 2},
            "skills": [{"skill": "Athletics", "ability": "STR", "bonus": 9}],
            "technique_attack_bonus": 9, "technique_save_dc": 17,
        },
        "equipment": [{"starting_kit": {"items": [], "resolved_treasure_purchases": {"wondrous": list(treasures)}}}],
    }


def _compile(sheet, **kwargs):
    from combat.factory_compiler import compile_character

    return compile_character(sheet, actor_id="actor:factory.enhancements", typed_authority={"mechanics": {}}, **kwargs)


def test_compile_uses_highest_bonus_per_ability_without_a_cap():
    # A traditional alternate form in a different slot can coexist with the belt.
    sheet = _sheet(_enhancement("Giant Might", "STR", 2, "Waist"),
                   _enhancement("Titan Might", "STR", 4, "Neck"),
                   _enhancement("Nimble Wind", "DEX", 2, "Hands"))
    bundle = _compile(sheet)
    actor = bundle["actor_template"]
    numbers = bundle["actor_numbers"]
    assert (actor["strength_score"], actor["dexterity_score"]) == (24, 16)
    assert actor["ability_mods"]["STR"] == 7
    assert actor["saving_throws"]["STR"] == 11  # still includes proficiency
    assert bundle["skills"]["Athletics"] == 11
    assert (numbers["attack_bonus"], numbers["save_dc"]) == (11, 19)
    assert (actor["armor_class"], actor["initiative_bonus"]) == (13, 3)
    opportunity = next(row["parameters"]["typed"] for row in bundle["action_catalog"]
                       if row["source_definition_id"].endswith(".opportunity_attack"))
    assert opportunity["weapon"]["fixed_damage"] == 8  # 1 + the effective Strength modifier
    assert _compile(sheet, attuned=["wondrous.0", "wondrous.2"])["actor_template"]["strength_score"] == 22
    assert sheet["ability_scores_and_statistics"]["abilities"][0]["score"] == 20


def test_table_refuses_a_duplicate_body_slot_and_allows_two_rings(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from combat.tabletop import ButtonStore, TabletopError
    from combat.tabletop_service import TabletopService

    belts = [_enhancement("Giant Might", "STR", 2, "Waist"),
             _enhancement("Titan Might", "STR", 4, "Waist", attunement_slots=2)]
    rings = [{"name": f"Ring {n}", "body_slot": "Fingers", "attunement_slots": 1} for n in range(3)]
    sheet = _sheet(*belts, *rings)
    service = TabletopService.__new__(TabletopService)
    service.buttons = ButtonStore(tmp_path / "buttons")
    service.combat = SimpleNamespace(userdata_root=tmp_path, _factory_owner_sheet=lambda project: sheet)
    monkeypatch.setattr(service, "sheet", service.buttons.get)
    project = "0b2d5c1e-4f7a-4a8e-9c3d-2e1f0a9b8c7d"

    for keys in (["wondrous.0", "wondrous.1"], ["wondrous.2", "wondrous.3", "wondrous.4"]):
        with pytest.raises(TabletopError) as err:
            service.save_attunement(project, keys)
        assert err.value.code == "TABLETOP_BODY_SLOT_FULL"
        assert "attuned" not in service.buttons.get(project)

    keys = ["wondrous.1", "wondrous.2", "wondrous.3"]
    assert service.save_attunement(project, keys)["attuned"] == keys
    carrying = _compile(sheet, attuned=service.buttons.get(project)["attuned"])["carrying"]
    assert carrying["attunement"]["used"] == 4
    assert [item["key"] for item in carrying["items"] if item["worn"]] == keys

    # A prepared character can leave the previously worn belt behind and put
    # another in that slot; validation uses the same carried load as the fight.
    service.save_left_behind(project, ["wondrous.1"])
    other = ["wondrous.0", "wondrous.2", "wondrous.3"]
    assert service.save_attunement(project, other)["attuned"] == other


def test_constitution_enhancement_preserves_damage_and_removal_has_a_floor(tmp_path):
    import json

    from combat.journey import JourneyStore

    sheet = _sheet(_enhancement("Vital Health", "CON", 2, "Neck"))
    sheet["identity"]["effective_cultivation_level"] = 8
    sheet["ability_scores_and_statistics"]["hit_points"]["build_state_current"] = 40
    equipped = _compile(sheet)
    assert equipped["actor_template"]["maximum_hp"] == 70  # Overall CL 10, not effective CL 8
    assert equipped["actor_template"]["initial_hp"] == 50
    assert equipped["equipment_hp_bonus"] == 10

    # The previous journey ended with this hero already wounded while wearing the amulet.
    store = JourneyStore(tmp_path / "journeys")
    store.root.mkdir()
    plain = _compile(sheet, attuned=[])
    actor = plain["actor_id"]
    snapshot = {"maximum_hp": 70, "current_hp": 5, "equipment_hp_bonus": 10, "temporary_hp": 0,
                "active": 1, "life_state": "", "conditions": {}}
    (store.root / "State.json").write_text(json.dumps({
        "sessions": {}, "actors": {actor: {"encounter_snapshot": snapshot}},
    }), encoding="utf-8")
    arena = {"width_squares": 10, "height_squares": 10, "square_size_ft": 5,
             "starting_positions": {}, "terrain_regions": []}
    journey = store.create([plain], arena, {actor: {"x": 2, "y": 2}}, {actor: 1800})
    cold = JourneyStore(store.root).load(journey["journey_id"]).state["actors"][actor]["encounter_snapshot"]
    assert (cold["current_hp"], cold["maximum_hp"]) == (1, 60)
    assert "equipment_hp_bonus" not in cold


def test_cp_maximum_uses_the_base_score_without_worn_time():
    sheet = _sheet(_enhancement("Titan Might", "STR", 4, "Waist"))
    stats = sheet["ability_scores_and_statistics"]
    stats["primary_resource"]["base_formula"] = {
        "op": "add", "terms": [{"op": "constant", "value": 25}, {"op": "ability_modifier", "ability": "STR"}],
    }
    bundle = _compile(sheet)
    stamina = next(pool for pool in bundle["actor_template"]["resources"]
                   if pool["resource_id"] == "resource:core.stamina")
    assert bundle["actor_template"]["ability_mods"]["STR"] == 7
    assert stamina["maximum"] == 30  # 25 + base modifier of 5, not the combat modifier of 7
