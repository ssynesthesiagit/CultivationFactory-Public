"""Automation lane H2: Counterstrike, Reflexive Preparation and Raging Bull (Retribution) as a Ready action on the lock-round-2
prepared-action hooks (combat/ext/counterstrike.py, authority override reviewed_final.d/zz_h2.json).

Every scenario runs a real compiled Retribution character in a Gate4ControllerEngine against An Eui; the trigger is a real
accepted action of the foe, answered through the same reaction transport the table uses.
"""

import pytest

from combat import ext
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.prepared_actions import CONDITION
from tests.test_auto_docket import ME, WEAPON, _fight, _names, _sheet
from tests.test_auto_tabik import _turn

FOCUS = "resource:core.martial_focus"
ATTACK_NAMES = ("Dao (Saber / Broadsword)", "Unarmed Strike")

TALENTS = ["RETRIBUTION_BASE_COUNTERSTRIKE", "TAL_RETRIBUTION_HAYMAKER", "TAL_RETRIBUTION_REFLEXIVE_PREPARATION", "TAL_RETRIBUTION_RAGING_BULL"]
TRIGGERS = {"me": "a foe starts an action that targets you", "ally": "a foe starts an action that targets an ally",
            "leaves": "a foe in your reach starts to move away", "enters": "a foe has moved into your reach",
            "hostile": "a foe in your reach begins any hostile action"}


def _request(engine, candidate, options=None):
    return ActionIntent(intent_id=f"h2:{engine.state.event_sequence}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        option_ids=candidate.option_ids if options is None else options, destination=candidate.destination)


def _fighter(foe_at=(4, 6), talents=TALENTS):
    engine = _fight(_sheet(list(talents), ["tianxia.sphere.retribution"], **WEAPON), foe_at=foe_at)
    engine.state.actors[AN].armor_class = -50  # every roll but a natural 1 hits
    return engine


def _answering(engine, *, trigger="me", variant=None, use="USE", extra=None):
    """The table's answers: the declaration's choice (the trigger, and the Counter talent when asked) and Use / Decline."""
    seen = []

    def provider(request):
        seen.append(request)
        checkpoint = request["checkpoint"]
        if checkpoint.startswith("READY:"):
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                    selection=use, option_ids=tuple(request["legal_option_ids"]) if use == "USE" else ()), None
        if request["reaction_source_id"] == "choice:needle.counterstrike":
            labels = request["choice_trigger"]["labels"]
            option = next(key for key, label in labels.items()
                          if TRIGGERS[trigger] in label and (variant is None or label.startswith(f"{variant} (")))
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                    selection="USE", option_ids=(option,)), None
        if request["reaction_source_id"] == "choice:needle.counterstrike_extra" and extra is not None:
            labels = request["choice_trigger"]["labels"]
            option = next(key for key, label in labels.items() if TRIGGERS[extra] in label)
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                    selection="USE", option_ids=(option,)), None
        return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE"), None

    engine.set_reaction_provider(provider)
    return seen


def _use(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(_request(engine, candidate))


def _prepare(engine, name="Counterstrike", trigger="me"):
    _answering(engine, trigger=trigger)
    _use(engine, name)


def _foe_does(engine, predicate, options=None):
    candidate = next(c for c in engine.legal_candidates() if predicate(c))
    before = len(engine.events)
    engine.execute_intent(_request(engine, candidate, options))
    return engine.events[before:]


def _held(actor):
    return [c for c in actor.conditions.values() if c.condition_id == CONDITION]


def _hits_on_foe(events):
    return [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME and e.payload.get("provisional_hit")]


def _replayed(engine, before, start):
    docs = enrich_committed_events(engine.events[start:], post_engine=engine)
    return Gate3EventReducer().apply_events(before, docs)


def _attacked(engine, name="Paired"):
    return _foe_does(engine, lambda c: ME in (c.target_ids or ()) and c.kind == "ACTION" and c.display_name.startswith(name))


# ---------------------------------------------------------------------------------------------------- the declaration
def test_counterstrike_declares_one_preparation_and_asks_for_the_trigger():
    engine = _fighter()
    names = _names(engine)
    assert {"Counterstrike", "Counterstrike + Haymaker", "Counterstrike + Raging Bull", "Reflexive Preparation"} <= names
    me = engine.state.actors[ME]
    seen = _answering(engine, trigger="ally")
    _use(engine, "Counterstrike + Haymaker")
    asked = [row for row in seen if row["reaction_source_id"] == "choice:needle.counterstrike"]
    assert len(asked) == 1 and len(asked[0]["legal_option_ids"]) == 8  # saber or Unarmed Strike, four triggers
    assert set(asked[0]["choice_trigger"]["labels"].values()) == {
        f"Counterstrike + Haymaker ({weapon}), when {text}"
        for weapon in ATTACK_NAMES for name, text in TRIGGERS.items() if name != "hostile"}
    held = _held(me)
    assert len(held) == 1 and not me.action_available and held[0].expires_on == "START_OF_SELF_NEXT_TURN"
    assert held[0].data["data"]["trigger"] == "targets_ally" and held[0].data["source_id"] == "ready:retribution.counterstrike"


def test_raging_bull_does_not_charge_toward_a_visible_fear_source():
    from combat.ext.counterstrike import _straight_charge
    engine = _fighter(foe_at=(4, 6))
    actor, foe = engine.state.actors[ME], engine.state.actors[AN]
    actor.position = Position(x=1, y=6)
    engine._apply_condition(actor, "condition:typed.frightened", "test:fear", foe.entity_id,
                            expires_on="UNTIL_REMOVED")
    assert _straight_charge(engine, actor, foe, 5) is None
    actor.conditions.clear()
    assert _straight_charge(engine, actor, foe, 5)


def test_a_new_declaration_replaces_the_held_one_and_counter_talent_use_effects_still_run():
    engine = _fighter(talents=[*TALENTS, "TAL_RETRIBUTION_TIGHT_GUARD"])
    me = engine.state.actors[ME]
    ac = engine._ac_modifier(me)
    _prepare(engine, "Counterstrike + Haymaker")
    assert engine._ac_modifier(me) > ac and len(_held(me)) == 1  # Tight Guard's AC bonus for preparing, as before
    me.action_available = True
    _prepare(engine, "Counterstrike", trigger="leaves")
    assert len(_held(me)) == 1 and _held(me)[0].data["data"]["trigger"] == "leaves_reach" and _held(me)[0].data["data"]["variant"].endswith("COUNTERSTRIKE")


def test_the_built_in_ai_is_offered_one_counterstrike_and_prepares_it_with_its_preferred_choice():
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.test_auto_tabik import ROOT

    engine = _fighter()
    context = build_decision_context(engine, PolicyLibrary(ROOT).fallback(), for_ai=True)
    names = [c.display_name for c in context.legal_candidates if c.display_name.startswith(("Counterstrike", "Reflexive"))]
    assert names == ["Counterstrike + Haymaker"]  # the richest Counter talent; Reflexive Preparation waits until the Action is spent
    player = build_decision_context(engine, PolicyLibrary(ROOT).fallback())
    assert {c.display_name for c in player.legal_candidates if c.display_name.startswith(("Counterstrike", "Reflexive"))} == {
        "Counterstrike", "Counterstrike + Haymaker", "Counterstrike + Raging Bull", "Reflexive Preparation"}
    _use(engine, "Counterstrike + Haymaker")  # no answer given: the AI's preferred combination
    held = _held(engine.state.actors[ME])[0].data
    assert held["data"]["trigger"] == "targets_me" and held["data"]["variant"].endswith("+b81629b754") and held["automatic_use"] is True
    engine.state.actors[ME].bonus_action_available = True
    spent = build_decision_context(engine, PolicyLibrary(ROOT).fallback(), for_ai=True)
    assert not [c for c in spent.legal_candidates if c.display_name.startswith(("Counterstrike", "Reflexive"))]  # one preparation at a time


# ---------------------------------------------------------------------------------------------------- the trigger
@pytest.mark.parametrize("haymaker_save_succeeds", [False, True])
def test_a_foe_attacking_you_gets_the_counterstrike_first_and_the_reaction_comes_back_on_a_hit(haymaker_save_succeeds):
    engine = _fighter()
    if haymaker_save_succeeds:
        engine.state.actors[AN].saving_throws["DEX"] = 40
    _prepare(engine, "Counterstrike + Haymaker")
    before = engine.state.model_copy(deep=True)
    start = len(engine.events)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _turn(engine, AN)
    seen = _answering(engine)
    events = _attacked(engine)
    order = [e.event_type for e in events]
    assert order[0] == "INTENT_ACCEPTED" and order.index("REACTION_RESOLVED") < max(i for i, name in enumerate(order) if name == "ATTACK_ROLLED")
    counter = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]
    assert len(counter) == 1 and counter[0].target_ids == (AN,) and counter[0].payload["provisional_hit"]
    # fix/log1 (merge cac068a1, source eb92fbbd) attributes named rider saves
    # and their conditions to the talent, while the attack remains Counterstrike.
    haymaker_source = "passive:TAL_RETRIBUTION_HAYMAKER"
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    assert len(saves) == 1
    save = saves[0]
    assert save.source_definition_id == haymaker_source and save.actor_id == AN
    assert save.payload["reason"] == f"SAVE:{haymaker_source}:DEX"
    assert save.payload["dc"] == 30 and save.payload["success"] is haymaker_save_succeeds
    assert counter[0].sequence < save.sequence < next(
        e.sequence for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == AN)
    from combat.ext.retribution_riders import HAYMAKER

    conditions = [c for c in foe.conditions.values() if c.condition_id == HAYMAKER]
    assert len(conditions) == (0 if haymaker_save_succeeds else 1)
    if conditions:
        assert conditions[0].source_definition_id == haymaker_source
        assert conditions[0].source_actor_id == ME and conditions[0].data["dc"] == 30
        assert conditions[0].expires_on == "UNTIL_REMOVED"  # printed healing/rest removal
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (AN,)]
# The printed PB bonus belongs to the weapon's single roll, before defenses.
    assert len(damage) == 1
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED"
             and e.actor_id == ME and e.target_ids == (AN,)]
    assert len(rolls) == 1
    weapon = next(a for a in engine.action_catalog.values()
                  if a.owner_id == ME and a.display_name == "Dao (Saber / Broadsword) attack")
    typed = weapon.parameters["typed"]
    assert rolls[0].payload["modifier"] == typed["weapon"]["damage"]["modifier"] + typed["numbers"]["pb"]
    assert rolls[0].payload["modifier"] == typed["weapon"]["damage"]["modifier"] + me.proficiency_bonus
    # The committed packet is that same roll: no split packet and no second instance.
    assert damage[0].payload["reduced_to"] == rolls[0].payload["total"]
    assert foe.current_hp < 55 and me.current_hp < 60  # the foe's own attack still came after it ("the activity continues")
    assert [row["reaction_source_id"] for row in seen if row["checkpoint"].startswith("READY:")] == ["ready:retribution.counterstrike"]
    assert me.reaction_available and len(_held(me)) == 1  # "After a Counterstrike hits, you regain your Reaction"; it waits on
    assert me.turn_flags["once_per_round:counterstrike"].startswith(f"{engine.state.round_number}:1:")
    replay = _replayed(engine, before, start)
    assert replay.actors[ME].reaction_available and replay.actors[AN].current_hp == foe.current_hp
    assert [c.model_dump(mode="json") for c in replay.actors[AN].conditions.values() if c.condition_id == HAYMAKER] == [
        c.model_dump(mode="json") for c in conditions]


def test_only_one_counterstrike_per_round_even_with_the_reaction_back():
    engine = _fighter()
    _prepare(engine)
    _turn(engine, AN)
    _answering(engine)
    _attacked(engine)
    me = engine.state.actors[ME]
    assert me.reaction_available and me.turn_flags["once_per_round:counterstrike"].startswith(f"{engine.state.round_number}:1:")
    assert len(_held(me)) == 1  # the preparation stands until my next turn, but the round's one Counterstrike is made
    _turn(engine, AN)
    seen = _answering(engine)
    events = _attacked(engine)
    assert not [row for row in seen if row["checkpoint"].startswith("READY:")] and not _hits_on_foe(events)
    engine.state.round_number += 1  # the next round: the same preparation answers again before my turn
    _turn(engine, AN)
    seen = _answering(engine)
    assert len(_hits_on_foe(_attacked(engine))) == 1 and [row for row in seen if row["checkpoint"].startswith("READY:")]


def test_decline_keeps_waiting_and_the_declaration_ends_at_your_next_turn():
    engine = _fighter()
    _prepare(engine)
    _turn(engine, AN)
    seen = _answering(engine, use="DECLINE")
    _attacked(engine)
    me = engine.state.actors[ME]
    assert [row for row in seen if row["checkpoint"].startswith("READY:")] and me.reaction_available and len(_held(me)) == 1
    _turn(engine, ME)
    assert not _held(me)


def test_an_action_against_someone_else_or_out_of_reach_does_not_fire_the_you_trigger():
    engine = _fighter(foe_at=(9, 6))
    _prepare(engine)
    _turn(engine, AN)
    seen = _answering(engine)
    _foe_does(engine, lambda c: c.display_name == "Dodge")
    assert not [row for row in seen if row["checkpoint"].startswith("READY:")] and len(_held(engine.state.actors[ME])) == 1


def test_leaving_reach_is_answered_before_the_foe_moves():
    engine = _fighter()
    _prepare(engine, trigger="leaves")
    _turn(engine, AN)
    _answering(engine)
    foe = engine.state.actors[AN]
    events = _foe_does(engine, lambda c: c.kind == "MOVE" and c.destination is not None and c.destination.x >= 7)
    order = [e.event_type for e in events]
    assert order.index("REACTION_RESOLVED") < order.index("MOVEMENT_COMMITTED")
    struck = [e for e in _hits_on_foe(events) if "COUNTERSTRIKE" in e.source_definition_id]
    opportunity = [e for e in _hits_on_foe(events) if "opportunity" in e.source_definition_id]
    assert len(struck) == 1 and foe.position.x >= 7
    assert len(opportunity) == 1  # the regained Reaction "may be spent normally": the leaving foe provokes as usual


def test_a_foe_that_moves_into_reach_is_struck_when_it_lands():
    engine = _fighter(foe_at=(8, 6))
    _prepare(engine, trigger="enters")
    _turn(engine, AN)
    _answering(engine)
    events = _foe_does(engine, lambda c: c.kind == "MOVE" and c.destination is not None and (c.destination.x, c.destination.y) == (4, 6))
    order = [e.event_type for e in events]
    assert order.index("MOVEMENT_COMMITTED") < order.index("REACTION_RESOLVED") and len(_hits_on_foe(events)) == 1


def test_a_move_that_stays_out_of_reach_is_not_an_entry():
    engine = _fighter(foe_at=(9, 6))
    _prepare(engine, trigger="enters")
    _turn(engine, AN)
    seen = _answering(engine)
    _foe_does(engine, lambda c: c.kind == "MOVE" and c.destination is not None and (c.destination.x, c.destination.y) == (8, 6))
    assert not [row for row in seen if row["checkpoint"].startswith("READY:")]


# ---------------------------------------------------------------------------------------------------- Raging Bull
def test_raging_bull_charges_in_a_straight_line_then_strikes_and_provokes():
    plain = _fighter(foe_at=(7, 6))  # four squares away: too far for the plain Counterstrike
    _prepare(plain)
    _turn(plain, AN)
    seen = _answering(plain)
    _foe_does(plain, lambda c: ME in (c.target_ids or ()) and c.display_name.startswith("Scouring"), ())
    assert not [row for row in seen if row["checkpoint"].startswith("READY:")]  # out of reach: it keeps waiting
    engine = _fighter(foe_at=(7, 6))
    _prepare(engine, "Counterstrike + Raging Bull")
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    me = engine.state.actors[ME]
    _turn(engine, AN)
    _answering(engine)
    events = _foe_does(engine, lambda c: ME in (c.target_ids or ()) and c.display_name.startswith("Scouring"), ())
    move = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME)
    assert move.payload["cost_ft"] == 15 and move.payload["counterstrike"] == "raging_bull"
    assert (me.position.x, me.position.y) == (6, 6) and len(_hits_on_foe(events)) == 1
    order = [e.event_type for e in events]
    assert order.index("MOVEMENT_COMMITTED") < order.index("REACTION_RESOLVED")
    assert _replayed(engine, before, start).actors[ME].position == me.position


def test_raging_bull_needs_a_clear_straight_line_within_half_the_speed():
    engine = _fighter(foe_at=(7, 7))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    from combat.ext import counterstrike

    assert [(p.x, p.y) for p in counterstrike._straight_charge(engine, me, foe, 5)] == [(4, 6), (5, 6), (6, 6)]  # 15 ft east, adjacent
    foe.position = Position(x=8, y=6)
    assert counterstrike._straight_charge(engine, me, foe, 5) is None  # a fourth square would be more than half of 30 feet
    foe.position = Position(x=4, y=6)
    assert counterstrike._straight_charge(engine, me, foe, 5) == []  # in reach already: nothing to cross
    blocker = foe.model_copy(deep=True, update={"entity_id": "test:blocker", "position": Position(x=4, y=6)})
    engine.state.actors["test:blocker"] = blocker
    engine.actor_footprints["test:blocker"] = engine.actor_footprints[AN]
    foe.position = Position(x=6, y=6)
    assert counterstrike._straight_charge(engine, me, foe, 5) is None  # the only line runs through an occupied square


# ---------------------------------------------------------------------------------------------------- Reflexive Preparation
def test_reflexive_preparation_prepares_counterstrike_for_a_bonus_action_and_martial_focus():
    engine = _fighter()
    me = engine.state.actors[ME]
    focus = me.resources["resource:core.martial_focus"]
    assert focus >= 1 and me.action_available and me.bonus_action_available
    _answering(engine, trigger="me", variant="Counterstrike + Haymaker")
    _use(engine, "Reflexive Preparation")
    held = _held(me)
    assert len(held) == 1 and me.action_available and not me.bonus_action_available  # the Action is untouched
    assert me.resources["resource:core.martial_focus"] == focus - 1
    assert held[0].data["data"]["trigger"] == "targets_me" and held[0].data["data"]["variant"].endswith("+b81629b754")
    _turn(engine, AN)
    _answering(engine)
    events = _attacked(engine)
    assert len(_hits_on_foe(events)) == 1


def test_reflexive_preparation_lists_every_counterstrike_by_name_and_runs_its_use_effects():
    engine = _fighter(talents=[*TALENTS, "TAL_RETRIBUTION_TIGHT_GUARD"])
    me = engine.state.actors[ME]
    ac = engine._ac_modifier(me)
    seen = _answering(engine, trigger="enters", variant="Counterstrike + Raging Bull")
    _use(engine, "Reflexive Preparation")
    asked = next(row for row in seen if row["reaction_source_id"] == "choice:needle.counterstrike")
    labels = set(asked["choice_trigger"]["labels"].values())
    assert len(asked["legal_option_ids"]) == 24  # three variants, two attacks, four triggers
    assert labels == {
        f"{variant} ({weapon}), when {text}"
        for variant in ("Counterstrike", "Counterstrike + Haymaker", "Counterstrike + Raging Bull")
        for weapon in ATTACK_NAMES for name, text in TRIGGERS.items() if name != "hostile"}
    held = _held(me)[0].data["data"]
    assert held["trigger"] == "enters_reach" and held["bull"] is True
    assert engine._ac_modifier(me) > ac  # Tight Guard's bonus for preparing, from Reflexive Preparation too


def test_plain_fighters_get_no_ready_declarations():
    from tests.test_auto_docket import DARK

    engine = _fight(_sheet(DARK, ["tianxia.sphere.dark"]))
    assert not [name for name in _names(engine) if name.startswith(("Ready", "Counterstrike"))]
    assert not ext.run("prepare_options", engine, engine.state.actors[ME])


# ---------------------------------------------------------------------------------------------------- Realm Evolutions and the Court
def test_heaven_reading_stillness_adds_the_any_hostile_action_trigger():
    plain = _fighter()
    assert not [c for c in plain.legal_candidates() if TRIGGERS["hostile"] in c.display_name]
    engine = _fighter(talents=[*TALENTS, "TAL_RETRIBUTION_HEAVEN_READING_STILLNESS"])
    me = engine.state.actors[ME]
    seen = _answering(engine, trigger="hostile")
    _use(engine, "Counterstrike")
    asked = next(row for row in seen if row["reaction_source_id"] == "choice:needle.counterstrike")
    assert len(asked["legal_option_ids"]) == 10 and _held(me)[0].data["data"]["trigger"] == "hostile_action"
    assert set(asked["choice_trigger"]["labels"].values()) == {
        f"Counterstrike ({weapon}), when {text}" for weapon in ATTACK_NAMES for text in TRIGGERS.values()}
    _turn(engine, AN)
    seen = _answering(engine)
    _foe_does(engine, lambda c: c.display_name in ("Dodge", "Ruin-Tempered Armament — Quick"), ())  # defensive or a buff on itself: not hostile
    assert not [row for row in seen if row["checkpoint"].startswith("READY:")]
    _turn(engine, AN)
    events = _attacked(engine)  # an attack is a hostile action
    assert len(_hits_on_foe(events)) == 1


def test_the_court_adds_a_trigger_regains_focus_and_denies_the_targets_reactions():
    engine = _fighter(talents=[*TALENTS, "TAL_RETRIBUTION_COURT_OF_THE_AWAITING_BLADE"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _use(engine, "Court of the Awaiting Blade")
    assert me.resources[FOCUS] == 0
    me.bonus_action_available = True
    seen = _answering(engine, trigger="me", extra="leaves")
    _use(engine, "Counterstrike")
    assert [row["reaction_source_id"] for row in seen].count("choice:needle.counterstrike_extra") == 1
    held = _held(me)[0].data
    assert held["data"]["triggers"] == ["targets_me", "leaves_reach"] and held["label"].endswith("or when a foe in your reach starts to move away")
    _turn(engine, AN)
    _answering(engine)
    _attacked(engine)
    assert me.resources[FOCUS] == 1  # "once per round when your Counterstrike hits, regain Martial Focus"
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())  # "the target cannot take Reactions"
    assert me.turn_flags[f"once_per_round:court_focus:{engine.state.round_number}"] is True


def test_the_court_does_nothing_for_a_fighter_who_never_raised_it():
    engine = _fighter(talents=[*TALENTS, "TAL_RETRIBUTION_COURT_OF_THE_AWAITING_BLADE"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    seen = _answering(engine, trigger="me")
    _use(engine, "Counterstrike")
    assert not [row for row in seen if row["reaction_source_id"] == "choice:needle.counterstrike_extra"]
    _turn(engine, AN)
    _answering(engine)
    _attacked(engine)
    assert me.resources[FOCUS] == 1 and not any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())


def test_two_answers_makes_two_counterstrikes_a_round_but_never_two_in_one_creatures_turn():
    from combat.ext import counterstrike
    from combat.gate2_runtime_content import LEE

    engine = _fight(_sheet([*TALENTS, "TAL_RETRIBUTION_COURT_OF_THE_AWAITING_BLADE", "TAL_RETRIBUTION_TWO_ANSWERS_WITHIN_ONE_BREATH"],
                           ["tianxia.sphere.retribution"], **WEAPON), foe_at=(4, 6), second_foe=(3, 7))
    me = engine.state.actors[ME]
    for foe in (AN, LEE):
        engine.state.actors[foe].armor_class = -50
    assert counterstrike.limit(engine, me) == 1  # the Court is not up yet
    _use(engine, "Court of the Awaiting Blade")
    assert counterstrike.limit(engine, me) == 2
    me.bonus_action_available = True
    _answering(engine, trigger="me")
    _use(engine, "Counterstrike")
    _turn(engine, AN)
    _answering(engine)
    assert len(_hits_on_foe(_attacked(engine))) == 1
    assert len(_held(me)) == 1 and counterstrike.used(engine, me) == (1, AN)
    assert counterstrike._spent(engine, me)  # a second one in the same creature's turn: no
    _turn(engine, LEE)
    assert not counterstrike._spent(engine, me)  # another creature's turn: the second answer of the round
    _answering(engine)
    # rider lane 9: an action with a mode choice (Lightning Lash) lists every mode in option_ids, which is not one legal pick; candidate
    # order follows the compiled catalog, so take an action without a choice
    events = _foe_does(engine, lambda c: ME in (c.target_ids or ()) and c.kind == "ACTION" and c.display_name != "Dodge" and not c.option_ids)
    assert len(_hits_on_foe(events)) == 1 and counterstrike.used(engine, me)[0] == 2
    _turn(engine, AN)
    assert counterstrike._spent(engine, me)  # two is the most a round allows
