"""Sphere typing review, sweep batch sw-yin (2026-09-28): the Yin sphere's typed mechanics against the owner's printed text.

Every test compiles a corrected ability and runs it through the engine; each fails on the typing the authority carried before
this review (58231d8).  What the old typing did, in a fight:

* Sovereign Yin Incarnation (a Bonus Action that changes the user's own area for a minute) compiled to two melee-range actions
  aimed at a foe -- one of them the user's own Temporary HP -- and made a Constitution save at the moment of casting, against
  every creature within 20 feet, marked or not.  It is a zone: a creature that *starts its turn* within 20 feet *while marked by
  the user* makes the save.
* Yin Domain hit every enemy at the moment of casting with damage, a Speed penalty and a permanent mark; the printed text gives
  the aura only "if they begin their turn with a Waning Mark, their Speed is reduced by 10 feet".
* No Dawn in the Wound never reduced any healing; Twofold Waning moved the user 30 feet and spent a mark it had no text for;
  Veil of Waning Breath (an obscuring area) marked its target for the rest of the fight; Moon-Ending Meridian Seal slowed
  creatures that carried no Waning Mark.
* Four reactions put the Waning Mark on the creature that *failed* its save (the text: on a *successful* one) and left it
  there for the rest of the fight (the text: until the end of the marker's next turn, or a minute); Preserving Yin never held
  the ally at 1 Hit Point; two never spent the mark they say to spend.
"""

import copy
from functools import lru_cache

from combat import typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent, Position
from tests.test_auto_support import ME, _engine
from tests.test_reaction_effects_r6 import REACTOR, ROOT, SHEET as REACTION_SHEET, _typed_action, _use
from tests.test_zones import SHEET

YIN = "tianxia.sphere.yin"
MARKING = "TAL_YIN_MARKING_A_CREATURE"  # "Mark the Waning": the Waning Mark itself
SOVEREIGN, DOMAIN, NO_DAWN = "TAL_YIN_SOVEREIGN_YIN_INCARNATION", "TAL_YIN_YIN_DOMAIN_COURT_OF_WANING_RETURN", "TAL_YIN_NO_DAWN_IN_THE_WOUND"
TWOFOLD, VEIL, MERIDIAN = "TAL_YIN_TWOFOLD_WANING", "TAL_YIN_VEIL_OF_WANING_BREATH", "TAL_YIN_MOON_ENDING_MERIDIAN_SEAL"
ARRIVES, UNFINISHED = "TAL_YIN_THE_ACTION_ARRIVES_INCOMPLETE", "tianxia.talent.yin.the_unfinished_action_beneath_heaven"
WORLD, PRESERVING, DEPARTURE = "TAL_YIN_THE_WORLD_RECEIVES_THE_BLOW", "TAL_YIN_PRESERVING_YIN", "TAL_YIN_INCOMPLETE_DEPARTURE"
FAILS, PASSES = 30, 1  # the foe's saving throw (a d20 + a small modifier) against this DC never / always makes it
MARK_CONDITION = "condition:typed.mark.waning_mark"
NEXT_TURN_OF_THE_MARKER = "END_OF_MARKER_NEXT_TURN"  # "A Waning Mark lasts until the end of your next turn" (Mark Limit)


@lru_cache(maxsize=None)
def _compiled(talent: str, dc: int, reaction: bool = False) -> dict:
    sheet, actor = (REACTION_SHEET, REACTOR) if reaction else (SHEET, ME)
    stats = {**sheet["ability_scores_and_statistics"], "technique_save_dc": dc}
    return compile_character({**sheet, "equipment": [], "ability_scores_and_statistics": stats,
                              "spheres_and_talents": {"sphere_record_ids": [YIN], "learned_talent_record_ids": [MARKING, talent]}}, actor_id=actor)


def _fight(talent: str, dc: int = FAILS, foe_at=(4, 6)):
    """The Yin character (at 3,6) against one foe (AN); the foe is first in the round."""
    bundle = copy.deepcopy(_compiled(talent, dc))
    return bundle, _engine(bundle, foe_at=foe_at)


def _reaction_fight(talent: str, dc: int = FAILS):
    """The reactor, its ally (LEE) and the foe (AN): each reacts through the row the compiler built for it."""
    engine = Gate2Engine(ROOT, match_seed="R6", typed_bundles=(copy.deepcopy(_compiled(talent, dc, True)),),
                         roster_setup={"primary_actor_ids": [REACTOR, LEE, AN], "team_by_actor": {REACTOR: "team:a", LEE: "team:a", AN: "team:b"}})
    engine.typed_actor_ids = {*engine.typed_actor_ids, LEE}
    for actor_id, x in ((REACTOR, 5), (LEE, 6), (AN, 9)):
        engine.state.actors[actor_id].position = Position(x=x, y=6)
    return engine


def _row(bundle: dict, prefix: str) -> dict:
    return next(row for row in bundle["action_catalog"] if row["display_name"].startswith(prefix))


def _reaction_row(bundle: dict, feature_id: str) -> dict:
    return next(row for row in bundle["typed_reactions"] if row["feature_id"] == feature_id)


def _cast(engine, prefix: str) -> None:
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith(prefix))
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _foes_turn(engine) -> None:
    engine.end_turn()  # the caster's turn is over; the foe's begins (its start-of-turn zone triggers run)
    assert engine.state.current_actor_id == AN


def _events(engine, *kinds):
    return [event for event in engine.events if event.event_type in kinds]


def _mark(engine, foe, marker: str = ME) -> None:
    """A Waning Mark from ``marker`` on ``foe`` -- Mark the Waning's own result -- through the executor."""
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, engine.state.actors[marker], action, None, {"numbers": {}, "effects": []}, [foe], foe, {})
    typed_executor.run_effects(ctx, [{"type": "mark", "mark": "Waning Mark", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}}])


def _marks(actor) -> list[str]:
    return [row.expires_on for row in actor.conditions.values() if row.condition_id.startswith(MARK_CONDITION)]


def _denied(actor) -> bool:
    return any(row.condition_id == "condition:typed.reaction_denied" for row in actor.conditions.values())


def _heal(engine, subject, amount: int = 20, source: str = ME) -> int:
    """Hit Points that ``amount`` of healing gives ``subject`` right now (its healing modifiers apply)."""
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, engine.state.actors[source], action, None, {"numbers": {"pb": 4}}, [subject], subject, {})
    subject.current_hp = 10
    typed_executor.block_healing(ctx, {"type": "healing", "flat": amount, "applies_to": "target"})
    return subject.current_hp - 10


# ---- Sovereign Yin Incarnation ---------------------------------------------------------------------------------------------


def test_sovereign_yin_incarnation_is_one_self_cast_that_saves_nothing_when_cast():
    bundle, engine = _fight(SOVEREIGN)
    assert [c.display_name.split(" — Hits allies too:")[0] for c in engine.legal_candidates() if "Sovereign" in c.display_name] == ["Sovereign Yin Incarnation"]
    row = _row(bundle, "Sovereign")
    assert (row["economy"], row["target_kind"]) == ("BONUS_ACTION", "SELF")  # not "...: Temporary HP" aimed at an enemy in reach
    _cast(engine, "Sovereign Yin Incarnation")
    foe = engine.state.actors[AN]
    assert not _events(engine, "SAVE_ROLLED")  # the save is a creature's, at the start of its turn
    assert engine._effective_speed(foe) == 30 and not foe.modifiers and not foe.conditions


def test_sovereign_marked_creature_that_fails_starting_its_turn_in_the_aura_loses_reactions_and_20_feet():
    _, engine = _fight(SOVEREIGN, FAILS)
    _cast(engine, "Sovereign Yin Incarnation")
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _foes_turn(engine)
    assert len(_events(engine, "SAVE_ROLLED")) == 1
    assert _denied(foe) and engine._effective_speed(foe) == 10  # "cannot take Reactions and its Speed is reduced by 20 feet"


def test_sovereign_marked_creature_that_saves_loses_only_10_feet():
    _, engine = _fight(SOVEREIGN, PASSES)
    _cast(engine, "Sovereign Yin Incarnation")
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _foes_turn(engine)
    assert len(_events(engine, "SAVE_ROLLED")) == 1
    assert not _denied(foe) and engine._effective_speed(foe) == 20  # "On a successful save, its Speed is reduced by 10 feet"


def test_sovereign_ignores_a_creature_it_has_not_marked_and_one_beyond_20_feet():
    _, engine = _fight(SOVEREIGN, FAILS)
    _cast(engine, "Sovereign Yin Incarnation")
    foe = engine.state.actors[AN]
    _foes_turn(engine)  # in the aura, unmarked
    assert not _events(engine, "SAVE_ROLLED") and engine._effective_speed(foe) == 30 and not _denied(foe)
    _, engine = _fight(SOVEREIGN, FAILS, foe_at=(9, 6))  # 30 feet away, marked
    _cast(engine, "Sovereign Yin Incarnation")
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _foes_turn(engine)
    assert not _events(engine, "SAVE_ROLLED") and engine._effective_speed(foe) == 30 and not _denied(foe)


# ---- Yin Domain: Court of Waning Return --------------------------------------------------------------------------------------


def test_yin_domain_does_nothing_to_enemies_at_the_moment_of_casting():
    _, engine = _fight(DOMAIN)
    foe = engine.state.actors[AN]
    hp = foe.current_hp
    _cast(engine, "Yin Domain")
    assert foe.current_hp == hp and not _events(engine, "SAVE_ROLLED", "DAMAGE_COMMITTED")  # was: PB cold/necrotic damage at cast
    assert engine._effective_speed(foe) == 30 and not foe.modifiers  # was: -10 Speed at cast
    assert not _marks(foe)  # was: a permanent Waning Mark at cast


def test_yin_domain_slows_only_a_marked_enemy_that_begins_its_turn_inside():
    _, engine = _fight(DOMAIN)
    _cast(engine, "Yin Domain")
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _foes_turn(engine)
    assert engine._effective_speed(foe) == 20  # "if they begin their turn with a Waning Mark, their Speed is reduced by 10 feet"
    _, engine = _fight(DOMAIN)
    _cast(engine, "Yin Domain")
    foe = engine.state.actors[AN]
    _foes_turn(engine)  # unmarked
    assert engine._effective_speed(foe) == 30
    _, engine = _fight(DOMAIN, foe_at=(11, 6))  # marked, 40 feet away: outside the 30-foot aura
    _cast(engine, "Yin Domain")
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _foes_turn(engine)
    assert engine._effective_speed(foe) == 30


# ---- No Dawn in the Wound ---------------------------------------------------------------------------------------------------


def test_no_dawn_reduces_a_marked_targets_healing_until_the_concentration_ends():
    bundle, engine = _fight(NO_DAWN, FAILS)
    row = _row(bundle, "No Dawn")
    assert (row["target_kind"], row["range_ft"], row["concentration"]) == ("HOSTILE_ENTITY", 60, True)  # aimed at a foe, not the user
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _cast(engine, "No Dawn")
    assert len(_events(engine, "SAVE_ROLLED")) == 1
    assert [(m.target_field, m.value, m.expires_on) for m in foe.modifiers.values()] == [("healing_reduction", "minus:4", "CONCENTRATION_END")]
    assert _heal(engine, foe, 20) == 16  # reduced by the Proficiency Bonus (the Key Ability modifier is not modelled)
    engine._end_concentration(engine.state.actors[ME], "TEST")
    assert not foe.modifiers and _heal(engine, foe, 20) == 20


def test_no_dawn_does_nothing_to_a_target_that_saves_or_that_carries_no_mark():
    # A control on the corrected typing (the old row was inert, so it held there too): the save and the mark gate both matter.
    _, engine = _fight(NO_DAWN, PASSES)
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _cast(engine, "No Dawn")
    assert not foe.modifiers and _heal(engine, foe, 20) == 20  # a successful save
    _, engine = _fight(NO_DAWN, FAILS)
    foe = engine.state.actors[AN]
    _cast(engine, "No Dawn")  # "Choose one creature that currently has one of your Waning Marks": this one has none
    assert not foe.modifiers and _heal(engine, foe, 20) == 20


# ---- Twofold Waning ---------------------------------------------------------------------------------------------------------


def test_twofold_waning_marks_two_creatures_without_the_old_unprinted_movement():
    bundle, engine = _fight(TWOFOLD)
    row = _row(bundle, "Twofold Waning")
    assert [r['type'] for r in row['parameters']['typed']['effects']] == ['yin_twofold']
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    start = me.position
    _cast(engine, "Twofold Waning")
    assert me.position == start and _marks(foe) and not foe.modifiers
    assert sum(bool(_marks(actor)) for actor in engine.state.actors.values()) == 2


# ---- Veil of Waning Breath --------------------------------------------------------------------------------------------------


def test_veil_of_waning_breath_makes_an_area_and_marks_nobody():
    bundle, engine = _fight(VEIL)
    # "When a creature inside the area gains a Waning Mark, you may choose ..." is the second paragraph's trigger, not an effect of the
    # first: the area marks nobody.  (The old typing read it as a permanent mark on the target; a cast at a cell has no creature target, so
    # that mark never landed -- the typed data is what was wrong.)
    assert [effect["type"] for effect in _row(bundle, "Veil")["parameters"]["typed"]["effects"]] == ["zone"]
    foe = engine.state.actors[AN]
    _cast(engine, "Veil of Waning Breath")
    assert _events(engine, "ZONE_CREATED") and not _marks(foe)


# ---- Moon-Ending Meridian Seal ----------------------------------------------------------------------------------------------


def test_meridian_seal_slows_a_marked_target_that_fails_by_20_feet_for_a_minute():
    bundle, engine = _fight(MERIDIAN, FAILS)
    assert [row["display_name"] for row in bundle["action_catalog"] if row["display_name"].startswith("Moon-Ending")] == ["Moon-Ending Meridian Seal"]
    row = _row(bundle, "Moon-Ending")
    assert (row["target_kind"], row["range_ft"]) == ("HOSTILE_ENTITY", 60)
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _cast(engine, "Moon-Ending")
    assert len(_events(engine, "SAVE_ROLLED")) == 1 and engine._effective_speed(foe) == 10
    assert [m.expires_on for m in foe.modifiers.values()] != ["UNTIL_REMOVED"]  # "for 1 minute": a round count, not the whole fight


def test_meridian_seal_does_nothing_to_a_target_that_saves_or_that_carries_no_mark():
    _, engine = _fight(MERIDIAN, PASSES)
    foe = engine.state.actors[AN]
    _mark(engine, foe)
    _cast(engine, "Moon-Ending")
    assert engine._effective_speed(foe) == 30
    _, engine = _fight(MERIDIAN, FAILS)
    foe = engine.state.actors[AN]
    _cast(engine, "Moon-Ending")  # "Choose one creature within range that currently has one of your Waning Marks"
    assert engine._effective_speed(foe) == 30


# ---- The reactions ----------------------------------------------------------------------------------------------------------


def _foe_uses_an_ability(engine, target: str = LEE) -> None:
    """The foe (AN) takes an Action -- one typed ability that deals 1 damage -- so its Action completes (creature_acted) and,
    being a technique, is declared first (technique_used)."""
    _use(engine, AN, _typed_action(engine, AN, [{"type": "damage", "flat": 1, "applies_to": "target", "damage_types": ["slashing"]}]), target)


def test_the_action_arrives_incomplete_spends_the_mark_and_gives_a_new_one_only_on_a_successful_save():
    engine = _reaction_fight(ARRIVES, FAILS)
    foe = engine.state.actors[AN]
    _mark(engine, foe, REACTOR)
    _foe_uses_an_ability(engine)
    assert not _marks(foe)  # "Spend the creature's Waning Mark"; a failed save gives no new one (was: a mark, until removed, on the failure)
    assert not engine.state.actors[REACTOR].reaction_available
    engine = _reaction_fight(ARRIVES, PASSES)
    foe = engine.state.actors[AN]
    _mark(engine, foe, REACTOR)
    _foe_uses_an_ability(engine)
    assert _marks(foe) == [NEXT_TURN_OF_THE_MARKER]  # "On a successful save ... the target gains a Waning Mark": the ordinary one


def test_the_action_arrives_incomplete_answers_only_a_marked_creature():
    # A control (it held under the old typing as well): the reaction is Mark-gated and stays unspent for an unmarked creature.
    engine = _reaction_fight(ARRIVES, FAILS)
    _foe_uses_an_ability(engine)
    assert engine.state.actors[REACTOR].reaction_available and not _marks(engine.state.actors[AN])


def test_the_unfinished_action_marks_the_source_for_a_minute_only_when_its_save_succeeds():
    engine = _reaction_fight(UNFINISHED, FAILS)
    foe = engine.state.actors[AN]
    _foe_uses_an_ability(engine)
    assert len(_events(engine, "SAVE_ROLLED")) == 1 and not _marks(foe)  # was: the Waning Mark on the source that FAILED
    engine = _reaction_fight(UNFINISHED, PASSES)
    foe = engine.state.actors[AN]
    _foe_uses_an_ability(engine)
    marks = _marks(foe)
    assert len(marks) == 1 and marks[0] not in ("UNTIL_REMOVED", NEXT_TURN_OF_THE_MARKER)  # "lasts for 1 minute": ten rounds


def test_the_world_receives_the_blow_marks_the_damaging_creature_until_the_end_of_the_marker_next_turn():
    engine = _reaction_fight(WORLD)
    foe = engine.state.actors[AN]
    typed_reactions.after_technique(engine, foe, {REACTOR, LEE})  # one effect damaged two creatures
    assert _marks(foe) == [NEXT_TURN_OF_THE_MARKER]  # was: until removed
    assert not engine.state.actors[REACTOR].reaction_available
    engine = _reaction_fight(WORLD)
    typed_reactions.after_technique(engine, engine.state.actors[AN], {LEE})  # one creature: not its trigger
    assert not _marks(engine.state.actors[AN])


def test_preserving_yin_holds_the_ally_at_1_hit_point_bars_healing_and_marks_it():
    engine = _reaction_fight(PRESERVING)
    ally = engine.state.actors[LEE]
    ally.current_hp = 5
    _foe_uses_an_ability_with(engine, damage=20)
    assert ally.current_hp == 1 and ally.active  # "The creature drops to 1 Hit Point instead of 0"
    assert _marks(ally) == [NEXT_TURN_OF_THE_MARKER]  # "You place a Waning Mark on the triggering creature"
    assert _heal(engine, ally, 10, REACTOR) == 0  # "Until the start of your next turn, it cannot regain Hit Points"
    expiries = [m.expires_on for m in ally.modifiers.values() if m.target_field == "healing_reduction"]
    assert len(expiries) == 1 and expiries[0].startswith(f"START_OF_TURN_AT:{REACTOR}")  # the reactor's next turn


def test_preserving_yin_leaves_an_ally_that_is_not_dropping_alone():
    # A control (it held under the old typing as well): the reaction answers "drops to 0", not any damage.
    engine = _reaction_fight(PRESERVING)
    ally = engine.state.actors[LEE]
    hp = ally.current_hp
    _foe_uses_an_ability_with(engine, damage=20)
    assert ally.current_hp == hp - 20 and not _marks(ally) and engine.state.actors[REACTOR].reaction_available


def _foe_uses_an_ability_with(engine, damage: int) -> None:
    _use(engine, AN, _typed_action(engine, AN, [{"type": "damage", "flat": damage, "applies_to": "target", "damage_types": ["slashing"]}]), LEE)


def test_incomplete_departure_spends_the_mark_before_the_save_and_answers_a_success_with_no_reactions():
    row = _reaction_row(_compiled(DEPARTURE, FAILS, True), DEPARTURE)
    spend, save = row["effects"]  # "Spend the creature's Waning Mark. The target makes a Wisdom saving throw."
    assert (spend["type"], spend["mark"]) == ("spend_mark", "Waning Mark")
    assert (save["type"], save["ability"], save["on_fail"]) == ("save", "wis", [])  # the halved teleport is a table ruling
    assert [effect["type"] for effect in save["on_success"]] == ["reaction_denied"]  # "cannot take Reactions until the start of its next turn"
    assert (row["kind"], row["requires_mark"], row["range_ft"]) == ("moved", "*", 90)
