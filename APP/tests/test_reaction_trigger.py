"""Consent context cannot escape its checkpoint or exception lifetime."""
from types import SimpleNamespace

import pytest

from combat.reaction_trigger import contextual_request, trigger_scope, current_trigger


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


def test_movement_source_receipt_is_nested_copied_and_default_inert():
    engine = SimpleNamespace()
    assert current_trigger(engine) is None
    with trigger_scope(engine, 'FORCED_MOVEMENT', actor_id='source', target_id='subject',
                       source_id='actual effect', source_cl=20, ignores_bodily_anchoring=True):
        copy = current_trigger(engine)
        copy['source_cl'] = 1
        assert current_trigger(engine)['source_cl'] == 20
        with trigger_scope(engine, 'FORCED_MOVEMENT', actor_id='other', source_cl=3):
            assert current_trigger(engine)['source_cl'] == 3
        assert current_trigger(engine)['ignores_bodily_anchoring'] is True
    assert current_trigger(engine) is None
