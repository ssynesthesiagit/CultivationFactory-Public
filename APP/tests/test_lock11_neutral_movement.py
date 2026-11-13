"""A neutral move cannot beat an equally valuable non-move by candidate hash."""
import pytest
from combat.gate4_controller import LocalDeterministicController
from tests.test_combat_gate4_controller import engine, choose, AN


@pytest.mark.parametrize('improvement,kind', [(-1, 'END_TURN'), (0, 'END_TURN'), (1, 'MOVE')])
@pytest.mark.parametrize('reverse', [False, True])
def test_move_must_improve_score_and_choice_is_order_independent(improvement, kind, reverse):
    e = engine('LOCK11-NEUTRAL')
    _, context = choose(e, AN)
    move = next(c for c in context.legal_candidates if c.kind == 'MOVE').model_copy(update={'candidate_id': 'candidate:a'})
    end = next(c for c in context.legal_candidates if c.kind == 'END_TURN').model_copy(update={'candidate_id': 'candidate:z'})
    actor = next(a for a in context.actors if a.entity_id == AN)
    policy = context.policy.model_copy(update={'position_relative': True,
        'action_priorities': {move.source_definition_id: improvement}})
    context = context.model_copy(update={'actors': (actor,), 'policy': policy,
        'recent_events': (), 'legal_candidates': (end, move) if reverse else (move, end)})
    before = context.model_dump(mode='json')
    controller = LocalDeterministicController()
    choice = controller.choose_primary_action(context)
    if not improvement:
        assert len({s.total for s in choice.record.scored_alternatives}) == 1
    picked = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert picked.kind == kind
    assert choice.record.deterministic_tie_break == (
        'highest integer total, then non-movement choices, then candidate_id, then option_ids')
    assert controller.choose_primary_action(context) == choice
    assert context.model_dump(mode='json') == before


@pytest.mark.parametrize('kind', ['END_TURN', 'MOVE'])
@pytest.mark.parametrize('reverse', [False, True])
def test_nonmove_and_move_only_ties_keep_stable_candidate_order(kind, reverse):
    e = engine('LOCK11-NEUTRAL')
    _, ctx = choose(e, AN)
    candidate = next(c for c in ctx.legal_candidates if c.kind == kind)
    rows = tuple(candidate.model_copy(update={'candidate_id': f'candidate:{key}'}) for key in ('z', 'a'))
    if reverse:
        rows = tuple(reversed(rows))
    assert all(row.kind == kind for row in rows)
    ctx = ctx.model_copy(update={'legal_candidates': rows})
    choice = LocalDeterministicController().choose_primary_action(ctx)
    assert len({row.total for row in choice.record.scored_alternatives}) == 1
    assert choice.intent.candidate_id == 'candidate:a'
