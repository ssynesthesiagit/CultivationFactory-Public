"""Regression coverage for Vanishing Technique's sense-limited OA exception.

The fight is imported, activated and reloaded through the native table path;
sense rows model the observers' rules-backed capabilities.
"""
from types import SimpleNamespace

import pytest

from combat import senses
from combat.ext.tabik_ninpo import VANISHING, vanishing_opportunity
from tests.test_mgr_t15_vanishing_native import setup, activate, reload, OWNER, FOE


@pytest.mark.parametrize(
    "sense,expected",
    [
        ("truesight", None),
        ("blindsight", None),
        ("tremorsense", "DISADVANTAGE"),
        ("qi_sensing", "DISADVANTAGE"),
    ],
)
def test_opportunity_attack_only_senses_that_see_invisible_cancel_disadvantage(tmp_path, sense, expected):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    observer = engine.state.actors[FOE]
    target = engine.state.actors[OWNER]
    bundle = next(row for row in engine.typed_bundle_documents if row.get("actor_id") == FOE)
    bundle.setdefault("senses", {}).setdefault("rows", []).append(
        {"feature_id": "test:rules-backed-sense", "sense": sense, "range_ft": 30, "when": "always"}
    )
    engine._typed_oa_attacker = FOE

    assert vanishing_opportunity(SimpleNamespace(engine=engine, actor=observer), target) == expected

    # The exception is scoped to this attack; Vanishing remains active and the
    # native turn-end restore still grants Invisible without another Hide.
    assert any(c.condition_id == "condition:typed.vanishing_state" for c in target.conditions.values())
    assert any(c.condition_id == "condition:typed.invisible" for c in target.conditions.values())
    from tests.worker2_support import settle
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    restored = reload(tmp_path, mid).state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.invisible" for c in restored.conditions.values())


def test_tracking_mark_overcomes_only_invisible_attack_benefit(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    observer = engine.state.actors[FOE]
    target = engine.state.actors[OWNER]
    # The source-owned Smoke Mark is an observer-specific exception. It masks
    # only the target's Invisible condition for this marked attacker.
    engine._apply_condition(
        observer, "condition:typed.hidden_strike_smoke_mark", "test:smoke-mark", OWNER,
        expires_on="UNTIL_REMOVED", data={"owner_id": FOE},
    )
    masked = senses.masked_conditions(engine, observer, target)
    invisible_ids = {iid for iid, state in target.conditions.items()
                     if state.condition_id == "condition:typed.invisible"}
    assert invisible_ids
    assert invisible_ids <= masked.get(OWNER, set())
    assert any(c.condition_id == "condition:typed.vanishing_state" for c in target.conditions.values())
    from tests.worker2_support import settle
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    restored = reload(tmp_path, mid).state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.invisible" for c in restored.conditions.values())
