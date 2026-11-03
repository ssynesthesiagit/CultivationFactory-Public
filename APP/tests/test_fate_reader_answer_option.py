"""Regression for actionable Read the Thread branch options."""
from types import SimpleNamespace

from combat.ext.fate_reader import READ, THREAD_ANSWER, branch_gate, thread_questions


def _actor(predictions):
    return SimpleNamespace(conditions={
        "answer": SimpleNamespace(condition_id=THREAD_ANSWER,
                                   data={"predictions": predictions}),
    })


def test_mark_branch_is_not_offered_without_a_prediction():
    actor = _actor("[]")
    action = SimpleNamespace(parameters={"fate_record_branch": True})
    engine = SimpleNamespace(state=SimpleNamespace(actors={}))
    assert branch_gate(engine, actor, None, action) is False


def test_mark_branch_remains_available_with_an_actionable_prediction():
    actor = _actor('[{"actor_id":"creature-1","description":"moves north"}]')
    action = SimpleNamespace(parameters={"fate_record_branch": True})
    target = SimpleNamespace(active=True)
    engine = SimpleNamespace(state=SimpleNamespace(actors={"creature-1": target}))
    assert branch_gate(engine, actor, None, action) is None
    target.active = False
    assert branch_gate(engine, actor, None, action) is False
    engine.state.actors.clear()
    assert branch_gate(engine, actor, None, action) is False


def test_thread_question_labels_follow_typed_options(monkeypatch):
    from combat import typed_numbers
    options = [{"id": "danger", "label": "A synthetic danger question"},
               {"id": "next_action", "label": "A synthetic action question"}]
    monkeypatch.setattr(typed_numbers, "authority_mechanics", lambda: {
        READ: {"effects": [{"type": "fate_read_thread", "options": options}]}})
    assert thread_questions() == {row["id"]: row["label"] for row in options}
