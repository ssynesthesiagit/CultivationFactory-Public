"""Queue-compatible lean board checks. No browser or live model clients."""
from pathlib import Path
import subprocess
import json
from test_fogedge_frontier import _absolute_imports
from test_foggrey_browser import REPLACE_UNSEEN_JS


def test_browser_replacement_paints_opaque_floor_and_rejects_hidden_css():
    """Exercise the browser fixture's stimulus without launching Chromium."""
    harness = """
import assert from 'node:assert/strict';
const pixels = new Uint8Array(384 * 256);
const context = {
  fillStyle: '',
  fillRect(x, y, width, height) {
    assert.equal(this.fillStyle, '#ff0000');
    assert.deepEqual([x, y, width, height], [0, 0, 384, 256]);
    pixels.fill(1);
  },
};
const floor = {width:384, height:256, getContext(kind) {
  assert.equal(kind, '2d'); return context;
}};
const bg = {style:{}};
globalThis.document = {querySelector(selector) {
  if (selector === '.tt-bg-floor') return floor;
  if (selector === '.tt-bg') return bg;
  throw new Error(selector);
}};
eval('(' + STIMULUS + ')')();
assert.ok(pixels.every(pixel => pixel === 1), 'opaque live floor pixels must change');
"""
    def run(stimulus):
        source = harness.replace("STIMULUS", json.dumps(stimulus))
        return subprocess.run(["node", "--input-type=module", "-e", source],
                              capture_output=True, text=True, timeout=30)
    actual = run(REPLACE_UNSEEN_JS)
    assert actual.returncode == 0, actual.stdout + actual.stderr
    hidden_css = run("() => { document.querySelector('.tt-bg').style.background = 'red'; }")
    assert hidden_css.returncode != 0, "the old invisible replacement must fail the stimulus regression"
    assert "opaque live floor pixels must change" in hidden_css.stderr, hidden_css.stderr


def test_foggrey_scoped_board_modules():
    tabletop = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    for name in ("fog_memory_board.test.mjs", "board.test.mjs", "board-terrain.test.mjs", "board-frames.test.mjs"):
        result = subprocess.run(["node", "--test-reporter=tap", str(tabletop / name)],
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr


def test_foggrey_rejects_wash_below_saved_ground(tmp_path):
    tabletop = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    board = (tabletop / "board.js").read_text()
    marker = '  const rememberedSvg = svg("svg", {class: "tt-layer tt-remembered-layer", preserveAspectRatio: "none"}, board);'
    wash = '  const fog = el("canvas", "tt-fog", board);'
    assert board.count(marker) == board.count(wash) == 1
    board = board.replace(wash, "").replace(marker, wash + "\n" + marker)
    mutant = tmp_path / "board.mjs"
    mutant.write_text(_absolute_imports(board, tabletop))
    source = _absolute_imports((tabletop / "fog_memory_board.test.mjs").read_text(), tabletop)
    source = source.replace((tabletop / "board.js").as_uri(), mutant.as_uri())
    regression = tmp_path / "fog_memory_board.test.mjs"
    regression.write_text(source)
    result = subprocess.run(["node", "--test-reporter=tap", "--test-name-pattern=FOGGREY", str(regression)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode != 0, "wrong layer order unexpectedly passed"
    assert "one wash must paint after the composed saved ground" in result.stdout, result.stdout + result.stderr
