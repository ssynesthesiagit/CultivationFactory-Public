"""Bookkeeping for the throwaway "clean import" copy made when a character is finished.

Finishing a character proves the exported package really does import into a brand
new Factory.  To do that, the whole data folder is copied to a scratch folder, the
package is imported into the copy, and the result is compared with the original.
That copy is pure scratch and is large (tens of gigabytes once a data folder has
grown), so it has to be thrown away when the run ends.  It used to be left behind
every time, so the disk slowly filled with one whole copy per finished character.

This module owns the three things the finalize flow needs, so the copy's location,
its cleanup and the protection that keeps a live copy from being tidied away cannot
drift apart:

* :func:`container` / :func:`run_copy` -- where the copy for one run lives.  Both
  call sites in the service go through here rather than writing the path twice.
* :func:`prune` -- keep only the newest few run copies, so even a crash or a
  ``kill -9`` that skips the normal cleanup still cannot fill the disk.
* :func:`reserve` / :func:`release` / :func:`discard` -- who is allowed to delete
  a copy, and what the tidy-up really managed to delete.

Safety rule: a successfully reserved copy is never pruned while its owner reads it.
The caller must stop before proof execution if reservation fails. While a run reads
its copy it holds an operating-system file lock (the same ``flock`` the saved-fight
writer uses) on a small marker file beside that copy, and :func:`prune` deletes a
copy only after it has taken that same lock for itself.  Deciding and deleting
under one lock is what makes the rule hold: a copy in use by another process or by
another service instance survives however old it is, and a run that reserves a copy
while a tidy-up is already part way through its list is still safe -- its
reservation cannot appear and vanish between the decision and the deletion.

Two consequences of using an OS lock, both intended:

* The rule is not process-local.  Two service instances, or two OS processes,
  finalizing different characters against the same data folder protect each other,
  which is the case the previous in-memory set silently got wrong.
* The lock belongs to the operating system, so a run that dies without tidying up
  (a crash, a ``kill -9``) leaves no stuck reservation: its copy is prunable again
  from the next tidy-up instead of leaking forever.

Marker files remain even after their copies are deleted: unlinking a locked marker
would let a waiting opener lock an unreachable inode and lose its protection.
These empty files cost a little metadata per run; the large data copies are bounded.
Reservations are scoped to the canonical data root and run id. This protects the
scratch proof, not concurrent edits or finalization of the same live data root.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator

LOG = logging.getLogger(__name__)

# How many finished runs' copies to keep on disk.  Three is enough to compare the
# last few results by hand while still bounding the scratch folder to a small
# fraction of one data copy; raise it to keep more history.
KEEP_NEWEST_RUN_COPIES = 3

# Name of the per-run marker file that carries the "in use" lock.  It is a plain
# file in the scratch folder, so it is ignored by the copy listing (which only
# looks at folders) and costs nothing when it outlives its copy.
RESERVATION_SUFFIX = ".in-use"

# How long :func:`reserve` waits for a marker that another owner is holding.  It
# only ever waits on the one run's own marker, so this cannot slow down two runs
# that are merely in progress at the same time.
RESERVE_RETRY_SECONDS = 2.0
_RESERVE_RETRY_STEP = 0.02

# This process's reservations, (canonical data root, run id) -> locked handle. The
# handle being open *is* the reservation: closing it (or the process dying) hands
# the lock back, so there is no mark that can be forgotten or leaked.
_LOCK = threading.Lock()
_HELD: dict[tuple[Path, str], IO[bytes]] = {}


@dataclass(frozen=True)
class CleanupFailure:
    """One scratch copy that is still on disk, and why it was not removed."""

    name: str
    reason: str


@dataclass(frozen=True)
class CleanupResult:
    """The truthful outcome of one tidy-up pass.

    ``removed`` lists the copies that were confirmed gone.  ``failures`` lists the
    ones that are still on disk, each with a reason, so a caller (or a log line)
    can tell a real clean-up from a failed one instead of taking ``True`` on faith.
    """

    removed: tuple[str, ...] = ()
    failures: tuple[CleanupFailure, ...] = ()

    @property
    def ok(self) -> bool:
        """True when no cleanup failed (protected/budgeted copies may remain)."""
        return not self.failures

    def __bool__(self) -> bool:
        return self.ok


def container(data_dir: Path) -> Path:
    """Return the folder that holds every run's clean-import copy.

    The folder is a hidden sibling of the data folder so it is never mistaken for
    live data and is never inside the data folder that the finalize snapshot and
    rollback copy.
    """
    data_dir = Path(data_dir).resolve()
    return data_dir.parent / f".{data_dir.name}-cg1-clean-imports"


def run_copy(data_dir: Path, run_id: str) -> Path:
    """Return the one folder that holds ``run_id``'s clean-import copy."""
    return container(data_dir) / str(run_id)


def reservation_path(data_dir: Path, run_id: str) -> Path:
    """Return the marker file whose lock stands for "this run is using its copy"."""
    return container(data_dir) / f"{str(run_id)}{RESERVATION_SUFFIX}"


# --------------------------------------------------------------------------
# Who is using a copy
# --------------------------------------------------------------------------


@contextmanager
def _claim(path: Path, *, create: bool = True) -> Iterator[bool]:
    """Open (creating if asked) a marker and take its lock if it is free.

    Yields True when the marker says nobody is using the copy, which is the only
    condition under which a copy may be deleted: either this call took the lock
    itself, or there is no marker at all (a run that never reserved is not using
    the copy). It yields False only when another owner holds the lock; access and
    other lock errors raise OSError so cleanup can report failure. The OS drops
    the lock when the handle closes, including when the owning process is killed, so
    a claim is also the honest test for "nobody is using this any more".
    """
    try:
        handle = path.open("a+b" if create else "r+b")
    except FileNotFoundError:
        if create:
            raise
        yield True
        return
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - the close below ends the lock anyway
                pass
    finally:
        handle.close()


@contextmanager
def _owned(data_dir: Path, run_id: str) -> Iterator[bool]:
    """Hold ``run_id``'s marker lock across a block, if this run may hold it.

    A run that already reserved the copy keeps its own reservation.  Any other
    caller (a tidy-up, or a run that never reserved) gets the lock only when it is
    genuinely free.  Yields False when somebody else owns it, which means the copy
    must not be deleted.
    """
    run_id = str(run_id)
    key = (Path(data_dir).resolve(), run_id)
    with _LOCK:
        mine = _HELD.get(key)
        # A duplicate shares the same OS lock. Keep deletion protected even if a
        # local release closes the original, without blocking other roots/runs
        # on the bookkeeping mutex for the duration of a large tree deletion.
        held_fd = os.dup(mine.fileno()) if mine is not None else None
    if held_fd is not None:
        try:
            yield True
        finally:
            os.close(held_fd)
        return
    with _claim(reservation_path(data_dir, run_id)) as claimed:
        yield claimed


def reserve(data_dir: Path, run_id: str) -> bool:
    """Mark ``run_id``'s copy as in use so :func:`prune` will not delete it.

    Called while the clean-import proof is reading the copy.  The mark is an OS file
    lock, so it is honoured by every other process and service instance sharing the
    data folder, and it disappears with the process if the run dies. False means
    the marker is busy or inaccessible; the caller must stop before using the copy.
    """
    run_id = str(run_id)
    key = (Path(data_dir).resolve(), run_id)
    path = reservation_path(key[0], run_id)
    deadline = time.monotonic() + RESERVE_RETRY_SECONDS
    while True:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOG.warning("Could not create the clean-import scratch folder: %s", exc)
            return False
        with _LOCK:
            if key in _HELD:
                return True
            try:
                handle = path.open("a+b")
            except OSError as exc:
                LOG.warning("Could not mark the clean-import copy for run %s as in use: %s", run_id, exc)
                return False
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
            except OSError as exc:
                handle.close()
                LOG.warning("Could not lock the clean-import marker for run %s: %s", run_id, exc)
                return False
            else:
                _HELD[key] = handle
                return True
        if time.monotonic() >= deadline:
            LOG.warning("Another owner is still using run %s; its clean-import copy is not marked in use here.", run_id)
            return False
        time.sleep(_RESERVE_RETRY_STEP)


def release(data_dir: Path, run_id: str) -> None:
    """Undo :func:`reserve` once the run no longer reads its copy.

    The empty marker stays at its stable path, including after cleanup.
    """
    with _LOCK:
        handle = _HELD.pop((Path(data_dir).resolve(), str(run_id)), None)
        if handle is not None:
            handle.close()


def held_reservations() -> tuple[tuple[Path, str], ...]:
    """Return (canonical data root, run id) pairs reserved by this process.

    Exposed so a test can hand back what it took without reaching into the
    module's private bookkeeping.
    """
    with _LOCK:
        return tuple(sorted(_HELD))


def in_use(data_dir: Path, run_id: str) -> bool:
    """Report whether any owner, in this process or another, still holds ``run_id``."""
    run_id = str(run_id)
    with _LOCK:
        if (Path(data_dir).resolve(), run_id) in _HELD:
            return True
    try:
        with _claim(reservation_path(data_dir, run_id), create=False) as claimed:
            return not claimed
    except OSError:
        return True  # Access errors cannot establish that deletion is safe.


# --------------------------------------------------------------------------
# Deleting copies
# --------------------------------------------------------------------------


def _delete_tree(path: Path, name: str) -> CleanupResult:
    """Delete one copy and confirm it is gone before reporting success.

    ``shutil.rmtree(..., ignore_errors=True)`` is deliberately not used: it hides
    the very failure this module exists to notice.  A copy that survives the call --
    because the error was swallowed, or because a descendant could not be unlinked --
    is reported as a failure with the directory still on disk.
    """
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass  # another pass already removed it; there is nothing left to leak
    except OSError as exc:
        reason = f"{type(exc).__name__}: {exc}"
        LOG.warning("Could not remove the clean-import scratch copy %s: %s", name, reason)
        return CleanupResult(failures=(CleanupFailure(name, reason),))
    try:
        path.stat()
    except FileNotFoundError:
        return CleanupResult(removed=(name,))
    except OSError as exc:
        return _access_failure(name, exc)
    else:
        reason = "the copy is still on disk after removal"
        LOG.warning("Could not remove the clean-import scratch copy %s: %s", name, reason)
        return CleanupResult(failures=(CleanupFailure(name, reason),))


def _access_failure(name: str, exc: OSError) -> CleanupResult:
    """Report an inaccessible folder or marker separately from an active owner."""
    reason = f"{type(exc).__name__}: {exc}"
    LOG.warning("Could not tidy clean-import scratch %s: %s", name, reason)
    return CleanupResult(failures=(CleanupFailure(name, reason),))


def prune(data_dir: Path, *, keep: int = KEEP_NEWEST_RUN_COPIES, protect: object = ()) -> CleanupResult:
    """Delete all but the ``keep`` newest run copies; report what happened.

    A copy is deleted only once this call has taken the in-use lock for that copy,
    so a copy being read by any run -- in this process or another -- always
    survives, even if ``keep`` newer ones have finished since it started.  Checking
    and deleting under one lock also means a run that reserves a copy while this
    pass is part way through its list cannot have it deleted underneath: either the
    reservation is seen (and the copy kept) or this pass already owns the copy (and
    that run is not reading it yet).  A name in ``protect`` is never deleted
    whatever else is true.

    Housekeeping only: it never raises, because failing to tidy scratch space must
    never fail a character build.  Deletions that did not work are returned in
    :attr:`CleanupResult.failures` and logged, never counted as removed.
    """
    try:
        keep = max(0, int(keep))
    except (TypeError, ValueError):
        keep = KEEP_NEWEST_RUN_COPIES
    try:
        protected = {str(name) for name in protect}  # type: ignore[union-attr]
    except TypeError:
        protected = set()
    folder = container(data_dir)
    removed: list[str] = []
    failures: list[CleanupFailure] = []
    try:
        children = list(folder.iterdir())
    except FileNotFoundError:
        return CleanupResult()
    except OSError as exc:
        return _access_failure(folder.name, exc)
    aged_entries = []
    for child in children:
        try:
            info = child.stat()
        except FileNotFoundError:
            continue  # A concurrent cleanup already removed it.
        except OSError as exc:
            failures.extend(_access_failure(child.name, exc).failures)
            continue
        if stat.S_ISDIR(info.st_mode):
            aged_entries.append((child, info.st_mtime))
    entries = [child for child, _ in sorted(aged_entries, key=lambda item: (-item[1], item[0].name))]
    survivors = 0
    for child in entries:
        if child.name in protected:
            survivors += 1
            continue
        if survivors < keep:
            # Inside the budget: kept, so nothing is claimed for it and no marker is
            # created for a run that never reserved.
            survivors += 1
            continue
        # Beyond the budget, and the only place a copy can be lost: holding the
        # marker is the whole safety argument.  It is free only when no run is
        # reading the copy, and it is the same lock every reserver takes.
        try:
            with _claim(folder / f"{child.name}{RESERVATION_SUFFIX}") as mine:
                if not mine:
                    # Active copies may exceed the retention budget; safety takes
                    # priority over reclaiming a run's working data.
                    survivors += 1
                    continue
                result = _delete_tree(child, child.name)
                removed.extend(result.removed)
                failures.extend(result.failures)
        except OSError as exc:
            failures.extend(_access_failure(child.name, exc).failures)
    return CleanupResult(removed=tuple(removed), failures=tuple(failures))


def discard(data_dir: Path, run_id: str) -> CleanupResult:
    """Delete one run's copy and stop reserving it; report what happened.

    Called once a run has finished with its copy, on both the success and the
    failure path.  The copy is only removed while this run holds the in-use lock, so
    it cannot be deleted out from under a read still in progress.  Never raises: a
    copy that outlives the run only costs disk, and the failure is returned and
    logged rather than swallowed.
    """
    run_id = str(run_id)
    copy = run_copy(data_dir, run_id)
    try:
        present = stat.S_ISDIR(copy.stat().st_mode)
    except FileNotFoundError:
        present = False
    except OSError as exc:
        release(data_dir, run_id)
        return _access_failure(run_id, exc)
    if not present:
        # Nothing was ever copied, so there is nothing to protect and nothing to
        # claim; the reservation, if this run somehow holds one, has no work left.
        release(data_dir, run_id)
        return CleanupResult()
    try:
        with _owned(data_dir, run_id) as mine:
            if not mine:
                reason = "another owner is still using this run's copy"
                LOG.warning("Leaving the clean-import copy for run %s alone: %s.", run_id, reason)
                return CleanupResult(failures=(CleanupFailure(run_id, reason),))
            result = _delete_tree(copy, run_id)
    except OSError as exc:
        result = _access_failure(run_id, exc)
    # The run no longer reads the copy, even if deletion failed.
    release(data_dir, run_id)
    return result
