"""Miss riders wait for the final attack result, including later corrections."""
import pytest

from tests.test_critical_damage_reactions import (
    WEAPON_GUARD, ME, FOE, fight, crits, flippable_natural,
    to_turn, ask, attack_on, reload,
)
from tests.test_lock_choices import install


@pytest.mark.parametrize("replacement", ["none", "bonus", "outcome"])
def test_weapon_guard_step_waits_for_final_miss(tmp_path, monkeypatch, replacement):
    combat, table, mid = fight(tmp_path, mids=[WEAPON_GUARD])
    natural = flippable_natural(tmp_path, ranged=False)
    crits(monkeypatch, only=FOE, natural=natural)
    if replacement == "bonus":
        install(monkeypatch, "attack_miss_correction",
                lambda *args: {"source_id": "test:correction", "label": "Correction", "bonus": 10})
    elif replacement == "outcome":
        install(monkeypatch, "attack_miss_outcome",
                lambda *args: {"source_id": "test:replacement", "label": "Replacement", "force_hit": True})
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == WEAPON_GUARD
               and e.payload.get("hit_after_recheck") is False for e in engine.events)
    moved = any(e.event_type == "MOVEMENT_GRANTED" and e.actor_id == ME for e in engine.events)
    assert moved is (replacement == "none")
    assert bool([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]) is (replacement != "none")
