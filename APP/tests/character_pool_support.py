"""The owner's portable character pool: the one reader for every test that needs it.

The pool is held data. It is bound read-only only for host jobs on Swarmlord; lane jobs never have it. A pool
that is missing or holds no */current.zip means a misrouted run or a broken host, so the reader FAILS. It never
skips, and it never lets a test pass with nothing checked (POOLFAIL1).
"""
import os
from pathlib import Path

import pytest

POOL = Path(os.environ.get("P6_CHARACTER_POOL", "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters"))


def pool_archives() -> list[Path]:
    """Every owner sheet archive in the pool, sorted. Fails when the pool is missing or empty."""
    paths = sorted(POOL.glob("*/current.zip"))
    if not paths:
        pytest.fail(f"Owner character pool missing or empty: {POOL} (no */current.zip). "
                    "It is bound only for host jobs on Swarmlord; lane jobs never have it.")
    return paths
