"""Clean-import scratch copies must not pile up when a character is finished.

Finishing a character copies the whole data folder to a scratch folder to prove the
exported package imports into a brand new Factory.  That copy used to be left on
disk after every finished character (84 copies, ~40 GB).  These tests cover the
tidy-up: the run's own copy is deleted once the run ends -- on the success path
and on the rollback path -- copies from earlier runs are pruned to a small number,
and a copy a run is still reading is never deleted.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from character_creation import CharacterCreationExecutionService
from character_creation import auto_token as auto
from character_creation import clean_import_workspace
from character_creation.clean_import_workspace import KEEP_NEWEST_RUN_COPIES
from tests.test_cg1_owner_resolution_finalization import _finalization_service_and_run

RUN_ID = "cg1.run.clean-import-prune"
LIVE_RUN_ID = "cg1.run.clean-import-live"


@pytest.fixture(autouse=True)
def _no_leaked_reservations():
    """Keep a test's in-use marks from leaking into the next test."""
    yield
    for root, run_id in clean_import_workspace.held_reservations():
        clean_import_workspace.release(root, run_id)


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_copy(root: Path, run_id: str, mtime: float) -> Path:
    """Create a stand-in for one run's clean-import copy, with a known age."""
    copy = clean_import_workspace.run_copy(root, run_id)
    copy.mkdir(parents=True)
    (copy / "data").mkdir()
    (copy / "data" / "portable.db").write_text("scratch", encoding="utf-8")
    os.utime(copy, (mtime, mtime))
    return copy


def _remaining_copies(root: Path) -> list[str]:
    folder = clean_import_workspace.container(root)
    if not folder.is_dir():
        return []
    return sorted(child.name for child in folder.iterdir() if child.is_dir())


# --------------------------------------------------------------------------
# The scratch folder itself
# --------------------------------------------------------------------------


def test_run_copy_is_a_hidden_sibling_of_the_data_folder(tmp_path):
    """The copy must not sit inside the live data folder it copies."""
    root = _data_root(tmp_path)
    copy = clean_import_workspace.run_copy(root, RUN_ID)
    assert copy == tmp_path / ".data-cg1-clean-imports" / RUN_ID
    assert clean_import_workspace.container(root).parent == root.parent
    assert root not in copy.parents


def test_prune_keeps_only_the_newest_three_of_eighty_four_copies(tmp_path):
    """The reported leak: 84 finished runs left 84 whole copies on disk."""
    root = _data_root(tmp_path)
    for index in range(84):
        _make_copy(root, f"cg1.run.old-{index:03d}", mtime=1_000.0 + index)

    removed = clean_import_workspace.prune(root)

    assert len(removed.removed) == 84 - KEEP_NEWEST_RUN_COPIES
    assert removed.ok is True
    assert _remaining_copies(root) == [f"cg1.run.old-{index:03d}" for index in range(81, 84)]


def test_prune_is_a_no_op_when_there_is_no_scratch_folder_yet(tmp_path):
    """A first run has nothing to tidy, and must not raise for it."""
    root = _data_root(tmp_path)
    assert clean_import_workspace.prune(root).removed == ()
    assert _remaining_copies(root) == []


def test_prune_never_deletes_the_copy_a_run_is_still_using(tmp_path):
    """A long finalize started before three newer runs keeps its own copy."""
    root = _data_root(tmp_path)
    in_flight = _make_copy(root, "cg1.run.in-flight", mtime=1.0)
    for index in range(5):
        _make_copy(root, f"cg1.run.newer-{index}", mtime=2_000.0 + index)
    clean_import_workspace.reserve(root, "cg1.run.in-flight")

    clean_import_workspace.prune(root)

    assert in_flight.is_dir()
    assert "cg1.run.in-flight" in _remaining_copies(root)


# --------------------------------------------------------------------------
# One run's copy, once that run has finished with it
# --------------------------------------------------------------------------


def test_discard_deletes_one_runs_copy_and_ends_its_in_use_mark(tmp_path):
    root = _data_root(tmp_path)
    copy = _make_copy(root, RUN_ID, mtime=1.0)
    clean_import_workspace.reserve(root, RUN_ID)
    assert clean_import_workspace.in_use(root, RUN_ID) is True

    result = clean_import_workspace.discard(root, RUN_ID)

    assert result.removed == (RUN_ID,)
    assert result.ok is True
    assert not copy.exists()
    assert clean_import_workspace.in_use(root, RUN_ID) is False


def test_discard_reports_nothing_to_delete_when_the_run_never_made_a_copy(tmp_path):
    """Runs without a production release never make a copy; that is not an error."""
    root = _data_root(tmp_path)
    result = clean_import_workspace.discard(root, "cg1.run.never-ran")

    assert result.removed == ()
    assert result.failures == ()
    assert result.ok is True


# --------------------------------------------------------------------------
# The finalize flow itself, on a temporary data root
# --------------------------------------------------------------------------


def _finalizer(root: Path, db_path: Path, *, fail: bool, seen: dict):
    """A finalize service on a temp data root whose character pipeline is doubled.

    Everything up to and including the clean-import scratch folder is the real
    code; only the expensive character build (stage1/stage2/release) is replaced,
    so the success and rollback branches of the real finalizer are exercised.
    """
    svc, run, _ = _finalization_service_and_run(owner_resolutions=False)
    run["project_id"] = "p"
    run["created_at"] = "2026-10-01T00:00:00Z"
    run["request"]["typed_choice_snapshot"] = {"snapshot_sha256": "snapshot"}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE character_creation_runs
              (run_id TEXT, owner_decision TEXT, commit_json TEXT, final_revision INTEGER,
               output_json TEXT, status TEXT, updated_at TEXT, completed_at TEXT)"""
        )
        conn.execute("INSERT INTO character_creation_runs(run_id,status) VALUES (?,?)", (run["run_id"], run["status"]))

    @contextmanager
    def transaction():
        with sqlite3.connect(db_path) as conn:
            yield conn

    svc.db = SimpleNamespace(settings=SimpleNamespace(data_dir=root), transaction=transaction)

    def get(run_id):
        result = deepcopy(run)
        with sqlite3.connect(db_path) as conn:
            status, commit = conn.execute(
                "SELECT status,commit_json FROM character_creation_runs"
            ).fetchone()
        result["status"] = status
        result["commit"] = json.loads(commit) if commit else {}
        return result

    svc.get = get
    svc._approved_candidate_for_finalization = lambda *args: {
        "candidate_identity": "reviewed",
        "deterministic": True,
        "independent_compilations": 2,
        "identities": {},
    }
    svc.candidate_gm_authoring = SimpleNamespace(candidate_compilation_authority=lambda *a, **k: {})
    svc._require_frozen_choice_snapshot = lambda *args: {}
    svc._snapshot_data = lambda path, **kwargs: path.mkdir()
    svc._assert_completed_release_gate = lambda *args: None
    svc._snapshot_excluded_names = lambda: frozenset()
    svc._tree_hashes = lambda *args: {}
    svc._restore_data = lambda *args: None
    svc._record_finalize_failure = lambda *args: None
    svc._record_stage_timings = lambda *args: None
    svc._append_attempt = lambda *args, **kwargs: None
    svc._latest_attempt_id = lambda *args: None
    stable = {
        "factory_authoring": {},
        "command5": {},
        "consumer": {},
        "portable_audit": {},
        "clean_import": {},
    }
    svc.production_release = SimpleNamespace(_stable=lambda release: stable)

    def execute(*args, **kwargs):
        # The real clean-import proof makes this copy, reserves it, and then reads
        # it.  The double does the same: make the copy, and record that it is
        # there for the proof to read.
        copy = clean_import_workspace.run_copy(root, run["run_id"])
        copy.mkdir(parents=True)
        (copy / "data").mkdir()
        clean_import_workspace.reserve(root, run["run_id"])
        seen["copy_present_during_proof"] = copy.is_dir()
        seen["copies_during_proof"] = _remaining_copies(root)
        if fail:
            raise RuntimeError("mock live failure")
        return {"_production_release": {"production_artifact_identity": "release"}}

    svc._execute_live = execute
    return svc, run


def _seed_copies(root: Path, orphans: int = 6) -> None:
    """Copies left behind by earlier runs, oldest first."""
    for index in range(orphans):
        _make_copy(root, f"cg1.run.stale-{index:02d}", mtime=1_000.0 + index)


@pytest.mark.parametrize("fail", [False, True])
def test_finalize_removes_its_own_clean_import_copy_and_prunes_older_ones(tmp_path, monkeypatch, fail):
    """The bug: every finished character left a whole scratch copy behind.

    The run's copy is gone once the run ends, whether it ended in a committed
    character or a rollback, and copies left by earlier runs are tidied up to a
    small number instead of accumulating one per run.
    """
    monkeypatch.setattr(auto, "start", lambda *args, **kwargs: None)
    root = _data_root(tmp_path)
    _seed_copies(root)
    db_path = tmp_path / "finalize.sqlite"
    seen: dict = {}
    svc, run = _finalizer(root, db_path, fail=fail, seen=seen)
    run_id = run["run_id"]

    if fail:
        with pytest.raises(FoundryError) as raised:
            svc.finalize(run_id)
        assert raised.value.code == "CG1_FINALIZATION_ROLLED_BACK"
    else:
        assert svc.finalize(run_id)["status"] == "CLEAN_AND_FINALIZED"

    # The proof found its copy waiting for it.
    assert seen["copy_present_during_proof"] is True
    # ... and after the run there is no copy of this run left on disk.
    assert not clean_import_workspace.run_copy(root, run_id).exists()
    assert run_id not in _remaining_copies(root)
    # Copies from earlier runs are held to a small number, not one per run.
    assert len(_remaining_copies(root)) <= KEEP_NEWEST_RUN_COPIES


def test_finalize_prunes_a_backlog_before_adding_its_own_copy(tmp_path, monkeypatch):
    """The tidy-up runs per run, so a backlog cannot survive a later run."""
    monkeypatch.setattr(auto, "start", lambda *args, **kwargs: None)
    root = _data_root(tmp_path)
    for index in range(40):
        _make_copy(root, f"cg1.run.backlog-{index:02d}", mtime=1_000.0 + index)
    db_path = tmp_path / "finalize.sqlite"
    seen: dict = {}
    svc, run = _finalizer(root, db_path, fail=False, seen=seen)

    svc.finalize(run["run_id"])

    assert len(seen["copies_during_proof"]) <= KEEP_NEWEST_RUN_COPIES + 1
    assert len(_remaining_copies(root)) <= KEEP_NEWEST_RUN_COPIES


# --------------------------------------------------------------------------
# The real build step that creates the copy
# --------------------------------------------------------------------------


def _live_execution(tmp_path, *, root=None, run_id=LIVE_RUN_ID):
    """Use the real live orchestration with only expensive build stages doubled."""
    root = root or _data_root(tmp_path)
    svc = object.__new__(CharacterCreationExecutionService)
    handed: dict = {}

    class Release:
        def compile(self, *_args, clean_import_root=None, **kwargs):
            handed["path"] = clean_import_root
            handed["in_use"] = clean_import_workspace.in_use(root, run_id)
            handed["shared"] = clean_import_root == clean_import_workspace.run_copy(root, run_id)
            return {
                "factory_authoring": {},
                "command5": {},
                "consumer": {},
                "portable_audit": {"sha256": "portable"},
                "clean_import": {},
                "registration": None,
                "gm_export": None,
                "production_artifact_identity": "release",
                "combat_readiness": None,
                "completion_proof": {"combat": None},
            }

    class Stage1:
        def validate_response(self, *_args, **_kwargs):
            return {"attempt_id": "stage1-attempt"}

        def approve_and_commit(self, *_args, **_kwargs):
            return {"commit_id": "stage1-commit"}

    svc.db = SimpleNamespace(settings=SimpleNamespace(data_dir=root, logs_dir=tmp_path / "logs"))
    svc.owner_principal = "owner"
    svc._require_frozen_choice_snapshot = lambda _run: {"snapshot_sha256": "s" * 64}
    svc._plan_with_accepted_final_target = lambda _run, value, _accepted: value
    svc._execution_descriptive_fields = lambda _run, value: value
    svc._materialize_descriptive_fields = lambda *_a, **_k: None
    svc._materialize_delegated_final_grant_plan = lambda *_a, **_k: None
    svc._stage1_prior_attempt_id = lambda *_a, **_k: None
    svc._materialize_method_hard_lock = lambda *_a, **_k: {"method": "locked"}
    svc._delegated_path_ids_from_canonical_intent = lambda _value: []
    svc._issue_initial_catalog_provenance = lambda *_a, **_k: {"issued": True}
    svc._build_character_creation_projection = lambda *_a, **_k: {"projection": True}
    svc._stage2_commit = lambda *_a, **_k: ({"validation": True}, {"commit": True}, {"projection": True})
    svc._invoke = lambda _obj, names, *_a, **_k: {"surface": names[0]}
    svc._live_pipeline = lambda: {
        "stage1": Stage1(),
        "stage2": object(),
        "character_sheets": object(),
        "production_release": Release(),
        "combat_readiness": None,
    }
    run = {
        "run_id": run_id,
        "project_id": "p",
        "request": {"stage1_prompt": {"prompt_id": "prompt"}},
        "final_plan": {},
        "transport": {},
    }

    plan = {"stage1_response": {"path": "PATH"}, "stage2_proposal": {}, "output_profile": {}}
    return svc, run, plan, handed


def test_live_execution_hands_the_proof_the_shared_copy_path_and_holds_it(tmp_path):
    """The real proof call receives a protected copy at the shared path."""
    svc, run, plan, handed = _live_execution(tmp_path)
    svc._execute_live(run, plan)

    # The proof is given the one shared location, and it is protected while in use.
    assert handed["shared"] is True
    assert handed["in_use"] is True


# --------------------------------------------------------------------------
# A copy in use by ANOTHER process is still a copy in use
#
# The review found the old protection was a set in this process's memory: a second
# service instance, or a second OS process, finalizing against the same data folder
# could have its copy deleted by a tidy-up, and a copy that was only *marked* in
# use after the tidy-up had already looked would be treated as disposable.  The
# mark is now an operating-system file lock, which every process shares and which
# the tidy-up takes for itself before it deletes anything.
# --------------------------------------------------------------------------

_APP_DIR = Path(clean_import_workspace.__file__).resolve().parents[1]

_FOREIGN_RESERVE = """
import sys, time
from pathlib import Path
sys.path.insert(0, {app_dir!r})
from character_creation import clean_import_workspace
held = clean_import_workspace.reserve(Path(sys.argv[1]), sys.argv[2])
print("ready" if held else "busy", flush=True)
time.sleep(600)
"""


@contextmanager
def _foreign_reservation(root: Path, run_id: str):
    """Hold a run's reservation from a separate OS process, like a second service.

    Yields the child's reported result while it is alive. On context exit, kill
    and wait for it: only then has the operating system dropped its reservation.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_APP_DIR)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    child = subprocess.Popen(
        [sys.executable, "-c", _FOREIGN_RESERVE.format(app_dir=str(_APP_DIR)), str(root), run_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        line = child.stdout.readline().strip()
        if line not in {"ready", "busy"}:
            raise AssertionError(f"the other process never reserved: {line!r} {child.stderr.read()}")
        yield line == "ready"
    finally:
        if child.poll() is None:  # the other process only ever waits to be killed
            child.kill()
        child.wait(timeout=30)


def test_prune_keeps_a_copy_reserved_by_another_process(tmp_path):
    """The review's finding: the old in-memory mark did not reach other processes.

    A copy this process has never heard of, but which another process is reading
    right now, has to survive the tidy-up however old it is.
    """
    root = _data_root(tmp_path)
    theirs = _make_copy(root, "cg1.run.other-process", mtime=1.0)
    for index in range(6):
        _make_copy(root, f"cg1.run.mine-{index:02d}", mtime=2_000.0 + index)

    with _foreign_reservation(root, "cg1.run.other-process") as reserved:
        assert reserved is True
        result = clean_import_workspace.prune(root)

    assert theirs.is_dir()
    assert "cg1.run.other-process" not in result.removed
    assert "cg1.run.other-process" in _remaining_copies(root)


def test_a_reserve_that_lands_during_a_tidy_up_is_still_honoured(tmp_path, monkeypatch):
    """Deciding what to delete and deleting it must be one atomic step.

    The old code looked at the in-use marks once, up front, and then deleted for
    several seconds.  A run that marked its copy during that window was ignored.  The
    reservation is injected here inside the deletion loop, exactly where the old
    snapshot had already been taken.
    """
    root = _data_root(tmp_path)
    oldest = _make_copy(root, "cg1.run.oldest", mtime=1.0)
    _make_copy(root, "cg1.run.middle", mtime=2.0)
    for index in range(4):
        _make_copy(root, f"cg1.run.newer-{index}", mtime=3.0 + index)
    real_rmtree = shutil.rmtree
    granted: dict = {}

    def rmtree_reserving(path, *args, **kwargs):
        if not granted:  # a run marks its copy while the tidy-up is mid-list
            granted["held"] = clean_import_workspace.reserve(root, "cg1.run.oldest")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", rmtree_reserving)

    result = clean_import_workspace.prune(root)

    assert granted["held"] is True
    assert oldest.is_dir()
    assert "cg1.run.oldest" not in result.removed
    assert result.ok is True


def test_a_run_that_loses_the_race_is_told_its_copy_is_not_protected(tmp_path, monkeypatch):
    """The other half of atomicity: no run is told "reserved" and then loses its copy.

    When a tidy-up already owns the copy it is about to delete, a second reservation
    for the same run id fails and says so, instead of succeeding and then being
    ignored.
    """
    root = _data_root(tmp_path)
    _make_copy(root, RUN_ID, mtime=1.0)
    _make_copy(root, "cg1.run.newer", mtime=2_000.0)
    real_rmtree = shutil.rmtree
    outcome: dict = {}

    def rmtree_reserving(path, *args, **kwargs):
        # A second run asks for this very copy while the tidy-up already owns it.
        outcome[path.name] = clean_import_workspace.reserve(root, path.name)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", rmtree_reserving)
    monkeypatch.setattr(clean_import_workspace, "RESERVE_RETRY_SECONDS", 0.1)

    result = clean_import_workspace.prune(root, keep=0)

    assert set(outcome) == {"cg1.run.newer", RUN_ID}
    assert all(held is False for held in outcome.values())
    assert not clean_import_workspace.run_copy(root, RUN_ID).exists()
    assert result.removed == ("cg1.run.newer", RUN_ID)


def test_a_copy_whose_run_crashed_becomes_tidyable_again(tmp_path):
    """A killed run leaves a copy but no reservation, so the copy must not leak.

    This is why the mark is an OS lock and not a remembered run id: a crash cannot
    strand a copy the way a leaked in-memory mark would.
    """
    root = _data_root(tmp_path)
    crashed = _make_copy(root, "cg1.run.crashed", mtime=1.0)
    for index in range(5):
        _make_copy(root, f"cg1.run.newer-{index}", mtime=2_000.0 + index)

    with _foreign_reservation(root, "cg1.run.crashed") as reserved:
        assert reserved is True
        # While that process was alive its copy was untouchable, even though it was
        # the oldest in the folder.
        while_alive = clean_import_workspace.prune(root)
        assert "cg1.run.crashed" not in while_alive.removed
        assert crashed.is_dir()

    result = clean_import_workspace.prune(root)

    assert not crashed.exists()
    assert "cg1.run.crashed" in result.removed


def test_discard_leaves_a_copy_alone_when_another_process_still_holds_it(tmp_path):
    """A tidy-up must not delete a copy out from under a live read in another process."""
    root = _data_root(tmp_path)
    theirs = _make_copy(root, "cg1.run.other-process", mtime=1.0)

    with _foreign_reservation(root, "cg1.run.other-process") as reserved:
        assert reserved is True
        result = clean_import_workspace.discard(root, "cg1.run.other-process")

    assert theirs.is_dir()
    assert result.removed == ()
    assert [failure.name for failure in result.failures] == ["cg1.run.other-process"]


# --------------------------------------------------------------------------
# A removal that did not happen must not be reported as one
#
# The old code called shutil.rmtree(..., ignore_errors=True) and then reported the
# directory as removed.  A copy that could not be deleted -- a file still open, a
# read-only descendant, a full disk -- was left on disk with no warning at all.
# --------------------------------------------------------------------------


def test_discard_reports_a_failed_removal_and_keeps_the_copy_on_disk(tmp_path, monkeypatch, caplog):
    root = _data_root(tmp_path)
    copy = _make_copy(root, RUN_ID, mtime=1.0)
    clean_import_workspace.reserve(root, RUN_ID)

    def refuse(*_args, **_kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", refuse)

    with caplog.at_level("WARNING", logger="character_creation.clean_import_workspace"):
        result = clean_import_workspace.discard(root, RUN_ID)

    assert copy.is_dir()
    assert result.removed == ()
    assert result.ok is False
    assert [failure.name for failure in result.failures] == [RUN_ID]
    assert "Permission denied" in result.failures[0].reason
    assert "Permission denied" in caplog.text


def test_discard_does_not_claim_success_when_the_directory_is_still_there(tmp_path, monkeypatch):
    """The precise old bug: the error was swallowed and the copy reported as gone."""
    root = _data_root(tmp_path)
    copy = _make_copy(root, RUN_ID, mtime=1.0)

    monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", lambda *_a, **_k: None)

    result = clean_import_workspace.discard(root, RUN_ID)

    assert copy.is_dir()
    assert result.removed == ()
    assert result.ok is False
    assert result.failures[0].name == RUN_ID


def test_prune_reports_the_copies_it_could_not_remove(tmp_path, monkeypatch, caplog):
    """One undeletable copy must not be counted as a tidy-up, nor stop the rest."""
    root = _data_root(tmp_path)
    stuck = _make_copy(root, "cg1.run.stuck", mtime=1.0)
    for index in range(5):
        _make_copy(root, f"cg1.run.newer-{index}", mtime=2_000.0 + index)
    real_rmtree = shutil.rmtree

    def refuse(path, *args, **kwargs):
        if path.name == "cg1.run.stuck":
            return None  # a removal that silently leaves the copy behind
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", refuse)

    with caplog.at_level("WARNING", logger="character_creation.clean_import_workspace"):
        result = clean_import_workspace.prune(root)

    assert stuck.is_dir()
    assert "cg1.run.stuck" not in result.removed
    assert [failure.name for failure in result.failures] == ["cg1.run.stuck"]
    assert result.ok is False
    # The copies that could go, went: one stuck copy does not stop the tidy-up.
    assert len(result.removed) >= 1
    assert "cg1.run.stuck" in caplog.text


def test_a_reservation_is_dropped_when_its_run_is_finished(tmp_path):
    """The OS reservation ends; the stable empty marker remains for future openers."""
    root = _data_root(tmp_path)
    copy = _make_copy(root, RUN_ID, mtime=1.0)
    clean_import_workspace.reserve(root, RUN_ID)
    clean_import_workspace.discard(root, RUN_ID)

    clean_import_workspace.prune(root)

    assert clean_import_workspace.reservation_path(root, RUN_ID).is_file()
    assert not clean_import_workspace.in_use(root, RUN_ID)
    assert not copy.exists()


def test_in_use_is_false_for_a_run_that_never_reserved(tmp_path):
    """No marker at all means nobody reserved the run, not that it is in use.

    A copy nobody has claimed is tidyable, and asking must not answer otherwise --
    or a single first run would look permanently busy.
    """
    root = _data_root(tmp_path)
    _make_copy(root, RUN_ID, mtime=1.0)

    assert clean_import_workspace.in_use(root, RUN_ID) is False
    assert clean_import_workspace.in_use(root, "cg1.run.never-ran") is False


def test_a_tidy_up_leaves_no_markers_for_the_copies_it_kept(tmp_path):
    """Checking a copy must not leave a marker file behind for a run that never asked."""
    root = _data_root(tmp_path)
    for index in range(6):
        _make_copy(root, f"cg1.run.old-{index}", mtime=1_000.0 + index)

    clean_import_workspace.prune(root)

    folder = clean_import_workspace.container(root)
    left = sorted(
        child.name
        for child in folder.iterdir()
        if child.name.endswith(clean_import_workspace.RESERVATION_SUFFIX)
    )
    assert left == [f"cg1.run.old-{index}{clean_import_workspace.RESERVATION_SUFFIX}" for index in range(3)]


# --------------------------------------------------------------------------
# ...and the same, through a real finalize
# --------------------------------------------------------------------------


def test_finalize_does_not_prune_a_copy_another_process_is_using(tmp_path, monkeypatch):
    """Service level: one character's tidy-up must not disturb another's proof.

    The other process's copy is the oldest in the folder, so a tidy-up that only
    looked at its own process's marks would take it -- and the finalize that owns
    that read would fail its clean-import proof.
    """
    monkeypatch.setattr(auto, "start", lambda *args, **kwargs: None)
    root = _data_root(tmp_path)
    theirs = _make_copy(root, "cg1.run.other-process", mtime=1.0)
    _seed_copies(root)
    db_path = tmp_path / "finalize.sqlite"
    svc, run = _finalizer(root, db_path, fail=False, seen={})

    with _foreign_reservation(root, "cg1.run.other-process") as reserved:
        assert reserved is True
        assert svc.finalize(run["run_id"])["status"] == "CLEAN_AND_FINALIZED"

    assert theirs.is_dir()
    assert "cg1.run.other-process" in _remaining_copies(root)
    assert run["run_id"] not in _remaining_copies(root)
    # The backlog is still tidied: only the copy in use was spared.
    assert len(_remaining_copies(root)) <= KEEP_NEWEST_RUN_COPIES + 1


@pytest.mark.parametrize("has_copy", [False, True])
def test_marker_identity_survives_an_opener_paused_before_lock(tmp_path, monkeypatch, has_copy):
    """Neither orphan-marker cleanup nor copy deletion may replace a waiting inode."""
    root = _data_root(tmp_path)
    marker = clean_import_workspace.reservation_path(root, RUN_ID)
    marker.parent.mkdir(parents=True)
    marker.touch()
    if has_copy:
        _make_copy(root, RUN_ID, mtime=1.0)
    inode = marker.stat().st_ino
    opened, proceed = threading.Event(), threading.Event()
    real_open = Path.open
    outcome = {}

    def pause_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if path == marker and threading.current_thread() is reserver:
            opened.set()
            if not proceed.wait(10):
                handle.close()
                raise TimeoutError("prune never let the opener continue")
        return handle

    def reserve():
        outcome["held"] = clean_import_workspace.reserve(root, RUN_ID)

    reserver = threading.Thread(target=reserve)
    monkeypatch.setattr(Path, "open", pause_open)
    reserver.start()
    try:
        assert opened.wait(10)
        assert clean_import_workspace.prune(root, keep=0).ok
    finally:
        proceed.set()
        reserver.join(10)
    assert not reserver.is_alive()
    assert outcome["held"] is True
    assert marker.stat().st_ino == inode
    copy = _make_copy(root, RUN_ID, mtime=1.0)
    assert clean_import_workspace.prune(root, keep=0).removed == ()
    assert copy.is_dir()


def test_identical_run_ids_in_different_roots_have_separate_ownership(tmp_path, monkeypatch):
    root_a = _data_root(tmp_path / "a")
    root_b = _data_root(tmp_path / "b")
    copy_a = _make_copy(root_a, RUN_ID, mtime=1.0)
    copy_b = _make_copy(root_b, RUN_ID, mtime=1.0)
    assert clean_import_workspace.reserve(root_a, RUN_ID)
    monkeypatch.setattr(clean_import_workspace, "RESERVE_RETRY_SECONDS", 0)
    with _foreign_reservation(root_b, RUN_ID) as reserved:
        assert reserved
        assert not clean_import_workspace.reserve(root_b, RUN_ID)
        assert not clean_import_workspace.discard(root_b, RUN_ID).ok
        clean_import_workspace.release(root_b, RUN_ID)
        assert copy_b.is_dir()
        assert clean_import_workspace.in_use(root_a, RUN_ID)
        assert clean_import_workspace.prune(root_a, keep=0).removed == ()
        assert copy_a.is_dir()
    assert clean_import_workspace.reserve(root_b, RUN_ID)
    assert clean_import_workspace.discard(root_b, RUN_ID).ok
    assert clean_import_workspace.in_use(root_a, RUN_ID)


def test_data_root_alias_uses_the_same_marker_and_release(tmp_path):
    root = _data_root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert clean_import_workspace.run_copy(alias, RUN_ID) == clean_import_workspace.run_copy(root, RUN_ID)
    assert clean_import_workspace.reserve(root, RUN_ID)
    assert clean_import_workspace.reserve(alias, RUN_ID)
    assert clean_import_workspace.held_reservations() == ((root.resolve(), RUN_ID),)
    clean_import_workspace.release(alias, RUN_ID)
    assert not clean_import_workspace.in_use(root, RUN_ID)


def test_discard_keeps_its_lock_without_blocking_other_reservations(tmp_path, monkeypatch):
    root = _data_root(tmp_path / "a")
    other = _data_root(tmp_path / "b")
    copy = _make_copy(root, RUN_ID, mtime=1.0)
    assert clean_import_workspace.reserve(root, RUN_ID)
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(clean_import_workspace, "RESERVE_RETRY_SECONDS", 0)

    def delete(path, *args, **kwargs):
        clean_import_workspace.release(root, RUN_ID)
        assert clean_import_workspace.reserve(other, RUN_ID)
        # Closing the original handle must not let a new opener own a deletion
        # that is still in progress. No global mutex is held across this callback.
        assert not clean_import_workspace.reserve(root, RUN_ID)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", delete)
    assert clean_import_workspace.discard(root, RUN_ID).removed == (RUN_ID,)
    assert not copy.exists()
    assert clean_import_workspace.in_use(other, RUN_ID)
    assert not clean_import_workspace.in_use(root, RUN_ID)


@pytest.mark.parametrize("refusal", ["marker_access", "slow_cleanup"])
def test_finalize_rolls_back_before_proof_when_reservation_is_refused(tmp_path, monkeypatch, refusal):
    """Exercise real finalize + live execution; proof must never run unprotected."""
    monkeypatch.setattr(auto, "start", lambda *args, **kwargs: None)
    root = _data_root(tmp_path)
    svc, run = _finalizer(root, tmp_path / "finalize.sqlite", fail=False, seen={})
    live, live_run, plan, handed = _live_execution(tmp_path, root=root, run_id=run["run_id"])
    svc._execute_live = lambda *_a, **_k: live._execute_live(live_run, plan)
    copy = _make_copy(root, run["run_id"], mtime=1.0)
    marker = clean_import_workspace.reservation_path(root, run["run_id"])
    entered, finish = threading.Event(), threading.Event()
    worker = None
    outcome = {}
    if refusal == "marker_access":
        real_open = Path.open

        def deny_marker(path, *args, **kwargs):
            if path == marker:
                raise PermissionError("marker access denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_marker)
    else:
        real_rmtree = shutil.rmtree

        def slow_delete(path, *args, **kwargs):
            if path == copy:
                entered.set()
                assert finish.wait(10)
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(clean_import_workspace.shutil, "rmtree", slow_delete)
        monkeypatch.setattr(clean_import_workspace, "RESERVE_RETRY_SECONDS", 0.05)

        def prune():
            outcome["result"] = clean_import_workspace.prune(root, keep=0)

        worker = threading.Thread(target=prune)
        worker.start()
        assert entered.wait(10)
    try:
        with pytest.raises(FoundryError) as raised:
            svc.finalize(run["run_id"])
        assert raised.value.code == "CG1_FINALIZATION_ROLLED_BACK"
        assert raised.value.details["cause_code"] == "CG1_CLEAN_IMPORT_RESERVATION_FAILED"
        assert handed == {}  # No release compile or proof execution.
        assert svc.get(run["run_id"])["status"] != "CLEAN_AND_FINALIZED"
        assert copy.is_dir()  # Rollback cleanup neither guesses nor steals ownership.
    finally:
        finish.set()
        if worker is not None:
            worker.join(10)
    if worker is not None:
        assert not worker.is_alive()
        assert outcome["result"].removed == (run["run_id"],)


@pytest.mark.parametrize("operation", ["prune", "discard"])
@pytest.mark.parametrize("failure", ["stat", "marker_open", "flock"])
def test_cleanup_access_errors_return_failures(tmp_path, monkeypatch, operation, failure):
    root = _data_root(tmp_path)
    copy = _make_copy(root, RUN_ID, mtime=1.0)
    marker = clean_import_workspace.reservation_path(root, RUN_ID)
    if failure == "stat":
        real_stat = Path.stat

        def deny_stat(path, *args, **kwargs):
            if path == copy:
                raise PermissionError("copy access denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", deny_stat)
    elif failure == "marker_open":
        real_open = Path.open

        def deny_open(path, *args, **kwargs):
            if path == marker:
                raise PermissionError("marker access denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_open)
    else:
        def deny_lock(*args):
            raise PermissionError("lock access denied")

        monkeypatch.setattr(clean_import_workspace.fcntl, "flock", deny_lock)
    result = (clean_import_workspace.prune(root, keep=0) if operation == "prune"
              else clean_import_workspace.discard(root, RUN_ID))
    assert not result.ok
    assert result.removed == ()
    assert result.failures[0].name == RUN_ID
    assert "PermissionError" in result.failures[0].reason
    monkeypatch.undo()
    assert copy.is_dir()


def test_prune_enumeration_error_is_failure_not_missing_container(tmp_path, monkeypatch):
    root = _data_root(tmp_path)
    _make_copy(root, RUN_ID, mtime=1.0)
    folder = clean_import_workspace.container(root)
    real_iterdir = Path.iterdir

    def deny_listing(path):
        if path == folder:
            raise PermissionError("scratch listing denied")
        return real_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", deny_listing)
    result = clean_import_workspace.prune(root, keep=0)
    assert not result.ok
    assert result.removed == ()
    assert result.failures[0].name == folder.name
    assert "PermissionError" in result.failures[0].reason
