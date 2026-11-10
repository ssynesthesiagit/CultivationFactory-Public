"""VARIANTS26 fix: the pre-fight "Cast before the fight" list groups structured variant families.

The owner's screenshot showed four flat rows ("Standard", "Persistent", ...) with no "Meld: Darkvision" heading.
The production loop lives in tabletop.js loadPrefight(); this checks that loop itself, since no browser runs here.
Public-safe: reads only the shipped static file.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _load_prefight_body() -> str:
    source = (APP / "static" / "tabletop" / "tabletop.js").read_text(encoding="utf-8")
    start = source.index("async function loadPrefight(")
    end = source.index("\nasync function ", start + 1)
    return source[start:end]


def test_prefight_options_use_the_shared_variant_family_renderer():
    body = _load_prefight_body()
    assert "renderVariantGroups(document, data.options" in body
    # Each option row is still built by the pre-fight row helper, but only inside the per-row renderer.
    assert body.count("createPrefightRow(") == 1
    assert "prefightRow = view =>" in body
    assert "byId[view.action_id]" in body


def test_prefight_options_are_grouped_while_setup_controls_remain():
    body = _load_prefight_body()
    options, setup = body.split("for (const declaration of data.setup_choices || [])", 1)
    assert "for (const option of data.options)" not in options
    assert "box.appendChild(row)" not in options
    # Setup declarations are valid controls, separate from the buff-family renderer.
    assert "box.appendChild(row)" in setup
    assert "const amount = document.createElement(\"select\")" in setup


def test_prefight_checkbox_still_drives_the_pick_list():
    body = _load_prefight_body()
    assert "entry.prefight.add(option.action_id)" in body
    assert "entry.prefight.delete(option.action_id)" in body
    assert "entry.prefight.has(option.action_id)" in body
