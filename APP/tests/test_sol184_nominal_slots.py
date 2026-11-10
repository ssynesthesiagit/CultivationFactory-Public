"""Finalized slots keep deadlines, never creature-turn gameplay or decisions."""
import pytest

from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_models import ZoneState, Position
from combat.turn_decisions import omits_turn
from combat.ext import effect_durations as durations
from tests.h1_support import ROOT
from tests.test_effect_durations import _fight


def engine():
    e = Gate4ControllerEngine(ROOT, match_seed="SOL184", maximum_rounds=6)
    e.state.rules["finalized_turns"] = "skip_finalized_v1"
    order = e.state.initiative_order
    return e, e.state.actors[order[1]], e.state.actors[order[0]]


def omit(e, actor):
    actor.active = False
    actor.current_hp = 0
    actor.life_state = None
    actor.action_available = actor.bonus_action_available = actor.reaction_available = False
    actor.movement_remaining_ft = 0


def advance_to_nominal(e, dead):
    before = dead.turns_started
    sequence = e.state.event_sequence
    while e.state.current_slot_index != (e.state.initiative_order.index(dead.entity_id) - 1) % len(e.state.initiative_order):
        e.end_turn()
    e.end_turn()
    assert dead.turns_started == before
    assert not [event for event in e.events if event.sequence > sequence and event.actor_id == dead.entity_id
                and event.event_type in ("TURN_STARTED", "TURN_ENDED")]


@pytest.mark.parametrize("life,active,dead,expected", [
    (None, True, False, False), ("CONSCIOUS", True, False, False),
    ("DYING", True, False, False), ("STABLE", True, False, False),
    ("DYING", False, False, False), ("STABLE", False, False, False),
    (None, False, False, True), ("CONSCIOUS", True, True, True)])
def test_only_defeated_or_dead_slots_are_omitted(life, active, dead, expected):
    e, actor, _ = engine()
    actor.current_hp = 0
    actor.life_state, actor.active = life, active
    if dead:
        e._apply_condition(actor, "condition:typed.death_finalized", "test", actor.entity_id, expires_on="UNTIL_REMOVED")
    assert omits_turn(e, actor.entity_id) is expected
    e.state.rules.pop("finalized_turns")
    assert not omits_turn(e, actor.entity_id)


@pytest.mark.parametrize("token,holder_is_dead,source_is_dead,edge", [
    ("START_OF_SELF_NEXT_TURN", True, False, "START_OF_TURN"),
    ("START_OF_SOURCE_NEXT_TURN", False, True, "START_OF_TURN"),
    ("END_OF_HOLDER_NEXT_TURN", True, False, "END_OF_TURN"),
    ("END_OF_SOURCE_TURN_AT:1", False, True, "END_OF_TURN"),
    ("START_OF_TURN_AT:{dead}:1", False, False, "START_OF_TURN"),
    ("END_OF_TURN_AT:{dead}:1", False, False, "END_OF_TURN")])
def test_native_and_extension_source_holder_expiry_at_omitted_slot(token, holder_is_dead, source_is_dead, edge):
    e, dead, living = engine()
    omit(e, dead)
    holder, source = (dead if holder_is_dead else living), (dead if source_is_dead else living)
    expiry = token.format(dead=dead.entity_id)
    e._apply_condition(holder, "condition:typed.sol184_expiry", "test:expiry", source.entity_id, expires_on=expiry)
    mid = e._add_modifier(holder, "test:expiry", "armor_class", "ADD", 1, "SELF", expires_on=expiry)
    holder.modifiers[mid].source_actor_id = source.entity_id
    advance_to_nominal(e, dead)
    assert not [c for c in holder.conditions.values() if c.source_definition_id == "test:expiry"]
    assert not [m for m in holder.modifiers.values() if m.source_definition_id == "test:expiry"]
    removals = [ev for ev in e.events if ev.event_type in ("CONDITION_REMOVED", "MODIFIER_REMOVED")
                and ev.payload.get("checkpoint") == edge and holder.entity_id in ev.target_ids]
    assert len(removals) == 2


def test_counted_expiry_survives_multiple_omissions_new_effects_and_revival():
    e, dead, living = engine()
    omit(e, dead)
    e._apply_condition(living, "condition:typed.sol184_three", "test:three", dead.entity_id,
                       expires_on=f"END_OF_SOURCE_TURN_AT:{dead.turns_started + 3}")
    advance_to_nominal(e, dead)
    assert any(c.source_definition_id == "test:three" for c in living.conditions.values())
    e._apply_condition(living, "condition:typed.sol184_later", "test:later", dead.entity_id,
                       expires_on=durations.token("end", dead.entity_id, dead.turns_started + 2))
    advance_to_nominal(e, dead)
    assert {c.source_definition_id for c in living.conditions.values()} >= {"test:three", "test:later"}
    dead.active, dead.current_hp = True, 1
    for _ in range(len(e.state.initiative_order)):
        e.end_turn()
    assert dead.turns_started == 1
    assert not [c for c in living.conditions.values() if c.source_definition_id in {"test:three", "test:later"}]
    assert not [key for key in living.turn_flags if key.startswith("expiry_round_skipped:")]


def test_slot_expiry_and_owned_zone_deadlines_keep_their_position():
    e, dead, living = engine()
    omit(e, dead)
    slot = e.state.initiative_order.index(dead.entity_id)
    e._apply_condition(living, "condition:typed.sol184_round", "test:clock", living.entity_id,
                       expires_on=f"START_OF_SLOT_AT:{e.state.round_number}:{slot}")
    for field in ("start_of_owner_turn", "end_after_owner_turn", "rounds"):
        zone = ZoneState(zone_id=f"zone:{field}", owner_id=dead.entity_id, source_definition_id="test:clock",
                         center=Position(x=1,y=1), radius_cells=0, affected_cells=(Position(x=1,y=1),),
                         concentration_link=False, duration_rounds=1 if field == "rounds" else None,
                         created_round=0, trigger_profile={"kind": "TYPED", **({field: 1} if field != "rounds" else {})})
        e.state.zones[zone.zone_id] = zone
    advance_to_nominal(e, dead)
    assert not any(c.source_definition_id == "test:clock" for c in living.conditions.values())
    assert all(not z.active for z in e.state.zones.values() if z.source_definition_id == "test:clock")


def test_all_omitted_slots_reach_round_limit_without_turn_events():
    e, _, _ = engine()
    for actor in e.state.actors.values():
        omit(e, actor)
    seq = e.state.event_sequence
    e.end_turn()
    assert e.state.terminal_result.kind.value == "DRAW_DURATION"
    assert not any(ev.event_type == "TURN_STARTED" for ev in e.events if ev.sequence > seq)


def test_omitted_slot_runs_no_turn_boundary_start_or_repeat_saves(monkeypatch):
    from tests.test_lock_choices import install
    e, dead, _ = engine()
    omit(e, dead)
    seen = []
    install(monkeypatch, "turn_boundary_start", lambda engine, actor: seen.append(actor.entity_id))
    e._apply_condition(dead, "condition:typed.sol184_repeat", "test:repeat", dead.entity_id, expires_on="UNTIL_REMOVED",
                       data={"burn": 1, "repeat_save": {"ability": "CON", "dc": 10}})
    rolls = len(e.rolls)
    advance_to_nominal(e, dead)
    assert dead.entity_id not in seen
    assert len(e.rolls) == rolls
