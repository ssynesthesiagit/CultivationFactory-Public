"""Field Repair buttons retain their source description, even on public copies."""
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from combat.decision_text import cost_as_charged
from combat.player_text import clean, explain_cp
from factory_authoring.record_display import record_display
from tests.test_auto17_blacksmith import _sheet, FIELD_REPAIR


def test_field_repair_buttons_have_source_rules():
    smith = compile_character(_sheet([FIELD_REPAIR]), actor_id="actor:smith")
    buttons = auto_buttons(smith, {"cultivation_level": 10})
    repair = [b for b in buttons if b["label"].startswith("Confirm damaged equipment: Field Repair")]
    assert len(repair) == 2
    card = record_display(FIELD_REPAIR)
    assert card and card["text"].strip()
    body = card["text"] + f"\n\nSource ability: {card['title']}."
    body = "\n".join(clean(explain_cp(line)) for line in body.splitlines())
    rows = {row["display_name"]: row for row in smith["action_catalog"]}
    for button in repair:
        expected = cost_as_charged(body, rows[button["label"]]["costs"])
        assert expected in button["description"]
