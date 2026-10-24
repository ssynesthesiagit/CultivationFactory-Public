"""Public export must never ship the private stock wrapper or its environment test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORT = (ROOT / "tools" / "public_test_export.py").read_text()


def test_stock_wrappers_are_declared_local_only():
    for name in ("test_mgr_t15_mirror_stock.py", "test_mgr_t15_stock_environment.py"):
        assert f'"APP/tests/{name}"' in EXPORT


def test_export_drops_local_only_candidates_before_selection():
    local_block = EXPORT.index("for path in sorted(LOCAL_ONLY_TESTS & set(candidates))")
    fields_line = EXPORT.index("fields = {r.get('field'")
    assert local_block < fields_line
    assert "candidates.pop(path)" in EXPORT[local_block:fields_line]
