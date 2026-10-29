"""Public export must never ship the private stock wrapper or its environment test.

The exporter source is a local tool; it is not part of the public tree, so it is read lazily and the guard skips
there instead of aborting collection of the whole public shard.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPORT_PATH = ROOT / "tools" / "public_test_export.py"


def _export():
    if not EXPORT_PATH.is_file():
        pytest.skip("tools/public_test_export.py is local-only; not in the public tree")
    return EXPORT_PATH.read_text()


def test_stock_wrappers_are_declared_local_only():
    export = _export()
    for name in ("test_mgr_t15_mirror_stock.py", "test_mgr_t15_stock_environment.py"):
        assert f'"APP/tests/{name}"' in export


def test_export_drops_local_only_candidates_before_selection():
    export = _export()
    local_block = export.index("for path in sorted(LOCAL_ONLY_TESTS & set(candidates))")
    fields_line = export.index("fields = {r.get('field'")
    assert local_block < fields_line
    assert "candidates.pop(path)" in export[local_block:fields_line]
