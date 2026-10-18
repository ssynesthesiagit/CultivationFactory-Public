"""A declined Step on My Count must not spend the leader's Command Response.

Authority: WARLEADER_BASE_COMMAND_RESPONSES (authority/typed_mechanics/rules_text.json, "Step on My Count").

Printed clause under test:

  Step on My Count -- "a Commanded ally you can see ... starts its turn, ends its
  turn, or is missed by an attack roll: it moves 5 feet without provoking
  Opportunity Attacks from one creature you can see".

Step on My Count is an optional Response. Two separate people are asked about it:
the leader spends the Response and names the one creature whose opportunity
attacks the ally ignores, and the ally owns its own destination. If either of
them says no, the Step does not happen, so the printed cost (one Command
Response, normally 1 Momentum Mark, and the round's one Response) must not be
paid for a move that never occurs. Paying first and asking afterwards silently
destroys a Momentum Mark and burns the round's Response for nothing -- the
leader can no longer Brace the Line or Strike on My Count this round.

These cases drive the real engine through the real turn_end hook with the real
choice transport, so they fail on the engine as it was before the fix (the
Momentum Mark is gone and the round's Response is spent even though the ally
never moved).

Also covered here: answering both prompts still moves the ally and still costs
exactly one Momentum Mark. That guards the fix against regressing the ordinary
Step into a free move.
"""
from __future__ import annotations

import pytest

from combat import ext
from combat.ext import warleader_commands as C
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from tests import test_sys_resources_states as W

ME, ALLY, TFOE = W.ME, W.ALLY, W.TFOE
MOMENTUM = W.MOMENTUM
RESPONSE_KEY = C.RESPONSE_KEY  # "once_per_round:wl_response": the round's one Command Response
EXEMPT = "choice:needle.command_step_exempt"
DESTINATION = "choice:needle.command_step_destination"


def _table_that_declines(engine, declines):
    """Run Step on My Count against a live player transport that declines ``declines`` and answers the rest.

    Every other reaction the engine asks for during the hook gets no answer at
    all, which is what an ordinary unanswered fight looks like, so these cases
    exercise the decline path rather than a special-cased test double.
    """
    intent = ActionIntent(intent_id="i-step", decision_id="d-step", candidate_id="c-step", state_version=0,
                          actor_id=ALLY, target_ids=())

    def provider(request):
        if request["reaction_source_id"] in declines:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        return None, None

    engine._active_intent = intent
    engine._gate4_reaction_provider = provider
    engine._gate4_reaction_cache = {}
    return intent


def _step_at_end_of_ally_turn(declines):
    engine = W._command()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert engine._distance_actor_to_actor(ally, engine.state.actors[TFOE]) <= 5  # the Step has something to do
    _table_that_declines(engine, declines)
    start, marks = ally.position, me.resources[MOMENTUM]
    ext.run("turn_end", engine, ally)
    return engine, start, marks


@pytest.mark.parametrize('declines', [(DESTINATION,), (EXEMPT,), (EXEMPT, DESTINATION)], ids=['ally-declines', 'leader-declines', 'both-decline'])
def test_a_declined_step_on_my_count_costs_the_leader_nothing(declines):
    """Either player saying no leaves the ally where it stood and the leader's Marks and Response intact."""
    engine, start, marks = _step_at_end_of_ally_turn(declines)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert ally.position == start, "a declined Step must not move the ally"
    assert me.resources[MOMENTUM] == marks, "a declined Step must not spend a Momentum Mark"
    assert RESPONSE_KEY not in me.turn_flags, "a declined Step must not use up the round's one Command Response"
    assert not any("Step on My Count" in line for line in W._logs(engine.events)), "a declined Step must not claim to have happened"
    assert not W._moved(engine.events), "a declined Step must not commit movement"


def test_an_answered_step_on_my_count_still_moves_the_ally_and_costs_exactly_one_mark():
    """The ordinary Step is unchanged: both prompts answered, the ally moves, one Momentum Mark is spent."""
    engine = W._command()
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[TFOE]
    _table_that_declines(engine, ())  # answers nothing: the automatic first options are taken, as in an AI fight
    start, marks = ally.position, me.resources[MOMENTUM]
    ext.run("turn_end", engine, ally)
    assert ally.position != start
    assert me.resources[MOMENTUM] == marks - 1
    assert me.turn_flags[RESPONSE_KEY] == engine.state.round_number
    assert W._moved(engine.events)


def test_the_whole_option_set_stays_offered_to_a_ledgers_table():
    """A leader that has not declined is still offered every visible creature, and the ally every legal square."""
    engine = W._command()
    ally, foe = engine.state.actors[ALLY], engine.state.actors[TFOE]
    offered = {}
    real = engine._gate4_reaction_provider

    def spy(request):
        if request["reaction_source_id"] in (EXEMPT, DESTINATION):
            offered[request["reaction_source_id"]] = list(request.get("legal_option_ids") or [])
        return None, None

    engine._gate4_reaction_provider = spy
    _table_that_declines(engine, ())
    engine._gate4_reaction_provider = spy
    ext.run("turn_end", engine, ally)
    assert offered[EXEMPT], "the OA exemption must still offer the creatures the leader can see"
    assert offered[DESTINATION], "the destination menu must still offer the ally's legal squares"
    assert len(offered[DESTINATION]) > 1, "the destination menu must not collapse to a single option"