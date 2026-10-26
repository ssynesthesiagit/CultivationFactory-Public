"""GHOSTMARK1B focused Node checks, submitted as a whole-file public CI job."""
from pathlib import Path
import subprocess
import pytest

# Explicit resources keep cache-busted JS imports in the public CI snapshot.
# The exporter currently treats the query suffix as part of the filename.
PUBLIC_RESOURCES = (
    'art-kit.js', 'decor-art.js', 'flight-ui.js', 'floor-art-indoor.js',
    'fog_polygon.js', 'fog_presentation.js', 'ground-text.js', 'hovercard.js',
    'map-height-cards.js', 'object-art-catalog.js', 'object-art.js',
    'remembered_scenery.js', 'roof-art.js', 'roof-regions.js', 'scenery-raster.js',
    'terrain-art.js', 'tree-art.js', 'vision.js', 'wall-art.js',
    'wall-object-art.js', 'wall-openings.js', 'zone-text-data.js',
    'zone-text.js', 'zonepaint.js', 'zones.js',
)


@pytest.mark.parametrize('name', [
    'ghostmark.test.mjs', 'fog_memory_board.test.mjs',
    'fog_memory.test.mjs', 'board.test.mjs',
    'fog_memory_store.test.mjs',
])
def test_remembered_token_board(name):
    static = Path(__file__).resolve().parents[1] / 'static' / 'tabletop'
    result = subprocess.run(['node', '--test', str(static / name)],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
