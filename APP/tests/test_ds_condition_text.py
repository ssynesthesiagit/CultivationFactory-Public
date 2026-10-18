"""Hover sentence boundaries at the real table projection."""
from tests.test_status_text import _tooltip_table
from combat.gate5_service import FACTORY_ACTOR_PREFIX


def test_table_dodge_hover_separates_mechanics_from_reading(tmp_path, monkeypatch):
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    engine._apply_condition(actor, "condition:core.dodge", "system:combat.dodge", actor.entity_id,
                            expires_on="START_OF_SELF_NEXT_TURN")
    row = next(r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]
               if r["condition_id"] == "condition:core.dodge")
    assert row["rule_text"] == ("Attack rolls against it have Disadvantage if it can see the attacker; "
        "These benefits are lost if it is Incapacitated or its Speed is 0; Advantage on Dexterity saving throws. "
        "Dodging until the start of its next turn: attacks against it have Disadvantage if it can see the attacker, "
        "and it has Advantage on Dexterity saving throws. Both benefits end if it can't take actions or its Speed becomes 0; "
        "recovering does not restore this Dodge. Dodge costs an Action and no resource points.")
    assert row["rule_text"].count("Attack rolls against it have Disadvantage") == 1
    assert row["rule_text"].count("These benefits are lost") == 1
    assert "saving throws. Dodging" in row["detail"]
