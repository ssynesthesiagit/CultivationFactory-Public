"""Only defensive guards follow a useful safe approach in the turn plan."""
from types import SimpleNamespace as NS

import pytest

from combat.ai_tactics import TurnPlan
from combat.gate4_models import CandidateScore, ComponentScore


@pytest.mark.parametrize("guard,action,move,hazard,expected", [
    (False, 100, 20, False, 20),
    (False, 10, 11, False, 11),
    (True, 100, 20, False, 120),
    (True, 100, 20, True, 20),
    (True, 100, 0, False, 0),
    (True, -5, 1, False, 1),
])
def test_self_followup_only_rewards_safe_guard_approach(guard, action, move, hazard, expected):
    plan = NS(enabled=True, has_strike=False, actor=NS(entity_id="me"),
              actions={"self": {"guard": guard}}, context=NS(policy=NS(role=())))
    candidates = {
        "action": NS(kind="ACTION", destination=None, source_definition_id="self",
                     metadata={}, target_ids=("me",)),
        "move": NS(kind="MOVE", destination=(1, 0), source_definition_id="move",
                   metadata={"zone_hazard_exposure": hazard}, target_ids=()),
    }
    scores = [
        CandidateScore(candidate_id="action", option_ids=(), total=action,
                       components=(ComponentScore(component="target", value=action, explanation="test"),)),
        CandidateScore(candidate_id="move", option_ids=(), total=move, components=()),
    ]
    result = TurnPlan.with_self_followups(plan, scores, candidates)
    assert result[1].total == expected
