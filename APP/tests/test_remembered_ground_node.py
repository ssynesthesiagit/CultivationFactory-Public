"""Offline remembered-ground regressions, including the table snapshot/reload path."""
from pathlib import Path
import json
import subprocess

import pytest


@pytest.mark.parametrize("name", ["fog_memory_board", "fog_memory", "fog_memory_store", "fog_polygon", "floor-art-indoor", "scenery-reuse", "board"])
def test_remembered_ground_node(name):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["/usr/bin/node", "--test", "--test-isolation=none", "--test-reporter=tap", f"APP/static/tabletop/{name}.test.mjs"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=180,
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("mutation,pattern", [
    ("footprint", "natural background and diagonal"),
    ("plain", "plain ground and its transparent"),
    ("readiness", "delayed image readiness"),
    ("border", "exact border seam"),
    ("blend", "exact blended boundary"),
    ("quota", "table captures survive a quota-limited reload"),
    ("upload-backdrop", "transparent uploaded ground"),
    ("upload-theme-cache", "transparent uploaded ground"),
])
def test_regression_rejects_missing_fix(mutation, pattern, tmp_path):
    """Mutate only a subprocess module load; never edit production files."""
    root = Path(__file__).resolve().parents[2]
    target = "fog_memory_store.js" if mutation == "quota" else "board.js"
    source = (root / f"APP/static/tabletop/{target}").read_text()
    if mutation == "quota":
        old = "else await backend.set(key, snapshot);"
        assert old in source
        source = source.replace(old, "else saveMemory(storage, key, snapshot);", 1)
    elif mutation == "footprint":
        start = source.index("        for (const [x, y] of row.cells) {", source.index("inexactFloorCells = new Set(hardCells)"))
        end = source.index("\n      }\n      if (!floor.hidden", start)
        source = source[:start] + "        for (const [x, y] of row.cells) inexactFloorCells.add(`${x},${y}`);" + source[end:]
    else:
        old, new = {
            "plain": ('context.drawImage(painted, 0, 0);', 'if (background.style !== "plain") context.drawImage(painted, 0, 0);'),
            "readiness": ('handlers.onFloorReady?.();', '/* missing readiness snapshot */'),
            "border": ('context.stroke();', '/* missing border stroke */'),
            "blend": ('if (!blend || isArtificial(row.style)) {', 'if (true) {'),
            "upload-backdrop": ('context.fillRect(0, 0, destW, destH);', '/* missing sight-time backdrop */'),
            "upload-theme-cache": (":${backdrop.join(',')}`", '`'),
        }[mutation]
        assert old in source
        source = source.replace(old, new, 1)
    loader = tmp_path / "mutation-loader.mjs"
    loader.write_text(
        "import {registerHooks} from 'node:module';\nregisterHooks({load(url, context, nextLoad) {\n"
        "const result = nextLoad(url, context);\n"
        "if (url.startsWith('file:') && new URL(url).pathname.endsWith('/" + target + "')) "
        "return {...result, source: " + json.dumps(source) + "};\n"
        "return result;\n}});\n"
    )
    result = subprocess.run(
        ["/usr/bin/node", "--import", str(loader), "--test", "--test-isolation=none", "--test-reporter=tap", "--test-name-pattern", pattern,
         "APP/static/tabletop/fog_memory_board.test.mjs"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
    )
    print(f"NEGATIVE CONTROL {mutation}\n{result.stdout}")
    assert result.returncode != 0, "regression passed with its fix removed"
    assert "not ok" in result.stdout and "AssertionError" in result.stdout, result.stdout
    if mutation == "quota":
        assert "all accumulated sight-time pixels reload exactly" in result.stdout, result.stdout
    elif mutation == "upload-backdrop":
        assert "transparent pixels preserve the sight-time backdrop" in result.stdout, result.stdout
    elif mutation == "upload-theme-cache":
        assert "new visible captures refresh the theme-sensitive composition cache" in result.stdout, result.stdout
