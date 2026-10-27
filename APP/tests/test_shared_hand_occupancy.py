"""Shared equipment/Grapple eligibility across table commits and fresh loads."""
import pytest

from tests.hunt51_grapple_support import fight, grapple, on_turn, send, verify_reloaded
from tests.test_hunt51_grapple_persisted import reload, holds

W = "tianxia.mortal.weapon."
SHIELD = "tianxia.mortal.armor.shield"


def test_thunder_arrow_and_weapon_delivery_share_one_bow_after_table_reload(tmp_path):
    from combat.ext.hand_occupancy import weapon_grips
    user, service, table, match, ids = fight(
        tmp_path, "thunder-arrow-one-bow", equipment=(W + "gong_jian",),
        talents=("TAL_LIGHTNING_THUNDER_ARROW", "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY"))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    grips = weapon_grips(engine, engine.state.actors[ids[0]])
    assert len(grips) == 1 and next(iter(grips)).endswith('.weapon.gong_jian')
    send(table, match, lambda option: 'Thousand-Spark Volley' in option['label']
         and option.get('target_ids') == [ids[2]])
    verify_reloaded(user, service, match)
    engine = reload(user, service, match)
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 1


@pytest.mark.parametrize('legacy', [False, True])
def test_snipe_variants_share_one_bow_grip_after_table_reload(tmp_path, legacy):
    from combat.ext.hand_occupancy import weapon_grips
    user, service, table, match, ids = fight(
        tmp_path, "snipe-one-bow", equipment=(W + "gong_jian",),
        talents=("TAL_SNIPER_SNIPER_TRAINING", "TAL_SNIPER_MERIDIAN_GRAZING_SHOT"), legacy_delivery_metadata=legacy)
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    variants = [action for action in engine.action_catalog.values()
                if action.owner_id == ids[0] and action.parameters.get("typed", {}).get("maneuver") == "snipe"]
    field = 'maneuver_of' if legacy else 'weapon_source_id'
    assert variants and all(action.parameters["typed"][field].endswith(".weapon.gong_jian")
                            for action in variants)
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 1
    assert any("Meridian-Grazing Shot" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Stow Gong Jian" in option["label"])
    verify_reloaded(user, service, match)
    assert not any("Meridian-Grazing Shot" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Draw Gong Jian" in option["label"])
    verify_reloaded(user, service, match)
    assert any("Meridian-Grazing Shot" in option["label"] for option in options(table, match))


def options(table, match):
    return [{**option, "source_definition_id": group["source_definition_id"]}
            for group in table.state(match)["menu"]["actions"] for option in group["options"]]


@pytest.mark.parametrize('legacy', [False, True])
def test_barrage_follow_up_uses_the_same_bow_after_table_reload(tmp_path, legacy):
    from combat.ext.hand_occupancy import weapon_grips
    user, service, table, match, ids = fight(
        tmp_path, "barrage-one-bow", equipment=(W + "gong_jian",), talents=("TAL_BARRAGE_HAMMERING_SHOTS",),
        legacy_delivery_metadata=legacy)
    on_turn(table, match, ids[0])
    send(table, match, lambda option: option['label'].startswith('Barrage:') and option.get('target_ids') == [ids[2]])
    verify_reloaded(user, service, match)
    engine = reload(user, service, match)
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 1
    assert any(option['label'].startswith('Barrage follow-up:') for option in options(table, match))
    send(table, match, lambda option: option['label'].startswith('Barrage follow-up:') and option.get('target_ids') == [ids[2]])
    verify_reloaded(user, service, match)
    assert not any(option['label'].startswith('Barrage follow-up:') for option in options(table, match))


@pytest.mark.parametrize('legacy', [False, True])
def test_mixed_barrage_replacement_readies_its_own_weapon_after_reload(tmp_path, legacy):
    user, service, table, match, ids = fight(
        tmp_path, 'mixed-barrage-grips', equipment=(W + 'gong_jian', W + 'jian'),
        talents=('TAL_BARRAGE_MIXED_BARRAGE',), legacy_delivery_metadata=legacy, wielded=(W + 'jian',))
    on_turn(table, match, ids[0])
    # Start legal, then deliberately hold both objects to exercise Stow in play.
    send(table, match, lambda option: 'Draw Gong Jian' in option['label'])
    send(table, match, lambda option: 'Stow Jian' in option['label'])
    send(table, match, lambda option: option['label'].startswith('Barrage:')
         and 'Mixed Barrage' in option['label'] and option.get('target_ids') == [ids[2]])
    verify_reloaded(user, service, match)
    assert not any(option['label'].startswith('Mixed Barrage: Jian') for option in options(table, match))
    send(table, match, lambda option: 'Stow Gong Jian' in option['label'])
    send(table, match, lambda option: 'Draw Jian' in option['label'])
    verify_reloaded(user, service, match)
    assert any(option['label'].startswith('Mixed Barrage: Jian') for option in options(table, match))
    assert any(option['label'].startswith('Mixed Barrage: Unarmed Strike') for option in options(table, match))
    send(table, match, lambda option: option['label'].startswith('Mixed Barrage: Jian') and option.get('target_ids') == [ids[2]])
    verify_reloaded(user, service, match)
    assert not any(option['label'].startswith('Mixed Barrage:') for option in options(table, match))


def weapon_option(weapon, target):
    return lambda option: weapon in option.get("source_definition_id", "") and option.get("target_ids") == [target]


@pytest.mark.parametrize("legacy", [False, True])
def test_shield_staff_drop_pickup_and_physical_hold_share_hands(tmp_path, legacy):
    user, service, table, match, ids = fight(tmp_path, "shield-staff-" + str(legacy), six=True,
                                            equipment=(W + "qiang", SHIELD), legacy_weapon_metadata=legacy)
    on_turn(table, match, ids[0])
    # An overloaded grip is now an explicit in-play choice, never a default.
    send(table, match, lambda option: "Don Shield" in option["label"])
    send(table, match)
    on_turn(table, match, ids[0])
    assert not any(grapple(ids[3])(option) for option in options(table, match))
    assert not any(weapon_option("weapon.qiang", ids[3])(option) for option in options(table, match))
    send(table, match, lambda option: "Drop Shield" in option["label"])
    verify_reloaded(user, service, match)
    assert any(weapon_option("weapon.qiang", ids[3])(option) for option in options(table, match))
    # The second hand may release a two-handed grip to maintain a Grapple.
    send(table, match, grapple(ids[3]))
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 1
    assert not any(weapon_option("weapon.qiang", ids[3])(option) for option in options(table, match))
    assert not any("Pick up Shield" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Drop Qiang" in option["label"])
    verify_reloaded(user, service, match)
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[5]))
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 2
    assert not any(grapple(ids[4])(option) for option in options(table, match))
    send(table, match, lambda option: "Release grapple" in option["label"])
    verify_reloaded(user, service, match)
    send(table, match, lambda option: "Pick up Shield" in option["label"])
    engine = reload(user, service, match)
    from combat.ext.hand_occupancy import free_hands
    assert len(free_hands(engine, engine.state.actors[ids[0]])) == 1


def test_shield_alone_leaves_one_hand_for_grapple(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "shield-free-hand", six=True, equipment=(SHIELD,))
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[3]))
    assert len(holds(reload(user, service, match), ids[0])) == 1
    send(table, match)
    on_turn(table, match, ids[0])
    assert not any(grapple(ids[5])(option) for option in options(table, match))


def test_owner_given_shield_preserves_one_handed_versatile_attack(tmp_path):
    from factory_authoring.starting_kits import item_definition
    given = [{"kind": "armour", "equipped": False,
              "record": {"name": "Gift Shield", "chassis": item_definition(SHIELD)}}]
    user, service, table, match, ids = fight(tmp_path, "given-shield", equipment=(W + "jian",), owner_items=given)
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    action = next(action for action in engine.action_catalog.values()
                  if action.owner_id == ids[0] and action.source_definition_id.endswith("weapon.jian"))
    assert action.parameters["typed"]["weapon"]["damage"]["sides"] == 8
    send(table, match, weapon_option("weapon.jian", ids[2]))
    verify_reloaded(user, service, match)


def test_weapon_delivered_laughing_trip_cannot_bypass_shield(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "delivery-shield", equipment=(W + "gun", SHIELD),
                                            talents=("TAL_MONKEY_STYLE_LAUGHING_TRIP",))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    actions = [action for action in engine.action_catalog.values() if action.owner_id == ids[0]
               and "Laughing Trip" in action.display_name]
    assert actions and all(action.parameters["typed"].get("delivered_by") for action in actions)
    send(table, match, lambda option: "Don Shield" in option["label"])
    send(table, match)
    on_turn(table, match, ids[0])
    assert not any("Laughing Trip" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Drop Shield" in option["label"])
    assert any("Laughing Trip" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Laughing Trip" in option["label"] and option.get("target_ids") == [ids[2]])
    verify_reloaded(user, service, match)


def test_light_offhand_needs_two_weapon_grips_even_after_lead_drop(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "light-pair", equipment=(W + "bi_shou", W + "fu"))
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Bi Shou" in option["label"] and "attack" in option["label"]
         and "off-hand" not in option["label"] and option.get("target_ids") == [ids[2]])
    assert any("off-hand" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Drop Bi Shou" in option["label"])
    verify_reloaded(user, service, match)
    assert not any("off-hand" in option["label"] for option in options(table, match))


def test_stowing_frees_a_hand_and_spare_inventory_is_not_held(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "stow-three", six=True,
                                            equipment=(W + "bi_shou", W + "fu", W + "qiang"),
                                            wielded=(W + "bi_shou", W + "fu"))
    on_turn(table, match, ids[0])
    from combat.ext.hand_occupancy import weapon_grips, free_hands
    engine = reload(user, service, match)
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 2
    assert not any(grapple(ids[3])(option) for option in options(table, match))
    send(table, match, lambda option: "Stow Bi Shou" in option.get("label", ""))
    engine = reload(user, service, match)
    assert len(free_hands(engine, engine.state.actors[ids[0]])) == 1
    send(table, match, grapple(ids[3]))
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 1
    assert not any("Draw Bi Shou" in option["label"] for option in options(table, match))
    send(table, match, lambda option: "Release grapple" in option.get("label", ""))
    send(table, match, lambda option: "Draw Bi Shou" in option.get("label", ""))
    engine = reload(user, service, match)
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 2
    assert not free_hands(engine, engine.state.actors[ids[0]])


def test_versatile_uses_one_handed_die_while_maintaining_a_hold(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "versatile-hold-hit", equipment=(W + "jian",))
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[2]))
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, weapon_option("weapon.jian", ids[2]))
    engine = reload(user, service, match)
    events = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"
              and event.source_definition_id.endswith("weapon.jian")]
    assert events and all("d8" in event.payload["expression"] for event in events)
    assert len(holds(engine, ids[0])) == 1


def test_grapple_extra_attacks_cannot_bypass_two_handed_grip(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "grapple-followups", equipment=(W + "qiang",),
                                            talents=("tianxia.path.body_refining.feature.extra_attack",))
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[2]))
    engine = reload(user, service, match)
    assert len(holds(engine, ids[0])) == 1
    action = next(action for action in engine.action_catalog.values()
                  if action.owner_id == ids[0] and action.display_name == "Grapple")
    assert any(effect.get("type") == "attack" for effect in action.parameters["typed"]["effects"])
    assert not any(event.event_type == "ATTACK_ROLLED" and event.source_definition_id == action.source_definition_id
                   for event in engine.events)


def test_grapple_followup_uses_one_handed_versatile_die_after_reload(tmp_path):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    user, service, table, match, ids = fight(tmp_path, 'grapple-versatile-followup', equipment=(W + 'jian',),
                                            talents=('tianxia.path.body_refining.feature.extra_attack',))
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[2]))
    loaded = CombatService(ROOT, user)._load_session(match)
    engine = loaded.engine
    assert len(holds(engine, ids[0])) == 1
    action = next(row for row in engine.action_catalog.values()
                  if row.owner_id == ids[0] and row.display_name == 'Grapple')
    rolls = [event for event in engine.events if event.event_type == 'DAMAGE_ROLLED'
             and event.source_definition_id == action.source_definition_id]
    # Jian is 1d8 in one hand, Versatile 1d10 in two; the other hand holds the Grapple.
    assert rolls and all('d8' in event.payload['expression'] for event in rolls)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_binding_weapon_still_occupies_its_hand_after_reload(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "binding-occupied", six=True,
                                            equipment=(W + "bi_shou",), talents=("TAL_FENCING_BIND_WEAPON",))
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Disarm" in option["label"] and option.get("target_ids") == [ids[3]],
         reaction_pick=lambda choice: ["bind"] if any(row["id"] == "bind" for row in choice["options"])
         else [choice["options"][0]["id"]])
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    assert any(row.condition_id == "condition:typed.needle_binding" for row in actor.conditions.values())
    from combat.ext.hand_occupancy import free_hands, weapon_grips
    assert len(weapon_grips(engine, actor)) == len(free_hands(engine, actor)) == 1
    assert not any("Bi Shou" in option["label"] and "attack" in option["label"] for option in options(table, match))
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[5]))
    engine = reload(user, service, match)
    assert not free_hands(engine, engine.state.actors[ids[0]])
    send(table, match)
    on_turn(table, match, ids[0])
    assert not any(grapple(ids[4])(option) for option in options(table, match))
