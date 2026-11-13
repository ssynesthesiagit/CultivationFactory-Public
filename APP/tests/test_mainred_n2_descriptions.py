"""Field Repair buttons retain their source description, even on public copies."""
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from combat.player_text import explain_cp
from combat.status_text import printed_excerpt
from tests.test_auto17_blacksmith import _sheet, FIELD_REPAIR


def test_field_repair_buttons_have_source_rules():
    smith = compile_character(_sheet([FIELD_REPAIR]), actor_id="actor:smith")
    buttons = auto_buttons(smith, {"cultivation_level": 10})
    repair = [b for b in buttons if b["label"].startswith("Confirm damaged equipment: Field Repair")]
    assert len(repair) == 2
    expected = explain_cp(printed_excerpt(FIELD_REPAIR))
    assert expected
    assert all(b["description"] == expected for b in repair)
