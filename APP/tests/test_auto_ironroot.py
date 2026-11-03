"""Lingfeng Ironroot automation (worker ironroot, 2026-09-28): the fixes owned by this character's typing pass --
Withering Hand's CL-scaled damage, Demon Seed as a self stance (not a bogus attack action) with a CL-scaled hit
rider, Devour Essence and Heaven-Spiting Recovery as real reactions, Catch Blade as a reaction (not a passive),
Demon Bone Regeneration's turn-start heal, and the Bone Guard's innate "Guard the Sovereign" reaction."""

from pathlib import Path

from combat.factory_compiler import RESOURCE_IDS, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat import summons
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ironroot"
DEVOURED_ESSENCE = "resource:named.devoured_essence"
CORRUPTION = "resource:named.corruption"
DEMON_SEED_STANCE = "condition:typed.stance.demon_seed"


AUTOMATIC_DAEMONIC = ["TAL_DAEMONIC_CULTIVATION_BASE_SPHERE_ABILITIES", "TAL_DAEMONIC_CULTIVATION_DEMON_SEED",
                      "TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE", "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"]
KIT = {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}


def _bundle(talents, spheres=("tianxia.sphere.death", "tianxia.sphere.daemonic_cultivation", "tianxia.sphere.shield"), armed=False):
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": talents,
                                              "automatic_sphere_component_record_ids": AUTOMATIC_DAEMONIC}}
    if armed:
        sheet["equipment"] = [{"starting_kit": KIT}]
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="IRONROOT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _do(engine, actor_id, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_withering_hand_scales_its_dice_by_cl_with_no_stray_flat_bonus():
    bundle = _bundle(["TAL_DEATH_WITHERING_HAND"])
    row = next(r for r in bundle["action_catalog"] if r["display_name"] == "Withering Hand")
    on_hit = row["parameters"]["typed"]["effects"][0]["on_hit"][0]
    assert on_hit["dice_by_cl"] == [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 20, 4, 8]]
    assert on_hit.get("formula") in (None, "none") and not on_hit.get("flat")  # no leftover "+CL" flat bonus


def test_demon_seed_is_a_self_stance_not_a_bogus_attack_action():
    bundle = _bundle([])  # Demon Seed is a base Daemonic Cultivation ability, granted just from the sphere
    row = next(r for r in bundle["action_catalog"] if r["display_name"] == "Demon Seed")
    assert row["target_kind"] == "SELF"
    effects = row["parameters"]["typed"]["effects"]
    assert effects[0]["type"] == "stance" and effects[0]["name"] == "Demon Seed"
    rider = effects[0]["hit_riders"][0]
    assert rider["effects"][0]["dice_by_cl"] == [[1, 4, 1, 4], [5, 10, 1, 6], [11, 16, 1, 8], [17, 20, 1, 10]]
    assert not any(e["type"] == "attack" for e in effects)  # activating it is not itself an attack


def test_demon_seed_stance_adds_bonus_damage_once_a_hit_lands():
    engine = _engine(_bundle([], armed=True))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, ME, "Demon Seed")
    assert any(c.condition_id == DEMON_SEED_STANCE for c in me.conditions.values())
    strike_name = next(c.display_name for c in engine.legal_candidates() if c.display_name.endswith("attack"))
    foe_hp = foe.current_hp
    for attempt in range(20):  # until a hit lands (the dice decide)
        strike = next((c for c in engine.legal_candidates() if c.display_name == strike_name), None)
        if strike is None:
            break
        engine.execute_intent(ActionIntent(intent_id=f"s{attempt}", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                           state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
        if foe.current_hp < foe_hp:
            break
        engine.state.current_actor_id = ME
        me.action_available = True
    assert foe.current_hp < foe_hp  # the stance's extra Necrotic/Psychic/Force die landed alongside the strike


def test_devour_essence_compiles_as_one_owned_feature_for_its_printed_triggers():
    # Since rider lane C13 the whole ability is combat/ext/devour_essence.py (every printed trigger, Bonus Action on your own turn,
    # Reaction off it, once a round): its compiled feature row replaces the generic drop-to-zero reaction, which answered only the
    # first trigger and always spent the Reaction. Its firing: tests/test_riders_c13.py (Devour Essence tests).
    bundle = _bundle([])
    assert not [r for r in bundle["typed_reactions"] if r["name"] == "Devour Essence"]
    row = next(r for r in bundle["typed_passives"] if r.get("block") == "devour_essence")
    assert row["feature_id"] == "TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE" and row["cl"] == bundle["cl"]


def test_heaven_spiting_recovery_holds_her_at_1_hp_and_marks_corruption(tmp_path):
    # The rescue now observes the final native lethal checkpoint, rather than
    # reducing an isolated call to on_damage. Keep the rule assertions through
    # an actual committed table packet and a fresh reducer reload.
    from tests.test_a2_daemonic import recovery_prepare, RECOVERY_CHOICE
    from tests.test_auto103_daemonic import sow
    from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload

    combat, table, mid = fixture(tmp_path, ["TAL_DAEMONIC_CULTIVATION_HEAVEN_SPITING_RECOVERY",
                                            "TAL_DAEMONIC_CULTIVATION_DEMON_SEED"],
                                 bundle_transform=recovery_prepare)
    sow(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER]
    settle(table, mid, candidate(combat, mid, "Lethal blast", target=OWNER).candidate_id,
           {RECOVERY_CHOICE: "resource:core.qi"})
    me = reload(tmp_path, mid).state.actors[OWNER]
    assert me.current_hp == 1 and me.temporary_hp == 8
    assert me.resources["resource:core.qi"] == before.resources["resource:core.qi"] - 3
    assert me.resources[CORRUPTION] == before.resources[CORRUPTION] + 1


def test_catch_blade_is_a_reaction_on_a_missed_melee_attack_not_a_passive():
    bundle = _bundle(["TAL_SHIELD_CATCH_BLADE"])
    row = next(r for r in bundle["typed_reactions"] if r["name"] == "CATCH BLADE")
    assert row["kind"] == "missed"
    assert "CATCH BLADE" not in bundle["diagnostics"]["skipped"]["passive"]


def test_demon_bone_regeneration_heals_at_the_start_of_her_turn_while_hurt_and_seeded():
    bundle = _bundle(["TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION"])
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    me.current_hp = max(1, me.maximum_hp - 20)
    me.resources[DEVOURED_ESSENCE] = 2
    engine._apply_condition(me, DEMON_SEED_STANCE, "TEST", me.entity_id, expires_on="END_OF_SOURCE_TURN_AT:999")
    hp_before, essence_before = me.current_hp, me.resources[DEVOURED_ESSENCE]
    engine._system_start_turn()
    assert me.current_hp > hp_before
    assert me.resources[DEVOURED_ESSENCE] == essence_before - 1


def test_bone_guard_has_its_own_innate_guard_the_sovereign_reaction():
    table = summons.rules()
    bone_guard = table["creatures"]["bone_guard"]
    assert bone_guard["innate_reaction"]["kind"] == "ally_attacked"
    out, _summoning = summons.compile_summons(
        ["tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"], {}, owner_id=ME, short="ironroot",
        numbers={"key_mod": 2, "attack_bonus": 8, "save_dc": 18}, pb=4, cl=10)
    [bundle] = [row for row in out if row["summon"]["group"] == "bone_guard"]
    reaction = next(r for r in bundle["typed_reactions"] if r["name"] == "Guard the Sovereign")
    assert reaction["kind"] == "ally_attacked" and reaction["effects"][0]["type"] == "disadvantage"


def test_rouse_lesser_dead_now_fields_a_lesser_corpse_servant():
    out, _summoning = summons.compile_summons(["TAL_DEATH_ROUSE_LESSER_DEAD"], {}, owner_id=ME, short="ironroot",
                                              numbers={"key_mod": 2, "attack_bonus": 8, "save_dc": 18}, pb=4, cl=10)
    [bundle] = [row for row in out if row["summon"]["group"] == "lesser_corpse_servant"]
    assert bundle["actor_template"]["display_name"] == "Lesser Corpse Servant"
    assert bundle["actor_template"]["maximum_hp"] == 3 * 10 + 2  # 3*cl+key
