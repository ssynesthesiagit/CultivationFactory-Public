"""MAINREDGT5: a non-charm ``bar`` value on a condition must not break charm_rules.

protection's Ward ``ward_apron`` condition keeps ``data["bar"]`` as a plain string ("keep_out" / "no_closer").
charm_rules.bars() used to yield any truthy value, so gate() called ``.get`` on a str and raised
AttributeError at every candidate_allowed check (the hook was skipped, silently dropping charm restrictions).
These tests use fake actors and conditions, so they fail on the old bars() and pass on the fixed one.
"""
from __future__ import annotations

from types import SimpleNamespace

from combat.ext import charm_rules


def _actor(**data_by_id):
    conditions = {cid: SimpleNamespace(data=data, source_actor_id="src", condition_id="x")
                  for cid, data in data_by_id.items()}
    return SimpleNamespace(conditions=conditions)


def test_string_bar_is_not_a_charm_bar():
    actor = _actor(ward={"bar": "keep_out", "feet": 10, "anchor": "a"}, none={"bar": None})
    assert list(charm_rules.bars(actor)) == []


def test_candidate_gate_ignores_protection_string_bar():
    actor = _actor(ward={"bar": "no_closer", "ward": "z"})
    candidate = SimpleNamespace(kind="x", target_ids=())
    action = SimpleNamespace(economy=None)
    assert charm_rules.gate(None, actor, candidate, action) is None


def test_choice_owner_ignores_protection_string_bar():
    condition = SimpleNamespace(data={"bar": "keep_out"})
    assert charm_rules.bar_choice_owner(None, None, condition) is None


def test_dict_bar_is_still_yielded():
    held = SimpleNamespace(data={"bar": {"one_activity": True}}, source_actor_id="src", condition_id="x")
    actor = SimpleNamespace(conditions={"c": held})
    assert [(i, b) for i, _, b in charm_rules.bars(actor)] == [("c", {"one_activity": True})]
