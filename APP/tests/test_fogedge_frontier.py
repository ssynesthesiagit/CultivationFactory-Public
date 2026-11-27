"""Queue-compatible entry point for deterministic fog pixels, including a negative control.

Runs Node's software DOM/raster tests only; never starts a browser or a model client.
"""
from pathlib import Path
import re
import subprocess


TABLETOP = Path(__file__).resolve().parents[1] / "static" / "tabletop"


def test_fogedge_board_and_memory_modules(capsys):
    files = ["fog_memory_board.test.mjs", "fog_polygon.test.mjs", "fog_memory.test.mjs", "board.test.mjs"]
    for name in files:
        result = subprocess.run(
            ["node", "--test-reporter=tap", str(TABLETOP / name)],
            capture_output=True, text=True, timeout=120,
        )
        with capsys.disabled():
            print(f"FOGEDGE1F {name} summary:\n" + "\n".join(result.stdout.splitlines()[-10:]), flush=True)
        assert result.returncode == 0, result.stdout + result.stderr


def _absolute_imports(source, directory):
    """Keep scratch copies bound to original dependencies, without copying the app."""
    def absolute(match):
        quote, relative = match.groups()
        name, separator, query = relative.partition("?")
        uri = (directory / name).resolve().as_uri()
        return quote + uri + (separator + query if separator else "") + quote
    return re.sub(r"(['\"])(\.{1,2}/[^'\"]+)\1", absolute, source)


def test_fogedge_frontier_regressions_reject_translucent_backing(tmp_path, capsys):
    # Restore only the reviewed root cause in a scratch module. The working board never changes.
    board = (TABLETOP / "board.js").read_text()
    marker = "    const url = `url(${inverse.toDataURL()})`;"
    assert board.count(marker) == 1
    board = board.replace(marker,
        '    if (fog.exploredMask) { context.globalCompositeOperation = "destination-in"; '
        'context.drawImage(fog.exploredMask, 0, 0); }\n' + marker)
    mutant = tmp_path / "board.mjs"
    mutant.write_text(_absolute_imports(board, TABLETOP))
    source = _absolute_imports((TABLETOP / "fog_memory_board.test.mjs").read_text(), TABLETOP)
    source = source.replace((TABLETOP / "board.js").as_uri(), mutant.as_uri())
    regression = tmp_path / "fog_memory_board.test.mjs"
    regression.write_text(source)
    result = subprocess.run(
        ["node", "--test-reporter=tap", "--test-name-pattern=reloaded (floor|cover) changed unseen", str(regression)],
        capture_output=True, text=True, timeout=120,
    )
    with capsys.disabled():
        print("FOGEDGE1F negative-control summary:\n" + "\n".join(result.stdout.splitlines()[-10:]), flush=True)
    assert result.returncode != 0, "The faulty backing unexpectedly passed"
    assert "# fail 2" in result.stdout, result.stdout + result.stderr
    assert result.stdout.count("final pixel cannot depend on unseen live replacement colors") == 2, result.stdout
