"""A technique target can also respond to its activation, within ordinary row limits."""
import pytest

from combat import typed_reactions
from combat.gate2_runtime_content import AN
from tests.test_reaction_effects_r6 import _engine, _row, REACTOR


@pytest.mark.parametrize("free", [False, True])
def test_target_response_priority_and_free_response_overlap(free):
    target_row = _row("technique_targets", [{"type": "temp_hp", "flat": 3}], free=free)
    used_row = _row("technique_used", [{"type": "temp_hp", "flat": 7}], range_ft=60)
    engine = _engine([target_row, used_row])
    target = engine.state.actors[REACTOR]
    typed_reactions.on_technique_start(engine, engine.state.actors[AN], [target, target], {"numbers": {}})
    events = [e for e in engine.events if e.event_type == "REACTION_RESOLVED"]
    assert [e.source_definition_id for e in events] == [target_row["feature_id"]] + ([used_row["feature_id"]] if free else [])
    assert target.temporary_hp == (7 if free else 3)
    assert not target.reaction_available


@pytest.mark.parametrize("blocked", ["reaction", "range", "cost", "inactive", "ally"])
def test_targeted_technique_used_retains_eligibility_limits(blocked):
    row = _row("technique_used", [{"type": "temp_hp", "flat": 7}], range_ft=60)
    engine = _engine([row])
    target, actor = engine.state.actors[REACTOR], engine.state.actors[AN]
    if blocked == "reaction":
        target.reaction_available = False
    elif blocked == "range":
        row["range_ft"] = 5
    elif blocked == "cost":
        row["costs"] = [{"resource_id": "resource:core.qi", "amount": 999}]
    elif blocked == "inactive":
        target.active = False
    else:
        actor.team_id = target.team_id
    typed_reactions.on_technique_start(engine, actor, [target], {"numbers": {}})
    assert target.temporary_hp == 0
    assert not any(e.event_type == "REACTION_RESOLVED" for e in engine.events)
