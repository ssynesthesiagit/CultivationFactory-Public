"""SOL113: real persisted table turns, including legacy nonlethal defeat."""
import pytest

from combat import ext
from combat.ext import life_state
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import ROOT, _install
from tests.test_lock_choices import install


def fight(tmp_path, monkeypatch, *, rolls=(12, 12, 12), legacy=False, followup=None, excess=1, harvest=False,
          defeated_side=False, recovery=False, spirit=False, relations=False, terminal_zone=False):
    for name in ("sol113-left", "sol113-right", "sol113-ally"):
        _install(tmp_path, name)
    target_id = FACTORY_ACTOR_PREFIX + "sol113-left"
    foe_id = FACTORY_ACTOR_PREFIX + "sol113-right"
    service = CombatService(ROOT, tmp_path)
    if spirit:
        from tests.test_riders_c9 import sheet, SPIRIT_KIT
        spirit_owner_sheet = service._factory_owner_sheet
        def spirit_sheet(pid):
            original = spirit_owner_sheet(pid)
            if pid == "sol113-left":
                original = {**original, "spheres_and_talents": sheet(SPIRIT_KIT)["spheres_and_talents"]}
            return original
        monkeypatch.setattr(service, "_factory_owner_sheet", spirit_sheet)
    if harvest:
        from combat.ext import soul_warden
        owner_sheet = service._factory_owner_sheet
        def harvest_sheet(pid):
            sheet = owner_sheet(pid)
            if pid == "sol113-right":
                sheet = {**sheet, "identity": {**sheet["identity"], "cultivation_level": 22},
                    "path_and_subpath": {"path_feature_record_ids": [soul_warden.HARVEST]},
                    "ability_scores_and_statistics": {**sheet["ability_scores_and_statistics"],
                        "primary_resource": {"name": "Resonance", "maximum": 60}}}
            return sheet
        monkeypatch.setattr(service, "_factory_owner_sheet", harvest_sheet)
    if legacy or relations:
        create = service.persistence.create_match
        def legacy_create(**kw):
            kw["roster_setup"] = {**kw["roster_setup"], **({"rules": {}} if legacy else {}),
                                  **({"relations": {"teams": {}, "actors": {}}} if relations else {})}
            return create(**kw)
        monkeypatch.setattr(service.persistence, "create_match", legacy_create)

    def blow(engine, actor):
        # A deterministic attack checkpoint inside the actual End Turn commit.
        if actor.entity_id == target_id and actor.turns_started == 2:
            victim = next(a for a in engine.state.actors.values() if a.summon and a.summon.get("owner") == target_id) if spirit else actor
            engine._commit_damage(victim, victim.current_hp + excess, "FIRE", "test:eruption", foe_id, None, reaction_depth=0)
            if defeated_side:
                engine._defeat(engine.state.actors[FACTORY_ACTOR_PREFIX + "sol113-ally"], "test:ally_defeat", final=True)
                if recovery:
                    engine._apply_condition(actor, life_state.RECOVERY, "test:recovery", target_id, expires_on="UNTIL_REMOVED",
                                            data={"round": 10, "slot": 0, "label": "Scheduled stable recovery"})
        target = engine.state.actors.get(target_id)
        if terminal_zone and actor.entity_id != target_id and target is not None and target.life_state == "STABLE" and not engine.state.zones:
            # Persist a real native damage zone before the incoming Stable turn.
            from combat.gate2_runtime_models import ZoneState
            zone = ZoneState(zone_id="zone:sol113-terminal", source_definition_id="action:bai_meizhen.blackwater_serpent_court",
                             owner_id=foe_id, center=target.position, radius_cells=0, affected_cells=(target.position,),
                             concentration_link=False, created_round=engine.state.round_number, trigger_profile={"kind": "BLACKWATER"})
            engine.state.zones[zone.zone_id] = zone
            engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=foe_id,
                                 payload={"zone": zone.model_dump(mode="json")})
        if terminal_zone and engine.state.terminal_result is not None:
            engine._append_event("PASSIVE_TRIGGERED", "test:post_terminal_turn_start", actor_id=actor.entity_id)
        if (followup and actor.entity_id != target_id and target is not None and target.life_state == "DYING"
                and not any(e.source_definition_id == "test:followup" for e in engine.events)):
            if followup == "healing":
                life_state.restore_hp(engine, target, 5, "test:followup", actor.entity_id)
            else:
                if followup == "stable_damage":
                    life_state.stabilize(engine, target, "test:stabilize")
                if followup == "critical":
                    engine._append_event("ATTACK_ROLLED", "test:critical", actor_id=foe_id, target_ids=(target_id,), payload={"natural_result": 20})
                amount = target.maximum_hp if followup == "massive" else 4
                engine._commit_damage(target, amount, "FIRE", "test:followup", foe_id, None, reaction_depth=0)

    def death_die(engine, roll, intent):
        if terminal_zone and roll.actor_id == target_id and roll.reason.endswith(":CON") and roll.reason.startswith("SAVE:"):
            return {"source_id": "test:zone_save", "operation": "replace", "natural_result": 20}
        if harvest and roll.actor_id == foe_id and roll.reason.startswith("ATTACK"):
            return {"source_id": "test:attack_die", "operation": "replace", "natural_result": 20}
        if roll.reason == "SAVE:death" and roll.actor_id == target_id:
            turn = engine.state.actors[target_id].turns_started
            return {"source_id": "test:death_die", "operation": "replace", "natural_result": rolls[min(max(0, turn - 3), len(rolls)-1)]}
        return None

    ext.effects()
    if terminal_zone:
        def recovery_finished(engine, actor):
            # Keep combat open until this Stable creature's next boundary.
            if actor.entity_id == target_id and actor.turns_started == 6:
                engine._remove_condition(actor, life_state.RECOVERY, "test:recovery_finished")
        monkeypatch.setitem(ext._HOOKS, "turn_boundary_start", [recovery_finished, *ext._HOOKS.get("turn_boundary_start", [])])
    monkeypatch.setitem(ext._HOOKS, "turn_start", [*ext._HOOKS.get("turn_start", []), blow])
    install(monkeypatch, "d20_result", death_die)
    service.tabletop_maps.save({"map_id": "sol113", "display_name": "Dying rules test", "width_squares": 8, "height_squares": 8,
        "scale": 100, "walls": [], "starts": {"team1": [[1, 1], [1, 2]], "team2": [[2, 1]]}})
    view = service.create_factory_match(project_ids=["sol113-left", "sol113-ally"], opponent_actor_ids=[foe_id],
        control_modes={target_id: "MANUAL", foe_id: "MANUAL", FACTORY_ACTOR_PREFIX + "sol113-ally": "MANUAL"},
        arena_id="battlefield:map.sol113", match_seed="SOL113-TABLE", maximum_rounds=15)
    return service, TabletopService(service, tmp_path), view["match_id"], target_id


def advance(table, mid):
    state = table.state(mid)
    menu = state["menu"]
    if menu["manual"]:
        return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["state"]
    return table.auto_step(mid, state["last_sequence"])["state"]


def test_default_ai_fight_records_the_same_dying_rules(tmp_path):
    for name in ("ai-left", "ai-right"):
        _install(tmp_path, name)
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["ai-left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "ai-right"],
                                       match_seed="SOL113-NEW-AI")
    loaded = service._load_session(view["match_id"])
    assert set(view["metadata"]["participant_control_modes"].values()) == {"LOCAL_AUTO"}
    assert loaded.engine.state.rules == {"zero_hp": "dying_2024", "finalized_turns": "skip_finalized_v1"}
    assert next(e for e in loaded.engine.events if e.event_type == "MATCH_CREATED").payload["rules"] == loaded.engine.state.rules


def until_turn(service, table, mid, target_id, turn):
    for _ in range(20):
        actor = service._load_session(mid).engine.state.actors[target_id]
        if actor.turns_started >= turn:
            return table.state(mid)
        advance(table, mid)
    raise AssertionError("target turn never reached")


def test_legacy_defeated_human_slot_automatically_passes(tmp_path, monkeypatch):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, legacy=True)
    state = until_turn(service, table, mid, target_id, 2)
    actor = service._load_session(mid).engine.state.actors[target_id]
    assert not actor.active and actor.current_hp == 0
    # LIVE round 25 already completes the defeated slot at the engine boundary.
    # The displayed menu now belongs to the next fighter, whose Manual choice
    # must survive; querying the defeated fighter still yields Local Auto.
    assert state["menu"]["actor_id"] != target_id
    assert state["menu"]["manual"]
    assert service._mode_for_actor({"participant_control_modes": {target_id: "MANUAL"}},
                                   service._load_session(mid), target_id) == "LOCAL_AUTO"
    row = next(a for a in state["presentation"]["actors"] if a["entity_id"] == target_id)
    assert row["movement_remaining_ft"] == row["speed_ft"] == 0
    advance(table, mid)
    loaded = service._load_session(mid)
    assert loaded.engine.state.current_actor_id != target_id
    assert any(e.event_type == "TURN_ENDED" and e.actor_id == target_id for e in loaded.engine.events)
    assert not loaded.engine.state.rules
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("recovery,relations", [(False, False), (False, True), (True, False)])
def test_stable_last_opponent_resolves_without_execution_or_losing_recovery(tmp_path, monkeypatch, recovery, relations):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, defeated_side=True, recovery=recovery, relations=relations)
    until_turn(service, table, mid, target_id, 2)
    assert service._load_session(mid).engine.state.terminal_result is None, "dying actors can still roll a natural 20"
    until_turn(service, table, mid, target_id, 5)
    before = service._load_session(mid).engine
    assert before.state.actors[target_id].life_state == "STABLE"
    assert before.state.terminal_result is None
    advance(table, mid)  # End the completed stable turn through the table commit.
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[target_id]
    assert actor.active and actor.current_hp == 0 and actor.life_state == "STABLE"
    assert (loaded.engine.state.relations is not None) == relations
    terminal = loaded.engine.state.terminal_result
    if recovery:
        assert terminal is None, "scheduled recovery must keep the fight open"
    else:
        assert terminal.kind.value == "VICTORY"
        assert terminal.winning_team_id == loaded.engine.state.actors[FACTORY_ACTOR_PREFIX + "sol113-right"].team_id
        assert any(e.event_type == "MATCH_ENDED" for e in loaded.engine.events)
        assert not any(e.event_type == "ENTITY_DEFEATED" and e.actor_id == target_id for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"


def test_stable_incoming_turn_ends_before_native_zone_or_turn_start_effects(tmp_path, monkeypatch):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, defeated_side=True, recovery=True, terminal_zone=True)
    until_turn(service, table, mid, target_id, 5)
    for _ in range(6):
        before = CombatService(ROOT, tmp_path)._load_session(mid).engine
        # LIVE skips the finally defeated ally inside the same End Turn. Stop
        # before the next active slot, not before an inactive intermediate slot.
        order = before.state.initiative_order
        next_id = next(order[(before.state.current_slot_index + offset) % len(order)]
                       for offset in range(1, len(order) + 1)
                       if before.state.actors[order[(before.state.current_slot_index + offset) % len(order)]].active)
        if next_id == target_id:
            break
        advance(table, mid)
    else:
        raise AssertionError("Stable creature's incoming turn was not reached")
    body = before.state.actors[target_id]
    zone = before.state.zones["zone:sol113-terminal"]
    assert zone.active and before._in_zone(body, zone)
    assert body.active and body.life_state == "STABLE" and before.state.terminal_result is None
    assert zone.owner_id != target_id
    assert any(e.event_type == "ZONE_CREATED" and e.payload["zone"]["zone_id"] == zone.zone_id for e in before.events)
    advance(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[target_id]
    assert actor.active and actor.current_hp == 0 and actor.life_state == "STABLE"
    assert life_state._record(actor) == {"ok": 0, "bad": 0}
    assert loaded.engine.state.terminal_result.kind.value == "VICTORY"
    assert loaded.engine.state.terminal_result.winning_team_id == loaded.engine.state.actors[zone.owner_id].team_id
    ended = next(e.sequence for e in loaded.engine.events if e.event_type == "MATCH_ENDED")
    assert not any(e.sequence > ended for e in loaded.engine.events), "No turn-start effects or damage after combat ends"
    assert loaded.engine.state.zones[zone.zone_id].per_turn_triggered == zone.per_turn_triggered
    assert loaded.verify()["status"] == "PASS"


def test_service_battle_manifestation_is_destroyed_and_can_be_called_back(tmp_path, monkeypatch):
    from combat.ext.spirit_bonds import STRAIN
    service, table, mid, target_id = fight(tmp_path, monkeypatch, spirit=True)
    initial = service._load_session(mid).engine
    spirit = next(a for a in initial.state.actors.values() if a.summon and a.summon.get("owner") == target_id)
    assert spirit.active and spirit.summon["status"] == "present"
    spirit_id = spirit.entity_id
    until_turn(service, table, mid, target_id, 2)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[spirit_id]
    assert not actor.active and actor.current_hp == 0 and actor.life_state is None
    assert actor.summon["status"] == "destroyed"
    assert loaded.engine.state.actors[target_id].resources[STRAIN] == 1
    assert any(e.event_type == "ENTITY_DEFEATED" and e.actor_id == spirit_id for e in loaded.engine.events)
    assert not any(e.event_type == "CHECK_ROLLED" and e.actor_id == spirit_id for e in loaded.engine.events)
    state = table.state(mid)
    call_back = next(c for c in loaded.engine.legal_candidates() if c.display_name == "Call Back Bonded Spirit")
    assert state["menu"]["manual"]
    assert loaded.verify()["status"] == "PASS"
    result = table.act(mid, call_back.candidate_id, call_back.decision_id, call_back.state_version, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    called = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = called.engine.state.actors[spirit_id]
    assert actor.active and actor.summon["status"] == "present" and actor.current_hp == actor.maximum_hp
    assert called.engine.state.actors[target_id].resources[STRAIN] == 1
    assert called.verify()["status"] == "PASS"


@pytest.mark.parametrize("left_state,right_state,expected", [
    ("DYING", None, None), ("STABLE", "DYING", None),
    ("STABLE", "STABLE", "DRAW_SIMULTANEOUS"),
    ("STABLE", "CONSCIOUS", "VICTORY"),
])
def test_combat_resolution_waits_for_dying_survivors_and_draws_when_all_stable(left_state, right_state, expected):
    from types import SimpleNamespace
    def actor(name, state):
        return SimpleNamespace(entity_id=name, team_id=name, primary_combatant=True,
                               active=True, life_state=state, current_hp=0 if state else 10, conditions={})
    left, right = actor("left", left_state), actor("right", right_state)
    results = []
    engine = SimpleNamespace(state=SimpleNamespace(rules={"zero_hp": "dying_2024"}, terminal_result=None,
                                                   relations=None, actors={"left": left, "right": right}),
                             _end_match=lambda kind, team, reason: results.append(kind.value))
    life_state.resolve_stable_opponents(engine, left)
    assert results == ([] if expected is None else [expected])


@pytest.mark.parametrize("followup,expected,bad", [
    ("damage", "DYING", 1), ("critical", "DYING", 2),
    ("stable_damage", "DYING", 1), ("massive", None, 0), ("healing", None, 0),
])
def test_table_damage_at_zero_and_healing_are_persisted(tmp_path, monkeypatch, followup, expected, bad):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, followup=followup)
    for _ in range(12):
        engine = service._load_session(mid).engine
        if any(e.source_definition_id == "test:followup" for e in engine.events):
            break
        advance(table, mid)
    else:
        raise AssertionError("follow-up did not commit")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[target_id]
    assert actor.life_state == expected
    if expected:
        assert life_state._record(actor)["bad"] == bad
    elif followup == "healing":
        assert actor.current_hp == 5 and actor.active
        assert not any(c.condition_id == life_state.UNCONSCIOUS for c in actor.conditions.values())
    else:
        assert not actor.active
    assert loaded.verify()["status"] == "PASS"


def test_table_massive_initial_damage_kills_instead_of_dying(tmp_path, monkeypatch):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, excess=120)
    until_turn(service, table, mid, target_id, 2)
    loaded = service._load_session(mid)
    assert not loaded.engine.state.actors[target_id].active
    assert loaded.verify()["status"] == "PASS"


def test_ai_attacks_conscious_enemy_instead_of_downed_enemy(tmp_path, monkeypatch):
    from combat.gate4_context import build_decision_context

    service, table, mid, target_id = fight(tmp_path, monkeypatch)
    until_turn(service, table, mid, target_id, 2)
    foe_id = FACTORY_ACTOR_PREFIX + "sol113-right"
    for _ in range(6):
        engine = service._load_session(mid).engine
        if engine.state.current_actor_id == foe_id:
            break
        advance(table, mid)
    policy, _ = service.policies.for_actor(foe_id)
    raw = build_decision_context(engine, policy, for_ai=False).legal_candidates
    ai = build_decision_context(engine, policy, for_ai=True).legal_candidates
    def attacks(rows, target):
        return [c for c in rows if target in c.target_ids and
                ((engine.action_catalog.get(c.source_definition_id) is not None and engine.action_catalog[c.source_definition_id].attack_bonus is not None)
                 or int(c.metadata.get("expected_damage") or 0) > 0)]
    assert attacks(raw, target_id), "manual attacks on a dying creature remain legal"
    assert not attacks(ai, target_id)
    assert attacks(ai, FACTORY_ACTOR_PREFIX + "sol113-ally")
    moves = [c for c in engine.legal_candidates() if c.kind == "MOVE"]
    exposure = [engine._movement_reaction_exposure(engine.state.actors[foe_id], c.canonical_path) for c in moves]
    assert all(target_id not in reactors for reactors in exposure)
    assert any(FACTORY_ACTOR_PREFIX + "sol113-ally" in reactors for reactors in exposure)


def test_ai_may_finish_two_failed_saves_for_printed_soul_harvest(tmp_path, monkeypatch):
    from combat.ext import soul_warden
    from combat.gate4_context import build_decision_context

    service, table, mid, target_id = fight(tmp_path, monkeypatch, followup="critical", harvest=True)
    foe_id = FACTORY_ACTOR_PREFIX + "sol113-right"
    for _ in range(18):
        engine = service._load_session(mid).engine
        target = engine.state.actors[target_id]
        if engine.state.current_actor_id == foe_id and life_state._record(target)["bad"] == 2:
            break
        advance(table, mid)
    else:
        raise AssertionError("finishing opportunity never reached")
    assert soul_warden.can_harvest(engine, engine.state.actors[foe_id], target)
    policy, _ = service.policies.for_actor(foe_id)
    ai = build_decision_context(engine, policy, for_ai=True)
    assert any(target_id in c.target_ids and int(c.metadata.get("expected_damage") or 0) > 0 for c in ai.legal_candidates)
    service.set_controller_mode(mid, actor_id=foe_id, controller_mode="LOCAL_AUTO")
    assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    loaded = service._load_session(mid)
    assert not loaded.engine.state.actors[target_id].active
    assert loaded.engine.state.actors[foe_id].resources[soul_warden.FRAGMENT] == 1
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("rolls,expected,hp,active", [
    ((12, 12, 12), "STABLE", 0, True),
    ((3, 3, 3), None, 0, False),
    ((1, 3), None, 0, False),
    ((20,), None, 1, True),
])
def test_new_table_death_saves_commit_reload_and_replay(tmp_path, monkeypatch, rolls, expected, hp, active):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, rolls=rolls)
    state = until_turn(service, table, mid, target_id, 2)
    engine = service._load_session(mid).engine
    actor = engine.state.actors[target_id]
    assert engine.state.rules == {"zero_hp": "dying_2024", "finalized_turns": "skip_finalized_v1"}
    assert next(e for e in engine.events if e.event_type == "MATCH_CREATED").payload["rules"] == engine.state.rules
    assert actor.life_state == "DYING" and actor.active and actor.position is not None
    assert not actor.action_available and not actor.reaction_available and actor.movement_remaining_ft == 0
    assert any(c.condition_id == life_state.UNCONSCIOUS for c in actor.conditions.values())
    assert state["menu"]["manual"] and not state["menu"]["moves"] and not state["menu"]["actions"]
    state = until_turn(service, table, mid, target_id, 3)
    if rolls[0] != 20:
        row = next(a for a in state["presentation"]["actors"] if a["entity_id"] == target_id)
        assert row["death_saves"] == {"ok": int(rolls[0] >= 10), "bad": 2 if rolls[0] == 1 else int(rolls[0] < 10)}
    if rolls[0] == 12:
        log = table.events(mid, 0)["events"]
        assert any("death saving throw 1d20 [12]" in e["summary"] and "1 successes, 0 failures" in e["summary"] for e in log)
    state = until_turn(service, table, mid, target_id, 2 + len(rolls))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[target_id]
    assert (actor.life_state, actor.current_hp, actor.active) == (expected, hp, active)
    assert loaded.engine.state.rules == {"zero_hp": "dying_2024", "finalized_turns": "skip_finalized_v1"}
    if hp:
        assert state["menu"]["manual"] and state["menu"]["moves"] and actor.action_available
    assert loaded.verify()["status"] == "PASS"
