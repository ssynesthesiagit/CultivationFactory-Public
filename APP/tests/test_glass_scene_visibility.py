"""Refraction scene button (#ttGlassScene) visibility.

The GM-only button must be absent for player, observer and stale views and shown only for the GM, from the
first render. The DOM behaviour is an executable node test (tests/glass_scene_visibility.test.mjs) that runs
the production render path on the real markup. This file keeps the two facts a DOM model cannot evaluate:
the CSS rule that stops the .tt-tool display from overriding the hidden attribute, and the default hidden markup.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "static/tabletop/tabletop.css").read_text()
HTML = (ROOT / "static/tabletop/tabletop.html").read_text()


def test_refraction_scene_button_is_hidden_by_css_and_markup_by_default():
    # The toolbar's .tt-tool display rule must not override the HTML hidden state.
    assert re.search(r"\.tt-tool\[hidden\]\s*\{\s*display:\s*none\s*!important;", STYLE)
    assert re.search(r'<button id="ttGlassScene"[^>]*\shidden(?:\s|>)', HTML)


def test_refraction_scene_button_visibility_runs_in_the_dom():
    result = subprocess.run(
        ["node", "--test", "tests/glass_scene_visibility.test.mjs"],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    output = result.stdout + result.stderr
    errors = [line.strip() for line in output.splitlines() if "AssertionError" in line or "Error:" in line]
    assert result.returncode == 0, " | ".join(errors) + "\n" + output
