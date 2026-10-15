"""Explicit runtime input contract for the phone DOM tests on public CI.

wall-art imports art-kit with a cache-busting query string. Declare its real
path too so static export includes the source module; no assertion is replaced.
"""
from pathlib import Path


def require_runtime_assets():
    root = Path(__file__).resolve().parents[1]
    for relative in ('static/tabletop/art-kit.js',):
        assert (root / relative).is_file(), f'Missing phone runtime input: {relative}'
