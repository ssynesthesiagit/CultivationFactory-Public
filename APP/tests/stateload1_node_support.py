"""Explicit runtime input contract for the phone DOM tests on public CI.

The phone imports rendering modules with cache-busting query strings. Declare
their complete source closure so static export includes real module paths; no
assertion or production import is replaced.
"""
from pathlib import Path


def require_runtime_assets():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        'static/play/play-board.js', 'static/play/play-client.js', 'static/play/play-model.js',
        'static/play/play-ui.js', 'static/tabletop/api.js', 'static/tabletop/art-kit.js',
        'static/tabletop/board.js', 'static/tabletop/decor-art.js', 'static/tabletop/error-text.js',
        'static/tabletop/flight-ui.js', 'static/tabletop/floor-art-indoor.js', 'static/tabletop/fog_memory.js',
        'static/tabletop/fog_polygon.js', 'static/tabletop/fog_presentation.js', 'static/tabletop/fog_view.js',
        'static/tabletop/ground-text.js', 'static/tabletop/hovercard.js', 'static/tabletop/limits.js',
        'static/tabletop/map-height-cards.js', 'static/tabletop/map-heights.js', 'static/tabletop/newcomer-data.js',
        'static/tabletop/newcomer.js', 'static/tabletop/object-arrange.js', 'static/tabletop/object-art-catalog.js',
        'static/tabletop/object-art.js', 'static/tabletop/object-presentation.js', 'static/tabletop/plain-ground.js',
        'static/tabletop/presentation.js', 'static/tabletop/remembered_scenery.js', 'static/tabletop/roof-art.js',
        'static/tabletop/roof-regions.js', 'static/tabletop/rules.js', 'static/tabletop/scenery-raster.js',
        'static/tabletop/seats.js', 'static/tabletop/terrain-art.js', 'static/tabletop/textures.js',
        'static/tabletop/tree-art.js', 'static/tabletop/viewer-identity.js', 'static/tabletop/vision.js',
        'static/tabletop/wall-art.js', 'static/tabletop/wall-object-art.js', 'static/tabletop/wall-openings.js',
        'static/tabletop/zone-text-data.js', 'static/tabletop/zone-text.js', 'static/tabletop/zonepaint.js',
        'static/tabletop/zones.js',
    ):
        assert (root / relative).is_file(), f'Missing phone runtime input: {relative}'
