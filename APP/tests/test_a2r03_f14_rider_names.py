"""Refuse Heaven-Lock and Pressure Becomes Method see Prone in both of the
engine's Prone ids (``condition:typed.prone`` and ``condition:core.prone``)."""
from combat.ext import foundation_sacred_body as body
from combat.gate5_service import CombatService
from tests import test_a2r11_foundations as f


def test_core_prone_from_the_same_source_is_a_minor_rider(tmp_path, monkeypatch):
    _, _, mid = f._service_fight(tmp_path, monkeypatch, f._sacred(), f.SACRED_BARE)
    engine = f._engine(CombatService(f.ROOT, tmp_path), mid)
    fighter = engine.state.actors[f.FIGHTER]
    foe = engine.state.actors[f.SERVICE_FOE]
    engine._apply_condition(fighter, "condition:core.prone", "test:f14_dirty_trick", foe.entity_id,
                            expires_on="UNTIL_REMOVED")
    riders = body._minor_riders(engine, fighter, foe.entity_id)
    assert [body._condition_name(r) for r in riders] == ["prone"]
    assert body._minor_riders(engine, fighter, "someone-else") == []
