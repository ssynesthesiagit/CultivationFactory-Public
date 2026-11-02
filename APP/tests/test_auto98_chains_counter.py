"""AUTO98r2f1: Chain Counter's printed successful save, at the level the reviews' findings showed.

Findings pinned here, from ``fix/AUTO98r1.review.md`` and ``fix/AUTO98r2.review.md``:

1. The "reduce its remaining movement by 5 feet" outcome did nothing to a flyer that still had
   flight: the walking pool was already at 0 and the feet a flyer holds beyond its walking Speed
   live in a separate allowance. ``combat/flight.restrict`` now prices the request against
   ``combat/flight.budget`` -- the movement the creature can actually spend, over every mode it is
   in a position to use -- and the outcome is not offered at all when there is nothing left to
   take.
2. The same gate was wrong in the other direction for a flyer SLOWER than it walks: with walking
   Speed 30 and Fly 10, fifteen walked feet are fifteen usable feet even though its flight is
   exhausted, so the option used to be hidden, and with only three flight feet left the helper
   used to take three out of twenty-three usable walking feet.
3. The pull regression accepted any forced ``MOVEMENT_COMMITTED`` event, so a zero-distance pull
   against a blocked square satisfied it. ``test_the_printed_pull_moves_the_target_exactly_five_feet``
   runs a legal attack from 10 feet, where the pull can actually land, and pins the destination.
4. The prompt named the Chain Counter reaction instead of the attack it interrupted, so a dagger
   attack produced text describing Chain Counter interrupting. It also called EVERY trigger an
   incoming attack, although Chain Counter's printed trigger also covers a creature entering
   reach -- which is how the flight cases here are set off.

Every case drives the real table: the opponent really attacks (or really walks in), Chain Counter
really answers, the owner is really asked, and the result is read back after a commit through a
fresh CombatService (``reload`` also asserts full-state equality and a PASSING mechanical replay).
"""
import pytest

from combat import falling, flight
from combat.flight import profile as flight_profile
from combat.gate2_runtime_models import Position
from combat.flight import remaining as flight_remaining
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, turn

COUNTER = "tianxia.talent.chains.chain_counter"
CHOICE = "chains_counter_success"
LOOSE_SAVE_DC = 1        # the owner's save DC, low enough that the opponent always succeeds its save
ATTACK = "Bi Shou (Dagger) attack"
THROWN = "Bi Shou (Dagger) thrown"
MOVED = "moves into your reach"   # what the prompt must say when a walk, not an attack, set it off


def flyer(speed=40):
    """Give the opponent a Fly Speed; slower than its walking Speed when ``speed`` < 30."""
    def edit(bundle):
        if bundle["actor_template"]["entity_id"] == RIGHT:
            bundle["actor_template"].update(fly_speed_ft=speed, hover=True)
    return edit


def rooted(bundle):
    """An opponent with no Speed at all: it can attack but never move."""
    if bundle["actor_template"]["entity_id"] == RIGHT:
        bundle["actor_template"].update(speed_ft=0)


def respond(table, mid, state, candidate_id, outcome=None, limit=10):
    """Commit one action, answering every reaction and choice prompt it raises.

    Chain Counter's own reaction is answered USE; its printed successful save takes ``outcome``.
    Returns the final result and every prompt raised along the way.
    """
    answers = []
    prompts = []
    for _ in range(limit):
        menu = state["menu"]
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        ids = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [outcome] if outcome in ids else []})
        state = result["state"]
    raise AssertionError("the table never finished the action")


def attack(table, mid, outcome, label=ATTACK):
    """RIGHT really attacks LEFT; returns the prompts raised, so a test can read what it was told."""
    state = table.state(mid)
    candidate = next(o["candidate_id"] for g in state["menu"]["actions"] if g["label"] == label
                     for o in g["options"])
    return respond(table, mid, state, candidate, outcome)[1]


def counter_prompts(prompts):
    return [p for p in prompts if str(p["context"]["reaction_source_id"]).endswith(CHOICE)]


def cell(destination):
    """A square as (x, y, z); the table omits ``z`` at ground level."""
    return (int(destination["x"]), int(destination["y"]), int(destination.get("z", 0)))


def move_to(table, mid, destination):
    """Spend this turn's movement reaching the square ``destination``; returns the feet charged."""
    state = table.state(mid)
    menu = state["menu"]
    option = next(o for o in menu["moves"] if cell(o["destination"]) == destination)
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], [])
    assert result["status"] == "COMMITTED", result
    return int(option["cost_ft"] or 0)


def feet_between(engine, one, other):
    """The table's own square distance, in feet -- altitude included."""
    return engine.grid.distance_ft(Position(x=one[0], y=one[1], z=one[2]),
                                   Position(x=other[0], y=other[1], z=other[2]))


def spend(table, mid, combat, feet, holder, outcome=None):
    """Spend exactly ``feet`` of this turn's movement, landing next to the Chain Counter holder.

    Landing next to the holder is itself a printed Chain Counter trigger ("enters your reach"),
    so the prompts it raises are returned for the caller to inspect.
    """
    engine = reload(combat, mid)
    state = table.state(mid)
    option = next(o for o in sorted(state["menu"]["moves"], key=lambda o: (int(o["cost_ft"]), cell(o["destination"])))
                  if int(o["cost_ft"]) == feet and feet_between(engine, cell(o["destination"]), holder) == 5)
    assert int(option["cost_ft"]) == feet, f"no {feet}-foot move lands next to the holder"
    landed = cell(option["destination"])
    prompts = respond(table, mid, state, option["candidate_id"], outcome)[1]
    return landed, prompts


def flying_movement(engine, actor):
    """The flying pool alone; walking may still be left even when this is empty."""
    return flight_remaining(engine, actor, "fly") if flight_profile(engine, actor).speed_ft else 0


def positions():
    return {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}


def ranged_positions():
    """10 feet apart and off the holder's own row, so the pull has two clear squares.

    Straight ahead of an adjacent holder the only square toward it is the holder's own, which
    blocks a 10-foot pull onto the same square a 5-foot pull reaches. Stepping diagonally keeps
    both squares clear, so the exact distance the printed pull covers is observable.
    """
    return {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 5, "y": 7}}


def test_successful_save_asks_the_owner_for_the_printed_choice(tmp_path):
    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC, positions=positions())
    turn(table, mid, RIGHT)
    asked = counter_prompts(attack(table, mid, None))
    assert asked, "Chain Counter never offered its printed successful-save choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"pull", "withhold"}
    said = str(asked[0])
    assert "Chain Counter" in said, said
    assert "5 feet" in said and "movement" in said, said
    # Finding 3: the prompt names the attack that was interrupted, not the reaction answering it.
    assert "Chain Counter: Chain Counter interrupts" not in said, said
    assert ATTACK in said, said


def test_the_printed_pull_moves_the_target_exactly_five_feet(tmp_path):
    """Finding 2: a legal attack from 10 feet, where the pull really lands."""
    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC,
                               positions=ranged_positions())
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].position
    assert (before.x, before.y) == (5, 7), before
    assert counter_prompts(attack(table, mid, "pull", label=THROWN)), "the printed choice was never asked"
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    # Exactly one 5-foot square toward the holder, and no more.
    assert (foe.position.x, foe.position.y) == (4, 6), foe.position
    pulls = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.source_definition_id == COUNTER and (e.payload or {}).get("forced")]
    assert len(pulls) == 1, pulls
    # Exactly one 5-foot square toward the holder: start, then the square it lands on.
    assert [cell(step) for step in pulls[0].payload["path"]] == \
        [(5, 7, 0), (4, 6, 0)], pulls[0].payload
    assert cell(pulls[0].payload["destination"]) == (4, 6, 0), pulls[0].payload
    assert pulls[0].actor_id == RIGHT, pulls[0]


def test_a_blocked_pull_reports_the_printed_choice_without_moving_anyone(tmp_path):
    """The blocked-space case finding 2 asked to retain: adjacent, so the pull has nowhere to go."""
    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC, positions=positions())
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].position
    assert counter_prompts(attack(table, mid, "pull")), "the printed choice was never asked"
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    pulls = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.source_definition_id == COUNTER and (e.payload or {}).get("forced")]
    assert pulls, "the printed pull of 5 feet did not run at all"
    # Adjacent to the holder, so it stays where it is rather than stepping into an occupied square.
    assert (foe.position.x, foe.position.y) == (before.x, before.y), foe.position


def test_taking_five_feet_off_a_walkers_movement(tmp_path):
    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC, positions=positions())
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].movement_remaining_ft
    assert counter_prompts(attack(table, mid, "withhold")), "the printed choice was never asked"
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    pulls = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.source_definition_id == COUNTER and (e.payload or {}).get("forced")]
    assert not pulls, f"the printed movement reduction moved the creature: {pulls}"
    assert foe.movement_remaining_ft == before - 5, (before, foe.movement_remaining_ft)


def test_supported_elevated_walker_keeps_the_choice_and_loses_five_feet_after_reload(tmp_path):
    """SOLFAUTO98r3: walking on a finite platform does not require a Fly Speed."""
    def platform(arena):
        arena["terrain_regions"] = [{"terrain_type": "BLOCKED", "height_ft": 10, "movement_cost": 1,
                                     "cells": [{"x": x, "y": y}
                                               for x in range(2, 7) for y in range(1, 9)]}]

    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC,
                               positions={LEFT: {"x": 4, "y": 6, "z": 2},
                                          RIGHT: {"x": 3, "y": 2, "z": 2}}, arena_edit=platform)
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert falling.supported(engine, foe) and foe.position.z == 2
    assert foe.speed_ft == 30 and flight_profile(engine, foe).speed_ft == 0
    assert foe.movement_remaining_ft == 30

    # The real ten-foot walk triggers the counter with twenty walking feet left.
    state = table.state(mid)
    option = next(o for o in state["menu"]["moves"] if cell(o["destination"]) == (3, 4, 2))
    assert int(option["cost_ft"]) == 10
    asked = counter_prompts(respond(table, mid, state, option["candidate_id"], "withhold")[1])
    assert asked, "Chain Counter never offered its printed successful-save choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"pull", "withhold"}
    assert "cannot move right now" not in asked[0]["moment"]
    assert "spent its movement" not in asked[0]["moment"]
    # A fresh service checks full state equality and mechanical replay after the table commit.
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert foe.position == Position(x=3, y=4, z=2)
    assert foe.movement_remaining_ft == flight.budget(engine, foe).available_ft == 15
    assert foe.turn_flags.get("flight_movement_overrun_ft", 0) == 0
    reductions = [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED"
                  and e.source_definition_id == COUNTER and e.actor_id == RIGHT]
    assert [e.payload["distance_ft"] for e in reductions] == [-5]


def test_unsupported_airborne_creature_without_flight_keeps_zero_budget(tmp_path):
    """Altitude without support still bars walking, even with an unspent allowance.

    Hover holds this synthetic target aloft for the real table choice; it grants no Fly Speed.
    This isolates the budget gate from the separate automatic falling machinery.
    """
    def held_aloft(bundle):
        if bundle["actor_template"]["entity_id"] == RIGHT:
            bundle["actor_template"]["hover"] = True

    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC,
                               bundle_edit=held_aloft,
                               positions={LEFT: {"x": 3, "y": 6},
                                          RIGHT: {"x": 4, "y": 6, "z": 1}})
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert not falling.supported(engine, foe) and foe.position.z == 1
    assert flight_profile(engine, foe).speed_ft == 0
    assert foe.movement_remaining_ft == 30
    assert flight.budget(engine, foe).available_ft == 0
    before = foe.model_dump(mode="json")
    assert flight.restrict(engine, foe, 5) == 0
    assert foe.model_dump(mode="json") == before

    asked = counter_prompts(attack(table, mid, None))
    assert asked, "Chain Counter never offered its printed successful-save choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"pull"}
    assert "cannot move right now" in asked[0]["moment"]
    assert "spent its movement" not in asked[0]["moment"]
    reload(combat, mid)


def flight_setup(tmp_path, holder=(4, 9, 0), speed=40):
    """A flyer whose holder sits one square from where its flight or walk will land."""
    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC, bundle_edit=flyer(speed),
                               positions={LEFT: {"x": holder[0], "y": holder[1]}, RIGHT: {"x": 3, "y": 2}})
    turn(table, mid, RIGHT)
    return combat, table, mid, holder


def test_taking_five_feet_off_the_flight_a_flyer_has_left(tmp_path):
    """Finding 1: the review's example -- walking Speed 30, Fly 40, 35 feet flown, 5 feet left.

    The old code trimmed ``movement_remaining_ft``, which is already 0 here, so the flyer kept all
    five of its remaining feet. This pins the actual flight budget instead. Entering the holder's
    reach is a printed Chain Counter trigger, so the 35-foot flight is itself the trigger.
    """
    combat, table, mid, holder = flight_setup(tmp_path)
    landed, prompts = spend(table, mid, combat, 35, holder, outcome="withhold")
    engine = reload(combat, mid)
    flyer_state = engine.state.actors[RIGHT]
    assert feet_between(engine, landed, holder) == 5, landed
    assert flyer_state.speed_ft == 30 and flyer_state.fly_speed_ft == 40, (
        flyer_state.speed_ft, flyer_state.fly_speed_ft)
    asked = counter_prompts(prompts)
    assert asked, "Chain Counter never offered its printed successful-save choice"
    # Finding 4: this reaction answered a walk into reach, and says so instead of inventing an
    # attack. The ability's printed rules quote "makes a melee attack", so read the prompt's own
    # words, not the whole record.
    assert MOVED in asked[0]["moment"], asked[0]["moment"]
    assert "attack" not in asked[0]["moment"], asked[0]["moment"]
    # The five feet are gone from the flight allowance, not merely from the empty walking pool.
    assert flight.budget(engine, flyer_state).available_ft == 0, flight.budget(engine, flyer_state)
    assert flying_movement(engine, flyer_state) == 0, flying_movement(engine, flyer_state)
    assert flyer_state.movement_remaining_ft == 0, flyer_state.movement_remaining_ft
    assert flyer_state.turn_flags.get("flight_movement_overrun_ft") == 10, flyer_state.turn_flags

    # The reduction lasts this turn only: the next turn is a fresh allowance.
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert flight.budget(engine, engine.state.actors[RIGHT]).available_ft == 40, \
        flight.budget(engine, engine.state.actors[RIGHT])


def test_a_slow_flyer_can_still_lose_its_walking_movement(tmp_path):
    """Finding 2, first half: walking Speed 30 with Fly 10, fifteen feet walked.

    Its flight is exhausted (the flying pool is walking allowance plus Fly less Speed, so fifteen
    walked feet of a 30-foot walk leave none), but it is on the ground with fifteen walking feet
    left -- and ``flight.reachable`` still offers those ground routes. The old gate read the flying
    pool alone, so it hid the printed outcome and claimed the creature had spent its movement.
    """
    combat, table, mid, holder = flight_setup(tmp_path, holder=(4, 6, 0), speed=10)
    landed, prompts = spend(table, mid, combat, 15, holder, outcome="withhold")
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert feet_between(engine, landed, holder) == 5, landed
    assert foe.speed_ft == 30 and foe.fly_speed_ft == 10, (foe.speed_ft, foe.fly_speed_ft)
    assert foe.position.z == 0, foe.position

    asked = counter_prompts(prompts)
    assert asked, "Chain Counter never offered its printed successful-save choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"pull", "withhold"}, \
        asked[0]["choice"]["options"]
    assert "spent its movement" not in asked[0]["moment"], asked[0]["moment"]

    # Before the choice: no flight left, but fifteen walking feet.
    assert flying_movement(engine, foe) == 0, flying_movement(engine, foe)
    # After it: five of those fifteen walking feet are gone, and none came out of flight.
    assert foe.movement_remaining_ft == 10, foe.movement_remaining_ft
    assert foe.turn_flags.get("flight_movement_overrun_ft", 0) == 0, foe.turn_flags
    assert flight.budget(engine, foe).available_ft == 10, flight.budget(engine, foe)


def test_five_feet_come_off_a_slow_flyer_with_less_than_five_flight_feet_left(tmp_path):
    """Finding 2, second half: walking Speed 30 with Fly 12, ten feet walked.

    That leaves twenty feet in the shared allowance, of which the flying pool is two (walking
    allowance plus Fly less Speed), so the old helper priced the printed five feet against the
    flight alone and took two. It has to take five.
    """
    combat, table, mid, holder = flight_setup(tmp_path, holder=(4, 5, 0), speed=12)
    landed, prompts = spend(table, mid, combat, 10, holder, outcome="withhold")
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert feet_between(engine, landed, holder) == 5, landed
    assert foe.speed_ft == 30 and foe.fly_speed_ft == 12, (foe.speed_ft, foe.fly_speed_ft)

    asked = counter_prompts(prompts)
    assert asked, "Chain Counter never offered its printed successful-save choice"
    # Twenty feet walked off a 30-foot walking Speed leaves twenty; five more come off, so the
    # old two-foot reduction is not what happened.
    assert foe.movement_remaining_ft == 15, foe.movement_remaining_ft
    assert foe.turn_flags.get("flight_movement_overrun_ft", 0) == 0, foe.turn_flags
    assert flying_movement(engine, foe) == 0, flying_movement(engine, foe)


def test_a_creature_with_no_movement_left_is_not_offered_the_movement_choice(tmp_path):
    """Finding 1's gate: "reduce its remaining movement by 5 feet" cannot mean anything at 0 feet."""
    combat, table, mid, holder = flight_setup(tmp_path, holder=(4, 10, 0))
    landed, prompts = spend(table, mid, combat, 40, holder)
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert feet_between(engine, landed, holder) == 5, landed
    assert foe.movement_remaining_ft == 0, foe.movement_remaining_ft

    asked = counter_prompts(prompts)
    assert asked, "Chain Counter never offered its printed successful-save choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"pull"}, asked[0]["choice"]["options"]
    # The prompt says plainly why the second printed outcome is not on offer.
    assert "spent its movement this turn" in str(asked[0]), asked[0]
    assert "movement" in str(asked[0]), asked[0]
    # Flying its whole 40 feet leaves nothing to take anything from.
    assert flight.budget(engine, foe).available_ft == 0, flight.budget(engine, foe)


def test_a_creature_that_cannot_move_is_told_so_rather_than_that_it_spent_its_movement(tmp_path):
    """Finding 2's wording: a creature with no Speed had no movement to spend.

    It attacked, so Chain Counter answered and its save succeeded, but "reduce its remaining
    movement by 5 feet" cannot apply to something that was never granted any. The prompt must not
    say the creature spent movement it never had.
    """
    combat, table, mid = fight(tmp_path, [COUNTER], left_save_dc=LOOSE_SAVE_DC, bundle_edit=rooted,
                               positions=positions())
    turn(table, mid, RIGHT)
    asked = counter_prompts(attack(table, mid, None))
    assert asked, "Chain Counter never offered its printed successful-save choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"pull"}, asked[0]["choice"]["options"]
    said = asked[0]["moment"]
    assert "cannot move right now" in said, said
    assert "spent its movement" not in said, said
    engine = reload(combat, mid)
    budget = flight.budget(engine, engine.state.actors[RIGHT])
    assert budget.granted_ft == 0 and budget.available_ft == 0, budget


def test_a_character_without_chain_counter_is_never_asked(tmp_path):
    combat, table, mid = fight(tmp_path, [], left_save_dc=LOOSE_SAVE_DC, positions=positions())
    turn(table, mid, RIGHT)
    assert not counter_prompts(attack(table, mid, None))
