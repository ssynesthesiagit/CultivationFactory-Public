"""The readiness question names the attacker, the attack and the protected creature (checklist 9/13).

Only the defender's awareness of the attacker is withheld, so the human must declare it. The attacker still sees the
defender, which keeps its dagger attack legal for the table helper.
"""
from combat import senses
from combat.history_text import history_name
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish


def test_readiness_prompt_names_attacker_attack_and_protected_creature(tmp_path, monkeypatch):
    real_perceives, real_pinpoints = senses.perceives, senses.pinpoints

    def unaware(real):
        def check(engine, viewer, seen, **options):
            if viewer.entity_id == A and seen.entity_id == B:
                return False  # the defender is unaware of the attacker: the human must declare
            return real(engine, viewer, seen, **options)
        return check

    monkeypatch.setattr(senses, "perceives", unaware(real_perceives))
    monkeypatch.setattr(senses, "pinpoints", unaware(real_pinpoints))
    table, mid = acquired_combat(tmp_path, monkeypatch)
    advance(table, mid, B)
    seen = []

    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if "shield_readiness" in source:
            seen.append(prompt)
            return ["ready"]
        if "active_defense_payment" in source or source == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE":
            return ["reaction"]
        return None

    finish(table, mid, choose)
    assert seen, "the readiness question was never asked"
    engine = table.combat._load_session(mid).engine
    attacker, defender = engine.state.actors[B], engine.state.actors[A]
    rolled = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == B)
    src = rolled.source_definition_id
    attack = history_name(src, {src: engine.action_catalog[src].display_name})
    text = str(seen[0]["context"].get("prompt", "")) + " " + str(seen[0]["context"].get("labels", ""))
    assert attacker.display_name in text, text
    assert defender.display_name in text, text
    assert attack in text, text
