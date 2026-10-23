"""A forced miss (before_attack answer) keeps its forced outcome, but the rolled attack still offers Active Defense.

Active Defense's printed trigger is an attack roll, not a successful hit, so the optional after-roll response (and its
Reaction or Focus cost, and any Deflect or Smashing Counter it enables) stays available after a forced miss. Declining
costs nothing. The forced outcome is produced by a stub around combat.attack_outcomes.forced_miss (the real seam).
"""
import pytest

from combat import attack_outcomes
from combat import ext
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish, force_ai_attack


@pytest.mark.parametrize("payment", ["reaction", "focus", None])
@pytest.mark.parametrize("automatic_attacker", [False, True])
def test_forced_miss_still_offers_active_defense(tmp_path, monkeypatch, payment, automatic_attacker):
    ext.effects()
    real = attack_outcomes.forced_miss

    def forced(engine, actor, target, source_id, attack_index, roll, replies):
        if actor.entity_id != B:
            return real(engine, actor, target, source_id, attack_index, roll, replies)
        engine._append_event("ATTACK_FORCED_MISS", "test:mgr_t14.forced_miss", actor_id=actor.entity_id,
            target_ids=(target.entity_id,), payload={"attack_source_id": source_id, "attack_index": attack_index,
            "roll_id": roll.roll_id, "natural_result": roll.natural_result, "log": "Forced miss."})
        return True

    monkeypatch.setattr(attack_outcomes, "forced_miss", forced)
    table, mid = acquired_combat(tmp_path, monkeypatch)
    advance(table, mid, B)
    if automatic_attacker:
        force_ai_attack(table, mid)
    engine = table.combat._load_session(mid).engine
    before = engine.state.actors[A]
    ac_before = before.armor_class + engine._ac_modifier(before)

    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if "shield_readiness" in source:
            return ["ready"]
        if "active_defense_payment" in source or source == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE":
            return [payment] if payment else []  # decline
        return None

    finish(table, mid, choose, auto=automatic_attacker)
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    cold = CombatService(ROOT, tmp_path)
    engine = cold._load_session(mid).engine
    forced = [e for e in engine.events if e.event_type == "ATTACK_FORCED_MISS"]
    rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == B]
    windows = [e for e in engine.events if e.event_type == "REACTION_WINDOW_OPENED"
               and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE"]
    assert forced and rolled
    # The optional after-roll defense is still offered on the forced miss, after the roll.
    defender = engine.state.actors[A]
    if payment:
        assert len(windows) == 1 and windows[0].sequence > rolled[-1].sequence
    else:
        assert not windows  # declining opens no window and costs nothing
    assert defender.armor_class + engine._ac_modifier(defender) == ac_before  # the bonus was attack-only
    assert defender.reaction_available == (payment != "reaction")
    assert defender.resources["resource:core.martial_focus"] == (0 if payment == "focus" else 1)
    assert cold.verify(mid)["status"] == "PASS"
