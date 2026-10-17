"""Regression for actionable Read the Thread branch options."""
from types import SimpleNamespace

from combat.ext.fate_reader import THREAD_ANSWER, branch_gate, thread_answered


def _actor(predictions):
    return SimpleNamespace(conditions={
        "answer": SimpleNamespace(condition_id=THREAD_ANSWER,
                                   data={"predictions": predictions}),
    })


def test_mark_branch_is_not_offered_without_a_prediction():
    actor = _actor("[]")
    action = SimpleNamespace(parameters={"fate_record_branch": True})

    assert not thread_answered(actor)
    assert branch_gate(None, actor, None, action) is False


def test_mark_branch_remains_available_with_an_actionable_prediction():
    actor = _actor('[{"actor_id":"creature-1","description":"moves north"}]')
    action = SimpleNamespace(parameters={"fate_record_branch": True})

    assert thread_answered(actor)
    assert branch_gate(None, actor, None, action) is None
