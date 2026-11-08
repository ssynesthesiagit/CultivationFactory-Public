from pathlib import Path

from combat.gate2_profile_coverage import build_runtime_profile_coverage, write_runtime_profile_coverage


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json"


def test_all_68_mechanics_lock_profiles_bind_runtime_handlers_or_explicit_dispositions(tmp_path):
    result = build_runtime_profile_coverage(LOCK)
    assert result["status"] == "PASS"
    assert result["profile_count"] == 68
    assert result["covered_count"] + result["disposition_count"] == 68
    assert result["missing_count"] == 0
    assert result["missing_profile_ids"] == []


def test_runtime_profile_coverage_is_canonical_and_reproducible(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    write_runtime_profile_coverage(LOCK, a)
    write_runtime_profile_coverage(LOCK, b)
    assert a.read_bytes() == b.read_bytes()
