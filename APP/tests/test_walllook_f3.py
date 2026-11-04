"""Offline regressions and negative controls for the WALLLOOKF2 review findings."""

from pathlib import Path
import re
import subprocess

import pytest

import test_region_wall_rendering_node as wall_checks


APP = Path(__file__).resolve().parents[1]
STATIC = APP / "static" / "tabletop"


def _absolute_imports(source):
    """Scratch mutants import real dependencies; no duplicate app checkout."""
    def absolute(match):
        quote, relative = match.groups()
        name, separator, query = relative.partition("?")
        return quote + (STATIC / name).resolve().as_uri() + separator + query + quote
    return re.sub(r"(['\"])(\.{1,2}/[^'\"]+)\1", absolute, source)


def _memory_checks(path):
    return subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=tap",
         "--test-name-pattern=WALLLOOKF3:", str(path)],
        cwd=APP, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=120, check=False,
    )


def test_memory_regression_rejects_unfiltered_scenery(tmp_path):
    board = (STATIC / "board.js").read_text()
    selected = "walls: sceneryWalls.flatMap(w => wallPieces(w, map.openings))"
    assert board.count(selected) == 1
    board = board.replace(selected, "walls: (map.walls || []).flatMap(w => wallPieces(w, map.openings))")
    mutant = tmp_path / "unfiltered-board.mjs"
    mutant.write_text(_absolute_imports(board))
    check = _absolute_imports((STATIC / "fog_memory_board.test.mjs").read_text())
    check = check.replace((STATIC / "board.js").as_uri(), mutant.as_uri())
    harness = tmp_path / "cliff-memory.test.mjs"
    harness.write_text(check)
    result = _memory_checks(harness)
    assert result.returncode != 0, "Unfiltered scenery unexpectedly passed"
    assert "superseded vector wall must not enter sight-time scenery" in result.stdout, result.stdout + result.stderr


def _assert_region_cache_inputs(source):
    key = re.search(r"const sceneryKey = JSON.stringify\(([^;]+)\);", source)
    assert key, "scenery cache key must be explicit"
    assert "map.terrainRegions" in key[1], "region data must invalidate the scenery cache"


def test_region_cache_includes_region_data():
    source = (STATIC / "board.js").read_text()
    _assert_region_cache_inputs(source)
    # Eligibility transitions are exercised on the real board above; this source
    # guard also protects region-only edits that leave the selected walls equal.
    with pytest.raises(AssertionError, match="region data must invalidate"):
        _assert_region_cache_inputs(source.replace(", map.terrainRegions]);", "]);"))


def test_entrypoint_cache_contract_rejects_reviewed_mismatch(tmp_path, monkeypatch):
    html = (STATIC / "tabletop.html").read_text()
    script = (STATIC / "tabletop.js").read_text()
    # Use the existing contract against real resources and its reviewed failure.
    wall_checks.test_tabletop_entrypoint_and_board_cache_versions_match()
    version = re.search(r"tabletop\.js\?v=([^\"&]+)", html)[1]
    target = tmp_path / "static" / "tabletop"
    target.mkdir(parents=True)
    (target / "tabletop.html").write_text(html.replace(version, "walllookf1-1"))
    (target / "tabletop.js").write_text(script)
    monkeypatch.setattr(wall_checks, "APP", tmp_path)
    with pytest.raises(AssertionError, match="refresh together"):
        wall_checks.test_tabletop_entrypoint_and_board_cache_versions_match()


def _assert_selection_coverage_is_explicit(source):
    names = re.findall(r"test\('([^']+)'", source)
    assert any("synthetic region footprints" in name for name in names), \
        "map inventory must disclose its synthetic region footprints"
    assert "all built-in maps with natural finite wall regions use the same renderer" not in names


def test_builtin_inventory_discloses_synthetic_coverage():
    source = (STATIC / "region-wall-art.test.mjs").read_text()
    _assert_selection_coverage_is_explicit(source)
    misleading = source.replace(
        "authored built-in wall styles select natural cliff rows using synthetic region footprints",
        "all built-in maps with natural finite wall regions use the same renderer",
    )
    with pytest.raises(AssertionError, match="must disclose"):
        _assert_selection_coverage_is_explicit(misleading)
