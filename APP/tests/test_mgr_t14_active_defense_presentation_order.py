"""Newest Shield presentation declaration wins by committed sequence, not by condition order.

Condition keys sort unpadded event numbers ("...:98" after "...:102"), so the order combat_records() returns is not
chronology. The stub returns the two declarations in both orders across the 99/100 digit boundary; the latest
(sequence 102, can present) must win in each case, so Active Defense is not refused.
"""
import pytest

from combat import fact_consent_admission, senses
from combat.ext import active_defense_timing as timing
from tests.active_defense_table_support import A, B, acquired_combat


def _rec(seq, value):
    return {"sequence": seq, "value": value, "kind": "shield_presentation"}


@pytest.mark.parametrize("order", ["old_last", "new_last"])
def test_latest_presentation_declaration_wins_regardless_of_condition_order(tmp_path, monkeypatch, order):
    table, mid = acquired_combat(tmp_path, monkeypatch)
    engine = table.combat._load_session(mid).engine
    defender, attacker = engine.state.actors[A], engine.state.actors[B]
    old, new = _rec(98, "cannot_present"), _rec(102, "can_present")
    records = [new, old] if order == "old_last" else [old, new]
    monkeypatch.setattr(fact_consent_admission, "combat_records", lambda *a, **k: list(records))
    monkeypatch.setattr(senses, "perceives", lambda *a, **k: True)  # awareness is not the question here
    row = {"feature_id": "SHIELD_BASE_ACTIVE_DEFENSE", "after_attack_roll": 1}
    assert timing.shield_facts(engine, row, defender, attacker, None, {}) is not False
