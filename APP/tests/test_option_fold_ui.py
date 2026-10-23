from pathlib import Path


def test_attack_modifier_details_fold_when_off_or_unavailable_and_keep_controls():
    source = (Path(__file__).parents[1] / "static/tabletop/sheet.js").read_text()
    assert 'const folded = connected && (!available || !enabled);' in source
    assert 'class: "arow-child arow-folded", "data-option-fold": b.id' in source
    assert 'available ? "Off · turn on" : "Not available: "' in source
    # The controls remain inside the disclosure, so folding never discards the user's selections.
    assert '...(row?.selectors || []).map(selector => h("label"' in source
    assert 'h("div", {class: "arow arow-variant arow-rider"' in source
