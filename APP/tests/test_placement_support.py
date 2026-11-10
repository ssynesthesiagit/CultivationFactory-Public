"""The strict setup helper must not conceal unrelated table prompts."""
import pytest

from tests.placement_support import PLACEMENT_SQUARE, act_with_square


STATE = {"menu": {"actor_id": "actor:owner", "decision_id": "decision:1", "state_version": 7},
         "last_sequence": 12}


def pending(source=PLACEMENT_SQUARE, reactor="actor:owner"):
    return {"status": "REACTION_REQUIRED", "reaction": {
        "context": {"reaction_source_id": source, "reactor_id": reactor,
                    "checkpoint": "placement:intent:gate5:1"},
        "choice": {"options": [{"id": "cell:1,2,0"}, {"id": "cell:3,4,2"}]},
    }}


class ScriptedTable:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def act(self, *request):
        self.calls.append(request)
        return next(self.responses)


@pytest.mark.parametrize("square,selected,final", [
    (None, "cell:1,2,0", {"status": "COMMITTED"}),
    ((3, 4, 2), "cell:3,4,2", pending("choice:pay")),
    ((1, 2, 0), "cell:1,2,0", pending()),
])
def test_act_with_square_answers_once_and_returns_the_next_response(square, selected, final):
    prompt = pending()
    table = ScriptedTable(prompt, final)
    assert act_with_square(table, "match:1", STATE, "candidate:1", square=square) is final
    request = ("match:1", "candidate:1", "decision:1", 7, 12)
    assert table.calls == [request, (*request, [{
        **prompt["reaction"]["context"], "selection": "USE", "option_ids": [selected],
    }])]


@pytest.mark.parametrize("response", [
    {"status": "COMMITTED"},
    pending(reactor="actor:other"),
    pending("reaction:opportunity_attack"),
    pending("choice:consent"),
    pending("choice:pay"),
])
def test_act_with_square_leaves_nonplacement_and_other_actors_prompts_visible(response):
    table = ScriptedTable(response)
    assert act_with_square(table, "match:1", STATE, "candidate:1") is response
    assert len(table.calls) == 1


def test_act_with_square_rejects_an_unoffered_square():
    table = ScriptedTable(pending())
    with pytest.raises(AssertionError):
        act_with_square(table, "match:1", STATE, "candidate:1", square=(9, 9, 0))
    assert len(table.calls) == 1
