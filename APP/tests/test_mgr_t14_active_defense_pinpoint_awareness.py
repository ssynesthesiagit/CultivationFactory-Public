"""Awareness by pinpointing reaches Active Defense through the table (review finding 1).

The production Active Defense row keeps no blanket sight veto, so a defender that cannot perceive an invisible
attacker but pinpoints it (senses.pinpoints) is admitted by the awareness policy and the window opens after the roll.
Only the defender's perception and pinpointing are scripted; the row filters, admission and replay are production.
"""
from combat import senses
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish, force_ai_attack


def test_pinpointed_attacker_opens_active_defense_without_perception(tmp_path, monkeypatch):
    real_perceives, real_pinpoints = senses.perceives, senses.pinpoints

    def unseen(real):
        def check(engine, viewer, seen, **options):
            if viewer.entity_id == A and seen.entity_id == B:
                return real is real_pinpoints  # perceives: False; pinpoints: True
            return real(engine, viewer, seen, **options)
        return check

    monkeypatch.setattr(senses, "perceives", unseen(real_perceives))
    monkeypatch.setattr(senses, "pinpoints", unseen(real_pinpoints))
    table, mid = acquired_combat(tmp_path, monkeypatch)
    advance(table, mid, B)
    prompts = []

    def choose(prompt):
        prompts.append(prompt["context"]["reaction_source_id"])
        if "shield_readiness" in prompts[-1]:
            return ["ready"]
        if "active_defense_payment" in prompts[-1] or prompts[-1] == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE":
            return ["reaction"]
        return None

    finish(table, mid, choose)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    windows = [e for e in engine.events if e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE"]
    rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == B]
    assert windows and windows[0].sequence > rolled[-1].sequence
    assert any("active_defense" in str(source) for source in prompts)  # the defense was offered, not silently refused
