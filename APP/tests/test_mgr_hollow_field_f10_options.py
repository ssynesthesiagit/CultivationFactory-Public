"""The public tooltip fixture must supply the compiler's printed shape heading too."""
import json

from combat import factory_compiler
from tests.option_tooltip_support import synthetic_option_rules
from tests.test_option_tooltips import (
    test_node_sheet_and_table_builders as check_node_builders,
    test_printed_options_reach_sheet_and_real_table_menu_after_reload as check_table,
)


def test_shape_darkness_survives_redacted_printed_input_on_sheet_table_and_node(tmp_path, monkeypatch):
    # Public exports can redact prose while retaining typed effects. The compiler
    # reads talent categories from the heading, separately from tooltip prose.
    rules = {**factory_compiler._rules_text(),
             "TAL_DARK_NUMBING_DARKNESS": "### Redacted talent\nRedacted description."}
    monkeypatch.setattr(factory_compiler, "_RULES_TEXT_CACHE", rules)
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority["mechanics"]["DARK_BASE_DARKNESS"]["description"] = ["Redacted description."]
    authority["mechanics"]["DARK_BASE_DARKNESS"]["riders"] = []
    redacted_path = tmp_path / "redacted-authority.json"
    redacted_path.write_text(json.dumps(authority))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", redacted_path)
    with synthetic_option_rules(tmp_path, monkeypatch):
        check_table(tmp_path, False)
        check_node_builders()
    assert factory_compiler._rules_text() == rules
    assert factory_compiler.TYPED_AUTHORITY == redacted_path
