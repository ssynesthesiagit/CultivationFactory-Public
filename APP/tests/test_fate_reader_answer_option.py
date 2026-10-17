"""Regression for Read the Thread's post-answer option gate."""
from types import SimpleNamespace

from combat.ext.fate_reader import THREAD_ANSWER, branch_gate


def test_mark_branch_remains_available_after_answer_without_operational_prediction():
    actor = SimpleNamespace(conditions={
        "answer": SimpleNamespace(condition_id=THREAD_ANSWER, data={"predictions": "[]"}),
    })
    action = SimpleNamespace(parameters={"fate_record_branch": True})

    assert branch_gate(None, actor, None, action) is None
