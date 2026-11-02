from pathlib import Path

from combat.gate2_artifacts import build_gate2_artifacts


ROOT = Path(__file__).resolve().parents[1]


def test_gate2_generated_artifacts_rebuild_byte_identically(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    ma = build_gate2_artifacts(a)
    mb = build_gate2_artifacts(b)
    assert ma == mb
    files_a = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    assert files_a == files_b
    assert ma["profile_coverage_status"] == "PASS"
    assert ma["profile_count"] == 68
    assert ma["runtime_schema_count"] == 12
