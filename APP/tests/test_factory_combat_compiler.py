"""A finished Factory character compiles to typed combat data and fights under the combat AI."""

import json
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_models import LocalControllerPolicy
from combat.gate4_policy import PolicyLibrary
from factory_authoring.sphere_dao import character_dao, controller_policy, sheet_sphere_talents

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "actor:factory.test"
SHEET = {
    "identity": {"display_name": "Test Cultivator", "cultivation_level": 17, "proficiency_bonus": 6, "key_ability": "CON"},
    "ability_scores_and_statistics": {
        "abilities": json.dumps([{"ability": a, "modifier": m, "score": 10 + 2 * m} for a, m in
                                 (("STR", 4), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))]),
        "armor_class": json.dumps({"base_value": 14}), "hit_points": json.dumps({"maximum": 120}),
        "initiative": json.dumps({"bonus": 2}), "speed": json.dumps({"walking_ft": 30}),
        "primary_resource": json.dumps({"name": "Stamina", "maximum": 40}),
        "technique_attack_bonus": 10, "technique_save_dc": 18,
    },
    "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.brute", "tianxia.sphere.sabers"],
        "learned_talent_record_ids": ["TAL_BRUTE_MOUNTAIN_MOVING_PALM", "tianxia.talent.sabers.forward_cut"],
    },
    "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}],
}


def test_compiled_character_fights_with_its_typed_abilities():
    bundle = compile_character(SHEET, actor_id=ACTOR)
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Mountain-Moving Palm", "Forward Cut", "Dao (Saber / Broadsword) attack"} <= names
    template = bundle["actor_template"]
    assert template["armor_class"] == 14 and template["saving_throws"]["STR"] == 4
    assert ("resource:core.stamina", 40) in [(r["resource_id"], r["maximum"]) for r in template["resources"]]

    engine = Gate2Engine(ROOT, match_seed="FACTORY-COMPILER-TEST", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    policy = LocalControllerPolicy.model_validate(controller_policy(character_dao(sheet_sphere_talents(SHEET)), ACTOR))
    library = PolicyLibrary(ROOT, actor_policy=lambda actor: policy.model_dump(mode="json", by_alias=True) if actor == ACTOR else None)
    controller = LocalDeterministicController()
    for _ in range(400):
        if engine.state.terminal_result is not None:
            break
        actor_id = engine.legal_candidates()[0].actor_id
        engine.execute_intent(controller.choose_primary_action(build_decision_context(engine, library.for_actor(actor_id)[0], for_ai=True)).intent)
    assert engine.state.terminal_result is not None
    typed_used = {e.source_definition_id for e in engine.events if e.event_type == "INTENT_ACCEPTED" and e.actor_id == ACTOR}
    assert any(source.startswith("action:typed.") for source in typed_used)


def test_i_ching_change_and_tactical_movement():
    from combat.factory_compiler import primary_resource

    bundle = compile_character(SHEET, actor_id=ACTOR)
    engine = Gate2Engine(ROOT, match_seed="FACTORY-ICHING-TEST", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    policy = LocalControllerPolicy.model_validate(
        controller_policy(character_dao(sheet_sphere_talents(SHEET)), ACTOR, primary_resource=primary_resource(SHEET)))
    library = PolicyLibrary(ROOT, actor_policy=lambda actor: policy.model_dump(mode="json", by_alias=True) if actor == ACTOR else None)
    controller = LocalDeterministicController()
    while engine.legal_candidates()[0].actor_id != ACTOR:
        actor_id = engine.legal_candidates()[0].actor_id
        engine.execute_intent(controller.choose_primary_action(build_decision_context(engine, library.for_actor(actor_id)[0])).intent)
    moves = [c for c in engine.legal_candidates() if c.kind.value == "MOVE"]
    assert moves and all("cover_from_nearest_hostile" in c.metadata and "adjacent_hostiles" in c.metadata for c in moves)
    calm = controller.choose_primary_action(build_decision_context(engine, policy))
    assert "I Ching change" not in calm.record.explanation
    engine.state.actors[ACTOR].current_hp = 10  # badly wounded: the stress posture takes over
    pressed = controller.choose_primary_action(build_decision_context(engine, policy))
    assert "I Ching change (wounded)" in pressed.record.explanation


def test_extra_attack_and_conductive_strike_shape_the_compiled_weapon_attack():
    sheet = {**SHEET, "path_and_subpath": {"path_feature_record_ids": ["tianxia.path.body_refining.feature.extra_attack"]},
             "spheres_and_talents": {**SHEET["spheres_and_talents"],
                                     "learned_talent_record_ids": [*SHEET["spheres_and_talents"]["learned_talent_record_ids"], "TAL_LIGHTNING_CONDUCTIVE_STRIKE"]}}
    plain = next(row for row in compile_character(SHEET, actor_id=ACTOR)["action_catalog"] if row["display_name"].startswith("Dao"))
    bundle = compile_character(sheet, actor_id=ACTOR)
    dao = next(row for row in bundle["action_catalog"] if row["display_name"].startswith("Dao"))
    attack = dao["parameters"]["typed"]["effects"][0]
    assert attack["count"] == 4  # CL17
    assert {"type": "damage", "flat": 6, "damage_types": ["LIGHTNING"], "source_feature": "TAL_LIGHTNING_CONDUCTIVE_STRIKE",
            "once_per_turn": "TAL_LIGHTNING_CONDUCTIVE_STRIKE"} in attack["on_hit"]
    assert dao["parameters"]["typed"]["mundane"] is True
    assert dao["parameters"]["expected_damage"] == 4 * plain["parameters"]["expected_damage"] + 6
    skipped = bundle["diagnostics"]["skipped"]
    assert "Extra Attack" not in skipped["passive"] and "Conductive Strike" not in skipped["passive"]


def test_destructive_blast_and_forged_techniques_become_actions():
    """Owner 2026-09-25: Destructive Blast (checked typing) and Forged Techniques fight at level."""
    technique = {"technique_id": "tianxia.constructed.forged_technique.test", "name": "Palm Projection", "action_type": "bonus action",
                 "primary_sphere_effect": {"talent_id": "TAL_BRUTE_MOUNTAIN_MOVING_PALM"}, "cp_cost": {"final": 6},
                 "base_form": {"display_name": "Projection"}, "augments": [{"augment_id": "bonus_action_activation", "display_name": "Bonus-Action Activation"},
                                                                          {"augment_id": "domain_effect", "display_name": "Domain Effect"}],
                 "limits": ["usable once per Short Rest"]}
    counter = {**technique, "technique_id": "tianxia.constructed.forged_technique.counter", "name": "Counter", "action_type": "reaction"}
    sheet = {**SHEET, "forged_techniques": [technique, counter],
             "spheres_and_talents": {**SHEET["spheres_and_talents"], "automatic_sphere_component_record_ids": ["TAL_DESTRUCTION_DESTRUCTIVE_BLAST"]}}
    bundle = compile_character(sheet, actor_id=ACTOR)
    by_name = {row["display_name"]: row for row in bundle["action_catalog"]}
    blast = by_name["Destructive Blast"]
    assert blast["range_ft"] == 30 and blast["parameters"]["expected_damage"] == 18  # 4d8 at CL17
    forged = by_name["Palm Projection"]
    assert forged["economy"] == "BONUS_ACTION" and ["resource:core.stamina", 6] in [list(cost) for cost in forged["costs"]]
    assert any(cost[0].startswith("resource:uses.") for cost in forged["costs"])  # once per Short Rest: once per fight
    assert "Domain Effect (GM)" in forged["parameters"]["typed"]["riders"]
    # Owner 2026-09-27 (combat/forged.py): the Base Form delivers the Primary Sphere Effect. A Projection of the palm's
    # cone is a ranged technique attack: the 8d8 lands on a hit, the push and condition keep the palm's Strength save.
    attack = forged["parameters"]["typed"]["effects"][0]
    assert attack["type"] == "attack" and attack["attack_kind"] == "cultivation_ranged" and forged["target_kind"] == "HOSTILE_ENTITY"
    assert attack["on_hit"][0]["dice"] == {**attack["on_hit"][0]["dice"], "count": 8, "sides": 8}
    assert attack["on_hit"][1]["type"] == "save" and attack["on_hit"][1]["ability"] == "str"
    assert {effect["type"] for effect in attack["on_hit"][1]["on_fail"]} >= {"forced_movement"}
    assert "Counter" in bundle["diagnostics"]["skipped"]["reaction"]


def test_a_two_path_character_gets_both_cultivation_pools():
    """Smoke test 2026-09-25: a Body + Spirit character has Stamina and Resonance; Path features pay their own Path's pool."""
    stats = {**SHEET["ability_scores_and_statistics"], "primary_resource": json.dumps({
        "name": "Resonance", "maximum": 20,
        "definitions": [{"name": "Resonance", "max": 20, "resource_id": "tianxia.resource.resonance"},
                        {"name": "Stamina", "max": 54, "resource_id": "tianxia.resource.stamina"}]})}
    sheet = {**SHEET, "ability_scores_and_statistics": stats}
    bundle = compile_character(sheet, actor_id=ACTOR)
    pools = {row["resource_id"]: row["maximum"] for row in bundle["actor_template"]["resources"]}
    assert pools["resource:core.resonance"] == 20 and pools["resource:core.stamina"] == 54

    from combat.factory_compiler import _costs

    feature = {"name": "Body trick", "path_id": "tianxia.path.body_refining", "cost": [[{"resource": "cp", "amount": 2}]]}
    talent = {"name": "Sphere trick", "cost": [[{"resource": "cp", "amount": 1}]]}
    assert _costs(feature, "resonance", 4, "a", [], {"resonance", "stamina"})[0] == [("resource:core.stamina", 2)]
    assert _costs(talent, "resonance", 4, "b", [], {"resonance", "stamina"})[0] == [("resource:core.resonance", 1)]


def test_reach_versatile_and_bow_range_shape_weapon_attacks():
    """Owner 2026-09-26: Reach and Versatile apply; a bow's printed Range makes it a ranged attack."""
    def attacks(items):
        sheet = {**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}]}
        return {row["source_definition_id"].split(".")[-1]: row for row in compile_character(sheet, actor_id=ACTOR)["action_catalog"]
                if ".weapon." in row["source_definition_id"] and "#" not in row["source_definition_id"]
                and not row["source_definition_id"].endswith(".pickup")}

    rows = attacks(["tianxia.mortal.weapon.qiang", "tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.san_jie_gun",
                    "tianxia.mortal.weapon.gong_jian", "tianxia.mortal.weapon.jian"])
    assert {key: row["range_ft"] for key, row in rows.items()} == {
        "qiang": 10, "liu_xing_chui": 15, "san_jie_gun": 5, "gong_jian": 600, "jian": 5}
    assert rows["qiang"]["parameters"]["typed"]["range_ft"] is None  # a reach attack is still a melee attack
    assert (rows["gong_jian"]["parameters"]["typed"]["range_ft"], rows["gong_jian"]["parameters"]["typed"]["long_range_ft"]) == (150, 600)
    assert rows["jian"]["parameters"]["typed"]["weapon"]["damage"]["sides"] == 10  # both hands free
    with_shield = attacks(["tianxia.mortal.weapon.jian", "tianxia.mortal.armor.shield"])
    assert with_shield["jian"]["parameters"]["typed"]["weapon"]["damage"]["sides"] == 8


def test_rope_dart_reaches_30_ft_and_trips_or_grapples():
    """Owner 2026-09-26: the rope dart reaches 5-30 ft, deals 1d2 for its versatility, and a hit can also try a trip
    or a grapple -- "they can be added to it, but only one" (combat/rules/weapon_specials.json)."""
    sheet = {**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.sheng_biao"}]}}]}
    bundle = compile_character(sheet, actor_id=ACTOR)
    darts = {row["display_name"]: row for row in bundle["action_catalog"] if ".weapon.sheng_biao" in row["source_definition_id"]
             and not row["source_definition_id"].endswith(".pickup")}
    # The fixture SHEET carries the Brute sphere (below), which now grants Disarm on any melee weapon (gu 2026-09-28,
    # Brute Maneuvers) alongside the rope dart's own Trip/Grapple.
    assert set(darts) == {"Sheng Biao (Rope Dart) attack", "Sheng Biao (Rope Dart) attack: Trip", "Sheng Biao (Rope Dart) attack: Grapple",
                          "Sheng Biao (Rope Dart) attack: Disarm"}
    strike = darts["Sheng Biao (Rope Dart) attack"]
    weapon = strike["parameters"]["typed"]["weapon"]
    assert strike["range_ft"] == 30 and strike["parameters"]["typed"]["range_ft"] is None  # still a melee attack
    assert (weapon["damage"]["count"], weapon["damage"]["sides"], weapon["damage_types"]) == (1, 2, ["PIERCING"])
    trip = darts["Sheng Biao (Rope Dart) attack: Trip"]["parameters"]["typed"]
    on_hit = trip["effects"][0]["on_hit"]
    assert on_hit[0] == {"type": "damage", "weapon_damage": True}  # the hit still deals its damage
    rider = on_hit[-1]
    assert rider["ability"] == "STR_OR_DEX" and rider["on_fail"][0]["condition"] == "prone" and rider["first_hit_only"]
    assert trip["numbers"]["save_dc"] == 8 + 6 + 4  # PB + the better of STR/DEX (Finesse)

    engine = Gate2Engine(ROOT, match_seed="ROPE-DART", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    me, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    foe.position = me.position.model_copy(update={"x": me.position.x + 6})
    engine.state.current_actor_id = ACTOR
    assert engine._distance_actor_to_actor(me, foe) == 30
    for name in darts:
        engine.action_catalog[darts[name]["source_definition_id"]].parameters["typed"]["numbers"].update(attack_bonus=40, save_dc=40)
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Sheng Biao (Rope Dart) attack: Grapple"))
    from tests.test_typed_executor import _intent
    engine.execute_intent(_intent(candidate))
    assert any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())
    assert [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == candidate.source_definition_id]
    # Grappled lasts until the target escapes (owner 2026-09-26), not just past a turn...
    for checkpoint, who in (("END_OF_TURN", ACTOR), ("END_OF_TURN", AN), ("START_OF_TURN", AN)):
        engine._expire_for_checkpoint(checkpoint, who)
    assert any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())
    # ...or is beyond the grappler's reach (30 ft for the rope dart).
    foe.position = me.position.model_copy(update={"x": me.position.x + 7})
    engine._expire_for_checkpoint("START_OF_TURN", AN)
    assert not any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())


def _weapons_of(items, paths=("tianxia.path.qi_cultivation",), extra_ids=(), strength=None, features=(), spheres=()):
    abilities = [{"ability": a, "modifier": m, "score": 10 + 2 * m} for a, m in (("STR", 4), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))]
    if strength is not None:
        abilities[0] = {"ability": "STR", "modifier": (strength - 10) // 2, "score": strength}
    sheet = {**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
             "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "abilities": json.dumps(abilities)},
             "path_and_subpath": {"path_record_ids": list(paths), "path_feature_record_ids": list(features)},
             "spheres_and_talents": {**SHEET["spheres_and_talents"], "automatic_sphere_component_record_ids": list(extra_ids)}}
    # Printed choice is explicit and durable; owning Method cannot choose from gear.
    if "SABERS_BASE_SABER_LINE_METHOD" in extra_ids:
        # The choice goes through the public selector, not a pre-seeded row (MGR-T15 finding 3).
        from combat.ext.saber_learning import select
        from combat.table_advance import normalized
        saved = select({"source_id": "SABERS_BASE_SABER_LINE_METHOD", "item_id": "tianxia.mortal.weapon.dao",
                        "sheet": sheet, "gm_sphere": "", "gm": False, "saved": normalized(None), "principal": {}})
        sheet["learning_choices"] = saved["learning_choices"]
    bundle = compile_character(sheet, actor_id=ACTOR, granted_spheres=list(spheres))
    return bundle, {row["source_definition_id"].split(".weapon.")[-1]: row for row in bundle["action_catalog"]
                    if ".weapon." in row["source_definition_id"] and not row["source_definition_id"].endswith(".pickup")}


def test_weapon_proficiency_loading_and_heavy():
    """Owner 2026-09-26: "we need stuff like proficiency if applicable ... heavy loading long range"."""
    _, rows = _weapons_of(["tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.gun", "tianxia.mortal.weapon.nu_gong"])
    bonus = {key: row["parameters"]["typed"]["numbers"]["attack_bonus"] for key, row in rows.items()}
    assert bonus["gun"] == 6 + 4 and bonus["dao"] == 4  # Qi Cultivation trains simple weapons only: no PB with a martial dao
    _, rows = _weapons_of(["tianxia.mortal.weapon.dao"], extra_ids=["SABERS_BASE_SABER_LINE_METHOD"])
    assert rows["dao"]["parameters"]["typed"]["numbers"]["attack_bonus"] == 6 + 4  # Saber-Line Method's chosen saber
    _, rows = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.qi_cultivation", "tianxia.path.body_refining"))
    assert rows["dao"]["parameters"]["typed"]["numbers"]["attack_bonus"] == 6 + 4  # an added Path adds its training

    _, rows = _weapons_of(["tianxia.mortal.weapon.nu_gong", "tianxia.mortal.weapon.guandao_yanyuedao"], paths=("tianxia.path.body_refining",),
                          features=["tianxia.path.body_refining.feature.extra_attack"])
    assert rows["nu_gong"]["parameters"]["typed"]["effects"][0]["count"] == 1  # Loading: one bolt per action at CL17
    assert rows["guandao_yanyuedao"]["parameters"]["typed"]["effects"][0]["count"] == 4
    assert "disadvantage" not in rows["guandao_yanyuedao"]["parameters"]["typed"]
    _, rows = _weapons_of(["tianxia.mortal.weapon.guandao_yanyuedao", "tianxia.mortal.weapon.chui"], strength=12)
    assert rows["guandao_yanyuedao"]["parameters"]["typed"]["disadvantage"] == "Heavy" and rows["chui"]["parameters"]["typed"]["disadvantage"]


def test_light_and_paired_weapons_give_an_off_hand_attack_after_the_attack_action():
    """Owner 2026-09-26: "light and paired for offhand attacks for dual wielding"."""
    bundle, rows = _weapons_of(["tianxia.mortal.weapon.duan_jian", "tianxia.mortal.weapon.bi_shou", "tianxia.mortal.weapon.jian"],
                               paths=("tianxia.path.body_refining",), spheres=["tianxia.sphere.weapons"])
    offhand = {key: row for key, row in rows.items() if key.endswith("#offhand")}
    assert set(offhand) == {"duan_jian#offhand", "bi_shou#offhand"}  # the jian is neither Light nor Paired
    knife = offhand["bi_shou#offhand"]
    # The dagger's Nick mastery makes its off-hand attack part of the Attack action; the short sword's (Vex) is a Bonus Action.
    assert knife["economy"] == "NONE" and offhand["duan_jian#offhand"]["economy"] == "BONUS_ACTION"
    assert knife["parameters"]["typed"]["weapon"]["damage"]["modifier"] == 0
    assert knife["parameters"]["typed"]["effects"][0]["count"] == 1
    _, paired = _weapons_of(["tianxia.mortal.weapon.hu_die_dao"], paths=("tianxia.path.body_refining",))
    assert "hu_die_dao#offhand" in paired  # Butterfly Sabers are their own pair

    engine = Gate2Engine(ROOT, match_seed="OFF-HAND", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    me, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    me.position = me.position.model_copy(update={"x": 3, "y": 6})
    foe.position = foe.position.model_copy(update={"x": 4, "y": 6})
    engine.state.current_actor_id = ACTOR
    names = lambda: {c.display_name for c in engine.legal_candidates() if c.actor_id == ACTOR}  # noqa: E731
    assert not any("off-hand" in name for name in names())
    from tests.test_typed_executor import _intent
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith("Duan Jian (Short Sword) attack"))))
    assert foe.active and engine.state.current_actor_id == ACTOR
    offered = {name for name in names() if "off-hand" in name}
    assert offered == {"Bi Shou (Dagger) off-hand attack"}  # a different Light weapon; the short sword is not Paired


def test_long_range_shots_have_disadvantage():
    from tests.test_typed_executor import _intent

    bundle, rows = _weapons_of(["tianxia.mortal.weapon.bi_shou"], paths=("tianxia.path.body_refining",))
    assert rows["bi_shou#thrown"]["range_ft"] == 60 and rows["bi_shou#thrown"]["parameters"]["typed"]["range_ft"] == 20
    modes = []
    for cells in (3, 10):  # 15 ft is inside the thrown dagger's 20 ft; 50 ft is long range (20/60)
        engine = Gate2Engine(ROOT, match_seed=f"LONG-RANGE-{cells}", typed_bundles=(bundle,),
                             roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
        me, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
        me.position = me.position.model_copy(update={"x": 0, "y": 6})  # row 0 has walls in the way
        foe.position = foe.position.model_copy(update={"x": cells, "y": 6})
        engine.state.current_actor_id = ACTOR
        before = len(engine.events)
        engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith("Bi Shou (Dagger) thrown"))))
        modes += [(engine._distance_actor_to_actor(me, foe), e.payload.get("mode")) for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED"]
    assert [mode for _, mode in modes] == ["NORMAL", "DISADVANTAGE"], modes


def test_masteries_come_from_the_weapon_table_and_need_proficiency():
    """Owner 2026-09-26: each weapon type fights its own way, "in line with dnd 5e as far as it can be"."""
    _, rows = _weapons_of(["tianxia.mortal.weapon.ji", "tianxia.mortal.weapon.ge", "tianxia.mortal.weapon.chui", "tianxia.mortal.weapon.dao",
                           "tianxia.mortal.weapon.gong_jian", "tianxia.mortal.weapon.gun", "tianxia.mortal.weapon.duan_jian"],
                          paths=("tianxia.path.body_refining",), spheres=["tianxia.sphere.weapons"])
    hits = {key: [e["type"] for e in row["parameters"]["typed"]["effects"][0]["on_hit"][1:]] for key, row in rows.items() if "#" not in key}
    assert hits["ji"] == ["cleave"] and hits["chui"] == ["forced_movement"] and hits["dao"] == ["disadvantage"]
    assert hits["gong_jian"] == ["speed"] and hits["gun"] == ["save"] and hits["duan_jian"] == ["vex"]
    assert rows["chui"]["parameters"]["typed"]["effects"][0]["on_hit"][1]["max_size_cells"] == 2  # Push: Large or smaller
    graze = rows["ge"]["parameters"]["typed"]["effects"][0]["on_miss"]
    assert graze == [{"type": "damage", "flat": 4, "damage_types": ["SLASHING"], "applies_to": "target"}]
    # The fixture SHEET carries the Brute sphere, which now grants Disarm on any melee weapon (gu 2026-09-28, Brute
    # Maneuvers) alongside the Ge's own Trip/Pull.
    assert {key for key in rows if key.startswith("ge#") and "#method_" not in key} == {"ge#trip", "ge#pull", "ge#disarm"}
    _, untrained = _weapons_of(["tianxia.mortal.weapon.dao"])  # Qi Cultivation: no martial training, so no mastery
    assert untrained["dao"]["parameters"]["typed"]["mastery"] is None and len(untrained["dao"]["parameters"]["typed"]["effects"][0]["on_hit"]) == 1


def test_a_maneuver_rides_only_the_first_hit_of_the_attack_action():
    bundle, rows = _weapons_of(["tianxia.mortal.weapon.sheng_biao"], paths=("tianxia.path.body_refining",),
                               features=["tianxia.path.body_refining.feature.extra_attack"])
    trip = rows["sheng_biao#trip"]
    assert trip["parameters"]["typed"]["effects"][0]["count"] == 4
    engine = Gate2Engine(ROOT, match_seed="ONE-MANEUVER", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    me, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    me.position, foe.position = me.position.model_copy(update={"x": 3, "y": 6}), foe.position.model_copy(update={"x": 4, "y": 6})
    engine.state.current_actor_id = ACTOR
    foe.maximum_hp = 999
    foe.current_hp = 999
    engine.action_catalog[trip["source_definition_id"]].parameters["typed"]["numbers"].update(attack_bonus=40, save_dc=1)
    from tests.test_typed_executor import _intent
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.source_definition_id == trip["source_definition_id"])))
    source = trip["source_definition_id"]
    assert sum(1 for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == source) >= 4
    assert sum(1 for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == source) == 1


def test_prone_creatures_stand_at_the_start_of_their_turn_for_half_their_speed():
    engine = Gate2Engine(ROOT, match_seed="STAND-UP")
    target = next(a for a in engine.state.actors.values() if a.entity_id != engine.state.current_actor_id)
    engine._apply_condition(target, "condition:typed.prone", "src.trip", engine.state.current_actor_id, expires_on="STAND_UP")
    target.movement_remaining_ft = 30
    engine._expire_for_checkpoint("END_OF_TURN", engine.state.current_actor_id)
    assert any(c.condition_id == "condition:typed.prone" for c in target.conditions.values())  # still down for the attacker's allies
    engine._expire_for_checkpoint("START_OF_TURN", target.entity_id)
    assert not any(c.condition_id == "condition:typed.prone" for c in target.conditions.values())
    assert target.movement_remaining_ft == 30 - engine._effective_speed(target) // 2
    # Grappled as well (Speed 0): it cannot stand.
    engine._apply_condition(target, "condition:typed.prone", "src.trip", engine.state.current_actor_id, expires_on="STAND_UP")
    engine._apply_condition(target, "condition:typed.grappled", "src.grab", engine.state.current_actor_id, expires_on="END_OF_HOLDER_NEXT_TURN")
    engine._expire_for_checkpoint("START_OF_TURN", target.entity_id)
    assert any(c.condition_id == "condition:typed.prone" for c in target.conditions.values())


def test_cleave_swings_into_a_second_adjacent_enemy_once_per_turn():
    from combat.gate2_runtime_content import LEE
    from tests.test_typed_executor import _intent

    bundle, rows = _weapons_of(["tianxia.mortal.weapon.ji"], paths=("tianxia.path.body_refining",), spheres=["tianxia.sphere.weapons"])
    engine = Gate2Engine(ROOT, match_seed="CLEAVE", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN, LEE], "team_by_actor": {ACTOR: "team:a", AN: "team:b", LEE: "team:b"}})
    me, first, second = engine.state.actors[ACTOR], engine.state.actors[AN], engine.state.actors[LEE]
    me.position = me.position.model_copy(update={"x": 3, "y": 6})
    first.position = first.position.model_copy(update={"x": 5, "y": 6})
    second.position = second.position.model_copy(update={"x": 5, "y": 7})
    engine.state.current_actor_id = ACTOR
    halberd = rows["ji"]["source_definition_id"]
    engine.action_catalog[halberd].parameters["typed"]["numbers"].update(attack_bonus=40)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == halberd and c.target_ids == (AN,))
    engine.execute_intent(_intent(candidate))
    struck = [e.target_ids[0] for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == halberd]
    assert struck.count(LEE) == 1 and AN in struck


def _duel(bundle, seed, *, gap=1):
    engine = Gate2Engine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN], "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    me, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    me.position, foe.position = me.position.model_copy(update={"x": 3, "y": 6}), foe.position.model_copy(update={"x": 3 + gap, "y": 6})
    engine.state.current_actor_id = ACTOR
    return engine, me, foe


def test_disarm_drops_the_weapon_until_it_is_picked_up():
    """Owner 2026-09-26: "disarm not dropping" -- the target loses that weapon's attacks until it spends the pick-up."""
    from tests.test_typed_executor import _intent

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.bi_shou"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "DISARM")
    engine.typed_actor_ids.add(ACTOR)
    dao = next(a for a in me.action_ids if a.endswith(".weapon.dao"))
    engine._apply_condition(me, "condition:typed.disarmed", "src.disarm", AN, expires_on="UNTIL_REMOVED",
                            data={"disables_action": dao, "dropped_at": me.position.model_dump(mode="json")})
    names = {c.display_name for c in engine.legal_candidates() if c.actor_id == ACTOR}
    assert not any(name.startswith("Dao (Saber / Broadsword) attack") for name in names)
    assert any(name.startswith("Bi Shou (Dagger) attack") for name in names) and "Pick up Dao (Saber / Broadsword)" in names
    assert "Pick up Bi Shou (Dagger)" not in names
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name == "Pick up Dao (Saber / Broadsword)")))
    assert not me.conditions and any(c.display_name.startswith("Dao (Saber / Broadsword) attack") for c in engine.legal_candidates())

    from combat import typed_executor
    assert typed_executor._best_weapon_action(engine, me) == dao  # the Disarm maneuver takes the hardest-hitting weapon


def test_a_grappled_creature_can_escape_with_its_action():
    from tests.test_typed_executor import _intent

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "ESCAPE")
    assert "Escape grapple" not in {c.display_name for c in engine.legal_candidates()}
    engine._apply_condition(me, "condition:typed.grappled", "src.grab", AN, expires_on="UNTIL_REMOVED", data={"escape_dc": 1, "reach_ft": 5})
    assert engine._attack_mode(me, foe) == "NORMAL"  # attacking the grappler is fine...
    escape = next(c for c in engine.legal_candidates() if c.display_name == "Escape grapple")
    engine.execute_intent(_intent(escape))
    check = next(e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == escape.source_definition_id)
    assert check.payload["success"] and not me.conditions and not me.action_available


def test_grappled_attackers_have_disadvantage_against_others_and_vex_marks_one_target():
    from combat.gate2_runtime_content import LEE

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.duan_jian"], paths=("tianxia.path.body_refining",))
    engine = Gate2Engine(ROOT, match_seed="VEX", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN, LEE], "team_by_actor": {ACTOR: "team:a", AN: "team:b", LEE: "team:b"}})
    me, an, lee = engine.state.actors[ACTOR], engine.state.actors[AN], engine.state.actors[LEE]
    engine._apply_condition(me, "condition:typed.grappled", "src.grab", AN, expires_on="UNTIL_REMOVED", data={"escape_dc": 10, "reach_ft": 5})
    assert (engine._attack_mode(me, an), engine._attack_mode(me, lee)) == ("NORMAL", "DISADVANTAGE")
    me.conditions.clear()
    engine.state.current_actor_id = ACTOR
    engine._add_modifier(me, "src.vex", "attack_mode_vs", "SET", f"ADVANTAGE:{AN}", "NEXT_ATTACK", expires_on=f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}")
    assert (engine._attack_mode(me, an), engine._attack_mode(me, lee)) == ("ADVANTAGE", "NORMAL")
    engine._expire_for_checkpoint("END_OF_TURN", ACTOR)
    assert engine._attack_mode(me, an) == "ADVANTAGE"  # lasts through your next turn
    me.turns_started += 1
    engine._expire_for_checkpoint("END_OF_TURN", ACTOR)
    assert engine._attack_mode(me, an) == "NORMAL"


def test_size_limits_push_and_maneuvers():
    """Push: Large or smaller. Trip, Grapple and Pull: no more than one size larger than you (2024 rules)."""
    from combat import typed_executor
    from combat.gate2_runtime_models import Position

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.chui"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "SIZE")
    huge = engine._footprint(foe).model_copy(update={"width_cells": 3, "height_cells": 3, "occupied_relative_cells": tuple(
        Position(x=x, y=y) for x in range(3) for y in range(3))})
    engine.actor_footprints[AN] = huge
    action = engine.action_catalog[next(a for a in me.action_ids if a.endswith(".weapon.chui"))]
    ctx = typed_executor.Context(engine, me, action, None, action.parameters["typed"], [foe], foe, {})
    before = foe.position
    typed_executor.block_forced_movement(ctx, {"type": "forced_movement", "distance_ft": 10, "direction": "away", "applies_to": "target", "max_size_cells": 2})
    assert foe.position == before
    saves = len([e for e in engine.events if e.event_type == "SAVE_ROLLED"])
    typed_executor.block_save(ctx, {"type": "save", "ability": "STR_OR_DEX", "max_size_larger": 1, "on_fail": [{"type": "condition", "condition": "prone"}]})
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == saves  # Huge vs Medium: no attempt


def test_a_grappler_drags_the_creature_and_pays_double_movement():
    """2024 Grappled ("Movable"): the grappler can drag it along; each foot costs 1 extra foot (owner 2026-09-26 asked)."""
    from tests.test_typed_executor import _intent

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "DRAG")
    engine._apply_condition(foe, "condition:typed.grappled", "src.grab", ACTOR, expires_on="UNTIL_REMOVED", data={"escape_dc": 12, "reach_ft": 5})
    me.movement_remaining_ft = 30
    moves = [c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.actor_id == ACTOR]
    # Walking retains its geometric quote; added jump candidates quote the
    # paid cost. Both must travel at most 15 feet and spend double distance.
    assert max(engine.grid.distance_ft(me.position, c.destination) for c in moves) <= 15
    paid = lambda c: c.movement_cost_ft * (1 if c.metadata.get('movement_mode') == 'jump' else 2)
    assert all(2 * engine.grid.distance_ft(me.position, c.destination) <= paid(c) <= 30 for c in moves)
    away = max(moves, key=lambda c: (engine.grid.distance_ft(c.destination, foe.position), -c.destination.x))
    engine.execute_intent(_intent(away))
    assert engine._distance_actor_to_actor(me, foe) <= 5  # it came along
    assert me.movement_remaining_ft == 30 - paid(away)
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == AN and e.payload.get("dragged_by") == ACTOR for e in engine.events)
    release = next(c for c in engine.legal_candidates() if c.display_name == "Release grapple")
    engine.execute_intent(_intent(release))
    assert not foe.conditions and "Release grapple" not in {c.display_name for c in engine.legal_candidates()}


def test_a_dropped_weapon_is_picked_up_only_within_5_ft():
    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "DROPPED")
    dao = next(a for a in me.action_ids if a.endswith(".weapon.dao"))
    engine._apply_condition(me, "condition:typed.disarmed", "src.disarm", AN, expires_on="UNTIL_REMOVED",
                            data={"disables_action": dao, "dropped_at": {"x": 3, "y": 6}})
    assert "Pick up Dao (Saber / Broadsword)" in {c.display_name for c in engine.legal_candidates()}
    me.position = me.position.model_copy(update={"x": 6, "y": 6})  # pushed 15 ft away from it
    assert "Pick up Dao (Saber / Broadsword)" not in {c.display_name for c in engine.legal_candidates()}


def test_a_pin_is_a_grapple_broken_in_two_escapes():
    """Owner 2026-09-26: a pinned creature must succeed on a grapple check to break the pin but is still grappled, so it
    needs another check to break the grapple."""
    from combat import typed_executor

    bundle, rows = _weapons_of(["tianxia.mortal.weapon.qiang"], paths=("tianxia.path.body_refining",))
    pin = rows["qiang#pin"]["parameters"]["typed"]["effects"][0]["on_hit"][-1]
    assert [row["condition"] for row in pin["on_fail"]] == ["grappled", "pinned"] and pin["max_size_larger"] == 1
    engine, me, foe = _duel(bundle, "PIN", gap=2)
    action = engine.action_catalog[rows["qiang#pin"]["source_definition_id"]]
    ctx = typed_executor.Context(engine, me, action, None, {**action.parameters["typed"], "numbers": {"save_dc": 99}}, [foe], foe, {})
    typed_executor.block_save(ctx, pin)
    held = lambda: sorted(c.condition_id.split(".")[-1] for c in foe.conditions.values())  # noqa: E731
    assert held() == ["grappled", "pinned"] and engine._attack_mode(me, foe) == "ADVANTAGE"
    for checkpoint, who in (("END_OF_TURN", AN), ("START_OF_TURN", ACTOR), ("START_OF_TURN", AN)):
        engine._expire_for_checkpoint(checkpoint, who)
    assert held() == ["grappled", "pinned"]  # until it escapes (within the spear's 10 ft reach)
    for condition in foe.conditions.values():
        condition.data["escape_dc"] = 1
    escape = typed_executor.Context(engine, foe, engine.action_catalog[next(a for a in me.action_ids if a.endswith("escape_grapple"))], None,
                                    {"numbers": {"escape_bonus": 0}}, [foe], foe, {})
    typed_executor.block_escape_grapple(escape, {})
    assert held() == ["grappled"]
    typed_executor.block_escape_grapple(escape, {})
    assert held() == []

def _walk_away(engine, mover_id, reactor, *, cells=3):
    from tests.test_typed_executor import _intent

    engine.state.current_actor_id = mover_id
    mover = engine.state.actors[mover_id]
    moves = [c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.actor_id == mover_id]
    away = max(moves, key=lambda c: (engine.grid.distance_ft(c.destination, reactor.position), -c.movement_cost_ft))
    before = len(engine.events)
    engine.execute_intent(_intent(away))
    return [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and e.source_definition_id.endswith(".opportunity_attack")]


def test_factory_fighters_make_opportunity_attacks_with_their_best_melee_weapon():
    """Owner 2026-09-26: opportunity attacks for Factory fighters (the AI used to decline every one)."""
    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.bi_shou"], paths=("tianxia.path.body_refining",))
    oa = next(row for row in bundle["action_catalog"] if row["source_definition_id"].endswith(".opportunity_attack"))
    assert oa["parameters"]["typed"]["opportunity_of"].endswith(".weapon.dao") and oa["parameters"]["typed"]["effects"][0]["count"] == 1
    assert oa["source_definition_id"] not in bundle["actor_template"]["action_ids"]  # only the reaction uses it
    assert any(choice["id"] == "opportunity_attack" for choice in bundle["reaction_plan"]["choices"])
    engine, me, foe = _duel(bundle, "OA")
    struck = _walk_away(engine, AN, me)
    assert len(struck) == 1 and not me.reaction_available
    # Disengage: no attack.
    engine2, me2, foe2 = _duel(bundle, "OA-DISENGAGE")
    foe2.turn_flags["disengaged"] = True
    assert _walk_away(engine2, AN, me2) == []


def test_reach_weapons_threaten_10_ft_and_the_plan_can_switch_it_off():
    bundle, _ = _weapons_of(["tianxia.mortal.weapon.qiang"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "OA-REACH", gap=2)
    assert engine._distance_actor_to_actor(me, foe) == 10 and len(_walk_away(engine, AN, me)) == 1
    off = compile_character({**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang"}]}}]},
                            actor_id=ACTOR, reaction_plan={"order": [], "off": ["opportunity_attack"]})
    engine2, me2, _ = _duel(off, "OA-OFF", gap=2)
    assert _walk_away(engine2, AN, me2) == []



def test_thrown_melee_weapons_strike_in_melee_and_shots_next_to_an_enemy_have_disadvantage():
    """Owner 2026-09-26 list items 2 and 3: a dagger is a melee weapon you can also throw; a ranged attack with an
    enemy within 5 ft has Disadvantage (2024)."""
    from tests.test_typed_executor import _intent

    bundle, rows = _weapons_of(["tianxia.mortal.weapon.bi_shou", "tianxia.mortal.weapon.gong_jian"], paths=("tianxia.path.body_refining",))
    melee, thrown = rows["bi_shou"], rows["bi_shou#thrown"]
    assert (melee["range_ft"], melee["parameters"]["typed"]["range_ft"]) == (5, None)
    assert (thrown["range_ft"], thrown["parameters"]["typed"]["range_ft"], thrown["parameters"]["typed"]["long_range_ft"]) == (60, 20, 60)
    assert "gong_jian#thrown" not in rows and rows["gong_jian"]["parameters"]["typed"]["range_ft"] == 150  # a bow only shoots
    engine, me, foe = _duel(bundle, "POINT-BLANK")  # the enemy stands next to you
    modes = {}
    for name in ("Gong Jian (Bow and Arrow) attack", "Bi Shou (Dagger) attack"):
        me.action_available, engine.state.current_actor_id = True, ACTOR
        # Free the bow's second hand; then recover the dagger before its attack.
        # The original fixture silently held a bow and dagger simultaneously.
        gear = "Drop tianxia.mortal.weapon.bi_shou" if name.startswith("Gong") else "Pick up Bi Shou (Dagger)"
        engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name == gear)))
        before = len(engine.events)
        engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith(name))))
        modes[name] = [e.payload.get("mode") for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED"][0]
    assert modes == {"Gong Jian (Bow and Arrow) attack": "DISADVANTAGE", "Bi Shou (Dagger) attack": "NORMAL"}


def test_unarmed_grapple_and_shove_replace_one_attack():
    """2024 Unarmed Strike options (owner 2026-09-26 list item 4): save vs 8 + STR + PB, a free hand for Grapple."""
    from combat import typed_executor

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",), features=["tianxia.path.body_refining.feature.extra_attack"])
    options = {row["display_name"]: row for row in bundle["action_catalog"]
               if ".unarmed." in row["source_definition_id"] or row["source_definition_id"].endswith(".natural.unarmed_strike")}
    assert set(options) == {"Unarmed Strike", "Shove: Push 5 ft", "Shove: Prone", "Grapple"}
    strike = options["Unarmed Strike"]["parameters"]["typed"]
    assert strike["weapon"]["fixed_damage"] == 5 and strike["weapon"]["damage_type"] == "BLUDGEONING"
    grapple = options["Grapple"]["parameters"]["typed"]
    assert grapple["numbers"]["save_dc"] == 8 + 6 + 4 and grapple["effects"][0]["max_size_larger"] == 1
    assert grapple["effects"][1]["type"] == "attack" and grapple["effects"][1]["count"] == 3  # the rest of Extra Attack
    shielded, _ = _weapons_of(["tianxia.mortal.weapon.dao", "tianxia.mortal.armor.shield"], paths=("tianxia.path.body_refining",))
    assert "Grapple" in {row["display_name"] for row in shielded["action_catalog"]}  # drop gear can free a hand
    from combat.ext.grapple_parts import hide_grapple_without_part
    shield_engine, shield_actor, _ = _duel(shielded, "SHIELD-GRAPPLE")
    shield_grapple = next(row for row in shield_engine.action_catalog.values() if row.display_name == "Grapple")
    assert hide_grapple_without_part(shield_engine, shield_actor, None, shield_grapple) is False
    engine, me, foe = _duel(bundle, "SHOVE")
    action = engine.action_catalog[options["Shove: Prone"]["source_definition_id"]]
    typed = {**action.parameters["typed"], "numbers": {**action.parameters["typed"]["numbers"], "save_dc": 99}}
    typed_executor.run_effects(typed_executor.Context(engine, me, action, None, typed, [foe], foe, {}), typed["effects"][:1])
    assert any(c.condition_id.endswith(".prone") for c in foe.conditions.values())


def _unarmed_catalog(*, spheres=(), talents=(), features=(), strength=4):
    """A weaponless CL 17 Body Refining fighter (Extra Attack: 4 attacks) with these spheres, talents and Path features."""
    abilities = [{"ability": a, "modifier": m, "score": 10 + 2 * m} for a, m in
                 (("STR", strength), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))]
    sheet = {**SHEET, "equipment": [], "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "abilities": json.dumps(abilities)},
             "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"],
                                  "path_feature_record_ids": ["tianxia.path.body_refining.feature.extra_attack", *features]},
             "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": list(talents)}}
    return {row["display_name"]: row for row in compile_character(sheet, actor_id=ACTOR)["action_catalog"]}


def test_the_basic_unarmed_strike_gives_way_only_to_a_better_free_unarmed_attack():
    """Hunt 53: every fighter's 2024 Unarmed Strike Damage option (1 + Strength modifier Bludgeoning, each attack of the Attack
    action) -- unless a natural weapon or the Iron Fist sphere already strikes harder. A paid special unarmed technique does
    not replace it (it is delivered with it); talents that change "your Unarmed Strike" apply to it; Grapple and Shove stay."""
    from combat.tabletop import engine_button_description

    grapple_shove = {"Grapple", "Shove: Push 5 ft", "Shove: Prone"}
    plain = _unarmed_catalog()
    strike = plain["Unarmed Strike"]
    typed = strike["parameters"]["typed"]
    assert strike["source_definition_id"].endswith(".natural.unarmed_strike") and strike["economy"] == "ACTION" and not strike["costs"]
    assert typed["effects"][0]["attack_kind"] == "unarmed" and typed["effects"][0]["count"] == 4
    assert typed["numbers"]["attack_bonus"] == 6 + 4 and strike["parameters"]["expected_damage"] == 4 * 5
    # The sealed roller deals fixed_damage + the die's modifier: Strength is counted once (it was 1 + twice Strength).
    assert typed["weapon"]["fixed_damage"] == 5 and typed["weapon"]["damage"]["modifier"] == 0
    assert plain["Opportunity Attack"]["parameters"]["typed"]["weapon"] == typed["weapon"]  # one shared payload
    assert plain["Grapple"]["parameters"]["typed"]["weapon"] == typed["weapon"]  # the rest of its Attack action
    assert grapple_shove <= set(plain)
    help_text = engine_button_description(strike)
    assert "Action: make 4 attacks" in help_text and "Each hit deals 5 bludgeoning" in help_text
    assert "within 5 feet" in help_text and "needs no weapon and costs no Qi, Stamina or other resource" in help_text
    assert _unarmed_catalog(strength=-2)["Unarmed Strike"]["parameters"]["typed"]["weapon"]["fixed_damage"] == 0  # never below 0

    natural = _unarmed_catalog(features=["tianxia.path.body_refining.feature.iron_fist"])  # Body Refining's Iron Fist: 1d8
    assert "Unarmed Strike" not in natural and "Iron Fist attack" in natural and grapple_shove <= set(natural)
    sphere = _unarmed_catalog(spheres=["tianxia.sphere.iron_fist"], talents=["TAL_IRON_FIST_IRON_FIST_TRAINING"])
    assert "Unarmed Strike" not in sphere and "Unarmed Strike (Iron Fist)" in sphere and grapple_shove <= set(sphere)
    assert not any(row["source_definition_id"].endswith(".natural.unarmed_strike") for catalog in (natural, sphere) for row in catalog.values())

    palm = _unarmed_catalog(spheres=["tianxia.sphere.void"], talents=["TAL_VOID_EMPTY_PALM_SCRIPTURE"])  # 2 CP, "make one unarmed strike"
    assert palm["Empty Palm Scripture"]["costs"] and "Unarmed Strike" in palm and grapple_shove <= set(palm)
    assert palm["Empty Palm Scripture"]["parameters"]["typed"]["weapon"] == palm["Unarmed Strike"]["parameters"]["typed"]["weapon"]
    nullifying = _unarmed_catalog(spheres=["tianxia.sphere.void"], talents=["TAL_VOID_NULLIFYING_STRIKE"])
    variants = [row for name, row in nullifying.items() if name.startswith("Unarmed Strike + Nullifying Strike")]
    assert variants and all(row["costs"] and ".natural.unarmed_strike+" in row["source_definition_id"] for row in variants)
    assert not nullifying["Unarmed Strike"]["costs"]
    assert "needs no weapon" not in engine_button_description(variants[0])


def test_conditional_unarmed_attacks_never_replace_the_free_strike(monkeypatch):
    """Existing target, turn and typed legality gates cannot stand in for an always-legal attack."""
    from combat import ext
    from combat.gate2_runtime_models import ActionDefinition

    ext.effects()
    restrictions = [({"requires_condition": "condition:typed.burning"}, {}),
                    ({"target_requires_condition": "condition:typed.burning"}, {}),
                    ({"blocked_by_turn_flag": "used"}, {}),
                    ({}, {"requires_inside": "zone"}),
                    ({}, {"target_requires_mark": "mark"})]
    for parameters, typed_gate in restrictions:
        def restricted(info):
            base = _unrestricted
            return [base.model_copy(update={"owner_id": info["actor_id"], "parameters": {
                **base.parameters, **parameters, "typed": {**base.parameters["typed"], **typed_gate}}})]

        # A genuinely better basic attack, then exactly one additional legality gate.
        row = _unarmed_catalog()["Unarmed Strike"]
        row["source_definition_id"] = "action:typed.test.natural.restricted"
        row["display_name"] = "Conditional strike"
        row["parameters"]["expected_damage"] = 100
        row["parameters"]["typed"]["weapon"]["fixed_damage"] = 25
        _unrestricted = ActionDefinition.model_validate(row)
        with monkeypatch.context() as patch:
            patch.setitem(ext._HOOKS, "compile_actions", [restricted])
            catalog = _unarmed_catalog()
        assert {"Conditional strike", "Unarmed Strike"} <= set(catalog), (parameters, typed_gate)
    with monkeypatch.context() as patch:
        patch.setitem(ext._HOOKS, "compile_actions", [lambda info: [_unrestricted.model_copy(update={"owner_id": info["actor_id"]})]])
        assert "Unarmed Strike" not in _unarmed_catalog()  # unrestricted equivalent suppresses the duplicate


def _two_fighters(seed, items_a, items_b):
    from combat.gate2_engine import Gate2Engine as Engine

    def sheet(items):
        return {**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
                "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]}}
    a_id, b_id = "actor:factory.a", "actor:factory.b"
    first = [compile_character(sheet(items_a), actor_id=a_id), compile_character(sheet(items_b), actor_id=b_id)]
    bundles = [compile_character(sheet(items), actor_id=aid, held_weapons=[row for other in first if other["actor_id"] != aid for row in other["weapons"]])
               for items, aid in ((items_a, a_id), (items_b, b_id))]
    engine = Engine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                    roster_setup={"primary_actor_ids": [a_id, b_id], "team_by_actor": {a_id: "team:a", b_id: "team:b"}})
    a, b = engine.state.actors[a_id], engine.state.actors[b_id]
    a.position, b.position = a.position.model_copy(update={"x": 3, "y": 6}), b.position.model_copy(update={"x": 4, "y": 6})
    return engine, a, b


def test_a_taken_weapon_can_be_used_and_disarming_the_taker_gets_it_back():
    """Owner 2026-09-26: an enemy may take your dropped weapon (and fight with it); disarming it knocks yours loose."""
    from combat import typed_executor
    from tests.test_typed_executor import _intent

    engine, a, b = _two_fighters("TAKE", ["tianxia.mortal.weapon.dao"], ["tianxia.mortal.weapon.bi_shou"])
    dao = next(x for x in a.action_ids if x.endswith(".weapon.dao"))
    engine._apply_condition(a, "condition:typed.disarmed", "src.disarm", b.entity_id, expires_on="UNTIL_REMOVED",
                            data={"disables_action": dao, "dropped_at": {"x": 3, "y": 6}})
    engine.state.current_actor_id = b.entity_id
    names = lambda who: {c.display_name for c in engine.legal_candidates() if c.actor_id == who.entity_id}  # noqa: E731
    assert not any(n.startswith("Dao (Saber / Broadsword) attack") for n in names(b))
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name == "Take a dropped weapon")))
    grip = next(c for c in a.conditions.values() if c.condition_id.endswith(".disarmed"))
    assert grip.data.get("held_by") == b.entity_id and "dropped_at" not in grip.data
    assert any(n.startswith("Dao (Saber / Broadsword) attack") for n in names(b))  # it fights with it
    engine.state.current_actor_id = a.entity_id
    assert "Pick up Dao (Saber / Broadsword)" not in names(a)
    action = engine.action_catalog[dao]
    ctx = typed_executor.Context(engine, a, action, None, action.parameters["typed"], [b], b, {})
    typed_executor.block_condition(ctx, {"type": "condition", "condition": "disarmed", "applies_to": "target"})
    grip = next(c for c in a.conditions.values() if c.condition_id.endswith(".disarmed"))
    assert grip.data.get("dropped_at") == b.position.model_dump(mode="json") and "held_by" not in grip.data
    assert "Pick up Dao (Saber / Broadsword)" in names(a)


def test_improvised_weapons_can_be_grabbed_swung_and_thrown():
    """Owner 2026-09-26: "grabbing a stick or a table leg or a brass vase or whatever is usable"."""
    from tests.test_typed_executor import _intent

    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",))
    engine, me, foe = _duel(bundle, "IMPROVISED")
    names = lambda: {c.display_name for c in engine.legal_candidates() if c.actor_id == ACTOR}  # noqa: E731
    assert "Improvised weapon attack" not in names() and "Grab an improvised weapon" in names()
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name == "Grab an improvised weapon")))
    assert {"Improvised weapon attack", "Improvised weapon thrown"} <= {n.split(" ->")[0] for n in names()} or \
        any(n.startswith("Improvised weapon attack") for n in names())
    assert "Grab an improvised weapon" not in names()  # holding one already (and the free interaction is used)
    swing = engine.action_catalog[f"action:typed.test.improvised.attack"] if "action:typed.test.improvised.attack" in engine.action_catalog else next(
        engine.action_catalog[x] for x in me.action_ids if x.endswith(".improvised.attack"))
    assert swing.parameters["typed"]["numbers"]["attack_bonus"] == 4  # no proficiency bonus without a grant
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith("Improvised weapon thrown"))))
    assert not any(c.condition_id.endswith(".improvised") for c in me.conditions.values())  # thrown: gone
    drunk, _ = _weapons_of(["tianxia.mortal.weapon.dao"], paths=("tianxia.path.body_refining",), extra_ids=["TAL_DRUNKEN_STYLE_ACCIDENTAL_WEAPON"])
    trained = next(r for r in drunk["action_catalog"] if r["source_definition_id"].endswith(".improvised.attack"))
    assert trained["parameters"]["typed"]["numbers"]["attack_bonus"] == 4 + 6



def test_masteries_need_a_weapon_sphere_and_specialists_cover_their_family():
    """Owner 2026-09-26: the Weapons Sphere grants mastery with every weapon, Sabers/Sword/Spear/Axes/Chains/Sniper/Monkey
    Style with their own weapons; without one, no mastery."""
    items = ["tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.qiang", "tianxia.mortal.weapon.fu"]
    mastery = lambda spheres: {k: r["parameters"]["typed"]["mastery"] for k, r in _weapons_of(  # noqa: E731
        items, paths=("tianxia.path.body_refining",), spheres=spheres)[1].items() if "#" not in k}
    assert mastery([]) == {"dao": "Sap", "qiang": None, "fu": None}  # the test sheet already has the Sabers Sphere
    assert mastery(["tianxia.sphere.axes"]) == {"dao": "Sap", "qiang": None, "fu": "Vex"}
    assert mastery(["tianxia.sphere.weapons"]) == {"dao": "Sap", "qiang": "Push", "fu": "Vex"}


def test_weapons_sphere_methods_fit_the_weapon_and_come_once_per_turn():
    from tests.test_typed_executor import _intent

    bundle, rows = _weapons_of(["tianxia.mortal.weapon.qiang"], paths=("tianxia.path.body_refining",), spheres=["tianxia.sphere.weapons"])
    methods = {k.split("#method_")[1] for k in rows if "#method_" in k}
    assert methods == {"guarding", "pressing", "measuring", "pinning", "sweeping"}  # Thrust, Guard, Pin tags; Reach; a spear (a polearm)
    pin = rows["qiang#method_pinning"]
    assert pin["parameters"]["requires_resource"] == {"resource:core.martial_focus": 1}
    _, plain = _weapons_of(["tianxia.mortal.weapon.qiang"], paths=("tianxia.path.body_refining",))
    assert not any("#method_" in k for k in plain)  # without the Weapons Sphere
    engine, me, foe = _duel(bundle, "METHOD", gap=2)
    measuring = rows["qiang#method_measuring"]["source_definition_id"]
    engine.action_catalog[measuring].parameters["typed"]["numbers"]["attack_bonus"] = 40
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.source_definition_id == measuring)))
    assert any(m.target_field == "speed_ft" and m.value == -10 for m in foe.modifiers.values())
    assert me.turn_flags.get("weapon_method")
    me.action_available = True
    assert not any("#method_" in c.source_definition_id for c in engine.legal_candidates() if c.actor_id == ACTOR)


def test_dual_wielding_balanced_defense_ambidexterity_and_paired_rhythm():
    from tests.test_typed_executor import _intent

    talents = ["TAL_DUAL_WIELDING_TWIN_WEAPON_TRAINING", "TAL_DUAL_WIELDING_AMBIDEXTERITY", "TAL_DUAL_WIELDING_PAIRED_RHYTHM"]
    pair = ["tianxia.mortal.weapon.duan_jian", "tianxia.mortal.weapon.duan_dao"]  # short sword + short saber, both Light
    base, _ = _weapons_of(pair, paths=("tianxia.path.body_refining",))
    bundle, rows = _weapons_of(pair, paths=("tianxia.path.body_refining",), extra_ids=talents)
    assert bundle["actor_template"]["armor_class"] == base["actor_template"]["armor_class"] + 1  # Balanced Defense
    shielded, _ = _weapons_of([*pair, "tianxia.mortal.armor.shield"], paths=("tianxia.path.body_refining",), extra_ids=talents)
    assert shielded["actor_template"]["armor_class"] == _weapons_of([*pair, "tianxia.mortal.armor.shield"], paths=("tianxia.path.body_refining",))[0]["actor_template"]["armor_class"]
    ambi = rows["duan_dao#offhand_ambidexterity"]
    assert ambi["economy"] == "NONE" and ambi["parameters"]["typed"]["effects"][0]["type"] == "spend_resource"
    engine, me, foe = _duel(bundle, "PAIRED-RHYTHM")
    me.resources["resource:core.martial_focus"] = 0
    for name in me.action_ids:
        if ".weapon." in name:
            engine.action_catalog[name].parameters["typed"]["numbers"]["attack_bonus"] = 40
    foe.maximum_hp = 999
    foe.current_hp = 999
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith("Duan Jian (Short Sword) attack"))))
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith("Duan Dao (Short Saber) off-hand attack"))))
    assert me.resources["resource:core.martial_focus"] == 1  # hit with both weapons: Martial Focus back


def test_dual_wielding_pair_talents_synchronous_following_and_tandem():
    """Owner 2026-09-26 ("go ahead with the dual wielding"): Synchronous Accuracy, Following Strike, Tandem Offensive."""
    from combat.gate2_runtime_content import LEE, LING
    from combat.typed_executor import _tandem_bonus, Context
    from tests.test_typed_executor import _intent

    talents = ["TAL_DUAL_WIELDING_SYNCHRONOUS_ACCURACY", "TAL_DUAL_WIELDING_FOLLOWING_STRIKE", "TAL_DUAL_WIELDING_TANDEM_OFFENSIVE"]
    pair = ["tianxia.mortal.weapon.duan_jian", "tianxia.mortal.weapon.duan_dao"]
    bundle, rows = _weapons_of(pair, paths=("tianxia.path.body_refining",), extra_ids=talents)
    sync, follow = rows["duan_dao#offhand_synchronous"], rows["duan_dao#following"]
    assert sync["parameters"]["typed"]["effects"][1]["count"] == 2 and sync["parameters"]["requires_turn_flags"] == ["pair:lead_missed"]
    assert follow["economy"] == "NONE" and follow["parameters"]["typed"]["weapon"]["damage"]["modifier"] <= 0  # no positive modifier

    # Synchronous Accuracy: offered only once a Lead attack of the Attack action has missed; two attacks, Focus spent.
    engine, me, foe = _duel(bundle, "PAIR-SYNC")
    me.resources["resource:core.martial_focus"] = 1
    foe.maximum_hp = foe.current_hp = 999
    for name in me.action_ids:
        if ".weapon." in name:
            engine.action_catalog[name].parameters["typed"]["numbers"]["attack_bonus"] = -40  # every attack misses
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.display_name.startswith("Duan Jian (Short Sword) attack"))))
    assert me.turn_flags.get("pair:lead_missed")
    offered = [c for c in engine.legal_candidates() if "Synchronous Accuracy" in c.display_name]
    assert offered and offered[0].source_definition_id.endswith("duan_dao#offhand_synchronous")
    before = sum(1 for e in engine.events if e.event_type == "ATTACK_ROLLED")
    engine.execute_intent(_intent(offered[0]))
    assert sum(1 for e in engine.events if e.event_type == "ATTACK_ROLLED") - before == 2
    assert me.resources["resource:core.martial_focus"] == 0
    assert not any("Synchronous Accuracy" in c.display_name for c in engine.legal_candidates())  # once per turn

    # Following Strike: after the Paired Strike, a free attack at another creature, while a Lead attack went at a third.
    engine = Gate2Engine(ROOT, match_seed="PAIR-FOLLOW", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN, LEE, LING], "team_by_actor": {ACTOR: "team:a", AN: "team:b", LEE: "team:b", LING: "team:b"}})
    me = engine.state.actors[ACTOR]
    me.position = me.position.model_copy(update={"x": 5, "y": 6})
    for foe_id, x, y in ((AN, 6, 6), (LEE, 4, 6), (LING, 5, 7)):
        engine.state.actors[foe_id].position = engine.state.actors[foe_id].position.model_copy(update={"x": x, "y": y})
        engine.state.actors[foe_id].maximum_hp = engine.state.actors[foe_id].current_hp = 999
    engine.state.current_actor_id = ACTOR
    me.turn_flags.update({"pair:lead_targets": [LING], "pair:paired_strike_done": True, "pair:paired_target": AN})
    targets = {c.target_ids[0] for c in engine.legal_candidates() if c.display_name.endswith("Following Strike")}
    assert targets == {LEE}  # not the Paired Strike's creature (AN), not the Lead's third creature (LING)
    me.turn_flags["pair:lead_targets"] = [AN]
    assert not any(c.display_name.endswith("Following Strike") for c in engine.legal_candidates())  # no third creature

    # Tandem Offensive: a Lead hit while holding Martial Focus lends the higher numeric bonus to the Answering Weapon.
    answer = engine.action_catalog[next(a for a in me.action_ids if a.endswith("duan_dao#offhand"))]
    ctx = Context(engine, me, answer, None, {**answer.parameters["typed"], "magic_bonus": 0}, [], None, {})
    me.turn_flags["pair:tandem_magic"] = 2
    assert _tandem_bonus(ctx) == 2
    assert _tandem_bonus(Context(engine, me, answer, None, {**answer.parameters["typed"], "magic_bonus": 3}, [], None, {})) == 0


def test_casting_hand_weapon_method_uses_the_cultivation_ability_with_the_conduit_weapon():
    """Owner 2026-09-26 ("go ahead with the ... weapons sphere casting"): Body Refiners use Constitution with their Conduit Weapon."""
    talents = ["tianxia.talent.weapons.qi_conduit_method", "TAL_WEAPONS_ARMAMENT_CONDUIT_INITIATE", "TAL_WEAPONS_CASTING_HAND_WEAPON_METHOD"]
    weapon = ["tianxia.mortal.weapon.jian"]
    _, plain = _weapons_of(weapon, paths=("tianxia.path.body_refining",), strength=10, spheres=["tianxia.sphere.weapons"])
    _, conduit = _weapons_of(weapon, paths=("tianxia.path.body_refining",), strength=10, extra_ids=talents, spheres=["tianxia.sphere.weapons"])
    _, half = _weapons_of(weapon, paths=("tianxia.path.body_refining",), strength=10, extra_ids=talents[:2], spheres=["tianxia.sphere.weapons"])
    typed = lambda rows: rows["jian"]["parameters"]["typed"]  # noqa: E731
    # Compilation preserves the ordinary packet; runtime consent applies the cultivation ability.
    assert typed(conduit) == typed(plain)
    casting = conduit["jian#conduit"]["parameters"]["typed"]
    assert casting["numbers"]["attack_bonus"] == typed(plain)["numbers"]["attack_bonus"]
    assert casting["weapon"]["damage"]["modifier"] == typed(plain)["weapon"]["damage"]["modifier"]
    assert casting["weapon"]["ability_modifier"] == typed(plain)["weapon"]["ability_modifier"]
    assert casting["weapons_casting_hand_explicit"] is True
    assert conduit["jian#conduit"]["parameters"]["variant_of"] == casting["weapons_casting_hand"]
    assert typed(half)["numbers"]["attack_bonus"] == typed(plain)["numbers"]["attack_bonus"]  # the Initiate alone changes nothing


def test_carrying_capacity_caps_speed_when_the_kit_is_too_heavy():
    """Owner 2026-09-26 ("we dont have weight limits on equipment ... we should probably do that as well"): 2024 capacity is
    15 x Strength; past it, Speed is 5 feet. Item Book weapons use their SRD equivalent's weight."""
    armour = ["tianxia.mortal.armor.full_lamellar_battle_dress", "tianxia.mortal.weapon.nu_gong"]  # 55 lb + 18 lb
    light, _ = _weapons_of(armour, paths=("tianxia.path.body_refining",), strength=16)  # capacity 240
    heavy, _ = _weapons_of(armour, paths=("tianxia.path.body_refining",), strength=4)   # capacity 60
    assert {key: light["carrying"][key] for key in ("weight_lb", "capacity_lb", "over", "unweighed")} == \
        {"weight_lb": "73", "capacity_lb": 240, "over": False, "unweighed": []}
    assert heavy["carrying"]["speed_ft"] > 5 and heavy["carrying"]["template_speed_ft"] == 5  # combat/carry.py lifts the cap once under
    assert heavy["carrying"]["over"] and heavy["carrying"]["capacity_lb"] == 60
    assert heavy["actor_template"]["speed_ft"] == 5 and light["actor_template"]["speed_ft"] > 5


def test_an_always_on_range_modifier_widens_the_typed_range_too():
    """Fight audit 2026-09-29: the action reached 70 feet but its typed range_ft stayed 60."""
    from tests.test_generic_reactions import REACTOR_SHEET, _mechanic

    authority = {"mechanics": {
        "BOLT": {**_mechanic("BOLT", "Bolt", "action", [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                                                         "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"]}]}]),
                 "range": {"kind": "feet", "feet": 60}},
        "LONG_REACH": _mechanic("LONG_REACH", "Long Reach", "passive", [], modifier={
            "targets": ["Bolt"], "scope": "named", "when": "use", "optional": False, "limit": "none", "effects": [], "add_range_ft": 10}),
    }}
    sheet = {**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["BOLT", "LONG_REACH"]}}
    bundle = compile_character(sheet, actor_id="actor:factory.range_mod", typed_authority=authority)
    bolt = next(a for a in bundle["action_catalog"] if a["display_name"] == "Bolt")
    assert bolt["range_ft"] == 70 and bolt["parameters"]["typed"]["range_ft"] == 70


def test_zone_material_uses_ability_identity_not_damage_interaction_text():
    from combat.factory_compiler import _zone_visual

    canopy = _zone_visual(
        {"name": "Canopy of Ten Thousand Leaves", "sphere_id": "verdant"},
        "A canopy of leaves and spirit-boughs spreads from the claim. Fire damage that affects the canopy may destroy sections.",
        {"verdant": "Verdant Growth"}, "light",
    )
    assert canopy["material"] == "vines"

    fire_canopy = _zone_visual(
        {"name": "Flame Canopy", "sphere_id": "fire"},
        "Cold damage destroys this canopy.", {"fire": "Fire"}, "light",
    )
    poison_cloud = _zone_visual(
        {"name": "Poison Cloud", "sphere_id": "poison"},
        "This cloud is immune to fire damage.", {"poison": "Poison"}, "heavy",
    )
    declared = _zone_visual(
        {"name": "Plain Field", "visual": {"material": "bamboo"}},
        "Cold damage affects creatures inside.", {}, None,
    )
    lightning_word = _zone_visual({"name": "Lightning Field"}, "", {}, None)
    assert fire_canopy["material"] == "fire"
    assert poison_cloud["material"] == "poison"
    assert declared["material"] == "bamboo"
    assert lightning_word["material"] == "lightning"


def test_zone_material_precedence_is_element_then_subpath_then_sphere():
    """Element outranks subpath, and subpath outranks Sphere, when the name gives no material word."""
    from combat.factory_compiler import _zone_visual

    spheres = {"tianxia.sphere.wind": "Wind"}
    element_first = _zone_visual({"name": "Plain Court", "element": "fire", "subpath_id": "tianxia.subpath.qi.ice_cultivator"},
                                 "", {}, None)
    subpath_first = _zone_visual({"name": "Plain Court", "subpath_id": "tianxia.subpath.qi.ice_cultivator",
                                  "sphere_id": "tianxia.sphere.wind"}, "", spheres, None)
    sphere_only = _zone_visual({"name": "Plain Court", "sphere_id": "tianxia.sphere.wind"}, "", spheres, None)
    assert element_first["material"] == "fire"
    assert subpath_first["material"] == "ice"
    assert sphere_only["material"] == "wind"


def test_identity_free_zone_never_takes_material_from_rules_text():
    """A zone with no recognized name or Sphere gets generic art, even when its rules text names damage types."""
    from combat.factory_compiler import _zone_visual

    text = "Fire damage affects this zone; lightning and cold damage destroy it."
    assert _zone_visual({"name": "Unlabeled Zone"}, text, {}, None)["material"] == "generic"
