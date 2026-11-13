"""Movement must earn its place before inheriting an available self action."""
from types import SimpleNamespace as NS

import pytest

from combat.ai_tactics import TurnPlan
from combat.gate4_models import CandidateScore, ComponentScore


@pytest.mark.parametrize("part,action,move", [
    ("immediate_effect", 100, 20),
    ("character_policy", -5, 1),
    ("target", 10, 11),
])
def test_self_followup_only_rewards_independently_better_safe_moves(part, action, move):
    plan = NS(enabled=True, has_strike=False, actor=NS(entity_id="me"), actions={},
              context=NS(policy=NS(role=())))
    candidates = {
        "action": NS(kind="ACTION", destination=None, source_definition_id="self",
                     metadata={}, target_ids=("me",)),
        "move": NS(kind="MOVE", destination=(1, 0), source_definition_id="move",
                   metadata={}, target_ids=()),
    }
    scores = [
        CandidateScore(candidate_id="action", option_ids=(), total=action,
                       components=(ComponentScore(component=part, value=action, explanation="test"),)),
        CandidateScore(candidate_id="move", option_ids=(), total=move, components=()),
    ]
    result = TurnPlan.with_self_followups(plan, scores, candidates)
    expected = move + action if action > 0 and move > action else move
    assert result[1].total == expected
