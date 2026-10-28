"""Parser rows that a typed row already states (the fight audit's "parser duplicate rows" finding).

The parser reads what it can of a line and states no subject and no duration; the models then type the same line with both.  The
structured pass (typed_structure.from_v2) put the parser's row back beside the model's whenever the two disagreed on ``condition``
("none" from a model, nothing from the parser), and the copy had no duration: Furnace Step's +10 Speed ran twice and one copy never
ended, Joint Seal's -10 Speed stayed on its target for the fight.  ``drop_restated_parser_rows`` (run once at the end of the build)
removes the parser's copy when a typed row of the same delivery surface states the same effect on the same printed line; a parser
row that is the only typing of its line stays, and a reviewed_final mechanic is never touched.

The first half tests that pass on hand-built mechanics, the second checks the built authority and casts the abilities the audit
named through the fight engine."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import TYPED_AUTHORITY
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from factory_authoring.typed_structure import drop_restated_parser_rows, from_v2
from tests.test_auto_shi import ME as SHI, _bundle as _shi_bundle, _engine as _shi_engine, _hit_with_dao
from tests.test_auto_support import ME as SUPPORT
from tests.test_expiry_fixes_data import _cast

APP = Path(__file__).resolve().parents[1]
RULES_TEXT = APP / "authority/typed_mechanics/rules_text.json"


def _typed(kind, evidence, origin="model_v2", **fields):
    """A row as a model writes it: every field spelled out (condition "none"), the number as "flat", a duration."""
    return {"type": kind, "applies_to": "self", "flat": 0, "formula": "none", "damage_types": [], "ability": "none", "condition": "none",
            "distance_ft": 0, "on": "", "duration": "instant", "origin": origin, "evidence": evidence, **fields}


def _parsed(kind, evidence, **fields):
    """A row as the parser reads it: no subject, no condition, no duration, the number as "amount"."""
    return {"type": kind, "origin": "parser", "evidence": evidence, **fields}


def _mechanic(effects, status="model_v2_unchecked", **surfaces):
    return {"key": "X", "typing_status": status, "effects": effects, **surfaces}


def _left(mechanic, surface="effects"):
    return [(row["type"], row.get("origin")) for row in mechanic[surface]]


def _unchanged(mechanic, text):
    before = copy.deepcopy(mechanic)
    assert drop_restated_parser_rows(mechanic, text) == []
    assert mechanic == before


FURNACE = ("Until the end of your turn:\n• Speed increases by 10 feet;\n• ignore your own Molten Terrain;\n"
           "• do not provoke opportunity attacks from one creature of your choice;")


# ------------------------------------------------------------------ the pass on hand-built mechanics
def test_a_parser_row_the_model_typed_too_is_dropped_and_the_models_row_stays():
    typed = _typed("speed", "Speed increases by 10 feet", flat=10, duration="until_end_of_turn")
    parsed = _parsed("speed", "Speed increases by 10 feet", amount=10)
    mechanic = _mechanic([typed, _typed("zone", "leave one 5-foot patch of Molten Terrain", distance_ft=5), parsed])
    assert drop_restated_parser_rows(mechanic, FURNACE) == [parsed]
    assert _left(mechanic) == [("speed", "model_v2"), ("zone", "model_v2")]
    assert mechanic["effects"][0] == typed


def test_the_structured_pass_puts_the_parsers_copy_back_and_the_build_drops_it():
    """The defect where it started: the model's row says condition "none", the parser's says nothing, and from_v2 took them for
    two effects.  Whichever pass ends up removing the copy, the built mechanic must state the Speed bonus once, as the model typed it."""
    model = {"type": "speed", "applies_to": "self", "flat": 10, "formula": "none", "damage_types": [], "ability": "none", "condition": "none",
             "distance_ft": 0, "on": "", "duration": "until_end_of_turn", "evidence": "Speed increases by 10 feet"}
    tree = from_v2({"delivery": "automatic", "effects": [model]}, [_parsed("speed", "Speed increases by 10 feet", amount=10)], FURNACE)
    mechanic = _mechanic(tree)
    drop_restated_parser_rows(mechanic, FURNACE)
    assert _left(mechanic) == [("speed", "model_v2")]
    assert mechanic["effects"][0]["duration"] == "until_end_of_turn"


def test_a_parser_row_that_is_the_only_typing_of_its_line_stays():
    slow = _parsed("speed", "Speed is reduced by 10 feet", amount=-10)
    hold = _typed("reaction_denied", "it cannot take Opportunity Attacks", applies_to="target", duration="until_start_of_next_turn")
    _unchanged(_mechanic([slow, hold]), "Speed is reduced by 10 feet. It cannot take Opportunity Attacks.")
    _unchanged(_mechanic([slow]), "Speed is reduced by 10 feet.")


@pytest.mark.parametrize("parsed, typed, text", [
    pytest.param(_parsed("speed", "Speed increases by 10 feet", amount=10), _typed("speed", "Speed increases by 10 feet", flat=20),
                 "Speed increases by 10 feet.", id="another-number"),
    pytest.param(_parsed("speed", "Your Speed increases by 10 feet", amount=10), _typed("speed", "Your mount's Speed increases by 10 feet", flat=10),
                 "Your Speed increases by 10 feet. Your mount's Speed increases by 10 feet.", id="another-line"),
    pytest.param(_parsed("condition", "is Stunned", condition="stunned"), _typed("condition", "is Stunned", applies_to="target", condition="prone"),
                 "The target is Stunned.", id="another-condition"),
    pytest.param(_parsed("ac_bonus", "+2 AC", amount=2), _typed("speed", "+2 AC", flat=2), "Gain +2 AC.", id="another-type"),
    pytest.param(_parsed("condition", "is Restrained", condition="restrained", repeat_save={"ability": "str"}),
                 _typed("condition", "is Restrained", applies_to="target", condition="restrained"),
                 "The target is Restrained and repeats the save each turn.", id="the-parser-says-more"),
    pytest.param(_parsed("advantage", "Stealth checks", on="Stealth checks"), _typed("advantage", "Athletics checks", on="Athletics checks"),
                 "Gain Advantage on Stealth checks and Athletics checks.", id="another-roll"),
])
def test_a_row_that_differs_from_the_typed_one_is_not_its_copy(parsed, typed, text):
    _unchanged(_mechanic([typed, parsed]), text)


def test_a_temp_hp_sum_the_model_typed_as_two_rows_is_not_a_copy_of_either():
    """"Temporary HP equal to your PB + your key ability modifier" is one parser row but two model rows, and a grant takes the larger
    of them, not their sum: dropping the parser's row would change the amount."""
    text = "The target gains Temporary HP equal to your Proficiency Bonus + your Key Ability modifier."
    total = _parsed("temp_hp", "gains Temporary HP equal to your Proficiency Bonus + your Key Ability modifier", dice=None,
                    formula="text:your proficiency bonus + your key ability modifier")
    pb = _typed("temp_hp", "Temporary HP equal to your Proficiency Bonus + your Key Ability modifier", applies_to="target", formula="pb")
    key = _typed("temp_hp", "Temporary HP equal to your Proficiency Bonus + your Key Ability modifier", applies_to="target",
                 formula="key_ability_modifier")
    _unchanged(_mechanic([total, pb, key]), text)


@pytest.mark.parametrize("text, dropped", [
    pytest.param("An ally within 30 feet gains +2 AC until the start of your next turn.", True, id="ally-only"),
    pytest.param("You and one ally within 30 feet gain +2 AC until the start of your next turn.", False, id="caster-too"),
])
def test_the_casters_own_share_is_not_a_copy_of_the_allys_row(text, dropped):
    """The parser states no subject, so its bonus lands on the caster; when the text gives it to an ally, the model's ally row
    is the whole of it and the parser's is a wrong copy -- unless the text names the caster among the recipients."""
    ally = _typed("ac_bonus", "+2 AC until the start of your next turn", applies_to="ally", flat=2, duration="until_start_of_next_turn")
    mine = _parsed("ac_bonus", "+2 AC", amount=2)
    mechanic = _mechanic([ally, mine])
    if dropped:
        assert drop_restated_parser_rows(mechanic, text) == [mine]
        assert mechanic["effects"] == [ally]
    else:
        _unchanged(mechanic, text)


@pytest.mark.parametrize("text, dropped", [
    pytest.param("Inside the Domain, you and allies you designate gain the following benefits:\nResistance to Necrotic damage;\n"
                 "Advantage on saving throws against Charmed.", False, id="the-lead-in-names-the-caster"),
    pytest.param("Choose an ally or yourself:\nResistance to Necrotic damage.", False, id="the-lead-in-offers-yourself"),
    pytest.param("Inside the Domain, allies you designate gain the following benefits:\nResistance to Necrotic damage;\n"
                 "Advantage on saving throws against Charmed.", True, id="the-lead-in-names-allies-only"),
    pytest.param("When a commanded ally begins its turn within 5 feet of you it gains one of the following benefits:\n"
                 "Resistance to Necrotic damage;\nremove the Frightened condition if the ally can see or hear you and the source is weaker.",
                 True, id="another-bullet-mentions-you"),
    pytest.param("A willing creature within 5 feet of yourself or one of your Anchors gains:\nResistance to Necrotic damage.", True,
                 id="yourself-is-a-distance"),
])
def test_a_bullet_is_read_with_the_lead_in_that_names_its_recipients(text, dropped):
    """Court of Unshadowed Dawn says "you and allies you designate gain the following benefits:" and lists each benefit on a line of
    its own, so the line that quotes "Resistance to Necrotic damage" never says who gets it.  The model typed the benefit for allies
    and the parser's row lands on the caster: that row is the caster's own share, and only the lead-in shows it."""
    ally = _typed("resistance", "Resistance to Necrotic damage", applies_to="ally", damage_types=["necrotic"], duration="concentration")
    mine = _parsed("resistance", "Resistance to Necrotic damage", damage_types=["necrotic"])
    mechanic = _mechanic([ally, mine])
    if dropped:
        assert drop_restated_parser_rows(mechanic, text) == [mine]
        assert mechanic["effects"] == [ally]
    else:
        _unchanged(mechanic, text)


def test_reaction_denied_is_one_effect_however_it_is_written():
    parsed = _parsed("condition", "cannot take Reactions", condition="reaction_denied")
    typed = _typed("reaction_denied", "and cannot take Reactions", applies_to="target", duration="one_round")
    mechanic = _mechanic([parsed, typed])
    assert drop_restated_parser_rows(mechanic, "On a hit the target takes 2d6 damage and cannot take Reactions.") == [parsed]
    assert _left(mechanic) == [("reaction_denied", "model_v2")]


@pytest.mark.parametrize("direction, dropped", [("away", True), ("toward", False)])
def test_a_push_is_away_unless_the_typed_row_says_toward(direction, dropped):
    parsed = _parsed("forced_movement", "Push it 5 feet", distance_ft=5)
    typed = _typed("forced_movement", "Push it 5 feet", applies_to="target", distance_ft=5, direction=direction)
    mechanic = _mechanic([typed, parsed])
    if dropped:
        assert drop_restated_parser_rows(mechanic, "Push it 5 feet.") == [parsed]
    else:
        _unchanged(mechanic, "Push it 5 feet.")


def test_a_movement_that_provokes_nothing_hands_the_flag_to_the_typed_row():
    """The parser reads "does not provoke" itself; the model's movement row does not, so it takes the flag when the parser's goes."""
    text = "You move up to 30 feet in a straight line. This movement does not provoke Opportunity Attacks."
    typed = _typed("movement", "You move up to 30 feet in a straight line", distance_ft=30, flat=30)
    parsed = _parsed("movement", "move up to 30 feet", mode="move", distance_ft=30, no_opportunity_attacks=True)
    mechanic = _mechanic([typed, parsed])
    assert "no_opportunity_attacks" not in typed
    assert drop_restated_parser_rows(mechanic, text) == [parsed]
    assert len(mechanic["effects"]) == 1 and mechanic["effects"][0]["distance_ft"] == 30
    assert mechanic["effects"][0]["no_opportunity_attacks"] is True


DEX_TEXT = ("Creatures in a 10-foot-radius sphere make a Dexterity saving throw. On a failed save, a creature takes 10d10 lightning damage "
            "and is Stunned until the end of its next turn. On a successful save, it takes half damage and is not Stunned.")
DICE = {"count": 10, "sides": 10}


def _save(origin, ability="dex", on_fail=(), on_success=()):
    return {"type": "save", "ability": ability, "dc": "technique_save_dc", "origin": origin, "on_fail": list(on_fail), "on_success": list(on_success)}


def _banner():
    """Heaven Breaks the Banner as the earlier passes leave it: the parser's Dexterity save and the model's, each with its damage, its
    Stun and its half damage.  The rows inside the parser's save carry no origin (the parser stamps only the rows it puts at the top)."""
    parsed = _save("parser", on_fail=[{"type": "damage", "dice": DICE, "damage_types": ["lightning"], "evidence": "takes 10d10 lightning damage"},
                                      {"type": "condition", "condition": "stunned", "evidence": "is Stunned"}],
                   on_success=[{"type": "half_damage", "evidence": "takes half damage"}])
    typed = _save("model_v2", on_fail=[{"type": "damage", "dice": DICE, "damage_types": ["lightning"], "evidence": "takes 10d10 lightning damage"},
                                       _typed("condition", "and is Stunned until the end of its next turn.", origin="model", applies_to="target",
                                              condition="stunned", duration="one_round")],
                 on_success=[{"type": "half_damage", "origin": "model_v2"}])
    return parsed, typed


def test_a_parser_save_a_typed_save_states_goes_with_everything_in_it():
    """A save rolls once per copy: both saves ran, so the damage and the Stun were doubled and each was rolled for separately."""
    parsed, typed = _banner()
    mechanic = _mechanic([parsed, typed])
    dropped = drop_restated_parser_rows(mechanic, DEX_TEXT)
    assert [row["type"] for row in dropped] == ["save", "damage", "condition", "half_damage"]
    assert mechanic["effects"] == [typed]  # the typed save is exactly as it was


def test_a_parser_save_that_holds_something_only_it_types_stays_whole():
    parsed, typed = _banner()
    parsed["on_fail"].append({"type": "condition", "condition": "prone", "evidence": "is knocked Prone"})
    _unchanged(_mechanic([parsed, typed]), DEX_TEXT + " It is knocked Prone.")


def test_the_parsers_half_damage_needs_a_half_damage_in_the_typed_save():
    parsed, typed = _banner()
    typed["on_success"] = []
    _unchanged(_mechanic([parsed, typed]), DEX_TEXT)


@pytest.mark.parametrize("typed_ability, dropped", [("dex", True), ("con", False), (None, False)])
def test_a_bare_parser_save_goes_only_beside_a_typed_save_of_its_ability(typed_ability, dropped):
    parsed = _save("parser")
    effects = [parsed] + ([_save("model_v2", ability=typed_ability, on_fail=[_typed("condition", "is Stunned", applies_to="target",
                                                                                  condition="stunned")])] if typed_ability else [])
    mechanic = _mechanic(effects)
    if dropped:
        assert drop_restated_parser_rows(mechanic, "The target makes a Dexterity saving throw. Failed Save: is Stunned.") == [parsed]
        assert _left(mechanic) == [("save", "model_v2")]
    else:
        _unchanged(mechanic, "The target makes a Dexterity saving throw. Failed Save: is Stunned.")


def test_a_row_is_a_copy_only_of_a_row_in_its_own_branch():
    prone = lambda origin: {"type": "condition", "condition": "prone", "applies_to": "target", "origin": origin, "evidence": "is knocked Prone"}  # noqa: E731
    text = "Failed Save: is knocked Prone. Successful Save: is knocked Prone."
    _unchanged(_mechanic([_save("model_v2", on_fail=[prone("model_v2")], on_success=[prone("parser")])]), text)
    same = _mechanic([_save("model_v2", on_fail=[prone("model_v2"), prone("parser")])])
    assert [row["origin"] for row in drop_restated_parser_rows(same, text)] == ["parser"]
    assert [row["origin"] for row in same["effects"][0]["on_fail"]] == ["model_v2"]


@pytest.mark.parametrize("path", [("effects",), ("options", 0, "effects"), ("modifier", "effects"), ("modifier", "options", 0, "effects")],
                         ids=["effects", "an-option", "the-modifier", "a-modifier-option"])
def test_every_delivery_surface_is_cleaned(path):
    typed = _typed("speed", "Speed increases by 10 feet", flat=10)
    parsed = _parsed("speed", "Speed increases by 10 feet", amount=10)
    mechanic = _mechanic([], options=[{"effects": []}], modifier={"effects": [], "options": [{"effects": []}]})
    surface = mechanic
    for part in path[:-1]:
        surface = surface[part]
    surface[path[-1]] = [typed, parsed]
    assert drop_restated_parser_rows(mechanic, "Speed increases by 10 feet.") == [parsed]
    assert surface[path[-1]] == [typed]


def test_a_row_is_a_copy_only_of_a_row_on_its_own_delivery_surface():
    typed = _typed("speed", "Speed increases by 10 feet", flat=10)
    parsed = _parsed("speed", "Speed increases by 10 feet", amount=10)
    for layout in ({"effects": [parsed], "modifier": {"effects": [typed]}},
                   {"effects": [parsed], "options": [{"effects": [typed]}]},
                   {"effects": [], "options": [{"effects": [typed]}, {"effects": [parsed]}]}):
        _unchanged({"key": "X", "typing_status": "model_v2_unchecked", **layout}, "Speed increases by 10 feet.")


def test_a_reviewed_final_mechanic_is_left_as_its_reviewer_wrote_it():
    typed = _typed("speed", "Speed increases by 10 feet", flat=10)
    parsed = _parsed("speed", "Speed increases by 10 feet", amount=10)
    _unchanged(_mechanic([typed, parsed], status="reviewed_final"), "Speed increases by 10 feet.")


def test_attacks_are_the_deliverys_scaffolding_and_are_never_dropped_as_copies():
    attack = lambda origin: {"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "origin": origin, "on_hit": [], "on_miss": []}  # noqa: E731
    _unchanged(_mechanic([attack("parser"), attack("model_v2")]), "Make a melee Cultivation Attack.")


def test_the_pass_is_idempotent_and_never_drops_a_typed_row():
    parsed, typed = _banner()
    speed = _typed("speed", "Speed increases by 10 feet", flat=10)
    copy_of_speed = _parsed("speed", "Speed increases by 10 feet", amount=10)
    mechanic = _mechanic([parsed, typed, speed, copy_of_speed])
    text = DEX_TEXT + " Speed increases by 10 feet."
    dropped = drop_restated_parser_rows(mechanic, text)
    assert [row["type"] for row in dropped] == ["save", "damage", "condition", "half_damage", "speed"]
    assert not any(row is typed or row is speed for row in dropped)
    assert mechanic["effects"] == [typed, speed]
    assert drop_restated_parser_rows(mechanic, text) == []


# ------------------------------------------------------------------ the built authority
@lru_cache(maxsize=None)
def _mechanics() -> dict:
    return json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]


def _rows(effects):
    for row in effects or []:
        if isinstance(row, dict):
            yield row
            for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
                yield from _rows(row.get(branch))


def test_the_built_authority_holds_no_parser_row_that_a_typed_row_states():
    """The pass is the last step of the build, so running it over the built file must find nothing: a file built without it (or
    before it) still carries the copies, and the abilities that read them run twice."""
    texts = json.loads(RULES_TEXT.read_text(encoding="utf-8"))
    left = {}
    for key, mechanic in _mechanics().items():
        dropped = drop_restated_parser_rows(copy.deepcopy(mechanic), texts.get(key) or texts.get(key.split("#")[0]) or "")
        if dropped:
            left[key] = [row.get("type") for row in dropped]
    assert not left, f"{len(left)} mechanics still carry a parser copy of a typed row (rebuild the authority): {dict(list(left.items())[:5])}"


def test_joint_seal_reduces_speed_once_and_the_reduction_ends():
    mechanic = _mechanics()["tianxia.talent.pressure_points.joint_seal"]
    speed = [row for row in _rows(mechanic["effects"]) if row.get("type") == "speed"]
    assert len(speed) == 1, "the parser's copy of the successful save's Speed reduction (no subject, no duration) is back"
    assert speed[0]["origin"] == "model_v2" and speed[0]["duration"] == "until_start_of_next_turn" and speed[0]["flat"] == -10


def test_numbing_point_states_each_of_its_effects_once():
    mechanic = _mechanics()["PRESSURE_POINTS_BASE_NUMBING_POINT"]
    kinds = [(row.get("type"), row.get("condition") if row.get("type") == "condition" else None) for row in _rows(mechanic["effects"])]
    assert len(kinds) == len(set(kinds)) and ("speed", None) in kinds


# ------------------------------------------------------------------ real casts through the fight engine
def _speed_modifiers(actor):
    """The Speed bonuses and penalties an actor carries, as (value, expiry)."""
    return sorted(((m.value, m.expires_on) for m in actor.modifiers.values() if m.target_field == "speed_ft"), key=str)  # None: it never ends


def _held(actor):
    return {c.condition_id.removeprefix("condition:typed."): c.expires_on for c in actor.conditions.values()}


SHI_TALENTS = ["PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING", "PRESSURE_POINTS_BASE_NUMBING_POINT", "tianxia.talent.pressure_points.joint_seal"]


def _numb_the_leg():
    """Shi picks Numbing Point (Numb Leg) and hits: her Touch the Point applies the Point to the target."""
    engine = _shi_engine(_shi_bundle(SHI_TALENTS))
    me, foe = engine.state.actors[SHI], engine.state.actors[AN]
    pick = next(c for c in engine.legal_candidates() if c.display_name == "Touch the Point: Numbing Point (Numb Leg)")
    engine.execute_intent(ActionIntent(intent_id="pick", decision_id=pick.decision_id, candidate_id=pick.candidate_id,
                                       state_version=pick.state_version, actor_id=SHI, target_ids=pick.target_ids))
    me.action_available = True
    assert _hit_with_dao(engine)
    return engine, me, foe


def _next_turn(engine, me):
    engine.state.current_actor_id = SHI
    engine._system_start_turn()
    me.action_available = True


def test_numbing_point_slows_its_target_once_and_it_wears_off_at_the_start_of_her_next_turn():
    engine, me, foe = _numb_the_leg()
    assert _speed_modifiers(foe) == [(-10, "START_OF_SOURCE_NEXT_TURN")]
    assert _held(foe)["no_opportunity_attacks"] == "START_OF_SOURCE_NEXT_TURN"
    assert engine._effective_speed(foe) == foe.speed_ft - 10
    _next_turn(engine, me)
    assert _speed_modifiers(foe) == [] and "no_opportunity_attacks" not in _held(foe)


def test_joint_seal_reduces_speed_by_one_step_and_leaves_none_behind():
    """Closing the Seal on the marked target: the successful save's "Speed is reduced by 10 feet until the start of your next turn".
    The parser's copy of that line had no duration, so the target kept a second -10 Speed for the rest of the fight."""
    engine, me, foe = _numb_the_leg()
    _next_turn(engine, me)  # the Point's own slow is over
    assert _hit_with_dao(engine)  # hitting the marked target closes the Seal
    assert _speed_modifiers(foe) == [(-10, "START_OF_SOURCE_NEXT_TURN")]
    assert engine._effective_speed(foe) == foe.speed_ft - 10
    _next_turn(engine, me)
    assert _speed_modifiers(foe) == []


# ------------------------------------------------------------------ Furnace Step (a reviewed_final snapshot, cleaned by hand)
FURNACE_STEP = "TAL_MAGMA_FURNACE_STEP"


def test_furnace_step_states_its_speed_bonus_once():
    """The expiry snapshot of Furnace Step held the model's "Speed increases by 10 feet" and the parser's copy of the same line
    (the snapshot had given the copy an expiry, but it was still a second +10).  A reviewed_final mechanic is outside the build
    pass, so the snapshot itself no longer carries the copy."""
    speed = [row for row in _rows(_mechanics()[FURNACE_STEP]["effects"]) if row.get("type") == "speed"]
    assert len(speed) == 1, "the parser's second copy of 'Speed increases by 10 feet' is back in the reviewed snapshot"
    assert speed[0]["flat"] == 10 and speed[0]["expires_on"] == "END_OF_CURRENT_TURN"


def test_furnace_step_adds_ten_speed_once_and_only_for_the_rest_of_the_turn():
    engine = _cast("tianxia.sphere.magma", FURNACE_STEP, "Furnace Step")
    caster = engine.state.actors[SUPPORT]
    assert _speed_modifiers(caster) == [(10, "END_OF_CURRENT_TURN")]
    assert engine._effective_speed(caster) == caster.speed_ft + 10
    engine.end_turn()  # the caster's turn is over
    assert _speed_modifiers(caster) == []
    assert engine._effective_speed(caster) == caster.speed_ft


# ------------------------------------------------------------------ "you and allies": the caster's own share
COURT_OF_UNSHADOWED_DAWN = "tianxia.talent.radiance.court_of_unshadowed_dawn"


def test_court_of_unshadowed_dawn_still_gives_its_caster_the_resistance_and_the_advantage_once():
    """"you and allies you designate gain the following benefits": the model typed the benefits for allies only, and the engine's
    ally subject leaves out the caster, so the parser's row (no subject: the caster) is the caster's only source of them.  A pass
    that dropped it as the ally row's copy took the benefits away from the very creature the text names first."""
    engine = _cast("tianxia.sphere.radiance", COURT_OF_UNSHADOWED_DAWN, "Court of Unshadowed Dawn")
    caster = engine.state.actors[SUPPORT]
    assert sorted((m.target_field, str(m.value)) for m in caster.modifiers.values()) == [("damage_resistance", "NECROTIC")]
    from combat import typed_executor, zones

    wards = [rule["save_against"] for rule in typed_executor.condition_rules(caster) if rule.get("save_against")]
    assert wards == [{"mode": "ADVANTAGE", "against": ["charmed", "frightened", "possession", "corruption"], "abilities": []}]
    # The review's spatial ward replaces a permanent, creation-time buff.
    caster.position = caster.position.model_copy(update={"x": 30})
    zones.sync_inside(engine)
    assert not [rule for rule in typed_executor.condition_rules(caster) if rule.get("save_against")]
    assert not [m for m in caster.modifiers.values() if m.target_field == "damage_resistance"]
