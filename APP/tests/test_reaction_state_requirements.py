"""Relevant-only checks of the data-driven reaction state gate, without ability IDs."""
from types import SimpleNamespace

import pytest

from combat.ext.activation_requirements import (
    compile_state_requirement, generic_row_below_printed_gate,
)


@pytest.mark.parametrize("condition,falling,allowed", [
    (None, False, False),
    ("condition:typed.prone", False, True),
    ("condition:core.prone", False, True),
    ("condition:typed.restrained", False, False),
    (None, True, True),
])
def test_reaction_state_alternatives_use_conditions_or_native_falling(monkeypatch, condition, falling, allowed):
    from combat import falling as native_falling

    actor = SimpleNamespace(conditions={} if condition is None else {
        "instance": SimpleNamespace(condition_id=condition),
    })
    monkeypatch.setattr(native_falling, "required", lambda engine, subject: falling)
    row = {"feature_id": "synthetic", "numbers": {"cl": 1}}
    states = ["prone", "falling"]
    compiled = compile_state_requirement(row, {"mechanic": {
        "activation": {"requires_any_state": states},
    }})
    assert row == {"feature_id": "synthetic", "numbers": {"cl": 1}}
    assert compiled["requires_any_state"] == states
    assert compiled["requires_any_state"] is not states
    assert (generic_row_below_printed_gate(None, actor, compiled) is not False) == allowed
    assert compile_state_requirement(row, {"mechanic": {}}) is None
    assert generic_row_below_printed_gate(None, actor, row) is None
