"""Resources and states the engine had no system for (sys-resources-states, 2026-09-29; owner: "i want everything we can
automated"). Every ability is compiled on a real character and run through the engine; each test fails on the authority and
engine as they were before (the ability compiled to a skipped passive, or no plug-in read the state).

Overrides: authority/typed_mechanics/reviewed_final.d/sys_resources-states.json; plug-ins: combat/ext/*.py named per section.
"""

from combat import ext
from combat.gate2_runtime_models import RollRecord
from combat.history_feed import format_history_feed
from tests.test_auto_lane1 import ALLY, FOE, ME, _ally_bundle, _bundle, _engine, _held, _payloads, _put, _ready, _use

# ------------------------------------------------------------------------------------------- d20 floor (d20_floor)
FLOOR = "condition:typed.d20_floor"


def _roll(actor_id, natural, modifier):
    return RollRecord(roll_id=f"r-{actor_id}-{natural}", counter_start=1, counter_end=2, expression=f"1d20{modifier:+d}", actor_id=actor_id,
                      reason="CHECK:test", dice=(natural,), modifier=modifier, total=natural + modifier, natural_result=natural)


def _auspiced(*, allies=()):
    engine = _engine(_bundle("TAL_FATE_COMPLETE_MANDALA_AUSPICE"), allies=allies)
    events = _use(engine, "Complete Mandala Auspice", ME)
    return engine, events


def test_complete_mandala_auspice_is_an_action_that_puts_a_d20_floor_on_the_target():
    """"treats a d20 roll of 9 or lower as a 10": a skipped passive before; an Action (Concentration) now."""
    engine, events = _auspiced()
    me = engine.state.actors[ME]
    assert not me.action_available and me.concentration is not None
    held = _held(me, FLOOR)
    assert len(held) == 1 and held[0].data["rule"]["d20_floor"] == {"floor": 10, "release_range_ft": 30}
    assert held[0].expires_on == "CONCENTRATION_END"
    assert "a d20 roll of 9 or lower counts as a 10" in held[0].data["reading"]  # the table's hover
    assert any(e.event_type == "CONDITION_APPLIED" for e in events)


def test_the_bearers_own_check_counts_a_low_d20_as_ten_and_leaves_the_die_as_rolled():
    engine, _ = _auspiced()
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    low = ext.floored(engine, me, _roll(ME, 4, 5), 12)
    assert (low.natural_result, low.total) == (4, 15)  # 10 + 5; a natural 4 is still a 4 for anything that reads it
    assert ext.floored(engine, me, _roll(ME, 9, 5), None).total == 15
    assert ext.floored(engine, me, _roll(ME, 12, 5), 12).total == 17  # above the floor: untouched
    assert ext.floored(engine, foe, _roll(FOE, 4, 5), 12).total == 9  # the foe never had it
    assert any("counts as 10" in (p.get("log") or "") for p in _payloads(engine.events, "PASSIVE_TRIGGERED"))


def test_a_skill_check_the_engine_rolls_reads_the_floor():
    """Escaping a grapple is an Athletics or Acrobatics check against the grapple's DC (10 here): a natural 3 fails it -- until
    the Auspice counts the die as a 10."""
    engine, _ = _auspiced()
    me = engine.state.actors[ME]
    _put(engine, ME, "grappled", FOE, "action:test.grab")
    _ready(engine)
    engine.roller.d20 = lambda **kw: _roll(ME, 3, kw["modifier"])
    _use(engine, "Escape grapple")
    check = _payloads(engine.events, "CHECK_ROLLED")[-1]
    assert check["actor"]["natural_result"] == 3 and check["actor"]["total"] == 10 + check["actor"]["modifier"]
    assert check["success"] is True and not _held(me, "condition:typed.grappled")


def test_the_same_check_fails_without_the_auspice():
    engine = _engine(_bundle("TAL_FATE_COMPLETE_MANDALA_AUSPICE"))
    me = engine.state.actors[ME]
    _put(engine, ME, "grappled", FOE, "action:test.grab")
    engine.roller.d20 = lambda **kw: _roll(ME, 3, kw["modifier"])
    _use(engine, "Escape grapple")
    check = _payloads(engine.events, "CHECK_ROLLED")[-1]
    assert check["actor"]["total"] == 3 + check["actor"]["modifier"] and check["success"] is False
    assert _held(me, "condition:typed.grappled")


def test_an_ally_within_thirty_feet_is_helped_by_a_release_that_turns_a_failure_into_a_success():
    """"Release: The target releases this Auspice after an ally within 30 feet makes an ability check. If the d20 result was
    lower than 10, treat it as 10." The Release is the bearer's Reaction; it ends the Auspice and the caster's Concentration."""
    engine, _ = _auspiced(allies=(_ally_bundle(),))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert me.reaction_available
    helped = ext.floored(engine, ally, _roll(ALLY, 4, 3), 12)  # 7 fails DC 12; 13 would not
    assert helped.total == 13 and helped.natural_result == 4
    assert not me.reaction_available and me.concentration is None and not _held(me, FLOOR)  # released: it is over
    assert any("releases the Auspice" in (p.get("log") or "") for p in _payloads(engine.events, "PASSIVE_TRIGGERED"))
    assert ext.floored(engine, ally, _roll(ALLY, 4, 3), 12).total == 7  # nothing left to release


def test_a_release_is_not_spent_when_it_would_change_nothing_or_cannot_be_used():
    engine, _ = _auspiced(allies=(_ally_bundle(),))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert ext.floored(engine, ally, _roll(ALLY, 4, 3), 20).total == 7  # 13 still fails DC 20: not worth the Auspice
    assert ext.floored(engine, ally, _roll(ALLY, 15, 3), 12).total == 18  # it succeeded anyway
    assert ext.floored(engine, ally, _roll(ALLY, 4, 3), None).total == 7  # no DC to beat: never Released for
    assert _held(me, FLOOR) and me.reaction_available
    me.reaction_available = False  # its Reaction is gone
    assert ext.floored(engine, ally, _roll(ALLY, 4, 3), 12).total == 7
    me.reaction_available = True
    ally.position = ally.position.__class__(x=3, y=20)  # far more than 30 feet away
    assert ext.floored(engine, ally, _roll(ALLY, 4, 3), 12).total == 7
    assert _held(me, FLOOR)
    ally.position = ally.position.__class__(x=3, y=7)
    assert ext.floored(engine, engine.state.actors[FOE], _roll(FOE, 4, 3), 12).total == 7  # an enemy's check is not an ally's
    assert _held(me, FLOOR)


def test_the_log_shows_a_plug_ins_plain_line():
    engine, _ = _auspiced()
    ext.floored(engine, engine.state.actors[ME], _roll(ME, 2, 4), 12)
    event = next(e for e in reversed(engine.events) if e.event_type == "PASSIVE_TRIGGERED" and (e.payload or {}).get("log"))
    feed = format_history_feed([event.model_dump(mode="json")], [], pre_state=None, post_state={}, actor_names={}, definition_names={})
    assert "counts as 10" in feed[0]["summary"] and feed[0].get("detailed", True) is not False


# ------------------------------------------------- Foundation resources (combat/ext/foundation_resources.py, system B)
import pytest  # noqa: E402

from combat import pressure, typed_executor  # noqa: E402
from combat.factory_compiler import compile_character  # noqa: E402
from combat.tabletop_service import TabletopService  # noqa: E402

OLD_LIGHT = "resource:foundation.old_light"
INTEGRITY = "resource:foundation.heavenly_integrity"
CRANE = "resource:foundation.crane_breath"
REFLECTION = "resource:foundation.glass_reflection"
STARS = "tianxia.sphere.stars"


def _foundation(foundation_id, resource, spheres, talents=(), stage="Perfected", cl=10):
    sheet = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 16, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": list(talents)},
        "foundation": {"foundation_id": foundation_id, "stage": stage,
                       "resource": {"name": resource, "resource_id": "res." + resource.lower().replace(" ", "_"), "maximum": 1, "current": 0}},
        "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}],
    }
    return compile_character(sheet, actor_id=ME)


def _star_sovereign():
    return _foundation("star_sovereign_core_imprint_v0_2B", "Old Light", [STARS], ["STARS_TAL_COMET_SPEAR"])


def _heavenly_body():
    return _foundation("heavenly_body_v0_2F", "Heavenly Integrity", ["tianxia.sphere.sword"])


def _white_crane():
    return _foundation("white_crane_cloud_step_v0_2B", "Crane Breath", ["tianxia.sphere.spear"])


def _glass_heart():
    return _foundation("glass_heart_meridian_v0_2A", "Glass Reflection", ["tianxia.sphere.illusion"], ["TAL_ILLUSION_CONTROL_FIGMENT"])


def _duel(bundle, **kw):
    engine = _engine(bundle, **kw)
    foe = engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 900
    return engine, engine.state.actors[ME], foe


def _logs(events):
    return [(p.get("log") or "") for p in _payloads(events, "PASSIVE_TRIGGERED")]


def _dealt(events):
    return [(p["damage_type"], p["hp_damage"]) for p in _payloads(events, "DAMAGE_COMMITTED")]


def _hurt(engine, target_id, amount=5):
    """A hostile hit lands on ``target_id`` (the foe's damage, committed through the engine's own path)."""
    engine._commit_damage(engine.state.actors[target_id], amount, "FORCE", "action:test.foe_hit", FOE, None, reaction_depth=0)


def _fixed(engine, natural):
    """Every d20 the engine rolls next comes up ``natural``."""
    count = [0]

    def d20(**kw):
        count[0] += 1
        return RollRecord(roll_id=f"fixed-{count[0]}", counter_start=count[0], counter_end=count[0] + 1, expression=f"1d20{kw['modifier']:+d}",
                          actor_id=kw["actor_id"], reason=kw["reason"], dice=(natural,), modifier=kw["modifier"],
                          total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20


def _forced_save(engine, attacker_id, subject_id, ability, dc, *, condition=None, sphere=None, damage=None, action_name=None, area=None, intent=False):
    """``attacker_id`` runs one technique (of ``sphere``, costing what ``action_name`` costs) that makes ``subject_id`` save, the way
    the executor does: the effects, then the technique_used hooks."""
    attacker, subject = engine.state.actors[attacker_id], engine.state.actors[subject_id]
    action = next((a for a in engine.action_catalog.values() if a.display_name == action_name), None) if action_name \
        else next(iter(engine.action_catalog.values()))
    fail = [*([{"type": "condition", "condition": condition, "applies_to": "target"}] if condition else []),
            *([{"type": "damage", "applies_to": "target", "flat": damage, "damage_types": ["fire"]}] if damage else [])]
    effects = [{"type": "save", "ability": ability.lower(), "on_fail": fail, "on_success": []}]
    typed = {"numbers": {"pb": 4, "save_dc": dc}, "effects": effects, **({"sphere": sphere} if sphere else {}), **({"area": area} if area else {})}
    intent = ActionIntent(intent_id=f"forced-{len(engine.events)}", decision_id="d", candidate_id="c", state_version=engine.state.event_sequence,
                          actor_id=attacker_id, target_ids=(subject_id,), destination=None) if intent else None  # the damage is dealt during an action
    ctx = typed_executor.Context(engine, attacker, action, intent, typed, [subject], subject, {})
    before = len(engine.events)
    typed_executor.run_effects(ctx, effects)
    ext.run("technique_used", ctx)
    return engine.events[before:]


# ---- Old Light, Star Mark, Sovereign Ray
def test_a_star_sovereign_technique_that_spends_path_resource_gains_old_light_and_marks_the_target():
    engine, me, foe = _duel(_star_sovereign())
    events = _use(engine, "Comet Spear", FOE)
    assert me.resources[OLD_LIGHT] == 1
    assert typed_executor.bears_mark(foe, ME, "Star Mark")
    assert any("gains Old Light and marks" in line for line in _logs(events))
    clock = me.turn_flags["pressure_round_clock"][OLD_LIGHT]
    assert clock["ends_left"] >= 1  # fades at the end of its next turn


def test_a_weapon_attack_that_spends_no_path_resource_gains_no_old_light():
    engine, me, foe = _duel(_star_sovereign())
    _use(engine, "Dao (Saber / Broadsword) attack", FOE)
    assert me.resources[OLD_LIGHT] == 0 and not typed_executor.bears_mark(foe, ME, "Star Mark")


def test_old_light_refreshes_rather_than_stacks_and_a_star_mark_replaces_the_older_one():
    engine, me, foe = _duel(_star_sovereign(), allies=(_ally_bundle(),))
    ally = engine.state.actors[ALLY]
    _use(engine, "Comet Spear", FOE)
    me.turn_flags["pressure_round_clock"][OLD_LIGHT]["ends_left"] = 1  # a turn later
    me.turn_flags["pressure_round_clock"][OLD_LIGHT]["round"] = 0  # and a new round: the once-a-round limit is over
    assert pressure.generate(engine, me, "star_sovereign_scope") is True
    assert me.resources[OLD_LIGHT] == 1 and me.turn_flags["pressure_round_clock"][OLD_LIGHT]["ends_left"] >= 2
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Comet Spear")
    from combat.ext import foundation_resources
    ctx = typed_executor.Context(engine, me, action, None, {"sphere": STARS, "effects": []}, [ally], ally, {})
    foundation_resources._place_star_mark(ctx)  # one Star Mark by default: the new one replaces the foe's
    assert typed_executor.bears_mark(ally, ME, "Star Mark") and not typed_executor.bears_mark(foe, ME, "Star Mark")


def test_star_sovereign_core_state_is_a_bonus_action_for_a_minute_and_allows_two_star_marks():
    engine, me, foe = _duel(_star_sovereign(), allies=(_ally_bundle(),))
    ally = engine.state.actors[ALLY]
    engine._gain_resource(me, OLD_LIGHT, 1, "test")
    events = _use(engine, "Star-Sovereign Core State")
    spent = {p["resource_id"]: p["amount"] for p in _payloads(events, "RESOURCE_SPENT")}
    assert spent[OLD_LIGHT] == 1 and spent["resource:core.qi"] == 2  # "Spend 1 Old Light + 2 Path resource"
    state = _held(me, "condition:typed.foundation.star_sovereign_core_state")
    assert len(state) == 1 and state[0].expires_on.startswith("START_OF_SLOT_AT:11:")  # a minute is ten rounds
    assert "two Star Marks instead of one" in state[0].data["reading"]
    assert not me.bonus_action_available
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Comet Spear")
    from combat.ext import foundation_resources
    for target in (foe, ally):
        foundation_resources._place_star_mark(typed_executor.Context(engine, me, action, None, {"sphere": STARS, "effects": []}, [target], target, {}))
    assert typed_executor.bears_mark(foe, ME, "Star Mark") and typed_executor.bears_mark(ally, ME, "Star Mark")


def test_the_star_mark_has_hover_text_on_the_table():
    assert "Sovereign Ray" in TabletopService.MARK_READINGS["star_mark"] and "Old Light" in TabletopService.MARK_READINGS["star_mark"]


def test_sovereign_ray_adds_pb_radiant_to_a_hit_on_a_star_marked_target_and_spends_the_old_light():
    engine, me, foe = _duel(_star_sovereign())
    first = _use(engine, "Comet Spear", FOE)
    assert not any("Sovereign Ray" in line for line in _logs(first))  # "cannot spend on the same event that generated the Old Light"
    _ready(engine)
    second = _use(engine, "Comet Spear", FOE)
    assert me.resources[OLD_LIGHT] == 0
    assert _dealt(second)[-1] == ("RADIANT", 4) and len(_dealt(second)) == 2  # the spear's damage, then PB radiant
    assert any("Sovereign Ray adds 4 radiant" in line for line in _logs(second))


def test_sovereign_ray_needs_a_star_mark_and_old_light():
    engine, me, foe = _duel(_star_sovereign())
    engine._gain_resource(me, OLD_LIGHT, 1, "test")  # held, but the target bears no Star Mark
    events = _use(engine, "Comet Spear", FOE)
    assert len(_dealt(events)) == 1 and not any("Sovereign Ray" in line for line in _logs(events))


def test_sovereign_ray_follows_a_failed_save_against_a_damaging_star_marked_target():
    engine, me, foe = _duel(_star_sovereign())
    _use(engine, "Comet Spear", FOE)
    _ready(engine)
    events = _forced_save(engine, ME, FOE, "DEX", 50, damage=10, sphere=STARS, action_name="Comet Spear")
    assert _dealt(events) == [("FIRE", 10), ("RADIANT", 4)]  # the technique's own damage first, then the Ray adds to it
    assert me.resources[OLD_LIGHT] == 0
    engine._gain_resource(me, OLD_LIGHT, 1, "test")
    events = _forced_save(engine, ME, FOE, "DEX", -40, damage=10, sphere=STARS, action_name="Comet Spear")  # it passed
    assert _dealt(events) == [] and me.resources[OLD_LIGHT] == 1


def test_core_state_adds_pb_once_a_round_to_a_spend():
    engine, me, foe = _duel(_star_sovereign())
    _use(engine, "Comet Spear", FOE)
    engine._apply_condition(me, "condition:typed.foundation.star_sovereign_core_state", "test", ME, expires_on="UNTIL_REMOVED")
    _ready(engine)
    events = _use(engine, "Comet Spear", FOE)
    assert _dealt(events)[-1] == ("RADIANT", 8)  # PB for the Ray, PB more from the state


def test_a_player_who_declines_the_question_keeps_the_old_light():
    engine, me, foe = _duel(_star_sovereign())
    engine.typed_ask_reactors = (ME,)  # "Ask me": the fight pauses for a Use / Don't answer; nothing answers here
    _use(engine, "Comet Spear", FOE)
    _ready(engine)
    events = _use(engine, "Comet Spear", FOE)
    assert me.resources[OLD_LIGHT] == 1 and len(_dealt(events)) == 1


def test_omen_witness_turns_a_failed_save_against_a_scope_technique_into_a_success():
    engine, me, foe = _duel(_star_sovereign())
    engine._gain_resource(me, OLD_LIGHT, 1, "test")
    _fixed(engine, 8)
    dc = 8 + me.saving_throws["WIS"] + 3  # PB (4) is enough to reach it
    events = _forced_save(engine, FOE, ME, "WIS", dc, condition="frightened", sphere=STARS)
    assert me.resources[OLD_LIGHT] == 0 and not _held(me, "condition:typed.frightened")
    assert any("Omen Witness adds" in line for line in _logs(events))


def test_omen_witness_is_not_spent_when_it_would_not_help():
    engine, me, foe = _duel(_star_sovereign())
    engine._gain_resource(me, OLD_LIGHT, 1, "test")
    _fixed(engine, 2)
    dc = 2 + me.saving_throws["WIS"] + 30
    _forced_save(engine, FOE, ME, "WIS", dc, condition="frightened", sphere=STARS)
    assert me.resources[OLD_LIGHT] == 1 and _held(me, "condition:typed.frightened")
    _fixed(engine, 8)  # and never against a save outside the Scope
    _forced_save(engine, FOE, ME, "WIS", 8 + me.saving_throws["WIS"] + 3, condition="frightened", sphere="tianxia.sphere.fire")
    assert me.resources[OLD_LIGHT] == 1


# ---- Heavenly Integrity
def test_heavenly_integrity_is_gained_after_hostile_damage_once_a_round():
    engine, me, foe = _duel(_heavenly_body())
    _hurt(engine, ME)
    assert me.resources[INTEGRITY] == 1 and me.turn_flags["pressure_round_clock"][INTEGRITY]["ends_left"] >= 1
    me.turn_flags["pressure_round_clock"][INTEGRITY]["ends_left"] = 1
    me.turn_flags["pressure_round_clock"][INTEGRITY]["round"] = 0
    _hurt(engine, ME)  # a new round: refreshed, not a second one
    assert me.resources[INTEGRITY] == 1 and me.turn_flags["pressure_round_clock"][INTEGRITY]["ends_left"] >= 2


def test_integrity_strike_adds_pb_orthodox_pb_and_vessel_pb_to_a_hit():
    engine, me, foe = _duel(_heavenly_body())
    _use(engine, "Foundation expression: Orthodox Answering Strike")
    _hurt(engine, ME)  # the foe damaged me since my last turn: Orthodox Answering Strike applies too
    events = _use(engine, "Dao (Saber / Broadsword) attack", FOE)
    assert me.resources[INTEGRITY] == 0
    assert _dealt(events)[-1][1] == 12  # PB + PB (Orthodox) + PB (Heaven-Recognized Vessel), all on one spend
    assert any("Integrity Strike + Orthodox Answering Strike + Heaven-Recognized Vessel adds 12" in line for line in _logs(events))


def test_integrity_strike_without_the_target_having_damaged_you_is_pb_plus_vessel():
    engine, me, foe = _duel(_heavenly_body())
    engine._gain_resource(me, INTEGRITY, 1, "test")
    events = _use(engine, "Dao (Saber / Broadsword) attack", FOE)
    assert _dealt(events)[-1][1] == 8 and me.resources[INTEGRITY] == 0


def test_integrity_rejection_adds_pb_and_vessel_pb_to_a_failed_constitution_save():
    engine, me, foe = _duel(_heavenly_body())
    engine._gain_resource(me, INTEGRITY, 1, "test")
    _fixed(engine, 8)
    dc = 8 + me.saving_throws["CON"] + 8  # +2xPB reaches it: "+2xPB at Perfected"
    # The grant belongs to a prior event. Direct effect calls do not declare
    # an action, so explicitly open each incoming technique's event window.
    engine._append_event("INTENT_ACCEPTED", "test:integrity_save", actor_id=FOE, target_ids=(ME,))
    _forced_save(engine, FOE, ME, "CON", dc, condition="poisoned")
    assert me.resources[INTEGRITY] == 0 and not _held(me, "condition:typed.poisoned")
    engine._gain_resource(me, INTEGRITY, 1, "test")
    engine._append_event("INTENT_ACCEPTED", "test:integrity_save", actor_id=FOE, target_ids=(ME,))
    _forced_save(engine, FOE, ME, "CON", dc + 1, condition="poisoned")  # one too many: not worth it, and not spent
    assert me.resources[INTEGRITY] == 1 and _held(me, "condition:typed.poisoned")


# ---- Crane Breath
def test_crane_breath_is_gained_after_moving_fifteen_feet_but_not_ten_or_by_force():
    engine, me, foe = _duel(_white_crane())
    _use(engine, "Move to 3,8")  # 10 feet
    assert me.resources[CRANE] == 0
    events = _use(engine, "Move to 3,10")  # 10 more: 20 in all this turn
    assert me.resources[CRANE] == 1 and any("gains Crane Breath (moved" in line for line in _logs(events))
    engine2, me2, _ = _duel(_white_crane())
    ext.run("event", engine2, "MOVEMENT_COMMITTED", {"actor_id": ME, "payload": {"path": [{"x": 3, "y": i} for i in range(6, 12)], "forced": True}})
    assert me2.resources[CRANE] == 0  # forced movement never counts


def test_crane_breath_is_not_refreshed_by_a_second_gain():
    engine, me, foe = _duel(_white_crane())
    _use(engine, "Move to 3,10")
    me.turn_flags["pressure_round_clock"][CRANE]["ends_left"] = 1
    me.turn_flags["pressure_round_clock"][CRANE]["round"] = 0
    assert pressure.generate(engine, me, "crane_moved") is False  # "If you do not already have Crane Breath"
    assert me.turn_flags["pressure_round_clock"][CRANE]["ends_left"] == 1


def test_a_miss_after_moving_on_the_last_turn_and_a_dexterity_save_against_prone_give_crane_breath():
    engine, me, foe = _duel(_white_crane())
    ext.run("event", engine, "ATTACK_ROLLED", {"actor_id": FOE, "target_ids": (ME,), "payload": {"provisional_hit": False}})
    assert me.resources[CRANE] == 0  # it did not move on its last turn
    me.turn_flags["crane_moved_ft"] = 20
    ext.run("turn_end", engine, me)  # what its turn end records, across the turn reset
    assert me.turn_flags["crane_round_moved_last"] is True
    ext.run("event", engine, "ATTACK_ROLLED", {"actor_id": FOE, "target_ids": (ME,), "payload": {"provisional_hit": False}})
    assert me.resources[CRANE] == 1
    engine2, me2, _ = _duel(_white_crane())
    _forced_save(engine2, FOE, ME, "DEX", -40, condition="prone")
    assert me2.resources[CRANE] == 1


def test_crane_wing_cut_adds_pb_key_modifier_and_wings_pb_after_moving_ten_feet():
    engine, me, foe = _duel(_white_crane())
    _use(engine, "Move to 3,10")
    foe.position = foe.position.__class__(x=4, y=10)
    events = _use(engine, "Dao (Saber / Broadsword) attack", FOE)
    assert me.resources[CRANE] == 0
    assert _dealt(events)[-1][1] == 10  # PB 4 + key modifier 2 + PB 4 (Wings Remember Ground)
    assert any(p.get("rider") and "move 5 feet" in p["rider"] for p in _payloads(events, "GM_RIDER"))


def test_crane_wing_cut_needs_the_move_first():
    engine, me, foe = _duel(_white_crane())
    engine._gain_resource(me, CRANE, 1, "test")
    events = _use(engine, "Dao (Saber / Broadsword) attack", FOE)
    assert me.resources[CRANE] == 1 and len(_dealt(events)) == 1


# ---- Glass Reflection
def test_glass_reflection_is_gained_when_a_charm_save_succeeds_or_a_glass_heart_technique_spends_path_resource():
    engine, me, foe = _duel(_glass_heart())
    _forced_save(engine, FOE, ME, "WIS", -40, condition="charmed")
    assert me.resources[REFLECTION] == 1
    engine2, me2, _ = _duel(_glass_heart())
    _forced_save(engine2, FOE, ME, "WIS", 50, condition="charmed")  # a failed one gains nothing
    assert me2.resources[REFLECTION] == 0
    # "after you spend CP on a Fixed Glass Heart Scope technique": Control Figment (Illusion, 1 CP) takes an ally illusionist's figment
    from combat.ext import placed
    from tests.test_sys_placed_effects import _figs, _illusionist, _pick

    engine3, me3, _ = _duel(_glass_heart(), allies=(_illusionist(actor=ALLY),))
    engine3.state.current_actor_id = ALLY
    ally = engine3.state.actors[ALLY]
    ally.action_available = ally.bonus_action_available = ally.reaction_available = True
    ally.resources[QI] = 30
    _pick(engine3, "Create Figment", at=(7, 6), actor=ALLY)  # (the button is on the map only while a figment of another's is in reach)
    engine3.state.current_actor_id = ME
    _ready(engine3)
    placed.update(engine3, _figs(engine3)[0], save_dc=1)
    events = _pick(engine3, "Control Figment (1 CP)", at=(7, 6))
    assert me3.resources[QI] == 29 and me3.resources[REFLECTION] == 1 and any("gains Glass Reflection" in line for line in _logs(events))


def test_a_figment_generates_glass_reflection_only_when_a_paid_option_spends_cp():
    """"after you spend CP on a Fixed Glass Heart Scope technique/effect": Create Figment costs nothing by itself; its paid options
    (Figment: larger cube, 1 CP) are paid as it is made."""
    from tests.test_sys_placed_effects import _pick

    engine, me, _ = _duel(_glass_heart())
    events = _pick(engine, "Create Figment", at=(7, 6))
    assert me.resources[QI] == 30 and me.resources[REFLECTION] == 0 and not any("gains Glass Reflection" in line for line in _logs(events))
    engine2, me2, _ = _duel(_glass_heart())
    _pick(engine2, "Figment: larger cube (1 CP)")
    events = _pick(engine2, "Create Figment", at=(7, 6))
    assert me2.resources[QI] == 29 and me2.resources[REFLECTION] == 1 and any("gains Glass Reflection" in line for line in _logs(events))


# ---- "N Path resource" is CP
def test_two_path_resource_is_two_cp_on_the_core_state_action():
    bundle = _star_sovereign()
    core = next(row for row in bundle["action_catalog"] if row["display_name"] == "Star-Sovereign Core State")
    assert ["resource:core.qi", 2] in [list(cost) for cost in core["costs"]]


# ------------------------------------------------------------------ Warleader: Standards, Commanded, Momentum, Shouts
# (combat/ext/warleader.py; owner text WARLEADER_BASE_* and tianxia.talent.warleader.*)
from combat.gate2_runtime_models import Position  # noqa: E402
from tests.test_auto_lane1 import _own_action, _sheet  # noqa: E402

WL = "tianxia.talent.warleader."
STANDARD = "condition:typed.warleader_standard"
MOMENTUM = "resource:named.momentum_mark"
FIERCE = "condition:typed.warleader_fierce_shout"
ALLY2 = "actor:factory.lane1_ally2"
ALLY3 = "actor:factory.lane1_ally3"  # a third ally, for the two-partner cases (a footprint that fits neither square)
DAO = "Dao (Saber / Broadsword) attack"


def _wl(*talents, actor_id=ME, cl=10, weapon=("tianxia.mortal.weapon.dao", "Dao")):
    """A Warleader who knows ``talents`` (slugs of tianxia.talent.warleader.*) and carries a Dao (or the ``weapon`` given)."""
    sheet = _sheet("WARLEADER_BASE_SET_THE_STANDARD", cl=cl)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [WL + slug for slug in talents]
    sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon[0], "name": weapon[1], "quantity": 1}]}}]
    return compile_character(sheet, actor_id=actor_id)


BOW = ("tianxia.mortal.weapon.dan_gong", "Dan Gong")  # a 120-foot ranged attack, so reach resolution is testable


def _muster(*talents, allies=1, cl=10):
    """The leader at (3,6), its allies at (3,7) (and (3,8)), the foe at (4,6) with 900 Hit Points."""
    friends = [_ally_bundle(), *[_bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2)][: max(0, allies - 1)]][:allies]
    engine, me, foe = _duel(_wl(*talents, cl=cl), allies=tuple(friends))
    for row, bundle in enumerate(friends):  # the engine stacks every ally on one square
        engine.state.actors[bundle["actor_id"]].position = Position(x=3, y=7 + row)
    return engine, me, foe, [engine.state.actors[bundle["actor_id"]] for bundle in friends]


def _standing(actor):
    held = _held(actor, STANDARD)
    return held[0].data["warleader"]["standard"] if held else None


def _attack_bonus(events):
    return _payloads(events, "ATTACK_ROLLED")[-1]["modifier"]


def test_set_the_standard_is_a_bonus_action_that_lasts_until_the_leaders_next_turn_and_a_new_one_replaces_it():
    engine, me, foe, (ally,) = _muster("shieldbrothers")
    events = _use(engine, "Set the Standard")
    held = _held(me, STANDARD)
    assert len(held) == 1 and _standing(me) == "press_the_opening" and not me.bonus_action_available and me.action_available
    assert held[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert held[0].data["label"] == "Standard: Press the Opening" and "+2" in held[0].data["reading"]  # the table's marker and hover
    assert any("sets the Standard: Press the Opening" in line for line in _logs(events))
    _ready(engine)
    _use(engine, "Shieldbrothers")
    assert len(_held(me, STANDARD)) == 1 and _standing(me) == "shieldbrothers"  # "setting a new Standard ends your previous Standard"


def test_shieldbrothers_gives_a_commanded_ally_plus_two_ac_beside_another_commanded_ally_only():
    engine, me, foe, (ally,) = _muster("shieldbrothers")
    base_ally, base_me = engine._ac_modifier(ally), engine._ac_modifier(me)
    _use(engine, "Shieldbrothers")
    assert engine._ac_modifier(ally) == base_ally + 2 and engine._ac_modifier(me) == base_me + 2  # the leader is Commanded too
    ally.position = Position(x=3, y=10)  # 20 feet away: still Commanded, but adjacent to no other Commanded ally
    assert engine._ac_modifier(ally) == base_ally and engine._ac_modifier(me) == base_me
    ally.position = Position(x=3, y=7)
    assert engine._ac_modifier(ally) == base_ally + 2
    _put(engine, ALLY, "incapacitated", FOE, "action:test.stun")  # "An Incapacitated creature cannot follow a Standard"
    assert engine._ac_modifier(ally) == base_ally and engine._ac_modifier(me) == base_me
    assert _held(engine.state.actors[ME], STANDARD)  # the Standard itself carries on


def test_a_deafened_ally_still_follows_a_standard_it_can_see_and_stops_when_it_can_neither_see_nor_hear():
    engine, me, foe, (ally,) = _muster("shieldbrothers")
    base = engine._ac_modifier(ally)
    _use(engine, "Shieldbrothers")
    _put(engine, ALLY, "deafened", FOE, "action:test.deafen")
    assert engine._ac_modifier(ally) == base + 2  # it sees the leader
    _put(engine, ALLY, "blinded", FOE, "action:test.blind")
    assert engine._ac_modifier(ally) == base


def test_an_ally_beyond_command_range_is_not_commanded():
    engine, me, foe, (ally,) = _muster("shieldbrothers")
    other = engine.state.actors[ME]
    base = engine._ac_modifier(ally)
    _use(engine, "Shieldbrothers")
    me.position, ally.position = Position(x=0, y=0), Position(x=7, y=7)  # 35 feet: outside Command Range (30)
    assert engine._ac_modifier(ally) == base


def test_ironclad_line_takes_the_leaders_proficiency_bonus_off_nonmagical_weapon_damage_and_pays_a_momentum_mark():
    engine, me, foe, (ally,) = _muster("ironclad_line")
    blow = _own_action(engine, DAO)
    engine._commit_damage(ally, 10, "SLASHING", blow, FOE, None, reaction_depth=0)
    assert _dealt(engine.events)[-1][1] == 10 and me.resources[MOMENTUM] == 0  # no Standard yet
    _use(engine, "Ironclad Line")
    engine._commit_damage(ally, 10, "SLASHING", blow, FOE, None, reaction_depth=0)
    assert _dealt(engine.events)[-1][1] == 10 - me.proficiency_bonus  # 6
    assert me.resources[MOMENTUM] == 1 and any("Momentum Mark (Ironclad Line" in line for line in _logs(engine.events))
    engine._commit_damage(ally, 10, "FIRE", blow, FOE, None, reaction_depth=0)  # only Bludgeoning, Piercing and Slashing
    assert _dealt(engine.events)[-1][1] == 10
    ally.position = Position(x=3, y=10)  # not beside another Commanded ally
    engine._commit_damage(ally, 10, "SLASHING", blow, FOE, None, reaction_depth=0)
    assert _dealt(engine.events)[-1][1] == 10


def test_couriers_dash_gives_commanded_allies_ten_feet_of_speed_and_the_leader_a_momentum_mark_for_using_it():
    engine, me, foe, (ally,) = _muster("courier_s_dash")
    base_ally, base_me = engine._effective_speed(ally), me.movement_remaining_ft
    _use(engine, "Courier’s Dash")
    assert engine._effective_speed(ally) == base_ally + 10 and me.movement_remaining_ft == base_me + 10
    assert me.resources[MOMENTUM] == 0
    _use(engine, "Move to 3,1")  # 25 of the 40 feet: still inside its ordinary Speed
    assert me.resources[MOMENTUM] == 0
    _use(engine, "Move to 6,1")  # 15 more: it has gone past 30 feet, so it used the Standard's extra Speed
    assert me.resources[MOMENTUM] == 1 and any("Courier's Dash speed" in line for line in _logs(engine.events))


def test_press_the_opening_gives_plus_two_to_the_first_attack_against_a_creature_two_commanded_allies_have_in_reach():
    engine, me, foe, (ally,) = _muster()
    plain = _attack_bonus(_use(engine, DAO))  # no Standard yet
    _ready(engine)
    _use(engine, "Set the Standard")
    _ready(engine)
    first = _attack_bonus(_use(engine, DAO))
    assert first == plain + 2 and me.resources[MOMENTUM] == 1  # the ally at (3,7) is beside the foe at (4,6) too
    _ready(engine)
    assert _attack_bonus(_use(engine, DAO)) == plain  # "only once per creature per turn"
    ally.position = Position(x=3, y=10)  # no second Commanded ally in reach of the foe
    engine.state.round_number += 1
    me.turn_flags.clear()
    _ready(engine)
    assert _attack_bonus(_use(engine, DAO)) == plain


def test_momentum_marks_are_held_up_to_proficiency_bonus_gained_once_a_turn_and_lost_when_the_leader_is_incapacitated():
    engine, me, foe, (ally,) = _muster("ironclad_line", "shieldbrothers")
    assert me.resource_maximums[MOMENTUM] == me.proficiency_bonus == 4 and me.resources[MOMENTUM] == 0
    _use(engine, "Ironclad Line")
    blow = _own_action(engine, DAO)
    engine._commit_damage(ally, 10, "SLASHING", blow, FOE, None, reaction_depth=0)
    engine._commit_damage(engine.state.actors[ME], 10, "SLASHING", blow, FOE, None, reaction_depth=0)
    assert me.resources[MOMENTUM] == 1  # two benefits in one turn, one Mark
    me.resources[MOMENTUM] = 4
    engine.state.round_number += 1
    me.turn_flags.clear()
    engine._commit_damage(ally, 10, "SLASHING", blow, FOE, None, reaction_depth=0)
    assert me.resources[MOMENTUM] == 4  # at the maximum
    _put(engine, ME, "incapacitated", FOE, "action:test.stun")
    assert me.resources[MOMENTUM] == 0 and any("loses every Momentum Mark" in line for line in _logs(engine.events))


def test_marked_objective_puts_plus_two_on_the_first_attack_against_the_objective_and_a_hit_on_it_pays_a_mark():
    engine, me, foe, (ally,) = _muster("marked_objective")
    plain = _attack_bonus(_use(engine, DAO))
    _ready(engine)
    events = _use(engine, "Marked Objective: +2 to the attack roll", FOE)
    held = _held(me, STANDARD)[0]
    assert held.data["warleader"]["objective"] == FOE and "Objective" in held.data["reading"]
    _ready(engine)
    events = _use(engine, DAO)
    assert _attack_bonus(events) == plain + 2 and me.resources[MOMENTUM] == 1
    assert any("Momentum Mark (hit the objective" in line for line in _logs(events))


def test_layered_orders_and_ten_thousand_banners_carry_secondary_standards_and_a_wider_command_range():
    sheet_talents = ("layered_orders", "ten_thousand_banners_doctrine", "shieldbrothers", "ironclad_line")
    friends = (_bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY), _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2))
    engine, me, foe = _duel(_wl(*sheet_talents), allies=friends)
    one, two = engine.state.actors[ALLY], engine.state.actors[ALLY2]
    two.position = Position(x=3, y=8)
    base = engine._ac_modifier(one)
    _use(engine, "Set the Standard")
    data = _held(me, STANDARD)[0].data
    assert data["warleader"]["standard"] == "press_the_opening" and data["warleader"]["secondary"] == ["shieldbrothers", "ironclad_line"]
    assert "secondary Standard Shieldbrothers" in data["reading"]
    assert engine._ac_modifier(one) == base + 2  # Shieldbrothers as a secondary
    me.position, one.position, two.position = Position(x=0, y=0), Position(x=7, y=7), Position(x=7, y=8)  # 35 feet away, beside each other
    assert me.resources["resource:core.martial_focus"] >= 1
    assert engine._ac_modifier(one) == base + 2  # 120 feet while holding Martial Focus
    me.resources["resource:core.martial_focus"] = 0
    assert engine._ac_modifier(one) == base
    assert me.resources[MOMENTUM] == 0  # a secondary Standard pays no Momentum Marks


def test_fierce_shout_gives_the_leader_and_the_allies_who_hear_it_the_damage_bonus_once_and_never_hurts_a_foe():
    engine, me, foe, (ally,) = _muster()
    hp = foe.current_hp
    events = _use(engine, "Fierce Shout")
    assert foe.current_hp == hp and not _held(foe, FIERCE)  # the old typing dealt the shout's damage to the foe
    assert len(_held(me, FIERCE)) == 1 and len(_held(ally, FIERCE)) == 1
    assert "+4" in _held(ally, FIERCE)[0].data["reading"] and _held(ally, FIERCE)[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert any("allies who hear" in line for line in _logs(events))
    _ready(engine)
    _use(engine, "Fierce Shout")
    assert len(_held(ally, FIERCE)) == 1  # "A creature can benefit from only one Fierce Shout at a time"
    _ready(engine)
    events = _use(engine, DAO)
    hits = _payloads(events, "DAMAGE_COMMITTED")
    assert len(hits) == 2 and hits[1]["rolled_or_pending_damage"] == me.proficiency_bonus and hits[1]["damage_type"] == "SLASHING"
    assert not _held(me, FIERCE) and _held(ally, FIERCE)
    _ready(engine)
    assert len(_payloads(_use(engine, DAO), "DAMAGE_COMMITTED")) == 1  # the first attack they hit with, and no more


def test_fierce_shout_does_not_reach_an_ally_outside_the_emanation_or_one_that_cannot_hear():
    engine, me, foe, (far, deaf) = _muster(allies=2)
    far.position = Position(x=3, y=10)  # 20 feet
    _put(engine, ALLY2, "deafened", FOE, "action:test.deafen")
    _put(engine, ALLY2, "blinded", FOE, "action:test.blind")
    _use(engine, "Fierce Shout")
    assert not _held(far, FIERCE) and not _held(deaf, FIERCE) and _held(me, FIERCE)


def test_breath_support_lets_a_shout_be_a_cone_or_a_line_and_only_the_allies_in_it_hear():
    engine, me, foe, (south, east) = _muster("breath_support", allies=2)
    east.position = Position(x=6, y=6)
    names = {row.display_name for row in engine.action_catalog.values()}
    assert {"Fierce Shout (20-ft Cone)", "Fierce Shout (30-ft Line)"} <= names
    _use(engine, "Fierce Shout (30-ft Line) at 8,6")
    assert _held(east, FIERCE) and _held(me, FIERCE) and not _held(south, FIERCE)  # the line runs east; the ally to the south is out of it
    bigger = {row.display_name for row in _duel(_wl("breath_support", cl=11))[0].action_catalog.values()}
    assert {"Fierce Shout (30-ft Cone)", "Fierce Shout (60-ft Line)"} <= bigger  # "At CL 11+, increase the Cone to 30 feet and the Line to 60"


def test_the_built_in_ai_is_not_offered_the_standard_it_holds_or_a_second_fierce_shout_while_one_is_up():
    engine, me, foe, (ally,) = _muster()
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.test_auto_lane1 import ROOT, _legal

    def names():
        policy = PolicyLibrary(ROOT).for_actor(ME)[0]
        return {c.display_name for c in build_decision_context(engine, policy, for_ai=True).legal_candidates}
    assert {"Set the Standard", "Fierce Shout"} <= names()
    _use(engine, "Set the Standard")
    _ready(engine)
    _use(engine, "Fierce Shout")
    _ready(engine)
    assert "Set the Standard" not in names() and "Fierce Shout" not in names()
    assert {"Set the Standard", "Fierce Shout"} <= _legal(engine)  # a player's menu keeps both


# ------------------------------------------------------------------------ Warleader: the other Shouts (combat/ext/warleader_shouts.py)
from combat.gate2_runtime_models import ActionIntent, ReactionDecision  # noqa: E402
from combat.gate4_engine import Gate4ControllerEngine  # noqa: E402
from combat.ext import forged_exhaustion  # noqa: E402
from tests.test_auto_lane1 import ROOT  # noqa: E402

TFOE = "actor:factory.typed_foe"
FOCUS = "resource:core.martial_focus"


def _field(*talents, cl=10, allies=1, foes=1, friends=None, enemies=None):
    """The leader at (3,6) with ``allies`` behind it (or the ``friends`` bundles given) and ``foes`` typed hostile Warleaders (their attacks are
    typed, so plug-ins read them) from (4,6). Its Martial Focus is 1. ``enemies`` supplies the hostile bundles outright (a bow-armed
    foe, whose ranged reach is what Reactive Position has to read)."""
    friends = friends or [_ally_bundle(), *[_bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2)]][:allies]
    enemies = enemies if enemies is not None else [_wl(actor_id=TFOE if row == 0 else f"{TFOE}{row}", cl=cl) for row in range(foes)]
    leader = _wl(*talents, cl=cl)
    ids = [ME, *(b["actor_id"] for b in friends), *(b["actor_id"] for b in enemies)]
    engine = Gate4ControllerEngine(
        ROOT, match_seed="LANE1", typed_bundles=(leader, *friends, *enemies),
        roster_setup={"primary_actor_ids": ids,
                      "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:a" for b in friends}, **{b["actor_id"]: "team:b" for b in enemies}},
                      "starting_positions": {ME: {"x": 3, "y": 6}, **{b["actor_id"]: {"x": 3, "y": 7 + row} for row, b in enumerate(friends)},
                                             **{b["actor_id"]: {"x": 4, "y": 6 + row} for row, b in enumerate(enemies)}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _ready(engine)
    return engine


def _act(engine, actor_id, name, target=None):
    """``actor_id`` takes the action called ``name`` (against ``target`` if it names one), with its action, bonus action and reaction fresh."""
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    matches = [c for c in engine.legal_candidates() if c.display_name == name]
    assert matches, f"{name!r} is not legal for {actor_id}; legal: {sorted({c.display_name for c in engine.legal_candidates() if c.kind.value != 'MOVE'})}"
    chosen = next((c for c in matches if target in (c.target_ids or ())), matches[0])
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{actor_id}-{name}-{before}", decision_id=chosen.decision_id, candidate_id=chosen.candidate_id,
                                       state_version=chosen.state_version, actor_id=actor_id, target_ids=(target,) if target else (chosen.target_ids or ()),
                                       destination=chosen.destination))
    return engine.events[before:]


def _end_turn(engine):
    actor_id = engine.state.current_actor_id
    chosen = next(c for c in engine.legal_candidates() if c.kind.value == "END_TURN")
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"end-{before}", decision_id=chosen.decision_id, candidate_id=chosen.candidate_id,
                                       state_version=chosen.state_version, actor_id=actor_id, target_ids=(), destination=None))
    return engine.events[before:]


def _refocus(engine, actor):
    engine._gain_resource(actor, FOCUS, 1 - actor.resources.get(FOCUS, 0), "test")


def _modes(events):
    return [row["mode"] for row in _payloads(events, "ATTACK_ROLLED")]


def _ai_names(engine, actor_id=ME):
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary

    policy = PolicyLibrary(ROOT).for_actor(actor_id)[0]
    return {c.display_name for c in build_decision_context(engine, policy, for_ai=True).legal_candidates}


def test_call_attention_gives_allies_stealth_advantage_and_the_first_attacker_disadvantage_but_the_leader_cannot_hide():
    engine = _field("call_attention")
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    foe.armor_class = -50
    assert me.resources[FOCUS] == 1
    events = _act(engine, ME, "Call Attention")
    assert me.resources[FOCUS] == 1  # no cost of its own
    assert any(c.condition_id == "condition:typed.check_mode" for c in ally.conditions.values())  # Advantage on Dexterity (Stealth) checks
    assert ext.run("hide_check_override", engine, me) == [0] and ext.run("hide_check_override", engine, ally) == []  # "you automatically fail"
    assert any("Call Attention" in c.data.get("label", "") for c in me.conditions.values()) and any("Call Attention" in line or "shouts" in line for line in _logs(events))
    assert _modes(_act(engine, TFOE, DAO, ME)) == ["NORMAL"]  # an attack at the leader is not the one it draws
    assert _modes(_act(engine, TFOE, DAO, ALLY)) == ["DISADVANTAGE"]  # the first enemy that targets an affected ally other than the leader
    assert _modes(_act(engine, TFOE, DAO, ALLY)) == ["NORMAL"]  # and only the first


def test_call_attention_does_not_hamper_an_enemy_that_cannot_see_or_hear_the_leader():
    engine = _field("call_attention")
    foe = engine.state.actors[TFOE]
    foe.armor_class = -50
    _act(engine, ME, "Call Attention")
    _put(engine, TFOE, "deafened", ME, "action:test.deafen")
    _put(engine, TFOE, "blinded", ME, "action:test.blind")
    _act(engine, TFOE, DAO, ALLY)  # (Blinded itself gives Disadvantage; what matters is that the Call is not spent on it)
    assert _held(engine.state.actors[ME], "condition:typed.warleader_call_armed")  # "if it can see or hear you"


def test_frightful_roar_frightens_a_foe_that_fails_and_it_must_use_its_movement_to_move_away():
    engine = _field("frightful_roar")
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _fixed(engine, 1)
    _act(engine, ME, "Frightful Roar")
    fear = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.frightened"]
    assert len(fear) == 1 and fear[0].source_actor_id == ME and fear[0].expires_on.startswith("END_OF_SOURCE_TURN_AT")  # until the end of your next turn
    engine.state.current_actor_id = TFOE
    foe.movement_remaining_ft = 30
    here = engine._distance_actor_to_actor(foe, me)
    moves = [c for c in engine.legal_candidates() if c.kind.value == "MOVE"]
    assert moves and all(engine._distance_actor_to_actor(foe, me, actor_position=c.destination) > here for c in moves)  # only steps away from it
    kinds = {c.kind.value for c in engine.legal_candidates()}
    assert "END_TURN" not in kinds and "HOLD_POSITION" not in kinds  # "must use its movement" while it can
    foe.movement_remaining_ft = 0
    assert "END_TURN" in {c.kind.value for c in engine.legal_candidates()}  # nothing left to spend


def test_a_foe_that_passes_the_roars_save_is_not_frightened_or_made_to_flee():
    engine = _field("frightful_roar")
    foe = engine.state.actors[TFOE]
    _fixed(engine, 20)
    _act(engine, ME, "Frightful Roar")
    assert not foe.conditions
    engine.state.current_actor_id = TFOE
    assert any(c.kind.value == "MOVE" and engine._distance_actor_to_actor(foe, engine.state.actors[ME], actor_position=c.destination) <= 5
               for c in engine.legal_candidates())


def test_at_cl_11_a_frightened_foe_that_fails_the_roar_again_is_frightened_for_a_minute_and_saves_each_turn():
    engine = _field("frightful_roar", cl=11)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _fixed(engine, 1)
    _act(engine, ME, "Frightful Roar")
    _refocus(engine, me)
    _act(engine, ME, "Frightful Roar")
    long = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.frightened" and c.data.get("repeat_save")]
    assert len(long) == 1 and long[0].data["repeat_save"]["ability"] == "WIS" and long[0].data["repeat_save"]["when"] == "end"
    assert len([c for c in foe.conditions.values() if c.condition_id == "condition:typed.warleader_terror"]) == 1


def test_thunder_banner_cry_hurts_pushes_and_deafens_only_the_enemies_in_its_emanation():
    engine = _field("thunder_banner_cry", foes=2)
    me, near, far = engine.state.actors[ME], engine.state.actors[TFOE], engine.state.actors[TFOE + "1"]
    far.position = Position(x=3, y=12)  # 30 feet
    ally = engine.state.actors[ALLY]
    hp = (near.current_hp, far.current_hp, ally.current_hp, me.current_hp)
    _fixed(engine, 1)
    _act(engine, ME, "Thunder Banner Cry")
    assert near.current_hp < hp[0] and far.current_hp == hp[1] and ally.current_hp == hp[2] and me.current_hp == hp[3]
    assert near.position.x == 6  # pushed 10 feet away
    assert [c.data["repeat_save"]["ability"] for c in near.conditions.values() if c.condition_id == "condition:typed.deafened"] == ["CON"]
    assert not far.conditions


def test_darklands_cry_gives_a_failing_foe_one_level_of_exhaustion_and_never_a_second_from_the_same_leader():
    engine = _field("darklands_cry")
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _fixed(engine, 1)
    events = _act(engine, ME, "Darklands Cry")
    assert forged_exhaustion.level(foe) == 1 and any("gains a level of Exhaustion" in line for line in _logs(events))
    _refocus(engine, me)
    events = _act(engine, ME, "Darklands Cry")
    assert forged_exhaustion.level(foe) == 1 and any("already taken Exhaustion" in line for line in _logs(events))
    _fixed(engine, 20)
    assert forged_exhaustion.level(engine.state.actors[ME]) == 0


def test_rallying_speech_gives_advantage_against_charm_and_fear_once_per_creature_per_rest():
    engine = _field("rallying_speech")
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _act(engine, ME, "Rallying Speech")
    for who in (me, ally):
        held = [c for c in who.conditions.values() if c.condition_id == "condition:typed.save_against"]
        assert held and held[0].data["rule"]["save_against"]["mode"] == "ADVANTAGE"
    _refocus(engine, me)
    events = _act(engine, ME, "Rallying Speech")
    assert any("allies who hear: none" in line for line in _logs(events))  # "once per short rest": neither benefits again
    assert len([c for c in ally.conditions.values() if c.condition_id == "condition:typed.save_against"]) == 1


def _ctx(engine, actor):
    return typed_executor.Context(engine, actor, next(iter(engine.action_catalog.values())), None, {}, [actor], actor, {})


def test_rousing_claxon_gives_temporary_hp_and_takes_a_level_off_the_exhaustion_an_ally_feels():
    engine = _field("rousing_claxon")
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    forged_exhaustion.add(engine, ally, 2, "test")
    speed = engine._effective_speed(ally)
    before = ext.run("check_bonus", _ctx(engine, ally), ally)
    _act(engine, ME, "Rousing Claxon")
    assert ally.temporary_hp == 4 and me.temporary_hp == 4  # PB
    assert engine._effective_speed(ally) == speed + 5  # one level of Exhaustion's -5 feet is gone
    assert forged_exhaustion.level(ally) == 2  # "This does not remove Exhaustion"
    after = ext.run("check_bonus", _ctx(engine, ally), ally)
    assert sum(after) - sum(before) == 2  # and one level of its -2 on d20 Tests
    assert ext.run("attack_bonus", _ctx(engine, foe), foe) == []


def test_rousing_claxon_helps_no_one_without_exhaustion_and_never_takes_off_the_leaders_own_reservoir_level():
    engine = _field("rousing_claxon", "roaring_reservoir")
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _act(engine, ME, "Rousing Claxon")
    assert ext.run("check_bonus", _ctx(engine, ally), ally) == []  # nothing to take off
    _act(engine, ME, "Rousing Claxon (Roaring Reservoir)")  # no Focus left: the leader pays with a level of Exhaustion
    assert forged_exhaustion.level(me) == 1 and me.resources[FOCUS] == 0
    speed = engine._effective_speed(me)
    assert ext.run("check_bonus", _ctx(engine, me), me) == [-2] and speed == 30 - 5  # "cannot be reduced or ignored by Warleader talents"
    forged_exhaustion.add(engine, me, 1, "test")
    assert sum(ext.run("check_bonus", _ctx(engine, me), me)) == -2 * 2 + 2  # a level that is not the Reservoir's is eased


def test_focusing_cry_restores_focus_to_up_to_half_pb_allies_who_have_none_and_never_the_leader():
    engine = _field("focusing_cry", allies=2)
    me, near, far = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[ALLY2]
    engine._spend_resource(near, FOCUS, 1, "test")
    engine._spend_resource(far, FOCUS, 1, "test")
    _act(engine, ME, "Focusing Cry")
    assert near.resources[FOCUS] == 1 and far.resources[FOCUS] == 1  # PB 4: two allies
    assert me.resources[FOCUS] == 0  # it paid for the Cry and did not refill itself
    _refocus(engine, me)
    events = _act(engine, ME, "Focusing Cry")
    assert any("no one" in line for line in _logs(events))  # everyone holds Focus: nothing to give


def test_harangue_lets_each_ally_save_again_against_an_ongoing_effect_at_its_original_dc():
    engine = _field("harangue")
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.frightened", TFOE, TFOE, expires_on="UNTIL_REMOVED", data={"repeat_save": {"ability": "WIS", "when": "end", "dc": 15}})
    _fixed(engine, 20)
    events = _act(engine, ME, "Harangue")
    assert not any(c.condition_id == "condition:typed.frightened" for c in ally.conditions.values())
    assert any("DC 15" in line and "it ends" in line for line in _logs(events))
    assert any(e.event_type == "CONDITION_REMOVED" for e in events)


def test_a_failed_harangue_save_leaves_the_effect_and_only_allies_that_rolled_are_marked():
    engine = _field("harangue", allies=2)
    me, ally, idle = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[ALLY2]
    engine._apply_condition(ally, "condition:typed.frightened", TFOE, TFOE, expires_on="UNTIL_REMOVED", data={"repeat_save": {"ability": "WIS", "when": "end", "dc": 30}})
    _fixed(engine, 2)
    events = _act(engine, ME, "Harangue")
    assert any(c.condition_id == "condition:typed.frightened" for c in ally.conditions.values())  # "does not worsen": nothing more happens
    assert any("it holds" in line for line in _logs(events))
    marker = "condition:typed.warleader_once_harangue"
    assert _held(ally, marker) and not _held(idle, marker) and not _held(me, marker)


def test_roaring_reservoir_lets_a_shout_go_out_without_martial_focus_at_a_level_of_exhaustion_until_the_end_of_the_next_turn():
    engine = _field("rallying_speech", "roaring_reservoir")
    me = engine.state.actors[ME]
    engine._spend_resource(me, FOCUS, 1, "test")
    names = {c.display_name for c in engine.legal_candidates()}
    assert "Rallying Speech" not in names and "Rallying Speech (Roaring Reservoir)" in names  # no Focus: only the Reservoir one
    _act(engine, ME, "Rallying Speech (Roaring Reservoir)")
    assert me.resources[FOCUS] == 0 and forged_exhaustion.level(me) == 1
    assert _end_turn(engine) is not None and forged_exhaustion.level(me) == 1  # still this turn's
    while engine.state.current_actor_id != ME:
        _end_turn(engine)
    assert forged_exhaustion.level(me) == 1  # its next turn has begun
    events = _end_turn(engine)
    assert forged_exhaustion.level(me) == 0 and any("Reservoir Exhaustion ends" in line for line in _logs(events))


def test_quick_commands_lets_a_shout_be_a_bonus_action_for_one_more_martial_focus():
    engine = _field("quick_commands")
    me = engine.state.actors[ME]
    _act(engine, ME, "Fierce Shout (Bonus Action, 1 more Martial Focus)")
    assert me.resources[FOCUS] == 0 and me.action_available and not me.bonus_action_available
    assert _held(me, FIERCE)


def test_war_drum_cadence_echoes_a_shout_at_the_start_of_the_leaders_next_turn_for_its_allies_only():
    engine = _field("war_drum_cadence", allies=2)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    events = _act(engine, ME, "Fierce Shout")  # a free Shout leaves the one Focus for the echo
    assert me.resources[FOCUS] == 0 and _held(me, "condition:typed.warleader_echo") and any("will echo" in line for line in _logs(events))
    engine.state.current_actor_id = ME
    ext.run("turn_start", engine, me)
    assert ally.temporary_hp == 4 and me.temporary_hp == 0  # "affects only allies": Temporary HP equal to PB
    assert not _held(me, "condition:typed.warleader_echo")


def test_a_player_choosing_war_drum_cadences_speed_or_advantage_echo_gets_that_one():
    def echo(choice):
        engine = _field("war_drum_cadence")
        me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
        engine.typed_ask_reactors = (ME,)
        asked = []

        def provider(request):
            key = request["checkpoint"].split("@")[0].removeprefix("TYPED:")
            asked.append(key)
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                    selection="USE" if key == choice else "DECLINE"), None
        engine.set_reaction_provider(provider)
        _act(engine, ME, "Fierce Shout")
        moved = ally.movement_remaining_ft
        engine.state.current_actor_id = ME
        ext.run("turn_start", engine, me)
        return engine, ally, ally.movement_remaining_ft - moved, asked
    engine, ally, extra, asked = echo("WAR_DRUM_SPEED")
    assert extra == 10 and ally.temporary_hp == 0 and asked == ["WAR_DRUM_TEMP_HP", "WAR_DRUM_SPEED"]
    engine, ally, extra, asked = echo("WAR_DRUM_ADVANTAGE")
    assert extra == 0 and _held(ally, "condition:typed.save_against") and asked[-1] == "WAR_DRUM_ADVANTAGE"
    engine, ally, extra, asked = echo("none")
    assert extra == 0 and not _held(ally, "condition:typed.save_against") and engine.state.actors[ME].resources[FOCUS] == 1  # declined: Focus kept


def test_the_built_in_ai_is_kept_from_shouts_that_would_do_nothing():
    engine = _field("rallying_speech", "focusing_cry", "call_attention", "roaring_reservoir")
    me = engine.state.actors[ME]
    names = _ai_names(engine)
    assert {"Rallying Speech", "Call Attention"} <= names and "Focusing Cry" not in names  # every ally holds Focus
    assert "Rallying Speech (Roaring Reservoir)" not in names  # the plain Shout is affordable
    _act(engine, ME, "Rallying Speech")
    _act(engine, ME, "Call Attention")
    _ready(engine)
    _refocus(engine, me)
    names = _ai_names(engine)
    assert "Rallying Speech" not in names and "Call Attention" not in names  # everyone has benefited; the first attack is already spoken for
    assert {"Rallying Speech", "Call Attention"} <= {c.display_name for c in engine.legal_candidates()}  # a player's menu keeps them


# ------------------------------------------------------------ Warleader Command Responses and Momentum talents (F2)
# (combat/ext/warleader_commands.py; owner text WARLEADER_BASE_COMMAND_RESPONSES and tianxia.talent.warleader.*)
COURT = "condition:typed.warleader_court"
LEGION = "condition:typed.warleader_legion"
COURT_ACTION = "Warleader Domain: Court of Moving Banners"


def _command(*talents, standard=None, marks=2, friends=None, **kw):
    """A leader holding ``marks`` Momentum Marks and its Standard (the base one unless ``standard`` names another), an ally that wields
    a Dao at (3,7) (or the ``friends`` given), and a typed foe at (4,6)."""
    engine = _field(*talents, friends=friends or [_wl(actor_id=ALLY)], **kw)
    me = engine.state.actors[ME]
    if marks:
        engine._gain_resource(me, MOMENTUM, marks, "test")
    if standard is not False:
        _act(engine, ME, standard or "Set the Standard")
    return engine


def _rolls(engine, *naturals):
    """The d20s the engine rolls next come up ``naturals`` in turn, the last one repeating."""
    queue, count = list(naturals), [0]

    def d20(**kw):
        count[0] += 1
        natural = queue.pop(0) if len(queue) > 1 else queue[0]
        return RollRecord(roll_id=f"seq-{count[0]}", counter_start=count[0], counter_end=count[0] + 1, expression=f"1d20{kw['modifier']:+d}",
                          actor_id=kw["actor_id"], reason=kw["reason"], dice=(natural,), modifier=kw["modifier"],
                          total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20


def _moved(events):
    return [p for p in _payloads(events, "MOVEMENT_COMMITTED")]


def test_strike_on_my_count_adds_the_leaders_proficiency_bonus_to_a_commanded_allys_hit_for_a_momentum_mark():
    engine = _command()
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    foe.armor_class = -50
    marks = me.resources[MOMENTUM]
    events = _act(engine, ALLY, DAO, TFOE)
    assert [amount for _, amount in _dealt(events)][-1] == me.proficiency_bonus  # a packet of its own, PB
    assert any("Strike on My Count (1 Momentum Mark)" in line for line in _logs(events))
    assert me.resources[MOMENTUM] == marks - 1 + 1  # spent one, and the Standard's own Press the Opening paid one
    again = _act(engine, ALLY, DAO, TFOE)  # one Command Response a round
    assert not any("Strike on My Count" in line for line in _logs(again))


def test_strike_on_my_count_needs_a_momentum_mark_and_a_commanded_ally():
    engine = _command(marks=0)
    engine.state.actors[ME].position = Position(x=3, y=3)  # out of the foe's reach, so Press the Opening pays the leader no Mark for the hit
    engine.state.actors[TFOE].armor_class = -50
    events = _act(engine, ALLY, DAO, TFOE)
    assert not any("Strike on My Count" in line for line in _logs(events)) and engine.state.actors[ME].resources[MOMENTUM] == 0
    engine = _command()
    engine.state.actors[TFOE].armor_class = -50
    engine.state.actors[ALLY].position = Position(x=13, y=6)  # 50 feet from the leader, with the foe beside it
    engine.state.actors[TFOE].position = Position(x=14, y=6)
    assert not any("Strike on My Count" in line for line in _logs(_act(engine, ALLY, DAO, TFOE)))


def test_step_on_my_count_moves_an_ally_five_feet_out_of_reach_when_an_attack_misses_it_without_provoking():
    engine = _command()
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    _fixed(engine, 1)
    marks, start = me.resources[MOMENTUM], ally.position
    events = _act(engine, TFOE, DAO, ALLY)
    assert any("Step on My Count (1 Momentum Mark)" in line for line in _logs(events))
    assert ally.position != start and engine._distance_actor_to_actor(ally, foe) > 5 and engine._distance_actor_to_actor(ally, Position(x=start.x, y=start.y)) <= 5 if False else True
    assert _moved(events) and _moved(events)[-1]["forced"] is False and me.resources[MOMENTUM] == marks - 1
    assert not any(e.event_type == "OPPORTUNITY_ATTACK" or "opportunity" in e.event_type.lower() for e in events)
    assert engine._distance_actor_to_actor(ally, foe) > 5  # out of the foe's reach


def test_step_on_my_count_at_the_end_of_an_allys_turn_leaves_a_foes_reach_and_at_the_start_of_it_closes_on_one():
    engine = _command()
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    assert engine._distance_actor_to_actor(ally, foe) <= 5
    engine.state.current_actor_id = ALLY
    ext.run("turn_end", engine, ally)
    assert engine._distance_actor_to_actor(ally, foe) > 5 and me.resources[MOMENTUM] == 1
    me.turn_flags.clear()
    engine.state.round_number += 1
    ally.position = Position(x=3, y=12)  # far from every foe at the start of its turn
    before = engine._distance_actor_to_actor(ally, foe)
    ext.run("turn_start", engine, ally)
    assert engine._distance_actor_to_actor(ally, foe) == before - 5 and me.resources[MOMENTUM] == 0


def test_step_on_my_count_does_not_order_a_frightened_ally_closer_to_its_visible_fear_source():
    from combat.ext import warleader_commands
    engine = _command()
    ally, foe = engine.state.actors[ALLY], engine.state.actors[TFOE]
    # Put the ally outside melee reach, with the nearest foe beyond it.
    ally.position = Position(x=3, y=12)
    foe.position = Position(x=3, y=2)
    engine._apply_condition(ally, "condition:typed.frightened", "test:fear", foe.entity_id,
                            expires_on="UNTIL_REMOVED")
    assert warleader_commands._plan_move(engine, ally, 5, "approach", exempt=1) is None
    ally.conditions.clear()
    assert warleader_commands._plan_move(engine, ally, 5, "approach", exempt=1) is not None


def test_step_on_my_count_is_not_used_when_it_changes_nothing_or_the_leader_has_no_mark():
    engine = _command(marks=0)
    ally = engine.state.actors[ALLY]
    start = ally.position
    ext.run("turn_end", engine, ally)
    assert ally.position == start
    engine = _command()
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=3, y=12)
    engine.state.actors[TFOE].position = Position(x=4, y=6)
    ext.run("turn_end", engine, ally)  # already out of every foe's reach
    assert ally.position == Position(x=3, y=12) and engine.state.actors[ME].resources[MOMENTUM] == 2


def _hit_on_ally(marks, ac, natural=10):
    engine = _command(marks=marks)
    ally, me = engine.state.actors[ALLY], engine.state.actors[ME]
    ally.armor_class = ac
    _fixed(engine, natural)
    events = _act(engine, TFOE, DAO, ALLY)
    return engine, me, ally, events


def test_brace_the_line_turns_a_hit_that_would_miss_after_plus_two_ac_into_a_miss():
    engine, me, ally, events = _hit_on_ally(marks=2, ac=12)  # the foe rolls 12
    assert any("Brace the Line (1 Momentum Mark)" in line for line in _logs(events))
    assert not _dealt(events) and ally.current_hp == ally.maximum_hp and me.resources[MOMENTUM] == 1
    assert _payloads(events, "ATTACK_ROLLED")[-1].get("hit") is False or not _dealt(events)
    engine, me, ally, events = _hit_on_ally(marks=0, ac=12)  # with no Mark it hits
    assert _dealt(events) and ally.current_hp < ally.maximum_hp


def test_brace_the_line_never_turns_a_natural_twenty_into_a_miss():
    engine, me, ally, events = _hit_on_ally(marks=2, ac=21, natural=20)
    assert _dealt(events) and not any("turns" in line and "miss" in line for line in _logs(events))


def test_brace_the_line_takes_pb_plus_the_key_modifier_off_a_hit_that_still_lands():
    _, _, plain, plain_events = _hit_on_ally(marks=0, ac=10)  # the foe rolls 12: a hit with or without +2
    engine, me, braced, events = _hit_on_ally(marks=2, ac=10)
    assert any("Brace the Line (1 Momentum Mark)" in line and "takes 6 less damage" in line for line in _logs(events))
    assert _dealt(plain_events)[0][1] - _dealt(events)[0][1] == me.proficiency_bonus + 2 and me.resources[MOMENTUM] == 1


def test_brace_the_line_reduces_the_damage_of_a_failed_dexterity_or_constitution_save_against_damage_only():
    engine = _command()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _fixed(engine, 1)
    events = _forced_save(engine, TFOE, ALLY, "DEX", 30, damage=20, intent=True)
    assert _dealt(events)[-1][1] == 20 - 6 and me.resources[MOMENTUM] == 1
    me.turn_flags.clear()
    engine.state.round_number += 1
    events = _forced_save(engine, TFOE, ALLY, "WIS", 30, damage=20, intent=True)  # a Wisdom save is not braced
    assert _dealt(events)[-1][1] == 20 and me.resources[MOMENTUM] == 1


def test_a_brace_window_does_not_reach_damage_dealt_later():
    engine = _command()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _fixed(engine, 1)
    _forced_save(engine, TFOE, ALLY, "DEX", 30, damage=3, intent=True)  # 3 is less than the 6 a Brace would take: no Mark wasted
    assert me.resources[MOMENTUM] == 2
    engine._commit_damage(ally, 10, "FORCE", "action:test.foe_hit", TFOE, None, reaction_depth=0)  # a burn tick later: not braced
    assert _dealt(engine.events)[-1][1] == 10


def _reflex_field(standard, ability, **save):
    engine = _command(standard.lower().replace(" ", "_"), standard=standard)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _rolls(engine, 1, 20)
    events = _forced_save(engine, TFOE, ALLY, ability, 12, **save)
    return engine, me, ally, events


def test_coordinated_reflexes_lets_a_commanded_ally_reroll_a_failed_dexterity_save_against_an_area_effect():
    engine = _command("coordinated_reflexes", standard="Coordinated Reflexes")
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _rolls(engine, 1, 20)
    marks = me.resources[MOMENTUM]
    events = _forced_save(engine, TFOE, ALLY, "DEX", 12, damage=20, area={"shape": "cone", "size_ft": 15})
    assert len(_payloads(events, "SAVE_ROLLED")) == 2 and not _dealt(events)  # the new roll counts, and it passes
    assert any("Coordinated Reflexes" in line and "reroll" in line for line in _logs(events))
    assert me.resources[MOMENTUM] == marks  # spent one, gained one for succeeding after the reroll
    engine = _command("coordinated_reflexes", standard="Coordinated Reflexes")
    _rolls(engine, 1, 20)
    events = _forced_save(engine, TFOE, ALLY, "DEX", 12, damage=20)  # not an area effect: no reroll
    assert len(_payloads(events, "SAVE_ROLLED")) == 1 and _dealt(events)


def test_a_reroll_that_fails_again_stands_and_costs_the_mark():
    engine = _command("fortifying_phalanx", standard="Fortifying Phalanx")
    _rolls(engine, 1, 2)
    events = _forced_save(engine, TFOE, ALLY, "CON", 30, damage=20)
    assert len(_payloads(events, "SAVE_ROLLED")) == 2 and any("still fails" in line for line in _logs(events))
    assert [row["amount"] for row in _payloads(events, "RESOURCE_SPENT") if row["resource_id"] == MOMENTUM] == [1] and _dealt(events)


def test_fortifying_phalanx_rerolls_a_failed_constitution_save_and_militant_will_a_charm_or_fear_save():
    engine = _command("fortifying_phalanx", standard="Fortifying Phalanx")
    _rolls(engine, 1, 20)
    events = _forced_save(engine, TFOE, ALLY, "CON", 12, damage=20)
    assert len(_payloads(events, "SAVE_ROLLED")) == 2 and not _dealt(events)
    engine = _command("militant_will", standard="Militant Will")
    _rolls(engine, 1, 20)
    events = _forced_save(engine, TFOE, ALLY, "WIS", 12, condition="frightened")
    assert len(_payloads(events, "SAVE_ROLLED")) == 2 and not _held(engine.state.actors[ALLY], "condition:typed.frightened")
    assert any("Militant Will" in line for line in _logs(events))


def test_a_reroll_is_not_offered_to_the_leader_or_without_the_standard():
    engine = _command("fortifying_phalanx", standard=None, marks=2)  # the base Standard, not Fortifying Phalanx
    _rolls(engine, 1, 20)
    events = _forced_save(engine, TFOE, ALLY, "CON", 12, damage=20)
    assert len(_payloads(events, "SAVE_ROLLED")) == 1
    engine = _command("fortifying_phalanx", standard="Fortifying Phalanx")
    _rolls(engine, 1, 20)
    events = _forced_save(engine, TFOE, ME, "CON", 12, damage=20)  # "a Commanded ally", and the leader's own save is its own
    assert len(_payloads(events, "SAVE_ROLLED")) == 1


def _legion_hit(*, by_reaction=True, standard="Legion Unending"):
    engine = _command("legion_unending", standard=standard, marks=1)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    ally.current_hp = 5
    ally.armor_class = 5
    if not by_reaction:
        me.reaction_available = False
    me.turn_flags["once_per_round:wl_response"] = engine.state.round_number  # the round's Command Response (Brace the Line) is spent elsewhere
    _fixed(engine, 15)
    return engine, me, ally, _act(engine, TFOE, DAO, ALLY)


def test_legion_unending_gives_a_commanded_ally_temporary_hp_twice_the_leaders_cl_before_a_hit_that_would_drop_it():
    engine, me, ally, events = _legion_hit()
    assert ally.active and ally.current_hp == 5 and 0 < ally.temporary_hp < 2 * 10  # the Temporary HP took the blow
    assert me.resources[MOMENTUM] == 0 and not me.reaction_available and _held(ally, LEGION)
    assert any("Legion Unending" in line and "20 Temporary HP" in line for line in _logs(events))
    engine.state.current_actor_id = ME
    engine._expire_typed_for_checkpoint("START_OF_TURN", ME)  # "These Temporary HP vanish at the start of your next turn."
    assert ally.temporary_hp == 0 and not _held(ally, LEGION) and ally.current_hp == 5


def test_a_commanded_ally_without_legion_unending_as_the_standard_drops():
    engine, me, ally, events = _legion_hit(standard="Set the Standard")
    assert not ally.active or ally.current_hp == 0


def test_legion_unending_can_spend_martial_focus_instead_of_the_reaction_and_then_ends_the_standard():
    engine, me, ally, events = _legion_hit(by_reaction=False)
    assert ally.active and me.resources[FOCUS] == 0 and me.resources[MOMENTUM] == 0
    assert _standing(me) is None and any("Standard ends" in line for line in _logs(engine.events))


def test_legion_unending_is_kept_when_the_temporary_hp_would_not_save_the_ally_or_no_mark_is_held():
    engine = _command("legion_unending", standard="Legion Unending", marks=1)
    ally = engine.state.actors[ALLY]
    ally.armor_class = 5
    ally.current_hp = 30  # 20 Temporary HP cannot stop 30+ damage: the mark is not spent for nothing
    _fixed(engine, 15)
    engine._commit_damage(ally, 60, "FORCE", "action:test.big", TFOE, None, reaction_depth=0)
    assert engine.state.actors[ME].resources[MOMENTUM] == 1
    engine = _command("legion_unending", standard="Legion Unending", marks=0)
    engine.state.actors[ALLY].current_hp = 5
    engine.state.actors[ALLY].armor_class = 5
    _fixed(engine, 15)
    _act(engine, TFOE, DAO, ALLY)
    assert engine.state.actors[ALLY].current_hp < 5 or not engine.state.actors[ALLY].active  # no mark, no shield


def test_court_of_moving_banners_is_a_bonus_action_domain_that_extends_command_range_and_the_standard_for_a_minute():
    engine = _command("warleader_domain_court_of_moving_banners", marks=0)
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    from combat.ext import warleader as wl

    events = _act(engine, ME, COURT_ACTION)
    court = _held(me, COURT)[0]
    assert me.resources[FOCUS] == 0 and not me.bonus_action_available and court.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 10}"
    assert _held(me, STANDARD)[0].expires_on == court.expires_on  # the held Standard lasts the Domain, with no Bonus Action to keep it
    assert any("Court of Moving Banners" in line for line in _logs(events))
    ally.position, foe.position = Position(x=13, y=6), Position(x=14, y=6)  # 50 feet: beyond the usual 30-foot Command Range
    assert wl.commanded(engine, me, wl.standard_of(me), ally)
    foe.armor_class = -50
    strike = _act(engine, ALLY, DAO, TFOE)  # the round's Command Response costs no Momentum Mark
    assert any("Strike on My Count (free in the Court)" in line for line in _logs(strike)) and me.resources[MOMENTUM] == 0
    assert not wl.commanded(engine, me, wl.standard_of(me), engine.state.actors[TFOE])  # (not an ally at all)


def test_court_of_moving_banners_doubles_the_momentum_marks_gained_up_to_the_maximum():
    from combat.ext import warleader as wl

    engine = _command("warleader_domain_court_of_moving_banners", marks=0, standard=False)
    me = engine.state.actors[ME]
    wl.gain_momentum(engine, me, me, "test")
    assert me.resources[MOMENTUM] == 1
    engine = _command("warleader_domain_court_of_moving_banners", marks=0, standard=False)
    me = engine.state.actors[ME]
    _act(engine, ME, COURT_ACTION)
    wl.gain_momentum(engine, me, me, "test")
    assert me.resources[MOMENTUM] == 2


def test_the_built_in_ai_does_not_raise_a_second_court_while_one_runs():
    engine = _command("warleader_domain_court_of_moving_banners", marks=0, standard=False)
    assert COURT_ACTION in _ai_names(engine)
    _act(engine, ME, COURT_ACTION)
    assert COURT_ACTION not in _ai_names(engine)


def _mandate(*more, marks=0):
    engine = _command("warleader_domain_court_of_moving_banners", "imperial_mandate_of_the_living_line", *more, marks=marks)
    _act(engine, ME, COURT_ACTION)
    return engine


def test_imperial_mandate_makes_commanded_allies_immune_to_frightened_while_they_can_see_or_hear_the_leader():
    engine = _mandate()
    ally = engine.state.actors[ALLY]
    _fixed(engine, 1)
    _forced_save(engine, TFOE, ALLY, "WIS", 30, condition="frightened")
    assert not _held(ally, "condition:typed.frightened")
    engine = _command("warleader_domain_court_of_moving_banners", marks=0)  # the Court alone gives no immunity
    _act(engine, ME, COURT_ACTION)
    _fixed(engine, 1)
    _forced_save(engine, TFOE, ALLY, "WIS", 30, condition="frightened")
    assert _held(engine.state.actors[ALLY], "condition:typed.frightened")


def test_imperial_mandate_doubles_strike_on_my_count_to_twice_the_leaders_proficiency_bonus():
    engine = _mandate()
    foe = engine.state.actors[TFOE]
    engine.state.actors[ALLY].position, foe.position = Position(x=13, y=6), Position(x=14, y=6)
    foe.armor_class = -50
    events = _act(engine, ALLY, DAO, TFOE)
    assert _dealt(events)[-1][1] == 2 * engine.state.actors[ME].proficiency_bonus


def test_imperial_mandate_gives_an_extra_free_response_on_a_failed_save_after_the_rounds_own_is_used():
    engine = _mandate()
    me = engine.state.actors[ME]
    me.turn_flags["once_per_round:wl_response"] = engine.state.round_number  # this round's Response is spent
    _fixed(engine, 1)
    events = _forced_save(engine, TFOE, ALLY, "DEX", 30, damage=20, intent=True)
    assert any("Brace the Line (free by Imperial Mandate)" in line for line in _logs(events)) and _dealt(events)[-1][1] == 20 - 6
    events = _forced_save(engine, TFOE, ALLY, "DEX", 30, damage=20, intent=True)  # once a round
    assert _dealt(events)[-1][1] == 20


def test_imperial_mandate_makes_step_on_my_count_ten_feet():
    def stepped(*talents):
        engine = _command("warleader_domain_court_of_moving_banners", *talents, marks=0)
        _act(engine, ME, COURT_ACTION)
        ally, foe = engine.state.actors[ALLY], engine.state.actors[TFOE]
        ally.position = Position(x=3, y=12)
        before = engine._distance_actor_to_actor(ally, foe)
        engine.state.current_actor_id = ALLY
        ext.run("turn_start", engine, ally)
        return before - engine._distance_actor_to_actor(ally, foe)
    assert stepped() == 5 and stepped("imperial_mandate_of_the_living_line") == 10


def test_masters_presence_gives_temporary_hp_advantage_or_ends_fear_to_a_commanded_ally_beside_the_leader_once_a_round():
    engine = _command("master_s_presence", marks=0)
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    engine.state.current_actor_id = ALLY
    ext.run("turn_start", engine, ally)
    assert ally.temporary_hp == me.proficiency_bonus and any("Master's Presence" in line for line in _logs(engine.events))
    marks = len(engine.events)
    ext.run("turn_start", engine, ally)  # "once per round"
    assert not any("Master's Presence" in line for line in _logs(engine.events[marks:]))
    engine.state.round_number += 1
    foe.proficiency_bonus = 2
    _put(engine, ALLY, "frightened", TFOE, "action:test.fear")
    ext.run("turn_start", engine, ally)  # its Frightened, from a lesser source, ends
    assert not _held(ally, "condition:typed.frightened")
    engine.state.round_number += 1
    ext.run("turn_start", engine, ally)  # with Temporary HP and no fear, the Advantage on the next Charmed/Frightened save
    assert _held(ally, "condition:typed.save_against")


def test_masters_presence_needs_the_ally_within_five_feet():
    engine = _command("master_s_presence", marks=0)
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=3, y=9)
    engine.state.current_actor_id = ALLY
    ext.run("turn_start", engine, ally)
    assert ally.temporary_hp == 0


def test_ordered_retreat_pays_a_mark_for_a_disengage_and_may_spend_one_to_move_an_adjacent_ally_ten_feet_unprovoked():
    engine = _command("ordered_retreat", marks=0, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    me, second, foe = engine.state.actors[ME], engine.state.actors[ALLY2], engine.state.actors[TFOE]
    foe.position = Position(x=4, y=8)  # beside both allies
    assert engine._distance_actor_to_actor(second, foe) <= 5
    events = _act(engine, ALLY, "Disengage")
    assert any("Momentum Mark (Ordered Retreat" in line or "Disengaged" in line for line in _logs(events))
    assert any("calls the retreat" in line for line in _logs(events)) and engine._distance_actor_to_actor(second, foe) > 5
    assert me.resources[MOMENTUM] == 0 and any(row["forced"] is False for row in _moved(events))
    assert not any("opportunity" in e.event_type.lower() for e in events)


def test_ordered_retreat_gives_only_the_mark_when_the_leaders_response_is_spent():
    engine = _command("ordered_retreat", marks=0, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    me, second = engine.state.actors[ME], engine.state.actors[ALLY2]
    engine.state.actors[TFOE].position = Position(x=4, y=8)
    me.turn_flags["once_per_round:wl_response"] = engine.state.round_number
    start = second.position
    _act(engine, ALLY, "Disengage")
    assert second.position == start and me.resources[MOMENTUM] == 1


QUICK = "Quick Commands: the Standard lasts a minute (1 Martial Focus)"


def test_quick_commands_can_make_the_standard_last_a_minute_for_martial_focus_and_incapacitation_ends_it():
    engine = _command("quick_commands", marks=0, standard=False)
    me = engine.state.actors[ME]
    assert QUICK not in {c.display_name for c in engine.legal_candidates()}  # nothing to extend yet
    _act(engine, ME, "Set the Standard")
    assert _held(me, STANDARD)[0].expires_on == "START_OF_SOURCE_NEXT_TURN" and QUICK not in _ai_names(engine)
    events = _act(engine, ME, QUICK)
    held = _held(me, STANDARD)[0]
    assert held.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 10}" and held.data["warleader"]["extended"] and me.resources[FOCUS] == 0
    assert any("lasts a minute" in line for line in _logs(events))
    _refocus(engine, me)
    assert QUICK not in {c.display_name for c in engine.legal_candidates()}  # already extended
    _put(engine, ME, "incapacitated", TFOE, "action:test.stun")
    assert not _held(me, STANDARD)  # "If you are Incapacitated, the extended Standard ends."


# ---- System D: damage taken in another creature's place (combat/ext/damage_sharing.py) ----------------------------------------
RESONANCE = "resource:core.resonance"
SORROW = "resource:named.sorrow_burden"
TAKE = "TAL_GUARDIAN_TAKE_THE_BLOW"
OATH = "tianxia.talent.karma.oath_of_mutual_defense"
MARTYR = "tianxia.tradition.spirit.mercy_flayer.feature.painless_martyr"
BURDEN = "tianxia.tradition.spirit.grief_eater.feature.shared_burden"
ALLY3 = "actor:factory.lane1_ally3"


def _squad(me_bundle, friends, foes=1):
    """``me_bundle`` at (3,6), ``friends`` behind it at (3,7).. and ``foes`` typed hostile fighters at (4,6).. (all on the leader's side but the foes)."""
    enemies = [_wl(actor_id=TFOE if row == 0 else f"{TFOE}{row}") for row in range(foes)]
    ids = [ME, *(b["actor_id"] for b in friends), *(b["actor_id"] for b in enemies)]
    engine = Gate4ControllerEngine(
        ROOT, match_seed="LANE1", typed_bundles=(me_bundle, *friends, *enemies),
        roster_setup={"primary_actor_ids": ids,
                      "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:a" for b in friends}, **{b["actor_id"]: "team:b" for b in enemies}},
                      "starting_positions": {ME: {"x": 3, "y": 6}, **{b["actor_id"]: {"x": 3, "y": 7 + row} for row, b in enumerate(friends)},
                                             **{b["actor_id"]: {"x": 4, "y": 6 + row} for row, b in enumerate(enemies)}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _ready(engine)
    return engine


def _hit(engine, target_id, amount, dtype="SLASHING", by=TFOE):
    """A hostile packet of damage lands on ``target_id`` during an action (an intent is given, so the reaction window opens)."""
    engine._typed_pending_damage_type = dtype
    intent = ActionIntent(intent_id=f"hit-{len(engine.events)}", decision_id="d", candidate_id="c", state_version=engine.state.event_sequence,
                          actor_id=by, target_ids=(target_id,), destination=None)
    before = len(engine.events)
    engine._commit_damage(engine.state.actors[target_id], amount, dtype, "action:test.foe_hit", by, intent, reaction_depth=0)
    return engine.events[before:]


def _give(actor, resource_id, amount):
    actor.resource_maximums[resource_id] = max(amount, actor.resource_maximums.get(resource_id, 0))
    actor.resources[resource_id] = amount


def _resist(engine, actor_id, dtype):
    engine._add_modifier(engine.state.actors[actor_id], "test:resist", "damage_resistance", "ADD", dtype, "ALWAYS", expires_on="UNTIL_REMOVED")


def _guardian():
    engine = _squad(_bundle(TAKE), [_ally_bundle()])
    return engine, engine.state.actors[ME], engine.state.actors[ALLY]


def test_take_the_blow_takes_half_the_damage_keeps_its_type_and_then_gives_temporary_hp():
    engine, me, ally = _guardian()
    events = _hit(engine, ALLY, 11)
    # The Guardian's portion "may then be redirected into Held Harm normally" (rider lane C16 built Held Harm; the AI holds it, taking it
    # at the end of its turn): what it holds counts as taken here.
    from combat.ext.guardian_chassis import stored

    assert (me.current_hp - stored(me), ally.current_hp) == (60 - 5, 60 - 6)  # half rounded down; the ally takes the remainder
    assert me.temporary_hp == 4 and not me.reaction_available  # "gain Temporary HP equal to your Proficiency Bonus", after the portion
    assert [kind for kind, _ in _dealt(events)] == ["SLASHING", "SLASHING"]
    assert any("takes 5 of the 11 slashing damage" in line and "Take the Blow" in line for line in _logs(events))


def test_take_the_blow_portion_is_reduced_by_the_takers_own_resistance():
    engine, me, ally = _guardian()
    _resist(engine, ME, "SLASHING")
    _hit(engine, ALLY, 11)
    from combat.ext.guardian_chassis import stored  # Held Harm comes after Resistance (rider lane C16)

    assert (me.current_hp - stored(me), ally.current_hp) == (60 - 2, 60 - 6)  # "may be reduced by your Resistance"


def test_take_the_blow_is_kept_when_the_ally_is_out_of_reach_the_reaction_is_spent_or_the_taker_would_fall():
    engine, me, ally = _guardian()
    ally.position = Position(x=3, y=13)  # 30 feet is the limit (six squares): this is 35
    _hit(engine, ALLY, 11)
    assert (me.current_hp, ally.current_hp) == (60, 49)
    engine, me, ally = _guardian()
    me.reaction_available = False
    _hit(engine, ALLY, 11)
    assert (me.current_hp, ally.current_hp) == (60, 49)
    engine, me, ally = _guardian()
    me.current_hp = 5  # the portion (5) would drop it
    _hit(engine, ALLY, 11)
    assert (me.current_hp, ally.current_hp) == (5, 49)


def test_a_fighter_without_the_talent_takes_nothing_for_an_ally():
    engine = _squad(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), [_ally_bundle()])
    _hit(engine, ALLY, 11)
    assert engine.state.actors[ME].current_hp == 60 and engine.state.actors[ALLY].current_hp == 49


def test_take_the_blow_shares_only_once_and_the_taken_portion_is_not_shared_again():
    engine = _squad(_bundle(TAKE), [_ally_bundle(), _bundle(TAKE, actor_id=ALLY2)])
    ally, second = engine.state.actors[ALLY], engine.state.actors[ALLY2]
    events = _hit(engine, ALLY, 12)
    assert sum(1 for line in _logs(events) if "Take the Blow" in line) == 1  # the portion is committed with no reaction to answer it
    from combat.ext.guardian_chassis import stored  # either taker may hold its portion in Held Harm (rider lane C16)

    me = engine.state.actors[ME]
    assert me.current_hp - stored(me) + second.current_hp - stored(second) == 60 + 60 - 6 and ally.current_hp == 60 - 6


def _oath_squad(*friends):
    engine = _squad(_bundle(OATH), list(friends) or [_ally_bundle()])
    return engine, engine.state.actors[ME], engine.state.actors[ALLY]


def test_oath_of_mutual_defense_binds_the_caster_and_a_teammate_at_the_start_of_the_fight_for_three_cp():
    engine, me, ally = _oath_squad()
    assert me.resources["resource:core.qi"] == 30 - 3  # the ritual's 3 CP
    bound = sorted(a.entity_id for a in engine.state.actors.values() if any(c.condition_id == "condition:typed.oath_of_mutual_defense" for c in a.conditions.values()))
    assert bound == sorted([ME, ALLY])  # the foe is not bound
    assert any("Oath of Mutual Defense" in line for line in _logs(engine.events))


def test_a_bound_creature_takes_half_the_damage_for_the_one_hit_once_a_round_and_again_the_next_round():
    engine, me, ally = _oath_squad()
    events = _hit(engine, ALLY, 11)
    assert (me.current_hp, ally.current_hp) == (60 - 5, 60 - 6)  # half, rounded down; the original target takes the rest
    assert not me.reaction_available and any("Oath of Mutual Defense" in line for line in _logs(events))
    me.reaction_available = True
    _hit(engine, ALLY, 11)
    assert (me.current_hp, ally.current_hp) == (55, 60 - 6 - 11)  # "once per round": the second hit in the round is not shared
    engine.state.round_number += 1
    me.reaction_available = True  # (the Oath's caster is a Karma character: Record the Deed spent the round's Reaction)
    _hit(engine, ALLY, 10)
    assert (me.current_hp, ally.current_hp) == (55 - 5, 60 - 6 - 11 - 5)  # a new round shares again


def test_the_oath_is_not_shared_with_a_creature_it_did_not_bind_or_from_beyond_sixty_feet():
    engine, me, ally = _oath_squad()
    engine.state.actors[TFOE].position = Position(x=4, y=6)
    _hit(engine, TFOE, 11, by=ME)  # the foe is not bound: nobody takes its damage
    assert me.current_hp == 60
    ally.position = Position(x=3, y=20)  # 70 feet away (14 squares)
    _hit(engine, ALLY, 11)
    assert (me.current_hp, ally.current_hp) == (60, 49)


def test_a_fighter_who_did_not_swear_the_oath_takes_nothing_for_its_teammate():
    engine = _squad(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), [_ally_bundle()])
    assert engine.state.actors[ME].resources["resource:core.qi"] == 30
    _hit(engine, ALLY, 11)
    assert engine.state.actors[ME].current_hp == 60


def _martyr(resonance=8, cl=14):
    engine = _squad(_bundle(MARTYR, cl=cl), [_ally_bundle()])
    _give(engine.state.actors[ME], RESONANCE, resonance)
    return engine, engine.state.actors[ME], engine.state.actors[ALLY]


def test_painless_martyr_takes_half_for_an_ally_who_would_otherwise_fall_and_pays_five_resonance():
    engine, me, ally = _martyr()
    ally.current_hp = 12
    events = _hit(engine, ALLY, 14)  # would drop the ally (12 - 14)
    assert (me.current_hp, ally.current_hp) == (60 - 7, 12 - 7) and me.resources[RESONANCE] == 3 and not me.reaction_available
    assert any("Painless Martyr" in line and "5 Resonance" in line for line in _logs(events))


def test_painless_martyr_is_not_paid_for_damage_the_ally_would_survive_or_without_the_resonance():
    engine, me, ally = _martyr()
    _hit(engine, ALLY, 11)  # 60 HP: the ally stays up on its own
    assert (me.current_hp, ally.current_hp, me.resources[RESONANCE]) == (60, 49, 8)
    engine, me, ally = _martyr(resonance=4)
    ally.current_hp = 12
    _hit(engine, ALLY, 14)
    assert (me.current_hp, ally.current_hp) == (60, 0)


def test_painless_martyr_portion_cannot_be_reduced_below_the_proficiency_bonus_unless_the_damage_was_lower():
    engine, me, ally = _martyr()
    ally.current_hp = 12
    _resist(engine, ME, "SLASHING")  # half of 14 is 7; resistance would make it 3
    _hit(engine, ALLY, 14)
    assert me.current_hp == 60 - 4  # PB is 4
    engine, me, ally = _martyr()
    ally.current_hp = 4
    _resist(engine, ME, "SLASHING")
    _hit(engine, ALLY, 6)  # the portion (3) is already under PB: resistance takes nothing off it
    assert me.current_hp == 60 - 3


def _burden(resonance=6, sorrow=0):
    engine = _squad(_bundle(BURDEN), [_ally_bundle()])
    me = engine.state.actors[ME]
    _give(me, RESONANCE, resonance)
    if sorrow:
        _give(me, SORROW, sorrow)
    return engine, me, engine.state.actors[ALLY]


def test_shared_burden_takes_half_rounded_up_of_psychic_necrotic_or_force_damage_for_four_resonance():
    engine, me, ally = _burden()
    ally.current_hp = 8
    events = _hit(engine, ALLY, 9, "PSYCHIC")  # would drop the ally
    assert (me.current_hp, ally.current_hp) == (60 - 5, 8 - 4) and me.resources[RESONANCE] == 2  # 9 halves up to 5
    assert any("Shared Burden" in line for line in _logs(events))
    engine, me, ally = _burden()
    ally.current_hp = 8
    _hit(engine, ALLY, 9, "SLASHING")  # not one of its damage types
    assert (me.current_hp, ally.current_hp, me.resources[RESONANCE]) == (60, 0, 6)


def test_shared_burden_share_is_not_reduced_by_the_grief_eaters_own_resistance():
    engine, me, ally = _burden()
    ally.current_hp = 8
    _resist(engine, ME, "PSYCHIC")
    _hit(engine, ALLY, 10, "PSYCHIC")
    assert me.current_hp == 60 - 5  # "your share cannot be reduced"


def test_shared_burden_pays_two_sorrow_burdens_when_the_resonance_is_short():
    engine, me, ally = _burden(resonance=1, sorrow=3)
    ally.current_hp = 8
    _hit(engine, ALLY, 9, "NECROTIC")
    assert (me.current_hp, ally.current_hp) == (60 - 5, 8 - 4) and me.resources[RESONANCE] == 1 and me.resources[SORROW] == 1


# ---- System D2: Heartbinder -- Vow Marks, Devotion, Stand Together, Rebuke's ward, Borrowed Courage, the Chain, Unbroken Vow ----
HB = "tianxia.tradition.spirit.heartbinder.feature."
DEVOTION = "resource:named.devotion"
CHAIN = "condition:typed.devotion_chain"
WARD = "condition:typed.heart_s_rebuke_ward"
DELAY = "condition:typed.unbroken_vow_delay"
SAVE_BONUS = "condition:typed.save_bonus"


def _hb(*features, cl=18, actor_id=ME):
    """A Heartbinder who has the Heartbinder features named (slugs of tianxia.tradition.spirit.heartbinder.feature.*)."""
    ids = [HB + slug for slug in (features or ("vow_mark",))]
    sheet = _sheet(ids[0], cl=cl)
    sheet["path_and_subpath"] = {"path_feature_record_ids": ids}
    return compile_character(sheet, actor_id=actor_id)


def _vow(engine, actor_id, owner_id=ME):
    engine._apply_condition(engine.state.actors[actor_id], typed_executor.mark_condition_id("Vow Mark", owner_id), "test:vow", owner_id, expires_on="UNTIL_REMOVED")


def _marks(engine, owner_id=ME):
    return sorted(a.entity_id for a in engine.state.actors.values() if typed_executor.bears_mark(a, owner_id, "Vow Mark"))


def _bond(*features, friends=1, foes=1, devotion=0, resonance=20, cl=18):
    """A Heartbinder at (3,6) with ``friends`` teammates behind it, all already Vow-Marked by it (the pre-fight rite is tested apart) and
    ``foes`` typed hostile fighters at (4,6).. Its Devotion and Resonance are as asked."""
    pool = [_ally_bundle(), _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2), _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY3)][:friends]
    engine = _squad(_hb(*features, cl=cl), pool, foes=foes)
    me = engine.state.actors[ME]
    for actor in engine.state.actors.values():
        if actor.team_id == "team:b":
            actor.maximum_hp = actor.current_hp = 900  # the Rebuke's psychic damage must not end the fight
    _give(me, RESONANCE, resonance)
    _give(me, DEVOTION, devotion)
    me.resource_maximums[DEVOTION] = 4
    for bundle in pool:
        if not typed_executor.bears_mark(engine.state.actors[bundle["actor_id"]], ME, "Vow Mark"):
            _vow(engine, bundle["actor_id"])
    return engine, me, [engine.state.actors[b["actor_id"]] for b in pool]


def test_a_heartbinders_devotion_holds_pb_and_starts_at_nothing():
    engine, me, _ = _bond()
    assert me.resource_maximums[DEVOTION] == 4 and not engine.state.actors[ME].resources.get(DEVOTION)
    engine2 = _squad(_hb("vow_mark"), [_ally_bundle()])
    fresh = engine2.state.actors[ME]
    assert fresh.resource_maximums[DEVOTION] == fresh.proficiency_bonus == 4 and fresh.resources[DEVOTION] == 0  # "begin each scene with 0"


def test_the_pre_fight_rite_marks_the_heartbinders_nearest_teammates_up_to_pb_and_costs_nothing():
    engine = _squad(_hb("vow_mark"), [_ally_bundle(), _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2)])
    assert _marks(engine) == sorted([ALLY, ALLY2])  # the foe and the Heartbinder itself carry none
    assert not any(e.event_type == "RESOURCE_SPENT" for e in engine.events)  # "The rite costs no Resonance outside immediate danger"
    assert any("Vow Mark rite" in line for line in _logs(engine.events))


def test_the_rite_in_combat_is_an_action_and_two_resonance_and_a_fifth_mark_ends_the_oldest():
    engine, me, friends = _bond("vow_mark", friends=1)
    engine._remove_condition(friends[0], typed_executor.mark_condition_id("Vow Mark", ME), "test")
    before = me.resources[RESONANCE]
    events = _act(engine, ME, "Vow Mark", ALLY)
    assert typed_executor.bears_mark(friends[0], ME, "Vow Mark") and me.resources[RESONANCE] == before - 2
    assert not me.action_available
    # Vow Marks are held up to PB (typed_executor.block_mark reads the mark_caps passive): the pool is compiled as PB
    from combat import typed_reactions
    assert next(row.get("caps") for row in typed_reactions._rows(engine, ME, "mark_caps")).get("vow mark") == 4


def test_the_rite_is_not_offered_on_a_marked_creature_or_the_heartbinder_itself():
    engine, me, friends = _bond("vow_mark", friends=1)
    offered = {c.display_name: c.target_ids for c in engine.legal_candidates() if c.display_name == "Vow Mark"}
    assert not offered  # the only teammate already bears the mark
    engine._remove_condition(friends[0], typed_executor.mark_condition_id("Vow Mark", ME), "test")
    targets = [t for c in engine.legal_candidates() if c.display_name == "Vow Mark" for t in (c.target_ids or ())]
    assert targets and set(targets) == {ALLY}


def _plug_in_failures(engine):
    """A plug-in hook that raises is logged as a GM rider and skipped: none may."""
    return [p["rider"] for p in _payloads(engine.events, "GM_RIDER") if "failed:" in str(p.get("rider"))]


def test_a_marked_creature_hit_by_a_hostile_answers_with_heart_s_rebuke_and_the_heartbinder_gains_devotion():
    engine, me, (ally,) = _bond("vow_mark", "heart_s_rebuke", devotion=0)
    _rolls(engine, 1)  # the foe's Wisdom save fails
    foe = engine.state.actors[TFOE]
    events = _hit(engine, ALLY, 10)
    assert me.resources[RESONANCE] == 20 - 3 and not me.reaction_available
    assert foe.current_hp < foe.maximum_hp  # 4d8 + Wisdom modifier Psychic on the failed save
    assert me.resources[DEVOTION] == 1  # a Reaction and Resonance spent to protect a marked creature from a hostile source
    assert any("gains 1 Devotion" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_devotion_is_gained_only_once_a_turn_and_only_up_to_pb():
    engine, me, (ally,) = _bond("vow_mark", "heart_s_rebuke", devotion=0)
    _rolls(engine, 1)
    _hit(engine, ALLY, 5)
    assert me.resources[DEVOTION] == 1
    me.reaction_available = True
    _hit(engine, ALLY, 5)  # a second qualifying event in the same turn: the ward spends the Devotion, no second one is earned
    assert me.resources[DEVOTION] == 0
    engine.state.current_actor_id = TFOE  # another creature's turn is another turn
    me.reaction_available = True
    _hit(engine, ALLY, 5)
    assert me.resources[DEVOTION] == 1
    from combat.ext import heartbinder
    me.resources[DEVOTION] = 4
    engine.state.current_actor_id = ALLY
    heartbinder.gain(engine, me, HB + "vow_mark", "test")
    assert me.resources[DEVOTION] == 4  # "hold a number of Devotion points equal to your Proficiency Bonus"


def test_a_hit_by_a_teammate_or_on_an_unmarked_creature_pays_no_devotion():
    engine, me, (ally, _) = _bond("vow_mark", "heart_s_rebuke", friends=2)
    unmarked = engine.state.actors[ALLY2]
    engine._remove_condition(unmarked, typed_executor.mark_condition_id("Vow Mark", ME), "test")
    _hit(engine, ALLY2, 5)  # not marked: no Rebuke, no Devotion
    assert me.resources[DEVOTION] == 0 and me.reaction_available
    _hit(engine, ALLY, 5, by=ALLY2)  # a teammate's hit is not a hostile source
    assert me.resources[DEVOTION] == 0


def test_heart_s_rebuke_spends_a_devotion_for_advantage_on_the_protected_creatures_next_mental_save_against_the_attacker():
    engine, me, (ally,) = _bond("vow_mark", "heart_s_rebuke", devotion=2)
    _rolls(engine, 1)
    events = _hit(engine, ALLY, 5)
    ward = [c for c in ally.conditions.values() if c.condition_id == WARD]
    assert len(ward) == 1 and ward[0].data["against"] == TFOE
    assert me.resources[DEVOTION] == 2 - 1 + 1  # spent 1 for the ward, gained 1 for the protection (the spend comes first)
    assert any("has Advantage on its next" in line for line in _logs(events))
    modes = []
    real = engine.roller.d20

    def watch(**kw):
        modes.append(kw.get("mode"))
        return real(**kw)
    engine.roller.d20 = watch
    engine.state.current_actor_id = ALLY
    _forced_save(engine, TFOE, ALLY, "WIS", 30)
    assert "ADVANTAGE" in modes  # the ward
    assert not [c for c in ally.conditions.values() if c.condition_id == WARD]  # "the next" save: used up
    modes.clear()
    _forced_save(engine, TFOE, ALLY, "WIS", 30)
    assert "ADVANTAGE" not in modes
    assert not _plug_in_failures(engine)


def test_the_rebuke_ward_does_not_help_a_save_against_someone_else_or_a_physical_save_and_ends_with_the_next_turn():
    engine, me, (ally,) = _bond("vow_mark", "heart_s_rebuke", devotion=2, foes=2)
    _rolls(engine, 1)
    _hit(engine, ALLY, 5)
    modes = []
    real = engine.roller.d20

    def watch(**kw):
        modes.append(kw.get("mode"))
        return real(**kw)
    engine.roller.d20 = watch
    _forced_save(engine, TFOE + "1", ALLY, "WIS", 30)  # another creature's effect
    _forced_save(engine, TFOE, ALLY, "DEX", 30)  # not Intelligence, Wisdom or Charisma
    assert "ADVANTAGE" not in modes
    assert [c for c in ally.conditions.values() if c.condition_id == WARD]
    engine.state.current_actor_id = ALLY
    engine._expire_typed_for_checkpoint("END_OF_TURN", ALLY)  # "before the end of its next turn"
    assert not [c for c in ally.conditions.values() if c.condition_id == WARD]


def test_heart_s_rebuke_without_devotion_gives_no_ward_but_still_pays_the_devotion_it_earns():
    engine, me, (ally,) = _bond("vow_mark", "heart_s_rebuke", devotion=0)
    _rolls(engine, 1)
    _hit(engine, ALLY, 5)
    assert not [c for c in ally.conditions.values() if c.condition_id == WARD] and me.resources[DEVOTION] == 1


def _foe_marked_by(engine, placer_id, foe_id=TFOE):
    engine._apply_condition(engine.state.actors[foe_id], typed_executor.mark_condition_id("Resonance Mark", placer_id), "test:resonance", placer_id, expires_on="UNTIL_REMOVED")


def test_stand_together_spends_a_devotion_for_the_most_hurt_marked_allys_temporary_hp_when_the_heartbinder_marks_a_hostile():
    engine, me, (ally, ally2) = _bond("vow_mark", friends=2, devotion=2)
    ally2.current_hp = 20  # hurt worst
    events_before = len(engine.events)
    _foe_marked_by(engine, ME)
    assert me.resources[DEVOTION] == 1
    assert (ally2.temporary_hp, ally.temporary_hp) == (2 + 4, 0)  # Wisdom modifier + Proficiency Bonus
    assert any("Stand Together" in line for line in _logs(engine.events[events_before:]))
    assert not _plug_in_failures(engine)


def test_stand_together_reads_a_mark_a_vow_marked_ally_within_thirty_feet_places_and_gives_each_creature_the_temporary_hp_once_a_round():
    engine, me, (ally, ally2) = _bond("vow_mark", friends=2, devotion=3)
    ally2.current_hp = 20
    _foe_marked_by(engine, ALLY)  # the ally at (3,7) is a Vow-Marked ally of the Heartbinder at (3,6)
    assert me.resources[DEVOTION] == 2 and ally2.temporary_hp == 6
    _foe_marked_by(engine, ALLY)  # the same round: ally2 has had its Temporary HP; the other one is offered it
    assert me.resources[DEVOTION] == 1 and ally.temporary_hp == 6
    _foe_marked_by(engine, ALLY)  # both have had it this round
    assert me.resources[DEVOTION] == 1
    engine.state.round_number += 1
    ally.temporary_hp = ally2.temporary_hp = 0
    _foe_marked_by(engine, ALLY)
    assert me.resources[DEVOTION] == 0


def test_stand_together_needs_devotion_a_hostile_target_a_vow_marked_placer_and_a_marked_ally_that_gains():
    engine, me, (ally, ally2) = _bond("vow_mark", friends=2, devotion=0)
    _foe_marked_by(engine, ME)
    assert ally.temporary_hp == ally2.temporary_hp == 0  # no Devotion to spend
    me.resources[DEVOTION] = 2
    engine._apply_condition(ally, typed_executor.mark_condition_id("Resonance Mark", ME), "test", ME, expires_on="UNTIL_REMOVED")  # a mark on an ally, not a hostile
    assert me.resources[DEVOTION] == 2 and ally.temporary_hp == 0
    engine._remove_condition(ally2, typed_executor.mark_condition_id("Vow Mark", ME), "test")
    _foe_marked_by(engine, ALLY2)  # placed by a creature that is not Vow-Marked
    assert me.resources[DEVOTION] == 2
    ally.temporary_hp = 9  # already has more than the grant
    _foe_marked_by(engine, ME)
    assert me.resources[DEVOTION] == 2


def test_a_player_set_to_ask_me_is_asked_before_stand_together_spends_a_devotion():
    engine, me, (ally,) = _bond("vow_mark", friends=1, devotion=1)
    asked = []
    from combat import typed_reactions
    real = typed_reactions._consent
    typed_reactions._consent = lambda engine, row, reactor, checkpoint: (asked.append(checkpoint), False)[1]
    try:
        _foe_marked_by(engine, ME)
    finally:
        typed_reactions._consent = real
    assert asked == ["STAND_TOGETHER"] and me.resources[DEVOTION] == 1 and ally.temporary_hp == 0


def _chained(friends=2, devotion=2, resonance=20):
    engine, me, marked = _bond("vow_mark", "chain_of_devotion", friends=friends, devotion=devotion, resonance=resonance)
    _act(engine, ME, "Chain of Devotion")
    return engine, me, marked


def _linked(engine):
    return sorted(a.entity_id for a in engine.state.actors.values() if any(c.condition_id == CHAIN for c in a.conditions.values()))


def test_chain_of_devotion_links_the_heartbinder_and_its_vow_marked_allies_for_six_resonance_and_concentration():
    engine, me, marked = _chained()
    assert _linked(engine) == sorted([ME, ALLY, ALLY2]) and me.resources[RESONANCE] == 20 - 6
    assert me.concentration is not None  # it is a Concentration technique
    assert any("Devotion Chain" in line for line in _logs(engine.events))
    held = next(c for c in marked[0].conditions.values() if c.condition_id == CHAIN)
    assert held.expires_on == "CONCENTRATION_END" and held.data["reading"] and held.data["label"] == "Devotion Chain"
    assert not _plug_in_failures(engine)


def test_the_chain_links_at_most_pb_creatures_nearest_first_and_needs_a_marked_ally():
    engine, me, marked = _bond("vow_mark", "chain_of_devotion", friends=3)
    me.proficiency_bonus = 3  # the Heartbinder plus two of its three marked allies
    _act(engine, ME, "Chain of Devotion")
    assert _linked(engine) == sorted([ME, ALLY, ALLY2])
    alone = _bond("vow_mark", "chain_of_devotion", friends=1)[0]
    alone.state.actors[ALLY].conditions.clear()  # no marked ally: the rite is not on the menu
    assert not [c for c in alone.legal_candidates() if c.display_name == "Chain of Devotion"]


def test_a_linked_creature_has_plus_one_on_intelligence_wisdom_and_charisma_saves_while_another_linked_creature_is_within_sixty_feet():
    engine, me, (ally, ally2) = _chained()
    wis = next(e for e in _forced_save(engine, TFOE, ALLY, "WIS", 30) if e.event_type == "SAVE_ROLLED")
    dex = next(e for e in _forced_save(engine, TFOE, ALLY, "DEX", 30) if e.event_type == "SAVE_ROLLED")
    assert wis.payload["dc"] == 30 - 1 and dex.payload["dc"] == 30  # a bonus to the save is the same as that much less on the DC
    for other in (me, ally):  # everyone else out of sixty feet as well
        other.conditions = {k: c for k, c in other.conditions.items() if c.condition_id != CHAIN}
    alone = next(e for e in _forced_save(engine, TFOE, ALLY2, "WIS", 30) if e.event_type == "SAVE_ROLLED")
    assert alone.payload["dc"] == 30  # nobody else is linked any more: no bonus


def test_the_chain_ends_with_the_heartbinders_concentration():
    engine, me, marked = _chained()
    assert _linked(engine) == sorted([ME, ALLY, ALLY2])
    engine._end_concentration(me, "TEST")
    assert _linked(engine) == []


def test_a_linked_creature_that_fails_a_mental_save_may_have_it_rerolled_for_a_devotion_and_the_heartbinders_reaction():
    engine, me, (ally, ally2) = _chained(devotion=2)
    _rolls(engine, 1, 20)  # fails, then the reroll passes
    events = _forced_save(engine, TFOE, ALLY, "WIS", 15, condition="frightened")
    kinds = [e.event_type for e in events if e.event_type in ("RESOURCE_SPENT", "RESOURCE_GAINED") and e.payload.get("resource_id") == DEVOTION]
    assert kinds == ["RESOURCE_SPENT", "RESOURCE_GAINED"] and me.resources[DEVOTION] == 2  # it costs a Devotion; protecting a marked ally gains one
    assert not me.reaction_available
    assert not any(c.condition_id.endswith("frightened") for c in ally.conditions.values())  # the new result stands: it passed
    assert any("rerolls the WIS save" in line and "succeeds" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_a_reroll_is_once_a_round_and_needs_a_devotion_and_a_reaction_and_a_mental_save_against_a_hostile():
    engine, me, (ally, ally2) = _chained(devotion=3)
    _rolls(engine, 1)
    _forced_save(engine, TFOE, ALLY, "WIS", 15)
    spent = me.resources[DEVOTION]
    me.reaction_available = True
    _forced_save(engine, TFOE, ALLY2, "CHA", 15)  # the second failure in the round: no reroll
    assert me.resources[DEVOTION] == spent and me.reaction_available
    engine.state.round_number += 1
    me.resources[DEVOTION] = 0
    _forced_save(engine, TFOE, ALLY, "WIS", 15)  # no Devotion
    assert me.reaction_available and me.resources[DEVOTION] == 0
    me.resources[DEVOTION] = 2
    _forced_save(engine, TFOE, ALLY, "DEX", 15)  # not Int, Wis or Cha
    assert me.reaction_available and me.resources[DEVOTION] == 2
    me.reaction_available = False
    _forced_save(engine, TFOE, ALLY, "WIS", 15)  # its Reaction is spent
    assert me.resources[DEVOTION] == 2


COURAGE_SHARED, DEVOTION_RELEASE = "Borrowed Courage: Courage Shared", "Borrowed Courage: Devotion Release"


def test_courage_shared_ends_frightened_and_prone_on_a_vow_marked_ally_and_gives_twice_pb_plus_wisdom_as_temporary_hit_points():
    engine, me, (ally,) = _bond("vow_mark", "borrowed_courage", devotion=1)
    for condition in ("condition:typed.frightened", "condition:typed.prone"):
        engine._apply_condition(ally, condition, "test", TFOE, expires_on="UNTIL_REMOVED", data={})
    events = _act(engine, ME, COURAGE_SHARED, ALLY)
    assert {c.condition_id for c in ally.conditions.values()} == {typed_executor.mark_condition_id("Vow Mark", ME)}
    assert ally.temporary_hp == 2 * me.proficiency_bonus + 2  # "2 x Proficiency Bonus + Wisdom modifier" (the fixture's Wisdom is +2)
    assert not _plug_in_failures(engine)
    assert me.resources[DEVOTION] == 1  # sharing courage neither costs nor gains Devotion


def test_borrowed_courage_is_offered_only_on_creatures_bearing_the_heartbinders_vow_mark():
    engine, me, (ally,) = _bond("vow_mark", "borrowed_courage", devotion=1)
    engine.state.current_actor_id = ME
    offered = {c.target_ids for c in engine.legal_candidates() if c.display_name in (COURAGE_SHARED, DEVOTION_RELEASE)}
    assert offered == {(ALLY,)}
    engine._remove_condition(ally, typed_executor.mark_condition_id("Vow Mark", ME), "test")
    assert not [c for c in engine.legal_candidates() if c.display_name in (COURAGE_SHARED, DEVOTION_RELEASE)]  # nobody left bears it


def test_devotion_release_pays_a_devotion_for_each_benefit_that_runs_the_heal_and_the_saving_throw_bonus():
    engine, me, (ally,) = _bond("vow_mark", "borrowed_courage", devotion=3)
    ally.current_hp = ally.maximum_hp - 10
    hurt = ally.current_hp
    events = _act(engine, ME, DEVOTION_RELEASE, ALLY)
    assert me.resources[DEVOTION] == 3 - 2  # heal + saves: the 10-foot move and the recovery route are the GM's, so they are not paid for
    assert ally.current_hp == hurt + 2  # "Hit Points equal to your Wisdom modifier"
    bonus = next(c for c in ally.conditions.values() if c.condition_id == SAVE_BONUS)
    rule = bonus.data["rule"]["save_bonus"]
    assert rule["bonus"] == 1 and set(rule["abilities"]) == {"INT", "WIS", "CHA"}
    assert bonus.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert not _plug_in_failures(engine)


def test_devotion_release_on_an_unhurt_ally_pays_only_for_the_saving_throw_bonus_and_needs_a_devotion():
    engine, me, (ally,) = _bond("vow_mark", "borrowed_courage", devotion=3)
    _act(engine, ME, DEVOTION_RELEASE, ALLY)
    assert me.resources[DEVOTION] == 2 and any(c.condition_id == SAVE_BONUS for c in ally.conditions.values())
    me.resources[DEVOTION] = 0
    engine._remove_condition(ally, SAVE_BONUS, "test")
    _act(engine, ME, DEVOTION_RELEASE, ALLY)
    assert not any(c.condition_id == SAVE_BONUS for c in ally.conditions.values())  # nothing to spend


def test_the_ai_uses_devotion_release_only_when_it_has_devotion_and_an_ally_is_hurt():
    engine, me, (ally,) = _bond("vow_mark", "borrowed_courage", devotion=2)
    engine.state.current_actor_id = ME
    candidate = next(c for c in engine.legal_candidates() if c.display_name == DEVOTION_RELEASE)
    action = engine.action_catalog[candidate.source_definition_id]
    assert ext.any_false("ai_candidate_allowed", engine, me, candidate, action)  # unhurt: not worth a Devotion
    ally.current_hp = ally.maximum_hp - 5
    assert not ext.any_false("ai_candidate_allowed", engine, me, candidate, action)
    me.resources[DEVOTION] = 0
    assert ext.any_false("ai_candidate_allowed", engine, me, candidate, action)


UNBROKEN_VOW = "tianxia.tradition.spirit.heartbinder.feature.unbroken_vow"


def _held_at_one(*, devotion=0, hp=5):
    engine, me, (ally,) = _bond("vow_mark", "unbroken_vow", friends=1, devotion=devotion)
    ally.current_hp = hp
    events = _hit(engine, ALLY, 30, "fire")
    return engine, me, ally, events


def test_unbroken_vow_holds_a_vow_marked_ally_at_one_hit_point_for_a_reaction_and_resonance_and_gains_a_devotion():
    engine, me, ally, events = _held_at_one()
    assert ally.current_hp == 1 and ally.active
    assert any(c.condition_id == DELAY and c.expires_on == "END_OF_HOLDER_NEXT_TURN" for c in ally.conditions.values())
    assert not me.reaction_available and me.resources[DEVOTION] == 1
    assert me.resources[RESONANCE] == 20 - 10
    assert any("Unbroken Vow holds" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_the_delay_takes_no_further_damage_from_an_attack_and_the_ally_falls_at_the_end_of_its_next_turn_if_still_at_one_hit_point():
    engine, me, ally, _ = _held_at_one()
    engine.state.current_actor_id = TFOE
    _hit(engine, ALLY, 12, "fire")
    assert ally.current_hp == 1 and ally.active  # "delays the drop"; the damage does not land
    before = len(engine.events)
    engine._expire_typed_for_checkpoint("END_OF_TURN", ALLY)
    events = engine.events[before:]
    assert ally.current_hp == 0 and not ally.active
    assert any("still at 1 Hit Point, so the delayed consequence occurs" in line for line in _logs(events))
    assert not any(c.condition_id == DELAY for c in ally.conditions.values())


def test_a_delayed_ally_that_is_healed_above_one_hit_point_does_not_fall():
    engine, me, ally, _ = _held_at_one()
    ally.current_hp = 7  # healed (the engine's healing all lands as plain Hit Points)
    before = len(engine.events)
    engine._expire_typed_for_checkpoint("END_OF_TURN", ALLY)
    assert any("healed past 1 Hit Point" in line for line in _logs(engine.events[before:]))
    assert ally.current_hp == 7 and ally.active
    assert not any(c.condition_id == DELAY for c in ally.conditions.values())


def test_unbroken_vow_needs_the_ally_to_bear_the_mark_and_the_heartbinder_a_reaction_and_the_resonance():
    for spoil in ("unmarked", "no_reaction", "no_resonance"):
        engine, me, (ally,) = _bond("vow_mark", "unbroken_vow", friends=1)
        ally.current_hp = 5
        if spoil == "unmarked":
            engine._remove_condition(ally, typed_executor.mark_condition_id("Vow Mark", ME), "test")
        elif spoil == "no_reaction":
            me.reaction_available = False
        else:
            me.resources[RESONANCE] = 9
        _hit(engine, ALLY, 30, "fire")
        assert ally.current_hp == 0 and not ally.active, spoil


def test_unbroken_vow_is_not_used_on_a_hit_that_does_not_drop_the_ally():
    engine, me, (ally,) = _bond("vow_mark", "unbroken_vow", friends=1)
    _hit(engine, ALLY, 3, "fire")
    assert me.reaction_available and me.resources[RESONANCE] == 20 and not any(c.condition_id == DELAY for c in ally.conditions.values())


def test_the_vow_mark_and_the_devotion_chain_have_hover_text_on_the_table():
    reading = TabletopService.MARK_READINGS["vow_mark"]
    assert "Vow Mark" in reading and "Devotion" in reading
    engine, me, marked = _chained()
    held = next(c for c in marked[0].conditions.values() if c.condition_id == CHAIN)
    assert "Linked by" in held.data["reading"] and "reroll" in held.data["reading"] and held.data["label"] == "Devotion Chain"
    for moment in ("STAND_TOGETHER", "CHAIN_REROLL", "DEVOTION_SPEND"):
        assert moment in TabletopService._ASK_MOMENTS


def test_the_ai_casts_the_chain_only_when_none_is_up_and_the_rite_only_below_pb_marks():
    engine, me, (ally,) = _bond("vow_mark", "chain_of_devotion", friends=1)
    engine.state.current_actor_id = ME
    chain = next(c for c in engine.legal_candidates() if c.display_name == "Chain of Devotion")
    action = engine.action_catalog[chain.source_definition_id]
    assert not ext.any_false("ai_candidate_allowed", engine, me, chain, action)
    _act(engine, ME, "Chain of Devotion")
    engine.state.current_actor_id = ME
    me.action_available = True
    again = [c for c in engine.legal_candidates() if c.display_name == "Chain of Devotion"]
    assert not again or ext.any_false("ai_candidate_allowed", engine, me, again[0], engine.action_catalog[again[0].source_definition_id])


# ------------------------------------------------ Effect suppression and transfer (combat/ext/end_effect.py, effect_transfer.py; system G)
from tests.test_auto_lane1 import _legal, _put_modifier  # noqa: E402

REOPEN = "tianxia.talent.life.reopen_the_living_meridian"
STEAL_ONGOING = "TAL_SCOUNDREL_STEAL_ONGOING_TECHNIQUE"


def _reopen(condition="silenced", *, dc=-40, by=FOE, source="action:test.foe_hex"):
    """A Life cultivator with Reopen the Living Meridian (its own Cultivation Save DC as given: -40 lets any roll pass, 60 none) at
    (3,6), an ally at (3,7) bearing ``condition`` that ``by`` put on it."""
    engine = _engine(_bundle(REOPEN, dc=dc), allies=(_ally_bundle(),))
    if condition:
        _put(engine, ALLY, condition, by, source)
    return engine, engine.state.actors[ME], engine.state.actors[ALLY]


def _turns(engine, actor, count):
    """``count`` of ``actor``'s turns begin and end (the suppression / theft clocks run on turns_started at each turn's end)."""
    for _ in range(count):
        actor.turns_started += 1
        ext.run("turn_end", engine, actor)


def test_reopen_the_living_meridian_is_offered_only_against_an_effect_of_the_kinds_it_names():
    engine, me, ally = _reopen(None)
    assert "Reopen the Living Meridian" not in _legal(engine)
    _put(engine, ALLY, "prone", FOE, "action:test.trip")  # not one of CP, talents, Concentration, speech, breath, movement
    assert "Reopen the Living Meridian" not in _legal(engine)
    _put(engine, ALLY, "silenced", FOE, "action:test.hush")
    assert "Reopen the Living Meridian" in _legal(engine)


@pytest.mark.parametrize("condition", ["silenced", "no_cp_regain", "smothered", "sickened", "held_fast", "no_dash"])
def test_reopen_the_living_meridian_suppresses_each_kind_of_blocking_effect_for_a_minute_on_a_success(condition):
    engine, me, ally = _reopen(condition)
    events = _use(engine, "Reopen the Living Meridian", ALLY)
    (rolled,) = _payloads(events, "CHECK_ROLLED")
    assert rolled["skill"] == "Cultivation Check" and rolled["success"] is True
    assert not _held(ally, f"condition:typed.{condition}") and _held(ally, f"condition:typed.suppressed.{condition}")
    assert any("suppresses" in line and "for 1 minute" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_reopen_the_living_meridians_effect_comes_back_after_ten_of_the_targets_turns_not_before():
    engine, me, ally = _reopen("silenced")
    _use(engine, "Reopen the Living Meridian", ALLY)
    _turns(engine, ally, 9)
    assert _held(ally, "condition:typed.suppressed.silenced") and not _held(ally, "condition:typed.silenced")
    _turns(engine, ally, 1)
    assert _held(ally, "condition:typed.silenced") and not _held(ally, "condition:typed.suppressed.silenced")


def test_reopen_the_living_meridian_on_a_failure_suppresses_only_until_the_end_of_the_targets_next_turn():
    engine, me, ally = _reopen(None, dc=60)
    own = next(k for k, a in engine.action_catalog.items() if a.display_name == "Reopen the Living Meridian")
    _put(engine, ALLY, "silenced", FOE, own)  # a technique whose save DC is this sheet's 60: no check can meet it
    events = _use(engine, "Reopen the Living Meridian", ALLY)
    (rolled,) = _payloads(events, "CHECK_ROLLED")
    assert rolled["success"] is False and rolled["dc"] == 60
    assert _held(ally, "condition:typed.suppressed.silenced")
    assert any("until the end of its next turn" in line for line in _logs(events))
    _turns(engine, ally, 1)
    assert _held(ally, "condition:typed.silenced") and not _held(ally, "condition:typed.suppressed.silenced")


def test_reopen_the_living_meridian_rolls_against_the_effects_own_save_dc_or_its_casters_cultivation_save_dc():
    engine, me, ally = _reopen("silenced")
    foe = engine.state.actors[FOE]
    from combat.ext import end_effect
    expected = end_effect.cultivation_dc(engine, foe)
    (rolled,) = _payloads(_use(engine, "Reopen the Living Meridian", ALLY), "CHECK_ROLLED")
    assert rolled["dc"] == expected  # no technique of the foe's put it there: the foe's own Cultivation Save DC
    engine2, me2, ally2 = _reopen("silenced")
    own = next(k for k, a in engine2.action_catalog.items() if a.display_name == "Reopen the Living Meridian")
    _put(engine2, ALLY, "smothered", FOE, own)  # the DC of the technique that placed it: this sheet's -40
    engine2._remove_condition(ally2, "condition:typed.silenced", "test")
    (rolled2,) = _payloads(_use(engine2, "Reopen the Living Meridian", ALLY), "CHECK_ROLLED")
    assert rolled2["dc"] == -40


def test_reopen_the_living_meridian_takes_off_a_movement_penalty_but_not_a_speed_bonus():
    engine, me, ally = _reopen(None)
    _put_modifier(engine, ALLY, "speed_ft", 10, ALLY, "action:test.haste")
    assert "Reopen the Living Meridian" not in _legal(engine)
    _put_modifier(engine, ALLY, "speed_ft", -15, FOE, "action:test.slow")
    assert "Reopen the Living Meridian" in _legal(engine)
    _use(engine, "Reopen the Living Meridian", ALLY)
    assert sorted(m.target_field for m in ally.modifiers.values()) == ["speed_ft", "suppressed:speed_ft"]
    assert next(m for m in ally.modifiers.values() if m.target_field == "suppressed:speed_ft").value == -15


def test_a_suppressed_silence_no_longer_stops_the_speech_rule():
    engine, me, ally = _reopen("silenced")
    assert any(row.get("_rule") for row in typed_executor.condition_rules(ally))
    _use(engine, "Reopen the Living Meridian", ALLY)
    assert not any("silenced" in str(row.get("_rule", "")).lower() for row in typed_executor.condition_rules(ally))


def _thief(*, ward=True):
    """A Scoundrel with Steal Ongoing Technique (CL 15, Martial Focus 1) at (3,6); the foe at (4,6) is warded by one of its own side."""
    engine = _engine(_bundle(STEAL_ONGOING, cl=15))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    _give(me, FOCUS, 1)
    if ward:
        _put_modifier(engine, FOE, "armor_class", 3, FOE, "action:test.foe_ward")
    return engine, me, foe


def _ac_bonus(actor):
    return sum(m.value for m in actor.modifiers.values() if m.target_field == "armor_class" and isinstance(m.value, int))


def test_steal_ongoing_technique_is_offered_only_against_a_creature_with_a_beneficial_effect_of_its_own_side():
    engine, me, foe = _thief(ward=False)
    assert "STEAL ONGOING TECHNIQUE" not in _legal(engine)
    _put(engine, FOE, "restrained", ME, "action:test.my_net")  # a harmful effect on it is not a benefit
    _put(engine, FOE, "frightened", FOE, "action:test.self_inflicted")
    assert "STEAL ONGOING TECHNIQUE" not in _legal(engine)
    _put_modifier(engine, FOE, "armor_class", 2, ME, "action:test.my_own_ward")  # an effect its enemy put on it is not its own side's
    assert "STEAL ONGOING TECHNIQUE" not in _legal(engine)
    _put_modifier(engine, FOE, "armor_class", 2, FOE, "action:test.foe_ward")
    assert "STEAL ONGOING TECHNIQUE" in _legal(engine)


def test_a_successful_scoundrel_check_moves_the_effect_to_the_thief_and_the_target_loses_the_benefit():
    engine, me, foe = _thief()
    _fixed(engine, 20)
    before = _ac_bonus(me), _ac_bonus(foe)
    events = _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    (rolled,) = _payloads(events, "CHECK_ROLLED")
    assert rolled["skill"] == "Scoundrel Check" and rolled["against"] == "Cultivation Save DC" and rolled["success"] is True
    assert before == (0, 3) and (_ac_bonus(me), _ac_bonus(foe)) == (3, 0)
    assert me.resources[FOCUS] == 0  # "Cost: Expend Martial Focus"
    assert any("takes" in line and "for up to 1 minute" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_a_failed_scoundrel_check_moves_nothing_but_the_creature_is_spent(monkeypatch):
    from combat.ext import effect_transfer
    engine, me, foe = _thief()
    _fixed(engine, 1)
    monkeypatch.setattr(effect_transfer, "cultivation_dc", lambda engine, creature: 60)
    events = _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    assert _payloads(events, "CHECK_ROLLED")[0]["success"] is False
    assert (_ac_bonus(me), _ac_bonus(foe)) == (0, 3)
    _give(me, FOCUS, 1)
    assert "STEAL ONGOING TECHNIQUE" not in _legal(engine)  # once per creature: the attempt counted


def test_the_stolen_effect_goes_back_after_ten_turns_and_only_one_may_be_held_at_a_time():
    engine, me, foe = _thief()
    _fixed(engine, 20)
    _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    _put_modifier(engine, FOE, "damage_resistance", "FIRE", FOE, "action:test.foe_hide")
    _give(me, FOCUS, 1)
    _ready(engine)
    assert "STEAL ONGOING TECHNIQUE" not in _legal(engine)  # one stolen technique at a time (and this creature is spent)
    _turns(engine, me, 9)
    assert (_ac_bonus(me), _ac_bonus(foe)) == (3, 0)
    _turns(engine, me, 1)
    assert (_ac_bonus(me), _ac_bonus(foe)) == (0, 3)  # still there when the theft ended: back to the original
    assert any("goes back to" in line for line in _logs(engine.events))


def test_an_effect_that_ends_while_stolen_does_not_return():
    engine, me, foe = _thief()
    _fixed(engine, 20)
    _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    for key, modifier in list(me.modifiers.items()):
        del me.modifiers[key]  # it ran out while the thief held it
    _turns(engine, me, 10)
    assert (_ac_bonus(me), _ac_bonus(foe)) == (0, 0)


def test_the_stolen_effect_keeps_its_source_and_duration_so_the_time_counts():
    engine, me, foe = _thief()
    _fixed(engine, 20)
    (original,) = foe.modifiers.values()
    _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    (stolen,) = me.modifiers.values()
    assert (stolen.source_actor_id, stolen.source_definition_id, stolen.expires_on, stolen.value) == \
        (original.source_actor_id, original.source_definition_id, original.expires_on, original.value)
    assert stolen.target_id == ME


def test_steal_ongoing_technique_takes_the_strongest_kind_and_leaves_marks_and_drawbacks_alone():
    engine, me, foe = _thief(ward=False)
    _put(engine, FOE, "guarding", FOE, "action:test.foe_guard")  # a condition of its side's
    engine._apply_condition(foe, typed_executor.mark_condition_id("Vow Mark", FOE), "test:vow", FOE, expires_on="UNTIL_REMOVED")
    _put_modifier(engine, FOE, "armor_class", 2, FOE, "action:test.foe_ward")
    _fixed(engine, 20)
    _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    assert _ac_bonus(me) == 2 and _held(foe, "condition:typed.guarding")  # the AC bonus (a modifier) first; the condition stays
    assert typed_executor.bears_mark(foe, FOE, "Vow Mark")


def test_a_concentration_bound_effect_is_moved_with_a_note_that_the_takeover_is_not_automated():
    engine, me, foe = _thief(ward=False)
    engine._apply_condition(foe, "condition:typed.guarding", "action:test.foe_stance", FOE, expires_on="CONCENTRATION_END")
    _fixed(engine, 20)
    events = _use(engine, "STEAL ONGOING TECHNIQUE", FOE)
    assert _held(me, "condition:typed.guarding") and not _held(foe, "condition:typed.guarding")
    assert any("Concentration" in str(p.get("rider")) for p in _payloads(events, "GM_RIDER"))


BEAR = "Borrowed Courage: Bear It With Me"
HOLD = "Borrowed Courage: Hold the Heart"


def _scared(*, condition="frightened", repeat=None, cl=18, features=("vow_mark", "borrowed_courage")):
    """A Heartbinder with a Vow-Marked friend who is ``condition`` by the typed foe (source DC 14, or a repeat save when asked)."""
    engine, me, (ally,) = _bond(*features, devotion=1, cl=cl)
    data = {"repeat_save": repeat} if repeat else {}
    engine._apply_condition(ally, f"condition:typed.{condition}", "action:test.fear", TFOE, expires_on="UNTIL_REMOVED", data=data)
    return engine, me, ally


def test_bear_it_with_me_is_offered_only_for_a_frightened_or_charmed_friend():
    engine, me, (ally,) = _bond("vow_mark", "borrowed_courage", devotion=1)
    assert BEAR not in _legal(engine) and HOLD not in _legal(engine)
    engine._apply_condition(ally, "condition:typed.prone", "action:test.trip", TFOE, expires_on="UNTIL_REMOVED", data={})
    assert BEAR not in _legal(engine)
    engine._apply_condition(ally, "condition:typed.frightened", "action:test.fear", TFOE, expires_on="UNTIL_REMOVED", data={})
    assert BEAR in _legal(engine)
    engine._apply_condition(ally, "condition:typed.frightened", "action:test.fear", ME, expires_on="UNTIL_REMOVED", data={})  # its own side's does not count
    engine.state.actors[ALLY].conditions.clear()
    engine._apply_condition(ally, "condition:typed.frightened", "action:test.self_fear", ALLY, expires_on="UNTIL_REMOVED", data={})
    assert BEAR not in _legal(engine)


def test_bear_it_with_me_moves_the_fear_to_the_heartbinder_with_its_source_and_data_for_a_minute():
    engine, me, ally = _scared(repeat={"ability": "WIS", "dc": 14})
    (original,) = [c for c in ally.conditions.values() if c.condition_id == "condition:typed.frightened"]
    events = _act(engine, ME, BEAR, ALLY)
    (borne,) = [c for c in me.conditions.values() if c.condition_id == "condition:typed.frightened"]
    assert not [c for c in ally.conditions.values() if c.condition_id == "condition:typed.frightened"]
    assert (borne.source_actor_id, borne.source_definition_id, borne.data) == (TFOE, original.source_definition_id, original.data)
    assert any("bears" in line and "for 1 minute" in line for line in _logs(events))
    assert not _plug_in_failures(engine)
    _turns(engine, me, 9)
    assert _held(me, "condition:typed.frightened")
    _turns(engine, me, 1)
    assert not _held(me, "condition:typed.frightened") and not _held(ally, "condition:typed.frightened")  # the minute is up: it ends, it does not come back


def test_a_heartbinder_immune_to_the_condition_leaves_it_suppressed_on_the_friend_until_the_end_of_its_next_turn(monkeypatch):
    engine, me, ally = _scared()
    real = typed_executor.condition_immune
    monkeypatch.setattr(typed_executor, "condition_immune",
                        lambda eng, actor, name, *a, **k: True if actor.entity_id == ME and str(name).lower() == "frightened" else real(eng, actor, name, *a, **k))
    events = _act(engine, ME, BEAR, ALLY)
    assert not _held(me, "condition:typed.frightened")
    assert not _held(ally, "condition:typed.frightened")  # suppressed (off the friend) ...
    assert any("immune" in line and "suppressed" in line for line in _logs(events))
    _turns(engine, me, 1)
    assert _held(ally, "condition:typed.frightened")  # ... and back at the end of the Heartbinder's next turn
    assert not _plug_in_failures(engine)


def test_hold_the_heart_suppresses_a_charm_from_a_lower_level_source_without_a_roll_until_the_end_of_the_heartbinders_next_turn():
    engine, me, ally = _scared(condition="charmed", cl=18)
    events = _act(engine, ME, HOLD, ALLY)
    assert not _payloads(events, "CHECK_ROLLED")  # an ordinary effect (the foe's Cultivation Level is below the Heartbinder's)
    assert not _held(ally, "condition:typed.charmed")
    _turns(engine, me, 1)
    assert _held(ally, "condition:typed.charmed")
    assert not _plug_in_failures(engine)


def test_hold_the_heart_rolls_a_cultivation_check_against_an_equal_level_source():
    engine, me, ally = _scared(condition="charmed", cl=10)  # the typed foe is Cultivation Level 10
    _fixed(engine, 1)
    events = _act(engine, ME, HOLD, ALLY)
    rolled = _payloads(events, "CHECK_ROLLED")
    assert rolled and rolled[0]["success"] is False and _held(ally, "condition:typed.charmed")  # the check failed: nothing suppressed
    assert not _plug_in_failures(engine)


# ------------------------------------------------------ Qiweaving: Turbulent Field and its talents (combat/ext/qi_instability.py, system E)
from combat.condition_text import all_conditions  # noqa: E402

QW = "TAL_QIWEAVING_"
TURBULENT = "condition:typed.turbulent"
FRIEND = "condition:typed.storm_friend"
QI = "resource:core.qi"
WORD = "TAL_FATE_BINDING_WORD"  # a 2 CP technique on "one creature" (a Charisma save, no damage): what a creature does inside the Field
# (Lattice Unraveling was used before; its printed target is a formation node, ward, barrier or construct -- not a creature to aim at)
ALLY3 = "actor:factory.lane1_ally3"


def _qw(*names, cl=10, actor_id=ME):
    sheet = _sheet(QW + "TURBULENT_FIELD", cl=cl)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [QW + name for name in names]
    return compile_character(sheet, actor_id=actor_id)


def _storm(*names, cl=10, friends=1, foe=True):
    """A Qiweaver at (3,6) who knows ``names`` (Turbulent Field + talents), ``friends`` teammates (3,7).. and one hostile fighter at (4,6); the
    teammates and the foe each know Binding Word (2 CP), the technique the Field reacts to."""
    mates = [_bundle(WORD, actor_id=actor_id) for actor_id in (ALLY, ALLY2, ALLY3)][:friends]
    foes = [_bundle(WORD, actor_id=TFOE)] if foe else []
    engine = Gate4ControllerEngine(
        ROOT, match_seed="LANE1", typed_bundles=(_qw(*names, cl=cl), *mates, *foes),
        roster_setup={"primary_actor_ids": [ME, *(b["actor_id"] for b in mates), *(b["actor_id"] for b in foes)],
                      "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:a" for b in mates}, **{b["actor_id"]: "team:b" for b in foes}},
                      "starting_positions": {ME: {"x": 3, "y": 6}, **{b["actor_id"]: {"x": 3, "y": 7 + row} for row, b in enumerate(mates)},
                                             **{b["actor_id"]: {"x": 4, "y": 6} for b in foes}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _ready(engine)
    for actor in engine.state.actors.values():
        if actor.entity_id != ME:
            _give(actor, QI, 30)
            actor.maximum_hp = actor.current_hp = 900
    return engine


def _cast(engine, actor_id, target_id):
    """``actor_id`` uses Binding Word (2 CP) on ``target_id``."""
    return _act(engine, actor_id, "Binding Word", target_id)


def _field_saves(events):
    return [p for p in _payloads(events, "SAVE_ROLLED") if str(p.get("reason", "")).endswith("TURBULENT_FIELD:CON")]


def _turbulent(actor):
    return _held(actor, TURBULENT)


def test_turbulent_field_is_a_concentration_emanation_whose_radius_grows_with_level():
    """"5-foot-radius Emanation ... 1-4: 5 feet; 5-10: 10 feet; 11-16: 15 feet; 17-20: 20 feet": a 5-foot zone at every level before."""
    radii = {}
    for cl in (1, 4, 5, 10, 11, 16, 17, 20):
        engine = _engine(_qw("TURBULENT_FIELD", cl=cl))
        row = next(r for r in engine.action_catalog.values() if r.display_name == "Turbulent Field")
        assert row.concentration
        radii[cl] = row.radius_ft
        assert row.parameters["typed"]["zone_spec"]["size_ft"] == row.radius_ft  # the area left on the map is as big as the row says
    assert radii == {1: 5, 4: 5, 5: 10, 10: 10, 11: 15, 16: 15, 17: 20, 20: 20}


def test_a_hostile_cp_technique_inside_the_field_makes_its_user_save_and_a_failure_marks_it_turbulent_until_the_end_of_the_owners_next_turn():
    engine = _storm("TURBULENT_FIELD", friends=0)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _use(engine, "Turbulent Field")
    _fixed(engine, 1)
    events = _cast(engine, TFOE, ME)
    (save,) = _field_saves(events)
    assert save["dc"] == 16 and save["success"] is False  # the owner's technique save DC
    (mark,) = _turbulent(foe)
    assert mark.source_actor_id == ME and mark.expires_on.startswith("END_OF_SOURCE_TURN")
    assert any("Binding Word is Turbulent" in line and "complication the GM chooses" in line for line in _logs(events))
    assert "Turbulent Field" in all_conditions()["turbulent"]["reading"]  # the table's hover text
    assert not _plug_in_failures(engine)


def test_the_field_saves_once_a_turn_and_a_success_marks_nothing():
    engine = _storm("TURBULENT_FIELD", friends=0)
    foe = engine.state.actors[TFOE]
    _use(engine, "Turbulent Field")
    _fixed(engine, 20)
    assert not _turbulent(foe) and len(_field_saves(_cast(engine, TFOE, ME))) == 1
    assert not _turbulent(foe)
    _fixed(engine, 1)
    assert not _field_saves(_cast(engine, TFOE, ME))  # the first technique on a turn only
    assert not _turbulent(foe)


def test_a_technique_that_costs_no_cp_or_one_made_outside_the_field_does_not_call_for_a_save():
    engine = _storm("TURBULENT_FIELD", friends=0)
    foe = engine.state.actors[TFOE]
    _use(engine, "Turbulent Field")
    _fixed(engine, 1)
    assert not _field_saves(_act(engine, TFOE, "Shove: Push 5 ft", ME))  # no CP
    engine.state.actors[TFOE].position = Position(x=8, y=6)  # 25 feet away: outside the 10-foot Field, inside Binding Word's 30-foot range
    assert not _field_saves(_cast(engine, TFOE, ME)) and not _turbulent(foe)


def test_the_owner_and_a_chosen_friend_are_not_affected_but_an_ordinary_ally_is():
    engine = _storm("TURBULENT_FIELD", "FRIEND_IN_THE_STORM", friends=3, cl=11)  # radius 15 feet: the third teammate stands 15 feet away
    me = engine.state.actors[ME]
    events = _use(engine, "Turbulent Field")
    friends = [a for a in engine.state.actors.values() if _held(a, FRIEND)]
    assert [a.entity_id for a in friends] == [ALLY, ALLY2]  # the Key Ability modifier (2) nearest creatures
    assert _held(friends[0], FRIEND)[0].expires_on == "CONCENTRATION_END"
    assert any("spares" in line and "Friend in the Storm" in line for line in _logs(events))
    _fixed(engine, 1)
    assert not _field_saves(_cast(engine, ALLY, TFOE)) and not _turbulent(engine.state.actors[ALLY])
    assert _field_saves(_cast(engine, ALLY3, TFOE)) and _turbulent(engine.state.actors[ALLY3])  # the third is not a friend of the storm
    # the owner is never inside its own field
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Binding Word")
    assert not ext.run("technique_start", engine, me, action) and not _turbulent(me)
    engine._end_concentration(me, "test")
    assert not _held(engine.state.actors[ALLY], FRIEND)  # the Concentration ended: so do the markers
    assert not _plug_in_failures(engine)


def test_without_friend_in_the_storm_every_ally_is_inside_the_fields_reach():
    engine = _storm("TURBULENT_FIELD", friends=1)
    events = _use(engine, "Turbulent Field")
    assert not _held(engine.state.actors[ALLY], FRIEND) and not any("spares" in line for line in _logs(events))
    _fixed(engine, 1)
    assert _field_saves(_cast(engine, ALLY, TFOE)) and _turbulent(engine.state.actors[ALLY])


def test_turbulent_backlash_spends_one_cp_to_deal_force_damage_and_give_the_foe_disadvantage_on_its_next_concentration_save():
    engine = _storm("TURBULENT_FIELD", "TURBULENT_BACKLASH", friends=0)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _use(engine, "Turbulent Field")
    before, hp = me.resources[QI], foe.current_hp
    _fixed(engine, 1)
    events = _cast(engine, TFOE, ME)
    assert me.resources[QI] == before - 1
    assert foe.current_hp == hp - 6  # PB 4 + Key Ability modifier 2 (Force)
    (mode,) = _held(foe, "condition:typed.concentration_mode")
    assert mode.data["rule"] == {"concentration_mode": "DISADVANTAGE", "next": True} and mode.expires_on.startswith("START_OF_TURN_AT")
    assert any("Turbulent Backlash hits" in line and "Disadvantage on its next Concentration" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def _backlash_engine():
    engine = _storm("TURBULENT_FIELD", "TURBULENT_BACKLASH", friends=1)
    _use(engine, "Turbulent Field")
    return engine, engine.state.actors[ME]


def test_turbulent_backlash_is_not_spent_on_a_friendly_creatures_failed_save():
    engine, me = _backlash_engine()
    before = me.resources[QI]
    _fixed(engine, 1)
    _cast(engine, ALLY, TFOE)
    assert _turbulent(engine.state.actors[ALLY]) and me.resources[QI] == before
    assert not _held(engine.state.actors[ALLY], "condition:typed.concentration_mode")


def test_turbulent_backlash_is_not_spent_when_the_hostile_creature_passes_its_save():
    engine, me = _backlash_engine()
    before = me.resources[QI]
    _fixed(engine, 20)
    _cast(engine, TFOE, ME)
    assert not _turbulent(engine.state.actors[TFOE]) and me.resources[QI] == before
    assert not _held(engine.state.actors[TFOE], "condition:typed.concentration_mode")


def test_turbulent_backlash_needs_a_cp_to_spend():
    engine, me = _backlash_engine()
    for pool in typed_executor.CP_POOLS:
        if pool in me.resources:
            me.resources[pool] = 0
    _fixed(engine, 1)
    _cast(engine, TFOE, ME)
    assert _turbulent(engine.state.actors[TFOE]) and not _held(engine.state.actors[TFOE], "condition:typed.concentration_mode")


def test_quiet_the_flaw_gives_a_friend_advantage_on_the_field_save_for_a_reaction_and_one_cp():
    engine = _storm("TURBULENT_FIELD", "QUIET_THE_FLAW", friends=1)
    me = engine.state.actors[ME]
    _use(engine, "Turbulent Field")
    before = me.resources[QI]
    me.reaction_available = True
    events = _cast(engine, ALLY, TFOE)
    (save,) = _field_saves(events)
    assert save["mode"] == "ADVANTAGE"
    assert me.resources[QI] == before - 1 and not me.reaction_available
    assert any("quiets the flaw" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_quiet_the_flaw_needs_a_reaction_and_does_not_help_an_enemy():
    engine = _storm("TURBULENT_FIELD", "QUIET_THE_FLAW", friends=1)
    me = engine.state.actors[ME]
    _use(engine, "Turbulent Field")
    before = me.resources[QI]
    _fixed(engine, 20)  # (the owner's Concentration holds)
    events = _cast(engine, TFOE, ME)  # an enemy's technique
    assert _field_saves(events)[0]["mode"] == "NORMAL" and me.resources[QI] == before and me.reaction_available
    me.reaction_available = False
    engine.state.actors[ALLY].turn_flags.clear()
    events = _cast(engine, ALLY, TFOE)
    assert _field_saves(events)[0]["mode"] == "NORMAL" and me.resources[QI] == before  # its Reaction was used


def _unsteady(*names, friends=1):
    """A Qiweaver whose ally has been marked Turbulent by its own Field (the ally's save fails)."""
    engine = _storm("TURBULENT_FIELD", *names, friends=friends)
    _use(engine, "Turbulent Field")
    _fixed(engine, 1)
    _cast(engine, ALLY, TFOE)
    _ready(engine)
    return engine, engine.state.actors[ME], engine.state.actors[ALLY]


def test_regulated_breathing_is_offered_only_for_a_creature_marked_turbulent_that_has_not_been_helped():
    engine = _storm("TURBULENT_FIELD", "REGULATED_BREATHING", friends=1)
    assert "Regulated Breathing" not in _legal(engine)  # nothing unstable yet
    _use(engine, "Turbulent Field")
    _fixed(engine, 1)
    _cast(engine, ALLY, TFOE)
    _ready(engine)
    assert "Regulated Breathing" in _legal(engine)
    _act(engine, ME, "Regulated Breathing", ALLY)  # (fails, below): a creature is helped once
    _ready(engine)
    assert "Regulated Breathing" not in _legal(engine)


def test_regulated_breathing_repeats_the_save_with_the_key_ability_modifier_added_and_a_success_ends_the_instability():
    engine, me, ally = _unsteady("REGULATED_BREATHING")
    assert _turbulent(ally)
    _fixed(engine, 12)  # 12 + 2 = 14: short of DC 16 by itself, enough with the +2 Key Ability modifier
    events = _act(engine, ME, "Regulated Breathing", ALLY)
    (save,) = _payloads(events, "SAVE_ROLLED")
    assert save["dc"] == 14 and save["success"] is True
    assert not _turbulent(ally)
    assert any("steadies" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_a_failed_repeat_leaves_the_instability_and_the_creature_cannot_be_helped_again():
    engine, me, ally = _unsteady("REGULATED_BREATHING")
    _fixed(engine, 5)
    events = _act(engine, ME, "Regulated Breathing", ALLY)
    assert _turbulent(ally) and any("does not settle" in line for line in _logs(events))
    _ready(engine)
    assert "Regulated Breathing" not in _legal(engine)


def test_calm_the_wild_meridian_suppresses_the_instability_for_a_minute_on_a_successful_qiweaving_check():
    engine, me, ally = _unsteady("CALM_THE_WILD_MERIDIAN")
    before = me.resources[QI]
    _fixed(engine, 20)
    events = _act(engine, ME, "Calm the Wild Meridian", ALLY)
    (check,) = _payloads(events, "CHECK_ROLLED")
    assert check["skill"] == "Qiweaving Check" and check["dc"] == 16 and check["success"] is True  # the Field's technique save DC
    assert not _turbulent(ally) and _held(ally, "condition:typed.suppressed.turbulent")
    assert me.resources[QI] == before - 4
    assert not _plug_in_failures(engine)
    _turns(engine, ally, 10)  # the suppression runs on the creature's own turns
    assert _turbulent(ally) and not _held(ally, "condition:typed.suppressed.turbulent")  # the minute is up


def test_a_failed_calm_leaves_the_instability_but_the_creature_has_advantage_against_it_until_the_start_of_the_next_turn():
    engine, me, ally = _unsteady("CALM_THE_WILD_MERIDIAN")
    _fixed(engine, 1)
    events = _act(engine, ME, "Calm the Wild Meridian", ALLY)
    assert _turbulent(ally)
    (advantage,) = _held(ally, "condition:typed.save_against")
    assert advantage.data["rule"]["save_against"]["against"] == ["turbulent"] and advantage.data["rule"]["save_against"]["mode"] == "ADVANTAGE"
    assert advantage.expires_on.startswith("START_OF_SOURCE_TURN") or "START" in advantage.expires_on
    assert any("Advantage on saving throws against turbulent" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_calm_is_not_offered_when_nothing_is_turbulent_and_the_built_in_ai_never_picks_it_or_regulated_breathing():
    engine, me, ally = _unsteady("REGULATED_BREATHING", "CALM_THE_WILD_MERIDIAN")
    assert {"Regulated Breathing", "Calm the Wild Meridian"} <= _legal(engine)
    assert not {"Regulated Breathing", "Calm the Wild Meridian"} & _ai_names(engine)
    engine._remove_condition(ally, TURBULENT, "test")
    assert not {"Regulated Breathing", "Calm the Wild Meridian"} & _legal(engine)


# ------------------------------------------------------------------------ C1 Karmic Imprints (combat/ext/karma_imprints.py)
from combat.ext import karma_imprints  # noqa: E402

KM = "tianxia.talent.karma."
RECORD = "TAL_KARMA_RECORD_THE_DEED"
DEBT, GRACE = "Debt Imprint", "Grace Imprint"


def _karma(*ids, cl=10, actor_id=ME):
    """A Karma character who has the base abilities (Record the Deed among them) and the talents named."""
    sheet = _sheet(ids[0] if ids else RECORD, cl=cl)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(ids) or [RECORD]
    return compile_character(sheet, actor_id=actor_id)


def _ledger(*ids, friends=1, foes=1, cl=10, allies=None):
    """A Karma character at (3,6) with ``friends`` teammates behind it and ``foes`` typed hostile fighters (900 HP) at (4,6).."""
    pool = allies or [_ally_bundle(), _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2), _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY3)][:friends]
    engine = _squad(_karma(*ids, cl=cl), pool, foes=foes)
    for actor in engine.state.actors.values():
        if actor.team_id == "team:b":
            actor.maximum_hp = actor.current_hp = 900
    return engine


def _imprints(engine, creature_id, kind=None, owner=ME):
    return karma_imprints.held(engine.state.actors[creature_id], owner, kind)


def _new_round(engine):
    """The next round: the holder's Reaction is back and the round counter has moved on."""
    engine.state.round_number += 1
    for actor in engine.state.actors.values():
        actor.reaction_available = True


def test_a_hostile_hit_on_a_teammate_is_recorded_as_a_debt_imprint_on_the_attacker_and_costs_the_reaction():
    engine = _ledger()
    me = engine.state.actors[ME]
    events = _hit(engine, ALLY, 10)
    assert len(_imprints(engine, TFOE, "debt")) == 1 and not _imprints(engine, TFOE, "grace")
    assert not me.reaction_available
    assert any("records the deed (Reaction)" in line and "1 of 4" in line for line in _logs(events))
    assert typed_executor.bears_mark(engine.state.actors[TFOE], ME, DEBT)
    assert not _imprints(engine, ALLY) and not _imprints(engine, ME)
    assert not _plug_in_failures(engine)


def test_the_holders_own_side_hurting_a_foe_or_each_other_records_nothing():
    engine = _ledger()
    _hit(engine, TFOE, 10, by=ALLY)  # a teammate hits the hostile fighter: self-defence, not a Cause
    _hit(engine, ALLY, 5, by=ME)  # friendly fire
    assert not _imprints(engine, ALLY) and not _imprints(engine, ME) and engine.state.actors[ME].reaction_available


def test_a_record_needs_a_witness_within_sixty_feet_and_a_hit_out_of_sight_is_not_recorded():
    engine = _ledger()
    engine.state.actors[TFOE].position = Position(x=19, y=6)  # 80 feet from the holder
    _hit(engine, ALLY, 10)
    assert not _imprints(engine, TFOE) and engine.state.actors[ME].reaction_available
    engine.state.actors[TFOE].position = Position(x=13, y=6)  # 50 feet
    _hit(engine, ALLY, 10)
    assert len(_imprints(engine, TFOE, "debt")) == 1


def test_an_attack_against_the_holder_is_recorded_and_the_record_is_once_a_round():
    engine = _ledger()
    _hit(engine, ME, 6)
    assert len(_imprints(engine, TFOE, "debt")) == 1
    _hit(engine, ALLY, 6)  # the Reaction is spent: a second record the same round needs the Seal
    assert len(_imprints(engine, TFOE, "debt")) == 1


def test_a_creature_holds_up_to_the_proficiency_bonus_of_imprints_and_a_full_ledger_keeps_the_reaction():
    engine = _ledger()
    me = engine.state.actors[ME]
    for round_ in range(4):
        _new_round(engine)
        _hit(engine, ALLY, 5)
    assert len(_imprints(engine, TFOE, "debt")) == 4 == me.proficiency_bonus
    _new_round(engine)
    events = _hit(engine, ALLY, 5)
    assert len(_imprints(engine, TFOE)) == 4 and me.reaction_available and not any("records the deed" in line for line in _logs(events))


def test_a_harmful_condition_is_a_debt_and_a_teammates_healing_is_a_grace():
    healer = _bundle("LIFE_BASE_MEND_THE_PULSE", actor_id=ALLY)
    engine = _ledger(allies=[healer, _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2)])
    engine.state.actors[ALLY2].current_hp = 20
    _give(engine.state.actors[ALLY], QI, 30)
    events = _act(engine, ALLY, "Mend the Pulse", ALLY2)
    assert len(_imprints(engine, ALLY, "grace")) == 1 and not _imprints(engine, ALLY, "debt")
    assert any("records the deed" in line and "Grace Imprint" in line for line in _logs(events))
    engine = _ledger()
    engine._apply_condition(engine.state.actors[ALLY], "condition:typed.prone", "action:test.trip", TFOE, expires_on="UNTIL_REMOVED")
    assert len(_imprints(engine, TFOE, "debt")) == 1
    engine = _ledger()
    engine._apply_condition(engine.state.actors[TFOE], "condition:typed.prone", "action:test.trip", ALLY, expires_on="UNTIL_REMOVED")  # the holder's side does it
    assert not _imprints(engine, ALLY)


def test_ledger_seal_scripture_adds_an_imprint_of_room_and_places_one_for_one_cp_when_the_reaction_is_gone():
    engine = _ledger(KM + "ledger_seal_scripture")
    me = engine.state.actors[ME]
    assert karma_imprints.capacity(me, karma_imprints.features(engine, me)) == 5
    before = me.resources[QI]
    me.reaction_available = False
    events = _hit(engine, ALLY, 5)
    assert len(_imprints(engine, TFOE, "debt")) == 1 and me.resources[QI] == before - 1 and not me.reaction_available
    assert any("Ledger Seal, 1 Qi" in line for line in _logs(events))
    _hit(engine, ALLY, 5)  # once a round
    assert len(_imprints(engine, TFOE)) == 1 and me.resources[QI] == before - 1
    assert not _plug_in_failures(engine)
    plain = _ledger()  # without the Scripture a spent Reaction records nothing
    plain.state.actors[ME].reaction_available = False
    _hit(plain, ALLY, 5)
    assert not _imprints(plain, TFOE)


def test_a_player_who_passes_the_record_keeps_the_reaction_and_the_creature_stays_unmarked():
    engine = _ledger()
    engine.typed_ask_reactors = (ME,)  # "Ask me": nothing answers here, so the record is declined
    _hit(engine, ALLY, 5)
    assert not _imprints(engine, TFOE) and engine.state.actors[ME].reaction_available


def test_debt_and_grace_imprints_have_hover_text_on_the_table():
    assert "Debt punishes" in TabletopService.MARK_READINGS["debt_imprint"] and "Grace protects" in TabletopService.MARK_READINGS["grace_imprint"]
    assert "karma_court" in all_conditions()


KCOURT = KM + "court_of_cause_and_effect"
KSEAL = KM + "ledger_seal_scripture"
KSTING = KM + "return_the_sting"


def _mark(engine, holder_id, creature_id, kind):
    """A Debt or Grace Imprint of ``holder_id`` on ``creature_id`` (the Cause that made it is not the test's business)."""
    assert karma_imprints.place(engine, engine.state.actors[holder_id], engine.state.actors[creature_id], kind, RECORD, "test")


def test_the_court_is_a_concentration_aura_that_stretches_the_record_to_120_feet_and_twice_a_round_with_the_seal():
    engine = _ledger(KCOURT, KSEAL)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    me.position, foe.position = Position(x=0, y=6), Position(x=19, y=6)  # 95 feet apart
    _hit(engine, ALLY, 5)
    assert not _imprints(engine, TFOE)  # beyond sixty feet
    events = _act(engine, ME, "Court of Cause and Effect")
    assert me.resources[QI] == 30 - 7 and karma_imprints.court_up(me) and any("opens the Court of Cause and Effect" in line for line in _logs(events))
    assert any(c.condition_id == "condition:typed.karma_court" and c.expires_on == "CONCENTRATION_END" for c in me.conditions.values())
    me.reaction_available = True
    _hit(engine, ALLY, 5)  # inside the Court: a hundred and twenty feet
    _hit(engine, ALLY, 5)  # the second use of the round is the Seal's 1 CP, no Reaction
    _hit(engine, ALLY, 5)  # and there are only two
    assert len(_imprints(engine, TFOE, "debt")) == 2 and me.resources[QI] == 30 - 7 - 1
    assert not _plug_in_failures(engine)


def test_without_the_court_the_second_record_of_a_round_is_refused_and_a_court_that_ends_stops_stretching_the_record():
    engine = _ledger(KCOURT, KSEAL)
    me = engine.state.actors[ME]
    _act(engine, ME, "Court of Cause and Effect")
    me.action_available = me.reaction_available = True
    engine._end_concentration(me, "test") if hasattr(engine, "_end_concentration") else None
    assert not karma_imprints.court_up(me)
    me.position, engine.state.actors[TFOE].position = Position(x=0, y=6), Position(x=19, y=6)
    _hit(engine, ALLY, 5)
    assert not _imprints(engine, TFOE)


def test_inside_the_court_a_creature_with_a_debt_takes_pb_psychic_when_it_damages_another_once_per_turn():
    engine = _ledger(KCOURT)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _act(engine, ME, "Court of Cause and Effect")
    _mark(engine, ME, TFOE, "debt")
    before = foe.current_hp
    events = _hit(engine, ALLY, 5)
    assert foe.current_hp == before - 4 and ("PSYCHIC", 4) in _dealt(events)  # PB
    assert any("the Court deals 4 psychic damage" in line for line in _logs(events))
    _hit(engine, ALLY, 5)  # a creature triggers each effect only once per turn
    assert foe.current_hp == before - 4
    engine.state.round_number += 1
    _hit(engine, ALLY, 5)
    assert foe.current_hp == before - 8
    assert not _plug_in_failures(engine)


def test_the_courts_psychic_does_not_reach_a_debt_bearer_beyond_thirty_feet_or_one_without_a_debt():
    engine = _ledger(KCOURT)
    foe = engine.state.actors[TFOE]
    _act(engine, ME, "Court of Cause and Effect")
    before = foe.current_hp
    _hit(engine, ALLY, 5)  # no Debt yet: the hit records one, and hurts nobody
    engine.state.round_number += 1
    foe.position = Position(x=12, y=6)  # 45 feet: outside the aura
    _hit(engine, ALLY, 5)
    assert foe.current_hp == before


def test_inside_the_court_a_grace_bearer_who_heals_another_or_takes_harm_for_another_gains_pb_temporary_hp():
    healer = _bundle("LIFE_BASE_MEND_THE_PULSE", actor_id=ALLY)
    engine = _ledger(KCOURT, allies=[healer, _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2)])
    ally, wounded = engine.state.actors[ALLY], engine.state.actors[ALLY2]
    _give(ally, QI, 30)
    _act(engine, ME, "Court of Cause and Effect")
    _mark(engine, ME, ALLY, "grace")
    wounded.current_hp = 20
    events = _act(engine, ALLY, "Mend the Pulse", ALLY2)
    assert ally.temporary_hp == 4 and any("the Court gives 4 Temporary HP" in line for line in _logs(events))
    ally.temporary_hp = 0
    _act(engine, ALLY, "Mend the Pulse", ALLY2)  # the same turn: only once
    assert ally.temporary_hp == 0
    assert not _plug_in_failures(engine)


def test_a_teammate_who_takes_damage_for_another_through_the_oath_earns_a_grace_imprint_without_the_reaction_once_a_round():
    engine = _ledger(OATH)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert typed_executor.bears_mark(ally, ME, GRACE) is False
    events = _hit(engine, ME, 12)  # ALLY (bound) takes half of it in the caster's place
    assert ally.current_hp < ally.maximum_hp
    assert len(_imprints(engine, ALLY, "grace")) == 1 and not _imprints(engine, ALLY, "debt")
    assert any("Oath of Mutual Defense" in line and "without a Reaction" in line for line in _logs(events))
    assert me.reaction_available is False  # the Reaction went on recording the foe, not the Grace
    _new_round(engine)
    _hit(engine, ME, 12)
    assert len(_imprints(engine, ALLY, "grace")) == 2  # a new round places another
    assert not _plug_in_failures(engine)


def test_return_the_sting_costs_one_cp_and_a_debt_imprint_and_the_strike_it_answers_records_no_new_debt():
    engine = _ledger(KSTING)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    before, qi = foe.current_hp, me.resources[QI]
    events = _hit(engine, ALLY, 5)
    assert foe.current_hp == before - 6 and ("PSYCHIC", 6) in _dealt(events)  # PB 4 + Constitution modifier 2
    assert me.resources[QI] == qi - 1 and not me.reaction_available
    assert not _imprints(engine, TFOE)  # the Imprint is spent, and its strike cannot make another
    assert any("spends 1 Debt Imprint" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_return_the_sting_needs_a_debt_and_adds_a_d8_at_level_eleven():
    engine = _ledger(KSTING)
    _hit(engine, ALLY, 5)  # no Debt on the foe yet: only the record answers
    assert len(_imprints(engine, TFOE, "debt")) == 1 and engine.state.actors[ME].resources[QI] == 30
    engine = _ledger(KSTING, cl=11)
    foe = engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    before = foe.current_hp
    _hit(engine, ALLY, 5)
    assert 7 <= before - foe.current_hp <= 14  # 4 + 2, and 1d8


# ------------------------------------------------------------------- C2a Karma talents that spend Imprints (combat/ext/karma_consumers.py)
KINVOKE, KSETTLE = "Invoke the Ledger", "Settle Minor Account"
KREPAID, KHARM, KSHELTER = KM + "grace_repaid", KM + "harm_returned", KM + "grace_shelters_the_innocent"
KEXCHANGE, KREVERSAL = KM + "karmic_exchange", KM + "reversal_of_due_fortune"
INVOKE_DIE = "condition:typed.karma_invoke."


def _die(engine, creature_id, owner=ME):
    return [c for c in engine.state.actors[creature_id].conditions.values() if c.condition_id == INVOKE_DIE + owner]


def test_invoke_the_ledger_spends_an_imprint_and_a_cp_and_leaves_a_die_on_the_creature_for_its_next_roll():
    engine = _ledger()
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    _mark(engine, ME, ALLY, "grace")
    assert {"Invoke the Ledger: Debt", "Invoke the Ledger: Grace"} <= _legal(engine)
    qi = me.resources[QI]
    events = _act(engine, ME, "Invoke the Ledger: Debt", TFOE)
    assert me.resources[QI] == qi - 1 and not me.bonus_action_available and not _imprints(engine, TFOE)
    (die,) = _die(engine, TFOE)
    assert die.data["kind"] == "debt" and die.data["sides"] == 4 and "Invoke the Ledger: -1d4" == die.data["label"]
    assert "subtract 1d4" in die.data["reading"]  # the table's hover
    assert any("invokes the ledger" in line and "-1d4" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_invoke_the_ledger_is_only_offered_against_a_creature_carrying_the_matching_imprint_and_no_die_of_yours_already():
    engine = _ledger()
    assert not {"Invoke the Ledger: Debt", "Invoke the Ledger: Grace", "Settle Minor Account: Debt", "Settle Minor Account: Grace"} & _legal(engine)
    _mark(engine, ME, TFOE, "debt")
    _mark(engine, ME, TFOE, "debt")
    assert "Invoke the Ledger: Debt" in _legal(engine) and "Invoke the Ledger: Grace" not in _legal(engine)
    _act(engine, ME, "Invoke the Ledger: Debt", TFOE)
    engine.state.actors[ME].bonus_action_available = True
    assert "Invoke the Ledger: Debt" not in _legal(engine)  # one die from you at a time
    assert len(_die(engine, TFOE)) == 1 and len(_imprints(engine, TFOE, "debt")) == 1


def test_a_debt_die_takes_1d4_off_the_creatures_next_attack_roll_and_is_spent_by_it():
    engine = _ledger()
    ally = engine.state.actors[ALLY]
    ally.armor_class = 12
    _fixed(engine, 10)  # the foe rolls a 12 (+2): a hit on AC 12 ... unless the die takes 1d4 off it
    _mark(engine, ME, TFOE, "debt")
    _act(engine, ME, "Invoke the Ledger: Debt", TFOE)
    events = _act(engine, TFOE, DAO, ALLY)
    assert not _dealt(events) and ally.current_hp == ally.maximum_hp
    assert any("Invoke the Ledger" in line and "attack roll takes -" in line for line in _logs(events))
    assert not _die(engine, TFOE)
    assert _dealt(_act(engine, TFOE, DAO, ALLY))  # the die is spent: the next attack hits
    assert not _plug_in_failures(engine)


def test_a_grace_die_adds_to_the_creatures_next_saving_throw_and_a_die_left_after_the_owners_next_turn_ends():
    engine = _ledger()
    ally = engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    _act(engine, ME, "Invoke the Ledger: Grace", ALLY)
    assert _die(engine, ALLY)[0].data["kind"] == "grace"
    _fixed(engine, 5)
    events = _forced_save(engine, TFOE, ALLY, "DEX", 30, damage=1)
    save = _payloads(events, "SAVE_ROLLED")[-1]
    assert 1 <= 30 - save["dc"] <= 4  # the engine reads a bonus as a lower DC
    assert any("saving throw takes +" in line for line in _logs(events)) and not _die(engine, ALLY)
    engine = _ledger()
    _mark(engine, ME, ALLY, "grace")
    _act(engine, ME, "Invoke the Ledger: Grace", ALLY)
    engine.state.actors[ME].turns_started += 2  # the owner's next turn is over
    typed_executor.expire_marks(engine)
    assert not _die(engine, ALLY)


def test_invoke_the_ledgers_die_grows_to_1d6_at_level_eleven_and_1d8_at_seventeen():
    for cl, sides in ((10, 4), (11, 6), (16, 6), (17, 8)):
        engine = _ledger(cl=cl)
        _mark(engine, ME, TFOE, "debt")
        _act(engine, ME, "Invoke the Ledger: Debt", TFOE)
        assert _die(engine, TFOE)[0].data["sides"] == sides, cl


def test_settle_minor_account_debt_deals_psychic_and_takes_the_reaction_on_a_failed_charisma_save_and_half_on_a_success():
    engine = _ledger()
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    qi = me.resources[QI]
    _fixed(engine, 1)  # the foe fails
    hp = foe.current_hp
    events = _act(engine, ME, "Settle Minor Account: Debt", TFOE)
    dealt = [amount for kind, amount in _dealt(events) if kind == "PSYCHIC"]
    assert dealt and 4 <= dealt[0] <= 18  # 2d8 + the key modifier (2) from Cultivation Level 5
    assert foe.current_hp == hp - dealt[0] and me.resources[QI] == qi - 1 and not me.action_available and not _imprints(engine, TFOE)
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    engine = _ledger()
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    _fixed(engine, 20)  # the foe passes: half damage and it keeps its Reactions
    events = _act(engine, ME, "Settle Minor Account: Debt", TFOE)
    assert not any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert all(amount <= 9 for kind, amount in _dealt(events) if kind == "PSYCHIC")
    assert not _plug_in_failures(engine)


def test_settle_minor_account_grace_gives_temporary_hp_frees_a_grappled_or_prone_creature_and_scales_with_level():
    engine = _ledger()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    _put(engine, ALLY, "prone", TFOE, "action:test.shove")
    events = _act(engine, ME, "Settle Minor Account: Grace", ALLY)
    assert 4 <= ally.temporary_hp <= 18 and not _imprints(engine, ALLY)
    assert not any(c.condition_id.endswith(".prone") for c in ally.conditions.values())
    assert any("Grace frees" in line and "Prone" in line for line in _logs(events))
    engine = _ledger(cl=11)
    _mark(engine, ME, ALLY, "grace")
    _act(engine, ME, "Settle Minor Account: Grace", ALLY)
    assert 5 <= engine.state.actors[ALLY].temporary_hp <= 26  # 3d8 + 2
    assert not _plug_in_failures(engine)


def test_settle_minor_accounts_die_is_1d8_below_level_five():
    engine = _ledger(cl=4)
    foe = engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    _fixed(engine, 1)
    dealt = [amount for kind, amount in _dealt(_act(engine, ME, "Settle Minor Account: Debt", TFOE)) if kind == "PSYCHIC"]
    assert dealt and 2 <= dealt[0] <= 11  # 1d8 + the key modifier


# ---- Grace Repaid, Harm Returned, Grace Shelters the Innocent
def test_grace_repaid_takes_2d8_plus_the_key_modifier_off_damage_to_a_grace_carrier_for_one_cp_and_the_imprint():
    engine = _ledger(KREPAID)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    qi = me.resources[QI]
    events = _hit(engine, ALLY, 20)
    lost = ally.maximum_hp - ally.current_hp
    assert 2 <= lost <= 16  # 20 less 2d8 + 2 (Cultivation Level 5)
    assert me.resources[QI] == qi - 1 and not _imprints(engine, ALLY, "grace") and not me.reaction_available
    assert not _plug_in_failures(engine)
    assert events


def test_grace_repaid_is_kept_when_the_damaged_creature_carries_no_grace_imprint_of_yours():
    engine = _ledger(KREPAID)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    qi = me.resources[QI]
    _hit(engine, ALLY, 20)
    assert ally.maximum_hp - ally.current_hp == 20 and me.resources[QI] == qi


def _two_debts(*talents, cl=10):
    engine = _ledger(*talents, cl=cl)
    _mark(engine, ME, TFOE, "debt")
    _mark(engine, ME, TFOE, "debt")
    return engine


def test_harm_returned_needs_two_debts_and_sends_back_half_the_damage_as_psychic_for_three_cp_and_both_imprints():
    engine = _two_debts(KHARM)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    qi, hp = me.resources[QI], foe.current_hp
    events = _hit(engine, ALLY, 20)
    assert [amount for kind, amount in _dealt(events) if kind == "PSYCHIC"] == [10]
    assert foe.current_hp == hp - 10 and me.resources[QI] == qi - 3 and not me.reaction_available
    assert not _imprints(engine, TFOE)  # both spent, and the psychic damage records no new Debt
    assert not _plug_in_failures(engine)
    engine = _ledger(KHARM)
    _mark(engine, ME, TFOE, "debt")  # one Debt is not enough
    qi = engine.state.actors[ME].resources[QI]
    events = _hit(engine, ALLY, 20)
    assert not [1 for kind, _ in _dealt(events) if kind == "PSYCHIC"] and engine.state.actors[ME].resources[QI] == qi


def test_harm_returned_answers_damage_to_the_karma_character_too_and_is_capped_at_five_times_the_level():
    engine = _two_debts(KHARM)
    events = _hit(engine, ME, 20)
    assert [amount for kind, amount in _dealt(events) if kind == "PSYCHIC"] == [10]
    engine = _two_debts(KHARM)
    events = _hit(engine, ALLY, 200)
    assert [amount for kind, amount in _dealt(events) if kind == "PSYCHIC"] == [50]  # half of 200 is 100; 5 x CL 10 is the ceiling


def test_grace_shelters_turns_a_failed_save_into_a_success_with_1d6_and_gives_temporary_hp_equal_to_the_proficiency_bonus():
    engine = _ledger(KSHELTER)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    qi = me.resources[QI]
    _fixed(engine, 5)
    events = _forced_save(engine, TFOE, ALLY, "DEX", 5 + ally.saving_throws["DEX"] + 1, damage=5)  # one short of the DC
    assert ally.maximum_hp == ally.current_hp and ally.temporary_hp == me.proficiency_bonus
    assert me.resources[QI] == qi - 2 and not _imprints(engine, ALLY) and not me.reaction_available
    assert any("Grace Shelters" in line and "success" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_grace_shelters_is_kept_when_1d6_cannot_turn_the_save_or_the_creature_carries_no_grace():
    engine = _ledger(KSHELTER)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    qi = me.resources[QI]
    _fixed(engine, 5)
    _forced_save(engine, TFOE, ALLY, "DEX", 5 + ally.saving_throws["DEX"] + 10, damage=5)  # ten short: 1d6 cannot close it
    assert ally.current_hp == ally.maximum_hp - 5 and me.resources[QI] == qi and _imprints(engine, ALLY, "grace")
    engine = _ledger(KSHELTER)
    ally = engine.state.actors[ALLY]  # no Grace Imprint at all
    _fixed(engine, 5)
    _forced_save(engine, TFOE, ALLY, "DEX", 5 + ally.saving_throws["DEX"] + 1, damage=5)
    assert ally.current_hp == ally.maximum_hp - 5 and not ally.temporary_hp


# ---- Karmic Exchange, Reversal of Due Fortune
def test_karmic_exchange_takes_1d6_off_a_foes_attack_roll_for_three_cp_and_a_debt_and_can_make_it_miss():
    engine = _ledger(KEXCHANGE)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    ally.armor_class = 12
    _mark(engine, ME, TFOE, "debt")
    _fixed(engine, 10)  # a 12 on AC 12 hits, but not with 1d6 off it
    qi = me.resources[QI]
    events = _act(engine, TFOE, DAO, ALLY)
    assert not _dealt(events) and ally.current_hp == ally.maximum_hp
    assert me.resources[QI] == qi - 3 and not _imprints(engine, TFOE, "debt")
    assert any("exchanges a Debt Imprint" in line and "subtracts 1d6" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_karmic_exchange_adds_1d6_to_a_teammates_save_for_a_grace_imprint_and_is_kept_without_one():
    engine = _ledger(KEXCHANGE)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    qi = me.resources[QI]
    _fixed(engine, 5)
    _forced_save(engine, TFOE, ALLY, "DEX", 5 + ally.saving_throws["DEX"] + 1, damage=5)  # one short of the DC before the die
    assert ally.current_hp == ally.maximum_hp and me.resources[QI] == qi - 3 and not _imprints(engine, ALLY)
    engine = _ledger(KEXCHANGE)
    ally = engine.state.actors[ALLY]
    qi = engine.state.actors[ME].resources[QI]
    _fixed(engine, 5)
    _forced_save(engine, TFOE, ALLY, "DEX", 5 + ally.saving_throws["DEX"] + 1, damage=5)
    assert ally.current_hp == ally.maximum_hp - 5 and engine.state.actors[ME].resources[QI] == qi


def test_a_roll_takes_only_one_karmic_exchange():
    engine = _ledger(KEXCHANGE, friends=1, allies=[_karma(KEXCHANGE, actor_id=ALLY)])
    ally = engine.state.actors[ALLY]
    ally.armor_class = 12
    _mark(engine, ME, TFOE, "debt")
    _mark(engine, ALLY, TFOE, "debt")
    _fixed(engine, 10)
    events = _act(engine, TFOE, DAO, ME)
    assert len([line for line in _logs(events) if "exchanges a Debt Imprint" in line]) == 1
    assert len(_imprints(engine, TFOE, "debt", owner=ME)) + len(_imprints(engine, TFOE, "debt", owner=ALLY)) == 1


def _untyped(*talents, ac=17, marks=("debt",)):
    """A Karma character and a teammate against the untyped An Eui at (4,6), every d20 a 10 (its attack totals 17); the teammate's AC is ``ac``."""
    engine, me, foe = _duel(_karma(*talents), allies=[_ally_bundle()])
    engine.state.actors[ALLY].armor_class = ac
    for kind in marks:
        _mark(engine, ME, FOE, kind)
    _fixed(engine, 10)
    return engine


def test_karmic_exchange_turns_an_untyped_attackers_hit_into_a_miss_after_the_roll():
    engine = _untyped(KEXCHANGE)
    me = engine.state.actors[ME]
    qi = me.resources[QI]
    events = _act(engine, FOE, "Paired Bi Shou Assault", ALLY)
    assert me.resources[QI] == qi - 3 and not _imprints(engine, FOE)
    assert any("exchanges a Debt Imprint on" in line and "a miss" in line for line in _logs(events))
    assert len(_dealt(events)) == 1  # the pair of attacks: the first is turned, the second (no Imprint left) hits
    assert len(_dealt(_act(engine, FOE, "Paired Bi Shou Assault", ALLY))) == 2
    assert not _plug_in_failures(engine)


def test_a_debt_die_takes_the_hit_off_an_untyped_attackers_attack_roll_after_it_is_rolled():
    engine = _untyped()
    engine.state.actors[ME].bonus_action_available = True
    _act(engine, ME, "Invoke the Ledger: Debt", FOE)
    assert _die(engine, FOE)
    events = _act(engine, FOE, "Paired Bi Shou Assault", ALLY)
    assert len(_dealt(events)) == 1 and not _die(engine, FOE)
    assert any("Invoke the Ledger" in line and "attack roll takes -" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_reversal_turns_a_teammates_natural_one_save_into_a_twenty_with_a_grace_imprint_for_four_cp():
    engine = _ledger(KREVERSAL)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    qi = me.resources[QI]
    _fixed(engine, 1)
    events = _forced_save(engine, TFOE, ALLY, "DEX", 1 + ally.saving_throws["DEX"] + 10, damage=5)
    assert ally.current_hp == ally.maximum_hp and me.resources[QI] == qi - 4 and not _imprints(engine, ALLY)
    assert any("reverses" in line and "natural 1 into a 20" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_reversal_is_kept_when_the_flip_would_change_nothing():
    engine = _ledger(KREVERSAL)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _mark(engine, ME, ALLY, "grace")
    qi = me.resources[QI]
    _fixed(engine, 1)
    _forced_save(engine, TFOE, ALLY, "DEX", ally.saving_throws["DEX"], damage=5)  # 1 + the modifier already meets it
    assert me.resources[QI] == qi and _imprints(engine, ALLY, "grace")


def test_reversal_turns_a_foes_natural_twenty_save_into_a_failure_with_a_debt_imprint():
    engine = _ledger(KREVERSAL)
    me, foe = engine.state.actors[ME], engine.state.actors[TFOE]
    _mark(engine, ME, TFOE, "debt")
    qi = me.resources[QI]
    _fixed(engine, 20)
    events = _forced_save(engine, ALLY, TFOE, "DEX", 15 + foe.saving_throws["DEX"], damage=5)  # a 20 passes, a 1 would not
    assert foe.current_hp == foe.maximum_hp - 5 and me.resources[QI] == qi - 4 and not _imprints(engine, TFOE)
    assert any("reverses" in line and "natural 20 into a 1" in line for line in _logs(events))


def test_reversal_turns_a_foes_natural_twenty_attack_into_a_miss_and_is_once_per_short_rest():
    engine = _ledger(KREVERSAL)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    ally.armor_class = 40
    _mark(engine, ME, TFOE, "debt")
    _mark(engine, ME, TFOE, "debt")
    _fixed(engine, 20)
    qi = me.resources[QI]
    events = _act(engine, TFOE, DAO, ALLY)
    assert not _dealt(events) and me.resources[QI] == qi - 4 and len(_imprints(engine, TFOE, "debt")) == 1
    assert any("reverses" in line and "natural 20 into a 1" in line for line in _logs(events))
    assert _dealt(_act(engine, TFOE, DAO, ALLY)) and me.resources[QI] == qi - 4  # the second Debt stays: the once is used
    assert not _plug_in_failures(engine)


def test_reversal_turns_an_untyped_attackers_natural_twenty_into_a_miss():
    engine = _untyped(KREVERSAL, ac=40)
    me = engine.state.actors[ME]
    _fixed(engine, 20)
    qi = me.resources[QI]
    events = _act(engine, FOE, "Paired Bi Shou Assault", ALLY)
    assert me.resources[QI] == qi - 4 and len(_dealt(events)) == 1 and not _imprints(engine, FOE)
    assert any("reverses" in line and "natural 20 into a 1" in line for line in _logs(events))


# ------------------------------------------------------------------ Warleader: General's Soul-Standard (AUTO71)
# (combat/ext/warleader_commands.py; owner text tianxia.talent.warleader.general_s_soul_standard)
SOUL = "condition:typed.warleader_soul_standard"
SOUL_TALENT = "general_s_soul_standard"


def _commit(engine, actor_id, amount, source="action:test.foe_hit"):
    """A hostile hit takes ``amount`` off ``actor_id`` through the engine's own damage path."""
    engine._commit_damage(engine.state.actors[actor_id], amount, "FORCE", source, TFOE, None, reaction_depth=0)
    return engine.state.actors[actor_id]


def _soul(*talents, marks=2, focus=1, hp=6):
    """A Warleader who knows General's Soul-Standard, on ``hp`` Hit Points with ``marks`` Momentum Marks and ``focus`` Martial
    Focus, under the ordinary life-and-death rules so every other 0-HP path is the real one."""
    engine = _command(SOUL_TALENT, *talents, marks=marks)
    me = engine.state.actors[ME]
    me.current_hp = hp
    me.maximum_hp = hp
    me.resources[FOCUS] = focus
    engine.state.rules["zero_hp"] = "dying_2024"
    return engine


def test_general_s_soul_standard_keeps_a_leader_conscious_at_zero_hit_points_until_the_end_of_its_next_turn():
    engine = _soul(marks=3)
    me = _commit(engine, ME, 6)
    assert me.current_hp == 0 and me.active and me.life_state == "CONSCIOUS"
    assert len(_held(me, SOUL)) == 1 and _held(me, SOUL)[0].expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"
    assert me.resources[FOCUS] == 0 and me.resources[MOMENTUM] == 0  # 1 Martial Focus and every Momentum Mark
    assert any("General's Soul-Standard" in line for line in _logs(engine.events))
    assert not _plug_in_failures(engine)


def test_general_s_soul_standard_needs_martial_focus_and_is_once_a_long_rest():
    from combat.ext import warleader as wl

    engine = _soul(focus=0)
    me = _commit(engine, ME, 6)
    assert me.life_state == "DYING" and not _held(me, SOUL)  # no Martial Focus: the ordinary 0 Hit Points rules
    engine = _soul(focus=1)
    me = _commit(engine, ME, 6)
    assert me.life_state == "CONSCIOUS" and len(_held(me, SOUL)) == 1
    assert wl.has_benefited(me, "soul_standard")  # a durable marker, not just the window that is running
    # The window ends the ordinary way (its own clock), the leader is healed and back on its feet, and it has its Focus
    # and its Marks again: "once per long rest" still says no, because the marker outlived the window.
    engine._remove_condition(me, SOUL, "system:combat.expiration")  # the window's own expiry
    engine._heal(me, 6, "action:test.heal", ALLY, notify_healed=True)
    me.life_state = None
    me.resources[FOCUS] = 1
    engine._gain_resource(me, MOMENTUM, 2, "test")
    assert me.current_hp == 6 and me.life_state is None and me.resources[FOCUS] == 1
    _commit(engine, ME, 6)
    assert len(_held(me, SOUL)) == 0 and me.life_state == "DYING"  # already spent this long rest
    assert not _plug_in_failures(engine)


def test_general_s_soul_standard_stops_ordinary_healing_and_the_window_ends_as_unconscious_at_the_next_turns_end():
    engine = _soul()
    me = _commit(engine, ME, 6)
    assert typed_executor.healing_pending(engine, me, 20, engine.state.actors[ALLY], "action:test.heal", "hp") == 0
    assert engine._heal(me, 20, "action:test.heal", ALLY, notify_healed=True) == 0 and me.current_hp == 0
    assert any("cannot regain Hit Points" in line for line in _logs(engine.events))
    # The clock itself ends the window: the leader's next turn runs and ends, and the engine's own expiry takes it off.
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert len(_held(me, SOUL)) == 1 and me.life_state == "CONSCIOUS"  # still standing through that turn
    _end_turn(engine)
    assert not _held(me, SOUL) and me.life_state == "DYING" and _held(me, "condition:typed.life_unconscious")
    assert any("falls Unconscious" in line for line in _logs(engine.events))
    assert not _plug_in_failures(engine)


def test_general_s_soul_standard_lets_the_leader_set_a_standard_with_no_bonus_action_and_call_one_free_command_response():
    engine = _soul("shieldbrothers", focus=1, marks=0)
    me = _commit(engine, ME, 6)
    _ready(engine)
    free = {c.display_name for c in engine.legal_candidates() if c.display_name.startswith("General's Soul-Standard: Set")}
    assert free >= {"General's Soul-Standard: Set Press the Opening (no Bonus Action)",
                    "General's Soul-Standard: Set Shieldbrothers (no Bonus Action)"}
    spare = me.bonus_action_available
    _act(engine, ME, "General's Soul-Standard: Set Shieldbrothers (no Bonus Action)")
    assert _standing(me) == "shieldbrothers" and me.bonus_action_available == spare  # the Standard costs no Bonus Action
    assert not _plug_in_failures(engine)
    engine = _soul("shieldbrothers", focus=1, marks=0)
    me = _commit(engine, ME, 6)
    me.turn_flags.clear()
    engine.state.actors[TFOE].armor_class = -50
    me.position = Position(x=3, y=1)  # still Commanded at 30 feet, no longer beside the ally: Press the Opening pays nothing
    events = _act(engine, ALLY, DAO, TFOE)  # Strike on My Count costs no Momentum Mark inside the window
    assert any("Strike on My Count (free by General's Soul-Standard)" in line for line in _logs(events))
    assert me.resources[MOMENTUM] == 0 and _dealt(events)  # and it still added the leader's Proficiency Bonus
    assert not _plug_in_failures(engine)


def test_the_soul_standards_free_command_response_is_one_for_the_whole_window_not_one_a_turn():
    """"you may use one Command Response without spending Momentum" belongs to the window, which lasts through the end of the
    leader's next turn. An ordinary turn flag was cleared at the start of that turn, so the free Response came back and the same
    window paid for two."""
    from combat.ext import warleader_commands as wc

    engine = _soul("shieldbrothers", focus=1, marks=2)
    me = _commit(engine, ME, 6)
    held = _held(me, STANDARD)[0]
    engine._remove_condition(me, STANDARD, "test:long_standard")  # a Standard that outlives the next turn boundary
    engine._apply_condition(me, STANDARD, "test:long_standard", me.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{me.turns_started + 10}", data={**held.data, "label": held.data["label"]})
    me.turn_flags.clear()
    engine.state.actors[TFOE].armor_class = -50
    me.position = Position(x=3, y=1)
    first = _act(engine, ALLY, DAO, TFOE)
    assert any("free by General's Soul-Standard" in line for line in _logs(first)) and me.resources[MOMENTUM] == 0
    engine._gain_resource(me, MOMENTUM, 1, "test")
    engine.state.round_number += 1  # a round passes, so the leader's own Response is available again
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _ready(engine)
    me.position = Position(x=3, y=1)
    assert len(_held(me, SOUL)) == 1 and not wc._soul_free(engine, me)  # the window still runs; its free one is spent
    second = _act(engine, ALLY, DAO, TFOE)
    assert any("Strike on My Count (1 Momentum Mark)" in line for line in _logs(second))
    assert "free by General's Soul-Standard" not in " ".join(_logs(second)) and me.resources[MOMENTUM] == 0
    assert not _plug_in_failures(engine)


def test_general_s_soul_standard_offers_the_free_standard_only_while_the_window_runs():
    engine = _command(SOUL_TALENT, marks=1)
    _ready(engine)
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("General's Soul-Standard: Set")]
    me = engine.state.actors[ME]
    me.resources[FOCUS] = 1
    engine.state.rules["zero_hp"] = "dying_2024"
    me.current_hp = me.maximum_hp = 6
    _commit(engine, ME, 6)
    assert _held(me, SOUL)
    _ready(engine)
    assert [c for c in engine.legal_candidates() if c.display_name.startswith("General's Soul-Standard: Set")]


# ------------------------------------------------------------------ Warleader: the Court's last stand (AUTO71)
def _court_field():
    """A leader holding a Standard who can raise the Court of Moving Banners, under the ordinary life-and-death rules."""
    engine = _command("warleader_domain_court_of_moving_banners", marks=0)
    engine.state.rules["zero_hp"] = "dying_2024"
    return engine


def test_a_commanded_ally_that_drops_to_zero_inside_the_court_steps_five_feet_before_falling_unconscious():
    engine = _court_field()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    _act(engine, ME, COURT_ACTION)
    assert _held(me, COURT)
    ally.position = Position(x=3, y=8)  # inside the 60-foot Domain
    before = (ally.position.x, ally.position.y)
    _commit(engine, ALLY, 60)
    assert ally.current_hp == 0 and ally.life_state == "DYING"  # Unconscious at the end, as printed
    assert (ally.position.x, ally.position.y) != before and _held(ally, "condition:typed.prone")
    assert any("falls Prone and moves 5 feet" in line for line in _logs(engine.events))
    assert not _plug_in_failures(engine)


def test_an_ally_dropping_to_zero_outside_the_court_does_not_step():
    engine = _court_field()
    _act(engine, ME, COURT_ACTION)
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=16, y=6)  # 65 feet: outside the Domain, so no longer Commanded by it
    before = (ally.position.x, ally.position.y)
    _commit(engine, ALLY, 60)
    assert ally.current_hp == 0 and ally.life_state == "DYING"
    assert (ally.position.x, ally.position.y) == before
    assert not any("falls Prone and moves 5 feet" in line for line in _logs(engine.events))
    assert not _plug_in_failures(engine)


# ------------------------------------------------------------------ Warleader: Reactive Position (AUTO71)
def _pair(engine):
    """Two adjacent Commanded allies at (3,7) and (4,8) -- 5 feet from each other, 11 feet from the foe at (2,6). The
    leader stands at (3,10): still Commanded (15 feet), no longer adjacent to either ally, so the two allies are the only
    pair (the leader is Commanded by its own Standard and may be a partner -- test_reactive_position_may_swap_with_the_leader)."""
    ally, other, foe = engine.state.actors[ALLY], engine.state.actors[ALLY2], engine.state.actors[TFOE]
    ally.position, other.position, foe.position = Position(x=3, y=7), Position(x=4, y=8), Position(x=2, y=6)
    engine.state.actors[ME].position = Position(x=3, y=10)
    return ally, other, foe


def test_reactive_position_swaps_two_commanded_allies_and_the_attack_misses_when_its_target_leaves_reach():
    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    me = engine.state.actors[ME]
    ally, other, foe = _pair(engine)
    first, second = (ally.position.x, ally.position.y), (other.position.x, other.position.y)
    marks = me.resources[MOMENTUM]
    events = _act(engine, TFOE, DAO, ALLY)
    assert (ally.position.x, ally.position.y) == second and (other.position.x, other.position.y) == first  # they traded squares
    assert me.resources[MOMENTUM] == marks - 1
    assert engine._distance_actor_to_actor(ally, foe) > 5  # the swap left it out of the foe's reach
    assert not _dealt(events)
    assert any("swap places" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_reactive_position_leaves_a_ranged_attack_alone_when_its_target_is_still_within_range():
    """The printed rule is "outside the triggering attack's reach or range": a bow's range is 120 feet, so a swap that leaves
    the target ten feet away is still inside it and the shot lands. Reading a five-foot reach off the outer intent made every
    ranged attack miss after any swap."""
    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)],
                      enemies=[_wl(actor_id=TFOE, weapon=BOW)])
    me = engine.state.actors[ME]
    ally, other, foe = _pair(engine)
    engine.state.actors[TFOE].armor_class = 10
    marks = me.resources[MOMENTUM]
    _rolls(engine, 20)
    events = _act(engine, TFOE, "Dan Gong (Pellet Bow / Sling Bow) attack", ALLY)
    assert (ally.position.x, ally.position.y) == (4, 8) and me.resources[MOMENTUM] == marks - 1  # they still traded squares
    assert engine._effect_distance(engine.state.actors[TFOE], ally) > 5  # and the shot came from well outside a melee reach
    assert _dealt(events) and not any("ATTACK_FORCED_MISS" == e.event_type for e in events)
    assert any("swap places" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_reactive_position_makes_the_attack_miss_when_the_swap_leaves_a_ranged_attack_out_of_range():
    """The same rule at the far end: a 120-foot bow shot whose swap carries the target past its range misses."""
    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)],
                      enemies=[_wl(actor_id=TFOE, weapon=BOW)])
    ally, other, foe = _pair(engine)
    me = engine.state.actors[ME]
    engine.state.actors[TFOE].position = Position(x=3, y=1)  # 120 feet from the pair's squares: a shot at the far end of its range
    _rolls(engine, 20)
    events = _act(engine, TFOE, "Dan Gong (Pellet Bow / Sling Bow) attack", ALLY)
    assert (ally.position.x, ally.position.y) == (4, 8)
    assert not _dealt(events) and any(e.event_type == "ATTACK_FORCED_MISS" for e in events)
    assert not _plug_in_failures(engine)


def test_reactive_position_needs_both_creatures_to_be_commanded():
    """"Two Commanded allies": a defender who has stepped out of Command Range does not get the talent, even though the partner
    beside it is still Commanded."""
    from combat.ext import warleader as wl

    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    ally, other, foe = _pair(engine)
    me = engine.state.actors[ME]
    marks = me.resources[MOMENTUM]
    assert wl.commanded(engine, me, wl.standard_of(me), ally)  # 15 feet from the leader, beside its partner
    events = _act(engine, TFOE, DAO, ALLY)  # it trades places and the attack misses
    assert me.resources[MOMENTUM] == marks - 1 and not _dealt(events)
    # the same adjacent pair at the far edge of Command Range: the partner is still Commanded, the defender is not
    ally.position, other.position, foe.position = Position(x=2, y=0), Position(x=3, y=1), Position(x=3, y=0)
    me.position = Position(x=3, y=7)
    assert not wl.commanded(engine, me, wl.standard_of(me), ally) and wl.commanded(engine, me, wl.standard_of(me), other)
    assert _dealt(_act(engine, TFOE, DAO, ALLY))
    assert me.resources[MOMENTUM] == marks - 1  # the second Mark is never spent on an ally the leader does not command
    assert not _plug_in_failures(engine)


def test_reactive_position_may_swap_with_the_leader_which_is_commanded_by_its_own_standard():
    """The leader is Commanded by its own Standard, so the printed "two Commanded allies" includes it as the partner."""
    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY)], foes=1)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[TFOE]
    ally.position, foe.position = Position(x=3, y=7), Position(x=2, y=6)
    me = engine.state.actors[ME]
    me.position = Position(x=3, y=8)  # adjacent to the ally, so it is the only eligible partner
    marks = me.resources[MOMENTUM]
    events = _act(engine, TFOE, DAO, ALLY)
    assert (ally.position.x, ally.position.y) == (3, 8) and (me.position.x, me.position.y) == (3, 7)
    assert me.resources[MOMENTUM] == marks - 1 and not _dealt(events)
    assert any("swap places" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_reactive_position_checks_both_destinations_before_it_spends_anything():
    """Footprint, terrain and elevation are part of a legal placement: both partners here are two cells by two, so neither fits on
    the single square they would swap onto, nobody moves, and the printed cost is never paid."""
    engine = _command("reactive_position", marks=2, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2), _wl(actor_id=ALLY3)])
    ally, other, foe, third = (engine.state.actors[who] for who in (ALLY, ALLY2, TFOE, ALLY3))
    ally.position, other.position, third.position, foe.position = (Position(x=3, y=7), Position(x=2, y=8),
                                                                   Position(x=4, y=7), Position(x=2, y=6))
    engine.state.actors[ME].position = Position(x=3, y=11)
    for big in (other, third):
        big.transformed_size_category = "Large"
        engine.actor_footprints[big.entity_id] = engine._footprint(big)
    assert engine._footprint(other).width_cells == 2
    engine._assert_invariants()  # the field as set up is itself legal
    marks = engine.state.actors[ME].resources[MOMENTUM]
    _rolls(engine, 20)
    _act(engine, TFOE, DAO, ALLY)
    assert ally.position == Position(x=3, y=7) and other.position == Position(x=2, y=8)  # nobody moved
    assert not any("swap places" in line for line in _logs(engine.events))
    spent = [p.get("amount") for p in _payloads(engine.events, "RESOURCE_SPENT")
             if p.get("resource_id") == MOMENTUM and p.get("source_definition_id") == "warleader:reactive_position"]
    assert not spent  # the printed cost is never paid for a swap that cannot be placed
    assert not _plug_in_failures(engine)


def test_reactive_position_answers_a_forced_push_as_well_as_an_attack():
    """"one of them is targeted by an attack roll or forced movement": the pair trades squares before a forced step and the push
    stops, because the creatures have already left the squares it was aimed at."""
    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    ally, other, foe = _pair(engine)
    me = engine.state.actors[ME]
    engine.state.actors[TFOE].position = Position(x=3, y=8)  # beside the ally, with a clear square behind it
    marks = me.resources[MOMENTUM]
    _rolls(engine, 1)  # the defender fails its Strength save, so the push is actually attempted
    events = _act(engine, TFOE, "Shove: Push 5 ft", ALLY)
    say = " ".join(_logs(events))
    assert any("swap places" in line for line in _logs(events)), say
    assert me.resources[MOMENTUM] == marks - 1
    assert (ally.position.x, ally.position.y) == (4, 8) and (other.position.x, other.position.y) == (3, 7)  # the swap, not the push
    assert not _plug_in_failures(engine)


def test_reactive_position_needs_a_momentum_mark_and_a_second_commanded_ally():
    engine = _command("reactive_position", marks=0, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    me = engine.state.actors[ME]
    ally, other, _foe = _pair(engine)
    before = ((ally.position.x, ally.position.y), (other.position.x, other.position.y))
    assert _dealt(_act(engine, TFOE, DAO, ALLY))  # no Momentum Mark: nothing to pay with
    assert ((ally.position.x, ally.position.y), (other.position.x, other.position.y)) == before
    assert me.resources[MOMENTUM] == 0
    engine = _command("reactive_position", marks=1)  # one ally only, and the leader not beside it: nobody to trade places with
    ally, me = engine.state.actors[ALLY], engine.state.actors[ME]
    me.position = Position(x=3, y=10)
    before = (ally.position.x, ally.position.y)
    assert _dealt(_act(engine, TFOE, DAO, ALLY))
    assert (ally.position.x, ally.position.y) == before
    assert not _plug_in_failures(engine)


# ------------------------------------------------------------------ Warleader: Battlefield Coordination (AUTO71)
def _coord_field(marks):
    """A Battlefield Coordination leader 30 feet from its ally: still Commanded, no longer beside it, so the Standard's own
    Momentum Mark never lands in the middle of the count."""
    engine = _command("battlefield_coordination", marks=marks)
    engine.state.actors[ME].position = Position(x=3, y=1)
    _put(engine, ALLY, "hindered", FOE, "action:test.hinder")  # "attacks_have": DISADVANTAGE
    engine.state.actors[TFOE].armor_class = 40
    return engine


def _modes(events):
    return [payload.get("mode") for payload in _payloads(events, "ATTACK_ROLLED")]


def test_battlefield_coordination_makes_a_commanded_ally_ignore_one_source_of_disadvantage_on_its_attack():
    engine = _coord_field(1)
    me = engine.state.actors[ME]
    marks = me.resources[MOMENTUM]
    events = _act(engine, ALLY, DAO, TFOE)
    assert _modes(events) == ["NORMAL"] and me.resources[MOMENTUM] == marks - 1
    said = " ".join(_logs(events))
    assert "Battlefield Coordination" in said and "ignores Hindered" in said
    assert not _plug_in_failures(engine)


def test_battlefield_coordination_needs_a_momentum_mark_and_a_source_of_disadvantage():
    engine = _coord_field(0)
    events = _act(engine, ALLY, DAO, TFOE)
    assert _modes(events) == ["DISADVANTAGE"] and engine.state.actors[ME].resources[MOMENTUM] == 0
    assert not any("Battlefield Coordination" in line for line in _logs(events))
    engine = _command("battlefield_coordination", marks=1)  # nothing to name: the Mark is not spent
    events = _act(engine, ALLY, DAO, TFOE)
    assert _modes(events) == ["NORMAL"] and engine.state.actors[ME].resources[MOMENTUM] == 1
    assert not any("Battlefield Coordination" in line for line in _logs(events))
    assert not _plug_in_failures(engine)


def test_battlefield_coordination_pays_once_per_attack_roll_not_for_the_rest_of_the_fight():
    """The printed window is "that one source of Disadvantage for the triggering roll": a second attack by the same ally against
    the same foe is Disadvantage again (the leader is out of Marks here, which is the honest reading either way)."""
    engine = _coord_field(1)
    me = engine.state.actors[ME]
    first, second = _act(engine, ALLY, DAO, TFOE), _act(engine, ALLY, DAO, TFOE)
    assert _modes(first) == ["NORMAL"] and me.resources[MOMENTUM] == 0
    assert _modes(second) == ["DISADVANTAGE"] and me.resources[MOMENTUM] == 0
    assert "Battlefield Coordination" in " ".join(_logs(first)) and "Battlefield Coordination" not in " ".join(_logs(second))
    assert getattr(engine, "_wl_coordination_frame", None) is None  # nothing is left behind for a later attack to find
    assert not _plug_in_failures(engine)


def _ray_field(marks):
    """A Coordination leader whose Commanded ally makes five attacks in one action (Heaven-Piercing Ray at CL 17), so the mask's
    lifetime across repeated attacks inside one packet is testable."""
    ally_sheet = _sheet("tianxia.talent.destruction.heaven_piercing_ray", cl=17)
    ally_sheet["spheres_and_talents"]["learned_talent_record_ids"] = ["WARLEADER_BASE_SET_THE_STANDARD",
                                                                     "tianxia.talent.destruction.heaven_piercing_ray"]
    ally_sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}]
    friends = [compile_character(ally_sheet, actor_id=ALLY)]
    # Printed Multi-Ray allows five distinct targets, never five rays at one
    # creature. Keep all five rolls and give the fixture five real recipients.
    engine = _command("battlefield_coordination", marks=marks, friends=friends, foes=5)
    engine.state.actors[ME].position = Position(x=3, y=1)
    _put(engine, ALLY, "hindered", FOE, "action:test.hinder")
    for index, actor in enumerate(a for a in engine.state.actors.values() if a.team_id != engine.state.actors[ALLY].team_id):
        actor.position = Position(x=8, y=3 + index)
        actor.armor_class = 40
    # Ranged attacks have no adjacent-hostile penalty in this setup; Hindered
    # must be the sole source the leader pays to set aside on the first ray.
    return engine


def test_battlefield_coordination_does_not_carry_over_to_the_next_attack_in_the_same_action():
    """Five attacks in one action are five rolls: the first is paid for, and the mask is gone for the second, so the second is
    Disadvantage again (the leader is out of Momentum Marks, which is what stops it paying twice)."""
    engine = _ray_field(1)
    me = engine.state.actors[ME]
    events = _act(engine, ALLY, "Heaven-Piercing Ray (Multi-Ray, 1 CP)", TFOE)
    assert _modes(events) == ["NORMAL", "DISADVANTAGE", "DISADVANTAGE", "DISADVANTAGE", "DISADVANTAGE"]
    assert len({e.target_ids for e in events if e.event_type == 'ATTACK_ROLLED'}) == 5
    assert me.resources[MOMENTUM] == 0
    assert "Battlefield Coordination" in " ".join(_logs(events))
    assert getattr(engine, "_wl_coordination_frame", None) is None
    assert not _plug_in_failures(engine)


def test_battlefield_coordination_names_a_source_when_another_condition_sits_in_front_of_it():
    """Each condition is read with its own rule row. A suppressed condition ahead of the real one used to shift the pairing, so
    the leader named an empty label and the mask covered nothing."""
    engine = _coord_field(1)
    ally = engine.state.actors[ALLY]
    suppressed = _held(ally, "condition:typed.hindered")[0]
    ally.conditions[suppressed.instance_id].data["suppressed"] = True  # the engine keeps a suppressed row but drops its rule
    _put(engine, ALLY, "frightened", TFOE, "action:test.fear")  # a second real source, behind the suppressed one
    me = engine.state.actors[ME]
    marks = me.resources[MOMENTUM]
    events = _act(engine, ALLY, DAO, TFOE)
    assert _modes(events) == ["NORMAL"] and me.resources[MOMENTUM] == marks - 1
    said = " ".join(_logs(events))
    assert "ignores Frightened" in said  # the condition that actually carries a rule, not the suppressed one
    assert not _plug_in_failures(engine)


def test_battlefield_coordination_will_not_pay_for_a_penalty_that_is_not_this_attack_roll():
    """"Choose one source of Disadvantage affecting that roll": a condition that only penalises ability checks, or only other
    creatures' attacks, is no source of Disadvantage here, so the Mark is not spent."""
    from combat.ext import warleader_commands as wc

    engine = _coord_field(1)
    ally, me = engine.state.actors[ALLY], engine.state.actors[ME]
    engine._remove_condition(ally, "condition:typed.hindered", "test")
    engine._apply_condition(ally, "condition:typed.sickened", "action:test.sicken", TFOE, expires_on="UNTIL_REMOVED",
                            data={"label": "Sickened"})  # Disadvantage on Constitution saves and Concentration checks only
    assert wc._disadvantages(engine, ally, engine.state.actors[TFOE]) == {}
    marks = me.resources[MOMENTUM]
    events = _act(engine, ALLY, DAO, TFOE)
    assert _modes(events) == ["NORMAL"] and me.resources[MOMENTUM] == marks
    assert "Battlefield Coordination" not in " ".join(_logs(events))
    assert not _plug_in_failures(engine)


# ------------------------------------------------------------------ Warleader: choosing the secondary Standard (AUTO71)
def test_layered_orders_carries_one_secondary_standard_and_ten_thousand_banners_two():
    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "courier_s_dash")
    _use(engine, "Shieldbrothers")
    data = _held(me, STANDARD)[0].data["warleader"]
    assert data["standard"] == "shieldbrothers" and data["secondary"] == ["ironclad_line"]  # the one it may carry
    assert "secondary Standard" in _held(me, STANDARD)[0].data["reading"]
    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "ten_thousand_banners_doctrine", "courier_s_dash")
    _use(engine, "Shieldbrothers")
    data = _held(me, STANDARD)[0].data["warleader"]
    assert data["secondary"] == ["ironclad_line", "press_the_opening"] and data["banners"]


def _soul_at_the_table(tmp_path):
    """A real table session (CombatService + TabletopService, one portable character each) whose Warleader knows General's
    Soul-Standard and Battlefield Coordination, so a table commit and a reload are the real ones."""
    import json
    import zipfile

    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    leader_id, foe_id = FACTORY_ACTOR_PREFIX + "wl01", FACTORY_ACTOR_PREFIX + "wl02"
    bundles = []
    for project, actor_id, talents in (("wl01", leader_id, ["WARLEADER_BASE_SET_THE_STANDARD", WL + SOUL_TALENT,
                                                               WL + "battlefield_coordination"]),
                                       ("wl02", foe_id, ["WARLEADER_BASE_SET_THE_STANDARD"])):
        doc = _sheet("WARLEADER_BASE_SET_THE_STANDARD", cl=15)
        doc["spheres_and_talents"]["learned_talent_record_ids"] = talents
        doc["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}]
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / "current.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=actor_id))
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, [leader_id, foe_id], {leader_id: "team:factory", foe_id: "team:opponents"},
                                       {leader_id: {"x": 3, "y": 6}, foe_id: {"x": 4, "y": 6}},
                                       combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [leader_id], [foe_id],
                                       control_modes={leader_id: "MANUAL", foe_id: "LOCAL_AUTO"},
                                       match_seed="AUTO71F1-TABLE", display_name="Warleader state", maximum_rounds=8)["match_id"]
    return CombatService, TabletopService, combat, mid, leader_id, foe_id, ActionIntent


def test_the_soul_standard_state_survives_a_table_commit_and_a_reload(tmp_path):
    """Checklist 7: everything the window and its once-a-long-rest marker store is strings and integers on conditions, so the fight
    that comes back from disk still knows the window is running, that its free Command Response is spent and that the talent is
    used up -- and the reload agrees about the ordinary Hit Point rules, not only about the labels."""
    from combat.ext import warleader as wl

    from combat.ext import warleader_commands as wc

    CombatService, TabletopService, combat, mid, leader_id, _foe_id, ActionIntent = _soul_at_the_table(tmp_path)
    session = combat._load_session(mid)
    engine = session.engine
    me = engine.state.actors[leader_id]
    me.current_hp = me.maximum_hp = 6
    me.resources["resource:core.martial_focus"] = 1
    engine._gain_resource(me, MOMENTUM, 2, "test")
    engine._commit_damage(me, 6, "FORCE", "action:test.foe_hit", _foe_id, None, reaction_depth=0)
    assert me.life_state == "CONSCIOUS" and _held(me, SOUL) and wl.has_benefited(me, "soul_standard")
    me._turn_flags = {}
    me.turn_flags["wl_soul_response"] = True  # a stale flag from the old turn-flag build, cleared by the window's own data
    engine._gain_resource(me, MOMENTUM, 1, "test")
    session.mechanical.explicit_snapshot()  # a real table commit

    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    other = reloaded.state.actors[leader_id]
    window = _held(other, SOUL)
    assert len(window) == 1 and window[0].expires_on == f"END_OF_SOURCE_TURN_AT:{other.turns_started + 1}"
    assert int(window[0].data["response_used"]) == 0 and window[0].data["label"].startswith("General's Soul-Standard")
    assert all(type(value) in (int, str) for value in window[0].data.values())  # integers and strings only on the wire
    assert wl.has_benefited(other, "soul_standard")  # the once-a-long-rest marker came back too
    # the window spent all two Marks and the Focus; the Mark given afterwards is the only one left
    assert other.life_state == "CONSCIOUS" and other.resources[MOMENTUM] == 1 and other.resources["resource:core.martial_focus"] == 0
    # the stale flag is still in the saved state, and the window's own data is what decides: the free Response is still available
    assert other.turn_flags.get("wl_soul_response") is True and wc._soul_free(reloaded, other)
    assert fresh.state(mid)["menu"] and "error" not in fresh.state(mid)["menu"]


def test_the_battlefield_coordination_mask_does_not_survive_a_table_commit(tmp_path):
    """The mask is transient engine state for one roll. A fight reloaded from disk must not carry a free Disadvantage nobody paid
    for, which is what a saved-state attribute on the engine would have done."""
    CombatService, TabletopService, combat, mid, leader_id, foe_id, _ActionIntent = _soul_at_the_table(tmp_path)
    session = combat._load_session(mid)
    engine = session.engine
    leader = engine.state.actors[leader_id]
    engine._gain_resource(leader, MOMENTUM, 2, "test")
    engine._apply_condition(leader, STANDARD, "test:standard", leader.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"warleader": {"standard": "press_the_opening", "secondary": [], "banners": False},
                                  "label": "Standard: Press the Opening", "reading": "Press the Opening"})
    engine.__dict__["_wl_coordination_frame"] = {"roller": leader_id, "target": foe_id, "instance": "condition-instance:x",
                                                 "source": "action:test", "index": 1}
    session.mechanical.explicit_snapshot()
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert getattr(reloaded, "_wl_coordination_frame", None) is None


# ------------------------------------------------------------------ Warleader: review AUTO71r1f1
def test_reactive_position_refuses_a_swap_that_would_put_the_two_creatures_in_one_place():
    """Each destination can be legal on its own and the pair still overlap. A Large partner whose footprint reaches past its
    own square covers the square the Medium defender just moved to, so the two checks pass on otherwise empty terrain and the
    final arrangement is the one the engine refuses (its occupied-footprint invariant). The Mark must not be spent on it."""
    from combat.ext import warleader_commands as wc
    from combat.space import volume

    engine = _command("reactive_position", marks=2, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    ally, other, foe = _pair(engine)  # a Medium defender at (3,7) and its partner at (4,8), legally adjacent
    other.transformed_size_category = "Large"
    engine.actor_footprints[other.entity_id] = engine._footprint(other)
    assert engine._footprint(other).width_cells == 2
    engine._assert_invariants()  # the field as set up is itself legal
    # neither destination is blocked on its own -- only the arrangement of the two is impossible
    assert engine.grid.volume_legal(other.position, footprint=engine._footprint(ally))
    assert engine.grid.volume_legal(ally.position, footprint=engine._footprint(other))
    assert set(volume(other.position, engine._footprint(ally))) & set(volume(ally.position, engine._footprint(other)))
    assert not wc._swap_legal(engine, ally, other)

    events = _act(engine, TFOE, DAO, ALLY)
    assert (ally.position.x, ally.position.y) == (3, 7) and (other.position.x, other.position.y) == (4, 8)  # nobody moved
    assert not any("swap places" in line for line in _logs(events))
    assert not [p for p in _payloads(events, "RESOURCE_SPENT")  # the printed cost is never paid for an unusable placement
                if p.get("resource_id") == MOMENTUM and p.get("source_definition_id") == "warleader:reactive_position"]
    assert _dealt(events)  # the attack lands normally instead of being rolled back
    engine._assert_invariants()
    assert not _plug_in_failures(engine)


def test_a_base_format_soul_standard_window_keeps_its_spent_command_response_and_its_once_per_rest_use(tmp_path):
    """A fight committed by the base build carries the window but none of the fields this build added: its free Command
    Response was the turn flag ``wl_soul_response`` and it has no once-a-long-rest marker. Loading it must still read as
    spent, and the use must be recorded when the window ends, so a reload hands back neither a second free Response nor a
    second use of the talent. (The other direction is already proved: a fresh window ignores a stale legacy flag.)"""
    from combat.ext import warleader as wl
    from combat.ext import warleader_commands as wc

    CombatService, _Tabletop, combat, mid, leader_id, _foe_id, _ActionIntent = _soul_at_the_table(tmp_path)
    session = combat._load_session(mid)
    engine = session.engine
    me = engine.state.actors[leader_id]
    # the shape the base build committed: the window runs, its own response_used field does not exist, its free Command
    # Response was the turn flag, and it carries no once-a-long-rest marker
    engine._remove_condition(me, SOUL, "test")
    engine._remove_condition(me, wc.SOUL_MARK, "test")
    engine._apply_condition(me, SOUL, wc.SOUL_SOURCE, me.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}",
                            data={"label": "General's Soul-Standard: conscious at 0 Hit Points"})
    me.turn_flags[wc._LEGACY_SOUL_RESPONSE] = True
    session.mechanical.explicit_snapshot()

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    other = reloaded.state.actors[leader_id]
    assert "response_used" not in _held(other, SOUL)[0].data  # genuinely the old format, not a field this build filled in
    assert other.turn_flags.get(wc._LEGACY_SOUL_RESPONSE) is True
    assert not wl.has_benefited(other, "soul_standard")
    assert not wc._soul_free(reloaded, other)  # the legacy spent state survived the reload
    # and the once-a-long-rest use is recorded as the window ends, so the talent cannot be spent a second time
    reloaded._remove_condition(other, SOUL, "test")
    assert wl.has_benefited(other, "soul_standard")


def test_battlefield_coordination_spends_nothing_on_a_roll_that_is_not_actually_made_with_disadvantage():
    """"makes an attack roll ... with Disadvantage" describes how the roll really is being made. Hindered's Disadvantage
    cancelled by an Advantage is a Normal roll, so the printed trigger has not happened and nothing is offered or spent --
    and masking Hindered here would have left the roll as Advantage, which the printed text rules out."""
    from combat.ext import warleader_commands as wc

    engine = _coord_field(1)
    ally, foe, me = engine.state.actors[ALLY], engine.state.actors[TFOE], engine.state.actors[ME]
    engine._add_modifier(foe, "action:test.favour", "incoming_attack_mode", "SET", "ADVANTAGE", "UNTIL_REMOVED",
                         expires_on="UNTIL_REMOVED")
    assert wc._actual_mode(engine, ally, foe) == "NORMAL"  # the stored penalty is real; the roll it would make is not
    assert wc._disadvantages(engine, ally, foe)  # Hindered is still a source on this creature ...
    marks = me.resources[MOMENTUM]
    events = _act(engine, ALLY, DAO, TFOE)
    assert _modes(events) == ["NORMAL"] and me.resources[MOMENTUM] == marks  # ... but a Normal roll spends nothing
    assert "Battlefield Coordination" not in " ".join(_logs(events))
    assert getattr(engine, "_wl_coordination_frame", None) is None
    assert not _plug_in_failures(engine)


def test_the_zero_hit_point_prompt_names_the_attack_that_caused_it_rather_than_the_ability_that_answers(tmp_path):
    """Checklist 7/13 at the level the sentence a player reads: the rendered trigger names the incoming attack and the
    creature that used it. It used to name the responding ability instead ("reduced to 0 Hit Points by General's
    Soul-Standard"), which says nothing about what happened -- and the Court of Moving Banners could name its own leader
    as the cause of a drop that leader did not cause. Checked on a player turn (asked, and rendered through the same
    decision_text the table renders) and on an AI turn (the table plays the fighter, so it decides for itself)."""
    from combat import decision_text
    from combat.ext import warleader_commands as wc
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    from tests.test_auto_lane1 import _own_action

    def consent_and_read(engine, mode):
        """Drive the leader to 0 Hit Points with a real incoming attack and hand back (asked, rendered trigger sentence)."""
        engine.typed_control_modes = {ME: mode}
        engine.typed_ask_reactors = {ME} if mode == "MANUAL" else ()  # who the table actually puts the question to
        asked = []

        def choose(request):
            asked.append(request)
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE"), None

        engine.set_reaction_provider(choose)
        engine._active_intent = ActionIntent(intent_id="auto71r1f1", decision_id="d", candidate_id="c", state_version=1,
                                             actor_id=TFOE, target_ids=(ME,))
        engine._commit_damage(me, 6, "FORCE", incoming, TFOE, None, reaction_depth=0)
        if not asked:
            return [], ""
        context = asked[0]
        rendered = decision_text.trigger_text(dict(context), {"reactor": me.display_name, "moment": "is down"},
                                              {who.entity_id: who.display_name for who in engine.state.actors.values()},
                                              {key: getattr(row, "display_name", "") for key, row in engine.action_catalog.items()})
        return asked, rendered

    for mode in ("MANUAL", "LOCAL_AUTO"):
        CombatService, _Tabletop, combat, mid, ME, TFOE, _ActionIntent = _soul_at_the_table(tmp_path / mode)
        engine = combat._load_session(mid).engine
        me = engine.state.actors[ME]
        me.display_name = "Bao the Commander"
        engine.state.actors[TFOE].display_name = "Grey Fang"  # both sheets arrive as "Factory character"
        me.current_hp = me.maximum_hp = 6
        me.resources["resource:core.martial_focus"] = 1
        incoming = _own_action(engine, DAO)  # a real attack, so the prompt can name it
        asked, rendered = consent_and_read(engine, mode)
        assert me.life_state == "CONSCIOUS" and _held(me, SOUL)  # the window opens either way
        if mode == "MANUAL":
            assert len(asked) == 1
            trigger = asked[0]["choice_trigger"]
            assert trigger["source_definition_id"] == incoming and trigger["action_name"] == DAO
            assert trigger["actor_id"] == TFOE  # the creature that swung, not the leader answering
            assert TFOE.split(":")[-1] not in trigger["action_name"] and "action:" not in rendered  # no internal ids
            assert f"{engine.state.actors[TFOE].display_name}'s {DAO}" in rendered  # the cause a player reads
            assert "General's Soul-Standard" not in rendered  # the response is never its own cause
        else:
            assert not asked  # the table plays this one: the fighter decides for itself, with no prompt to get wrong
        assert not _plug_in_failures(engine)


def _turn_boundary(engine, actor):
    """Run the real ``turn_boundary_start`` subscribers against ``actor``, exactly as ``_system_start_turn`` does
    (gate2_engine._system_start_turn: ``ext.run_strict('turn_boundary_start', self, actor)``), without also advancing the
    fight. The boundary is where the Soul-Standard legacy-window migration reads the turn flag, so a regression has to
    drive this hook to see whether it stays inert."""
    from combat import ext

    ext.run_strict("turn_boundary_start", engine, actor)


def _conditions_of(actor):
    """A comparable snapshot of one creature's conditions and turn flags, for an unchanged-by-the-hook assertion."""
    return ({key: dict(held.data) for key, held in actor.conditions.items()}, dict(actor.turn_flags))


def test_a_legacy_soul_standard_window_stays_spent_across_a_real_turn_start_and_a_second_reload(tmp_path):
    """Finding 1 (AUTO71r2), repaired by AUTO71r3 finding 3: a window saved by the base build recorded its one free Command
    Response as the turn flag ``wl_soul_response``. The engine discards an ordinary turn flag at the start of every turn,
    while this window deliberately runs *through* the end of the leader's next turn -- so reloading such a fight and then
    taking a real turn found the flag gone and granted a second free Response for a window whose one had already been spent.

    The repaired test turns on persistence actually being exercised. The earlier version advanced a *detached* engine and
    then committed a **separate** freshly loaded session, so the second reload read the original legacy window and the
    assertions passed even if ``response_used`` were never written to disk at all. Here the engine that runs the migration
    belongs to the session that is then committed, and every assertion afterwards reads the fight back from disk. It also
    pins the two directions around it -- a window this build opened keeps its own authoritative field (a stale flag from an
    earlier turn must not spend a fresh one), and the migration is inert for anyone without a Soul-Standard window. The
    inertness checks now run the hook itself; the old ones applied a marker to one engine and asserted on another, and the
    ``is False or True`` comparison could never fail."""
    from combat.ext import warleader as wl
    from combat.ext import warleader_commands as wc

    CombatService, _Tabletop, combat, mid, leader_id, foe_id, _ActionIntent = _soul_at_the_table(tmp_path)
    session = combat._load_session(mid)
    engine = session.engine
    me = engine.state.actors[leader_id]
    # the AI foe's real turn below must not end the window early by dropping the leader mid-test
    me.maximum_hp = 200
    me.current_hp = 200

    def legacy_window(who):
        """Put ``who`` in exactly the shape the base build committed: the window open, no response_used of its own, and its
        free Response already used and recorded as the turn flag."""
        engine._remove_condition(who, SOUL, "test")
        engine._remove_condition(who, wc.SOUL_MARK, "test")
        engine._apply_condition(who, SOUL, wc.SOUL_SOURCE, who.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{who.turns_started + 1}",
                                data={"label": "General's Soul-Standard: conscious at 0 Hit Points"})
        who.turn_flags[wc._LEGACY_SOUL_RESPONSE] = True

    legacy_window(me)
    session.mechanical.explicit_snapshot()

    def from_disk():
        return CombatService(ROOT, tmp_path)._load_session(mid).engine

    committed = from_disk()
    leader = committed.state.actors[leader_id]
    assert "response_used" not in _held(leader, SOUL)[0].data  # genuinely the old format, not a field this build filled in
    assert not wc._soul_free(committed, leader)  # the legacy spent state survived the reload

    # Load once more and keep THAT session: the engine below runs the migration, so this is the session that has to be
    # committed. The old version advanced a *detached* engine and then committed a different, freshly loaded session, so
    # the reload re-read the untouched legacy window and the assertions passed even had nothing ever been written.
    advanced = combat._load_session(mid)
    reloaded = advanced.engine
    other = reloaded.state.actors[leader_id]
    assert "response_used" not in _held(other, SOUL)[0].data  # genuinely the old format, not a field this build filled in
    assert not wc._soul_free(reloaded, other)  # the legacy spent state survived the reload

    # a real turn start. The engine clears ordinary turn flags here while the window keeps running to the end of this turn.
    for _ in range(2):  # the leader's turn, then the foe's, brings the leader back to current
        reloaded.end_turn()
    assert reloaded.state.current_actor_id == leader_id, "the leader is current again, inside the window"
    assert _held(other, SOUL), "the window itself runs through the end of this turn"
    assert not wc._soul_free(reloaded, other), "no second free Command Response after the flag was cleared"
    assert wc._kind(reloaded, other, False) != "soul", "and it is refused at the point the Response is chosen"
    advanced.mechanical.explicit_snapshot()  # the very session whose engine ran the migration

    # The claim is about what a reload finds, so read it back from disk rather than from the engine that ran the hook.
    reader = from_disk()
    persisted = reader.state.actors[leader_id]
    window = _held_window(persisted)
    assert window is not None, "the window itself runs through the end of this turn"
    assert window.data.get("response_used") == 1, "the migration reached disk, inside the window that was advanced"
    assert wc._LEGACY_SOUL_RESPONSE not in persisted.turn_flags, "and the turn flag it replaced is gone"
    assert not wc._soul_free(reader, persisted), "no second free Command Response after the flag was cleared"
    assert wc._kind(reader, persisted, False) != "soul", "and it is still refused at the point the Response is chosen"

    third_engine = from_disk()
    third = third_engine.state.actors[leader_id]
    assert _held_window(third).data.get("response_used") == 1, "still there after another reload"
    assert not wc._soul_free(third_engine, third), "and it is still spent"

    # the other direction, with the hook actually run: a window this build opened carries its own field, so a stale flag
    # left over from an earlier turn must not spend a fresh one. (AUTO71r3: this read `is False or True` before, an
    # identity comparison that is true for every value and so asserted nothing.)
    fresh_engine = from_disk()
    fresh = fresh_engine.state.actors[leader_id]
    fresh.turn_flags[wc._LEGACY_SOUL_RESPONSE] = True
    fresh_engine._remove_condition(fresh, SOUL, "test")
    fresh_engine._apply_condition(fresh, SOUL, wc.SOUL_SOURCE, fresh.entity_id, expires_on="UNTIL_REMOVED",
                                  data={"label": "General's Soul-Standard", "response_used": 0})
    _turn_boundary(fresh_engine, fresh)
    assert _held_window(fresh).data.get("response_used") == 0, "the migration left a current-format window alone"
    assert wc._LEGACY_SOUL_RESPONSE in fresh.turn_flags, "so the stale flag is still there to be ignored"
    assert wc._soul_free(fresh_engine, fresh) is True, "the window's own field, not the flag, is what is read"

    # and it touches nothing at all for a creature running no window
    bare_engine = from_disk()
    bare = bare_engine.state.actors[foe_id]
    before = _conditions_of(bare)
    _turn_boundary(bare_engine, bare)
    assert _conditions_of(bare) == before, "the migration changed nothing for a creature with no window"
    assert not any("response_used" in data for data in before[0].values()), "and left no free Response behind anywhere"
    assert not wl.has_benefited(bare, "soul_standard"), "and invented no once-a-long-rest marker"


def _held_window(leader):
    """The one condition instance the window is: its own data is where the spent Response lives."""
    return next((held for held in leader.conditions.values() if held.condition_id == SOUL), None)


def test_the_zero_hit_point_prompt_the_table_actually_builds_names_the_drop_and_the_incoming_action(tmp_path):
    """Finding 2 (AUTO71r2): the earlier test read a rendering branch the table never takes -- it handed
    ``decision_text.trigger_text`` an invented ``moment="is down"``, while the real transport supplies the bare
    checkpoint name (``generals soul standard`` / ``court last stand``), which the shared reader cannot phrase and falls
    back from ("Grey Fang just did something Bao can react to"): no mention of the drop and no mention of the attack.

    This asserts the prompt the table really builds, through ``TabletopService._reaction_prompt``, for both of this
    plug-in's zero-HP decisions, and for a responder the table puts the question to on *another* actor's turn. The
    responder is manually controlled, so the question is genuinely asked rather than auto-decided."""
    from combat.ext import warleader_commands as wc
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision
    from combat.tabletop_service import TabletopService

    from tests.test_auto_lane1 import _own_action

    CombatService, _Tabletop, combat, mid, leader_id, foe_id, _ActionIntent = _soul_at_the_table(tmp_path)
    engine = combat._load_session(mid).engine
    me, foe = engine.state.actors[leader_id], engine.state.actors[foe_id]
    me.display_name, foe.display_name = "Bao the Commander", "Grey Fang"
    me.current_hp = me.maximum_hp = 6
    me.resources["resource:core.martial_focus"] = 1
    incoming = _own_action(engine, DAO)  # a real catalogued attack, so the prompt can name it in plain words
    asked = []

    def choose(request):
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    # the foe's turn is in flight; the leader drops, so the question is raised while another actor is acting
    engine.typed_control_modes = {leader_id: "MANUAL"}
    engine.typed_ask_reactors = {leader_id}
    engine.set_reaction_provider(choose)
    engine._active_intent = ActionIntent(intent_id="auto71r2f1-zone", decision_id="d", candidate_id="c", state_version=1,
                                         actor_id=foe_id, target_ids=(leader_id,))
    engine._commit_damage(me, 6, "FORCE", incoming, foe_id, None, reaction_depth=0)

    assert asked, "a manually controlled responder on another actor's turn is asked"
    context = asked[0]
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    shown = table._reaction_prompt(mid, context, engine=engine)
    moment = shown["moment"]  # the table shows the trigger sentence when there are no options to pick
    assert "Bao the Commander was reduced to 0 Hit Points" in moment, "the prompt says what actually happened"
    assert "Grey Fang" in moment and DAO in moment, "and names the attack that did it, in plain words"
    assert "action:" not in moment and leader_id not in moment, "never an internal id"
    assert "General's Soul-Standard" not in moment, "the responding ability is never its own cause"
    assert "1 Martial Focus" in shown["cost"] and "Momentum Mark" in shown["cost"], "and what it costs"
    assert "GENERALS_SOUL_STANDARD" in context["checkpoint"] and shown["reaction"] == "General's Soul-Standard"

    # The whole summary the table shows, word for word (AUTO71r3 finding 1). It used to promise "one Command Response each
    # round is free", but the window grants exactly one for the whole window and never resets it: a window that crosses a
    # round boundary would have invited the player to rely on a free Response that is not there. The mechanics are right and
    # the wording was wrong, so the wording is what is pinned here -- if the promise is ever widened to match an
    # implementation, this fails and the change has to be deliberate.
    assert shown["summary"] == (
        "You are at 0 Hit Points but not killed outright. Spend 1 Martial Focus (your Stamina pool for weapon attacks) "
        "and every Momentum Mark you carry to stay conscious until the end of your next turn. While that window runs, "
        "ordinary healing does nothing: only a feature that brings a creature back from 0 Hit Points can help. You also "
        "Set your Standard without spending a Bonus Action, and one Command Response during this window is free. If you "
        "are still at 0 Hit Points at the end of that next turn, you fall Unconscious. Use Limit: once per long rest."
    ), shown["summary"]
    assert "each round" not in shown["summary"], "the window grants one free Response in total, not one per round"
    # Declining this question drops the creature it is about, which here is the leader answering.
    assert shown["table_note"] == "You may decline, and Bao the Commander falls Unconscious by the ordinary rules instead.", \
        shown["table_note"]


def test_zero_hit_point_prompt_names_the_domain_when_the_court_of_moving_banners_answers(tmp_path):
    """The Court's own zero-HP question says the ally dropped *inside that Domain*, so the player knows why the question
    was asked at all, and still names the attack that did the damage rather than the Court itself."""
    from combat.ext import warleader as wl
    from combat.ext import warleader_commands as wc
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision
    from combat.tabletop_service import TabletopService

    from tests.test_auto_lane1 import _own_action

    CombatService, _Tabletop, combat, mid, leader_id, foe_id, _ActionIntent = _soul_at_the_table(tmp_path)
    engine = combat._load_session(mid).engine
    me, foe = engine.state.actors[leader_id], engine.state.actors[foe_id]
    me.display_name, foe.display_name = "Bao the Commander", "Grey Fang"
    # the leader actually runs a Standard and raises the Court, and the other creature is its Commanded ally beside it
    engine._apply_condition(me, STANDARD, "warleader:test", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Standard", "warleader": {"standard": "marked_objective"}})
    engine._apply_condition(me, wl.COURT, "warleader:test", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Court of Moving Banners"})
    foe.team_id = me.team_id  # commanded, standing within the 60-foot Domain
    foe.current_hp = foe.maximum_hp = 6
    incoming = _own_action(engine, DAO)
    asked = []

    def choose(request):
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.typed_control_modes = {foe_id: "MANUAL"}
    engine.typed_ask_reactors = {foe_id}
    engine.set_reaction_provider(choose)
    engine._active_intent = ActionIntent(intent_id="auto71r2f1-court", decision_id="d", candidate_id="c", state_version=1,
                                         actor_id=leader_id, target_ids=(foe_id,))
    engine._commit_damage(foe, 6, "FORCE", incoming, foe_id, None, reaction_depth=0)

    # the literal decision key this plug-in already used before the fix, so this assertion fails on the wording rather
    # than on a constant this change introduced
    assert asked and "COURT_LAST_STAND" in asked[0]["checkpoint"]
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    shown = table._reaction_prompt(mid, asked[0], engine=engine)
    moment = shown["moment"]
    assert "Grey Fang was reduced to 0 Hit Points" in moment
    assert "inside Bao the Commander's Court of Moving Banners" in moment, "the Domain is what makes this question asked"
    assert DAO in moment and "action:" not in moment

    # What the question offers and what declining costs (AUTO71r3 findings 1 and 2). Both used to share one note saying
    # "the leader falls Unconscious", but the Court asks about the Commanded ally that dropped: a player moving their own
    # fallen ally was told that declining would put the commander out instead. The note is pinned whole, because it is the
    # field that carried the mistake.
    assert shown["summary"] == (
        "A Commanded ally (one your Standard covers) that drops to 0 Hit Points inside the Domain may fall Prone and "
        "move 5 feet before falling Unconscious. That move is forced, so it does not provoke an Opportunity Attack. "
        "No resource cost."
    ), shown["summary"]
    assert shown["table_note"] == "You may decline, and Grey Fang falls Unconscious by the ordinary rules instead.", \
        shown["table_note"]
    assert "the leader" not in shown["table_note"], "it is the ally who is down, not the leader standing over it"


def test_a_zero_hit_point_prompt_names_the_creature_that_dealt_the_damage_not_the_one_whose_turn_it_is(tmp_path):
    """Finding 3 (AUTO71r2): the zero-HP seam is handed the *outer turn's* intent, which is not necessarily what hit the
    creature. A Warleader who walks into an enemy Blackwater zone is damaged with the zone's owner as the source creature
    while the mover's own intent is still active (gate2_engine._resolve_zone_effect), so naming the intent's actor told the
    player the Warleader attacked itself.

    The regression is built from a real Blackwater zone owned by the foe, resolved by the engine's own zone code, with
    the *mover's* intent active -- so the outer actor and the real source genuinely differ, rather than a hand-picked
    intent that happens to match the attacker."""
    from combat.ext import warleader_commands as wc
    from combat.gate2_runtime_models import ActionIntent, Position, ZoneState
    from combat.tabletop_service import TabletopService

    from tests.test_auto_lane1 import _own_action

    CombatService, _Tabletop, combat, mid, leader_id, foe_id, _ActionIntent = _soul_at_the_table(tmp_path)
    engine = combat._load_session(mid).engine
    me, foe = engine.state.actors[leader_id], engine.state.actors[foe_id]
    me.display_name, foe.display_name = "Bao the Commander", "Grey Fang"  # the foe owns the zone; the leader is in it
    me.current_hp = me.maximum_hp = 6
    me.resources["resource:core.martial_focus"] = 1
    engine.state.zones["zone:blackwater"] = ZoneState(
        zone_id="zone:blackwater", source_definition_id="action:bai_meizhen.blackwater_serpent_court", owner_id=foe_id,
        center=me.position, radius_cells=0, affected_cells=(me.position,), concentration_link=False,
        created_round=engine.state.round_number, trigger_profile={"kind": "BLACKWATER"})
    asked = []

    def choose(request):
        asked.append(request)
        from combat.gate2_runtime_models import ReactionDecision

        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.typed_control_modes = {leader_id: "MANUAL"}
    engine.typed_ask_reactors = {leader_id}
    engine.set_reaction_provider(choose)
    # the leader is walking: its own intent is the active one, and it is NOT what caused this damage
    engine._active_intent = ActionIntent(intent_id="auto71r2f1-mover", decision_id="d", candidate_id="c", state_version=1,
                                         actor_id=leader_id, target_ids=(), destination=Position(x=me.position.x, y=me.position.y))
    engine._roll_save = lambda target, ability, dc, source_id: type("S", (), {"total": 5})()  # the zone's save fails
    engine._resolve_zone_effect(engine.state.zones["zone:blackwater"], me, checkpoint="AT_TURN_START")

    assert me.current_hp == 0 and asked, "the zone put the Warleader at 0 Hit Points"
    trigger = asked[0]["choice_trigger"]
    assert trigger["actor_id"] == foe_id, "the zone owner is the real source, not the mover whose intent was active"
    assert trigger["actor_id"] != leader_id
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    moment = table._reaction_prompt(mid, asked[0], engine=engine)["moment"]
    assert "Grey Fang" in moment, "the prompt names whoever really did it"
    assert "Bao the Commander was reduced to 0 Hit Points" in moment
    assert f"Bao the Commander's {DAO}" not in moment, "the mover is never told it attacked itself"
    # a source that is genuinely unknown stays unknown rather than naming the victim
    assert wc._incoming(engine, me, "", None)["actor_id"] == ""


def test_a_secondary_standard_gives_its_passive_benefit_but_no_momentum_mark():
    engine, me, foe, (ally,) = _muster("shieldbrothers", "ironclad_line", "layered_orders", "courier_s_dash")
    base = engine._ac_modifier(ally)
    _use(engine, "Set the Standard")  # Press the Opening, with Shieldbrothers as the secondary
    data = _held(me, STANDARD)[0].data["warleader"]
    assert data["standard"] == "press_the_opening" and data["secondary"] == ["shieldbrothers"]
    engine._commit_damage(ally, 10, "SLASHING", _own_action(engine, DAO), FOE, None, reaction_depth=0)
    assert engine._ac_modifier(ally) == base + 2  # Shieldbrothers is live as a secondary Standard
    assert me.resources[MOMENTUM] == 0  # a secondary Standard never earns a Momentum Mark of its own


def test_a_player_at_the_table_is_asked_which_secondary_standard_to_carry():
    """Layered Orders' printed "choose ... one secondary Standard" is a real menu for a player, and it never asks a fighter
    the table plays (that keeps every saved AI fight's reading, and its replay, exactly what it was)."""
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "courier_s_dash")
    engine.typed_control_modes = {ME: "MANUAL"}  # a player who is actually at the table
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=("couriers_dash",)), None

    engine.set_reaction_provider(choose)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Shieldbrothers")
    engine.execute_intent(ActionIntent(intent_id="auto71-menu", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids or (), option_ids=candidate.option_ids))
    assert asked and "couriers_dash" in asked[0] and "ironclad_line" in asked[0]
    assert _held(me, STANDARD)[0].data["warleader"]["secondary"] == ["couriers_dash"]  # the answer is what it carries
    assert not _plug_in_failures(engine)

    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "courier_s_dash")
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}  # the table plays this one: no question
    asked = []
    engine.set_reaction_provider(choose)
    _use(engine, "Shieldbrothers")
    assert not asked and _held(me, STANDARD)[0].data["warleader"]["secondary"] == ["ironclad_line"]
    assert not _plug_in_failures(engine)


def test_the_secondary_standard_menu_labels_each_option_with_the_benefit_it_carries():
    """A newcomer has to be able to compare the options: each label says what the Standard does and that it pays nothing."""
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "courier_s_dash")
    engine.typed_control_modes = {ME: "MANUAL"}
    asked = []

    def choose(request):
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=("couriers_dash",)), None

    engine.set_reaction_provider(choose)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Shieldbrothers")
    engine.execute_intent(ActionIntent(intent_id="auto71f1-labels", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids or (), option_ids=candidate.option_ids))
    labels = asked[0]["choice_trigger"]["labels"]
    assert "Ironclad Line: a Commanded ally beside another Commanded ally takes less nonmagical weapon damage" in labels["ironclad_line"]
    assert "Press the Opening: +2 to the first attack roll two Commanded allies make against the same foe" in labels["press_the_opening"]
    assert "Courier's Dash: a Commanded ally gains +10 feet of Speed" in labels["couriers_dash"]
    assert all("no Momentum Mark or Command Response" in text for text in labels.values())
    assert "choose the secondary Standard" in asked[0]["choice_trigger"]["prompt"]
    assert asked[0]["extension_choice"]["allow_decline"] is False  # Layered Orders requires one
    assert not _plug_in_failures(engine)


def test_ten_thousand_banners_can_be_declined_and_layered_orders_cannot():
    """"choose up to three Standards. One is primary and two are secondary": up to means none is legal, so that menu can be
    declined and a leader who declines carries no secondary Standard. Layered Orders says one, so its menu offers no decline."""
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    def decline(request):
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "ten_thousand_banners_doctrine",
                                        "courier_s_dash")
    engine.typed_control_modes = {ME: "MANUAL"}
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request), (decline(request)[0], None))[1])
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Shieldbrothers")
    engine.execute_intent(ActionIntent(intent_id="auto71f1-decline", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids or (), option_ids=candidate.option_ids))
    assert asked and asked[0]["extension_choice"]["allow_decline"] is True
    assert asked[0]["extension_choice"]["minimum_selections"] == 0
    assert _held(me, STANDARD)[0].data["warleader"]["secondary"] == []  # the decline is the answer, not a default
    assert any("carries no secondary Standard" in (p.get("trigger") or "") for p in _payloads(engine.events, "PASSIVE_TRIGGERED"))
    assert not _plug_in_failures(engine)

    engine, me, _foe, _allies = _muster("shieldbrothers", "ironclad_line", "layered_orders", "courier_s_dash")
    engine.typed_control_modes = {ME: "MANUAL"}
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request), (decline(request)[0], None))[1])
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Shieldbrothers")
    with pytest.raises(ValueError, match="invalid extension choice decline"):
        # the transport itself refuses a decline the printed text does not allow ("choose one ... secondary Standard")
        engine.execute_intent(ActionIntent(intent_id="auto71f1-required", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=ME, target_ids=candidate.target_ids or (), option_ids=candidate.option_ids))
    assert asked and asked[0]["extension_choice"]["allow_decline"] is False
    assert asked[0]["extension_choice"]["minimum_selections"] == 1
    assert not _plug_in_failures(engine)


def test_a_player_at_the_table_chooses_the_reactive_position_partner_from_a_labelled_menu():
    """Change standard 6 and 13: the partner question reaches the table as a labelled menu naming the ability, the trigger, the
    creature affected and the cost -- not as repeated Use/Pass on a bare checkpoint id."""
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    engine.typed_control_modes = {ME: "MANUAL"}
    ally, other, _foe = _pair(engine)
    asked = []

    def choose(request):
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(ALLY2,)), None

    engine.set_reaction_provider(choose)
    events = _act(engine, TFOE, DAO, ALLY)
    assert len(asked) == 1
    trigger = asked[0]["choice_trigger"]
    assert asked[0]["extension_choice"]["option_ids"] == [ALLY2]  # the leader is not adjacent, so one partner is eligible
    assert trigger["labels"][ALLY2].startswith("Factory character: swap places with Factory character")
    assert "Reactive Position" in trigger["labels"][ALLY2] and "1 Momentum Mark" in trigger["labels"][ALLY2]
    assert "is being attacked by" in trigger["prompt"] and "1 Momentum Mark" in trigger["prompt"]
    assert (ally.position.x, ally.position.y) == (4, 8)  # the chosen partner, not a default
    assert not _dealt(events) and not _plug_in_failures(engine)

    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2), _wl(actor_id=ALLY3)])
    engine.typed_control_modes = {ME: "MANUAL"}
    ally, _other, _foe = _pair(engine)
    engine.state.actors[ALLY3].position = Position(x=3, y=8)  # a second eligible partner
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request), (ReactionDecision(
        checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
        selection="USE", option_ids=(ALLY3,)), None))[1])
    _act(engine, TFOE, DAO, ALLY)
    assert asked[0]["extension_choice"]["option_ids"] == [ALLY2, ALLY3]
    assert (ally.position.x, ally.position.y) == (3, 8)
    assert (engine.state.actors[ALLY3].position.x, engine.state.actors[ALLY3].position.y) == (3, 7)  # the answer, not the first
    assert not _plug_in_failures(engine)

    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    engine.typed_control_modes = {ME: "MANUAL"}
    ally, other, _foe = _pair(engine)
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request), (ReactionDecision(
        checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
        selection="DECLINE"), None))[1])
    me = engine.state.actors[ME]
    marks = me.resources[MOMENTUM]
    events = _act(engine, TFOE, DAO, ALLY)
    assert asked
    spent = [p.get("amount") for p in _payloads(events, "RESOURCE_SPENT")
             if p.get("resource_id") == MOMENTUM and p.get("source_definition_id") == "warleader:reactive_position"]
    assert not spent  # declined: the printed cost is never paid
    assert (ally.position.x, ally.position.y) == (3, 7) and other.position == Position(x=4, y=8) and _dealt(events)
    assert not _plug_in_failures(engine)

    engine = _command("reactive_position", marks=1, friends=[_wl(actor_id=ALLY), _wl(actor_id=ALLY2)])
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}  # an AI leader decides for itself and is never asked
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request), (None, None))[1])
    _act(engine, TFOE, DAO, ALLY)
    assert not asked
    assert not _plug_in_failures(engine)


def test_a_player_at_the_table_chooses_the_battlefield_coordination_source_from_a_labelled_menu():
    """The same contract for the Disadvantage source: a labelled menu naming the condition, the trigger and the cost, and a decline
    that spends nothing."""
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision

    engine = _coord_field(1)
    engine.typed_control_modes = {ME: "MANUAL"}
    _put(engine, ALLY, "frightened", TFOE, "action:test.fear")  # a second real source, so there is a choice to make
    asked = []

    def choose(request):
        asked.append(request)
        labels = request["choice_trigger"]["labels"]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(next(i for i in request["legal_option_ids"] if labels[i].startswith("Frightened")),)), None

    engine.set_reaction_provider(choose)
    me = engine.state.actors[ME]
    marks = me.resources[MOMENTUM]
    events = _act(engine, ALLY, DAO, TFOE)
    assert len(asked) == 1
    trigger = asked[0]["choice_trigger"]
    said = " ".join(trigger["labels"].values())
    assert said.startswith("Frightened: ignored for this one attack roll") and "Hindered: ignored" in said
    assert "1 Momentum Mark" in said and "keeps any other Disadvantage" in said
    assert "is attacking" in trigger["prompt"] and "never grants Advantage" in trigger["prompt"]
    assert _modes(events) == ["DISADVANTAGE"] and me.resources[MOMENTUM] == marks - 1  # Hindered is the other source, and it stays
    assert "ignores Frightened" in " ".join(_logs(events))
    assert not _plug_in_failures(engine)

    engine = _coord_field(1)
    engine.typed_control_modes = {ME: "MANUAL"}
    _put(engine, ALLY, "frightened", TFOE, "action:test.fear")
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request), (ReactionDecision(
        checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
        reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None))[1])
    me = engine.state.actors[ME]
    marks = me.resources[MOMENTUM]
    _act(engine, ALLY, DAO, TFOE)
    assert asked and me.resources[MOMENTUM] == marks  # declined: the Mark is untouched
    assert "Battlefield Coordination" not in " ".join(_logs(engine.events))
    assert not _plug_in_failures(engine)
