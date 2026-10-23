"""A forced miss (before_attack answer) opens no Active Defense window and costs no Reaction or Focus.

The after-roll window is only worth opening when the attack could still change outcome; a forced miss cannot.
Synthetic acquired Shield fixture (public characters only), table-level.
"""
import pytest

from combat import ext
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish, force_ai_attack


@pytest.mark.parametrize("automatic_attacker", [False, True])
def test_forced_miss_does_not_open_active_defense(tmp_path, monkeypatch, automatic_attacker):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "before_attack", [lambda *args: {
        "force_miss": True, "source_id": "test:mgr_t14.forced_miss", "label": "Test: the attack misses"}])
    table, mid = acquired_combat(tmp_path, monkeypatch)
    advance(table, mid, B)
    if automatic_attacker:
        force_ai_attack(table, mid)

    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if "fact_admission.shield_readiness" in source:
            return ["ready"]
        if "active_defense_payment" in source or source == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE":
            return ["reaction"]
        return None

    prompts = finish(table, mid, choose, auto=automatic_attacker)
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    cold = CombatService(ROOT, tmp_path)
    engine = cold._load_session(mid).engine
    assert any(e.event_type == "ATTACK_FORCED_MISS" for e in engine.events)
    windows = [e for e in engine.events if e.event_type == "REACTION_WINDOW_OPENED"
               and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE"]
    assert windows == []
    assert not any("SHIELD" in p["context"]["reaction_source_id"].upper()
                   or "active_defense" in p["context"]["reaction_source_id"] for p in prompts), prompts
    defender = engine.state.actors[A]
    assert defender.reaction_available is True
    assert defender.resources["resource:core.martial_focus"] == 1
    assert cold.verify(mid)["status"] == "PASS"
