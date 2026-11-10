"""Shared-board stone defaults; actual pixel checks are opt-in for the lead."""
import re
import subprocess

from tests.test_builtin_arenas import ROOT


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


# The board module and the tabletop stylesheet are served to the combat table and the map editor alike, so when either
# changes both pages have to be cache bumped to the same generation, or one of them goes on drawing the old board. Every
# changed shared asset gets the same tag, and a page's own script tag may keep a descriptive prefix (r24-lock20) as long
# as it ends at the same generation. Bump ASSET_BUMP, and the pins in both pages and both scripts, in the commit that
# changes the assets.
ASSET_BUMP = "rel6-2"


def test_board_assets_are_cache_bumped_for_table_and_editor():
    static = ROOT / "static/tabletop"
    for page, script in [("tabletop.html", "tabletop.js"), ("mapeditor.html", "mapeditor.js")]:
        html = (static / page).read_text()
        assert f"tabletop.css?v={ASSET_BUMP}" in html, f"{page} must reload the changed tabletop.css"
        tag = re.search(rf"{re.escape(script)}\?v=([\w.-]+)", html)
        assert tag, f"{page} must load {script} with a version"
        assert tag.group(1).endswith(ASSET_BUMP), (
            f"{page} must load {script} at the {ASSET_BUMP} generation, not {tag.group(1)}")
        assert f'"./board.js?v={ASSET_BUMP}"' in (static / script).read_text(), (
            f"{script} must import the changed board module")
    assert f'"./mapeditor-zones.js?v={ASSET_BUMP}"' in (static / "mapeditor.js").read_text()
