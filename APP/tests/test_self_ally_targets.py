"""Hunt 3, bugs 3-5: abilities that only help their user or an ally, and Temporary HP printed as a sum.

Bug 3: ``_target_kind`` counted every harm-typed row whatever it was aimed at, so ~50 self and ally forms compiled as
"hostile creature within 5 ft" (a buff was only offered next to a foe and landed on it).
Bug 4: a cast on the caster itself found nobody for a "the target gains ..." row (Coagulate on itself gave no Temporary HP).
Bug 5: "Temporary HP equal to PB + your key modifier" is typed as one row per term and the engine keeps the largest grant.
Real mechanics run through the engine (Gate4ControllerEngine, as tests/test_auto_life.py does); the odd cases use typed rows.
"""
import json
import re
from pathlib import Path

import pytest

from combat import typed_executor as ex
from combat.factory_compiler import _target_kind, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from combat.gate4_engine import Gate4ControllerEngine
from factory_authoring.typed_structure import add_marks_from_text, add_spend_mark_from_text
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.selfally"
AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]

COAGULATE = ("BLOOD_BASE_COAGULATE", "tianxia.sphere.blood")
DEEP_ROOT = ("TAL_EARTH_DEEP_ROOT_STANCE", "tianxia.sphere.earth")
DEMON_EMPEROR = ("TAL_DAEMONIC_CULTIVATION_DEMON_EMPEROR_INCARNATION", "tianxia.sphere.daemonic_cultivation")
RADIANT_AEGIS = ("tianxia.talent.radiance.radiant_aegis_of_the_heart", "tianxia.sphere.radiance")


def _bundle(pair, *, cl=10):
    talent, sphere = pair
    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": cl}, "equipment": [],
             "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": [talent]}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(9, 6)):
    """The caster at (3, 6) and one foe six squares (30 ft) away, so nothing is within 5 ft."""
    engine = Gate4ControllerEngine(ROOT, match_seed="SELFALLY", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _candidates(engine, name):
    return [c for c in engine.legal_candidates() if c.display_name == name]


def _use(engine, candidate):
    engine.execute_intent(ActionIntent(intent_id="i", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))


def _row(bundle, name):
    return next(row for row in bundle["action_catalog"] if row["display_name"] == name)


def _thread(engine, creature_id):
    """Coagulate's "Target: One willing creature bearing your Blood Thread" (rider lane C5): the caster's Thread on the creature."""
    engine._apply_condition(engine.state.actors[creature_id], "condition:typed.mark.blood_thread." + ME, "test:thread", ME, expires_on="UNTIL_REMOVED")


def _cast(pair, name, *, cl=10):
    """Cast the named ability on its user; returns (engine, the events it produced)."""
    engine = _engine(_bundle(pair, cl=cl))
    if pair == COAGULATE:
        _thread(engine, ME)
    (candidate,) = _candidates(engine, name)
    assert candidate.target_ids == (ME,)
    before = len(engine.events)
    _use(engine, candidate)
    return engine, engine.events[before:]


# ---------------------------------------------------------------- bug 3: what an ability is aimed at
@pytest.mark.parametrize("key", [
    DEEP_ROOT[0], DEMON_EMPEROR[0],
    "tianxia.subpath.body.drunken_fist.feature.heavenly_drunk", "tianxia.talent.gravity.moon_weight_incarnation",
    "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY"])  # the last one's row is damage to "the attacker": a retaliation, not an aim
def test_a_self_stance_is_a_self_form(key):
    assert _target_kind(AUTH[key]) == ("SELF", None)


def test_the_creature_of_your_choice_is_still_aimed_at():
    # The speed/terrain stance targets its user. Its plug-in separately asks
    # which creature's Opportunity Attacks this movement ignores.
    assert _target_kind(AUTH["TAL_MAGMA_FURNACE_STEP"]) == ("SELF", None)
    assert any(row.get('type') == 'magma_furnace_step'
               for row in AUTH["TAL_MAGMA_FURNACE_STEP"]['effects'])


def test_an_ally_buff_is_an_ally_form_at_its_printed_range():
    assert _target_kind(AUTH[COAGULATE[0]]) == ("ALLY_OR_SELF", 30)
    assert _target_kind(AUTH[RADIANT_AEGIS[0]]) == ("ALLY_OR_SELF", 30)


def test_abilities_that_reach_a_foe_stay_hostile_forms():
    # Formation-Extinguishing Edict targets a formation node or construct, not a creature (Lightning review; objects system).
    assert _target_kind(AUTH["TAL_LIGHTNING_CHAIN_BOLT"]) == ("HOSTILE_ENTITY", 90)


def test_which_rows_make_an_ability_hostile():
    reach = {"kind": "feet", "feet": 30}

    def kind(*effects, rng=reach):
        return _target_kind({"effects": list(effects), "range": rng})

    gain = {"type": "temp_hp", "applies_to": "target", "formula": "pb"}
    assert kind(gain) == ("ALLY_OR_SELF", 30)
    # a harmful row held back for the GM (deferred), or aimed at the caster or an ally, is not aimed at a foe
    assert kind(gain, {"type": "condition", "applies_to": "target", "condition": "prone", "deferred": True}) == ("ALLY_OR_SELF", 30)
    assert kind(gain, {"type": "condition", "applies_to": "self", "condition": "prone"}) == ("ALLY_OR_SELF", 30)
    assert kind(gain, {"type": "damage", "applies_to": "ally"}) == ("ALLY_OR_SELF", 30)
    assert kind(gain, {"type": "mark", "applies_to": "self", "mark": "Ward"}) == ("ALLY_OR_SELF", 30)
    # one live row aimed at the target (or unaimed, as the parser leaves it) is
    assert kind(gain, {"type": "condition", "applies_to": "target", "condition": "prone"}) == ("HOSTILE_ENTITY", 30)
    assert kind(gain, {"type": "save", "ability": "wis"}) == ("HOSTILE_ENTITY", 30)
    assert kind(gain, {"type": "mark", "applies_to": "target", "mark": "Brand"}) == ("HOSTILE_ENTITY", 30)
    # "the attacker" with no reach: damage or a save the user's stance deals back is not an aim; a chosen creature is
    assert kind(gain, {"type": "damage", "applies_to": "attacker"}, rng=None) == ("SELF", None)
    assert kind({"type": "reaction_denied", "applies_to": "attacker", "on": "opportunity attacks"}, rng=None) == ("HOSTILE_ENTITY", 5)
    # no reach: the same benefit is a self form
    assert kind(gain, rng=None) == ("SELF", None)
    assert kind({"type": "condition", "applies_to": "creatures_in_area", "condition": "frightened"}, rng=None) == ("SELF", None)


def test_stances_are_offered_and_cast_with_no_foe_within_reach():
    for pair, name in ((DEEP_ROOT, "Deep Root Stance"), (DEMON_EMPEROR, "Demon Emperor Incarnation")):
        bundle = _bundle(pair)
        assert _row(bundle, name)["target_kind"] == "SELF"
        engine, events = _cast(pair, name)
        foe = engine.state.actors[AN]
        # the buff lands on the caster; the foe was neither knocked prone nor forced to save (Deep Root Stance put Prone on
        # a foe, Demon Emperor Incarnation forced a DC 17 Wisdom save on one)
        assert not foe.conditions, (name, [c.condition_id for c in foe.conditions.values()])
        assert not [e for e in events if e.event_type in {"SAVE_ROLLED", "DAMAGE_COMMITTED"}], name
        assert any(e.event_type in {"CONDITION_APPLIED", "MODIFIER_APPLIED"} and e.target_ids == (ME,) for e in events), name


def _movement_rows(effects):
    for row in effects or []:
        if isinstance(row, dict):
            if row.get("type") == "movement":
                yield row
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _movement_rows(row.get(key))


def test_no_typed_row_takes_movement_away_from_its_user():
    # "reduce forced movement against you by 5 feet" (Deep Root Stance) was typed as a movement grant of -5 feet
    taken = [(key, row["distance_ft"]) for key, mechanic in AUTH.items() for row in _movement_rows(mechanic.get("effects"))
             if str(row.get("distance_ft") or "").startswith("-")]
    assert not taken, taken


def test_a_stance_cast_with_no_movement_left_takes_effect():
    """Once the stance can be cast anywhere, a caster that has moved its whole Speed casts it with 0 feet left; the -5 feet
    it used to take off that raised a validation error (negative movement) and stopped the fight (hunt 3 rerun, F3-06)."""
    engine = _engine(_bundle(DEEP_ROOT))
    me = engine.state.actors[ME]
    me.movement_remaining_ft = 0
    (candidate,) = _candidates(engine, "Deep Root Stance")
    before = len(engine.events)
    _use(engine, candidate)
    events = engine.events[before:]
    assert me.movement_remaining_ft == 0
    assert any(e.event_type == "CONDITION_APPLIED" and e.target_ids == (ME,) for e in events)
    assert any(e.event_type == "GM_RIDER" and "forced movement" in str(e.payload.get("rider")) for e in events)


# ---------------------------------------------------------------- bug 4: a cast on the caster reaches the caster
def test_an_ally_ability_cast_on_its_user_takes_effect():
    engine, events = _cast(RADIANT_AEGIS, "Radiant Aegis of the Heart")
    me = engine.state.actors[ME]
    assert any(m.target_field == "damage_resistance" and str(m.value) == "NECROTIC" for m in me.modifiers.values())
    assert any(c.condition_id == "condition:typed.save_against" for c in me.conditions.values())


def test_the_same_ability_cast_on_an_ally_lands_on_the_ally_only():
    engine = _engine(_bundle(COAGULATE))
    engine.state.actors[AN].team_id = engine.state.actors[ME].team_id  # the second creature is an ally
    _thread(engine, AN)
    (candidate,) = [c for c in _candidates(engine, "Coagulate: Temporary HP") if c.target_ids == (AN,)]
    _use(engine, candidate)
    assert engine.state.actors[AN].temporary_hp > 0
    assert engine.state.actors[ME].temporary_hp == 0


def _synthetic(typed, kind):
    engine = Gate2Engine(ROOT, match_seed="SELFALLY-SYNTHETIC")
    actor = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id="action:typed.test", display_name="Typed test", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=kind,
                              range_ft=None if kind == "SELF" else 30, parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    return engine, actor, action


def _run(typed, kind, targets=()):
    engine, actor, action = _synthetic(typed, kind)
    targets = list(targets)
    ctx = ex.Context(engine, actor, action, None, typed, targets, targets[0] if len(targets) == 1 else None)
    ex.run_effects(ctx, typed["effects"])
    return engine, actor


NUMBERS = {"pb": 4, "key_mod": 2, "cl": 10, "save_dc": 20, "attack_bonus": 10}
HARM = [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["fire"]},
        {"type": "condition", "applies_to": "target", "condition": "prone"},
        {"type": "save", "applies_to": "target", "ability": "wis", "on_fail": [{"type": "condition", "condition": "frightened"}]},
        {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"},
        {"type": "mark", "applies_to": "target", "mark": "Brand", "duration": {"kind": "until_removed"}}]


@pytest.mark.parametrize("kind", ["SELF", "ALLY_OR_SELF"])
def test_a_row_that_harms_its_target_never_falls_back_to_the_caster(kind):
    gain = {"type": "temp_hp", "applies_to": "target", "flat": 5, "formula": "none"}
    engine, actor = _run({"effects": [*HARM, gain], "numbers": NUMBERS, "duration": {"kind": "instant"}}, kind)
    assert actor.current_hp == actor.maximum_hp and not actor.conditions
    assert not any(e.event_type in {"DAMAGE_COMMITTED", "SAVE_ROLLED", "MARK_PLACED", "FORCED_MOVEMENT_APPLIED"} for e in engine.events)
    assert actor.temporary_hp == 5  # the benefit alongside them does


def test_a_benefit_aimed_at_a_hostile_creature_form_is_not_given_to_the_caster():
    gain = {"type": "temp_hp", "applies_to": "target", "flat": 5, "formula": "none"}
    engine, actor = _run({"effects": [gain], "numbers": NUMBERS, "duration": {"kind": "instant"}}, "HOSTILE_ENTITY")
    assert actor.temporary_hp == 0


def test_a_benefit_cast_with_an_area_is_left_to_the_area():
    gain = {"type": "temp_hp", "applies_to": "target", "flat": 5, "formula": "none"}
    typed = {"effects": [gain], "numbers": NUMBERS, "duration": {"kind": "instant"}, "area": {"shape": "sphere", "size_ft": 10}}
    engine, actor = _run(typed, "SELF")
    assert actor.temporary_hp == 0


# ---------------------------------------------------------------- bug 5: Temporary HP printed as a sum
def _grants(engine):
    return [e.payload["offered"] for e in engine.events if e.event_type == "TEMP_HP_GRANTED"]


def test_coagulate_on_itself_grants_pb_plus_the_key_modifier():
    bundle = _bundle(COAGULATE)
    numbers = _row(bundle, "Coagulate: Temporary HP")["parameters"]["typed"]["numbers"]
    pb, key = int(numbers["pb"]), int(numbers["key_mod"])
    assert pb > 0 and key > 0
    engine, events = _cast(COAGULATE, "Coagulate: Temporary HP")
    assert [e.payload["offered"] for e in events if e.event_type == "TEMP_HP_GRANTED"] == [pb + key]
    assert engine.state.actors[ME].temporary_hp == pb + key  # printed 4 + 4, the largest single term gave 4


@pytest.mark.parametrize("cl, dice", [(11, "1d8+0"), (17, "2d8+0")])
def test_coagulate_adds_its_printed_dice_at_high_realms(cl, dice):
    bundle = _bundle(COAGULATE, cl=cl)
    numbers = _row(bundle, "Coagulate: Temporary HP")["parameters"]["typed"]["numbers"]
    engine, events = _cast(COAGULATE, "Coagulate: Temporary HP", cl=cl)
    rolled = [e for e in events if e.event_type == "DAMAGE_ROLLED" and str(e.payload.get("reason")).startswith("TEMP_HP")]
    assert [e.payload["expression"] for e in rolled] == [dice]
    assert engine.state.actors[ME].temporary_hp == int(numbers["pb"]) + int(numbers["key_mod"]) + rolled[0].payload["total"]


def test_split_terms_add_and_a_repeated_term_counts_once():
    rows = [{"type": "temp_hp", "applies_to": "target", "formula": "pb"},
            {"type": "temp_hp", "applies_to": "target", "formula": "key_ability_modifier"}]
    engine, actor = _run({"effects": rows, "numbers": NUMBERS, "duration": {"kind": "instant"}}, "SELF")
    assert _grants(engine) == [6] and actor.temporary_hp == 6
    twins = [rows[0], {**rows[0], "origin": "parser"}, rows[1]]  # a parser row and a model row both say "PB"
    engine, actor = _run({"effects": twins, "numbers": NUMBERS, "duration": {"kind": "instant"}}, "SELF")
    assert _grants(engine) == [6] and actor.temporary_hp == 6


def test_a_restated_total_and_flat_alternatives_are_not_summed():
    # the parser also leaves a row restating the whole printed line; it is a grant of its own, not a third term
    restated = {"type": "temp_hp", "applies_to": "target", "formula": "text: equal to your Proficiency Bonus + your Path key ability modifier"}
    assert not ex._is_temp_hp_term(restated)
    rows = [{"type": "temp_hp", "applies_to": "target", "formula": "pb"},
            {"type": "temp_hp", "applies_to": "target", "formula": "key_ability_modifier"}, restated]
    engine, actor = _run({"effects": rows, "numbers": NUMBERS, "duration": {"kind": "instant"}}, "SELF")
    assert actor.temporary_hp == 6
    # a realm table's flat alternatives (10 / 20 / 30) stay separate grants and the largest stands
    table = [{"type": "temp_hp", "applies_to": "target", "flat": amount, "formula": "none"} for amount in (10, 20)]
    engine, actor = _run({"effects": table, "numbers": NUMBERS, "duration": {"kind": "instant"}}, "SELF")
    assert _grants(engine) == [10, 20] and actor.temporary_hp == 20


def test_a_term_locked_to_a_higher_realm_is_left_out_below_it():
    rows = [{"type": "temp_hp", "applies_to": "target", "formula": "pb"},
            {"type": "temp_hp", "applies_to": "target", "formula": "key_ability_modifier", "min_cl": 11}]
    engine, actor = _run({"effects": rows, "numbers": NUMBERS, "duration": {"kind": "instant"}}, "SELF")
    assert actor.temporary_hp == 4
    engine, actor = _run({"effects": rows, "numbers": {**NUMBERS, "cl": 11}, "duration": {"kind": "instant"}}, "SELF")
    assert actor.temporary_hp == 6


# ---------------------------------------------------------------- the structure pass that made buffs look hostile
def test_gaining_temporary_hit_points_places_no_mark():
    for text in ("On a hit, the target gains Temporary Hit Points equal to your Proficiency Bonus.",
                 "The target gains 4d10 Temporary Hit Points.", "You gain PB Temporary Hit Points."):
        assert add_marks_from_text([], text) == [], text
    assert add_spend_mark_from_text([], "You may spend Temporary Hit Points to stay standing.") == []


def test_no_action_carries_a_hit_point_pool_as_a_mark():
    def rows(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from rows(child)
        elif isinstance(value, list):
            for child in value:
                yield from rows(child)

    bogus = [key for key, mechanic in AUTH.items()
             if (mechanic.get("activation") or {}).get("economy") in {"action", "bonus_action", "special"}
             and any(row.get("type") == "mark" and re.search(r"hit points?$", str(row.get("mark") or ""), re.I) for row in rows(mechanic.get("effects")))]
    assert bogus == []


def test_bell_strike_keeps_its_attack_when_it_no_longer_carries_a_hit_point_mark():
    # Removing the mark let the reaction-menu splitter drop this reaction's attack; the reviewed override restores it.
    mechanic = AUTH["tianxia.subpath.body.iron_shirt.feature.bell_strike"]
    assert not mechanic.get("options")
    attack = mechanic["effects"][0]
    assert attack["type"] == "attack"
    # rider lane C7 (Iron Shirt): the hit's "choose one" is an asked menu (path_results) of the printed results
    [menu] = attack["on_hit"]
    assert menu["type"] == "path_results"
    assert {row["type"] for option in menu["options"] for row in option["effects"]} >= {"forced_movement", "reaction_denied", "temp_hp"}
