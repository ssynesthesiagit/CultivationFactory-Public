"""Consent context cannot escape its checkpoint or exception lifetime."""
from types import SimpleNamespace

import pytest

from combat.reaction_trigger import contextual_request, trigger_scope


def test_trigger_scope_restores_nested_context_and_is_inert_outside_checkpoint():
    engine = SimpleNamespace()
    request = {"checkpoint": "TYPED:D20_REWRITE_ROLL@4", "reactor_id": "protector"}
    assert contextual_request(engine, request) is request
    with trigger_scope(engine, "D20_REWRITE_ROLL", actor_id="caster", target_id="ally",
                       source_id="hazard", roll_kind="save"):
        outer = contextual_request(engine, request)
        assert outer["attacking_actor_id"] == "caster"
        assert outer["protected_target_id"] == "ally"
        unrelated = {**request, "checkpoint": "TYPED:OTHER@4"}
        assert contextual_request(engine, unrelated) is unrelated
        with pytest.raises(RuntimeError):
            with trigger_scope(engine, "D20_REWRITE_ROLL", actor_id=None, target_id="other",
                               source_id="other-hazard", roll_kind="save"):
                assert contextual_request(engine, request)["protected_target_id"] == "other"
                raise RuntimeError("preview paused")
        assert contextual_request(engine, request) == outer
    assert not hasattr(engine, "_reaction_trigger")
    assert contextual_request(engine, request) is request
