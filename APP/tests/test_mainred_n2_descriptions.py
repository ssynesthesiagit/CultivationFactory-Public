"""Field Repair buttons retain their source description, even on public copies."""
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, _authority_index
from tests.test_auto17_blacksmith import _sheet, FIELD_REPAIR


def test_field_repair_buttons_have_source_rules():
    smith = compile_character(_sheet([FIELD_REPAIR]), actor_id="actor:smith")
    buttons = auto_buttons(smith, {"cultivation_level": 10})
    repair = [b for b in buttons if b["label"].startswith("Confirm damaged equipment: Field Repair")]
    assert len(repair) == 2
    from combat.display_text import printed_headers
    expected = printed_headers(_authority_index()[FIELD_REPAIR]["description"])
    assert expected
    assert all(b["description"] == expected for b in repair)
