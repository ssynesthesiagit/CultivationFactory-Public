"""Deadline endings use the same observable lifecycle as manual endings.

All setup effects are ordinary, persisted synthetic typed actions. The synthetic
adapters exercise public extension seams and never replace an engine method.
The real Concentration, duration, zone, summon and suppression implementations
perform their own work. Each accepted action uses the CombatService session's
mechanical.execute_intent, then drops the service and reloads its journal.

The --cold entry point starts a separate Python process, reinstalls only these
test adapters, reopens the saved fight and verifies its complete mechanical
replay. It can also execute the next real END_TURN. Thus the reload assertions
do not depend on an engine, a subscriber registry or a cache surviving restart.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from combat import concentration, ext, summons, zones
from combat.ext import (afflictions, benefit_suppression, concentration_duration,
                        effect_durations, end_effect, eye_patient_eye, placed)
from combat.gate2_engine import SYSTEM_EXPIRATION
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet


PREFIX = "action:test.p07."
ME = "actor:factory.p07"
SEAL = PREFIX + "seal"
ZONE = PREFIX + "zone"
DROP_ZONE = PREFIX + "drop_zone"
SUMMON = PREFIX + "summon"
SUMMON_FOCUS = PREFIX + "summon_focus"
DROP_SUMMON = PREFIX + "drop_summon"
DESTROY_SUMMON = PREFIX + "destroy_summon"
CHAIN = PREFIX + "chain"
DROP_CHAIN = PREFIX + "drop_chain"
INSTANCES = PREFIX + "instances"
AFFLICTION = PREFIX + "affliction"
OTHER_AFFLICTION = PREFIX + "other_affliction"
DROP_AFFLICTION = PREFIX + "drop_affliction"
SUPPRESS_ZONE = PREFIX + "suppress_zone"
RESTORE_ZONE = PREFIX + "restore_zone"
CLOCK_SETUP = PREFIX + "clock_setup"
CLOCK_REFRESH = PREFIX + "clock_refresh"
OBSERVATION = "test:p07.subscriber"
WARD = "test:p07.ward"
PARENT = "condition:test.p07.parent"
CHILD = "condition:test.p07.child"
ZONE_LINK = "condition:test.p07.zone_link"
SAME_NAMED = "condition:test.p07.same_named"
BONE = "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"
ZONE_TAG = "p07-zone"
AURA_TAG = "p07-summon-aura"
INDEPENDENT_TAG = "p07-independent-zone"


def _actions(info):
    if info["actor_id"] != ME:
        return []

    def action(source, effect_name, *, duration=None, targeted=False):
        return ActionDefinition(
            source_definition_id=source, display_name=source.removeprefix(PREFIX),
            owner_id=ME, economy="NONE", resolution_kind="TYPED",
            target_kind="HOSTILE_ENTITY_OR_SELF" if targeted else "SELF", range_ft=120,
            parameters={"typed": {
                "source": source, "numbers": info["numbers"],
                "duration": duration or {"kind": "instant"},
                "effects": [{"type": effect_name,
                             "applies_to": "target" if targeted else "self"}],
            }},
        )

    return [
        action(SEAL, "p07_seal", duration={"kind": "rounds", "amount": 2, "concentration": True}, targeted=True),
        action(ZONE, "p07_zone"), action(DROP_ZONE, "p07_drop_zone"),
        action(SUMMON, "p07_summon", duration={"kind": "rounds", "amount": 1}),
        action(DROP_SUMMON, "p07_drop_summon"),
        action(DESTROY_SUMMON, "p07_destroy_summon"),
        action(CHAIN, "p07_chain"), action(DROP_CHAIN, "p07_drop_chain"),
        action(INSTANCES, "p07_instances"),
        action(AFFLICTION, "p07_affliction"), action(DROP_AFFLICTION, "p07_drop_affliction"),
        action(SUPPRESS_ZONE, "p07_suppress_zone"), action(RESTORE_ZONE, "p07_restore_zone"),
        action(CLOCK_SETUP, "p07_clock_setup"), action(CLOCK_REFRESH, "p07_clock_refresh"),
    ]


def _seal(ctx, row):
    target = ctx.target
    ctx.engine._add_modifier(target, ctx.source, "speed_ft", "ADD", 5, "ALWAYS",
                             expires_on="CONCENTRATION_END")
    mid = ctx.engine._add_modifier(target, WARD, "armor_class", "ADD", 2, "ALWAYS",
                                   expires_on="END_OF_SOURCE_TURN_AT:99")
    assert benefit_suppression.suppress(ctx.engine, ctx.actor, target, "modifier:" + mid,
                                        "concentration", ctx.source)


def _inside_rule(name):
    return [{"id": "p07-inside", "name": name, "who": "any", "rule": {"speed_zero": True},
             "modifiers": [{"field": "armor_class", "value": 2}]}]


def _zone(ctx, row):
    zone = placed.place(
        ctx.engine, ctx.actor, source=ctx.source, tag=ZONE_TAG, cells=ctx.actor.position,
        name="Deadline test zone", inside=_inside_rule("Deadline test field"),
        extra={"end_after_owner_turn": ctx.actor.turns_started},
    )
    # This is a linked extension condition, separate from zones.sync_inside's
    # own records. Its source-ending subscriber must be delivered as well.
    ctx.engine._apply_condition(ctx.actor, ZONE_LINK, ctx.source, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED", data={"zone_id": zone.zone_id})


def _drop_zone(ctx, row):
    for zone in placed.of(ctx.engine, ZONE_TAG, owner_id=ctx.actor.entity_id):
        zones.remove(ctx.engine, zone, "MANUAL")


def _summon_with_aura(ctx, row):
    candidates = summons.owned_by(ctx.engine, ctx.actor.entity_id)
    assert len(candidates) == 1, "the synthetic fixture owns one real compiled Bone Guard"
    [creature] = candidates
    arrived = summons.summon(ctx.engine, ctx.actor, creature.summon["group"], ctx.source)
    assert arrived == [creature.entity_id]
    placed.place(
        ctx.engine, creature, source=ctx.source, tag=AURA_TAG,
        cells=(ctx.actor.position, creature.position), name="Summoned creature's aura",
        inside=_inside_rule("Summoned aura"), follows_owner=True, anchor_id=creature.entity_id,
    )
    # A stationary creation with its own lifetime does not end merely because
    # its creator leaves. Only the explicitly following aura is owner-linked.
    placed.place(ctx.engine, creature, source=ctx.source, tag=INDEPENDENT_TAG,
                 cells=creature.position, name="Independent stationary creation")
    # A departing owner must also finish both its current and held lifetimes.
    ctx.engine._start_concentration(creature, SUMMON_FOCUS)
    ctx.engine._start_concentration(creature, SUMMON_FOCUS)


def _drop_summon(ctx, row):
    for creature in summons.owned_by(ctx.engine, ctx.actor.entity_id):
        if creature.active:
            summons.dismiss(ctx.engine, creature, "MANUAL")


def _destroy_summon(ctx, row):
    [creature] = [creature for creature in summons.owned_by(ctx.engine, ctx.actor.entity_id) if creature.active]
    ctx.engine._defeat(creature, ctx.source)


def _chain(ctx, row):
    for condition_id, label, expiry in (
        (PARENT, "parent", "END_OF_CURRENT_TURN"),
        (CHILD, "child", "UNTIL_REMOVED"),
    ):
        ctx.engine._apply_condition(ctx.actor, condition_id, ctx.source, ctx.actor.entity_id,
                                    expires_on=expiry, data={"p07_label": label, "original": "kept"})


def _drop_chain(ctx, row):
    ctx.engine._remove_condition(ctx.actor, PARENT, ctx.source)


def _instances(ctx, row):
    for label, expiry in (("due", "END_OF_CURRENT_TURN"), ("remaining", "UNTIL_REMOVED")):
        ctx.engine._apply_condition(ctx.actor, SAME_NAMED, ctx.source, ctx.actor.entity_id,
                                    expires_on=expiry, data={"p07_label": label})


def _affliction(ctx, row):
    for source, setter, expiry in (
        (AFFLICTION, AN, "END_OF_CURRENT_TURN"),
        (AFFLICTION, ME, "UNTIL_REMOVED"),
        (OTHER_AFFLICTION, AN, "UNTIL_REMOVED"),
    ):
        data = afflictions._data(["Silent"], {"Silent": {"companions": ["silenced"]}},
                                 2, "Deadline test affliction", "p07-affliction-menu")
        ctx.engine._apply_condition(ctx.actor, afflictions.condition_id(), source, setter,
                                    expires_on=expiry, data=data)
        # Use the real companion producer, with an independently retained
        # child: its own timer must not conceal a missed parent notification.
        afflictions._companions(ctx.engine, ctx.actor, data, source, setter, "UNTIL_REMOVED")


def _drop_affliction(ctx, row):
    [parent] = [c for c in ctx.actor.conditions.values() if c.condition_id == afflictions.condition_id()
                and c.source_definition_id == AFFLICTION and c.source_actor_id == AN]
    # The dispeller and the dispelling action both differ from the origin.
    end_effect.remove_instance(ctx, ctx.actor, "condition", parent.instance_id, parent)


def _suppress_zone(ctx, row):
    holder = ctx.engine.state.actors[AN]
    [membership] = [c for c in holder.conditions.values() if c.condition_id == zones.ZONE_EFFECT]
    assert benefit_suppression.suppress(ctx.engine, ctx.actor, holder, "condition:" + membership.instance_id,
                                        "owner_turn", ctx.source)


def _restore_zone(ctx, row):
    holder = ctx.engine.state.actors[AN]
    [suppression] = [c for c in holder.conditions.values() if c.condition_id == benefit_suppression.SUPPRESSED]
    benefit_suppression._give_back(ctx.engine, holder, suppression.instance_id, suppression, "MANUAL_RESTORE")


def _clock_setup(ctx, row):
    [creature] = summons.owned_by(ctx.engine, ctx.actor.entity_id)
    assert summons.summon(ctx.engine, ctx.actor, creature.summon["group"], ctx.source) == [creature.entity_id]
    ctx.engine._apply_condition(
        ctx.actor, eye_patient_eye._record_id(), eye_patient_eye.SOURCE, creature.entity_id,
        expires_on=f"END_OF_SOURCE_TURN_AT:{creature.turns_started + 3}",
        data={"by": creature.entity_id, "until_round": ctx.engine.state.round_number + 10},
    )
    # The production scheduler must accrue the source's omitted slots; the
    # fixture never writes expiry bookkeeping or simulates a removal helper.
    ctx.engine._defeat(creature, ctx.source)


def _clock_refresh(ctx, row):
    held = eye_patient_eye.record(ctx.actor)
    assert held is not None
    eye_patient_eye._refresh(ctx.engine, ctx.actor, held, p07_refreshed=True)


def _label(engine, event_type, kwargs):
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_REMOVED":
        return {PARENT: "parent", CHILD: "child", ZONE_LINK: "zone-link", SAME_NAMED: "instance"}.get(payload.get("condition_id"))
    if event_type == "ZONE_REMOVED":
        zone = engine.state.zones.get(payload.get("zone_id"))
        return "zone" if zone is not None and placed.data(zone).get("tag") in {ZONE_TAG, AURA_TAG} else None
    return None


def _record_observation(engine, event_type, kwargs, observer, label):
    origin = kwargs.get("originating_event")
    payload = kwargs.get("payload") or {}
    ending = kwargs.get("ended_effect") or {}
    # Observe the delivered event's immutable identity after an earlier observer
    # may already have appended child-ending and diagnostic events.
    identity_ok = (origin is not None and any(row is origin for row in engine.events)
                   and origin.event_type == event_type
                   and origin.source_definition_id == kwargs.get("source_definition_id")
                   and origin.payload == payload)
    engine._append_event(
        "PASSIVE_TRIGGERED", OBSERVATION, actor_id=kwargs.get("actor_id"),
        target_ids=tuple(kwargs.get("target_ids") or ()),
        payload={"p07_observation": {
            "observer": observer, "label": label, "event_type": event_type,
            "ending_id": payload.get("instance_id") or payload.get("zone_id"),
            "identity_ok": identity_ok,
            "original_source": ending.get("source_definition_id"),
            "original_data": ending.get("data"),
        }},
    )


def _observer_a(engine, event_type, kwargs):
    label = _label(engine, event_type, kwargs)
    if label is None:
        return
    _record_observation(engine, event_type, kwargs, "a", label)
    if label == "parent":
        holder = engine.state.actors[kwargs["target_ids"][0]]
        engine._remove_condition(holder, CHILD, CHAIN)
        engine._remove_condition(holder, PARENT, CHAIN)  # reentrant repeat is a no-op
    elif label == "zone":
        zone_id = kwargs["payload"]["zone_id"]
        for holder in engine.state.actors.values():
            if any(c.condition_id == ZONE_LINK and c.data.get("zone_id") == zone_id
                   for c in holder.conditions.values()):
                engine._remove_condition(holder, ZONE_LINK, ZONE)


def _observer_b(engine, event_type, kwargs):
    label = _label(engine, event_type, kwargs)
    if label is not None:
        _record_observation(engine, event_type, kwargs, "b", label)


def _install_adapters(monkeypatch=None):
    ext.effects()

    def put(mapping, name, value):
        if monkeypatch is None:
            mapping[name] = value
        else:
            monkeypatch.setitem(mapping, name, value)

    handlers = {
        "p07_seal": _seal, "p07_zone": _zone, "p07_drop_zone": _drop_zone,
        "p07_summon": _summon_with_aura, "p07_drop_summon": _drop_summon,
        "p07_destroy_summon": _destroy_summon,
        "p07_chain": _chain, "p07_drop_chain": _drop_chain,
        "p07_instances": _instances,
        "p07_affliction": _affliction, "p07_drop_affliction": _drop_affliction,
        "p07_suppress_zone": _suppress_zone, "p07_restore_zone": _restore_zone,
        "p07_clock_setup": _clock_setup, "p07_clock_refresh": _clock_refresh,
    }
    for name, handler in handlers.items():
        put(ext._EFFECTS, name, handler)
    put(ext._HOOKS, "compile_actions", [*ext._HOOKS.get("compile_actions", ()), _actions])
    # Two ordinary, non-nested subscribers: ending events must reach both even
    # during a turn hook or a child ending. Production subscriber order remains.
    callbacks = [*ext._HOOKS.get("event", ()), _observer_a, _observer_b]
    put(ext._HOOKS, "event", sorted(callbacks, key=lambda fn: ext._HOOK_PRIORITIES.get(("event", fn), 0)))


@pytest.fixture
def adapters(monkeypatch):
    _install_adapters(monkeypatch)


def _snapshot(session):
    return {"state": session.engine.state.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in session.engine.events],
            "rolls": [roll.model_dump(mode="json") for roll in session.engine.rolls]}


def _reload(data, mid, *, expected=None):
    session = CombatService(ROOT, data)._load_session(mid)
    if expected is not None:
        assert _snapshot(session) == expected
    verified, replayed = session.verify(), session.mechanical.replay()
    assert verified["status"] == replayed["status"] == "PASS"
    assert verified["canonical_state_sha256"] == replayed["canonical_state_sha256"]
    assert replayed["events"] == [event.model_dump(mode="json") for event in session.engine.events]
    assert replayed["rolls"] == [roll.model_dump(mode="json") for roll in session.engine.rolls]
    return session


def _intent(session, source=None, *, target=None, name=None, at=None):
    candidate = next(c for c in session.engine.legal_candidates()
                     if (c.display_name.split(" at ")[0] == name if name is not None
                         else c.source_definition_id == source if source else c.kind.value == "END_TURN")
                     and (target is None or c.target_ids == (target,))
                     and (at is None or c.destination is not None and (c.destination.x, c.destination.y) == at))
    # An aborted attempt preserves state_version, but retry is a new client
    # request and must not reuse the aborted persistence transaction identity.
    attempt = sum(json.loads(line)["record_type"] == "PREPARE"
                  for line in session.store.journal_path.read_text().splitlines())
    return ActionIntent(
        intent_id=f"p07:{session.engine.state.state_version}:{attempt}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids,
    )


def _execute(data, mid, source=None, *, target=None, name=None, at=None):
    session = CombatService(ROOT, data)._load_session(mid)
    session.mechanical.execute_intent(_intent(session, source, target=target, name=name, at=at))
    expected = _snapshot(session)
    del session
    cold = _reload(data, mid)
    # Gate3 enriches raw live events with reducer snapshots at commit. Compare
    # the live mechanical state/rolls here; _reload compares every committed
    # event and roll to mechanical replay, and --cold compares that full record
    # again in another interpreter.
    assert cold.engine.state.model_dump(mode="json") == expected["state"]
    assert [roll.model_dump(mode="json") for roll in cold.engine.rolls] == expected["rolls"]
    return cold


def _match(data, *, seed="P07-DEADLINES", with_summon=False, mechanics=(), finalized_turns=False):
    bundle = compile_character(sheet([*([BONE] if with_summon else []), *mechanics]), actor_id=ME)
    bundle["concentration_rules"] = {"capacity": "unlimited"}
    roster = {"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
              "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}}
    if finalized_turns:
        roster["rules"] = {"finalized_turns": "skip_finalized_v1"}
    session = CombatService(ROOT, data).persistence.create_match(
        match_seed=seed, typed_bundles=(bundle,), roster_setup=roster,
    )
    mid = session.match_id
    for _ in range(8):
        if session.engine.state.current_actor_id == ME:
            return mid, session
        session = _execute(data, mid)
    raise AssertionError("the owner never received its first turn")


def _cold_process(data, mid, *, end_turn=False):
    args = [sys.executable, "-m", "tests.test_deadline_endings", "--cold", str(data), mid]
    if end_turn:
        args.append("--end-turn")
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["verify"] == receipt["replay"] == "PASS"
    session = _reload(data, mid, expected=receipt["snapshot"])
    return session


def _clock(session):
    return session.engine.state.round_number, session.engine.state.current_slot_index


def _suppressed(session, actor_id):
    return [c for c in session.engine.state.actors[actor_id].conditions.values()
            if c.condition_id == benefit_suppression.SUPPRESSED]


def _wards(session, actor_id):
    return [m for m in session.engine.state.actors[actor_id].modifiers.values() if m.source_definition_id == WARD]


def _copy_modifiers(session, actor_id):
    return [m for m in session.engine.state.actors[actor_id].modifiers.values()
            if m.source_definition_id == SEAL and m.expires_on == "CONCENTRATION_END"]


def _deadline(session, started):
    [row] = [c for c in session.engine.state.actors[ME].conditions.values()
             if c.condition_id == concentration_duration.DEADLINE and c.data["started_sequence"] == started]
    return tuple(int(n) for n in row.expires_on.rsplit(":", 2)[-2:])


def _advance_before(data, mid, deadline):
    """Leave the fight at the actual predecessor slot, so restart crosses the edge."""
    session = _reload(data, mid)
    for _ in range(30):
        state = session.engine.state
        following = (state.round_number + int(state.current_slot_index + 1 == len(state.initiative_order)),
                     (state.current_slot_index + 1) % len(state.initiative_order))
        if following == deadline:
            assert _clock(session) < deadline
            return session
        assert _clock(session) < deadline, "missed the effect's exact deadline"
        session = _execute(data, mid)
    raise AssertionError("did not reach the predecessor of the deadline")


@pytest.mark.parametrize("held", [False, True], ids=["current-copy", "held-copy"])
def test_copy_deadline_restores_only_its_suppressed_benefit(adapters, tmp_path, held):
    mid, session = _match(tmp_path)
    session = _execute(tmp_path, mid, SEAL, target=AN)
    first = session.engine.state.actors[ME].concentration.started_sequence
    first_deadline = _deadline(session, first)
    assert _suppressed(session, AN) and not _wards(session, AN)
    assert len(_copy_modifiers(session, AN)) == 1
    second = None
    if held:
        # Cast the second copy one round later, making the two deadlines distinct.
        session = _execute(tmp_path, mid)
        while session.engine.state.current_actor_id != ME:
            session = _execute(tmp_path, mid)
        session = _execute(tmp_path, mid, SEAL, target=ME)
        second = session.engine.state.actors[ME].concentration.started_sequence
        second_deadline = _deadline(session, second)
        assert second_deadline > first_deadline
        assert concentration.copies(session.engine.state.actors[ME], SEAL) == [first, second]
        assert _suppressed(session, ME) and not _wards(session, ME)

    session = _advance_before(tmp_path, mid, first_deadline)
    assert _suppressed(session, AN) and not _wards(session, AN)
    session = _cold_process(tmp_path, mid, end_turn=True)
    assert _clock(session) == first_deadline
    assert not _suppressed(session, AN) and len(_wards(session, AN)) == 1
    assert not _copy_modifiers(session, AN)
    ended = [e for e in session.engine.events if e.event_type == "CONCENTRATION_ENDED"
             and e.payload.get("started_sequence") == first]
    assert len(ended) == 1 and ended[0].payload["reason"] == "DURATION_ENDED"
    if held:
        assert _suppressed(session, ME) and not _wards(session, ME)
        assert len(_copy_modifiers(session, ME)) == 1
        assert concentration.copies(session.engine.state.actors[ME], SEAL) == [second]
        session = _advance_before(tmp_path, mid, second_deadline)
        session = _cold_process(tmp_path, mid, end_turn=True)
        assert _clock(session) == second_deadline
        assert not _suppressed(session, ME) and len(_wards(session, ME)) == 1
        assert not _copy_modifiers(session, ME)
    assert concentration.copies(session.engine.state.actors[ME], SEAL) == []


def test_two_copies_due_together_each_restore_once(adapters, tmp_path):
    mid, session = _match(tmp_path)
    session = _execute(tmp_path, mid, SEAL, target=AN)
    first = session.engine.state.actors[ME].concentration.started_sequence
    session = _execute(tmp_path, mid, SEAL, target=ME)
    second = session.engine.state.actors[ME].concentration.started_sequence
    deadline = _deadline(session, first)
    assert deadline == _deadline(session, second)
    assert concentration.copies(session.engine.state.actors[ME], SEAL) == [first, second]
    _advance_before(tmp_path, mid, deadline)
    session = _cold_process(tmp_path, mid, end_turn=True)
    assert _clock(session) == deadline
    for target in (ME, AN):
        assert not _suppressed(session, target) and len(_wards(session, target)) == 1
        assert not _copy_modifiers(session, target)
    ended = [e.payload["started_sequence"] for e in session.engine.events
             if e.event_type == "CONCENTRATION_ENDED" and e.source_definition_id == SEAL]
    assert ended == [first, second]
    assert concentration.copies(session.engine.state.actors[ME], SEAL) == []


@pytest.mark.parametrize("manual", [False, True], ids=["deadline", "manual"])
def test_zone_end_removes_inside_effects_and_subscriber_link(adapters, tmp_path, manual):
    mid, session = _match(tmp_path)
    session = _execute(tmp_path, mid, ZONE)
    [zone] = placed.of(session.engine, ZONE_TAG)
    holder = session.engine.state.actors[ME]
    assert any(c.condition_id == ZONE_LINK for c in holder.conditions.values())
    inside = [c for c in holder.conditions.values() if c.condition_id == zones.ZONE_EFFECT]
    assert len(inside) == 1 and inside[0].data["zone_id"] == zone.zone_id
    modifiers = set(inside[0].data["zone_modifiers"])
    assert modifiers and modifiers <= holder.modifiers.keys()
    session = (_execute(tmp_path, mid, DROP_ZONE) if manual
               else _cold_process(tmp_path, mid, end_turn=True))
    holder = session.engine.state.actors[ME]
    assert not session.engine.state.zones[zone.zone_id].active
    assert not any(c.condition_id in {ZONE_LINK, zones.ZONE_EFFECT} for c in holder.conditions.values())
    assert not modifiers & holder.modifiers.keys()
    observed = [(row["observer"], row["label"]) for row in _observations(session)]
    assert observed == [("a", "zone"), ("a", "zone-link"), ("b", "zone-link"), ("b", "zone")]
    _cold_process(tmp_path, mid)


@pytest.mark.parametrize("ending", ["deadline", "manual", "destroyed"])
def test_summon_end_removes_its_owned_aura_and_reconciles_recipients(adapters, tmp_path, ending):
    mid, session = _match(tmp_path, with_summon=True)
    session = _execute(tmp_path, mid, SUMMON)
    [creature] = summons.owned_by(session.engine, ME)
    assert creature.active and creature.summon["status"] == "present"
    owned_copies = concentration.copies(creature, SUMMON_FOCUS)
    assert len(owned_copies) == 2
    [aura] = placed.of(session.engine, AURA_TAG)
    assert aura.owner_id == creature.entity_id
    [independent] = placed.of(session.engine, INDEPENDENT_TAG)
    assert independent.owner_id == creature.entity_id and not independent.trigger_profile["follows_owner"]
    inside = [c for c in session.engine.state.actors[ME].conditions.values()
              if c.condition_id == zones.ZONE_EFFECT and c.data["zone_id"] == aura.zone_id]
    assert len(inside) == 1
    modifiers = set(inside[0].data["zone_modifiers"])
    if ending == "deadline":
        deadline = tuple(int(n) for n in creature.summon["expires_on"].rsplit(":", 2)[-2:])
        _advance_before(tmp_path, mid, deadline)
        session = _cold_process(tmp_path, mid, end_turn=True)
        assert _clock(session) == deadline
    else:
        session = _execute(tmp_path, mid, DESTROY_SUMMON if ending == "destroyed" else DROP_SUMMON)
    creature = session.engine.state.actors[creature.entity_id]
    assert not creature.active and creature.summon["status"] == ("destroyed" if ending == "destroyed" else "dismissed")
    assert not concentration.sources(creature)
    ended_copies = [e.payload["started_sequence"] for e in session.engine.events
                    if e.event_type == "CONCENTRATION_ENDED" and e.actor_id == creature.entity_id]
    assert sorted(ended_copies) == owned_copies
    assert not session.engine.state.zones[aura.zone_id].active
    assert session.engine.state.zones[independent.zone_id].active
    assert not any(c.condition_id == zones.ZONE_EFFECT and c.data["zone_id"] == aura.zone_id
                   for actor in session.engine.state.actors.values() for c in actor.conditions.values())
    assert not modifiers & session.engine.state.actors[ME].modifiers.keys()
    assert sum(e.event_type == "SUMMON_DISMISSED" and e.actor_id == creature.entity_id
               for e in session.engine.events) == int(ending != "destroyed")
    assert sum(e.event_type == "ENTITY_DEFEATED" and e.actor_id == creature.entity_id
               for e in session.engine.events) == int(ending == "destroyed")
    assert sum(e.event_type == "ZONE_REMOVED" and e.payload.get("zone_id") == aura.zone_id
               for e in session.engine.events) == 1
    _cold_process(tmp_path, mid)


def _observations(session):
    # Gate3 may append runtime snapshots to the final event of a transaction.
    # This nested field is the complete data the test subscriber emitted; the
    # full committed payload is independently compared to mechanical replay.
    return [e.payload["p07_observation"] for e in session.engine.events if e.source_definition_id == OBSERVATION]


def test_manual_and_deadline_endings_deliver_the_same_ordered_subscriber_events(adapters, tmp_path):
    outputs = []
    for label, manual in (("manual", True), ("deadline", False), ("deadline-again", False)):
        data = tmp_path / label
        mid, session = _match(data)
        session = _execute(data, mid, CHAIN)
        session = (_execute(data, mid, DROP_CHAIN) if manual else _cold_process(data, mid, end_turn=True))
        seen = _observations(session)
        assert [(row["observer"], row["label"]) for row in seen] == [
            ("a", "parent"), ("a", "child"), ("b", "child"), ("b", "parent")]
        assert all(row["identity_ok"] for row in seen)
        assert all(row["original_source"] == CHAIN for row in seen)
        assert all(row["original_data"] == {"p07_label": row["label"], "original": "kept"} for row in seen)
        assert len({(row["ending_id"], row["observer"]) for row in seen}) == len(seen)
        assert not any(c.condition_id in {PARENT, CHILD}
                       for c in session.engine.state.actors[ME].conditions.values())
        removed = [e for e in session.engine.events if e.event_type == "CONDITION_REMOVED"
                   and e.payload.get("condition_id") in {PARENT, CHILD}]
        assert len(removed) == 2  # observer A's reentrant removal never duplicates it
        outputs.append(seen)
        _cold_process(data, mid)
    # These are the complete subscriber-generated payloads. The caller's own
    # action/turn records and removal cause are intentionally different.
    assert outputs[0] == outputs[1] == outputs[2]


def test_native_expiry_removes_only_the_due_instance_of_a_shared_condition_name(adapters, tmp_path):
    mid, session = _match(tmp_path)
    session = _execute(tmp_path, mid, INSTANCES)
    before = {row.data["p07_label"]: row.instance_id
              for row in session.engine.state.actors[ME].conditions.values() if row.condition_id == SAME_NAMED}
    assert set(before) == {"due", "remaining"}
    session = _cold_process(tmp_path, mid, end_turn=True)
    conditions = session.engine.state.actors[ME].conditions
    assert before["due"] not in conditions
    assert conditions[before["remaining"]].data == {"p07_label": "remaining"}
    seen = _observations(session)
    assert [(row["observer"], row["ending_id"]) for row in seen] == [("a", before["due"]), ("b", before["due"])]
    assert all(row["identity_ok"] and row["original_source"] == INSTANCES
               and row["original_data"] == {"p07_label": "due"} for row in seen)


@pytest.mark.parametrize("failure, raised", [(ValueError, ext.CheckpointError), (ext.ControllerPause, ext.ControllerPause)],
                         ids=["subscriber-error", "controller-pause"])
def test_failed_ending_subscriber_unwinds_and_cold_retry_finishes_once(adapters, tmp_path, monkeypatch, failure, raised):
    mid, session = _match(tmp_path)
    session = _execute(tmp_path, mid, CHAIN)
    before = _snapshot(session)

    def fail(engine, event_type, kwargs):
        if event_type == "CONDITION_REMOVED" and kwargs.get("payload", {}).get("condition_id") == PARENT:
            raise failure("P07 ending subscriber failure")

    with monkeypatch.context() as local:
        local.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], fail])
        with pytest.raises(raised, match="P07 ending subscriber failure"):
            session.mechanical.execute_intent(_intent(session))
    assert _snapshot(session) == before
    assert not getattr(session.engine, "_effect_ending_depth", 0)
    assert not getattr(session.engine, "_expiring_effect_instances", set())
    assert not getattr(session.engine, "_ext_in_event", False)
    if failure is ext.ControllerPause:
        assert session.mechanical._records[-1]["record_type"] == "PREPARE"
        # The existing pause contract retains PREPARE. A new interpreter
        # resolves that exact request once after the question is answered.
        session = _cold_process(tmp_path, mid)
    else:
        _reload(tmp_path, mid, expected=before)
        session = _cold_process(tmp_path, mid, end_turn=True)
    assert not any(c.condition_id in {PARENT, CHILD}
                   for c in session.engine.state.actors[ME].conditions.values())
    assert [(row["observer"], row["label"]) for row in _observations(session)] == [
        ("a", "parent"), ("a", "child"), ("b", "child"), ("b", "parent")]
    assert sum(e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") in {PARENT, CHILD}
               for e in session.engine.events) == 2


def test_summon_deadline_rejects_restarted_concentration_and_rolls_back(adapters, tmp_path, monkeypatch):
    mid, session = _match(tmp_path, with_summon=True)
    session = _execute(tmp_path, mid, SUMMON)
    [creature] = summons.owned_by(session.engine, ME)
    creature_id = creature.entity_id
    owned_copies = concentration.copies(creature, SUMMON_FOCUS)
    deadline = tuple(int(n) for n in creature.summon["expires_on"].rsplit(":", 2)[-2:])
    session = _advance_before(tmp_path, mid, deadline)
    before = _snapshot(session)
    restarted = []

    def restart(engine, event_type, kwargs):
        if event_type == "CONCENTRATION_ENDED" and kwargs.get("actor_id") == creature_id:
            restarted.append(kwargs["payload"]["started_sequence"])
            # Keep the regression itself bounded if a future implementation
            # drains newly created copies forever instead of rejecting them.
            assert len(restarted) <= 4, "an invalid owner restart was repeatedly drained"
            engine._start_concentration(engine.state.actors[creature_id], SUMMON_FOCUS)

    with monkeypatch.context() as local:
        local.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], restart])
        with pytest.raises(ext.CheckpointError, match="Concentration restarted"):
            session.mechanical.execute_intent(_intent(session))
    assert sorted(restarted) == owned_copies
    assert _snapshot(session) == before
    assert not getattr(session.engine, "_effect_ending_depth", 0)
    _reload(tmp_path, mid, expected=before)
    session = _cold_process(tmp_path, mid, end_turn=True)
    creature = session.engine.state.actors[creature_id]
    assert not creature.active and not concentration.sources(creature)
    assert sum(e.event_type == "SUMMON_DISMISSED" and e.actor_id == creature_id
               for e in session.engine.events) == 1


@pytest.mark.parametrize("manual", [False, True], ids=["deadline", "manual-dispel"])
def test_affliction_end_uses_original_source_and_caster_for_its_companions(adapters, tmp_path, manual):
    mid, session = _match(tmp_path)
    session = _execute(tmp_path, mid, AFFLICTION)
    holder = session.engine.state.actors[ME]
    parents = {(c.source_definition_id, c.source_actor_id): c for c in holder.conditions.values()
               if c.condition_id == afflictions.condition_id()}
    companions = {(c.source_definition_id, c.source_actor_id): c for c in holder.conditions.values()
                  if c.condition_id == "condition:typed.silenced" and c.data.get("companion_of") == afflictions.NAME}
    assert parents.keys() == companions.keys() == {(AFFLICTION, AN), (AFFLICTION, ME), (OTHER_AFFLICTION, AN)}
    assert all(c.expires_on == "UNTIL_REMOVED" for c in companions.values())
    due = {parents[(AFFLICTION, AN)].instance_id, companions[(AFFLICTION, AN)].instance_id}
    controls = {c.instance_id: c.model_dump(mode="json")
                for key in ((AFFLICTION, ME), (OTHER_AFFLICTION, AN))
                for c in (parents[key], companions[key])}
    session = (_execute(tmp_path, mid, DROP_AFFLICTION) if manual
               else _cold_process(tmp_path, mid, end_turn=True))
    holder = session.engine.state.actors[ME]
    assert not due & holder.conditions.keys()
    assert {iid: holder.conditions[iid].model_dump(mode="json") for iid in controls} == controls
    removed = [e for e in session.engine.events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("instance_id") in due]
    assert len(removed) == 2 and {e.payload["instance_id"] for e in removed} == due
    [parent_ended] = [e for e in removed if e.payload["instance_id"] == parents[(AFFLICTION, AN)].instance_id]
    assert parent_ended.source_definition_id == (DROP_AFFLICTION if manual else SYSTEM_EXPIRATION)
    assert parent_ended.actor_id == ME
    assert not any(e.event_type == "CONDITION_REMOVED" and e.payload.get("instance_id") in controls
                   for e in session.engine.events)
    _cold_process(tmp_path, mid)


def test_removal_aftermath_does_not_recreate_a_suppressed_zone_membership(adapters, tmp_path):
    mid, session = _match(tmp_path, mechanics=("DARK_BASE_DARKNESS", "TAL_DARK_NUMBING_DARKNESS"))
    session = _execute(tmp_path, mid, name="Shape Darkness: Numbing Darkness")
    session = _execute(tmp_path, mid, name="Darkness", at=(10, 6))
    [membership] = [c for c in session.engine.state.actors[AN].conditions.values()
                    if c.condition_id == zones.ZONE_EFFECT]
    original = membership.model_dump(mode="json")
    area_key = membership.data["key"]
    zone_id = membership.data["zone_id"]

    def matching(saved):
        return [c for c in saved.engine.state.actors[AN].conditions.values()
                if c.condition_id == zones.ZONE_EFFECT and c.data.get("key") == area_key]

    session = _execute(tmp_path, mid, SUPPRESS_ZONE)
    assert session.engine.state.zones[zone_id].active
    assert matching(session) == [] and len(_suppressed(session, AN)) == 1
    session = _cold_process(tmp_path, mid)
    assert matching(session) == [] and len(_suppressed(session, AN)) == 1
    session = _execute(tmp_path, mid, RESTORE_ZONE)
    assert not _suppressed(session, AN)
    assert [c.model_dump(mode="json") for c in matching(session)] == [original]
    session = _cold_process(tmp_path, mid)
    assert session.engine.state.zones[zone_id].active
    assert [c.model_dump(mode="json") for c in matching(session)] == [original]


def test_refresh_preserves_omitted_source_slots_across_cold_reload(adapters, tmp_path):
    mid, session = _match(tmp_path, with_summon=True, finalized_turns=True)
    session = _execute(tmp_path, mid, CLOCK_SETUP)
    holder = session.engine.state.actors[ME]
    original = eye_patient_eye.record(holder)
    assert original is not None
    source_id = original.source_actor_id
    source_turns = session.engine.state.actors[source_id].turns_started
    old_key = effect_durations.expiry_key(original)
    assert effect_durations.skipped_expiry_slots(holder, original) == 0

    # ME's next slot is its destroyed summon. A new interpreter advances that
    # nominal boundary without manufacturing a turn for the finalized source.
    session = _cold_process(tmp_path, mid, end_turn=True)
    while session.engine.state.current_actor_id != ME:
        session = _execute(tmp_path, mid)
    holder = session.engine.state.actors[ME]
    assert effect_durations.skipped_expiry_slots(holder, original) == 1
    session = _execute(tmp_path, mid, CLOCK_REFRESH)
    session = _cold_process(tmp_path, mid)
    holder = session.engine.state.actors[ME]
    replacement = eye_patient_eye.record(holder)
    assert replacement is not None and replacement.instance_id != original.instance_id
    assert replacement.data["p07_refreshed"] is True
    assert replacement.expires_on == original.expires_on
    assert effect_durations.skipped_expiry_slots(holder, replacement) == 1
    assert old_key not in holder.turn_flags
    removed = [e for e in session.engine.events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("instance_id") == original.instance_id]
    assert len(removed) == 1 and removed[0].source_definition_id == eye_patient_eye.SOURCE

    session = _execute(tmp_path, mid)
    while session.engine.state.current_actor_id != ME:
        session = _execute(tmp_path, mid)
    holder = session.engine.state.actors[ME]
    assert replacement.instance_id in holder.conditions
    assert effect_durations.skipped_expiry_slots(holder, replacement) == 2
    session = _cold_process(tmp_path, mid, end_turn=True)
    holder = session.engine.state.actors[ME]
    assert eye_patient_eye.record(holder) is None
    assert effect_durations.expiry_key(replacement) not in holder.turn_flags
    removed = [e for e in session.engine.events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("instance_id") == replacement.instance_id]
    assert len(removed) == 1 and removed[0].source_definition_id == SYSTEM_EXPIRATION
    assert session.engine.state.actors[source_id].turns_started == source_turns
    assert not any(e.event_type in {"TURN_STARTED", "TURN_ENDED"} and e.actor_id == source_id
                   for e in session.engine.events)


def _cold_main():
    assert sys.argv[1] == "--cold"
    _install_adapters()
    data, mid = Path(sys.argv[2]), sys.argv[3]
    session = _reload(data, mid)
    if "--end-turn" in sys.argv[4:]:
        session = _execute(data, mid)
    print(json.dumps({"verify": "PASS", "replay": "PASS", "snapshot": _snapshot(session)}, sort_keys=True))


if __name__ == "__main__":
    _cold_main()
