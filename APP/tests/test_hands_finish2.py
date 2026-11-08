"""Review regressions through real table actions and persisted mechanical replay."""
import json
from pathlib import Path

from tests.hunt51_grapple_support import fight, grapple, on_turn, send, verify_reloaded
from tests.test_hunt51_grapple_persisted import reload
from tests.test_shared_hand_occupancy import W, SHIELD, options, weapon_option


def test_actual_672ec109_catalog_continues_without_managed_grips(tmp_path):
    # Produced by generate_legacy.py against the actual archived baseline, not
    # today's compiler with fields removed. No locked bundles are rewritten.
    bundle = json.loads((Path(__file__).parent / "fixtures/sol48_672ec109_bundle.json").read_text())
    assert not any(row["parameters"].get("equipment_grip") for row in bundle["action_catalog"])
    assert not any("requires_hands" in row["parameters"] for row in bundle["action_catalog"])
    user, service, table, match, ids = fight(tmp_path, "historical-catalog", saved_bundle=bundle)
    on_turn(table, match, ids[0])
    original = reload(user, service, match).action_catalog
    for weapon in ("qiang", "gun"):
        send(table, match, weapon_option("weapon." + weapon, ids[2]))
        verify_reloaded(user, service, match)
        send(table, match, lambda option, name=weapon.title(): "Drop " + name in option["label"])
        send(table, match)
        on_turn(table, match, ids[0])
    send(table, match, grapple(ids[2]))
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, weapon_option("weapon.jian", ids[2]))
    verify_reloaded(user, service, match)
    engine = reload(user, service, match)
    assert engine.action_catalog == original
    damage = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
              and e.source_definition_id.endswith("weapon.jian")]
    assert damage and all("d10" in e.payload["expression"] for e in damage)


def test_broken_weapon_can_be_stowed_without_repair_then_draw_and_grapple(tmp_path):
    user, service, table, match, ids = fight(
        tmp_path, "broken-release", equipment=(W + "bi_shou", W + "fu", W + "qiang"),
        talents=("TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_UNBOUND_TRACE"))
    for _ in range(3):
        on_turn(table, match, ids[0])
        send(table, match, lambda o: "Unbound Trace" in o["label"] and o.get("target_ids") == [ids[2]],
             reaction_pick=lambda choice: [next(row["id"] for row in choice["options"]
                                              if ":crack:" in row["id"] and row["id"].endswith("weapon.bi_shou"))]
             if any(":crack:" in row["id"] for row in choice["options"]) else [choice["options"][0]["id"]])
        verify_reloaded(user, service, match)
        send(table, match)
    on_turn(table, match, ids[0])
    from combat.ext.hand_occupancy import free_hands
    from combat.ext.weapon_hits import available_weapons
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    assert any("broken" in c.condition_id and c.data.get("disables_action", "").endswith("weapon.bi_shou")
               for c in actor.conditions.values())
    assert not free_hands(engine, actor)
    send(table, match, lambda o: "Stow Bi Shou" in o["label"])
    verify_reloaded(user, service, match)
    assert not any("Draw Bi Shou" in o["label"] for o in options(table, match))
    send(table, match, lambda o: "Draw Qiang" in o["label"])
    send(table, match, lambda o: "Stow Fu" in o["label"])
    send(table, match, grapple(ids[2]))
    verify_reloaded(user, service, match)
    engine = reload(user, service, match)
    assert not any(key.endswith("weapon.bi_shou") for key in available_weapons(engine, engine.state.actors[ids[0]]))
    assert any("broken" in c.condition_id for c in engine.state.actors[ids[0]].conditions.values())


def test_paired_recovery_needs_both_hands_and_preserves_draw_choice(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "paired-recovery",
                                            equipment=(W + "emei_ci", SHIELD))
    on_turn(table, match, ids[0])
    send(table, match, lambda o: "Drop Shield" in o["label"])
    send(table, match, lambda o: "Draw Emei" in o["label"])
    send(table, match, lambda o: "Drop Emei" in o["label"])
    send(table, match, lambda o: "Pick up Shield" in o["label"])
    verify_reloaded(user, service, match)
    assert not any("Pick up Emei" in o["label"] for o in options(table, match))
    send(table, match, lambda o: "Drop Shield" in o["label"])
    send(table, match, lambda o: "Pick up Emei" in o["label"])
    verify_reloaded(user, service, match)
    assert not any("Pick up Shield" in o["label"] for o in options(table, match))
    send(table, match, weapon_option("weapon.emei_ci", ids[2]))
    verify_reloaded(user, service, match)


def test_paired_taking_by_initially_unarmed_actor_needs_both_hands(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "paired-taking", heavenquake=True,
                                            equipment=(W + "emei_ci",), actor_scores={"actor:factory.luna38-a": 10},
                                            share_weapons=True)
    on_turn(table, match, ids[0])
    send(table, match, lambda o: "Drop Emei" in o["label"])
    send(table, match)
    on_turn(table, match, ids[3])
    # Ordinary unarmed fighters also opt into the fresh catalog's hand policy.
    send(table, match, grapple(ids[0]))
    verify_reloaded(user, service, match)
    from tests.test_hunt51_grapple_persisted import holds
    assert len(holds(reload(user, service, match), ids[3])) == 1
    assert not any("Take a dropped weapon" in o["label"] for o in options(table, match))
    send(table, match, lambda o: "Release grapple" in o["label"])
    send(table, match, lambda o: "Take a dropped weapon" in o["label"])
    verify_reloaded(user, service, match)
    from combat.ext.hand_occupancy import weapon_grips, free_hands
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[3]]
    assert list(weapon_grips(engine, actor).values()) == [2]
    assert not free_hands(engine, actor)
    assert not any(grapple(ids[0])(o) for o in options(table, match))


def test_ordinary_paired_attack_rejects_persisted_overflow(tmp_path, monkeypatch):
    from combat import ext

    def fixture_occupant(engine, actor):
        # A test owner supplies an extra occupant through the documented seam
        # only while its fixture condition is active. No production ability is invented.
        if actor.entity_id.endswith("luna38-a") and any(
                c.condition_id == "condition:typed.restrained" for c in actor.conditions.values()):
            return {"occupied:overflow:fixture": "fixture:occupied"}
        return None

    monkeypatch.setitem(ext._HOOKS, "hand_occupants", [*ext._HOOKS.get("hand_occupants", []), fixture_occupant])
    user, service, table, match, ids = fight(tmp_path, "paired-overflow", equipment=(W + "emei_ci",),
                                            fixture_conditions=("restrained",))
    on_turn(table, match, ids[0])
    assert any(weapon_option("weapon.emei_ci", ids[2])(o) for o in options(table, match))
    send(table, match)
    on_turn(table, match, ids[3])
    send(table, match, lambda o: "Fixture: Restrained" in o["label"] and o.get("target_ids") == [ids[0]])
    verify_reloaded(user, service, match)
    send(table, match)
    on_turn(table, match, ids[0])
    assert not any(weapon_option("weapon.emei_ci", ids[2])(o) for o in options(table, match))
    engine = reload(user, service, match)
    from combat.ext.hand_occupancy import weapon_allowed
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ids[0]
                  and a.source_definition_id.endswith("weapon.emei_ci"))
    assert weapon_allowed(engine, engine.state.actors[ids[0]], action) is False
