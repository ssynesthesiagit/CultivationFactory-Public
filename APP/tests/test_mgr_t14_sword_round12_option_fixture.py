"""The shared public option fixture must feed the compiler's printed heading too.

Public exports redact printed prose while keeping typed effects. `test_option_tooltips`
synthesises stable reference prose so its real sheet, table and Node assertions do
not depend on the exported wording. Shape selectors are compiled from a separate
rules-text reader, so that reader needs the same synthetic category heading;
otherwise the public copy loses `Shape Darkness: Numbing Darkness` from the sheet
and the table menu. This pins the shared fixture, not production combat code.
"""
import json

from combat import factory_compiler
from tests.option_tooltip_support import synthetic_option_rules
from tests.test_option_tooltips import (
    test_node_sheet_and_table_builders as check_node_builders,
    test_printed_options_reach_sheet_and_real_table_menu_after_reload as check_table,
)


def test_shape_darkness_survives_redacted_printed_input_on_sheet_table_and_node(tmp_path, monkeypatch):
    # Simulate the public export: typed mechanics stay, printed prose is redacted.
    rules = {**factory_compiler._rules_text(),
             "TAL_DARK_NUMBING_DARKNESS": "### Redacted talent\nRedacted description."}
    monkeypatch.setattr(factory_compiler, "_RULES_TEXT_CACHE", rules)
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority["mechanics"]["DARK_BASE_DARKNESS"]["description"] = ["Redacted description."]
    authority["mechanics"]["DARK_BASE_DARKNESS"]["riders"] = []
    for option in authority["mechanics"]["TAL_VOID_NULLIFYING_STRIKE"]["modifier"]["options"]:
        for effect in option["effects"]:
            for failure in effect.get("on_fail", []):
                failure["evidence"] = "Redacted failed-save option."
    redacted_path = tmp_path / "redacted-authority.json"
    redacted_path.write_text(json.dumps(authority))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", redacted_path)
    with synthetic_option_rules(tmp_path, monkeypatch):
        check_table(tmp_path, False)
        check_node_builders()
    assert factory_compiler._rules_text() == rules
    assert factory_compiler.TYPED_AUTHORITY == redacted_path
