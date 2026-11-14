"""The same roll selector contract is enforced at every authority boundary."""
import json

import pytest

from combat.roll_mode_semantics import require_roll_target
from factory_authoring.roll_targets import ROLL_TARGET_TYPES, seal_roll_targets
from tools import typed_mechanics_helpers as helpers


BAD = [
    pytest.param({"kind": "nonsense"}, "kind", id="kind"),
    pytest.param({"kind": "check", "checks": "saves"}, "checks", id="checks-string"),
    pytest.param({"kind": "save", "next": "yes"}, "next", id="next-string"),
    pytest.param({"kind": "attack", "preview": {"kind": "attack"}}, "preview.group", id="preview-no-group"),
    pytest.param({"kind": "check"}, "checks", id="check-no-checks"),
    pytest.param({"kind": "save", "inside": {"saves": "DEX"}}, "inside.saves", id="inside-string"),
    pytest.param({"kind": "save", "against": [3]}, "against", id="list-item"),
    pytest.param([], "roll_target", id="not-object"),
]


@pytest.mark.parametrize("selector,field", BAD)
@pytest.mark.parametrize("boundary", ["build", "load", "run"])
def test_malformed_selector_rejected_at_every_boundary(tmp_path, monkeypatch, selector, field, boundary):
    effect = {"type": "advantage", "roll_target": selector}
    with pytest.raises(ValueError) as error:
        if boundary == "build":
            seal_roll_targets({"test:source": {"effects": [effect]}})
        elif boundary == "load":
            path = tmp_path / "reviewed_final.json"
            path.write_text(json.dumps({"mechanics": {"test:source": {"effects": [effect]}}}))
            monkeypatch.setattr(helpers, "REVIEWED_FINAL", path)
            helpers.load_finals()
        else:
            require_roll_target(effect, "test:source")
    assert "test:source" in str(error.value)
    assert field in str(error.value)


@pytest.mark.parametrize("selector", [
    None,
    {"kind": "attack"},
    {"kind": None, "inside": {"exclude": True}},
    {"kind": "save", "future": {"arbitrary": 1}},
])
def test_valid_selectors_pass_unchanged(tmp_path, monkeypatch, selector):
    effect = {"type": "advantage", "roll_target": selector}
    seal_roll_targets(effect, "test:source")
    assert require_roll_target(effect, "test:source") is selector
    path = tmp_path / "reviewed_final.json"
    path.write_text(json.dumps({"mechanics": {"test:source": {"effects": [effect]}}}))
    monkeypatch.setattr(helpers, "REVIEWED_FINAL", path)
    assert helpers.load_finals()["test:source"]["effects"][0]["roll_target"] == selector


def test_authority_selector_corpus():
    # Reviewed load checks every selector; the generated authority uses the same reader.
    helpers.load_finals()
    authority = json.loads((helpers.APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    count = 0

    def visit(value, source):
        nonlocal count
        if isinstance(value, list):
            for item in value:
                visit(item, source)
        elif isinstance(value, dict):
            if value.get("type") in ROLL_TARGET_TYPES:
                require_roll_target(value, source)
                count += 1
            for key, item in value.items():
                if key != "roll_target":
                    visit(item, source)

    for source, row in authority["mechanics"].items():
        visit(row, source)
    assert count > 0
