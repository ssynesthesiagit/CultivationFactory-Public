"""Real-table damage controls and structured authority checks for Ward review F8."""
import json

import pytest

from combat import typed_reactions
from combat.factory_compiler import TYPED_AUTHORITY
from combat.gate2_rolls import DeterministicRollAuthority
from tests import test_disease_quarantine_ward as ward


def test_ward_has_no_unimplemented_combat_rider():
    record = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"][ward.WARD]
    # The two narrative clauses remain; all combat clauses belong to the typed effect,
    # not a third GM fallback. Do not pin player prose (public CI translates it).
    assert len(record["riders"]) == 2
    assert record["modifier"]["extra_cp"] == 2
    assert [r["type"] for r in record["modifier"]["effects"]].count("disease_quarantine_ward") == 1


@pytest.mark.parametrize("protected,psychic_resistance,expected", [
    (False, True, 12), (True, True, 6), (True, False, 12),
])
def test_real_sow_damage_matches_full_defense_query(tmp_path, monkeypatch, protected, psychic_resistance, expected):
    """Same real Sow: Ward halves eligible damage, but cannot resist legal Psychic damage."""
    original_bundle = ward._bundle

    def bundle(actor_id, *args, **kwargs):
        result = original_bundle(actor_id, *args, **kwargs)
        if actor_id == ward.SELECTED and psychic_resistance:
            result.setdefault("typed_passives", []).append({
                "feature_id": "test:psychic_resistance", "block": "resistance",
                "kind": "resistance", "damage_types": ["PSYCHIC"],
            })
        return result

    monkeypatch.setattr(ward, "_bundle", bundle)
    raw = DeterministicRollAuthority.raw_d20
    roll = DeterministicRollAuthority.roll

    def hit(self, **kwargs):
        answer = raw(self, **kwargs)
        if kwargs["reason"].startswith("ATTACK:"):
            return answer.model_copy(update={"natural_result": 10, "dice": (10,), "discarded": (),
                                             "total": 10 + kwargs["modifier"]})
        return answer

    def damage(self, dice, **kwargs):
        answer = roll(self, dice, **kwargs)
        if kwargs["reason"].startswith("DAMAGE:"):
            return answer.model_copy(update={"total": 12})
        return answer

    monkeypatch.setattr(DeterministicRollAuthority, "raw_d20", hit)
    monkeypatch.setattr(DeterministicRollAuthority, "roll", damage)
    combat, table, mid = ward._fight(tmp_path)
    if protected:
        ward._raise_ward(combat, table, mid)
    engine = ward._fresh(combat, mid).engine
    target = engine.state.actors[ward.SELECTED]
    source = next(a for a in engine.state.actors[ward.OWNER].action_ids if a.endswith(ward.SOW))
    for kind in ("NECROTIC", "POISON", "PSYCHIC"):
        factor = typed_reactions.damage_factor(engine, target, kind, source, ward.OWNER)
        assert factor == (0.5 if (protected and kind != "PSYCHIC") or
                         (psychic_resistance and kind == "PSYCHIC") else 1.0)
        assert typed_reactions.defend(engine, target, 12, kind, source, ward.OWNER) == int(12 * factor)
    hp = target.current_hp
    ward._sow(combat, table, mid, ward.SELECTED)
    loaded = ward._fresh(combat, mid).engine
    assert hp - loaded.state.actors[ward.SELECTED].current_hp == expected
    assert combat._load_session(mid).verify()["status"] == "PASS"
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"
