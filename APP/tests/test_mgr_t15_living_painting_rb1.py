"""Living Painting review round (F10R, RB1): the Serpent's swim wording in the public module header.

Source-only text checks; no fight, no model, no network, no authority JSON.
"""
import combat.ext.painting_forms as painting_forms


def test_module_header_states_the_swim_capability_not_unmodeled():
    doc = painting_forms.__doc__
    assert "Not modeled here" not in doc
    assert "Swim Speed (40 feet)" in doc
    assert "authored on the battlefield map" in doc
    assert "combat/swimming.py" in doc
