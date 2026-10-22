"""The AI strikes from the square it holds: a priced utility row is not an attack.

MAINREDTHROW1: "Pick up <weapon>" is compiled with an expected_damage price so the
planner values recovering a disarmed weapon. TurnPlan read that price as an
attack, so the recovery row's nominal 5-foot reach became the turn's attack
range and its sharing value became the reward for an enabling move: the AI
walked 15 feet into contact instead of throwing the axe it already had in reach,
and the thrown axe stayed where the thrower stood.
"""
from combat.ai_tactics import TurnPlan
from tests.test_thrown_possession import fixture


def test_priced_recovery_row_is_not_the_turns_attack(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    plan = TurnPlan(context)
    recovery = [aid for aid in plan.actions if aid.endswith(".pickup")]
    assert recovery, "the recovery row must be in the owned profile"
    assert plan.actions[recovery[0]]["damage"] > 0, "its damage price is kept for scoring"
    assert not plan.actions[recovery[0]]["attack"], "a recovery row is not an attack"
    assert plan.range_error(plan.actor.position) == 0, "the offered throw already covers this square"


def test_ai_throws_from_where_it_stands(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    choice = combat.controller.choose_primary_action(context)
    chosen = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert chosen.source_definition_id.endswith("#thrown"), chosen.source_definition_id
