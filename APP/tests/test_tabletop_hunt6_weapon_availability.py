"""Possession regressions at the table boundary, including persisted recovery.

Hold/accepted-intent fixtures event a disarm or trigger off-turn effects; actual
selection, pick-up, attacks, commit, reload and replay use the table service.
"""
import copy
import hashlib

import pytest

from tests.test_auto_martial import SPEAR_KIT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, HOLD, table_fight, on_hold, answer_action
from tests.test_tabletop_hunt6_fixup import INFUSION, THRUST, hit_script, reload, infusion_damage

STAFF = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.gun", "name": "Gun (Staff)", "quantity": 1}]}}
TWO = {"starting_kit": {"items": [*SPEAR_KIT["starting_kit"]["items"],
    {"item_id": "tianxia.mortal.weapon.mao", "name": "Mao (Long Spear)", "quantity": 1}]}}
QIANG = f"action:typed.{hashlib.sha256(LEFT.encode()).hexdigest()[:10]}.weapon.qiang"
MAO = QIANG.removesuffix("qiang") + "mao"
ALLY_QIANG = f"action:typed.{hashlib.sha256(ALLY.encode()).hexdigest()[:10]}.weapon.qiang"


def spears(session):
    from combat.ext.weapon_hits import available_weapons
    return available_weapons(session.engine, session.engine.state.actors[LEFT], ("spear",))


def offered(table, mid):
    return any(INFUSION in g["source_definition_id"] for g in table.state(mid)["menu"]["actions"])


def next_left(table, mid):
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"


def drop(engine, owner, weapon):
    actor = engine.state.actors[owner]
    engine._apply_condition(actor, "condition:typed.disarmed", HOLD, LEFT,
        expires_on="UNTIL_REMOVED", data={"disables_action": weapon,
                                         "dropped_at": actor.position.model_dump(mode="json")})


@pytest.mark.parametrize("kit", [SPEAR_KIT, TWO, {"starting_kit": {"items": [
    *SPEAR_KIT["starting_kit"]["items"], *STAFF["starting_kit"]["items"]]}}])
def test_only_own_held_spears_offered_without_attack_slot(monkeypatch, tmp_path, kit):
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION, THRUST], kit=kit)
    expected = {QIANG, MAO} if kit == TWO else {QIANG}
    assert set(spears(reload(tmp_path, mid))) == expected
    # A second held weapon must release the spear's attacking hand. Restore
    # that resting grip afterwards so the original possession assertions
    # still cover both held weapons independently of the spent Action slot.
    session = reload(tmp_path, mid)
    from combat.ext.hand_occupancy import weapon_grips
    ready = weapon_grips(session.engine, session.engine.state.actors[LEFT])
    stow = next((action for action in session.engine.action_catalog.values()
                 if action.owner_id == LEFT and (action.parameters.get("equipment_grip") or {}).get("held") == 0
                 and action.parameters["equipment_grip"]["weapon"] in ready
                 and action.parameters["equipment_grip"]["weapon"] != QIANG), None)
    if stow:
        assert answer_action(table, mid, stow.source_definition_id)["status"] == "COMMITTED"
    # Spending the action slot does not make a held weapon unavailable.
    assert answer_action(table, mid, ".weapon.qiang")["status"] == "COMMITTED"
    if stow:
        draw = next(action for action in reload(tmp_path, mid).engine.action_catalog.values()
                    if action.owner_id == LEFT and (action.parameters.get("equipment_grip") or {}).get("held") == 1
                    and action.parameters["equipment_grip"]["weapon"] == stow.parameters["equipment_grip"]["weapon"])
        assert answer_action(table, mid, draw.source_definition_id)["status"] == "COMMITTED"
    assert not reload(tmp_path, mid).engine.state.actors[LEFT].action_available
    assert set(spears(reload(tmp_path, mid))) == expected
    assert offered(table, mid)
    assert answer_action(table, mid, INFUSION, pick=QIANG)["status"] == "COMMITTED"
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_staff_owner_with_spear_ally_cannot_activate(monkeypatch, tmp_path):
    from combat.tabletop_service import TabletopError
    combat, table, mid = table_fight(tmp_path, [INFUSION], kit=STAFF, kits={"ally": SPEAR_KIT})
    loaded = reload(tmp_path, mid)
    assert any(a.owner_id == LEFT and a.parameters.get("requires_held_weapon") == ALLY_QIANG
               for a in loaded.engine.action_catalog.values())  # the dangerous synthetic copy exists
    assert not spears(loaded) and not offered(table, mid)
    state = table.state(mid)
    before = loaded.engine.state.model_dump(mode="json")
    with pytest.raises(TabletopError):
        table.act(mid, INFUSION, state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])
    assert reload(tmp_path, mid).engine.state.model_dump(mode="json") == before


def test_own_disarmed_spear_recovers_via_actual_pickup(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [INFUSION], kit=SPEAR_KIT)
    with monkeypatch.context() as fixture:
        on_hold(fixture, lambda engine: drop(engine, LEFT, QIANG))
        assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert not spears(reload(tmp_path, mid)) and not offered(table, mid)
    assert answer_action(table, mid, QIANG + ".pickup")["status"] == "COMMITTED"
    assert set(spears(reload(tmp_path, mid))) == {QIANG}
    next_left(table, mid)  # pick-up spent the bonus slot, not possession
    assert offered(table, mid)
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_disarmed_spear_variants_do_not_hide_remaining_spear(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [INFUSION, THRUST], kit=TWO)
    with monkeypatch.context() as fixture:
        on_hold(fixture, lambda engine: drop(engine, LEFT, QIANG))
        assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert set(spears(reload(tmp_path, mid))) == {MAO}
    assert offered(table, mid)
    # One legal choice commits immediately, without asking about dropped Qiang
    # or its variants or another fighter's synthetic copies.
    state = table.state(mid)
    menu = state["menu"]
    candidate = next(g["options"][0]["candidate_id"] for g in menu["actions"]
                     if INFUSION in g["source_definition_id"])
    assert table.act(mid, candidate, menu["decision_id"], menu["state_version"],
                     state["last_sequence"])["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert any(m.value.endswith("|" + MAO) for m in loaded.engine.state.actors[LEFT].modifiers.values()
               if m.target_field == "typed_on_hit")
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_bound_own_spear_bonus_waits_for_recovery(monkeypatch, tmp_path):
    from combat import typed_executor
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION, THRUST], kit=SPEAR_KIT)
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    def drop_and_probe(engine):
        drop(engine, LEFT, QIANG)
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = engine.action_catalog[QIANG]
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                      copy.deepcopy(action.parameters["typed"]), [target], target)
        typed_executor._on_hit_bonuses(ctx, target, {"attack_kind": "weapon"}, "PIERCING")
    with monkeypatch.context() as fixture:
        on_hold(fixture, drop_and_probe)
        assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert not infusion_damage(loaded)
    assert not spears(loaded)
    assert not any(k.startswith("_round_typed_on_hit:") for k in loaded.engine.state.actors[LEFT].turn_flags)
    next_left(table, mid)
    assert answer_action(table, mid, QIANG + ".pickup")["status"] == "COMMITTED"
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 1
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_borrowed_spear_requires_pickup_then_loses_availability_when_disarmed(monkeypatch, tmp_path):
    from combat import typed_executor
    from combat.ext.weapon_hits import available_weapons
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION, THRUST], kit=STAFF, kits={"ally": SPEAR_KIT})
    with monkeypatch.context() as fixture:
        on_hold(fixture, lambda engine: drop(engine, ALLY, ALLY_QIANG))
        assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert not spears(reload(tmp_path, mid)) and not offered(table, mid)
    # A borrowed two-handed spear still needs the hand resting on the staff.
    stow_staff = next(action for action in reload(tmp_path, mid).engine.action_catalog.values()
                      if action.owner_id == LEFT and (action.parameters.get("equipment_grip") or {}).get("held") == 0
                      and action.parameters["equipment_grip"]["weapon"].endswith(".weapon.gun"))
    assert answer_action(table, mid, stow_staff.source_definition_id)["status"] == "COMMITTED"
    assert answer_action(table, mid, ".take_weapon")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    borrowed, = spears(loaded)
    assert loaded.engine.action_catalog[borrowed].parameters["requires_held_weapon"] == ALLY_QIANG
    assert not available_weapons(loaded.engine, loaded.engine.state.actors[ALLY], ("spear",))
    next_left(table, mid)
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    # Lose the borrowed weapon via the engine's real Disarm effect. Probe the
    # bound bonus with a stale weapon context; it must neither fire nor spend.
    def disarm_and_probe(engine):
        actor, ally = engine.state.actors[LEFT], engine.state.actors[ALLY]
        source = engine.action_catalog[borrowed]
        ctx = typed_executor.Context(engine, ally, source, engine._active_intent,
                                      copy.deepcopy(source.parameters["typed"]), [actor], actor)
        typed_executor.block_condition(ctx, {"type": "condition", "condition": "disarmed", "applies_to": "target"})
        hit = typed_executor.Context(engine, actor, source, engine._active_intent,
                                     copy.deepcopy(source.parameters["typed"]), [engine.state.actors[RIGHT]],
                                     engine.state.actors[RIGHT])
        typed_executor._on_hit_bonuses(hit, hit.target, {"attack_kind": "weapon"}, "PIERCING")
    with monkeypatch.context() as fixture:
        on_hold(fixture, disarm_and_probe)
        assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert not spears(reload(tmp_path, mid)) and not infusion_damage(reload(tmp_path, mid))
    next_left(table, mid)  # Infusion already spent this turn's bonus action.
    assert answer_action(table, mid, ".take_weapon")["status"] == "COMMITTED"
    assert set(spears(reload(tmp_path, mid))) == {borrowed}
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 1
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("chooser_ai,trigger_ai", [(False, False), (False, True), (True, False)])
def test_off_turn_multi_spear_choice_manual_and_automatic(monkeypatch, tmp_path, chooser_ai, trigger_ai):
    from combat import typed_executor
    from combat.ext import needle
    from combat.gate4_engine import Gate4ControllerEngine
    combat, table, mid = table_fight(tmp_path, [INFUSION], kit=TWO, ask=True)
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if chooser_ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    if trigger_ai:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    original = Gate4ControllerEngine._append_event
    ask = needle.ask
    seen = []
    def observe(*args, **kwargs):
        seen.append(set(args[5]))
        return ask(*args, **kwargs)
    monkeypatch.setattr(needle, "ask", observe)
    def trigger(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        if event_type == "INTENT_ACCEPTED" and kwargs.get("actor_id") == RIGHT:
            actor = engine.state.actors[LEFT]
            action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT
                          and a.source_definition_id.endswith(INFUSION))
            ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                          copy.deepcopy(action.parameters["typed"]), [actor], actor)
            typed_executor.run_effects(ctx, ctx.typed["effects"])
        return result
    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", trigger)
    before = reload(tmp_path, mid).engine.state.model_dump(mode="json")
    result = table.auto_step(mid, 0) if trigger_ai else act(table, mid, HOLD)
    if chooser_ai:
        assert result["status"] == "COMMITTED"
        selected, = [m.value.rsplit("|", 1)[-1] for m in reload(tmp_path, mid).engine.state.actors[LEFT].modifiers.values()
                     if m.target_field == "typed_on_hit"]
        assert selected in {QIANG, MAO}
    else:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert {o["id"] for o in prompt["choice"]["options"]} == {QIANG, MAO}
        assert "Spear-Light Infusion" in str(prompt) and "Left" in str(prompt)
        assert reload(tmp_path, mid).engine.state.model_dump(mode="json") == before
        selected = MAO
        answers = [{**prompt["context"], "selection": "USE", "option_ids": [selected]}]
        if trigger_ai:
            result = table.auto_step(mid, 0, reactions=answers)
        else:
            state = table.state(mid)
            menu = state["menu"]
            candidate = next(g["options"][0]["candidate_id"] for g in menu["actions"]
                             if g["source_definition_id"] == HOLD)
            result = table.act(mid, candidate, menu["decision_id"], menu["state_version"],
                               state["last_sequence"], answers)
        assert result["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert seen and all(options == {QIANG, MAO} for options in seen)
    assert any(m.value.endswith("|" + selected) for m in loaded.engine.state.actors[LEFT].modifiers.values()
               if m.target_field == "typed_on_hit")
    assert loaded.mechanical.replay()["status"] == "PASS"
