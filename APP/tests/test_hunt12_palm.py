"""Severing Palm: choose before payment, then expire on the source's turn."""
import pytest
from tests.hunt12_support import ME, FOE, STAMINA, candidate, fight, hit_dice, reload, send

PALM = "tianxia.subpath.body.kensei.feature.severing_palm"
IRON = "TAL_IRON_FIST_IRON_FIST_TRAINING"


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_choice_precedes_payment_and_survives_reload(tmp_path, monkeypatch, auto, selection):
    combat, table, mid = fight(tmp_path, [PALM, IRON])
    hit_dice(monkeypatch)
    chosen = candidate(combat, mid, lambda c: ".natural.iron_fist" in c.source_definition_id and "#" not in c.source_definition_id and tuple(c.target_ids) == (FOE,))
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(combat, table, mid, chosen, auto=auto)
    if not auto:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["reaction"] == "Severing Palm"
        assert "4 Stamina" in prompt["trigger"]
        assert "Unarmed Strike" in prompt["trigger"] and "Factory character" in prompt["trigger"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**prompt["context"], "selection": selection, "option_ids": ["breath"] if selection == "USE" else []}
        result = send(combat, table, mid, chosen, [answer])
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    used = auto or selection == "USE"
    assert engine.state.actors[ME].resources[STAMINA] == before["actors"][ME]["resources"][STAMINA] - 4 * used
    assert bool(engine.state.actors[ME].turn_flags.get("severing_palm")) == used
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert bool(saves) == used


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("choice", ["arm", "leg", "breath", "flow", "guard"])
def test_duration_uses_source_next_turn_through_commit_reload(tmp_path, monkeypatch, auto, failed, choice):
    from tests.test_lock2_persistence import act
    combat, table, mid = fight(tmp_path, [PALM, IRON], dc=100 if failed else -100)
    # Attack abilities use their own mastery save DC after the owner edits;
    # control the saving die rather than relying on the sheet technique DC.
    hit_dice(monkeypatch, save_roll=1 if failed else 20)
    preset = candidate(combat, mid, lambda c: c.display_name == f"Severing Palm: {choice.title()}")
    assert send(combat, table, mid, preset)["status"] == "COMMITTED"
    chosen = candidate(combat, mid, lambda c: ".natural.iron_fist" in c.source_definition_id and "#" not in c.source_definition_id and tuple(c.target_ids) == (FOE,))
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    result = send(combat, table, mid, chosen, auto=auto)
    if not auto:
        assert result["status"] == "REACTION_REQUIRED"
        answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": [choice]}
        result = send(combat, table, mid, chosen, [answer])
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    source_turn = engine.state.actors[ME].turns_started

    def effects(engine):
        target = engine.state.actors[FOE]
        return [r for r in [*target.conditions.values(), *target.modifiers.values()]
                if getattr(r, "condition_id", "") in ("condition:typed.reaction_denied", "condition:typed.concentration_mode", "condition:typed.severing_arm")
                or getattr(r, "target_field", "") in ("attack_mode", "speed_halved", "armor_class")]

    rows = effects(engine)
    assert rows
    end = failed and choice != "guard"
    expected = f"END_OF_SOURCE_TURN_AT:{source_turn + 1}" if end else "START_OF_SOURCE_NEXT_TURN"
    assert all(r.expires_on == expected for r in rows), [(getattr(r, "target_field", ""), r.expires_on) for r in rows]
    # Passing the victim's turn must not remove the impairment.
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert effects(reload(tmp_path, mid))
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert bool(effects(reload(tmp_path, mid))) == end
    if end:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        assert not effects(reload(tmp_path, mid))


@pytest.mark.parametrize("owner_auto", [False, True])
@pytest.mark.parametrize("turn_auto", [False, True])
def test_off_turn_hit_asks_manual_owner_and_names_source_expiry(tmp_path, monkeypatch, owner_auto, turn_auto):
    from combat.typed_executor import Context, run_effects
    from tests.hunt12_support import event_hook
    from tests.test_lock2_persistence import act
    combat, table, mid = fight(tmp_path, [PALM, IRON])
    hit_dice(monkeypatch)
    strike = candidate(combat, mid, lambda c: ".natural.iron_fist" in c.source_definition_id and "#" not in c.source_definition_id and tuple(c.target_ids) == (FOE,))

    def strike_off_turn(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED" or kwargs.get("actor_id") != FOE:
            return
        action = engine.action_catalog[strike.source_definition_id]
        actor, target = engine.state.actors[ME], engine.state.actors[FOE]
        ctx = Context(engine, actor, action, engine._active_intent, action.parameters["typed"], [target], target)
        run_effects(ctx, action.parameters["typed"]["effects"])

    event_hook(monkeypatch, strike_off_turn)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    chosen = candidate(combat, mid, lambda c: c.source_definition_id == "system:combat.hold_position")
    if owner_auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    if turn_auto:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(combat, table, mid, chosen, auto=turn_auto)
    if not owner_auto:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["reaction"] == "Severing Palm" and "Unarmed Strike" in prompt["trigger"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        result = send(combat, table, mid, chosen, [{**prompt["context"], "selection": "USE", "option_ids": ["leg"]}], auto=turn_auto)
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources[STAMINA] == before["actors"][ME]["resources"][STAMINA] - 4
    target = engine.state.actors[FOE]
    rows = ([r for r in target.conditions.values() if r.condition_id == "condition:typed.severing_arm"] if owner_auto else
            [r for r in target.modifiers.values() if r.target_field == "speed_halved"])
    assert rows and all(r.expires_on == f"END_OF_TURN_AT:{ME}:{engine.state.actors[ME].turns_started + 1}" for r in rows)
