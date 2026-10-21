"""A real acquired Shield keeps its after-roll choice even on a natural miss."""
import pytest

from combat import ext
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish, force_ai_attack


def install(monkeypatch, point, callback):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, point, [callback])


@pytest.mark.parametrize("payment", ["reaction", "focus"])
@pytest.mark.parametrize("automatic_attacker", [False, True])
def test_acquired_shield_can_answer_a_rolled_miss(
        tmp_path, monkeypatch, payment, automatic_attacker):
    # A natural 1 still triggers Active Defense: it is not a hit-only response.
    # This also makes the after-roll boundary independent of equipment AC.
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:shield_rolled_miss", "operation": "replace",
        "natural_result": 1})
    table, mid = acquired_combat(tmp_path, monkeypatch)
    def cold():
        from combat.gate5_service import CombatService
        from tests.h1_support import ROOT
        return CombatService(ROOT, tmp_path)
    advance(table, mid, B)
    engine = cold()._load_session(mid).engine
    before = engine.state.actors[A]
    hp, ac = before.current_hp, before.armor_class + engine._ac_modifier(before)
    if automatic_attacker:
        force_ai_attack(table, mid)

    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if "fact_admission.shield_readiness" in source:
            return ["ready"]
        if ("active_defense_payment" in source
                or source == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE"):
            return [payment]
        return None

    prompts = finish(table, mid, choose, auto=automatic_attacker)
    engine = cold()._load_session(mid).engine
    rolled = next(e for e in reversed(engine.events)
                  if e.event_type == "ATTACK_ROLLED" and e.actor_id == B)
    windows = [e for e in engine.events if e.event_type == "REACTION_WINDOW_OPENED"
               and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE"]
    assert rolled.payload["natural_result"] == 1
    assert len(windows) == 1, {"prompts": prompts, "riders": [
        e.payload for e in engine.events if e.event_type == "GM_RIDER"]}
    assert windows[0].sequence > rolled.sequence
    assert windows[0].payload["checkpoint"] == "ATTACK_ROLLED_BEFORE_DAMAGE"
    defender = engine.state.actors[A]
    assert defender.current_hp == hp
    assert defender.armor_class + engine._ac_modifier(defender) == ac
    assert defender.reaction_available == (payment != "reaction")
    assert defender.resources["resource:core.martial_focus"] == (payment != "focus")
    assert cold().verify(mid)["status"] == "PASS"
    assert cold().replay(mid)["status"] == "PASS"


@pytest.mark.parametrize('payment', ['reaction', 'focus', None])
@pytest.mark.parametrize('automatic_attacker', [False, True])
def test_acquired_shield_after_roll_choice_does_not_outlive_attack(
        tmp_path, monkeypatch, payment, automatic_attacker):
    table, mid = acquired_combat(tmp_path, monkeypatch)
    advance(table, mid, B)
    if automatic_attacker:
        force_ai_attack(table, mid)
    engine = table.combat._load_session(mid).engine
    before = engine.state.actors[A]
    baseline_ac = before.armor_class + engine._ac_modifier(before)
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if 'fact_admission.shield_readiness' in source:
            return ['ready']
        if 'active_defense_payment' in source or source == 'reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE':
            return [payment] if payment else None
        return None
    finish(table, mid, choose, auto=automatic_attacker)
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    cold = CombatService(ROOT, tmp_path)
    engine = cold._load_session(mid).engine
    windows = [e for e in engine.events if e.event_type == 'REACTION_WINDOW_OPENED'
               and e.source_definition_id == 'SHIELD_BASE_ACTIVE_DEFENSE']
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == B]
    assert attacks
    if payment:
        assert windows and windows[-1].sequence > attacks[-1].sequence
        assert windows[-1].payload['checkpoint'] == 'ATTACK_ROLLED_BEFORE_DAMAGE'
    defender = engine.state.actors[A]
    assert not any(m.source_definition_id == 'SHIELD_BASE_ACTIVE_DEFENSE' for m in defender.modifiers.values())
    assert defender.armor_class + engine._ac_modifier(defender) == baseline_ac
    assert defender.reaction_available == (payment != 'reaction')
    assert defender.resources['resource:core.martial_focus'] == (0 if payment == 'focus' else 1)
    assert cold.verify(mid)['status'] == 'PASS'
    assert cold.replay(mid)['status'] == 'PASS'
