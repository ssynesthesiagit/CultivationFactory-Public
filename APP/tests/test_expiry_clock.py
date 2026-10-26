"""Durations counted in rounds (expiry-clock fix 2026-09-28). "For 1 minute" on anything but a Concentration technique had no
clock: a condition fell back to the end of the holder's next turn, a modifier stayed for the rest of the fight. The standard is
the shared units (1 round is one full round, 1 minute is 10 rounds, 1 hour is 600 rounds; only scene kinds last the fight), run by
combat/ext/effect_durations.py's START_OF_SLOT_AT name; typed_executor.effect_expiry / Context.expires_on route the kinds to it
(the table in combat/rules/typed_conditions.json). Concentration stays on CONCENTRATION_END."""

import pytest

from combat import typed_executor, zones
from combat.ext import effect_durations
from combat.gate2_engine import Gate2Engine
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from tests.test_auto_docket import AN, ME
from tests.test_effect_durations import LASTING, _conditions, _ctx, _expiry, _fight, _modifiers

MINUTE = {"kind": "minutes", "amount": 1, "concentration": False}
SLOW = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute", "evidence": "Its Speed is reduced by 10 feet."}
SCARE = {"type": "condition", "condition": "frightened", "applies_to": "target", "duration": "one_minute", "evidence": "It is Frightened."}
WARD = {"type": "ac_bonus", "applies_to": "self", "flat": 2, "duration": "hours", "evidence": "You gain a +2 bonus to AC."}


def _at(engine, rounds):
    """The round name for ``rounds`` rounds from this place in the turn order."""
    return f"START_OF_SLOT_AT:{engine.state.round_number + rounds}:{engine.state.current_slot_index}"


def _rounds(engine, count):
    """Play ``count`` whole rounds: every creature's turn ends once per round, back to the creature whose turn it was."""
    for _ in range(count * len(engine.state.initiative_order)):
        engine.end_turn()


# ------------------------------------------------------------------ the name
def test_the_round_names_read_back():
    engine, _me, _foe = _fight("ROUND-NAMES")
    name = effect_durations.round_token(engine, 10)
    assert name == _at(engine, 10)
    assert effect_durations.parse_round(name) == (engine.state.round_number + 10, engine.state.current_slot_index)
    assert effect_durations.parse(name) is None  # not one of the per-creature names
    assert effect_durations.round_token(engine, 0) == effect_durations.round_token(engine, 1)  # a duration lasts at least a round
    for other in ("START_OF_TURN_AT:actor:x:3", "START_OF_SLOT_AT:3", "START_OF_SLOT_AT:x:1", "START_OF_SLOT_AT:3:", "START_OF_SLOT_AT:-3:1",
                  "END_OF_SOURCE_TURN_AT:3", "UNTIL_REMOVED", None, ""):
        assert effect_durations.parse_round(other) is None, other


def test_a_round_name_comes_due_at_the_same_place_in_the_turn_order_and_not_before():
    engine, _me, _foe = _fight("ROUND-DUE")
    now, slot = engine.state.round_number, engine.state.current_slot_index
    name = effect_durations.round_token(engine, 1)
    for round_number in (now, now + 1, now + 2):
        for slot_index in range(len(engine.state.initiative_order)):
            engine.state.round_number, engine.state.current_slot_index = round_number, slot_index
            over = round_number > now + 1 or (round_number == now + 1 and slot_index >= slot)  # that slot of the next round on
            assert effect_durations.due(engine, name) is over, (round_number, slot_index)


@pytest.mark.parametrize("duration", [{"kind": "rounds", "amount": 1}, {"kind": "rounds", "amount": 3}, {"kind": "rounds"},
                                      {"kind": "minutes", "amount": 1}, {"kind": "minutes", "amount": 2}, {"kind": "minutes"}])
def test_the_standard_is_the_zones(duration):
    engine, _me, _foe = _fight("STANDARD")
    name = typed_executor.duration_expiry(engine, duration)
    assert effect_durations.parse_round(name)[0] - engine.state.round_number == zones._duration_rounds(duration)


def test_the_length_of_a_unit_is_the_rules_to_change():
    assert typed_executor.rules()["duration_rounds"]["rounds"] == 1 and typed_executor.rules()["duration_rounds"]["minutes"] == 10
    engine, _me, _foe = _fight("UNIT")
    assert typed_executor.clock_expiry(engine, "minutes", 3) == _at(engine, 30)
    assert typed_executor.clock_expiry(engine, "one_minute") == _at(engine, 10)
    for kind, count in (("hours", 600), ("days", 14400), ("one_hour", 600)):
        assert typed_executor.clock_expiry(engine, kind) == _at(engine, count)
    assert typed_executor.clock_expiry(engine, "until_end_of_scene") == "UNTIL_REMOVED"
    for kind in ("instant", "special", "one_round", "concentration", "until_removed", "_rule", "", None):
        assert typed_executor.clock_expiry(engine, kind) is None, kind  # the table's own note is text, not a length


# ------------------------------------------------------------------ what an ability lasts
def test_an_abilitys_duration_counts_rounds_and_the_fight():
    engine, me, foe = _fight("ABILITY")

    def lasts(duration):
        return _ctx(engine, me, foe, duration).expires_on()

    assert lasts({"kind": "minutes", "amount": 1}) == _at(engine, 10)
    assert lasts({"kind": "minutes", "amount": 2, "concentration": False}) == _at(engine, 20)
    assert lasts({"kind": "rounds", "amount": 3}) == _at(engine, 3)
    assert lasts({"kind": "rounds"}) == _at(engine, 1)
    for kind, count in (("hours", 600), ("days", 14400), ("one_hour", 600)):
        assert lasts({"kind": kind, "amount": 1}) == _at(engine, count)
    for kind in ("until_end_of_scene", "until_removed"):
        assert lasts({"kind": kind, "amount": 1}) == "UNTIL_REMOVED", kind
    assert lasts({"kind": "special", "text": "The scene"}) == "UNTIL_REMOVED"
    assert lasts({"kind": "special", "text": "Until the end of the scene."}) == "UNTIL_REMOVED"
    assert lasts({"kind": "special", "text": "Until you take a long rest"}) is None  # names no clock
    assert lasts({"kind": "special"}) is None and lasts({"kind": "instant"}) is None and lasts({}) is None
    assert lasts({"kind": "until_start_of_next_turn"}) == "START_OF_SOURCE_NEXT_TURN"  # the engine's own names are as they were
    assert lasts({"kind": "target_next_turn"}) == "END_OF_HOLDER_NEXT_TURN"


def test_concentration_stays_on_its_own_end_at_every_length():
    engine, me, foe = _fight("CONC")
    for kind, amount in (("minutes", 1), ("rounds", 3), ("hours", 1), ("until_end_of_scene", 1), ("instant", 1)):
        held = {"kind": kind, "amount": amount, "concentration": True}
        assert _ctx(engine, me, foe, held).expires_on() == "CONCENTRATION_END", kind
        for effect_kind in ("one_minute", "minutes", "rounds", "hours", "one_hour", "until_end_of_scene", "instant", "concentration"):
            assert _expiry(_ctx(engine, me, foe, held), {"duration": effect_kind}, foe, condition=True) == "CONCENTRATION_END", (kind, effect_kind)
    assert _expiry(_ctx(engine, me, foe, LASTING), {"duration": "one_minute"}, foe, condition=True) == "CONCENTRATION_END"
    assert _expiry(_ctx(engine, me, foe, LASTING), {"duration": "one_minute"}, foe) == "CONCENTRATION_END"  # a modifier as well


def test_an_effect_counts_its_own_amount_else_the_abilitys_in_the_same_unit():
    engine, me, foe = _fight("AMOUNT")
    two_minutes = _ctx(engine, me, foe, {"kind": "minutes", "amount": 2, "concentration": False})
    assert _expiry(two_minutes, {"duration": "minutes"}, foe) == _at(engine, 20)  # the ability's two
    assert _expiry(two_minutes, {"duration": {"kind": "minutes", "amount": 3}}, foe) == _at(engine, 30)  # its own three
    assert _expiry(two_minutes, {"duration": "one_minute"}, foe) == _at(engine, 10)  # "one minute" says its own length
    assert _expiry(two_minutes, {"duration": "rounds"}, foe) == _at(engine, 1)  # another unit: not the ability's two
    assert _expiry(two_minutes, {"duration": "hours"}, foe) == _at(engine, 600)


def test_the_words_of_an_effect_still_beat_the_clock():
    engine, me, foe = _fight("WORDS-CLOCK")
    ctx = _ctx(engine, me, foe, MINUTE)
    said = {"duration": "one_minute", "evidence": "Speed is reduced by 10 feet until the start of its next turn."}
    assert _expiry(ctx, said, foe) == effect_durations.token("start", AN, foe.turns_started + 1)
    assert _expiry(ctx, {**said, "expires_on": "UNTIL_REMOVED"}, foe) == "UNTIL_REMOVED"
    # (the effect kind one_round is not counted: the typing also uses it for "once per round", so the ability's own length stands)
    assert _expiry(ctx, {"duration": "one_round", "evidence": "It cannot take Reactions."}, foe) == _at(engine, 10)


def test_a_mark_for_a_minute_lasts_ten_rounds_unless_it_rides_a_concentration():
    engine, me, foe = _fight("MARKS")
    condition_id = typed_executor.mark_condition_id("Quarry", ME)

    def placed(context, duration):
        typed_executor.run_effects(context, [{"type": "mark", "mark": "Quarry", "applies_to": "target", "duration": duration}])
        return [c.expires_on for c in foe.conditions.values() if c.condition_id == condition_id]

    assert placed(_ctx(engine, me, foe), {"kind": "minutes", "amount": 1}) == [_at(engine, 10)]
    assert placed(_ctx(engine, me, foe), {"kind": "one_minute"}) == [_at(engine, 10)]  # refreshed, not stacked
    assert placed(_ctx(engine, me, foe), {"kind": "rounds", "amount": 2}) == [_at(engine, 2)]
    assert placed(_ctx(engine, me, foe), {"kind": "hours"}) == [_at(engine, 600)]
    assert placed(_ctx(engine, me, foe), {"kind": "until_removed"}) == ["UNTIL_REMOVED"]
    assert placed(_ctx(engine, me, foe, LASTING), {"kind": "one_minute"}) == ["CONCENTRATION_END"]
    assert placed(_ctx(engine, me, foe, LASTING), {"kind": "concentration"}) == ["CONCENTRATION_END"]


def test_an_on_hit_bonus_lasts_as_long_as_the_ability_does():
    engine, me, foe = _fight("ON-HIT")
    effect = {"type": "on_hit_bonus", "evidence": "Your weapon attacks deal +1d4 fire damage."}
    typed_executor._register_on_hit(_ctx(engine, me, foe, MINUTE), effect)
    typed_executor._register_on_hit(_ctx(engine, me, foe, LASTING), {**effect, "evidence": "Your fists deal +1d4 cold damage."})
    assert sorted(m.expires_on for m in _modifiers(me, "typed_on_hit")) == sorted([_at(engine, 10), "CONCENTRATION_END"])


# ------------------------------------------------------------------ over the rounds
def test_a_minute_lasts_ten_rounds_and_ends_where_it_began_in_the_turn_order():
    engine, me, foe = _fight("TEN-ROUNDS")
    started = engine.state.round_number
    ctx = _ctx(engine, me, foe, MINUTE)
    typed_executor.run_effects(ctx, [SCARE, SLOW, WARD])
    assert [c.expires_on for c in _conditions(foe, "frightened")] == [_at(engine, 10)]
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == [_at(engine, 10)]
    assert [m.expires_on for m in _modifiers(me, "armor_class")] == [_at(engine, 600)]  # one hour has a clock too
    _rounds(engine, 9)
    assert engine.state.current_actor_id == ME and engine.state.round_number == started + 9  # nine whole rounds on
    assert _conditions(foe, "frightened") and _modifiers(foe, "speed_ft")
    engine.end_turn()  # the foe's turn, the last of the tenth round
    assert engine.state.current_actor_id == AN and _conditions(foe, "frightened") and _modifiers(foe, "speed_ft")
    engine.end_turn()  # and the applier's turn comes round again
    assert engine.state.current_actor_id == ME and engine.state.round_number == started + 10
    assert not _conditions(foe, "frightened") and not _modifiers(foe, "speed_ft")
    assert _modifiers(me, "armor_class")  # the hour's did not
    removed = [e for e in engine.events if e.source_definition_id == "system:combat.expiration"]
    assert sorted(e.event_type for e in removed) == ["CONDITION_REMOVED", "MODIFIER_REMOVED"]
    assert {(e.actor_id, e.target_ids, e.payload["checkpoint"]) for e in removed} == {(ME, (AN,), "START_OF_TURN")}  # what a replay reads


def test_one_round_is_one_full_round():
    engine, me, foe = _fight("ONE-ROUND")
    started = engine.state.round_number
    typed_executor.run_effects(_ctx(engine, me, foe, {"kind": "rounds", "amount": 1}),
                               [{"type": "condition", "condition": "frightened", "applies_to": "target", "duration": "rounds"}])
    engine.end_turn()
    assert engine.state.current_actor_id == AN and _conditions(foe, "frightened")  # still under it through its own turn
    engine.end_turn()
    assert engine.state.current_actor_id == ME and engine.state.round_number == started + 1
    assert not _conditions(foe, "frightened")
    (removed,) = [e for e in engine.events if e.event_type == "CONDITION_REMOVED"]
    assert removed.payload["checkpoint"] == "START_OF_TURN"  # as the applier's turn began, not as the holder's ended


def test_a_reaction_counts_from_the_place_it_happens_in():
    engine, me, foe = _fight("REACTION-SLOT")
    engine.end_turn()  # the foe's turn: the user answers it with a Reaction
    assert engine.state.current_actor_id == AN
    typed_executor.run_effects(_ctx(engine, me, foe, MINUTE), [SCARE])
    (condition,) = _conditions(foe, "frightened")
    assert effect_durations.parse_round(condition.expires_on) == (engine.state.round_number + 10, engine.state.initiative_order.index(AN))


def test_a_replay_of_the_events_reaches_the_same_conditions_and_modifiers():
    engine, me, foe = _fight("REPLAY-CLOCK")
    typed_executor.run_effects(_ctx(engine, me, foe, MINUTE), [SCARE, SLOW, WARD])
    before, mark = engine.state.model_copy(deep=True), len(engine.events)
    _rounds(engine, 10)
    assert not _conditions(foe, "frightened") and not _modifiers(foe, "speed_ft") and _modifiers(me, "armor_class")
    events = enrich_committed_events(engine.events[mark:], post_engine=engine)
    replayed = Gate3EventReducer().apply_events(before, events, expected_start_sequence=before.event_sequence + 1)
    for actor_id, actor in engine.state.actors.items():
        assert sorted(replayed.actors[actor_id].conditions) == sorted(actor.conditions), actor_id
        assert sorted(replayed.actors[actor_id].modifiers) == sorted(actor.modifiers), actor_id
    assert not [c for c in replayed.actors[AN].conditions.values() if c.condition_id.endswith("frightened")]


def test_a_bare_engine_leaves_the_round_names_alone():
    engine, me, foe = _fight("BARE-CLOCK", Gate2Engine)  # the hooks exist only under the Gate 4 engine (combat/gate4_engine.py)
    typed_executor.run_effects(_ctx(engine, me, foe, MINUTE), [SLOW])
    (modifier,) = _modifiers(foe, "speed_ft")
    assert effect_durations.parse_round(modifier.expires_on) is not None
    _rounds(engine, 11)  # the bare engine does not know the name: the fight ends before it matters
    assert _modifiers(foe, "speed_ft")
