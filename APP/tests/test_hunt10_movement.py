"""H10-41: granted movement cannot defeat Speed 0 or trap an AI turn."""
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from tests.test_auto_bodya import _engine, BODY_REFINING_SHEET, ME
from combat.factory_compiler import compile_character
import pytest


def test_speed_zero_has_no_manual_or_ai_moves_and_ai_ends_turn():
    engine = _engine(compile_character(BODY_REFINING_SHEET, actor_id=ME))
    actor = engine.state.actors[ME]
    engine._add_modifier(actor, "test:pinned", "speed_ft", "ADD", -999, "SELF", expires_on="START_OF_SOURCE_NEXT_TURN")
    actor.movement_remaining_ft = 5
    actor.action_available = actor.bonus_action_available = False
    assert not any(c.kind.value == "MOVE" for c in engine.legal_candidates())
    policies = PolicyLibrary(engine.source_root)
    context = build_decision_context(engine, policies.for_actor(ME)[0])
    for _ in range(4):
        context = build_decision_context(engine, policies.for_actor(ME)[0])
        choice = LocalDeterministicController().choose_primary_action(context)
        engine.execute_intent(choice.intent)
        if engine.state.current_actor_id != ME:
            break
    assert engine.state.current_actor_id != ME


def test_zero_step_interruption_veto_is_turn_local_and_plain_movement_is_inert():
    from combat.ext.movement_safety import interrupted_movement, FLAG
    engine = _engine(compile_character(BODY_REFINING_SHEET, actor_id=ME))
    actor = engine.state.actors[ME]
    move = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE")
    from types import SimpleNamespace
    engine._active_intent = SimpleNamespace(destination=move.destination)
    interrupted_movement(engine, "MOVEMENT_COMMITTED", {"actor_id": ME, "payload": {
        "interrupted": True, "cost_ft": 0, "path": [actor.position.model_dump(mode="json")]}})
    assert any(k.startswith(FLAG) for k in actor.turn_flags)
    assert not any(c.kind.value == "MOVE" and c.destination == move.destination for c in engine.legal_candidates())
    assert any(c.kind.value == "MOVE" for c in engine.legal_candidates())
    engine._system_start_turn()
    assert not any(k.startswith(FLAG) for k in actor.turn_flags)
    assert any(c.kind.value == "MOVE" for c in engine.legal_candidates())


def test_pinned_granted_movement_table_commit_reload_replay(tmp_path):
    from combat.gate5_service import CombatService
    from tests.hunt10_support import fight, use, reload_equal
    service, session = fight(tmp_path, effects=[
        {"type": "speed", "becomes": 0, "applies_to": "self", "duration": "until_start_of_your_next_turn"},
        {"type": "movement", "distance_ft": 5, "applies_to": "self"},
    ])
    actor_id = session.engine.state.current_actor_id
    use(session, "Test setup")
    session = reload_equal(service, session)
    actor = session.engine.state.actors[actor_id]
    assert session.engine._effective_speed(actor) == 0
    assert actor.movement_remaining_ft > 0
    assert not any(c.kind.value == "MOVE" for c in session.engine.legal_candidates())
    service.set_controller_mode(session.match_id, actor_id=actor_id, controller_mode="LOCAL_AUTO")
    for _ in range(5):
        result = service.local_step(session.match_id)
        session = reload_equal(service, service._load_session(session.match_id))
        if session.engine.state.current_actor_id != actor_id:
            break
    assert session.engine.state.current_actor_id != actor_id
    assert service.verify(session.match_id)["status"] == "PASS"
    assert service.replay(session.match_id)["status"] == "PASS"


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("ignore_difficult", [False, True])
def test_noop_route_not_reoffered_after_table_commit_reload_replay(monkeypatch, tmp_path, ai_turn, ignore_difficult):
    from combat.gate5_service import CombatService
    from tests.test_lock2_persistence import table_match, ROOT
    from combat.ext.movement_safety import FLAG

    def stop_one_step(engine, event_type, kwargs):
        actor = engine.state.actors.get(kwargs.get("actor_id"))
        if actor is None:
            return
        if event_type == "REACTION_WINDOW_OPENED" and (kwargs.get("payload") or {}).get("checkpoint") == "LEAVE_REACH":
            if ignore_difficult:
                assert engine.grid.unimpeded_full_costs[(10, 6)] == 2
                assert (10, 6) not in engine.grid.base_movement_cost
            engine._apply_condition(actor, "condition:typed.prone", "test:stop", actor.entity_id,
                                    expires_on="UNTIL_REMOVED")
        elif event_type == "MOVEMENT_COMMITTED":
            # A transient obstacle: Speed and movement are usable again, so the
            # route veto itself must prevent the repeated no-op, not Speed 0.
            engine._remove_condition(actor, "condition:typed.prone", "test:stop")
    from combat import ext
    ext.effects()
    # Leave the same mechanical situation at the interruption checkpoint: this
    # synthetic obstacle interrupts every attempt without changing lasting state.
    monkeypatch.setitem(ext._HOOKS, "event", [stop_one_step, *ext._HOOKS["event"]])
    if ignore_difficult:
        from combat.gate5_service import FACTORY_ACTOR_PREFIX
        from combat.tabletop_service import TabletopService
        import json
        import zipfile
        from tests.test_factory_combat_compiler import SHEET
        # Seal a real terrain-ignoring passive in both participants' bundles.
        sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.athletics"],
            "learned_talent_record_ids": ["TAL_ATHLETICS_UNIMPEDED_POSITIONING"]}}
        for side in ("left", "right"):
            folder = tmp_path / "portable_characters" / side
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / "current.zip", "w") as archive:
                archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
        combat = CombatService(ROOT, tmp_path)
        combat.tabletop_maps.save({"display_name": "Interrupted terrain yard", "width_squares": 12, "height_squares": 8,
            "walls": [], "terrain": [{"type": "DIFFICULT", "cells": [[10, 6]]}],
            "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
        view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
            control_modes={FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")},
            arena_id="battlefield:map.interrupted-terrain-yard", match_seed="LOCK2-TABLE-READY")
        table, mid = TabletopService(combat, tmp_path), view["match_id"]
    else:
        combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[menu["actor_id"]]
    if ignore_difficult:
        from combat import motion
        assert motion.ignores_difficult(engine, actor)
        assert engine.grid.base_movement_cost[(10, 6)] == 2
    foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    move = next(c for c in menu["moves"] if
        max(abs(c["destination"]["x"] - foe.position.x), abs(c["destination"]["y"] - foe.position.y)) > 1 and
        max(abs(c["destination"]["x"] - actor.position.x), abs(c["destination"]["y"] - actor.position.y)) == 1)
    assert table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saved_actor = loaded.engine.state.actors[actor.entity_id]
    if ignore_difficult:
        assert motion.ignores_difficult(loaded.engine, saved_actor)
        assert loaded.engine.grid.base_movement_cost[(10, 6)] == 2
    assert saved_actor.position == actor.position
    assert any(k.startswith(FLAG) and type(v) is str for k, v in saved_actor.turn_flags.items())
    assert not any(c.kind.value == "MOVE" and c.destination.model_dump(mode="json") == move["destination"]
                   for c in loaded.engine.legal_candidates())
    assert not any(c["destination"] == move["destination"] for c in table.state(mid)["menu"]["moves"])
    if ai_turn:
        context = build_decision_context(loaded.engine, combat.policies.for_actor(actor.entity_id)[0], for_ai=True)
        assert not any(c.kind.value == "MOVE" and c.destination.model_dump(mode="json") == move["destination"] for c in context.legal_candidates)
        combat.set_controller_mode(mid, actor_id=actor.entity_id, controller_mode="LOCAL_AUTO")
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("recovery", ["restriction", "speed", "position", "terrain", "allowance"])
def test_recovered_route_after_table_commit_reload(monkeypatch, tmp_path, ai_turn, recovery):
    """A later committed action changes the blocker; manual/AI menus recover."""
    from combat import ext
    from combat.gate2_runtime_models import Position, ZoneState
    from combat.gate5_service import CombatService
    from tests.test_lock2_persistence import table_match, act, ROOT

    def obstacle(engine, event_type, kwargs):
        actor = engine.state.actors.get(kwargs.get("actor_id"))
        if actor is None:
            return
        foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
        if event_type == "REACTION_WINDOW_OPENED" and (kwargs.get("payload") or {}).get("checkpoint") == "LEAVE_REACH":
            if any(e.event_type == "HOLD_POSITION_COMMITTED" for e in engine.events):
                return
            engine._apply_condition(actor, "condition:typed.prone", "test:stop", actor.entity_id,
                                    expires_on="UNTIL_REMOVED")
            if recovery == "speed":
                engine._add_modifier(actor, "test:stop", "speed_ft", "ADD", -999, "SELF",
                                     expires_on="UNTIL_REMOVED")
            elif recovery == "terrain":
                engine.state.zones["zone:test.terrain"] = ZoneState(
                    zone_id="zone:test.terrain", source_definition_id="test:terrain", owner_id=foe.entity_id,
                    center=actor.position, radius_cells=0, affected_cells=(actor.position,),
                    concentration_link=False, created_round=engine.state.round_number,
                    trigger_profile={"kind": "BLACKWATER"})
                engine._append_event("ZONE_CREATED", "test:terrain", actor_id=foe.entity_id,
                                     payload={"zone": engine.state.zones["zone:test.terrain"].model_dump(mode="json")})
        elif event_type == "MOVEMENT_COMMITTED" and recovery != "restriction":
            engine._remove_condition(actor, "condition:typed.prone", "test:stop")
        elif event_type == "HOLD_POSITION_COMMITTED":
            if recovery == "restriction":
                engine._remove_condition(actor, "condition:typed.prone", "test:stop")
            elif recovery == "speed":
                for key, modifier in list(actor.modifiers.items()):
                    if modifier.source_definition_id == "test:stop":
                        del actor.modifiers[key]
                        engine._append_event("MODIFIER_REMOVED", "test:stop", actor_id=actor.entity_id,
                                             target_ids=(actor.entity_id,), payload={"modifier_id": key})
            elif recovery == "position":
                foe.position = Position(x=foe.position.x + 1, y=foe.position.y)
            elif recovery == "terrain":
                engine.state.zones["zone:test.terrain"].active = False
            else:
                actor.movement_remaining_ft += 5

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [obstacle, *ext._HOOKS["event"]])
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    actor_id = menu["actor_id"]
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[actor_id]
    foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    move = next(c for c in menu["moves"] if
        max(abs(c["destination"]["x"] - foe.position.x), abs(c["destination"]["y"] - foe.position.y)) > 1 and
        max(abs(c["destination"]["x"] - actor.position.x), abs(c["destination"]["y"] - actor.position.y)) == 1)
    assert table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[actor_id].position == actor.position
    assert not any(c.kind.value == "MOVE" and c.destination.model_dump(mode="json") == move["destination"]
                   for c in loaded.engine.legal_candidates())
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    context = build_decision_context(loaded.engine, combat.policies.for_actor(actor_id)[0], for_ai=ai_turn)
    assert any(c.kind.value == "MOVE" and c.destination.model_dump(mode="json") == move["destination"]
               for c in context.legal_candidates)
    if ai_turn:
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode="LOCAL_AUTO")
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    else:
        state = table.state(mid)
        menu = state["menu"]
        restored = next(c for c in menu["moves"] if c["destination"] == move["destination"])
        assert table.act(mid, restored["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_legacy_veto_and_grid_change_do_not_forbid_recovery():
    from combat.ext.movement_safety import FLAG, interrupted_movement, movement_allowed
    from types import SimpleNamespace
    engine = _engine(compile_character(BODY_REFINING_SHEET, actor_id=ME))
    actor = engine.state.actors[ME]
    move = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.movement_cost_ft == 5)
    key = f"{FLAG}:{actor.position.x},{actor.position.y}>{move.destination.x},{move.destination.y}"
    actor.turn_flags[key] = 1  # Old saves have no mechanical fingerprint.
    assert any(c.destination == move.destination for c in engine.legal_candidates() if c.kind.value == "MOVE")
    engine._active_intent = SimpleNamespace(destination=move.destination)
    interrupted_movement(engine, "MOVEMENT_COMMITTED", {"actor_id": ME, "payload": {
        "interrupted": True, "cost_ft": 0, "path": [actor.position.model_dump(mode="json")]}})
    engine.state.state_version += 1
    engine.state.event_sequence += 1
    assert not any(c.destination == move.destination for c in engine.legal_candidates() if c.kind.value == "MOVE")
    engine.grid.base_movement_cost[(move.destination.x, move.destination.y)] = 2
    # Direct seam check: legal_candidates rebuilds the grid from sealed map/zones.
    # The table regression above covers the persisted zone-driven terrain path.
    assert movement_allowed(engine, actor, move, None) is None


@pytest.mark.parametrize('current_receipt', [False, True])
def test_current_move_interruption_does_not_veto_future_route(current_receipt):
    """A current-action stop is transient; an older stop cannot release a veto."""
    from combat.ext.movement_safety import interrupted_movement, movement_allowed
    from types import SimpleNamespace
    engine = _engine(compile_character(BODY_REFINING_SHEET, actor_id=ME))
    actor = engine.state.actors[ME]
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.movement_cost_ft == 5)
    engine._active_intent = SimpleNamespace(destination=move.destination, intent_id='test:current-move')
    if not current_receipt:
        actor.turn_flags['movement_interrupted_sequence'] = engine.state.event_sequence
    engine._append_event('INTENT_ACCEPTED', 'system:combat.move', actor_id=ME,
                         trigger_or_intent_id='test:current-move')
    if current_receipt:
        actor.turn_flags['movement_interrupted_sequence'] = engine.state.event_sequence + 1
        engine._append_event('PASSIVE_TRIGGERED', 'test:stop-current-move', actor_id=ME)
    allowance = actor.movement_remaining_ft
    interrupted_movement(engine, 'MOVEMENT_COMMITTED', {'actor_id': ME, 'payload': {
        'interrupted': True, 'cost_ft': 0, 'path': [actor.position.model_dump(mode='json')]}})
    assert movement_allowed(engine, actor, move, None) is (None if current_receipt else False)
    assert actor.movement_remaining_ft == allowance


def test_terrain_fingerprint_matches_nested_execution_and_menu_views():
    from combat import motion
    from combat.ext.movement_safety import interrupted_movement, movement_allowed
    from types import SimpleNamespace
    engine = _engine(compile_character(BODY_REFINING_SHEET, actor_id=ME))
    actor = engine.state.actors[ME]
    actor.turn_flags["echoing_step"] = 1
    move = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE")
    engine.grid.base_movement_cost[(10, 6)] = 2
    engine._active_intent = SimpleNamespace(destination=move.destination)
    with motion.terrain_for(engine, actor):
        assert (10, 6) not in engine.grid.base_movement_cost
        interrupted_movement(engine, "MOVEMENT_COMMITTED", {"actor_id": ME, "payload": {
            "interrupted": True, "cost_ft": 0, "path": [actor.position.model_dump(mode="json")]}})
        with motion.terrain_for(engine, actor):
            assert movement_allowed(engine, actor, move, None) is False
    assert engine.grid.base_movement_cost[(10, 6)] == 2
    assert movement_allowed(engine, actor, move, None) is False
    # A real full-terrain change still releases the veto, even inside execution.
    engine.grid.base_movement_cost[(10, 6)] = 3
    with motion.terrain_for(engine, actor):
        assert movement_allowed(engine, actor, move, None) is None
