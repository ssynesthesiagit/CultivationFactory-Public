"""The readiness question names the attacker, the attack and the protected creature (checklist 9/13)."""
from combat.history_text import history_name
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish


def test_readiness_prompt_names_attacker_attack_and_protected_creature(tmp_path, monkeypatch):
    from combat import senses
    monkeypatch.setattr(senses, "perceives", lambda *a, **k: False)  # unaware of the attacker: the human must declare
    monkeypatch.setattr(senses, "pinpoints", lambda *a, **k: False)
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
