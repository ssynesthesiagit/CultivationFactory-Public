"""The same Concentration technique held more than once (owner ruling 2026-09-29, after Tabik cast a second Darkness and the
first ended REPLACED: "they can hold any number of the same spells as long as they arent the same stacking buff or something").

New bundles have no capacity ceiling; two legacy-mode regressions retain the old CL overflow behavior. A failed save
ends only the newest, and every effect an ended copy made goes with that copy alone. What may not happen is the same buff
twice on one creature: a second copy's modifier/condition replaces the older copy's, and a creature standing inside two
copies of one area gets that area's effect once. gate2_engine._start_concentration/_end_concentration,
combat/concentration.py, combat/zones.py sync_inside, combat/ext/concentration_copies.py."""

from combat import concentration, zones
from combat.gate2_runtime_content import AN
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from tests.test_auto_docket import ME, _do, _my_turn
from tests.test_concentration_modifiers import ARMOR, SPEED, _concentrate, _removed, _stamped
from tests.test_effect_durations import LASTING, _ctx, _fight, _modifiers
from tests.test_multi_concentration import _engine, capped_capacity

DARKNESS = "Darkness"


def _darkness(engine, at, shape=None):
    _my_turn(engine)  # a fresh turn: its action and Qi are back
    if shape:
        _do(engine, f"Shape Darkness: {shape}")
    _do(engine, DARKNESS, at=at)


def _reasons(engine, event_type="ZONE_REMOVED"):
    return [(e.payload or {}).get("reason") for e in engine.events if e.event_type == event_type]


def _inside_effects(actor):
    return sorted(c.data["key"] for c in actor.conditions.values() if c.condition_id == zones.ZONE_EFFECT)


def test_two_darknesses_stand_together_at_cl5():
    engine, me = _engine(5)
    _darkness(engine, (10, 6))
    [first] = zones.typed_zones(engine)
    _darkness(engine, (12, 6))
    both = zones.typed_zones(engine)
    assert len(both) == 2 and first.zone_id in {zone.zone_id for zone in both}  # the first was not REPLACED
    source = me.concentration.source_definition_id
    assert concentration.sources(me) == [source, source] and len(concentration.copies(me, source)) == 2
    assert "REPLACED" not in _reasons(engine, "ZONE_REMOVED") + _reasons(engine, "CONCENTRATION_ENDED")


def test_a_failed_save_ends_only_the_newest_darkness():
    engine, me = _engine(5)
    _darkness(engine, (10, 6))
    [older] = zones.typed_zones(engine)
    _darkness(engine, (12, 6))
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")  # what _concentration_check does on a failed save
    [left] = zones.typed_zones(engine)
    assert left.zone_id == older.zone_id  # ending one copy did not take the other's zone with it
    assert me.concentration is not None and me.concentration.zone_id == older.zone_id and concentration.held(me) == []
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert not zones.typed_zones(engine) and me.concentration is None


def test_the_area_effect_is_one_condition_however_many_darknesses_overlap():
    engine, me = _engine(5, talents=("TAL_DARK_NUMBING_DARKNESS",))
    foe = engine.state.actors[AN]
    _darkness(engine, (10, 6), shape="Numbing Darkness")
    single = _inside_effects(foe)
    assert single
    _darkness(engine, (11, 6), shape="Numbing Darkness")  # the foe at (10, 6) stands in both
    newest = max(zones.typed_zones(engine), key=lambda zone: int(zone.zone_id.rsplit(":", 1)[-1]))
    twice = _inside_effects(foe)
    assert len(twice) == len(single) and all(key.startswith(newest.zone_id + "|") for key in twice)  # once, from the newest copy
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")  # the newest ends: the older still covers it
    assert len(_inside_effects(foe)) == len(single) and not any(key.startswith(newest.zone_id + "|") for key in _inside_effects(foe))
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert _inside_effects(foe) == []


def test_at_cl5_a_third_darkness_ends_the_oldest(capped_capacity):
    engine, me = _engine(5)
    _darkness(engine, (10, 6))
    [oldest] = zones.typed_zones(engine)
    _darkness(engine, (12, 6))
    _darkness(engine, (5, 6))
    left = {zone.zone_id for zone in zones.typed_zones(engine)}
    assert len(left) == 2 and oldest.zone_id not in left  # only the limit ends one, and it is the one held longest
    assert _reasons(engine).count("REPLACED") == 1
    assert len(concentration.copies(me, me.concentration.source_definition_id)) == 2


def test_below_cl5_a_second_darkness_still_replaces_the_first(capped_capacity):
    engine, me = _engine(4)
    _darkness(engine, (10, 6))
    [first] = zones.typed_zones(engine)
    _darkness(engine, (12, 6))
    [now] = zones.typed_zones(engine)
    assert now.zone_id != first.zone_id and "REPLACED" in _reasons(engine, "CONCENTRATION_ENDED")


def test_the_same_self_buff_twice_does_not_stack():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe, effects=(ARMOR,))
    _concentrate(engine, me, foe, effects=(ARMOR,))  # a second copy of the same +2 AC
    assert len(concentration.copies(me, source)) == 2  # both are held ...
    bonus = _modifiers(me, "armor_class")
    assert len(bonus) == 1 and bonus[0].value == 2  # ... but the AC is +2, not +4


def test_ending_one_copy_takes_only_its_own_modifiers():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe, effects=(SPEED,))  # the older copy slows the foe
    engine._add_modifier(me, source, "speed_ft", "ADD", 5, "ALWAYS", expires_on="CONCENTRATION_END")  # something only the older made
    older = _stamped(engine, source)
    engine._start_concentration(me, source)  # the newer copy, which makes nothing of its own
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert _stamped(engine, source) == older  # the newer copy's ending left the older copy's effects alone
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert not _stamped(engine, source)


def test_a_condition_of_the_same_kind_is_replaced_not_doubled():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe, effects=())
    engine._apply_condition(foe, "condition:core.test_hex", source, me.entity_id, expires_on="CONCENTRATION_END", data={"rule": {"a": 1}})
    engine._start_concentration(me, source)
    engine._apply_condition(foe, "condition:core.test_hex", source, me.entity_id, expires_on="CONCENTRATION_END", data={"rule": {"a": 1}})
    hexes = [c for c in foe.conditions.values() if c.condition_id == "condition:core.test_hex"]
    assert len(hexes) == 1  # one hex, the newer copy's
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert not [c for c in foe.conditions.values() if c.condition_id == "condition:core.test_hex"]  # it ends with the copy that owns it


def test_a_replay_of_ending_the_newest_of_two_copies_reaches_the_same_state():
    engine, me, foe = _fight()
    source = _concentrate(engine, me, foe, effects=(SPEED,))
    engine._add_modifier(foe, source, "speed_ft", "ADD", -3, "ALWAYS", expires_on="CONCENTRATION_END")  # a second modifier the older copy made
    _concentrate(engine, me, foe, effects=(ARMOR,))  # the newer copy makes its own AC bonus only
    before, mark = engine.state.model_copy(deep=True), len(engine.events)
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    events = enrich_committed_events(engine.events[mark:], post_engine=engine)
    replayed = Gate3EventReducer().apply_events(before, events, expected_start_sequence=before.event_sequence + 1)
    assert {aid: (sorted(a.modifiers), sorted(a.conditions)) for aid, a in replayed.actors.items()} == \
        {aid: (sorted(a.modifiers), sorted(a.conditions)) for aid, a in engine.state.actors.items()}
    assert len(concentration.copies(me, source)) == 1  # the older copy is still held
