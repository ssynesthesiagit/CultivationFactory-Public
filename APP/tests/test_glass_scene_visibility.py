from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TABLE = (ROOT / "static/tabletop/tabletop.js").read_text()
STYLE = (ROOT / "static/tabletop/tabletop.css").read_text()
HTML = (ROOT / "static/tabletop/tabletop.html").read_text()
SCENE = (ROOT / "static/tabletop/glass-scene.js").read_text()


def test_glass_scene_control_is_hidden_for_non_gm_views_and_shown_only_for_gm():
    # The toolbar's .tt-tool display rule must not override the HTML hidden state.
    assert re.search(r"\.tt-tool\[hidden\]\s*\{\s*display:\s*none\s*!important;", STYLE)
    assert re.search(r'<button id="ttGlassScene"[^>]*\shidden(?:\s|>)', HTML)

    # renderViewerIdentity runs when the initial viewer is resolved and on changes;
    # keep its role-derived state on the actual button, including disabled GM/no-match.
    assert "setGlassSceneVisibility(glassScene, view.status, Boolean(app.matchId))" in TABLE
    assert re.search(r"function renderViewerIdentity\(view = currentViewer\(\)\)", TABLE)
    helper = re.search(
        r"export function setGlassSceneVisibility\(button, viewStatus, hasMatch\) \{([^}]*)\}",
        SCENE,
    )
    assert helper, "visibility helper must be wired and available for focused regression"
    body = helper.group(1)
    assert 'const isGM = viewStatus === "gm"' in body
    assert "button.hidden = !isGM" in body
    assert "button.disabled = !isGM || !hasMatch" in body

    # Equality with "gm" means player, observer, stale and pending identities all hide it.
    assert body.count('viewStatus === "gm"') == 1
