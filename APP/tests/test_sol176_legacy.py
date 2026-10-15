"""Unstamped c4326a2c saves continue byte-identically under the repaired modules."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
BASE = "c4326a2c"


@pytest.fixture(scope="module")
def base_source(tmp_path_factory):
    # Directory symlinks plus the few changed blobs: never a second project copy.
    root = tmp_path_factory.mktemp("sol176-base") / "APP"
    root.mkdir()
    changed = ["combat/typed_executor.py", "combat/factory_compiler.py", "combat/zones.py", "combat/ext/__init__.py",
               "combat/ext/teleport_steps.py", "combat/ext/scoundrel_riders.py",
               "combat/ext/rider_outcomes.py",
               "combat/ext/ability_source.py",
               "authority/Tianxia_Typed_Mechanics_Authority_R1.json"]
    dirs = {Path(p).parent for p in changed} | {Path(".")}
    dirs |= {parent for d in list(dirs) for parent in d.parents}
    def stage(relative):
        for path in (APP / relative).iterdir():
            rel = relative / path.name
            dest = root / rel
            if str(rel) == "combat/ext/subject_repositioning.py" or path.name == "__pycache__":
                continue
            if rel in dirs:
                dest.mkdir()
                stage(rel)
            elif str(rel) in changed:
                dest.write_bytes(subprocess.check_output(["git", "show", f"{BASE}:APP/{rel}"], cwd=APP.parent))
            else:
                dest.symlink_to(path, target_is_directory=path.is_dir())
    stage(Path("."))
    return root


@pytest.mark.parametrize("scenario", ["fail", "success", "gap", "stock"])
def test_pre_fix_saved_fight_continues_identically(base_source, tmp_path, scenario):
    script = APP / "tests/sol176_legacy_capture.py"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    def run(root, data, phase, mid=None):
        args = [sys.executable, str(script), str(root), str(data), phase, scenario]
        return subprocess.check_output(args + ([mid] if mid else []), cwd=root, env=env)
    initial = tmp_path / "initial"
    mid = run(base_source, initial, "prepare").decode().strip()
    before, after = tmp_path / "base", tmp_path / "head"
    shutil.copytree(initial, before)
    shutil.copytree(initial, after)
    expected = run(base_source, before, "continue", mid)
    actual = run(APP, after, "continue", mid)
    assert actual == expected, scenario


def test_behavior_regressions_fail_against_unmodified_base(base_source, tmp_path):
    cases = [
        "test_target_displacement_chooses_and_moves_only_subject_after_reload[MANUAL-15-1]",
        "test_target_displacement_chooses_and_moves_only_subject_after_reload[MANUAL-15-20]",
        "test_chosen_area_recipients_commit_reload_and_spare_friends[TAL_VOID_COLLAPSING_GAP-Collapsing Gap-True-MANUAL]",
        "test_bob_cover_ends_on_leaving_and_does_not_return_after_commit_reload",
    ]
    args = ["-q", "--tb=short", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'negative'}",
            *[str(APP / "tests/test_sol176_subject_displacement.py") + "::" + case for case in cases]]
    # Bind the base combat package before pytest inserts the head test directory.
    code = "import sys;sys.path.insert(0,sys.argv[1]);import combat.factory_compiler;import pytest;raise SystemExit(pytest.main(sys.argv[2:]))"
    result = subprocess.run([sys.executable, "-c", code, str(base_source), *args], cwd=base_source,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, text=True, capture_output=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "4 failed" in result.stdout and "ERROR collecting" not in result.stdout, result.stdout + result.stderr
