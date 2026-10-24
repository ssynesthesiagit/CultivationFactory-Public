"""How long an effect lasts (hunt 2026-09-29, bug 1: "effect-level durations are ignored"). A typed effect carries its own
duration -- a "duration" string and the printed words -- and combat/typed_executor.py read only effect["expires_on"] and the whole
ability's duration: Thunder That Answers First's "cannot take Reactions until the end of its next turn" ended with the turn it was
cast in (its Disadvantage never ended), and World as Canvas's "Speed is reduced by 10 feet until the start of its next turn" never
ended at all. effect_expiry() / stated_expiry() name the turn; combat/ext/effect_durations.py ends what the engine has no name for."""

import json

import pytest

from combat import typed_executor, typed_reactions
from combat.ext import effect_durations
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_docket import DARK, ME, ROOT, _my_turn, _sheet

MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
THUNDER = MECH["TAL_LIGHTNING_THUNDER_THAT_ANSWERS_FIRST"]["effects"][0]
CANVAS = MECH["tianxia.talent.ink.world_as_canvas"]["effects"]
ASH = MECH["TAL_MAGMA_BOILING_ASH_SKY"]["effects"]
# The cloud is a zone whose "starts its turn inside" trigger holds the Constitution save (typed so since the sw-lightning review;
# "A hostile creature that starts its turn inside makes a Constitution saving throw."), so the save is no longer ASH[1].
ASH_SAVE = ASH[0]["triggers"][0]["effects"][0]
LASTING = {"kind": "minutes", "amount": 1, "concentration": True}


@pytest.mark.parametrize("duration, deadline", [
    ({"kind": "until_start_of_next_turn"}, 8),
    ({"kind": "until_end_of_next_turn", "amount": 9}, 8),
    ({"kind": "turn"}, 8),
    ({"kind": "rounds", "amount": 3}, 10),
    ({"kind": "rounds"}, 8),
    ({"kind": "rounds", "amount": 0}, 8),
    ({"kind": "rounds", "amount": -2}, 8),
    ({"kind": "minutes", "amount": 2}, 27),
    ({"kind": "minutes", "amount": 0}, 17),
    ({"kind": "minutes", "amount": -2}, 17),
    ({"kind": "hours", "amount": 1}, 607),
    ({"kind": "scene"}, None),
    ({}, None),
])
def test_shared_docket_duration_preserves_integer_deadlines(duration, deadline):
    from types import SimpleNamespace

    engine = SimpleNamespace(state=SimpleNamespace(round_number=7))
    original = dict(duration)
    result = effect_durations.until_round(engine, duration)
    assert result == deadline
    assert result is None or type(result) is int
    assert duration == original and engine.state.round_number == 7


def _fight(seed="DURATIONS", engine_class=Gate4ControllerEngine):
    engine = engine_class(ROOT, match_seed=seed, typed_bundles=(compile_character(_sheet([*DARK]), actor_id=ME),),
                          roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                        "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    _my_turn(engine)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _ctx(engine, user, target, duration=None):
    action = engine.action_catalog[next(a for a in user.action_ids if a in engine.action_catalog)]
    typed = {"effects": [], "riders": [], "weapon": None, "duration": duration or {"kind": "instant"},
             "numbers": {"pb": 2, "cl": 5, "save_dc": 30, "attack_bonus": 5}}
    return typed_executor.Context(engine, user, action, None, typed, [target], target, {})


def _conditions(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == typed_executor.CONDITION_PREFIX + name]


def _modifiers(actor, field):
    return [m for m in actor.modifiers.values() if m.target_field == field]


def _end_turn(engine):
    engine.end_turn()
    return engine.state.current_actor_id


def _expiry(ctx, effect, subject=None, **kwargs):
    return typed_executor.effect_expiry(ctx, effect, subject or ctx.target, **kwargs)


# ------------------------------------------------------------------ the hunt's cases
def test_thunders_denial_lasts_through_the_end_of_its_next_turn():
    engine, me, foe = _fight()
    assert _end_turn(engine) == AN  # Thunder is a Reaction: it answers on the other creature's turn
    ctx = _ctx(engine, me, foe)
    typed_executor.run_effects(ctx, THUNDER["on_fail"])
    denied = _conditions(foe, "reaction_denied")
    assert [c.expires_on for c in denied] == [effect_durations.token("end", AN, foe.turns_started + 1)]  # not END_OF_HOLDER_NEXT_TURN
    disadvantage = _modifiers(foe, "attack_mode")
    assert [m.expires_on for m in disadvantage] == ["END_OF_CURRENT_TURN"]  # "the triggering technique's attack roll": this turn's
    assert _end_turn(engine) == ME
    assert _conditions(foe, "reaction_denied") and not _modifiers(foe, "attack_mode")  # its turn is over; the denial is not
    assert _end_turn(engine) == AN
    assert _conditions(foe, "reaction_denied")  # still cannot take Reactions through its whole next turn
    assert _end_turn(engine) == ME
    assert not _conditions(foe, "reaction_denied")  # ... until the end of it
    removed = [e for e in engine.events if e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id", "").endswith("reaction_denied")]
    assert removed and removed[-1].target_ids == (AN,) and removed[-1].payload["instance_id"] == denied[0].instance_id  # what a replay reads


def test_thunders_saved_denial_ends_at_the_start_of_its_next_turn():
    engine, me, foe = _fight()
    _end_turn(engine)
    typed_executor.run_effects(_ctx(engine, me, foe), THUNDER["on_success"])
    assert [c.expires_on for c in _conditions(foe, "reaction_denied")] == [effect_durations.token("start", AN, foe.turns_started + 1)]
    _end_turn(engine)
    assert _conditions(foe, "reaction_denied")  # over the rest of this round
    assert _end_turn(engine) == AN
    assert not _conditions(foe, "reaction_denied")  # gone as its next turn starts


def test_world_as_canvas_slows_and_restrains_only_until_the_start_of_its_next_turn():
    engine, me, foe = _fight()  # cast on the user's own turn; the ability itself carries no Concentration (as typed)
    ctx = _ctx(engine, me, foe, {"kind": "minutes", "amount": 1, "concentration": False})
    binding = CANVAS[0]["triggers"][0]["effects"][0]  # the Binding Script zone's save (a zone trigger since the retyping)
    typed_executor.run_effects(ctx, [*binding["on_success"], *binding["on_fail"]])
    assert [(m.value, m.expires_on) for m in _modifiers(foe, "speed_ft")] == [(-10, effect_durations.token("start", AN, foe.turns_started + 1))]
    assert [c.expires_on for c in _conditions(foe, "restrained")] == [effect_durations.token("start", AN, foe.turns_started + 1)]
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft") and not _conditions(foe, "restrained")
    assert [e.payload["modifier_id"] for e in engine.events if e.event_type == "MODIFIER_REMOVED" and e.target_ids == (AN,)]


def test_boiling_ash_sky_results_last_until_the_start_of_the_enemys_next_turn():
    engine, me, foe = _fight()
    _end_turn(engine)  # the cloud's save comes as the enemy's turn starts
    speed, invisible = ASH_SAVE["on_fail"][1], ASH_SAVE["on_fail"][2]
    typed_executor.run_effects(_ctx(engine, me, foe, LASTING), [speed, invisible])  # Concentration does not stretch them
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == ["START_OF_SOURCE_NEXT_TURN"]  # filed under the enemy: the engine's own name
    assert [c.expires_on for c in _conditions(foe, "no_invisible")] == [effect_durations.token("start", AN, foe.turns_started + 1)]
    assert _end_turn(engine) == ME
    assert _modifiers(foe, "speed_ft") and _conditions(foe, "no_invisible")  # not at the cloud owner's turn
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft") and not _conditions(foe, "no_invisible")


def test_a_reaction_with_no_duration_of_its_own_takes_its_effects_words(  # the generic-reaction context always says "instant"
        ):
    engine, me, foe = _fight()
    _end_turn(engine)
    row = {"feature_id": "REACTION.SURGE", "name": "Surge", "numbers": {"pb": 2}}
    effects = [{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn",
                "evidence": "its Speed is reduced by 10 feet until the start of its next turn"},
               {"type": "reaction_denied", "applies_to": "target", "duration": "one_round",
                "evidence": "The triggering creature cannot take Reactions until the end of its next turn"}]
    typed_reactions._run_generic_effects(engine, me, foe, row, effects)
    assert _modifiers(foe, "speed_ft") and _conditions(foe, "reaction_denied")
    _end_turn(engine)
    _end_turn(engine)  # its next turn has started
    assert not _modifiers(foe, "speed_ft") and _conditions(foe, "reaction_denied")
    _end_turn(engine)
    _end_turn(engine)
    assert not _conditions(foe, "reaction_denied")


# ------------------------------------------------------------------ what the ability lasts is not cut short
@pytest.mark.parametrize("effect_duration", ["instant", None, "concentration", {"kind": "instant"}])
def test_an_effect_that_says_instant_or_nothing_keeps_what_the_ability_lasts(effect_duration):
    engine, me, foe = _fight()
    ctx = _ctx(engine, me, foe, LASTING)
    effect = {"type": "condition", "condition": "frightened", "applies_to": "target", "evidence": "It is Frightened.",
              **({} if effect_duration is None else {"duration": effect_duration})}
    engine._start_concentration(me, ctx.source)
    typed_executor.run_effects(ctx, [effect])
    assert [c.expires_on for c in _conditions(foe, "frightened")] == ["CONCENTRATION_END"]
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert not _conditions(foe, "frightened")  # losing Concentration still ends it


def test_a_condition_without_any_duration_still_ends_with_the_creatures_next_turn():
    engine, me, foe = _fight()
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "condition", "condition": "frightened", "applies_to": "target"}])
    assert [c.expires_on for c in _conditions(foe, "frightened")] == ["END_OF_HOLDER_NEXT_TURN"]  # owner 2026-09-26: never permanent


# ------------------------------------------------------------------ which name, which turn
def test_the_engines_own_names_are_used_where_they_are_exact():
    engine, me, foe = _fight("NATIVE", Gate2Engine)  # no plug-in hooks under the bare engine
    ctx = _ctx(engine, me, foe)
    assert engine.state.current_actor_id == ME
    turn = me.turns_started + 1
    # a condition is filed under its applier: "your next turn" is the engine's own name; "its next turn" (an enemy's) is not
    assert _expiry(ctx, {"evidence": "until the start of your next turn"}, foe, condition=True) == "START_OF_SOURCE_NEXT_TURN"
    assert _expiry(ctx, {"evidence": "until the end of your next turn"}, foe, condition=True) == f"END_OF_SOURCE_TURN_AT:{turn}"
    assert _expiry(ctx, {"evidence": "until the end of its next turn"}, foe, condition=True) == effect_durations.token("end", AN, foe.turns_started + 1)
    # a modifier is filed under whoever's turn it is: here the user's, so its own turn is the engine's name, the enemy's is not
    assert _expiry(ctx, {"evidence": "until the start of your next turn"}, foe) == "START_OF_SOURCE_NEXT_TURN"
    assert _expiry(ctx, {"evidence": "until the start of its next turn"}, foe) == effect_durations.token("start", AN, foe.turns_started + 1)
    # ... and on the enemy's turn (a Reaction), the enemy's own turn is the engine's name and the user's is not
    engine.state.current_actor_id = AN
    assert _expiry(ctx, {"evidence": "until the start of its next turn"}, foe) == "START_OF_SOURCE_NEXT_TURN"
    assert _expiry(ctx, {"evidence": "until the start of your next turn"}, foe) == effect_durations.token("start", ME, me.turns_started + 1)


def test_the_engines_own_names_expire_without_the_plug_in():
    engine, me, foe = _fight("NATIVE-EXPIRE", Gate2Engine)
    ctx = _ctx(engine, me, me)
    typed_executor.run_effects(ctx, [{"type": "speed", "applies_to": "self", "flat": 10, "evidence": "until the start of your next turn"},
                                     {"type": "ac_bonus", "applies_to": "self", "amount": 2, "evidence": "until the end of your next turn"}])
    assert _modifiers(me, "speed_ft") and _modifiers(me, "armor_class")
    engine._expire_for_checkpoint("START_OF_TURN", ME)
    assert not _modifiers(me, "speed_ft") and _modifiers(me, "armor_class")
    engine._expire_for_checkpoint("END_OF_TURN", ME)
    assert _modifiers(me, "armor_class")  # this turn's end is not "the end of your next turn"
    me.turns_started += 1
    engine._expire_for_checkpoint("END_OF_TURN", ME)
    assert not _modifiers(me, "armor_class")


SOURCE, HOLDER = "the user's next turn", "the enemy's next turn"
ONE_ROUND, TEN_ROUNDS = "a round from now", "ten rounds from now"  # the round clock: the same place in the turn order, that far on


@pytest.mark.parametrize("kind, expected", [
    ("until_start_of_next_turn", "START_OF_SOURCE_NEXT_TURN"), ("until_start_of_your_next_turn", "START_OF_SOURCE_NEXT_TURN"),
    ("until_end_of_your_next_turn", SOURCE), ("until_end_of_next_turn", HOLDER), ({"kind": "until_end_of_next_turn"}, HOLDER),
    ("until_end_of_turn", HOLDER),  # on an enemy: the typing's short form of "the end of its next turn"
    ("end_of_turn", "END_OF_CURRENT_TURN"), ("this_attack", "END_OF_CURRENT_TURN"), ("until_removed", "UNTIL_REMOVED"),
    ("target_next_turn", "END_OF_HOLDER_NEXT_TURN"),  # the engine's own table (only marks carry it, and they read their own)
    ("rounds", ONE_ROUND), ("minutes", TEN_ROUNDS), ("one_minute", TEN_ROUNDS), ({"kind": "minutes", "amount": 2}, "twenty rounds from now"),
    ("hours", "six hundred rounds from now"), ("one_hour", "six hundred rounds from now"), ("until_end_of_scene", "UNTIL_REMOVED"),
    ("instant", None), ("special", None), ("one_round", None), (None, None),  # (one_round is also typed for "once per round")
])
def test_an_effects_duration_kind_on_an_enemy(kind, expected):
    engine, me, foe = _fight("KINDS")
    effect = {"type": "condition"} if kind is None else {"type": "condition", "duration": kind}
    later = lambda rounds: f"START_OF_SLOT_AT:{engine.state.round_number + rounds}:{engine.state.current_slot_index}"  # noqa: E731
    expected = {SOURCE: f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}", HOLDER: effect_durations.token("end", AN, foe.turns_started + 1),
                ONE_ROUND: later(1), TEN_ROUNDS: later(10), "twenty rounds from now": later(20),
                "six hundred rounds from now": later(600)}.get(expected, expected)
    assert _expiry(_ctx(engine, me, foe), effect, foe, condition=True) == expected  # (an ability that says "instant": nothing to keep)


def test_until_the_end_of_the_turn_is_this_turn_on_the_user_and_allies_and_the_next_turn_on_an_enemy():
    engine, me, foe = _fight("THIS-TURN")
    ctx = _ctx(engine, me, foe)
    effect = {"type": "ac_bonus", "duration": "until_end_of_turn"}
    assert _expiry(ctx, effect, me) == "END_OF_CURRENT_TURN"  # a self-buff: "until the end of the turn"
    assert _expiry(ctx, effect, foe) == effect_durations.token("end", AN, foe.turns_started + 1)  # owner 2026-09-26: never permanent
    # an ability that already says "until the end of the turn" is not stretched
    assert _expiry(_ctx(engine, me, foe, {"kind": "until_end_of_turn"}), effect, foe) == "END_OF_CURRENT_TURN"


def test_a_triggering_effect_with_a_special_duration_ends_with_the_turn_it_happens_in():
    engine, me, foe = _fight("TRIGGERING")
    ctx = _ctx(engine, me, foe, LASTING)
    assert _expiry(ctx, {"duration": "special", "evidence": "Disadvantage on the triggering attack roll"}, foe) == "END_OF_CURRENT_TURN"
    assert _expiry(ctx, {"duration": "special", "evidence": "Disadvantage on its attack rolls"}, foe) == "CONCENTRATION_END"  # nothing to go by


def test_the_effects_words_beat_the_coarse_kind_and_the_abilitys_duration():
    engine, me, foe = _fight("WORDS")
    ctx = _ctx(engine, me, foe, LASTING)
    words = {"duration": "until_end_of_turn", "evidence": "Disadvantage on attack rolls until the end of your next turn"}
    assert _expiry(ctx, words, foe) == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"  # not the enemy's, as the bare kind would say
    assert _expiry(ctx, {"evidence": "It is Deafened until the end of its next turn."}, foe, condition=True) == \
        effect_durations.token("end", AN, foe.turns_started + 1)
    assert _expiry(ctx, {"evidence": "It has Advantage. until the end of the current turn"}, foe) == "END_OF_CURRENT_TURN"
    assert _expiry(ctx, {"evidence": "for the rest of the turn", "duration": "one_minute"}, foe) == "END_OF_CURRENT_TURN"
    assert _expiry(ctx, {"evidence": "until the start of your next turn", "expires_on": "UNTIL_REMOVED"}, foe) == "UNTIL_REMOVED"  # an explicit one wins
    for text in ("It is Frightened for one minute", "until the end of the scene", "the start of the round", ""):
        assert _expiry(ctx, {"evidence": text}, foe) == "CONCENTRATION_END", text


def test_a_counted_duration_stands_unless_the_words_state_one_lifetime_of_their_own():
    """P20261005-15 (reconciled twice). One precedence contract, both sides.

    A counted ``duration`` kind is the row's own reviewed lifetime, so it wins over a turn phrase quoted in its evidence --
    that is what keeps Heaven's Roar's Deafened at one minute while the sentence also quotes a shorter sibling penalty on
    the caster. The exception is words that state one lifetime of this effect and nothing else: no second clause, no second
    lifetime, no length named beside the turn. Such a quote describes this effect alone, so its words decide, and a printed
    "for the rest of the turn" must not last ten rounds because the typed kind said ``one_minute``. A sentence that only
    continues this effect ("This cannot reduce Speed below 0.") is part of that one description and not a second effect;
    ``test_an_explanatory_sentence_keeps_the_current_turn_of_the_same_effect`` covers that side.

    The shape, not whose turn is named, is the test, because a sibling's quote can be ownerless too: "Deafened for 1 minute,
    and Disadvantage on Concentration saving throws for the rest of the turn" names no creature, yet the turn still belongs
    to the sibling and the minute must stand (regression for review finding 1). An *owned* phrase as the whole statement is
    this effect speaking, and is read as such: ``tests/test_expiry_clock.py::test_the_words_of_an_effect_still_beat_the_clock``
    pins that same row from the other file's context. The other ways one quote can hide a sibling -- a spelled-out length,
    two turn lifetimes, an unpunctuated " and " -- are pinned by
    ``test_a_sibling_sharing_the_same_words_keeps_the_counted_duration``.

    One thing stays with the ability: a counted effect of a *Concentrating* ability shares that ability's
    ``CONCENTRATION_END`` whatever turn its words quote, which is why the quoted shapes here are checked under both abilities
    and the ownerless ones are the only exception. Every counted row whose words name a turn is a sibling quote, so the
    exception changes no shipped ability.
    """
    engine, me, foe = _fight("COUNTED-KIND")
    plain = _ctx(engine, me, foe, {"kind": "minutes", "amount": 1})  # not Concentration, so a counted effect keeps its clock
    minute = effect_durations.round_token(engine, 10)
    ctx = _ctx(engine, me, foe, LASTING)
    # the exception: one statement, one lifetime, nothing else named beside it
    for text in ("for the rest of the turn", "until the end of the current turn", "Advantage until the end of this turn",
                 "reduce its Speed by 10 feet for the rest of the turn"):
        assert _expiry(ctx, {"evidence": text, "duration": "one_minute"}, foe) == "END_OF_CURRENT_TURN", text
    assert _expiry(plain, {"evidence": "Speed is reduced by 10 feet until the start of its next turn.",
                           "duration": "one_minute"}, foe) == effect_durations.token("start", AN, foe.turns_started + 1)
    # a sibling's rider quoted in the same sentence: the row's own minute stands, whatever turn it names
    deafened = {"type": "condition", "condition": "deafened", "duration": "one_minute",
                "evidence": "Deafened for 1 minute, and Disadvantage on Concentration saving throws until the end of your next turn"}
    assert _expiry(plain, deafened, foe, condition=True) == minute
    assert _expiry(plain, {"type": "condition", "condition": "deafened", "duration": "one_minute",
                           "evidence": "Deafened for 1 minute, and Disadvantage on Concentration saving throws "
                                       "for the rest of the turn"},
                    foe, condition=True) == minute  # the same shape with the ownerless phrase: still the sibling's
    assert _expiry(plain, {"type": "condition", "condition": "poisoned", "duration": "one_minute",
                           "evidence": "Poisoned for the stated duration; the separate penalty lasts until the end of your next turn."},
                    foe, condition=True) == minute
    # Court of Charged Paths as compiled: the minute belongs to the state, the quoted rider's turn to the other creature
    assert _expiry(plain, {"duration": "one_minute",
                           "evidence": "Your Charge limit increases by your Proficiency Bonus. The first time each round a "
                                       "hostile creature inside the court takes lightning damage from one of your talents, "
                                       "it cannot take Reactions until the start of its next turn."},
                    foe) == minute
    # the boundary: two described statements and the counted kind is kept, so a short owned row is corrected in the typed data
    assert _expiry(plain, {"duration": "one_minute",
                           "evidence": "A damaged hostile creature cannot take Reactions until the start of its next turn. "
                                       "The court ends."},
                    foe) == minute
    # a genuine short owned effect, however it is typed: the words alone, and the short structured kind, both read as the turn
    for effect in ({"evidence": "Speed is reduced by 10 feet until the start of its next turn."},
                   {"evidence": "Speed is reduced by 10 feet until the start of its next turn.", "duration": "until_start_of_next_turn"}):
        assert _expiry(plain, effect, foe) == effect_durations.token("start", AN, foe.turns_started + 1)
    # the one thing a Concentration still decides: a counted effect of a Concentrating ability shares that ability's end,
    # whatever turn its words quote. Only a plain "this turn" of this effect alone, above, is shorter than any Concentration.
    for text in ("Deafened for 1 minute, and Disadvantage on Concentration saving throws for the rest of the turn",
                 "The separate penalty lasts until the end of your next turn."):
        assert _expiry(ctx, {"duration": "one_minute", "evidence": text}, foe, condition=True) == "CONCENTRATION_END", text
    assert _expiry(ctx, {**deafened, "expires_on": "UNTIL_REMOVED"}, foe, condition=True) == "UNTIL_REMOVED"  # explicit still wins


@pytest.mark.parametrize("text", [
    "Poisoned for two minutes and its Speed is reduced until the start of its next turn.",  # a length spelled out, not digits
    "Poisoned for ten minutes. It also loses its Speed for the rest of the turn.",  # two sentences, two effects
    "Disadvantage until the start of its next turn and Speed reduced for the rest of the turn.",  # two turn lifetimes, no comma
    "Speed is reduced for the rest of the turn while it is also Poisoned.",  # two clauses joined with no comma
    "Poisoned for the next minute, and its Speed is reduced for the rest of the turn",  # "for the next minute"
])
def test_a_sibling_sharing_the_same_words_keeps_the_counted_duration(text):
    """PRO15r2 review finding 1: sibling prose must not take the single-lifetime exception and shorten a counted clock.

    One printed quote routinely carries a second effect, and the exception used to be granted whenever the quote's
    delimiters were absent: "two minutes" spelled in words beside a turn, two turn lifetimes, or an " and " with no comma all
    read as one statement, so a two-minute condition ended at the target's next turn instead of twenty rounds from now.
    Any wording that can carry more than one effect or one lifetime is now refused, however it is punctuated; the row's own
    reviewed count stands and the row is corrected in the typed data instead.
    """
    engine, me, foe = _fight("SIBLING-WORDS")
    plain = _ctx(engine, me, foe, {"kind": "minutes", "amount": 1})  # not Concentration, so a counted effect keeps its clock
    counted = {"type": "condition", "condition": "poisoned", "duration": {"kind": "minutes", "amount": 2}, "evidence": text}
    assert _expiry(plain, counted, foe, condition=True) == effect_durations.round_token(engine, 20)  # not the turn it quotes
    # the classifier itself, so the shape is pinned and not just its result
    assert typed_executor._own_words_state_one_lifetime(counted) is False, text
    # ... and a Concentrating ability still ends it, exactly as a counted effect of any other kind does
    assert _expiry(_ctx(engine, me, foe, LASTING), counted, foe, condition=True) == "CONCENTRATION_END"


@pytest.mark.parametrize("text", [
    "Speed is reduced by 10 feet for the rest of the turn. It is also Poisoned.",  # a rider named with the creature
    "Speed is reduced by 10 feet for the rest of the turn. It is Poisoned.",  # ... or without the "also"
    "Speed is reduced by 10 feet for the rest of the turn. It is also Frightened.",
    "Speed is reduced by 10 feet for the rest of the turn. This also makes it Deafened.",
    "Speed is reduced by 10 feet for the rest of the turn and it is also Poisoned.",  # the same rider, joined by "and"
])
def test_a_sentence_after_the_lifetime_that_adds_another_effect_keeps_the_counted_duration(text):
    """PRO15r3 review finding 1: a pronoun opening a sentence does not prove the sentence continues the same effect.

    "Speed is reduced by 10 feet for the rest of the turn. It is also Poisoned." quotes two effects, and the counted two
    minutes belong to the Poisoned row. Accepting any pronoun-led sentence as a clarification shortened it to this turn --
    twenty rounds became one turn, and under a Concentrating ability it bypassed CONCENTRATION_END -- which is the sibling bug
    this lane repairs, re-entered through the clarification rule. ``test_an_explanatory_sentence_keeps_the_current_turn_of_the
    _same_effect`` keeps the other side: a sentence that *limits* the same penalty is not a rider.
    """
    engine, me, foe = _fight("ADDED-EFFECT")
    plain = _ctx(engine, me, foe, {"kind": "minutes", "amount": 1})
    counted = {"type": "condition", "condition": "poisoned", "duration": {"kind": "minutes", "amount": 2}, "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(counted) is False, text  # the shape itself, not just its result
    assert _expiry(plain, counted, foe, condition=True) == effect_durations.round_token(engine, 20), text
    assert _expiry(_ctx(engine, me, foe, LASTING), counted, foe, condition=True) == "CONCENTRATION_END", text


@pytest.mark.parametrize("text", [
    "Speed is reduced by 10 feet for the rest of the turn but cannot be reduced below 0.",  # a floor, joined by "but"
    "Its walking and flying Speed are reduced by 10 feet for the rest of the turn.",  # one Speed, two kinds of movement
])
def test_a_conjunction_inside_one_effect_keeps_the_current_turn(text):
    """PRO15r3 review finding 2: "and"/"but"/"while" inside one effect is not a second effect.

    Treating every conjunction as a clause boundary refused a single Speed penalty that carries a floor, or names walking and
    flying as two kinds of the same Speed, so the printed "for the rest of the turn" became ten rounds -- or a whole
    Concentration. A conjunction is a boundary only when what follows it says something else happens
    (``test_a_sibling_sharing_the_same_words_keeps_the_counted_duration``); inside one effect or its floor, it is not.
    """
    engine, me, foe = _fight("CONJUNCTION-WORDS")
    said = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute", "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(said) is True, text
    for duration in ({"kind": "minutes", "amount": 1}, LASTING):  # a plain ability, and a Concentrating one
        assert _expiry(_ctx(engine, me, foe, duration), said, foe) == "END_OF_CURRENT_TURN", duration
    typed_executor.run_effects(_ctx(engine, me, foe, {"kind": "minutes", "amount": 1}), [said])
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == ["END_OF_CURRENT_TURN"], text  # ... and at the table
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft"), text  # not ten rounds from now


def test_an_explanatory_sentence_keeps_the_current_turn_of_the_same_effect():
    """PRO15r2 review finding 2: a sentence that only clarifies this effect is not a second effect.

    "Speed is reduced by 10 feet for the rest of the turn. This cannot reduce Speed below 0." describes one effect with a
    floor on it, so the turn stays the turn the words say. Read as a second statement it became ten rounds from now -- or a
    whole Concentration -- which is how a harmless clarification of the printed rule lengthened a movement penalty.
    """
    engine, me, foe = _fight("EXPLAINED-TURN")
    said = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute",
            "evidence": "Speed is reduced by 10 feet for the rest of the turn. This cannot reduce Speed below 0."}
    for duration in ({"kind": "minutes", "amount": 1}, LASTING):  # a plain ability, and a Concentrating one
        assert _expiry(_ctx(engine, me, foe, duration), said, foe) == "END_OF_CURRENT_TURN", duration
    typed_executor.run_effects(_ctx(engine, me, foe, {"kind": "minutes", "amount": 1}), [said])
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == ["END_OF_CURRENT_TURN"]  # ... and the table ends it there
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft")  # not ten rounds from now


@pytest.mark.parametrize("text", [
    "Speed is reduced by 10 feet for the rest of the turn and it cannot take Reactions.",  # the denial names the creature
    "Speed is reduced by 10 feet for the rest of the turn and cannot take Reactions.",  # ... or carries the same subject
    "Speed is reduced by 10 feet for the rest of the turn. It cannot take Reactions.",  # ... or is a sentence of its own
    "Speed is reduced by 10 feet for the rest of the turn and they cannot take Reactions.",
])
def test_an_action_denied_beside_a_counted_effect_keeps_the_counted_duration(text):
    """PRO15r4 review finding 1: a negation is not a limit until it refers to the effect already stated.

    "Speed is reduced by 10 feet for the rest of the turn and it cannot take Reactions." quotes two effects -- a Speed
    penalty for this turn, and a denial of Reactions -- so the row's own counted clock is what ends it. Reading any
    "cannot" as a limit on the first effect shortened it to END_OF_CURRENT_TURN (and under a Concentrating ability it
    bypassed CONCENTRATION_END), which is the sibling bug this lane repairs reached through the clarification rule: the
    denial never referred to the Speed at all, so it must not keep the effect's own words deciding. A floor or a ceiling on
    this effect's own verb ("cannot reduce Speed below 0", "cannot be reduced below 0") is still a limit, whichever subject
    the sentence names before it; ``test_an_explanatory_sentence_keeps_the_current_turn_of_the_same_effect`` pins that side,
    and ``test_a_floor_on_this_effect_itself_still_keeps_the_current_turn`` pins it from the creature's side.
    """
    engine, me, foe = _fight("DENIED-SIBLING")
    plain = _ctx(engine, me, foe, {"kind": "minutes", "amount": 1})  # not Concentration, so a counted effect keeps its clock
    counted = {"type": "condition", "condition": "reaction_denied", "applies_to": "target",
               "duration": {"kind": "minutes", "amount": 2}, "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(counted) is False, text  # the shape itself, not just its result
    assert _expiry(plain, counted, foe, condition=True) == effect_durations.round_token(engine, 20), text
    assert _expiry(_ctx(engine, me, foe, LASTING), counted, foe, condition=True) == "CONCENTRATION_END", text
    # ... and at the table: twenty rounds on, not the turn the sibling's phrase quotes
    typed_executor.run_effects(plain, [counted])
    denied = _conditions(foe, "reaction_denied")
    assert [c.expires_on for c in denied] == [effect_durations.round_token(engine, 20)], text
    assert _end_turn(engine) == AN
    assert _conditions(foe, "reaction_denied"), text  # still denied: not ended with the turn it quoted


@pytest.mark.parametrize("text", [
    "Speed is reduced by 10 feet for the rest of the turn. This reduction cannot reduce Speed below 0.",  # named outright
    "Speed is reduced by 10 feet for the rest of the turn and that reduction cannot reduce Speed below 0.",
    "Speed is reduced by 10 feet for the rest of the turn. Its Speed reduction cannot reduce Speed below 0.",
])
def test_a_floor_that_names_the_effect_keeps_the_current_turn(text):
    """PRO15r4 review finding 2: naming the effect in its own floor does not prolong it.

    "This reduction cannot reduce Speed below 0" is the same floor as "This cannot reduce Speed below 0", only written with
    the effect's name in front of its predicate. Read as a further effect it lasted ten rounds -- or a whole Concentration
    -- instead of the turn the words say, so a printed floor on a current-turn penalty lengthened it.
    """
    engine, me, foe = _fight("NAMED-FLOOR")
    said = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute", "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(said) is True, text
    for duration in ({"kind": "minutes", "amount": 1}, LASTING):  # a plain ability, and a Concentrating one
        assert _expiry(_ctx(engine, me, foe, duration), said, foe) == "END_OF_CURRENT_TURN", (text, duration)
    typed_executor.run_effects(_ctx(engine, me, foe, {"kind": "minutes", "amount": 1}), [said])
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == ["END_OF_CURRENT_TURN"], text  # ... and at the table
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft"), text  # not ten rounds from now


@pytest.mark.parametrize("text, condition", [
    # a passive keeps the subject it was built on, so it is about the creature here, not about the Speed penalty
    ("Speed is reduced by 10 feet for the rest of the turn. The target cannot be healed.", "healing_reduction"),
    ("Speed is reduced by 10 feet for the rest of the turn. It cannot be healed.", "healing_reduction"),
    ("Speed is reduced by 10 feet for the rest of the turn and its wounds cannot be healed.", "healing_reduction"),
    ("Speed is reduced by 10 feet for the rest of the turn and cannot be healed.", "healing_reduction"),
    # a bound is a bound on the number it is written beside: this one bounds how high the target may be, not its Speed
    ("Speed is reduced by 10 feet for the rest of the turn. The target cannot be moved above 10 feet from the ground.",
     "restrained"),
    ("Speed is reduced by 10 feet for the rest of the turn and it cannot be moved above 10 feet from the ground.",
     "restrained"),
])
def test_a_restriction_about_something_else_keeps_the_counted_duration(text, condition):
    """PRO15r5 review finding 1: scanning past a subject must not mistake a separate restriction for a limit.

    "Speed is reduced by 10 feet for the rest of the turn. The target cannot be healed." quotes two effects -- a Speed
    penalty for this turn, and a separate restriction -- so the row's own counted clock is what ends the row. Reading the
    later clause's passive ("cannot be healed") or its bound ("cannot be moved above 10 feet") as a limit on the first
    effect shortened it to END_OF_CURRENT_TURN, and under a Concentrating ability it bypassed CONCENTRATION_END as well.

    What tells the two apart is that a limit has to be about the very effect already stated: it says so with its own verb
    ("cannot reduce Speed below 0", "cannot be reduced below 0"), where a restriction on the creature's wounds, its healing
    or its height speaks of another verb and shares nothing but the numbers both passages happen to use. Where the words
    do not say which it is, the row's reviewed counted kind stands.
    """
    engine, me, foe = _fight("OTHER-RESTRICTION")
    plain = _ctx(engine, me, foe, {"kind": "minutes", "amount": 1})  # not Concentration, so a counted effect keeps its clock
    counted = {"type": "condition", "condition": condition, "applies_to": "target",
               "duration": {"kind": "minutes", "amount": 2}, "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(counted) is False, text  # the shape itself, not just its result
    assert _expiry(plain, counted, foe, condition=True) == effect_durations.round_token(engine, 20), text
    assert _expiry(_ctx(engine, me, foe, LASTING), counted, foe, condition=True) == "CONCENTRATION_END", text
    # ... and at the table: a real condition, twenty rounds on, still there when the turn the words quote has ended
    typed_executor.run_effects(plain, [counted])
    applied = _conditions(foe, condition)
    assert [c.expires_on for c in applied] == [effect_durations.round_token(engine, 20)], text
    assert _end_turn(engine) == AN
    assert _conditions(foe, condition), text  # not ended with the turn a sibling clause quoted


@pytest.mark.parametrize("text", [
    "Speed is reduced by 10 feet for the rest of the turn. Its Speed cannot be reduced below 0.",  # named, its own verb
    "Speed is reduced by 10 feet for the rest of the turn. The target cannot be reduced below 0.",  # named as the creature
    "Speed is reduced by 10 feet for the rest of the turn. This cannot be reduced below 0.",  # named as "This"
    "Speed is reduced by 10 feet for the rest of the turn and its Speed cannot be reduced below 0.",
])
def test_a_floor_on_this_effect_itself_still_keeps_the_current_turn(text):
    """PRO15r5 review finding 1, other side: refusing a restriction about something else must not refuse a floor on this
    effect, however the clause names its subject.

    "Its Speed cannot be reduced below 0" and "The target cannot be reduced below 0" are the same floor as the retained
    "This cannot be reduced below 0": the predicate is this effect's own verb, whatever subject the sentence puts in front
    of it. Read as a further effect they lasted ten rounds -- or a whole Concentration -- instead of the turn the printed
    words say, which is the harm the earlier rounds repaired. ``test_a_floor_that_names_the_effect_keeps_the_current_turn``
    pins the named-floor wording; this pins the same floor written from the creature's side.
    """
    engine, me, foe = _fight("FLOOR-ON-THIS")
    said = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute", "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(said) is True, text
    for duration in ({"kind": "minutes", "amount": 1}, LASTING):  # a plain ability, and a Concentrating one
        assert _expiry(_ctx(engine, me, foe, duration), said, foe) == "END_OF_CURRENT_TURN", (text, duration)
    typed_executor.run_effects(_ctx(engine, me, foe, {"kind": "minutes", "amount": 1}), [said])
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == ["END_OF_CURRENT_TURN"], text  # ... and at the table
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft"), text  # not ten rounds from now


@pytest.mark.parametrize("text", [
    # an adverb between "be" and the passive says how much, not what is done to it
    "Speed is reduced by 10 feet for the rest of the turn. Its Speed cannot be further reduced below 0.",
    # ... and one in front of the plain verb is the same floor said the other way round
    "Speed is reduced by 10 feet for the rest of the turn. This cannot further reduce Speed below 0.",
    "Speed is reduced by 10 feet for the rest of the turn and its Speed cannot be further reduced below 0.",
    # the sentence states the effect as a participle and bounds it with the base verb
    "This is reducing Speed by 10 feet for the rest of the turn. This cannot reduce Speed below 0.",
])
def test_a_floor_still_written_with_an_adverb_or_a_participle_keeps_the_current_turn(text):
    """PRO15r6 review finding 1: finding a limit's effect by its verb must read past an adverb in front of that verb, and
    must know a present participle as the same verb as its base.

    "Its Speed cannot be **further** reduced below 0" and "This cannot **further** reduce Speed below 0" put an adverb
    between the clause and its verb, and "This is **reducing** Speed ... cannot **reduce** Speed below 0" states the effect
    itself as a participle and bounds it with the base. Each names one Speed penalty with a floor on it. Read as a further
    effect each lasted the row's own counted ten rounds -- or a whole Concentration -- instead of the turn the words print,
    so a creature stayed slowed after the turn its text had already ended.
    """
    engine, me, foe = _fight("ADVERB-OR-PARTICIPLE")
    said = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute", "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(said) is True, text  # the shape itself, not just its result
    for duration in ({"kind": "minutes", "amount": 1}, LASTING):  # a plain ability, and a Concentrating one
        assert _expiry(_ctx(engine, me, foe, duration), said, foe) == "END_OF_CURRENT_TURN", (text, duration)
    # ... and at the table: a real modifier, created this turn and gone when the turn ends
    typed_executor.run_effects(_ctx(engine, me, foe, {"kind": "minutes", "amount": 1}), [said])
    assert [m.expires_on for m in _modifiers(foe, "speed_ft")] == ["END_OF_CURRENT_TURN"], text
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft"), text  # not ten rounds from now


@pytest.mark.parametrize("text", [
    # a passive with no bound of its own says nothing about what is Dispelled
    "Speed is reduced by 10 feet for the rest of the turn. This cannot be Dispelled.",
    "Speed is reduced by 10 feet for the rest of the turn. It cannot be Dispelled.",
])
def test_a_passive_with_no_bound_of_its_own_is_not_a_limit(text):
    """The deliberate consequence of PRO15r5, pinned so a later round cannot undo it by accident: a passive that names no
    effect of its own is a further effect, and the row's own counted kind is what ends it.

    "This cannot be Dispelled" does not say *what* is Dispelled -- not the Speed, not the floor -- so the words do not say it
    limits the penalty already stated. Read as a limit it shortened a ten-round row to this turn; the conservative reading is
    that the reviewed counted kind stands. Reading a verb through an adverb or a participle does not change this: "Dispelled"
    is neither, so it still names no word the Speed penalty's own sentence uses.
    """
    engine, me, foe = _fight("PASSIVE-NO-BOUND")
    said = {"type": "speed", "applies_to": "target", "flat": -10, "duration": "one_minute", "evidence": text}
    assert typed_executor._own_words_state_one_lifetime(said) is False, text  # the shape itself, not just its result
    assert _expiry(_ctx(engine, me, foe, {"kind": "minutes", "amount": 1}), said, foe) \
        == effect_durations.round_token(engine, 10), text  # the row's own one_minute, not this turn
    assert _expiry(_ctx(engine, me, foe, LASTING), said, foe) == "CONCENTRATION_END", text  # nor bypassed by Concentration


@pytest.mark.parametrize("text, edge, whose", [
    ("cannot take Reactions until the end of its next turn", "end", "its"),
    ("Speed is reduced by 10 feet until the start of its next turn.", "start", "its"),
    ("Gain +2 AC until your next turn", "start", "your"),
    ("Restrained until the end of the target’s next turn", "end", "the target’s"),
    ("it has Disadvantage before the end of their next turn", "end", "their"),
    ("Advantage until the end of this turn", "over", ""), ("reduce its Speed by 10 feet for the rest of the turn", "over", ""),
    ("Reactions until the end of  its\n next turn", "end", "its"),
])
def test_the_turn_words_that_are_read(text, edge, whose):
    assert typed_executor._turn_phrase({"evidence": text}) == (edge, whose)
    assert typed_executor._turn_phrase({"on": text}) == (edge, whose)


@pytest.mark.parametrize("text", ["for 1 minute", "at the start of each of its turns", "while it is in the zone", "start of the round", "", None])
def test_words_that_name_no_turn_are_left_to_the_duration_kind(text):
    assert typed_executor._turn_phrase({"evidence": text}) is None


def test_healing_reduction_takes_the_words_then_the_users_next_turn():
    engine, me, foe = _fight("HEALING")
    ctx = _ctx(engine, me, foe)
    typed_executor.block_healing_reduction(ctx, {"type": "healing_reduction", "evidence": "healing received is halved"})
    typed_executor.block_healing_reduction(ctx, {"type": "healing_reduction", "duration": "until_end_of_next_turn",
                                                 "evidence": "cannot regain Hit Points until the end of its next turn"})
    assert sorted(str(m.expires_on) for m in _modifiers(foe, "healing_reduction")) == sorted(
        ["START_OF_SOURCE_NEXT_TURN", effect_durations.token("end", AN, foe.turns_started + 1)])


def test_a_check_penalty_lasts_until_the_end_of_your_next_turn_when_it_says_so():
    engine, me, foe = _fight("CHECKS")
    ctx = _ctx(engine, me, foe)
    typed_executor.block_advantage(ctx, {"type": "disadvantage", "applies_to": "target", "on": "Wisdom (Perception) checks",
                                         "evidence": "Disadvantage on Wisdom (Perception) checks until the end of your next turn"})
    assert [c.expires_on for c in _conditions(foe, "check_mode")] == [f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"]


# ------------------------------------------------------------------ the plug-in
def test_the_plug_in_names_read_back_with_colons_in_the_actor_id():
    assert effect_durations.parse(effect_durations.token("start", "actor:factory.foe:2", 4)) == ("start", "actor:factory.foe:2", 4)
    assert effect_durations.parse(effect_durations.token("end", AN, 12)) == ("end", AN, 12)
    for other in ("START_OF_SOURCE_NEXT_TURN", "END_OF_SOURCE_TURN_AT:3", "END_OF_TURN_AT:x", "END_OF_TURN_AT::3", None, ""):
        assert effect_durations.parse(other) is None


def test_the_plug_in_ends_what_has_come_due_and_nothing_else():
    engine, me, foe = _fight("DUE")
    started = foe.turns_started
    start, end = (effect_durations.token(edge, AN, started + 1) for edge in ("start", "end"))
    assert not effect_durations.due(engine, start) and not effect_durations.due(engine, end)
    foe.turns_started = started + 1  # its next turn has begun ...
    engine.state.current_actor_id = AN  # ... and it is the one acting
    assert effect_durations.due(engine, start) and not effect_durations.due(engine, end)
    assert effect_durations.due(engine, end, ending_id=AN)  # over as it ends (the "turn_end" hook runs before the next creature is up)
    engine.state.current_actor_id = ME
    assert effect_durations.due(engine, end)  # over once it is no longer the one acting
    foe.turns_started = started + 2
    assert effect_durations.due(engine, end)  # and stays over when the count moves on
    assert not effect_durations.due(engine, "END_OF_TURN_AT:actor:nobody:1") and not effect_durations.due(engine, "UNTIL_REMOVED")


def test_a_bare_engine_leaves_the_plug_in_names_alone():
    engine, me, foe = _fight("BARE", Gate2Engine)  # the hooks exist only under the Gate 4 engine (combat/gate4_engine.py)
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "speed", "applies_to": "target", "flat": -10,
                                                         "evidence": "until the start of its next turn"}])
    (modifier,) = _modifiers(foe, "speed_ft")
    assert effect_durations.parse(modifier.expires_on) is not None
    engine.end_turn()  # the bare engine does not know the name: the fight ends before it matters
    assert _modifiers(foe, "speed_ft")
