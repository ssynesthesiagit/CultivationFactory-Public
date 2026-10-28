"""Internal Echo detonates after the target's first cumulative 10 feet of willing movement."""
import pytest

from tests.test_riders_c7 import FOE, ME, _typed_foe, bundle, fight, turn, use
from combat import ext
from combat.ext import drum_body
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_internal_echo_dispatch import echo
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import HOLD, LEFT, RIGHT, on_hold, table_fight


DRUM = "tianxia.subpath.body.heaven_thunder_drum_body.feature."
ECHOING = "condition:typed.echoing"


def _echoed():
    engine = fight(bundle([DRUM + "internal_echo"]), foe=_typed_foe(), foe_at=(10, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    # Native Reaction fixtures below pay Qi on this Body character.
    foe.resource_maximums["resource:core.qi"] = 2
    from types import SimpleNamespace
    drum_body.echoing(SimpleNamespace(engine=engine, actor=me, target=foe, numbers={"pb": 4, "save_dc": 50, "cl": 18},
                                      source=DRUM + "internal_echo"), {})
    turn(engine, FOE)
    return engine, foe


def _echo(foe):
    return any(c.condition_id == ECHOING for c in foe.conditions.values())


def _thunder(engine):
    return [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "THUNDER"]


def test_ten_feet_of_willing_movement_detonates_the_echo():
    engine, foe = _echoed()
    hp = foe.current_hp
    use(engine, "Move to 12,6", actor_id=FOE)  # 10 feet
    assert not _echo(foe) and len(_thunder(engine)) == 1 and foe.current_hp < hp


def test_less_than_ten_feet_leaves_the_echo_and_a_second_step_completes_it():
    engine, foe = _echoed()
    use(engine, "Move to 11,6", actor_id=FOE)  # 5 feet
    assert _echo(foe) and not _thunder(engine)
    use(engine, "Move to 12,6", actor_id=FOE)  # 5 more: ten in all
    assert not _echo(foe) and len(_thunder(engine)) == 1


def test_forced_movement_does_not_count():
    engine, foe = _echoed()
    from combat import movement_steps
    from combat.gate2_runtime_models import Position
    previous = foe.position
    destination = Position(x=12, y=6)
    with engine._movement_scope(foe, "test:shove", "forced", True):
        foe.position = destination
        movement_steps.landed(engine, foe, previous, destination, None, forced=True)
    assert _echo(foe) and not _thunder(engine)  # ten feet, but pushed: it does not count
    use(engine, "Move to 11,6", actor_id=FOE)  # the same ten feet, walked, counts: 5 ft
    use(engine, "Move to 12,6", actor_id=FOE)  # 5 more
    assert not _echo(foe) and len(_thunder(engine)) == 1

def test_echoes_from_multiple_sources_each_count_the_same_willing_movement():
    engine, foe = _echoed()
    second_source = engine.state.actors[ME]
    engine._apply_condition(foe, ECHOING, DRUM + "internal_echo", FOE,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(second_source.turns_started) + 1}",
                            data={"label": "second source Echo", "pb": 4, "save_dc": 50, "cl": 18})
    use(engine, "Move to 11,6", actor_id=FOE)  # both source instances record 5 ft
    assert len([c for c in foe.conditions.values() if c.condition_id == ECHOING]) == 2
    assert all(c.data["moved_ft"] == 5 for c in foe.conditions.values() if c.condition_id == ECHOING)
    use(engine, "Move to 12,6", actor_id=FOE)  # both reach 10 ft and detonate
    assert not _echo(foe)
    assert len(_thunder(engine)) == 2


def test_movement_counter_is_recorded_as_a_condition_update_for_replay():
    # Finding 1: the running 10-ft total must be a recorded CONDITION_UPDATED, or Gate 3 replay cannot reproduce the post-state.
    engine, foe = _echoed()
    use(engine, "Move to 11,6", actor_id=FOE)  # 5 ft
    updates = [e for e in engine.events if e.event_type == "CONDITION_UPDATED" and FOE in (e.target_ids or ())]
    assert updates and updates[-1].payload["data"]["moved_ft"] == 5
    held = next(c for c in foe.conditions.values() if c.condition_id == ECHOING)
    assert held.data["moved_ft"] == 5  # the live instance matches the recorded data


def test_movement_detonation_damage_is_a_top_level_packet_not_nested_in_an_event_hook(monkeypatch):
    # Finding 2: the 3d8 Thunder must not be resolved inside another event's hook, where its own riders do not run.
    # _ext_in_event is True for every root event's hooks (it cannot tell root from nested), so the probe reads the dispatch
    # depth instead: a hook running for a root event sees depth 1; a packet nested in another event's hook would see 2 or more.
    seen = []

    def probe(engine, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and (kwargs.get("payload") or {}).get("damage_type") == "THUNDER":
            seen.append(int(getattr(engine, "_ext_event_depth", 0)))

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), probe])
    engine, foe = _echoed()
    use(engine, "Move to 12,6", actor_id=FOE)  # 10 ft detonates
    assert seen == [1]


def test_accepted_reaction_spends_cost_and_reaction_before_echo_then_resolves(monkeypatch):
    # The real generic-reaction path must commit its economy before Internal Echo,
    # and the already-committed Reaction cannot defend against the detonation.
    from combat.typed_reactions import on_own_event

    engine, foe = _echoed()
    foe.resources["resource:core.qi"] = 2
    row = {"block": "generic", "feature_id": "test:echo_triggering_reaction", "kind": "own_ability",
           "name": "Echo-triggered response", "ask": False,
           "costs": [{"resource_id": "resource:core.qi", "amount": 1}],
           "effects": [{"type": "damage", "applies_to": "target",
                        "dice": {"count": 1, "sides": 4}, "damage_types": ["fire"]}]}
    engine.typed_reaction_rows[FOE].append(row)
    states_at_echo = []

    def observe(engine_, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and (kwargs.get("payload") or {}).get("damage_type") == "THUNDER":
            states_at_echo.append((foe.reaction_available, foe.resources["resource:core.qi"]))

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), observe])
    on_own_event(engine, foe, engine.state.actors[ME], "own_ability", source_id="test:trigger")

    assert states_at_echo == [(False, 1)]
    assert not _echo(foe) and len(_thunder(engine)) == 1
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == row["feature_id"]
               for e in engine.events)  # the committed Reaction continues after its own detonation
    assert drum_body.echo_detonates_on_reaction in ext._HOOKS["reaction_committed"]


def test_native_open_reaction_can_defer_notification_until_after_source_costs():
    from combat.typed_reactions import open_reaction, _notify_reaction_committed

    engine, foe = _echoed()
    foe.resources['resource:core.qi'] = 2
    row = {'feature_id': 'test:paid_native_reaction'}
    assert open_reaction(engine, row, foe, (ME,), 'test_paid', notify=False)
    assert _echo(foe) and foe.reaction_available is False
    foe.resources['resource:core.qi'] -= 1
    _notify_reaction_committed(engine, foe, row)
    assert foe.resources['resource:core.qi'] == 1
    assert not _echo(foe) and len(_thunder(engine)) == 1


def test_native_open_reaction_detonates_echo_after_reserving_reaction():
    from combat.typed_reactions import open_reaction

    engine, foe = _echoed()
    open_reaction(engine, {"feature_id": "test:native_reaction"}, foe, (ME,), "test_native")
    assert not _echo(foe) and len(_thunder(engine)) == 1
    assert foe.reaction_available is False


def test_echo_dropping_generic_reactor_interrupts_resolution():
    from combat.typed_reactions import _spend_generic

    engine, foe = _echoed()
    foe.current_hp = 1
    row = {"feature_id": "test:lethal_echo_reaction", "costs": [{"resource_id": "resource:core.qi", "amount": 1}]}
    foe.resources["resource:core.qi"] = 2
    assert _spend_generic(engine, foe, row) is False
    assert not foe.active and foe.resources["resource:core.qi"] == 1
    assert not _echo(foe) and len(_thunder(engine)) == 1


def test_accepted_generic_reaction_dropping_reactor_skips_effects():
    from combat.typed_reactions import on_own_event

    engine, foe = _echoed()
    foe.current_hp = 1
    foe.resources["resource:core.qi"] = 2
    row = {"block": "generic", "feature_id": "test:lethal_echo_response", "kind": "own_ability",
           "name": "Echo-triggered response", "ask": False,
           "costs": [{"resource_id": "resource:core.qi", "amount": 1}],
           "effects": [{"type": "damage", "applies_to": "target",
                        "dice": {"count": 1, "sides": 4}, "damage_types": ["fire"]}]}
    engine.typed_reaction_rows[FOE].append(row)
    on_own_event(engine, foe, engine.state.actors[ME], "own_ability", source_id="test:trigger")
    assert not foe.active and foe.resources["resource:core.qi"] == 1
    assert len(_thunder(engine)) == 1
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == row["feature_id"]
                   for e in engine.events)
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "FIRE"
                   for e in engine.events)


def test_accepted_native_reaction_reports_lethal_echo_before_effect_resolution():
    from combat.typed_reactions import open_reaction

    engine, foe = _echoed()
    foe.current_hp = 1
    accepted = open_reaction(engine, {"feature_id": "test:lethal_native_reaction"}, foe, (ME,), "test_native")
    assert accepted is False
    assert not foe.active and foe.reaction_available is False
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "test:lethal_native_reaction"
                   for e in engine.events)


def test_generic_reaction_payment_detonates_after_its_cost_is_paid():
    from combat.typed_reactions import _spend_generic

    engine, foe = _echoed()
    foe.resources["resource:core.qi"] = 2
    row = {"feature_id": "test:generic_echo_reaction", "costs": [{"resource_id": "resource:core.qi", "amount": 1}]}
    assert _spend_generic(engine, foe, row)
    assert foe.resources["resource:core.qi"] == 1
    assert not _echo(foe) and len(_thunder(engine)) == 1


def test_intercepted_reaction_reserves_before_payment_and_does_not_raise_on_lethal_echo(monkeypatch):
    # Exercise the actual intercepted range-reduction branch: reservation precedes
    # payment, and lethal Echo interrupts the accepted reaction without effects.
    from combat import typed_reactions

    engine, foe = _echoed()
    foe.current_hp = 1
    foe.resources["resource:core.qi"] = 2
    row = {"feature_id": "test:intercepted_echo_reaction", "name": "Intercepted response",
           "range_ft": 100, "costs": [{"resource_id": "resource:core.qi", "amount": 1}]}
    monkeypatch.setitem(ext._HOOKS, "technique_declared", [
        lambda *args: {"source_id": "test:range_interceptor", "label": "Shortened reach", "range_delta_ft": -200}])
    with typed_reactions._reaction_activation(engine, foe, engine.state.actors[ME], row) as permitted:
        assert permitted is False
    assert foe.reaction_available is False and foe.resources["resource:core.qi"] == 1
    assert not foe.active and len(_thunder(engine)) == 1
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == row["feature_id"]
                   for e in engine.events)




def test_iron_rain_readiness_stops_when_echo_interrupts_reaction(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from combat.ext import equipment_armor
    from combat import save_context

    _combat, table, mid = table_fight(tmp_path, [])
    feature = equipment_armor.T + "iron_rain_readiness"
    pool = "resource:core.qi"
    row = {"feature_id": feature, "costs": [{"resource_id": pool, "amount": 2}],
           "numbers": {"pb": 4}}
    saved = SimpleNamespace(ability="DEX", failed=True, area=True, action_name="blast")
    asked = []
    monkeypatch.setattr(equipment_armor, "rows", lambda engine, actor, kind:
                        [row] if actor.entity_id == LEFT and kind == "iron_rain_area" else [])
    monkeypatch.setattr(save_context, "damage_save", lambda engine, target, source, attacker:
                        saved if target == LEFT and source == "test:blast" else None)
    monkeypatch.setattr(save_context, "damage_response_state", lambda *args: {})

    def accept(*args, **kwargs):
        asked.append(kwargs["feature_id"])
        return ["use"]

    monkeypatch.setattr(equipment_armor, "ask", accept)

    def trigger(engine):
        actor, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._commit_damage(actor, actor.current_hp - 1, "FORCE", "test:injury", RIGHT, None, reaction_depth=99)
        echo(engine, actor, enemy)
        # Supply the actual Reaction row as well as its passive trigger. The
        # old fixture had neither the correct feature id nor a Reaction row.
        engine.typed_reaction_rows[LEFT].append(row)
        assert actor.current_hp == 1 and actor.reaction_available and _echo(actor)
        assert actor.resources[pool] == 30
        before = len(asked)
        engine._commit_damage(actor, 10, "FIRE", "test:blast", RIGHT, engine._active_intent, reaction_depth=0)
        assert asked[before:] == [feature]

    on_hold(monkeypatch, trigger)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine, actor = loaded.engine, loaded.engine.state.actors[LEFT]
    assert asked and actor.current_hp == 0 and actor.life_state == "DYING"
    assert not actor.reaction_available and actor.resources[pool] == 28
    assert not _echo(actor) and len(_thunder(engine)) == 1
    payment = next(e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == feature)
    assert payment.sequence < _thunder(engine)[0].sequence
    assert not any(e.source_definition_id == feature and e.event_type == "REACTION_RESOLVED" for e in engine.events)
    assert not any(r.reason.startswith("DAMAGE_REDUCTION:") for r in engine.rolls)
    incoming = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "test:blast")
    assert incoming.payload["reduced_to"] == 10
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_stamina_guard_echo_interruption_does_not_apply_soak_or_resolved_receipt():
    from combat import typed_reactions

    engine, foe = _echoed()
    foe.current_hp = 1
    foe.resources["resource:core.stamina"] = 2
    row = {"block": "damage_soak", "feature_id": "test:echo_stamina_guard", "name": "Stamina Guard",
           "trigger": "any_damage", "minimum_damage": 1, "resource_id": "resource:core.stamina",
           "die": 10, "max_spend": 1}
    engine.typed_reaction_rows[FOE].append(row)

    remaining = typed_reactions.on_damage(engine, foe, 7, 0, source_definition_id="test:incoming",
                                          source_actor_id=ME)

    assert remaining == 7
    assert foe.resources["resource:core.stamina"] == 1
    assert foe.reaction_available is False and not foe.active
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == row["feature_id"]
                   for e in engine.events)
    assert len(_thunder(engine)) == 1


def test_checkpoint_response_reports_lethal_echo_before_native_consumer_applies_followup():
    from combat.typed_reactions import commit_checkpoint_response

    engine, foe = _echoed()
    foe.current_hp = 1
    foe.resources["resource:core.qi"] = 2
    row = {"feature_id": "test:checkpoint_echo_reaction",
           "costs": [{"resource_id": "resource:core.qi", "amount": 1}]}
    assert commit_checkpoint_response(engine, foe, foe, row, "TEST_CHECKPOINT") is False
    assert foe.resources["resource:core.qi"] == 1 and not foe.active
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == row["feature_id"]
                   for e in engine.events)


def test_featherfall_native_consumer_stops_when_echo_drops_its_owner(monkeypatch):
    from combat.ext import talismans, needle

    engine, foe = _echoed()
    owner = engine.state.actors[ME]
    engine._apply_condition(owner, ECHOING, DRUM + "internal_echo", FOE,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(foe.turns_started) + 1}",
                            data={"label": "lethal Echo", "pb": 4, "save_dc": 50, "cl": 18})
    owner.current_hp = 1
    row = {"feature_id": talismans.FEATHERFALL_TALENT}
    monkeypatch.setattr(talismans, "_reaction_row", lambda engine_, actor, kind: row if actor is owner else None)
    monkeypatch.setattr(talismans, "available", lambda *args: True)
    monkeypatch.setattr(talismans, "_descending", lambda *args: False)
    monkeypatch.setattr(engine, "_distance_actor_to_actor", lambda *args: 5)
    foe.position.z = 1  # A real unsupported falling target, not a stale module-local import.
    monkeypatch.setattr(needle, "ask", lambda *args, **kwargs: [FOE])
    spent = []
    monkeypatch.setattr(talismans, "use_up", lambda *args: spent.append(owner.entity_id) or True)

    talismans.featherfall_talisman(engine, [foe], None)

    assert spent == [owner.entity_id] and not owner.reaction_available
    assert not owner.active and not any(c.condition_id == talismans.FEATHERFALL_CONDITION
                                        for c in foe.conditions.values())
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == talismans.FEATHERFALL_TALENT
                   for e in engine.events)


def test_native_reaction_detonates_every_echo_source_once():
    from combat.typed_reactions import open_reaction

    engine, foe = _echoed()
    engine._apply_condition(foe, ECHOING, DRUM + "internal_echo", FOE,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(foe.turns_started) + 1}",
                            data={"label": "second source Echo", "pb": 4, "save_dc": 50, "cl": 18})
    open_reaction(engine, {"feature_id": "test:two_source_native"}, foe, (ME,), "test_native")
    assert not _echo(foe)
    assert len(_thunder(engine)) == 2


def test_generic_commit_notification_is_idempotent_within_activation(monkeypatch):
    from combat.typed_reactions import _notify_reaction_committed

    engine, foe = _echoed()
    calls = []
    monkeypatch.setitem(ext._HOOKS, "reaction_committed", [lambda *args: calls.append(True)])
    with engine._transaction("test:one_reaction", "intent:one_reaction", FOE):
        row = {"feature_id": "test:one_feature"}
        _notify_reaction_committed(engine, foe, row)
        _notify_reaction_committed(engine, foe, row)
    assert calls == [True]




def test_long_weapon_opportunity_attack_stops_after_lethal_echo(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import weapons_second_pass
    from combat import movement_steps, target_knowledge, targeting
    from combat import typed_reactions as tr
    from combat.ext import rider_choices, hand_occupancy
    from combat import weapon_delivery, ext

    engine, guard = _echoed()
    mover = engine.state.actors[ME]
    guard.current_hp = 1
    action = SimpleNamespace(
        parameters={"typed": {"weapon": {"properties": "Reach"}}, "requires_hands": 1},
        source_definition_id="test:reach_weapon")
    row = {"feature_id": "test:long_weapon_measure", "action_id": "test:long_weapon_measure"}
    monkeypatch.setattr(weapons_second_pass, "owned", lambda *args: row)
    monkeypatch.setattr(movement_steps, "opportunity_exempt", lambda *args: False)
    monkeypatch.setattr(target_knowledge, "can_see", lambda *args: True)
    monkeypatch.setattr(targeting, "line_of_effect", lambda *args, **kwargs: True)
    monkeypatch.setattr(tr, "opportunity_reach", lambda *args: 10)
    monkeypatch.setattr(tr, "opportunity_profile", lambda *args: (row, action, 10))
    monkeypatch.setattr(weapon_delivery, "weapon_identity", lambda *args, **kwargs: "test:weapon")
    monkeypatch.setattr(hand_occupancy, "weapon_grips", lambda *args: {"test:weapon"})
    monkeypatch.setattr(hand_occupancy, "weapon_capacity", lambda *args: 1)
    previous = mover.position.model_copy(update={"x": mover.position.x - 1})
    real_distance = engine._distance_actor_to_actor
    def distance(*args, **kwargs):
        if "actor_position" in kwargs:
            return 15 if kwargs["actor_position"] == previous else 5
        return real_distance(*args, **kwargs)
    monkeypatch.setattr(engine, "_distance_actor_to_actor", distance)
    monkeypatch.setattr(tr, "wants_opportunity_attack", lambda *args, **kwargs: True)
    monkeypatch.setattr(rider_choices, "pick", lambda *args, **kwargs: True)
    monkeypatch.setattr(ext, "any_false", lambda *args: False)
    attacks = []
    monkeypatch.setattr(tr, "opportunity_attack", lambda *args, **kwargs: attacks.append(True))

    weapons_second_pass.entering_reach(engine, mover, previous, mover.position, None)
    assert not guard.active and len(_thunder(engine)) == 1
    assert not attacks
    assert guard.turn_flags.get(weapons_second_pass.ROUND) is None


def test_helicopter_descent_skips_its_condition_when_echo_interrupts_reaction(tmp_path, monkeypatch):
    from combat.ext import athletics
    from combat.gate2_runtime_models import Position

    _combat, table, mid = table_fight(tmp_path, [])
    row = {"feature_id": athletics.HELICOPTER, "fall_speed_ft": 60}
    asked = []
    monkeypatch.setattr(athletics, "row_of", lambda engine, actor, kind:
                        row if actor.entity_id == LEFT and kind == "helicopter_descent" else None)
    monkeypatch.setattr(athletics, "helicopter_gear", lambda *args: ["rope"])

    def accept(*args, **kwargs):
        asked.append(kwargs["feature_id"])
        return ["descend"]

    monkeypatch.setattr(athletics, "ask", accept)

    def prepare(engine):
        actor, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._commit_damage(actor, actor.current_hp - 1, "FORCE", "test:injury", RIGHT, None, reaction_depth=99)
        # A recorded flight fixture keeps the owner airborne until End Turn.
        engine._apply_condition(actor, "condition:test.flight", "test:flight", LEFT, expires_on="UNTIL_REMOVED",
                                data={"fly_speed_ft": 30})
        previous = actor.position
        actor.position = Position(x=previous.x, y=previous.y, z=1)
        engine._append_event("MOVEMENT_COMMITTED", "test:ascent", actor_id=LEFT,
            payload={"destination": actor.position.model_dump(mode="json"),
                     "path": [previous.model_dump(mode="json"), actor.position.model_dump(mode="json")],
                     "cost_ft": 0, "forced": True})
        echo(engine, actor, enemy)

    with monkeypatch.context() as setup:
        on_hold(setup, prepare)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT]
    assert cold.position.z == 1 and cold.current_hp == 1 and _echo(cold)
    assert cold.reaction_available and cold.resources[athletics.FOCUS] == 1
    assert not asked
    # TURN_ENDED dispatches the real turn_end hook; do not call the consumer.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine, actor = loaded.engine, loaded.engine.state.actors[LEFT]
    assert asked and set(asked) == {athletics.HELICOPTER}
    assert actor.current_hp == 0 and actor.life_state == "DYING"
    assert not actor.reaction_available and actor.resources[athletics.FOCUS] == 0
    assert not any(c.condition_id == athletics.HELICOPTER_CONDITION for c in actor.conditions.values())
    assert not _echo(actor) and len(_thunder(engine)) == 1
    payment = next(e for e in engine.events if e.event_type == "RESOURCE_SPENT"
                   and e.source_definition_id == athletics.HELICOPTER)
    assert payment.sequence < _thunder(engine)[0].sequence
    assert not any(e.source_definition_id == athletics.HELICOPTER
                   and e.event_type == "REACTION_RESOLVED" for e in engine.events)
    notes = [e.payload["log"] for e in engine.events
             if e.source_definition_id == athletics.HELICOPTER and e.event_type == "PASSIVE_TRIGGERED"]
    assert notes == [f"{actor.display_name} cannot finish this reaction after paying its cost."]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_hunger_fang_does_not_grant_temporary_hp_after_lethal_echo(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from combat.ext import hunger_riders

    _combat, table, mid = table_fight(tmp_path, [])
    pool = "resource:core.qi"
    asked = []
    monkeypatch.setattr(hunger_riders, "_modern", lambda actor: SimpleNamespace(
        data={"fang_meal_eligible": True, "fang_type": "acid"}) if actor.entity_id == LEFT else None)
    monkeypatch.setattr(hunger_riders, "row_of", lambda engine, actor, kind:
                        {"pb": 4} if actor.entity_id == LEFT and kind == "fang" else None)

    def accept(*args, **kwargs):
        asked.append(kwargs["name"])
        return ["use"]

    monkeypatch.setattr(hunger_riders, "ask", accept)

    def trigger(engine):
        actor, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._commit_damage(actor, actor.current_hp - 1, "FORCE", "test:injury", RIGHT, None, reaction_depth=99)
        echo(engine, actor, enemy)
        assert actor.current_hp == 1 and actor.reaction_available and _echo(actor)
        assert hunger_riders._cp(actor) == pool and actor.resources[pool] == 30
        before = len(asked)
        # Damage commitment invokes final_damage through the shared dispatcher.
        engine._commit_damage(actor, 8, "ACID", "test:acid", RIGHT, engine._active_intent, reaction_depth=0)
        assert asked[before:] == ["Devour the Venom, Keep the Fang"]

    on_hold(monkeypatch, trigger)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine, actor = loaded.engine, loaded.engine.state.actors[LEFT]
    assert asked and actor.current_hp == 0 and actor.life_state == "DYING"
    assert not actor.reaction_available and actor.resources[pool] == 29
    assert actor.temporary_hp == 0
    assert not _echo(actor) and len(_thunder(engine)) == 1
    payment = next(e for e in engine.events if e.event_type == "RESOURCE_SPENT"
                   and e.source_definition_id == hunger_riders.FANG)
    assert payment.sequence < _thunder(engine)[0].sequence
    assert not any(e.source_definition_id == hunger_riders.FANG
                   and e.event_type in ("TEMP_HP_GRANTED", "REACTION_RESOLVED") for e in engine.events)
    incoming = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "test:acid")
    assert incoming.payload["reduced_to"] == 8
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_retried_transaction_notifies_reaction_again_after_rollback(monkeypatch):
    from combat.typed_reactions import _notify_reaction_committed

    engine, foe = _echoed()
    calls = []
    monkeypatch.setitem(ext._HOOKS, "reaction_committed", [lambda *args: calls.append(True)])
    row = {"feature_id": "test:retry_feature"}
    for _ in range(2):
        with pytest.raises(RuntimeError, match="pause after notification"):
            with engine._transaction("test:retry", "intent:same_retry", FOE):
                _notify_reaction_committed(engine, foe, row)
                raise RuntimeError("pause after notification")
    assert calls == [True, True]


def test_lethal_first_echo_still_consumes_every_echo_triggered_by_reaction():
    from combat.typed_reactions import open_reaction

    engine, foe = _echoed()
    # Both Echo owners remain up: the target is not its own second attacker.
    source = engine.state.actors[ME].model_copy(deep=True)
    source.entity_id = "actor:test.second_echo_source"
    engine.state.actors[source.entity_id] = source
    foe.current_hp = 1
    engine._apply_condition(foe, ECHOING, DRUM + "internal_echo", source.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(source.turns_started) + 1}",
                            data={"label": "second source Echo", "pb": 4, "save_dc": 50, "cl": 18})
    open_reaction(engine, {"feature_id": "test:lethal_two_source"}, foe, (ME,), "test_native")
    assert not foe.active
    assert not _echo(foe)
    assert len(_thunder(engine)) == 2


def test_echo_label_does_not_claim_unwired_cultivation_point_trigger():
    engine, foe = _echoed()
    held = next(c for c in foe.conditions.values() if c.condition_id == ECHOING)
    assert "Action, Bonus Action, or Reaction" in held.data["label"] and "willingly moves" in held.data["label"]
    assert "Cultivation Point" not in held.data["label"] and "CP" not in held.data["label"]


def test_spend_reaction_allows_a_waiver_after_the_normal_reaction_is_used(monkeypatch):
    from combat.typed_reactions import spend_reaction

    engine, foe = _echoed()
    foe.reaction_available = False
    monkeypatch.setitem(ext._HOOKS, "reaction_spend", [lambda engine_, actor, row, commit: "free"])
    spend_reaction(engine, foe, {"feature_id": "test:waived_reaction"})
    assert foe.reaction_available is False


def test_stale_reaction_waiver_decision_falls_through_to_normal_reaction_check(monkeypatch):
    from combat.typed_reactions import spend_reaction

    engine, foe = _echoed()
    monkeypatch.setitem(ext._HOOKS, "reaction_spend", [])
    foe.reaction_available = False
    engine._typed_reaction_waived = {(foe.entity_id, "test:stale"): (-1, False)}
    with pytest.raises(ValueError, match="already used its Reaction"):
        spend_reaction(engine, foe, {"feature_id": "test:stale"})


def test_willing_movement_inside_an_event_hook_still_counts_toward_the_echo(monkeypatch):
    # Review finding 3: a willing step produced while an event hook runs (a nested event) must still count. The counter rides the
    # movement seam (movement_progress_committed), not a root-only event point, so the first 10 ft still detonates the Echo.
    from combat import movement_steps
    from combat.gate2_runtime_models import Position
    engine, foe = _echoed()
    seen = []

    def nested_steps(engine_, event_type, kwargs):
        if event_type != "TEST_NESTED_STEPS":
            return
        for x in (11, 12):
            previous, destination = foe.position, Position(x=x, y=6)
            with engine._movement_scope(foe, "test:nested_step", "walk", False):
                foe.position = destination
                movement_steps.landed(engine, foe, previous, destination, None)
            seen.append(_echo(foe))

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), nested_steps])
    engine._append_event("TEST_NESTED_STEPS", "test:nested_probe", actor_id=FOE)
    assert seen == [True, False]  # 5 ft, then the first 10 ft detonates it
    assert len(_thunder(engine)) == 1


def test_a_rolled_back_step_restores_the_echo_counter():
    # Review finding 4: the counter is written onto the live instance. The transaction rollback restores a deep copy of state, so
    # the feet walked inside a resolution that then fails must not stay on the Echo. Mid-transaction the counter must read 5.
    from combat import movement_steps
    from combat.gate2_runtime_models import Position
    engine, foe = _echoed()
    previous, destination = foe.position, Position(x=11, y=6)
    seen = {}
    with pytest.raises(RuntimeError):
        with engine._transaction("test:rolled_back_step", "intent:rolled_back_step", FOE):
            with engine._movement_scope(foe, "test:rolled_back_step", "walk", False):
                foe.position = destination
                movement_steps.landed(engine, foe, previous, destination, None)
            seen["mid"] = next(c for c in foe.conditions.values() if c.condition_id == ECHOING).data.get("moved_ft")
            raise RuntimeError("resolution failed after the step")
    assert seen["mid"] == 5
    foe = engine.state.actors[FOE]
    held = next(c for c in foe.conditions.values() if c.condition_id == ECHOING)
    assert held.data.get("moved_ft", 0) == 0 and foe.position == previous
