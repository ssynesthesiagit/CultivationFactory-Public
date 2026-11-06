"""Equipment is actor state, not status effects; exercise the real table and replay."""
import subprocess

from combat import carry
from combat.ext.hand_occupancy import occupancy, weapon_grips
from tests.hunt51_grapple_support import fight, on_turn, send, verify_reloaded
from tests.test_hunt51_grapple_persisted import reload
from tests.test_shared_hand_occupancy import W, weapon_option
from tests.h1_support import ROOT


def test_draw_stow_replaces_actor_state_with_one_history_line_and_no_status(tmp_path):
    user, service, table, match, ids = fight(
        tmp_path, "readiness-state", equipment=(W + "bi_shou", W + "fu", "tianxia.mortal.armor.lacquered_lamellar"),
        wielded=(W + "bi_shou",))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    weapon = next(key for key in actor.equipment_readiness if key.endswith(".weapon.bi_shou"))
    assert actor.equipment_readiness[weapon] == 1
    starts = [e for e in engine.events if e.event_type == "EQUIPMENT_READINESS_SET"]
    assert len(starts) == 1 and starts[0].payload["starting_equipment"] == 1

    for verb, held in (("Stow", 0), ("Draw", 1)):
        previous = len(engine.events)
        send(table, match, lambda option: (verb + " Bi Shou") in option.get("label", ""))
        verify_reloaded(user, service, match)
        engine = reload(user, service, match)
        actor = engine.state.actors[ids[0]]
        name = engine.action_catalog[weapon].display_name.removesuffix(" attack")
        events = engine.events[previous:]
        changed = [e for e in events if e.event_type == "EQUIPMENT_READINESS_SET"]
        assert len(changed) == 1
        assert changed[0].payload["readiness"] == actor.equipment_readiness
        assert actor.equipment_readiness[weapon] == held
        assert (weapon in weapon_grips(engine, actor)) == bool(held)
        assert not any("equipment_grip" in e.payload.get("condition_id", "") for e in events)
        assert not any("equipment_grip" in c.condition_id for c in actor.conditions.values())
        state = table.state(match)
        offered = [option for group in state["menu"]["actions"] for option in group["options"]
                   if group["source_definition_id"] == weapon]
        assert bool(offered) == bool(held)
        fighter = next(a for a in state["presentation"]["actors"] if a["entity_id"] == ids[0])
        grip_rows = {row.parameters["equipment_grip"]["held"]: row
                     for row in engine.action_catalog.values()
                     if row.owner_id == ids[0]
                     and row.parameters.get("equipment_grip", {}).get("weapon") == weapon}
        gear_choices = {group["source_definition_id"] for group in state["menu"]["actions"]
                        if group["source_definition_id"] in {row.source_definition_id for row in grip_rows.values()}}
        expected_grip = grip_rows[0 if held else 1]
        assert gear_choices == {expected_grip.source_definition_id}
        equipment_state = fighter["equipment_state"]
        held_text = " ".join((equipment_state["left_hand"], equipment_state["right_hand"]))
        assert (name in held_text) is bool(held)
        assert equipment_state["worn"] == ["Lacquered Lamellar"]
        assert not any("equipment_grip" in row["condition_id"] for row in fighter["conditions"])
        log = changed[0].payload["log"]
        assert log == actor.display_name + (" draws " if held else " stows ") + name + "."
    send(table, match)
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    assert engine.state.actors[ids[0]].equipment_readiness[weapon] == 1


def test_unsealed_default_grip_lazy_sheet_and_commit(tmp_path):
    from tests.test_starting_loadout import owner, bundle
    compiled = bundle(owner([W + "bi_shou"]))
    compiled["carrying"].pop("starting_loadout")
    user, service, table, match, ids = fight(tmp_path, "default-grip", saved_bundle=compiled)
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    assert not actor.equipment_readiness
    weapon = next(iter(weapon_grips(engine, actor)))
    rows = {a.parameters["equipment_grip"]["held"]: a.source_definition_id
            for a in engine.action_catalog.values() if a.owner_id == ids[0]
            and a.parameters.get("equipment_grip", {}).get("weapon") == weapon}

    def check(held):
        # The sheet receives menu headers and these source-wide refusals.
        state = table.state(match, lazy=True)
        reasons = state["unavailable_reasons"]
        assert f"act:{rows[held]}" in reasons
        assert f"act:{rows[1 - held]}" not in reasons
        fighter = next(a for a in state["presentation"]["actors"] if a["entity_id"] == ids[0])
        hands = " ".join((fighter["equipment_state"]["left_hand"], fighter["equipment_state"]["right_hand"]))
        assert ("Bi Shou" in hands) is bool(held)

    check(1)
    send(table, match, lambda option: option["source_definition_id"] == rows[0])
    verify_reloaded(user, service, match)
    check(0)
    send(table, match, lambda option: option["source_definition_id"] == rows[1])
    verify_reloaded(user, service, match)
    check(1)


def test_thrown_copies_leave_only_the_thrown_copy_unavailable_after_reload(tmp_path):
    from tests.test_starting_loadout import owner, bundle
    doc = owner([W + "fu"])
    doc["equipment"][0]["starting_kit"]["items"][0]["quantity"] = 3
    user, service, table, match, ids = fight(tmp_path, "readiness-thrown", saved_bundle=bundle(doc))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    items = carry.carrying_of(engine, ids[0])["items"]
    axes = [item for item in items if item["item_id"] == W + "fu"]
    assert len(axes) == 3
    ready = weapon_grips(engine, engine.state.actors[ids[0]])
    thrown = next(iter(ready))
    send(table, match, weapon_option(thrown + "#thrown", ids[2]))
    verify_reloaded(user, service, match)
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    lost = [item["weapon_action"] for item in axes if not carry.holds(engine, actor, item["key"])]
    assert lost == [thrown]
    assert thrown not in weapon_grips(engine, actor)
    assert all(actor.equipment_readiness[item["weapon_action"]] == 0
               for item in axes if item["weapon_action"] not in ready)


def test_explicit_weapon_hand_is_actor_state_and_replays(tmp_path):
    from combat.ext.equipment_hands import set_weapon_readiness
    from combat.gate3_reducer import Gate3EventReducer
    user, service, table, match, ids = fight(tmp_path, "readiness-hand", equipment=(W + "jian",))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    weapon = next(iter(weapon_grips(engine, actor)))
    before = engine.state.model_copy(deep=True)
    set_weapon_readiness(engine, actor, weapon, True, source="test:placement",
                         source_actor_id=ids[0], hand="hand:right")
    assert occupancy(engine, actor)["hand:right"] == ("weapon:" + weapon,)
    assert "hand:left" not in occupancy(engine, actor)
    # The same event reducer used by persisted fights preserves the named hand.
    Gate3EventReducer().apply_event(before, engine.events[-1])
    assert before.actors[ids[0]].equipment_readiness == actor.equipment_readiness


def test_fighter_sheet_status_node_renderer():
    subprocess.run(["node", "--test", "tests/sheet_status_tooltips_dom.test.mjs"],
                   cwd=ROOT, check=True)
