"""Pre-merge fixes: real accepted Spear actions, persisted turn use and lifetimes."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT, script
from tests.test_auto_martial import SPEAR_KIT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, table_fight, answer_action

INFUSION = "TAL_SPEAR_SPEAR_LIGHT_INFUSION"
THRUST = "SPEAR_BASE_SPEAR_THRUST"


@pytest.mark.parametrize("refresh", [False, True])
def test_base_format_spent_bonus_loads_through_table(monkeypatch, tmp_path, refresh):
    from combat import ext
    from tests.test_tabletop_hunt6 import on_hold

    combat, table, mid = setup(tmp_path, monkeypatch)

    def base_format(engine):
        actor = engine.state.actors[LEFT]
        # A saved spent reaction hit can leave both action slots available.
        actor.action_available = True
        actor.bonus_action_available = True
        for key in list(actor.turn_flags):
            if key.startswith("_round_typed_on_hit:"):
                del actor.turn_flags[key]
        for mid, modifier in actor.modifiers.items():
            if modifier.target_field == "typed_on_hit":
                actor.turn_flags[f"typed_on_hit:{mid}"] = True

    # Produce the base's spent-flag format using a real table commit.
    # Disable only the new migration while writing this historical fixture.
    on_hold(monkeypatch, base_format)
    with monkeypatch.context() as fixture:
        fixture.setitem(ext._HOOKS, "event", [h for h in ext._HOOKS["event"]
                                             if h.__module__ != "combat.ext.deferred_hit_state"])
        assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    monkeypatch.undo()
    hit_script(monkeypatch)
    loaded = reload(tmp_path, mid)
    assert any(k.startswith("typed_on_hit:") and v is True
               for k, v in loaded.engine.state.actors[LEFT].turn_flags.items())
    assert not any(k.startswith("_round_typed_on_hit:")
                   for k in loaded.engine.state.actors[LEFT].turn_flags)
    before = len(infusion_damage(loaded))
    if refresh:
        assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    # Real compiled weapon attack on the saved current turn cannot spend twice.
    assert answer_action(table, mid, ".weapon.qiang")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len(infusion_damage(loaded)) == before
    assert not any(k.startswith("typed_on_hit:") for k in loaded.engine.state.actors[LEFT].turn_flags)
    assert any(k.startswith("_round_typed_on_hit:") and isinstance(v, str)
               for k, v in loaded.engine.state.actors[LEFT].turn_flags.items())
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    approach_pushed_target(table, mid)
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len(infusion_damage(loaded)) == before + 1
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_staff_only_owner_cannot_offer_or_pay_for_infusion(monkeypatch, tmp_path):
    from combat.tabletop_service import TabletopError

    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gun", "name": "Gun (Staff)", "quantity": 1}]}}
    combat, table, mid = table_fight(tmp_path, [INFUSION], cl=11, kit=kit)
    state = table.state(mid)
    assert not any(INFUSION in g["source_definition_id"] for g in state["menu"]["actions"])
    before = reload(tmp_path, mid).engine.state.model_dump(mode="json")
    with pytest.raises(TabletopError):
        table.act(mid, INFUSION, state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])
    after = reload(tmp_path, mid).engine.state.model_dump(mode="json")
    assert after == before  # resources, economy, concentration and modifiers


def test_multiple_spears_prompt_and_bind_only_selected_weapon(monkeypatch, tmp_path):
    kit = {"starting_kit": {"items": [*SPEAR_KIT["starting_kit"]["items"],
                                    {"item_id": "tianxia.mortal.weapon.mao", "name": "Mao (Long Spear)", "quantity": 1}]}}
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION], cl=11, kit=kit)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if INFUSION in g["source_definition_id"])
    args = (mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])
    before = reload(tmp_path, mid).engine.state.model_dump(mode="json")
    result = table.act(*args)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    options = prompt["choice"]["options"]
    import hashlib
    prefix = f"action:typed.{hashlib.sha256(LEFT.encode()).hexdigest()[:10]}.weapon."
    assert {o["id"] for o in options} == {prefix + "qiang", prefix + "mao"}
    assert len({o["id"] for o in options}) == len(options)
    assert any(o["id"].endswith(".weapon.qiang") for o in options)
    selected = next(o["id"] for o in options if o["id"].endswith(".weapon.mao"))
    assert "Spear-Light Infusion" in str(prompt) and "Left" in str(prompt)
    assert reload(tmp_path, mid).engine.state.model_dump(mode="json") == before
    result = table.act(*args, [{**prompt["context"], "selection": "USE", "option_ids": [selected]}])
    assert result["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert any(m.value.endswith("|" + selected) for m in loaded.engine.state.actors[LEFT].modifiers.values()
               if m.target_field == "typed_on_hit")
    from tests.equipment_readiness import ready_table_weapon
    ready_table_weapon(table, mid, prefix + "qiang")
    assert answer_action(table, mid, ".weapon.qiang")["status"] == "COMMITTED"
    assert not infusion_damage(reload(tmp_path, mid))
    while table.state(mid)["menu"]["actor_id"] == LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    approach_pushed_target(table, mid)
    ready_table_weapon(table, mid, selected)
    assert answer_action(table, mid, ".weapon.mao")["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len(infusion_damage(loaded)) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


def approach_pushed_target(table, mid):
    # Spear Intent from an ordinary Spear attack pushes Right to x=6.
    state = table.state(mid)
    menu = state["menu"]
    move = next(m for m in menu["moves"] if m["destination"] == {"x": 5, "y": 4})
    assert table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"])["status"] == "COMMITTED"


def reload(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def infusion_damage(session):
    return [e for e in session.engine.events if e.event_type == "DAMAGE_COMMITTED"
            and e.source_definition_id.endswith(INFUSION)]


def hit_script(monkeypatch):
    from combat.gate4_engine import Gate4ControllerEngine
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [19, *([1] * 40)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)


def setup(tmp_path, monkeypatch, kit=SPEAR_KIT):
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION, THRUST], cl=11, kit=kit)
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    return combat, table, mid


def test_real_spear_thrust_delivers_bound_infusion_after_reload(monkeypatch, tmp_path):
    combat, table, mid = setup(tmp_path, monkeypatch)
    session = reload(tmp_path, mid)
    assert any(m.value.endswith(".weapon.qiang") for m in session.engine.state.actors[LEFT].modifiers.values()
               if m.target_field == "typed_on_hit")
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len(infusion_damage(loaded)) == 1
    assert infusion_damage(loaded)[0].payload["hp_damage"] == 2
    assert any(e.event_type == "DAMAGE_COMMITTED" and THRUST in e.source_definition_id for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_compiler_delivered_close_haft_strike_gets_bound_infusion_after_reload(monkeypatch, tmp_path):
    close = "TAL_AXES_CLOSE_HAFT_STRIKE"
    from combat.typed_executor import mark_condition_id
    from tests.test_tabletop_hunt6 import on_hold
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION, close], cl=11, kit=SPEAR_KIT)
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    # Seed the technique's printed Bite prerequisite through an evented table
    # transaction; delivery and the tested attack use the actual compiler row.
    on_hold(monkeypatch, lambda engine: engine._apply_condition(
        engine.state.actors[RIGHT], mark_condition_id("Bite", LEFT), close, LEFT,
        expires_on="END_OF_SOURCE_NEXT_TURN"))
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    session = reload(tmp_path, mid)
    action = next(a for a in session.engine.action_catalog.values()
                  if a.owner_id == LEFT and close in a.source_definition_id)
    assert action.parameters["typed"]["delivered_by"].split("#", 1)[0].endswith(".weapon.qiang")
    assert not action.parameters["typed"].get("weapon_source_id")
    before = len(infusion_damage(session))
    assert answer_action(table, mid, close)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len(infusion_damage(loaded)) == before + 1
    assert infusion_damage(loaded)[-1].payload["hp_damage"] == 2
    assert any(e.event_type == "DAMAGE_COMMITTED" and close in e.source_definition_id for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_other_weapon_does_not_receive_or_consume_bound_infusion(monkeypatch, tmp_path):
    kit = {"starting_kit": {"items": [*SPEAR_KIT["starting_kit"]["items"],
                                    {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
    combat, table, mid = setup(tmp_path, monkeypatch, kit)
    from tests.equipment_readiness import ready_table_weapon

    def ready(suffix):
        source = next(a.source_definition_id for a in reload(tmp_path, mid).engine.action_catalog.values()
                      if a.owner_id == LEFT and a.source_definition_id.endswith(suffix))
        ready_table_weapon(table, mid, source)

    # A carried axe is not an attack option while the infused spear occupies
    # the hands. Swap grips through committed Draw/Stow actions.
    ready(".weapon.fu")
    assert answer_action(table, mid, ".weapon.fu")["status"] == "COMMITTED"
    assert not infusion_damage(reload(tmp_path, mid))
    while table.state(mid)["menu"]["actor_id"] == LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    ready(".weapon.qiang")
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 1


def test_once_per_actual_turn_survives_reload_and_refresh(monkeypatch, tmp_path):
    from combat import typed_executor
    from combat.gate4_engine import Gate4ControllerEngine

    # Qiang's automatic Push mastery moves the foe out of reach, so later
    # synthetic attacks never hit. Use a non-pushing spear and thrust option
    # to isolate the printed once-per-turn hit gate, not movement geometry.
    kit = {"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.mao", "name": "Mao (Long Spear)", "quantity": 1}]}}
    combat, table, mid = setup(tmp_path, monkeypatch, kit)
    assert answer_action(table, mid, THRUST + "#opt2")["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 1

    def hit_twice(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT
                      and a.source_definition_id.endswith(THRUST + "#opt2"))
        import copy
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                     copy.deepcopy(action.parameters["typed"]), [target], target)
        before = len(engine.events)
        for _ in range(2):
            typed_executor.run_effects(ctx, ctx.typed["effects"])
        attacks = [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
        assert len(attacks) == 2 and all(e.payload["provisional_hit"] for e in attacks)

    original = Gate4ControllerEngine._append_event

    def sample_hits(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        # Like on_hold, run outside the event-hook recursion guard so normal
        # attack choices can pause the accepted transaction.
        if event_type == "HOLD_POSITION_COMMITTED" or (
                event_type == "MOVEMENT_COMMITTED" and not kwargs.get("payload", {}).get("forced")):
            hit_twice(engine)
        return result

    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", sample_hits)
    # Reloaded usage rejects another hit on the owner's same turn.
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 1
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] != LEFT
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 2
    # Hold Position is legal only once per turn. A distinct accepted move
    # tests another transaction after reload on that same off-turn.
    state = table.state(mid)
    menu = state["menu"]
    move = next(m for m in menu["moves"] if m["destination"] == {"x": 4, "y": 5})
    assert table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"])["status"] == "COMMITTED"
    assert len(infusion_damage(reload(tmp_path, mid))) == 2
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert answer_action(table, mid, THRUST + "#opt2")["status"] == "COMMITTED"
    before = len(infusion_damage(reload(tmp_path, mid)))
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert len(infusion_damage(loaded)) == before
    assert all(isinstance(v, (str, int)) for k, v in loaded.engine.state.actors[LEFT].turn_flags.items()
               if k.startswith("_round_typed_on_hit:"))
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_infusion_ends_after_ten_rounds_across_reload(monkeypatch, tmp_path):
    from combat.ext.concentration_duration import DEADLINE
    from combat.ext.effect_durations import parse_round

    combat, table, mid = setup(tmp_path, monkeypatch)
    loaded = reload(tmp_path, mid)
    actor = loaded.engine.state.actors[LEFT]
    deadline = next(c for c in actor.conditions.values() if c.condition_id == DEADLINE)
    end_round, end_slot = parse_round(deadline.expires_on)
    assert end_round == loaded.engine.state.round_number + 10
    assert type(deadline.data["started_sequence"]) is int
    for _ in range(35):
        loaded = reload(tmp_path, mid)
        state = loaded.engine.state
        if (state.round_number, state.current_slot_index) >= (end_round, end_slot):
            break
        assert state.actors[LEFT].concentration is not None
        assert any(m.target_field == "typed_on_hit" for m in state.actors[LEFT].modifiers.values())
        assert act(table, mid, "end")["status"] == "COMMITTED"
    else:
        raise AssertionError("deadline not reached")
    actor = loaded.engine.state.actors[LEFT]
    assert actor.concentration is None
    assert not any(m.target_field == "typed_on_hit" for m in actor.modifiers.values())
    assert not any(c.condition_id == DEADLINE for c in actor.conditions.values())
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    assert not infusion_damage(loaded)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_early_concentration_loss_removes_infusion_and_deadline_after_reload(monkeypatch, tmp_path):
    from combat.ext.concentration_duration import DEADLINE
    from tests.test_tabletop_hunt6 import on_hold

    combat, table, mid = setup(tmp_path, monkeypatch)
    on_hold(monkeypatch, lambda engine: engine._end_concentration(engine.state.actors[LEFT], "VOLUNTARY"))
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.concentration is None
    assert not any(m.target_field == "typed_on_hit" for m in actor.modifiers.values())
    assert not any(c.condition_id == DEADLINE for c in actor.conditions.values())
    assert answer_action(table, mid, THRUST)["status"] == "COMMITTED"
    assert not infusion_damage(reload(tmp_path, mid))
    assert reload(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_movement_opportunity_hit_delivers_infusion_through_table_reload(monkeypatch, tmp_path):
    hit_script(monkeypatch)
    combat, table, mid = table_fight(tmp_path, [INFUSION, THRUST], cl=11, kit=SPEAR_KIT, ask=True)
    assert answer_action(table, mid, INFUSION)["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    before = reload(tmp_path, mid)
    oa = next(a for a in before.engine.action_catalog.values()
              if a.owner_id == LEFT and a.source_definition_id.endswith(".opportunity_attack"))
    assert oa.parameters["typed"]["opportunity_of"].endswith(".weapon.qiang")
    state = table.state(mid)
    menu = state["menu"]
    # Qiang threatens ten feet: an accepted ordinary move leaves its reach.
    move = next(m for m in menu["moves"] if m["destination"]["x"] == 6 and m["destination"]["y"] == 4
                and m["destination"].get("z", 0) == 0)
    args = (mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    result = table.act(*args)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Opportunity Attack" and prompt["reactor"] == "Left"
    assert not infusion_damage(reload(tmp_path, mid))  # preview has not committed
    result = table.act(*args, [{**prompt["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    damage = infusion_damage(loaded)
    assert len(damage) == 1 and damage[0].target_ids == (RIGHT,) and damage[0].payload["hp_damage"] == 2
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == oa.source_definition_id
               for e in loaded.engine.events)
    # Qiang's printed Push mastery moves a hit target 10 ft (weapon_specials.json).
    # Native lock3 revalidation interrupts the stale voluntary path after that
    # displacement; it must not overwrite the push with the planned x=6 step.
    forced = next(e for e in loaded.engine.events if e.event_type == "MOVEMENT_COMMITTED"
                  and e.actor_id == RIGHT and e.source_definition_id == oa.source_definition_id
                  and e.payload.get("forced"))
    assert forced.payload["path"] == [{"x": 5, "y": 4}, {"x": 6, "y": 4}, {"x": 7, "y": 4}]
    assert loaded.engine.state.actors[RIGHT].position.model_dump(mode="json") == forced.payload["destination"] == {"x": 7, "y": 4}
    voluntary = next(e for e in reversed(loaded.engine.events) if e.event_type == "MOVEMENT_COMMITTED"
                     and e.actor_id == RIGHT and e.source_definition_id == "system:combat.movement")
    assert voluntary.payload["interrupted"] is True
    assert voluntary.payload["path"] == [{"x": 4, "y": 4}, {"x": 5, "y": 4}]
    # The planned move from x=4 to x=6 is two five-foot steps; the push is
    # separate forced movement and cannot inflate the voluntary path's cost.
    assert voluntary.payload["cost_ft"] == 5 and voluntary.payload["planned_cost_ft"] == 10
    assert loaded.engine.state.actors[RIGHT].movement_remaining_ft == before.engine.state.actors[RIGHT].movement_remaining_ft - 5
    assert not loaded.engine.state.actors[LEFT].reaction_available
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_held_infusion_copy_expires_without_ending_current_concentration(monkeypatch, tmp_path):
    from combat import concentration
    from combat.ext.concentration_duration import DEADLINE
    from combat.ext.effect_durations import parse_round
    from tests.test_tabletop_hunt6 import on_hold

    combat, table, mid = setup(tmp_path, monkeypatch)
    first = reload(tmp_path, mid).engine.state.actors[LEFT].concentration
    on_hold(monkeypatch, lambda engine: engine._start_concentration(engine.state.actors[LEFT], "test:second"))
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    monkeypatch.undo()  # do not create another concentration on subsequent holds
    loaded = reload(tmp_path, mid)
    actor = loaded.engine.state.actors[LEFT]
    assert concentration.held(actor)[0][1].started_sequence == first.started_sequence
    current = actor.concentration.started_sequence
    deadline = next(c for c in actor.conditions.values() if c.condition_id == DEADLINE)
    end_round, end_slot = parse_round(deadline.expires_on)
    for _ in range(35):
        loaded = reload(tmp_path, mid)
        if (loaded.engine.state.round_number, loaded.engine.state.current_slot_index) >= (end_round, end_slot):
            break
        assert concentration.held(loaded.engine.state.actors[LEFT])
        assert act(table, mid, "end")["status"] == "COMMITTED"
    else:
        raise AssertionError("held deadline not reached")
    actor = loaded.engine.state.actors[LEFT]
    assert not concentration.held(actor)
    assert actor.concentration.source_definition_id == "test:second"
    assert actor.concentration.started_sequence == current
    assert not any(m.target_field == "typed_on_hit" for m in actor.modifiers.values())
    assert not any(c.condition_id == DEADLINE for c in actor.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
