"""Hover sentence boundaries at the real table projection."""
from combat.condition_text import all_conditions
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
    assert row["rule_text"] == expected
    # The clauses are not repeated: one mechanics block, then the reading as its own sentences.
    assert row["rule_text"].count(dodge["mechanics"][0]) == 1
    assert row["rule_text"].count(dodge["reading"]) == 1
    # The hover detail breaks the sentence between the last clause and the reading.
    assert f"{dodge['mechanics'][-1]}. {dodge['reading'].split()[0]}" in row["detail"]
