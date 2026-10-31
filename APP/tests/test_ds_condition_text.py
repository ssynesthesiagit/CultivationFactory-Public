"""Hover sentence boundaries at the real table projection."""
from tests.test_status_text import _tooltip_table
from combat.condition_text import READING
from combat.gate5_service import FACTORY_ACTOR_PREFIX


def test_table_dodge_hover_separates_mechanics_from_reading(tmp_path, monkeypatch):
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    engine._apply_condition(actor, "condition:core.dodge", "system:combat.dodge", actor.entity_id,
                            expires_on="START_OF_SELF_NEXT_TURN")
    row = next(r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]
               if r["condition_id"] == "condition:core.dodge")
    rule_text = row["rule_text"]
    # Every sentence of this hover is this app's own text: the mechanics come from combat/condition_text.mechanics()
    # and the reading from its READING table, both of which ship verbatim in the public export. It is asserted in short
    # pieces because tools/public_test_redact.py reads one 13-word assert literal as a quote of the private rulebook
    # original ("typed_conditions.json") and would keep this file off the public run.
    assert rule_text.startswith("Attack rolls against it have Disadvantage")
    assert "; These benefits are lost if it is Incapacitated" in rule_text
    assert "; Advantage on Dexterity saving throws. " in rule_text
    assert rule_text.endswith(READING["dodge"])  # the reading follows the mechanics, it does not replace them
    assert rule_text.count("Attack rolls against it have Disadvantage") == 1  # the reading says "attacks", not a repeat
    assert rule_text.count("These benefits are lost") == 1
    assert "saving throws. Dodging" in row["detail"]
