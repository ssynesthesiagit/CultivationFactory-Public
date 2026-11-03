"""Modifiers stamped CONCENTRATION_END come off when the concentration does (expiry-clock fix 2026-09-28). The sealed engine's
_end_concentration removed the conditions of that expiry and never looked at ``modifiers``, so a "+2 AC while you concentrate"
or a Speed penalty from a Concentration technique stayed for the rest of the fight. combat/ext/concentration_modifiers.py
(the CONCENTRATION_ENDED event) and combat/concentration.py (end_held, for the older ones a fighter holds) take them off."""

from combat import concentration, typed_executor
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from tests.test_effect_durations import LASTING, _ctx, _fight, _modifiers

SPEED = {"type": "speed", "applies_to": "target", "flat": -10, "evidence": "its Speed is reduced by 10 feet"}
ARMOR = {"type": "ac_bonus", "applies_to": "self", "flat": 2, "evidence": "+2 AC"}


def _concentrate(engine, me, foe, effects=(SPEED, ARMOR)):
    ctx = _ctx(engine, me, foe, LASTING)
    engine._start_concentration(me, ctx.source)
    typed_executor.run_effects(ctx, list(effects))
    return ctx.source


def _stamped(engine, source):
    return sorted((actor.entity_id, mid) for actor in engine.state.actors.values()
                  for mid, m in actor.modifiers.items() if m.source_definition_id == source and m.expires_on == "CONCENTRATION_END")


def _removed(engine):
    return [(e.target_ids, e.payload["modifier_id"], e.payload["reason"]) for e in engine.events if e.event_type == "MODIFIER_REMOVED"]


def test_a_technique_that_ends_takes_its_modifiers_with_it():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe)
    stamped = _stamped(engine, source)
    assert len(stamped) == 2  # the Speed penalty on the foe and the AC bonus on the user, both "while you concentrate"
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert not _stamped(engine, source) and not _modifiers(foe, "speed_ft") and not _modifiers(me, "armor_class")
    assert sorted((target[0], mid) for target, mid, reason in _removed(engine)) == stamped  # each one has its event, filed under its holder
    assert {reason for _target, _mid, reason in _removed(engine)} == {"FAILED_DAMAGE_CHECK"}
    assert [e.source_definition_id for e in engine.events if e.event_type == "MODIFIER_REMOVED"] == [source, source]


def test_the_engines_own_ending_paths_all_reach_the_modifiers():
    for reason in ("FAILED_DAMAGE_CHECK", "ENTITY_DEFEATED", "VOLUNTARY", "REPLACED"):
        engine, me, foe = _fight(seed=f"CONC-{reason}")
        source = _concentrate(engine, me, foe)
        engine._end_concentration(me, reason)
        assert not _stamped(engine, source), reason


def test_recasting_replaces_the_old_modifiers_and_keeps_the_new_ones():
    # Owner ruling 2026-09-29: "they can hold any number of the same spells as long as they arent the same stacking buff". A
    # recast no longer ends the first copy (it was REPLACED before); both are held, but the same buff on the same creature does
    # not stack: the newer copy's modifier takes the older one's place (REFRESHED), so each holder still has one of each.
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe)
    old = _stamped(engine, source)
    again = _concentrate(engine, me, foe)
    assert again == source
    now = _stamped(engine, source)
    assert len(now) == 2 and not set(now) & set(old)  # one Speed penalty and one AC bonus, the recast's own
    assert {reason for _target, _mid, reason in _removed(engine)} == {"REFRESHED"}
    assert len(concentration.copies(me, source)) == 2 and len(concentration.held(me)) == 1  # the first copy is still held


def test_only_that_concentrations_modifiers_go():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe)
    other = f"{source}.OTHER"
    engine._add_modifier(foe, other, "speed_ft", "ADD", -5, "ALWAYS", expires_on="CONCENTRATION_END")  # another technique's
    engine._add_modifier(foe, source, "speed_ft", "ADD", -3, "ALWAYS", expires_on="UNTIL_REMOVED")  # not stamped for it
    engine._add_modifier(foe, source, "speed_ft", "ADD", -2, "ALWAYS", expires_on="END_OF_CURRENT_TURN")
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert sorted((m.source_definition_id, m.expires_on) for m in foe.modifiers.values()) == sorted(
        [(other, "CONCENTRATION_END"), (source, "UNTIL_REMOVED"), (source, "END_OF_CURRENT_TURN")])


def test_the_lingering_conflagration_handover_does_not_strip_them():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe)
    before = _stamped(engine, source)
    engine._append_event("CONCENTRATION_ENDED", source, actor_id=me.entity_id,
                         payload={"reason": "LINGERING_CONFLAGRATION", "zone_persists": True})  # the area stays, the technique's hold does not end
    assert _stamped(engine, source) == before


def test_one_held_beside_the_current_technique_ends_its_modifiers_too():
    engine, me, foe = _fight()
    assert concentration.limit(engine, me) >= 2  # a Level 5 fighter holds two at once
    first = _concentrate(engine, me, foe)
    engine._start_concentration(me, f"{first}.SECOND")  # a second technique: the first is held now, not ended
    assert concentration.concentrating_on(me, first) and _stamped(engine, first)
    (instance_id, _state), = concentration.held(me)
    concentration.end_held(engine, me, instance_id, "REPLACED")
    assert not _stamped(engine, first) and not concentration.concentrating_on(me, first)
    assert {reason for _target, _mid, reason in _removed(engine)} == {"REPLACED"} and len(_removed(engine)) == 2


def test_a_replay_of_the_events_reaches_the_same_modifiers():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe)
    before, mark = engine.state.model_copy(deep=True), len(engine.events)
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    events = enrich_committed_events(engine.events[mark:], post_engine=engine)
    replayed = Gate3EventReducer().apply_events(before, events, expected_start_sequence=before.event_sequence + 1)
    assert {aid: sorted(actor.modifiers) for aid, actor in replayed.actors.items()} == \
        {aid: sorted(actor.modifiers) for aid, actor in engine.state.actors.items()}
    assert not _stamped(engine, source)
