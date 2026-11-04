"""Paid relocation is decided from real assignments and activation-owned debits.

The consumer and actions here are intentionally synthetic. They exercise the
general seam through CombatService, the persisted mechanical execute_intent,
cold reload and mechanical replay; they do not claim a Meridian Lock catalogue
sweep. Ordinary native movement, teleport, forced movement and reactions still
perform their real work. In particular, a silent round trip has no movement
event or net displacement for an event-only/final-position guard to discover.
"""
from copy import deepcopy
import json

import pytest

from combat import ext, paid_relocation
from combat.factory_compiler import compile_character
from combat.gate2_engine import SYSTEM_OPPORTUNITY
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, Position, ReactionDecision, ZoneState
from combat.gate5_service import CombatService
from tests.test_auto_docket import ROOT, ME, _sheet
from tests.test_lock_choices import install


SOURCE = "action:test.paid_relocation"
PREPARE = "action:test.paid_relocation.prepare"
REACTION = "reaction:test.paid_relocation.hostile"
MARKER = "condition:typed.test_paid_relocation"
QI = "resource:core.qi"
STAMINA = "resource:core.stamina"
RESONANCE = "resource:core.resonance"
FOCUS = "resource:core.martial_focus"
AN_STAMINA = "resource:an_eui.stamina"
CP = frozenset((QI, STAMINA, RESONANCE, AN_STAMINA, "resource:lee_jia.qi"))


def _intent(session, pick=None, reactions=(), *, options=None):
    candidate = next(c for c in session.engine.legal_candidates()
                     if (pick(c) if pick else c.kind.value == "END_TURN"))
    # An aborted attempt leaves the state version unchanged, but a retry is a
    # new client request and must not reuse its persistence transaction ID.
    attempt = sum(json.loads(line)["record_type"] == "PREPARE"
                  for line in session.store.journal_path.read_text().splitlines())
    return ActionIntent(
        intent_id=f"paid-relocation:{session.engine.state.state_version}:{attempt}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids if options is None else options,
        reaction_decisions=tuple(reactions))


def _no_swallowed_test_failure(engine):
    assert not any(event.event_type == "GM_RIDER" and
                   (event.source_definition_id == f"ext:{__name__}" or
                    "test.paid_relocation" in event.source_definition_id or
                    "test_paid_relocation_guard" in str(event.payload))
                   for event in engine.events), "an assertion or veto was swallowed by a hook"


def _cold(data, mid):
    session = CombatService(ROOT, data)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    assert paid_relocation.current_activation(session.engine) is None
    _no_swallowed_test_failure(session.engine)
    return session


def _execute(data, mid, pick=None, reactions=(), *, options=None):
    session = CombatService(ROOT, data)._load_session(mid)
    session.mechanical.execute_intent(_intent(session, pick, reactions, options=options))
    assert paid_relocation.current_activation(session.engine) is None
    return _cold(data, mid)


def _snapshot(engine):
    return (engine.state.model_dump(mode="json"),
            [event.model_dump(mode="json") for event in engine.events],
            [roll.model_dump(mode="json") for roll in engine.rolls], engine.roller.counter)


def _commit_count(session):
    return sum(json.loads(line)["record_type"] == "COMMIT"
               for line in session.store.journal_path.read_text().splitlines())


def _veto(data, session, pick=None, reactions=()):
    engine = session.engine
    before, commits = _snapshot(engine), _commit_count(session)
    intent = _intent(session, pick or (lambda c: c.source_definition_id == SOURCE), reactions)
    with pytest.raises(paid_relocation.RelocationVeto, match="test relocation restriction"):
        session.mechanical.execute_intent(intent)
    assert _snapshot(engine) == before, "veto must restore state, economy, resources, events and rolls"
    assert paid_relocation.current_activation(engine) is None
    cold = _cold(data, session.match_id)
    assert _snapshot(cold.engine) == before
    assert _commit_count(cold) == commits, "a vetoed action must not gain a COMMIT"
    return cold


def _setup(data, monkeypatch, body=None, *, costs=(), prepare=None, guard=True,
           me_at=(3, 6), foe_at=(14, 6), reaction_rows=()):
    """Seal the test effects in a real compiled bundle before creating the save."""
    def actions(info):
        def action(source, effect, economy, price):
            return ActionDefinition(source_definition_id=source, display_name=source,
                owner_id=info["actor_id"], economy=economy, resolution_kind="TYPED",
                target_kind="SELF", costs=tuple(price), parameters={"typed": {
                    "source": source, "numbers": info["numbers"],
                    "effects": [{"type": effect}]}})
        return [action(SOURCE, "test_paid_relocation_body", "ACTION", costs),
                action(PREPARE, "test_paid_relocation_prepare", "NONE", ())]

    install(monkeypatch, "compile_actions", actions)
    monkeypatch.setitem(ext.effects(), "test_paid_relocation_body",
                        lambda ctx, row: body(ctx) if body else None)
    monkeypatch.setitem(ext.effects(), "test_paid_relocation_prepare",
                        lambda ctx, row: prepare(ctx) if prepare else None)
    seen = []

    def restriction(engine, actor, previous, destination):
        if actor.entity_id != ME:
            return None
        assert engine.state.actors[ME] is actor
        assert actor.position == previous, "the guard runs before assignment"
        assert previous != destination
        frame = paid_relocation.current_activation(engine)
        assert frame is not None and frame.actor_id == ME
        seen.append((previous, destination, frame.source_id))
        return paid_relocation.Restriction("test relocation restriction", CP)

    if guard:
        install(monkeypatch, "paid_relocation_guard", restriction)
    else:
        install(monkeypatch, "paid_relocation_guard", lambda *args: None)
        # No registered subscribers is the production default. Keep that exact
        # path distinct from a subscriber that declines to impose a restriction.
        monkeypatch.setitem(ext._HOOKS, "paid_relocation_guard", [])
    document = deepcopy(_sheet([]))
    document["ability_scores_and_statistics"]["primary_resource"] = {
        "name": "Qi", "maximum": 30,
        "definitions": [{"name": name, "maximum": 30} for name in ("Stamina", "Resonance")]}
    bundle = compile_character(document, actor_id=ME)
    if reaction_rows:
        from combat.canonical import canonical_sha256
        bundle["typed_reactions"].extend(deepcopy(reaction_rows))
        bundle["bundle_sha256"] = canonical_sha256({
            key: value for key, value in bundle.items() if key != "bundle_sha256"})
    session = CombatService(ROOT, data).persistence.create_match(
        match_seed="PAID-RELOCATION", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [ME, AN],
                      "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]},
                                             AN: {"x": foe_at[0], "y": foe_at[1]}}})
    while session.engine.state.current_actor_id != ME:
        session = _execute(data, session.match_id)
    # Begin every action from a cold-loaded state, so rollback compares journal
    # event enrichment with journal event enrichment rather than live objects.
    return _cold(data, session.match_id), seen


def _move(engine, actor, destination, source=SOURCE, **payload):
    previous = actor.position
    actor.position = destination
    engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
        payload={"destination": destination.model_dump(mode="json"), "cost_ft": 0,
                 "path": [previous.model_dump(mode="json"), destination.model_dump(mode="json")],
                 **payload})


def _shape(ctx, shape):
    actor, engine = ctx.actor, ctx.engine
    start = actor.position
    end = start.model_copy(update={"x": start.x + 1})
    if shape == "walk":
        engine.grant_movement(actor, (start, end), ctx.source, feet=5, intent=ctx.intent)
    elif shape == "fly":
        engine.grant_movement(actor, (start, start.model_copy(update={"z": 1})),
            ctx.source, feet=5, intent=ctx.intent, mode="fly")
    elif shape == "teleport":
        from combat.typed_executor import teleport_subject
        teleport_subject(ctx, actor, start.model_copy(update={"x": start.x + 2}))
    elif shape == "push_self":
        engine.move_path(actor, (start, end), ctx.source, kind="forced",
                         intent=ctx.intent, source_actor_id=actor.entity_id)
    elif shape == "swap":
        other = engine.state.actors[AN]
        there = other.position
        # Move the other actor first: veto must roll that partial swap back too.
        _move(engine, other, start, ctx.source, teleport=True)
        _move(engine, actor, there, ctx.source, teleport=True)
    elif shape == "vertical":
        from combat.falling import displace
        displace(engine, actor, 1, ctx.source, intent=ctx.intent)
    elif shape == "round_trip":
        # Deliberately no events and no final position change.
        actor.position = end
        actor.position = start
    else:
        assert shape == "direct"
        _move(engine, actor, end, ctx.source)


@pytest.mark.parametrize("shape", ["direct", "walk", "fly", "teleport", "push_self", "swap", "vertical", "round_trip"])
@pytest.mark.parametrize("paid", [False, True])
def test_paid_and_free_actual_assignment_paths_commit_reload_replay(tmp_path, monkeypatch, shape, paid):
    if shape == "fly":
        install(monkeypatch, "flight", lambda engine, actor:
                {"fly_speed_ft": 30} if actor.entity_id == ME else None)
    session, seen = _setup(tmp_path, monkeypatch, lambda ctx: _shape(ctx, shape),
                           costs=((QI, 1),) if paid else ())
    original = session.engine.state.actors[ME].position
    if paid:
        _veto(tmp_path, session)
        assert seen
        return
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
    actor = cold.engine.state.actors[ME]
    assert seen, "the allowed control must actually change its live position"
    if shape in ("round_trip", "vertical"):
        assert actor.position == original
        if shape == "vertical":
            assert any(event.payload.get("fall_distance_ft") == 5 for event in cold.engine.events)
    elif shape == "fly":
        assert actor.position.z == 1
    else:
        assert actor.position != original
    if shape == "swap":
        assert cold.engine.state.actors[AN].position == original
    assert actor.resources[QI] == 30


@pytest.mark.parametrize("costs,blocked", [
    (((QI, 1),), True), (((STAMINA, 1),), True), (((RESONANCE, 1),), True),
    (((FOCUS, 1),), False), (((FOCUS, 1), (QI, 1)), True), (((QI, 0),), False),
])
def test_actual_resource_payments_distinguish_focus_and_zero(tmp_path, monkeypatch, costs, blocked):
    session, _ = _setup(tmp_path, monkeypatch, lambda ctx: _shape(ctx, "direct"), costs=costs)
    if blocked:
        _veto(tmp_path, session)
    else:
        before = dict(session.engine.state.actors[ME].resources)
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert cold.engine.state.actors[ME].position == Position(x=4, y=6)
        for resource, amount in costs:
            assert cold.engine.state.actors[ME].resources[resource] == before[resource] - amount


@pytest.mark.parametrize("mode", ["walk", "fly", "jump"])
@pytest.mark.parametrize("paid", [False, True])
def test_native_move_candidates_include_walk_fly_and_jump(tmp_path, monkeypatch, mode, paid):
    if mode == "fly":
        install(monkeypatch, "flight", lambda engine, actor:
                {"fly_speed_ft": 30} if actor.entity_id == ME else None)
    session, seen = _setup(tmp_path, monkeypatch)
    if paid:
        # This fee is after a native step, not an ActionDefinition's listed
        # cost. Earlier assignment receipts must make the entire MOVE atomic.
        def fee(engine, mover, previous, destination, intent):
            if mover.entity_id == ME:
                engine._spend_resource(mover, QI, 1, "test:native-movement-fee")
        install(monkeypatch, "movement_step", fee)
    def pick(candidate):
        return (candidate.kind.value == "MOVE" and
                candidate.metadata.get("movement_mode", "walk") == mode and
                (candidate.destination.z == 1 if mode in ("jump", "fly") else
                 candidate.destination == Position(x=4, y=6)))
    if paid:
        _veto(tmp_path, session, pick)
    else:
        _execute(tmp_path, session.match_id, pick)
    assert seen
    if mode == "jump" and not paid:
        assert any(destination.z == 1 for _, destination, _ in seen)


def test_late_payment_retains_restriction_after_silent_return_and_rule_removal(tmp_path, monkeypatch):
    def prepare(ctx):
        ctx.engine._apply_condition(ctx.actor, MARKER, PREPARE, ME, expires_on=None)
    def body(ctx):
        _shape(ctx, "round_trip")
        ctx.engine._remove_condition(ctx.actor, MARKER, SOURCE)
        ctx.engine._spend_resource(ctx.actor, QI, 1, SOURCE)
    session, _ = _setup(tmp_path, monkeypatch, body, prepare=prepare)
    def restriction(engine, actor, previous, destination):
        if actor.entity_id == ME and any(c.condition_id == MARKER for c in actor.conditions.values()):
            return paid_relocation.Restriction("test relocation restriction", CP)
    install(monkeypatch, "paid_relocation_guard", restriction)
    session = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == PREPARE)
    cold = _veto(tmp_path, session)
    assert any(c.condition_id == MARKER for c in cold.engine.state.actors[ME].conditions.values())


@pytest.mark.parametrize("phase", ["resolution_final", "action_completed", "event"])
def test_veto_reaches_late_completion_and_observational_hooks(tmp_path, monkeypatch, phase):
    def marker(ctx):
        ctx.engine._append_event("PASSIVE_TRIGGERED", SOURCE, actor_id=ME,
                                 payload={"relocation_probe": True})
    session, _ = _setup(tmp_path, monkeypatch, marker, costs=((QI, 1),))
    calls = []
    def relocate(engine, actor):
        calls.append(phase)
        _move(engine, actor, actor.position.model_copy(update={"y": 7}))
    if phase == "resolution_final":
        def complete(engine, actor, action, candidate, intent):
            if action.source_definition_id == SOURCE:
                relocate(engine, actor)
    elif phase == "action_completed":
        def complete(engine, actor, economy, source):
            if source == SOURCE:
                relocate(engine, actor)
    else:
        def complete(engine, kind, kwargs):
            if kind == "PASSIVE_TRIGGERED" and kwargs.get("payload", {}).get("relocation_probe"):
                relocate(engine, engine.state.actors[ME])
    install(monkeypatch, phase, complete)
    _veto(tmp_path, session)
    assert calls == [phase]


def test_payment_in_completion_hook_rechecks_an_earlier_silent_move(tmp_path, monkeypatch):
    session, _ = _setup(tmp_path, monkeypatch, lambda ctx: _shape(ctx, "round_trip"))
    def pay(engine, actor, economy, source):
        if source == SOURCE:
            engine._spend_resource(actor, QI, 1, SOURCE)
    install(monkeypatch, "action_completed", pay)
    _veto(tmp_path, session)


def test_refund_does_not_erase_a_paid_activation(tmp_path, monkeypatch):
    def body(ctx):
        from combat.technique_costs import refund
        assert refund(ctx.engine, ctx.actor, SOURCE, ((QI, 1),), QI, 1, "test:refund") == 1
        assert ctx.actor.resources[QI] == 30
        _shape(ctx, "teleport")
    session, _ = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),))
    _veto(tmp_path, session)


@pytest.mark.parametrize("deep", [False, True])
def test_projected_actor_with_same_id_never_enters_live_guard(tmp_path, monkeypatch, deep):
    witnessed = []
    def body(ctx):
        projected = ctx.actor.model_copy(deep=deep)
        projected.position = Position(x=9, y=9, z=2)
        assert projected.entity_id == ctx.actor.entity_id and projected is not ctx.actor
        witnessed.append(projected.position)
        ctx.engine._grant_temp_hp(ctx.actor, 1, SOURCE, ME)
    session, seen = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),))
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
    assert witnessed and seen == []
    assert cold.engine.state.actors[ME].position == Position(x=3, y=6)
    assert cold.engine.state.actors[ME].resources[QI] == 29
    assert cold.engine.state.actors[ME].temporary_hp == 1


def _hostile_reaction(engine, effect, *, spend=True):
    reactor = engine.state.actors[AN]
    with paid_relocation.activation(engine, reactor, REACTION):
        assert reactor.reaction_available
        reactor.reaction_available = False
        if spend:
            engine._spend_resource(reactor, AN_STAMINA, 1, REACTION)
        effect()
        engine._append_event("REACTION_RESOLVED", REACTION, actor_id=AN,
                             target_ids=(ME,), payload={"checkpoint": "TEST_COMPLETION"})


def test_independent_hostile_payment_and_displacement_do_not_taint_free_parent(tmp_path, monkeypatch):
    def body(ctx):
        def hostile():
            # An enemy resource drain is not the target's activation payment.
            ctx.engine._spend_resource(ctx.actor, QI, 1, REACTION)
            _move(ctx.engine, ctx.actor, Position(x=4, y=6), REACTION, forced=True)
        _hostile_reaction(ctx.engine, hostile)
        assert paid_relocation.current_activation(ctx.engine).source_id == SOURCE
        _move(ctx.engine, ctx.actor, Position(x=5, y=6), SOURCE)
    session, _ = _setup(tmp_path, monkeypatch, body)
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
    assert cold.engine.state.actors[ME].position == Position(x=5, y=6)
    assert cold.engine.state.actors[ME].resources[QI] == 29
    assert not cold.engine.state.actors[AN].reaction_available


def test_outer_paid_ownership_returns_after_independent_hostile_reaction(tmp_path, monkeypatch):
    def body(ctx):
        _hostile_reaction(ctx.engine, lambda:
            _move(ctx.engine, ctx.actor, Position(x=4, y=6), REACTION, forced=True))
        _move(ctx.engine, ctx.actor, Position(x=5, y=6), SOURCE)
    session, _ = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),))
    _veto(tmp_path, session)


def test_paid_self_reaction_is_independent_of_a_free_parent(tmp_path, monkeypatch):
    def body(ctx):
        with paid_relocation.activation(ctx.engine, ctx.actor, "reaction:test.self"):
            ctx.engine._spend_resource(ctx.actor, QI, 1, "reaction:test.self")
            _move(ctx.engine, ctx.actor, Position(x=4, y=6), "reaction:test.self")
    session, _ = _setup(tmp_path, monkeypatch, body)
    _veto(tmp_path, session)


@pytest.mark.parametrize("payment", ["free", "upfront", "after_followup"])
def test_free_named_own_ability_followup_retains_its_parents_payment(tmp_path, monkeypatch, payment):
    from combat import typed_reactions
    follow_source = "reaction:test.paid_relocation.followup"
    named = {"block": "generic", "feature_id": SOURCE, "name": "Test Counterstrike",
             "kind": "attacked", "costs": [], "numbers": {"pb": 2}, "effects": []}
    follow = {"block": "generic", "feature_id": follow_source, "name": "Test free follow-up",
              "kind": "own_ability", "source_name": named["name"], "free": True,
              "costs": [], "numbers": {"pb": 2}, "range_ft": 60,
              "effects": [{"type": "test_paid_relocation_followup"}]}
    owners = []
    def follow_move(ctx, effect):
        frame = paid_relocation.current_activation(ctx.engine)
        owners.append(frame)
        assert frame.actor_id == ME and frame.source_id == SOURCE
        _move(ctx.engine, ctx.actor, Position(x=5, y=6), follow_source)
    monkeypatch.setitem(ext.effects(), "test_paid_relocation_followup", follow_move)
    def body(ctx):
        # An independently accepted hostile response can first displace the
        # payer; it must remain separate from the named ability's later rider.
        _hostile_reaction(ctx.engine, lambda:
            _move(ctx.engine, ctx.actor, Position(x=4, y=6), REACTION, forced=True))
        typed_reactions._run_generic_effects(ctx.engine, ctx.actor, ctx.engine.state.actors[AN], named, [])
        if payment == "after_followup":
            ctx.engine._spend_resource(ctx.actor, QI, 1, SOURCE)
    session, seen = _setup(tmp_path, monkeypatch, body,
        costs=((QI, 1),) if payment == "upfront" else (), reaction_rows=(follow,))
    if payment != "free":
        _veto(tmp_path, session)
    else:
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert cold.engine.state.actors[ME].position == Position(x=5, y=6)
        assert cold.engine.state.actors[ME].resources[QI] == 30
        assert cold.engine.state.actors[AN].resources[AN_STAMINA] == 20
        assert any(event.event_type == "REACTION_RESOLVED" and event.source_definition_id == follow_source
                   for event in cold.engine.events)
    assert owners and seen
    assert seen[-1][0] == Position(x=4, y=6) and seen[-1][2] == SOURCE


def test_native_hostile_opportunity_can_displace_paid_user_before_its_step(tmp_path, monkeypatch):
    def body(ctx):
        ctx.engine.grant_movement(ctx.actor, (Position(x=5, y=6), Position(x=4, y=6)),
                                  SOURCE, feet=5, intent=ctx.intent)
    session, _ = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),),
                         me_at=(5, 6), foe_at=(6, 6))
    entered = []
    def forced_response(engine, attacker, target, intent, context):
        if attacker.entity_id == AN and target.entity_id == ME:
            frame = paid_relocation.current_activation(engine)
            entered.append((frame.actor_id, frame.source_id))
            _move(engine, target, Position(x=5, y=5), SYSTEM_OPPORTUNITY, forced=True)
    install(monkeypatch, "before_attack", forced_response)
    answer = ReactionDecision(checkpoint="LEAVE_REACH", reactor_id=AN,
                              reaction_source_id=SYSTEM_OPPORTUNITY, selection="USE")
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE, (answer,))
    assert entered and all(owner == AN for owner, source in entered)
    assert cold.engine.state.actors[ME].position == Position(x=5, y=5)
    assert cold.engine.state.actors[ME].resources[QI] == 29
    assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == AN and
               e.source_definition_id == SYSTEM_OPPORTUNITY for e in cold.engine.events)


def test_enemy_paid_foreground_action_can_force_locked_creature_to_move(tmp_path, monkeypatch):
    session, _ = _setup(tmp_path, monkeypatch, me_at=(3, 6), foe_at=(4, 6))
    while session.engine.state.current_actor_id != AN:
        session = _execute(tmp_path, session.match_id)
    def push(engine, actor, action, candidate, intent):
        if actor.entity_id == AN:
            target = engine.state.actors[ME]
            end = Position(x=2, y=6)
            engine.move_path(target, (target.position, end), action.source_definition_id,
                             kind="forced", intent=intent, source_actor_id=AN)
    install(monkeypatch, "resolution_final", push)
    def pick(candidate):
        # This native option really spends Stamina during resolution; First
        # Arm's listed cost is unavailable without its prerequisite stance.
        return (candidate.source_definition_id == "action:an_eui.scouring_destruction_blast"
                and candidate.target_ids == (ME,) and "DEEPEN" in candidate.option_ids)
    before = session.engine.state.actors[AN].resources[AN_STAMINA]
    cold = _execute(tmp_path, session.match_id, pick, options=("DEEPEN", "AC_MINUS_1"))
    assert cold.engine.state.actors[ME].position == Position(x=2, y=6)
    assert cold.engine.state.actors[AN].resources[AN_STAMINA] < before


def _no_flight_zone(engine, owner, suffix, *, emit=True):
    zone = ZoneState(zone_id=f"zone:test.paid_relocation.{suffix}", source_definition_id=SOURCE,
        owner_id=owner, center=engine.state.actors[ME].position, radius_cells=0,
        affected_cells=(engine.state.actors[ME].position,), concentration_link=False,
        created_round=engine.state.round_number, trigger_profile={"kind": "TEST_NO_FLIGHT"})
    engine.state.zones[zone.zone_id] = zone
    if emit:
        engine._append_event("ZONE_CREATED", SOURCE, actor_id=owner,
                             payload={"zone": zone.model_dump(mode="json")})
    assert engine.state.actors[ME].position.z == 1, "ZONE_CREATED must retain deferred settlement timing"
    return zone


def _flight_from_zones(engine, actor):
    if actor.entity_id == ME:
        return {"fly_speed_ft": 30, "flight_disabled": any(
            zone.active and zone.trigger_profile.get("kind") == "TEST_NO_FLIGHT"
            for zone in engine.state.zones.values())}


@pytest.mark.parametrize("hostile", [False, True])
def test_deferred_fall_keeps_the_zone_creators_ownership(tmp_path, monkeypatch, hostile):
    install(monkeypatch, "flight", _flight_from_zones)
    session, _ = _setup(tmp_path, monkeypatch, costs=((QI, 1),),
        prepare=lambda ctx: _move(ctx.engine, ctx.actor, Position(x=3, y=6, z=1), PREPARE))
    session = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == PREPARE)
    assert session.engine.state.actors[ME].position.z == 1
    assert session.engine.state.actors[ME].resources[QI] == 30
    def complete(engine, actor, economy, source):
        if source != SOURCE:
            return
        if hostile:
            _hostile_reaction(engine, lambda: _no_flight_zone(engine, AN, "hostile"))
        else:
            _no_flight_zone(engine, ME, "self")
        # Both cases have returned to the same paid enclosing owner here.
        assert paid_relocation.current_activation(engine).actor_id == ME
        assert actor.position.z == 1
    install(monkeypatch, "action_completed", complete)
    if not hostile:
        cold = _veto(tmp_path, session)
        assert cold.engine.state.actors[ME].position.z == 1
        assert not cold.engine.state.zones
    else:
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert cold.engine.state.actors[ME].position.z == 0
        assert cold.engine.state.actors[ME].resources[QI] == 29
        assert any(zone.owner_id == AN for zone in cold.engine.state.zones.values())
        assert any(event.event_type == "REACTION_RESOLVED" and event.actor_id == AN
                   for event in cold.engine.events)
        assert any(event.payload.get("fall_distance_ft") == 5 for event in cold.engine.events)


@pytest.mark.parametrize("last_hostile", [False, True])
def test_restored_flight_then_new_independent_cause_replaces_fall_owner(tmp_path, monkeypatch, last_hostile):
    install(monkeypatch, "flight", _flight_from_zones)
    session, _ = _setup(tmp_path, monkeypatch, costs=((QI, 1),),
        prepare=lambda ctx: _move(ctx.engine, ctx.actor, Position(x=3, y=6, z=1), PREPARE))
    session = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == PREPARE)
    def complete(engine, actor, economy, source):
        if source != SOURCE:
            return
        from combat import zones
        if last_hostile:
            old = _no_flight_zone(engine, ME, "earlier-self")
            def replacement():
                zones.remove(engine, old, "TEST_REPLACED")
                _no_flight_zone(engine, AN, "later-hostile")
            _hostile_reaction(engine, replacement)
        else:
            _hostile_reaction(engine, lambda: _no_flight_zone(engine, AN, "earlier-hostile"))
            old = engine.state.zones["zone:test.paid_relocation.earlier-hostile"]
            zones.remove(engine, old, "TEST_REPLACED")
            _no_flight_zone(engine, ME, "later-self")
    install(monkeypatch, "action_completed", complete)
    if last_hostile:
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert cold.engine.state.actors[ME].position.z == 0
        assert [z.owner_id for z in cold.engine.state.zones.values() if z.active] == [AN]
    else:
        _veto(tmp_path, session)


@pytest.mark.parametrize("hostile", [False, True])
def test_silent_fall_cause_survives_an_observer_exception_caught_after_scope_exit(tmp_path, monkeypatch, hostile):
    """Observational hooks may fail after mutating; their accepted owner still caused the fall."""
    install(monkeypatch, "flight", _flight_from_zones)
    session, _ = _setup(tmp_path, monkeypatch,
        costs=((QI, 1),) if hostile else (),
        prepare=lambda ctx: _move(ctx.engine, ctx.actor, Position(x=3, y=6, z=1), PREPARE))
    session = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == PREPARE)
    owner_id = AN if hostile else ME
    def failing_observer(engine):
        actor = engine.state.actors[owner_id]
        with paid_relocation.activation(engine, actor, REACTION):
            engine._spend_resource(actor, AN_STAMINA if hostile else QI, 1, REACTION)
            _no_flight_zone(engine, owner_id, "silent-before-error", emit=False)
            raise ValueError("expected incidental observer failure")
    # This one ordinary exception is deliberate. Keep all other fixture
    # callbacks under the helper's strict no-swallowed-test-failure assertion.
    failing_observer.__module__ = "test_expected_observer_failure"
    install(monkeypatch, "test_throwing_relocation_effect", failing_observer)
    def complete(engine, actor, economy, source):
        if source != SOURCE:
            return
        ext.run("test_throwing_relocation_effect", engine)
        assert paid_relocation.current_activation(engine).actor_id == ME
        zone = engine.state.zones["zone:test.paid_relocation.silent-before-error"]
        # Publication belongs to the ordinary enclosing callback. Ownership
        # must already have survived the exceptional child exit and GM_RIDER.
        engine._append_event("ZONE_CREATED", SOURCE, actor_id=owner_id,
                             payload={"zone": zone.model_dump(mode="json")})
    install(monkeypatch, "action_completed", complete)
    if hostile:
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert cold.engine.state.actors[ME].position == Position(x=3, y=6)
        assert cold.engine.state.actors[ME].resources[QI] == 29
        expected = [event for event in cold.engine.events
                    if event.event_type == "GM_RIDER" and
                    event.source_definition_id == "ext:test_expected_observer_failure"]
        assert len(expected) == 1 and "expected incidental observer failure" in str(expected[0].payload)
    else:
        # The parent is free; only the interrupted independent child paid.
        cold = _veto(tmp_path, session)
        assert cold.engine.state.actors[ME].position.z == 1
        assert cold.engine.state.actors[ME].resources[QI] == 30


@pytest.mark.parametrize("reaction_paid", [False, True])
def test_native_deferred_recovery_keeps_its_payment_owner_until_after_damage_commit(tmp_path, monkeypatch, reaction_paid):
    from combat.ext import life_state
    recovery = "reaction:test.paid_relocation.deferred_recovery"
    row = {"block": "generic", "feature_id": recovery, "name": "Test deferred recovery",
           "kind": "drop_to_zero", "costs": [{"resource_id": QI, "amount": 1}] if reaction_paid else [],
           "numbers": {"pb": 2, "cl": 10, "key_mod": 2, "save_dc": 14},
           "effects": [{"type": "hold_at_1hp", "keep": 1},
                       {"type": "temp_hp", "flat": 2, "applies_to": "self"}]}
    # Script the synthetic defender's explicit yes; all native eligibility,
    # reaction spending, lethal reduction, queueing and flushing remain real.
    monkeypatch.setattr(life_state, "survival_consent", lambda *args, **kwargs: True)
    def body(ctx):
        def hostile_hit():
            ctx.engine._commit_damage(ctx.actor, ctx.actor.current_hp + 10, "FORCE", REACTION, AN,
                                      ctx.intent, reaction_depth=0)
        _hostile_reaction(ctx.engine, hostile_hit)
    session, seen = _setup(tmp_path, monkeypatch, body,
        costs=() if reaction_paid else ((QI, 1),), reaction_rows=(row,))
    owners = []
    def recovery_move(engine, kind, kwargs):
        if kind != "TEMP_HP_GRANTED" or kwargs.get("source_definition_id") != recovery:
            return
        actor = engine.state.actors[ME]
        frame = paid_relocation.current_activation(engine)
        owners.append(frame)
        assert actor.current_hp == 1, "this effect must run after the triggering damage commits"
        assert frame.actor_id == ME and frame.source_id == recovery
        _move(engine, actor, Position(x=4, y=6), recovery)
    install(monkeypatch, "event", recovery_move)
    if reaction_paid:
        _veto(tmp_path, session)
        assert owners and dict(owners[0].payments).get(QI) == 1
        assert not session.engine.__dict__.get("_typed_after_commit"), "rollback must discard deferred work"
    else:
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert owners and owners[0].payments == ()
        assert seen and seen[0][2] == recovery
        assert cold.engine.state.actors[ME].position == Position(x=4, y=6)
        assert cold.engine.state.actors[ME].current_hp == 1
        assert cold.engine.state.actors[ME].temporary_hp == 2
        assert cold.engine.state.actors[ME].resources[QI] == 29
        assert not cold.engine.state.actors[ME].reaction_available
        resolved = next(event for event in cold.engine.events
                        if event.event_type == "REACTION_RESOLVED" and event.source_definition_id == recovery)
        committed = next(event for event in cold.engine.events
                         if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == REACTION)
        granted = next(event for event in cold.engine.events
                       if event.event_type == "TEMP_HP_GRANTED" and event.source_definition_id == recovery)
        assert resolved.sequence < committed.sequence < granted.sequence


@pytest.mark.parametrize("reaction_paid", [False, True])
def test_native_hit_reduction_followup_resumes_the_guard_payment_owner(tmp_path, monkeypatch, reaction_paid):
    from combat import typed_reactions
    from combat.ext.attack_reduction import follow_up_scope
    guard_source = "reaction:test.paid_relocation.delayed_hit_guard"
    row = {"block": "generic", "feature_id": guard_source, "name": "Test delayed hit guard",
           "kind": "hit", "range_ft": 60,
           "costs": [{"resource_id": QI, "amount": 1}] if reaction_paid else [],
           "numbers": {"pb": 2, "cl": 10, "key_mod": 2, "save_dc": 14},
           "effects": [{"type": "damage_modifier", "flat": 3, "applies_to": "self"}]}
    owners = []
    def body(ctx):
        def hostile_hit():
            # This is the real generic hit checkpoint: eligibility, consent,
            # payment, Reaction spending and the parked reduction all run.
            _, hit = typed_reactions.on_attack_hit(
                ctx.engine, ctx.engine.state.actors[AN], ctx.actor,
                {"source_definition_id": REACTION, "action_name": "Test hostile hit", "range_ft": 5},
                total=100, natural=10, effective_ac=ctx.actor.armor_class)
            assert hit and ctx.actor.turn_flags[f"typed_hit_reduction:{AN}"] == 3
            assert paid_relocation.current_activation(ctx.engine).source_id == REACTION
            assert not owners, "the follow-up must wait for actual pending damage"
            # on_damage consumes the native parked flag only now, after the
            # accepted guard's immediate scope has returned to the attacker.
            ctx.engine._commit_damage(ctx.actor, 10, "FORCE", REACTION, AN,
                                      ctx.intent, reaction_depth=0)
        _hostile_reaction(ctx.engine, hostile_hit)
    session, seen = _setup(tmp_path, monkeypatch, body,
        costs=() if reaction_paid else ((QI, 1),), reaction_rows=(row,), foe_at=(4, 6))
    hp_before = session.engine.state.actors[ME].current_hp
    def after_reduction(engine, target, attacker, source, before, after, reduced_by):
        if guard_source not in reduced_by:
            return None
        assert target.entity_id == ME and attacker.entity_id == AN
        assert source == REACTION and (before, after) == (10, 7)
        assert paid_relocation.current_activation(engine).actor_id == AN
        # The synthetic consumer uses the same narrow continuation helper as
        # native Iron Empty Palm, Pressure Points, Needle and Fencing riders.
        with follow_up_scope(engine, target, attacker.entity_id, guard_source):
            frame = paid_relocation.current_activation(engine)
            owners.append(frame)
            assert frame.actor_id == ME and frame.source_id == guard_source
            _move(engine, target, Position(x=3, y=7), guard_source)
        return None
    install(monkeypatch, "hit_reduced", after_reduction)
    if reaction_paid:
        _veto(tmp_path, session)
        assert owners and dict(owners[0].payments).get(QI) == 1
    else:
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        actor = cold.engine.state.actors[ME]
        assert owners and owners[0].payments == ()
        assert actor.position == Position(x=3, y=7)
        assert actor.current_hp == hp_before - 7 and actor.resources[QI] == 29
        assert not actor.reaction_available
        assert f"typed_hit_reduction:{AN}" not in actor.turn_flags
        assert f"typed_hit_reduced_by:{AN}" not in actor.turn_flags
        resolved = next(event for event in cold.engine.events
                        if event.event_type == "REACTION_RESOLVED" and event.source_definition_id == guard_source)
        moved = next(event for event in cold.engine.events
                     if event.event_type == "MOVEMENT_COMMITTED" and event.source_definition_id == guard_source)
        committed = next(event for event in cold.engine.events
                         if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == REACTION)
        assert resolved.sequence < moved.sequence < committed.sequence
    assert seen and seen[-1][2] == guard_source


@pytest.mark.parametrize("failure", ["error", "pause"])
def test_nested_ownership_unwinds_and_persisted_pause_recovers(tmp_path, monkeypatch, failure):
    interrupted = []
    def body(ctx):
        def response():
            _move(ctx.engine, ctx.actor, Position(x=4, y=6), REACTION, forced=True)
            if not interrupted:
                interrupted.append(True)
                if failure == "pause":
                    raise ext.ControllerPause({"test": "paid relocation choice"})
                raise RuntimeError("test paid relocation interruption")
        _hostile_reaction(ctx.engine, response)
    session, _ = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),))
    engine = session.engine
    before = _snapshot(engine)
    exception = ext.ControllerPause if failure == "pause" else RuntimeError
    with pytest.raises(exception):
        session.mechanical.execute_intent(_intent(session, lambda c: c.source_definition_id == SOURCE))
    assert _snapshot(engine) == before
    assert paid_relocation.current_activation(engine) is None
    cold = _cold(tmp_path, session.match_id)
    if failure == "pause":
        # PREPARE was retained. Loading replays it after the one-time question
        # has been answered, with a fresh ownership stack and ordinary commit.
        assert cold.engine.state.actors[ME].position == Position(x=4, y=6)
        assert cold.engine.state.actors[ME].resources[QI] == 29
    else:
        assert _snapshot(cold.engine) == before
        cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
        assert cold.engine.state.actors[ME].position == Position(x=4, y=6)


@pytest.mark.parametrize("preexisting", [False, True])
def test_native_plugin_pending_marker_rolls_back_before_a_later_free_action(tmp_path, monkeypatch, preexisting):
    from combat.ext import near_and_far
    pending_name = near_and_far._PENDING
    roll_key = "ATTACK:test-paid-relocation-pending:1"
    callbacks = []
    real_after = near_and_far._after
    def after(engine, held, *, missed):
        callbacks.append((held, missed))
        return real_after(engine, held, missed=missed)
    monkeypatch.setattr(near_and_far, "_after", after)
    def body(ctx):
        foe = ctx.engine.state.actors[AN]
        # Use the real plug-in's producer. The callback must remain pending
        # until after a later root self-move has had an opportunity to veto.
        _hostile_reaction(ctx.engine, lambda: near_and_far._pending_set(
            ctx.engine, ctx.actor, foe, foe, roll_key, "fails", counter=False))
        assert ctx.engine.__dict__[pending_name]["attacker"] == ME
        _move(ctx.engine, ctx.actor, Position(x=4, y=6))
    def free_probe(ctx):
        # Keep the SAME live engine after rollback: a cold load alone would
        # discard an engine-side leak and make this an ineffective regression.
        near_and_far.far_missed(ctx.engine, "ATTACK_ROLLED", {
            "actor_id": ME, "payload": {"reason": roll_key, "provisional_hit": False}})
        _move(ctx.engine, ctx.actor, Position(x=4, y=6), PREPARE)
    session, _ = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),), prepare=free_probe)
    previous = {"attacker": AN, "defender": ME, "law": ME, "mode": "disadvantage",
                "events": 0, "roll": "ATTACK:older-independent-response:1", "counter": False}
    if preexisting:
        session.engine.__dict__[pending_name] = deepcopy(previous)
    else:
        assert pending_name not in session.engine.__dict__
    _veto(tmp_path, session)
    if preexisting:
        assert session.engine.__dict__[pending_name] == previous
    else:
        assert pending_name not in session.engine.__dict__
    assert callbacks == []
    session.mechanical.execute_intent(_intent(session, lambda c: c.source_definition_id == PREPARE))
    assert paid_relocation.current_activation(session.engine) is None
    assert callbacks == [], "a canceled child's pending marker must not run in the next action"
    if preexisting:
        assert session.engine.__dict__[pending_name] == previous
    else:
        assert pending_name not in session.engine.__dict__
    cold = _cold(tmp_path, session.match_id)
    assert cold.engine.state.actors[ME].position == Position(x=4, y=6)
    assert cold.engine.state.actors[ME].resources[QI] == 30


@pytest.mark.parametrize("blocked", [False, True])
def test_none_native_deferred_queue_at_transaction_start_never_leaks_ownership(tmp_path, monkeypatch, blocked):
    def body(ctx):
        if blocked:
            _move(ctx.engine, ctx.actor, Position(x=4, y=6))
        else:
            ctx.engine._grant_temp_hp(ctx.actor, 1, SOURCE, ME)
    session, _ = _setup(tmp_path, monkeypatch, body, costs=((QI, 1),))
    session.engine.__dict__["_typed_after_commit"] = None
    if blocked:
        cold = _veto(tmp_path, session)
        assert cold.engine.state.actors[ME].resources[QI] == 30
    else:
        session.mechanical.execute_intent(_intent(session, lambda c: c.source_definition_id == SOURCE))
        cold = _cold(tmp_path, session.match_id)
        assert cold.engine.state.actors[ME].resources[QI] == 29
        assert cold.engine.state.actors[ME].temporary_hp == 1
    assert "_typed_after_commit" in session.engine.__dict__
    assert session.engine._typed_after_commit is None
    assert paid_relocation.current_activation(session.engine) is None
    assert paid_relocation.current_activation(cold.engine) is None


def test_no_subscriber_preserves_paid_movement_and_serialized_state_shape(tmp_path, monkeypatch):
    session, seen = _setup(tmp_path, monkeypatch, lambda ctx: _shape(ctx, "teleport"),
                           costs=((QI, 1),), guard=False)
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE)
    assert seen == []
    assert cold.engine.state.actors[ME].position == Position(x=5, y=6)
    assert cold.engine.state.actors[ME].resources[QI] == 29
    assert "paid_relocation" not in json.dumps(cold.engine.state.model_dump(mode="json")).replace(SOURCE, "").replace(PREPARE, "")
