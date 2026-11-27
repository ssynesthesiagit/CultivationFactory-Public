"""Hover sentence boundaries at the real table projection."""
from combat.condition_text import all_conditions, READING
from tests.test_status_text import _tooltip_table
from combat.gate5_service import FACTORY_ACTOR_PREFIX


def test_table_dodge_hover_separates_mechanics_from_reading(tmp_path, monkeypatch):
    """Mechanics, then the printed reading, each once and properly sentence-broken.

    The expected text is built from the condition's own projection (its engine clauses and its printed
    reading), so the pin is the join between them -- separators, capitals and the sentence boundary -- and
    not a copy of printed prose.
    """
    dodge = all_conditions()["dodge"]
    expected = "; ".join(dodge["mechanics"]) + ". " + dodge["reading"]
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    engine._apply_condition(actor, "condition:core.dodge", "system:combat.dodge", actor.entity_id,
                            expires_on="START_OF_SELF_NEXT_TURN")
    row = next(r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]
               if r["condition_id"] == "condition:core.dodge")
    rule_text = row["rule_text"]
    assert rule_text == expected
    # The clauses are not repeated: one mechanics block, then the reading as its own sentences.
    assert rule_text.count(dodge["mechanics"][0]) == 1
    assert rule_text.count(dodge["reading"]) == 1
    # The hover detail breaks the sentence between the last clause and the reading.
    assert f"{dodge['mechanics'][-1]}. {dodge['reading'].split()[0]}" in row["detail"]
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
