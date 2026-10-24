"""Fight audit 2026-09-29, bugs 3 and 4 (typing).  Gravity Domain's "Failed Save: Its Speed becomes 10 feet" was typed as a flat
+10, so a failed save sped every enemy in the Domain up (26 times in one fight); World as Canvas's Binding Script made its
Strength save at the moment of casting, against every creature in the whole 60-foot area, and took 10 feet of Speed from those
who passed and those who failed alike.  Both are areas that act on a creature that starts its turn in them (or, for Binding
Script, enters them) -- a ``triggers`` list on the ``zone`` effect that combat/factory_compiler.py's _zone_spec hands to
combat/zones.py -- and "becomes N" is a set, which ``speed`` now has (typed_executor.block_speed, ``becomes``)."""

import copy
import json
import re
from functools import lru_cache

from combat import typed_executor, zones
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.typed_executor import CONDITION_PREFIX
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

GRAVITY, CANVAS = "tianxia.talent.gravity.gravity_domain", "tianxia.talent.ink.world_as_canvas"
PROCESSION = "tianxia.subpath.qi.calamity_banner_cultivator.feature.procession_of_ten_thousand_demons"
FAILS, PASSES = 30, 1  # the foe's Strength save (a d20 + a small modifier) against this DC never/always makes it


@lru_cache(maxsize=None)
def _compiled(talent: str, sphere: str, dc: int) -> dict:
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    return compile_character({**SHEET, "equipment": [], "ability_scores_and_statistics": stats,
                              "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": [talent]}}, actor_id=ME)


def _gravity(dc: int = FAILS, foe_at=(4, 6)):
    bundle = copy.deepcopy(_compiled(GRAVITY, "tianxia.sphere.gravity", dc))
    return bundle, _engine(bundle, foe_at=foe_at)


def _canvas(dc: int = FAILS, foe_at=(12, 6)):
    bundle = copy.deepcopy(_compiled(CANVAS, "tianxia.sphere.ink", dc))
    return bundle, _engine(bundle, foe_at=foe_at)


def _row(bundle: dict, prefix: str) -> dict:
    return next(row for row in bundle["action_catalog"] if row["display_name"].startswith(prefix))


def _cast(engine, prefix: str, near: tuple[int, int] | None = None) -> None:
    """The caster casts ``prefix`` at the square nearest ``near`` (the foe, unless said) -- an area that is placed on the
    map -- or, for one that is centred on the caster, the one way to cast it."""
    goal = near or (engine.state.actors[AN].position.x, engine.state.actors[AN].position.y)
    where = lambda c: 0 if c.destination is None else abs(c.destination.x - goal[0]) + abs(c.destination.y - goal[1])  # noqa: E731
    candidate = min((c for c in engine.legal_candidates() if c.display_name.startswith(prefix)), key=where)
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _foes_turn(engine) -> None:
    engine.end_turn()  # the caster's turn is over; the foe's begins (its start-of-turn zone triggers run)
    assert engine.state.current_actor_id == AN


def _events(engine, *kinds):
    return [event for event in engine.events if event.event_type in kinds]


def _speed_modifiers(foe):
    return [(m.value, m.expires_on) for m in foe.modifiers.values() if m.target_field == "speed_ft"]


# ---- the set form ---------------------------------------------------------------------------------------------------------


def _set_speed(engine, goal: int) -> None:
    """One ``speed`` effect with ``becomes`` run through the executor on the foe, by Gravity Domain's own action."""
    action = next(a for a in engine.action_catalog.values() if a.display_name.startswith("Gravity Domain"))
    foe = engine.state.actors[AN]
    ctx = typed_executor.Context(engine, engine.state.actors[ME], action, None, {"numbers": {}, "effects": []}, [foe], foe, {})
    typed_executor.run_effects(ctx, [{"type": "speed", "applies_to": "target", "becomes": goal, "expires_on": "START_OF_SOURCE_NEXT_TURN"}])


def test_becomes_sets_the_speed_where_a_flat_amount_adds_to_it():
    _, engine = _gravity()
    foe = engine.state.actors[AN]
    assert foe.speed_ft == 30 and engine._effective_speed(foe) == 30
    _set_speed(engine, 10)
    assert engine._effective_speed(foe) == 10  # "its Speed becomes 10 feet" -- the audit's flat +10 made it 40
    assert _speed_modifiers(foe) == [(-20, "START_OF_SOURCE_NEXT_TURN")]


def test_using_the_ability_again_replaces_its_set_and_the_speed_other_effects_give_is_counted():
    _, engine = _gravity()
    foe = engine.state.actors[AN]
    engine._add_modifier(foe, "test:swift", "speed_ft", "ADD", 5, "ALWAYS", expires_on="UNTIL_REMOVED")  # another buff: Speed 35
    _set_speed(engine, 10)
    _set_speed(engine, 10)  # the same ability on its next turn: refreshed, not stacked
    assert engine._effective_speed(foe) == 10 and len(_speed_modifiers(foe)) == 2  # the buff, and one set
    _set_speed(engine, 20)
    assert engine._effective_speed(foe) == 20


def test_a_set_made_while_a_grapple_holds_the_speed_at_zero_is_still_the_set_once_it_lets_go():
    _, engine = _gravity()
    foe = engine.state.actors[AN]
    engine._apply_condition(foe, "condition:core.grappled", "test:grab", ME, expires_on="UNTIL_REMOVED")
    assert engine._effective_speed(foe) == 0
    _set_speed(engine, 10)
    assert engine._effective_speed(foe) == 0  # still held
    for iid, condition in list(foe.conditions.items()):
        if condition.condition_id == "condition:core.grappled":
            del foe.conditions[iid]
    assert engine._effective_speed(foe) == 10  # not 40: the modifier was worked out from the Speed it would have had free


# ---- Gravity Domain -------------------------------------------------------------------------------------------------------


def test_gravity_domains_save_is_a_start_of_turn_trigger_of_its_zone_not_a_cast_time_effect():
    bundle, engine = _gravity()
    typed = _row(bundle, "Gravity Domain")["parameters"]["typed"]
    assert [e["type"] for e in typed["effects"]] == ["zone", "disadvantage", "forced_movement"]  # no top-level save, no top-level Speed
    [trigger] = [t for t in typed["zone_spec"]["triggers"] if any(e["type"] == "save" for e in t["effects"])]
    assert trigger["on"] == ["start"] and trigger["who"] == "hostile"  # "When a hostile creature starts its turn inside the Domain"
    [save] = trigger["effects"]
    assert save["ability"] == "str" and save["dc"] == "technique_save_dc"
    # "until the start of its next turn" is read from the words (typed_executor.effect_expiry), not a stamped expiry.
    assert [(e["type"], e.get("becomes"), e.get("expires_on")) for e in save["on_fail"]] == [("speed", 10, None)]
    assert [(e["type"], e.get("flat"), e.get("expires_on")) for e in save["on_success"]] == [("speed", -10, None)]
    assert all("until the start of its next turn" in e["evidence"] for e in save["on_fail"] + save["on_success"])

    foe = engine.state.actors[AN]
    _cast(engine, "Gravity Domain")
    assert not _events(engine, "SAVE_ROLLED", "MODIFIER_APPLIED")  # nothing at the moment of casting
    assert engine._effective_speed(foe) == 30 and not _speed_modifiers(foe)


def test_a_foe_that_fails_the_domains_save_has_speed_10_not_40():
    _, engine = _gravity(FAILS)
    foe = engine.state.actors[AN]
    _cast(engine, "Gravity Domain")
    _foes_turn(engine)
    [save] = _events(engine, "SAVE_ROLLED")
    assert save.payload["success"] is False
    assert engine._effective_speed(foe) == 10 and _speed_modifiers(foe) == [(-20, "START_OF_SOURCE_NEXT_TURN")]


def test_a_foe_that_passes_the_domains_save_is_slowed_by_10():
    _, engine = _gravity(PASSES)
    foe = engine.state.actors[AN]
    _cast(engine, "Gravity Domain")
    _foes_turn(engine)
    [save] = _events(engine, "SAVE_ROLLED")
    assert save.payload["success"] is True
    assert engine._effective_speed(foe) == 20 and _speed_modifiers(foe) == [(-10, "START_OF_SOURCE_NEXT_TURN")]


def test_the_domain_never_speeds_a_foe_up_and_turn_after_turn_does_not_stack():
    _, engine = _gravity(FAILS)
    foe = engine.state.actors[AN]
    _cast(engine, "Gravity Domain")
    for _ in range(3):
        _foes_turn(engine)
        assert engine._effective_speed(foe) == 10 and len(_speed_modifiers(foe)) == 1
        engine.end_turn()  # its turn ends: the caster's comes round again, then the foe's
        assert engine.state.current_actor_id == ME
        assert all(value <= 0 for value, _ in _speed_modifiers(foe))  # never faster than its own 30


# ---- World as Canvas's Binding Script -------------------------------------------------------------------------------------


def test_binding_script_is_a_20_foot_zone_that_saves_a_creature_entering_or_starting_its_turn_in_it():
    bundle, _ = _canvas()
    row = _row(bundle, "World as Canvas")
    typed = row["parameters"]["typed"]
    assert row["radius_ft"] == 60  # World as Canvas's printed outer targeting area.
    assert typed["zone_spec"]["size_ft"] == 20  # "one 20-foot-radius zone of Binding Script"
    assert [e["type"] for e in typed["effects"]] == ["zone"]  # the save and the Speed are not top-level effects any more
    [trigger] = typed["zone_spec"]["triggers"]
    assert sorted(trigger["on"]) == ["enter", "start"] and trigger["who"] == "any"  # "A creature entering ... or starting its turn there"
    [save] = trigger["effects"]
    assert save["type"] == "save" and save["ability"] == "str" and save["dc"] == "technique_save_dc"
    assert [(e["type"], e["condition"]) for e in save["on_fail"]] == [("condition", "restrained")]  # only a failure restrains it
    assert [(e["type"], e["flat"]) for e in save["on_success"]] == [("speed", -10)]  # only a success is slowed


def test_casting_binding_script_saves_nobody_and_slows_nobody():
    _, engine = _canvas(FAILS)
    foe = engine.state.actors[AN]
    _cast(engine, "World as Canvas")
    assert zones.typed_zones(engine) and not _events(engine, "SAVE_ROLLED", "MODIFIER_APPLIED")
    assert engine._effective_speed(foe) == 30 and not foe.conditions  # it was inside the area; nothing happened yet


def test_a_creature_that_fails_binding_scripts_save_at_the_start_of_its_turn_is_restrained_and_not_slowed():
    _, engine = _canvas(FAILS)
    foe = engine.state.actors[AN]
    _cast(engine, "World as Canvas")
    _foes_turn(engine)
    [save] = _events(engine, "SAVE_ROLLED")
    assert save.payload["success"] is False
    assert [c.condition_id for c in foe.conditions.values()] == [CONDITION_PREFIX + "restrained"]
    assert not _speed_modifiers(foe)  # the -10 is the success branch's; a Restrained creature's Speed is 0 anyway
    assert engine._effective_speed(foe) == 0


def test_a_creature_that_passes_binding_scripts_save_is_slowed_by_10_and_not_restrained():
    _, engine = _canvas(PASSES)
    foe = engine.state.actors[AN]
    _cast(engine, "World as Canvas")
    _foes_turn(engine)
    [save] = _events(engine, "SAVE_ROLLED")
    assert save.payload["success"] is True
    assert not foe.conditions and _speed_modifiers(foe) == [(-10, "START_OF_SOURCE_NEXT_TURN")]
    assert engine._effective_speed(foe) == 20


def test_a_creature_entering_the_zone_makes_the_save_once_and_a_creature_outside_it_makes_none():
    _, engine = _canvas(FAILS, foe_at=(19, 12))
    foe = engine.state.actors[AN]
    _cast(engine, "World as Canvas", near=(3, 3))  # the far corner of the map: 80 feet from the foe, four squares' radius
    [zone] = zones.typed_zones(engine)
    start = Position(x=foe.position.x, y=foe.position.y)
    assert start not in zone.affected_cells and not _events(engine, "SAVE_ROLLED")
    inside = min(zone.affected_cells, key=lambda cell: abs(cell.x - start.x) + abs(cell.y - start.y))
    foe.position = Position(x=inside.x, y=inside.y)
    zones.on_moved(engine, foe, start, foe.position)
    assert len(_events(engine, "SAVE_ROLLED")) == 1 and CONDITION_PREFIX + "restrained" in {c.condition_id for c in foe.conditions.values()}
    zones.on_moved(engine, foe, start, foe.position)  # once a turn
    assert len(_events(engine, "SAVE_ROLLED")) == 1


# ---- the typing itself ----------------------------------------------------------------------------------------------------


def _authority():
    return json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def _speed_effects(node):
    if isinstance(node, dict):
        if node.get("type") == "speed":
            yield node
        for value in node.values():
            yield from _speed_effects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _speed_effects(value)


def test_no_typed_speed_effect_reads_speed_becomes_as_an_add():
    """The audit's defect class: "Its Speed becomes 10 feet" typed as ``flat: 10``.  A ``speed`` effect quoting that wording
    has to use the set form (``becomes``), and the abilities the audit named are reviewed overrides."""
    mechanics = _authority()
    wrong = [key for key, record in mechanics.items() for effect in _speed_effects(record.get("effects"))
             if re.search(r"\bspeed\s+becomes\b", str(effect.get("evidence") or ""), re.I) and effect.get("becomes") is None]
    assert not wrong, wrong
    assert {mechanics[key]["typing_status"] for key in (GRAVITY, CANVAS, PROCESSION)} == {"reviewed_final"}


def test_procession_of_ten_thousand_demons_does_not_speed_its_user_up():
    """"The Banner's Fly Speed becomes 40 feet" is the Banner's, not the user's: it was typed as a +40 Speed on the user."""
    record = _authority()[PROCESSION]
    assert not list(_speed_effects(record["effects"]))
    assert any("Fly Speed becomes 40" in rider for rider in record["riders"])
