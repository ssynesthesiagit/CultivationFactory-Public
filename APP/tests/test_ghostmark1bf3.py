"""Focused GHOSTMARK1BF3 regressions, isolated from unrelated board snapshots."""
from pathlib import Path
import subprocess

# These modules use cache-busted imports; keep their plain files in the public snapshot.
PUBLIC_RESOURCES = (
    'art-kit.js', 'decor-art.js', 'flight-ui.js', 'floor-art-indoor.js',
    'fog_polygon.js', 'fog_presentation.js', 'ground-text.js', 'hovercard.js',
    'map-height-cards.js', 'object-art-catalog.js', 'object-art.js',
    'remembered_scenery.js', 'roof-art.js', 'roof-regions.js', 'scenery-raster.js',
    'terrain-art.js', 'tree-art.js', 'vision.js', 'wall-art.js',
    'wall-object-art.js', 'wall-openings.js', 'zone-text-data.js',
    'zone-text.js', 'zonepaint.js', 'zones.js',
)


def test_ghostmark1bf3_identity_regressions():
    static = Path(__file__).resolve().parents[1] / 'static' / 'tabletop'
    result = subprocess.run(
        ['node', '--test', '--test-reporter=tap',
         '--test-name-pattern=out-of-roster remembered tokens|identity contradicts the roster|never re-identified from the roster',
         str(static / 'fog_memory_board.test.mjs')],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
