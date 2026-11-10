"""Shared-board stone defaults; actual pixel checks are opt-in for the lead."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_natural_map_haze_is_opt_in_and_legacy_painted_smoke_keeps_its_appearance():
    subprocess.run(["node", "--input-type=module", "-e", """
      import assert from 'node:assert/strict';
      const {lightHazeStyle} = await import(process.argv[1]);
      const painted = {trigger_profile: {shape: 'painted'}};
      const optIn = {trigger_profile: {shape: 'painted', natural_haze: true}};
      const color = [183, 204, 208], haze = [160, 160, 168];
      const original = {tint: haze, fill: 0.16, drifts: [
        {tile:'haze', cells:4, dx:1, dy:0, duration:50, opacity:0.85}]};
      for (const material of ['smoke', 'fog']) {
        const look = {material, darkness:false};
        const mist = lightHazeStyle(optIn, look, color, haze);
        assert.equal(mist.fill, 0.36);
        assert.equal(mist.drifts.length, 2);
        assert(mist.tint.every((value, i) => value > color[i]));
        assert(mist.drifts.every(layer => layer.duration > 0 && layer.opacity > 0));
        // Existing saved fights have no natural_haze opt-in and retain the old wash/layer.
        assert.deepEqual(lightHazeStyle(painted, look, color, haze), original);
        assert.deepEqual(lightHazeStyle({trigger_profile:{shape:'sphere', natural_haze:true}}, look, color, haze), original);
        assert.deepEqual(lightHazeStyle(optIn, {...look, darkness:true}, color, haze),
          {...original, tint:[10,10,16]});
      }
      for (const material of ['bamboo', 'rubble', 'generic']) {
        assert.deepEqual(lightHazeStyle(painted, {material}, color, haze), original);
      }
    """, (ROOT / "static/tabletop/zonepaint.js").as_uri()], check=True, timeout=30)


def test_stone_pattern_has_theme_preserving_defaults_outside_app():
    css = (ROOT / "static/tabletop/tabletop.css").read_text()
    # SVG paint defaults to black when a var() has no value. Fallbacks must be
    # inside the existing declarations so themed maps still inherit their skin.
    for selector, prop, variable, fallback in [
        (".tt-stone-base", "fill", "--wall-fill", "#6d6a63"),
        (".tt-stone-joints", "stroke", "--wall-joint", "rgba(0,0,0,.35)"),
        (".tt-wall-solid.tt-wall-filled", "stroke", "--wall-edge", "#25221f"),
    ]:
        block = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", css)[1]
        assert f"{prop}: var({variable}, {fallback})" in block


# Source tokens are descriptive only: StaticBuild stamps the served pages and
# modules with one deploy version. Check the actual shared-asset contract, not
# a past release's spelling (the generic stamping unit test uses tiny fixtures).
def test_board_assets_are_cache_bumped_for_table_and_editor():
    from app.static_build import BUILD_HEADER, StaticBuild

    assets = StaticBuild(ROOT, nonce="arena-polish")
    stylesheet = assets.response_for("/static/tabletop/tabletop.css")
    assert stylesheet is not None
    assert stylesheet.headers[BUILD_HEADER] == assets.build
    assert stylesheet.headers["Cache-Control"] == "no-cache"
    for page, script in [("tabletop.html", "tabletop.js"), ("mapeditor.html", "mapeditor.js")]:
        response = assets.response_for(f"/static/tabletop/{page}")
        assert response is not None
        html = response.body.decode()
        assert response.headers[BUILD_HEADER] == assets.build
        assert response.headers["Cache-Control"] == "no-cache"
        for asset in ("tabletop.css", script):
            tag = re.search(rf'(?:href|src)="/static/tabletop/{re.escape(asset)}\?v=([\w.-]+)"', html)
            assert tag, f"{page} must load {asset} with a version"
            assert tag.group(1) == assets.build, f"{page} must load {asset} from this deploy"
        module = assets.response_for(f"/static/tabletop/{script}")
        assert module is not None
        assert f'"./board.js?v={assets.build}"' in module.body.decode(), (
            f"{script} must import the shared board from this deploy")
        if script == "mapeditor.js":
            assert f'"./mapeditor-zones.js?v={assets.build}"' in module.body.decode()
