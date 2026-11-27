"""Ability Enhancement Treasures from the Bible through character equipment."""

import pytest

from tools.build_treasure_catalog_authority import CONSUMABLES, WONDROUS, build


def test_catalog_keeps_published_ids_and_reads_printed_item_fields(tmp_path, monkeypatch):
    from factory_authoring import treasure_catalog

    treasure = tmp_path / WONDROUS
    treasure.parent.mkdir(parents=True)
    treasure.write_text(
        "# Tiny treasury\n\n"
        "| Body Slot | Typical Worn Forms | Ability Enhancement Slot |\n"
        "|---|---|---|\n"
        "| **Fingers (2)** | Rings *(up to two simultaneously)* | — |\n\n"
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
    assert (ring["treasure_id"], ring["value_gt"], ring["body_slot"]) == ("published-id", 300, "Fingers")
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


def test_compile_projects_encoded_owner_sheet_fields():
    import json

    sheet = _sheet(_enhancement("Nimble Wind", "DEX", 2, "Hands"),
                   _enhancement("Vital Health", "CON", 2, "Neck"))
    stats = sheet["ability_scores_and_statistics"]
    stats["initiative"] = {"bonus": 5}  # owner sheets can omit the ability
    stats["skills"].append({"skill": "Stealth", "ability": "DEX", "bonus": 6})
    for field in ("abilities", "armor_class", "hit_points", "initiative", "saving_throws", "skills"):
        stats[field] = json.dumps(stats[field])

    bundle = _compile(sheet)
    actor = bundle["actor_template"]
    assert (actor["initiative_bonus"], actor["armor_class"], actor["maximum_hp"]) == (6, 13, 70)
    assert actor["saving_throws"]["DEX"] == 3
    assert bundle["skills"]["Stealth"] == 7
    assert isinstance(stats["initiative"], str)


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


def test_published_hidden_pocket_belt_and_giant_might_use_the_same_slot():
    from combat.factory_compiler import equipment_list
    from combat.tabletop import TabletopError
    from factory_authoring.treasure_catalog import authority

    rows = authority()["wondrous"]
    by_name = {row["name"]: row for row in rows}
    sheet = _sheet(by_name["Hidden-Pocket Jade Belt"], by_name["Belt of Giant Might (+2)"])
    with pytest.raises(TabletopError) as err:
        equipment_list(sheet, attuned=["wondrous.0", "wondrous.1"], validate=True)
    assert err.value.code == "TABLETOP_BODY_SLOT_FULL"
    assert "Waist" in str(err.value)


@pytest.mark.parametrize(("maximum", "cl_field"), [
    pytest.param("60", "cultivation_level", id="numeric-string-maximum"),
    pytest.param(60, "cl", id="overall-cl-alias"),
])
def test_constitution_enhancement_preserves_damage_and_removal_has_a_floor(tmp_path, maximum, cl_field):
    import json
    from pathlib import Path
    from zipfile import ZipFile

    from combat.ability_checks import skill_bonus
    from combat.gate3_storage import load_typed_bundles
    from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
    from combat.journey import JourneyStore
    from combat.tabletop import ButtonStore
    from factory_authoring.treasure_catalog import authority

    belt = next(row for row in authority()["wondrous"] if row["name"] == "Belt of Giant Might (+2)")
    sheet = _sheet(_enhancement("Vital Health", "CON", 2, "Neck"), belt)
    identity = sheet["identity"]
    identity[cl_field] = identity.pop("cultivation_level")
    identity["effective_cultivation_level"] = 8
    stats = sheet["ability_scores_and_statistics"]
    stats["hit_points"] = {"maximum": maximum, "build_state_current": 40}
    stats["saving_throws"]["STR"] = "9"
    stats["skills"][0]["bonus"] = "9"

    project = "abcdef12"
    actor_id = FACTORY_ACTOR_PREFIX + project
    folder = tmp_path / "portable_characters" / project
    folder.mkdir(parents=True)
    with ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    root = Path(__file__).resolve().parents[1]
    ButtonStore(tmp_path / "tabletop_buttons").save_attunement(project, ["wondrous.0", "wondrous.1"])
    service = CombatService(root, tmp_path)
    fight = service.create_factory_match(
        project_ids=[project], match_seed="CON-AMULET", control_modes={actor_id: "MANUAL"},
    )
    admitted = next(row for row in fight["state"]["actors"] if row["entity_id"] == actor_id)
    assert (admitted["current_hp"], admitted["maximum_hp"]) == (50, 70)  # Overall CL 10, not effective CL 8
    assert (admitted["strength_score"], admitted["ability_mods"]["STR"]) == (22, 6)
    assert admitted["saving_throws"]["STR"] == 10
    [stored] = load_typed_bundles(service._match_dir(fight["match_id"]))
    assert stored["actor_template"]["saving_throws"]["STR"] == stored["skills"]["Athletics"] == 10
    escape = next(row for row in stored["action_catalog"] if row["source_definition_id"].endswith(".escape_grapple"))
    assert escape["parameters"]["typed"]["numbers"]["escape_bonus"] == 10

    loaded = CombatService(root, tmp_path)._load_session(fight["match_id"]).engine
    equipped = loaded.state.actors[actor_id]
    assert (equipped.current_hp, equipped.maximum_hp) == (50, 70)
    assert equipped.saving_throws["STR"] == skill_bonus(loaded, equipped, "Athletics", 6) == 10
    [bundle] = loaded.typed_bundle_documents
    assert bundle["skills"]["Athletics"] == 10
    assert bundle["equipment_hp_bonus"] == 10
    with ZipFile(folder / "current.zip") as archive:
        published = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))["ability_scores_and_statistics"]
    assert published["saving_throws"]["STR"] == published["skills"][0]["bonus"] == "9"

    # The previous journey ended with this hero already wounded while wearing the amulet.
    store = JourneyStore(tmp_path / "journeys")
    store.root.mkdir()
    plain = _compile(sheet, attuned=[])
    actor = plain["actor_id"]
    snapshot = {"maximum_hp": equipped.maximum_hp, "current_hp": 5, "equipment_hp_bonus": bundle["equipment_hp_bonus"],
                "temporary_hp": 0, "active": 1, "life_state": "", "conditions": {}}
    (store.root / "State.json").write_text(json.dumps({
        "sessions": {}, "actors": {actor: {"encounter_snapshot": snapshot}},
    }), encoding="utf-8")
    arena = {"width_squares": 10, "height_squares": 10, "square_size_ft": 5,
             "starting_positions": {}, "terrain_regions": []}
    journey = store.create([plain], arena, {actor: {"x": 2, "y": 2}}, {actor: 1800})
    cold = JourneyStore(store.root).load(journey["journey_id"]).state["actors"][actor]["encounter_snapshot"]
    assert (cold["current_hp"], cold["maximum_hp"]) == (1, 60)
    assert "equipment_hp_bonus" not in cold


def _steal_to_ground(table, mid, key):
    from tests import auto11_service_support as fight

    def set_down(prompt):
        source = prompt["context"]["reaction_source_id"]
        if source.endswith("steal_objects"):
            return f"fall:{key}"
        if source.endswith("steal_spot"):
            return next(row["id"] for row in prompt["choice"]["options"] if "at 3,5 " in row["label"])

    action = fight.candidate(table, mid, "Steal Equipment (take one worn thing)", fight.VICTIM)
    fight.play(table, mid, action, answer=set_down)


def test_initially_worn_amulet_can_be_picked_up_and_dropped_after_steal_equipment(tmp_path):
    from combat import carry
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests import auto11_service_support as fight

    amulet = _enhancement("Vital Health", "CON", 2, "Neck")
    victim_kit = {"items": [], "resolved_treasure_purchases": {"wondrous": [amulet]}}
    combat, table, mid = fight.fight(
        tmp_path, ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL", "TAL_SCOUNDREL_STEAL_EQUIPMENT"],
        victim_kit=victim_kit, thief_skills=[{"skill": "Sleight of Hand", "ability": "DEX", "bonus": 100}],
    )

    _steal_to_ground(table, mid, "wondrous.0")
    assert carry.dropped(fight.engine(combat, mid).state.actors[fight.VICTIM], "wondrous.0")

    cold = CombatService(combat.source_root, tmp_path)
    table = TabletopService(cold, tmp_path)
    menu = table.state(mid)["menu"]
    if menu["actor_id"] == fight.THIEF:
        fight.play(table, mid, menu["end_turn"])
    view = table.state(mid)
    assert view["menu"]["actor_id"] == fight.VICTIM
    def panel_item(state):
        return next(row for row in state["carrying"][fight.VICTIM]["items"] if row["key"] == "wondrous.0")

    on_ground = panel_item(view)
    assert on_ground["on_ground"] and not on_ground["held"] and not on_ground["worn"]
    assert on_ground["pickup"] and not on_ground["drop"]
    fight.play(table, mid, on_ground["pickup"])

    cold = CombatService(combat.source_root, tmp_path)
    table = TabletopService(cold, tmp_path)
    recovered = panel_item(table.state(mid))
    reloaded = fight.engine(cold, mid)
    assert carry.holds(reloaded, reloaded.state.actors[fight.VICTIM], "wondrous.0")
    assert recovered["held"] and not recovered["worn"] and not recovered["on_ground"]
    assert recovered["drop"] and not recovered["pickup"]
    fight.play(table, mid, recovered["drop"])
    dropped = panel_item(table.state(mid))
    assert dropped["on_ground"] and not dropped["held"] and not dropped["worn"]


def test_recovered_armour_does_not_qualify_as_worn_after_table_reload(tmp_path, monkeypatch):
    from combat.ext.blacksmith_forge import mark_count
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import bears_mark
    from tests import auto11_service_support as fight
    from tests.h1_support import script
    from tests.worker2_support import candidate

    sound = "TAL_SOUND_BODY_RESONANCE_STRIKE"
    axe = "Fu (Short Axe) attack"
    resolve = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        # Two high rolls guarantee the hit even with Disadvantage.
        script(engine, [19, 19, *([1] * 20)])
        return resolve(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    combat, table, mid = fight.fight(
        tmp_path, ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL", "TAL_SCOUNDREL_STEAL_EQUIPMENT", sound],
        thief_kit={"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]},
        thief_skills=[{"skill": "Sleight of Hand", "ability": "DEX", "bonus": 100}],
        victim_kit=fight.ARMOR, victim_talents=["tianxia.talent.blacksmith.armor_knows_its_owner"],
    )

    def end_turn(actor_id):
        menu = table.state(mid)["menu"]
        assert menu["actor_id"] == actor_id
        fight.play(table, mid, menu["end_turn"])

    def strike():
        sequence = fight.engine(combat, mid).state.event_sequence
        action = candidate(combat, mid, axe + " + Body Resonance Strike (1 CP)", target=fight.VICTIM)
        fight.play(table, mid, action.candidate_id)
        engine = fight.engine(combat, mid)
        assert any(e.sequence > sequence and e.event_type == "DAMAGE_COMMITTED"
                   and e.target_ids == (fight.VICTIM,) and e.payload["damage_type"] == "THUNDER"
                   for e in engine.events), "the paid rider must actually land before checking for Resonance"
        return bears_mark(engine.state.actors[fight.VICTIM], fight.THIEF, "Resonance")

    def armor_knows_options():
        menu = table.state(mid)["menu"]
        assert menu["actor_id"] == fight.VICTIM
        return [option for group in menu["actions"] if ".blacksmith.fit_armor.knows_" in group["source_definition_id"]
                for option in group["options"] if fight.VICTIM in option["target_ids"]]

    engine = fight.engine(combat, mid)
    toggle = next(a for a in engine.action_catalog.values()
                  if (spec := a.parameters.get("attack_modifier_setting")) and spec["modifier"] == sound
                  and spec["field"] == "on" and engine.action_catalog[spec["family"]].display_name == axe)
    fight.play(table, mid, next(c.candidate_id for c in engine.legal_candidates()
                                if c.source_definition_id == toggle.source_definition_id))
    assert strike()
    end_turn(fight.THIEF)

    # The target is the smith. Make a Forge Mark on an earlier turn so the
    # Bonus Action and the mark are still available for both menu checks.
    hammer = candidate(combat, mid, "Hammer the Mark", target=fight.VICTIM)
    fight.play(table, mid, hammer.candidate_id)
    end_turn(fight.VICTIM)
    end_turn(fight.THIEF)
    assert armor_knows_options()
    end_turn(fight.VICTIM)

    _steal_to_ground(table, mid, fight.ARMOR_KEY)
    end_turn(fight.THIEF)
    ground = next(row for row in table.state(mid)["carrying"][fight.VICTIM]["items"]
                  if row["key"] == fight.ARMOR_KEY)
    assert ground["on_ground"] and ground["pickup"]
    fight.play(table, mid, ground["pickup"])

    combat = CombatService(combat.source_root, tmp_path)
    table = TabletopService(combat, tmp_path)
    [suit] = table.state(mid)["carrying"][fight.VICTIM]["items"]
    assert suit["key"] == fight.ARMOR_KEY and suit["held"] and not suit["worn"]
    smith = fight.engine(combat, mid).state.actors[fight.VICTIM]
    assert smith.bonus_action_available and mark_count(smith, fight.VICTIM) > 0
    assert not armor_knows_options()

    end_turn(fight.VICTIM)
    assert not strike()


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
