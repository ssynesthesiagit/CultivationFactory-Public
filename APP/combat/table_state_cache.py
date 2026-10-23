"""Reuse a built table state between reads while nothing it was built from has changed.

Used by ``TabletopService.state`` only (SPEEDREUSE2, owner 2026-10-18 after a 10-creature playtest: "it just shows we
are still not there with speed"). A big fight takes seconds to build and an idle browser re-reads it every few seconds,
so the last answer to each exact request is kept and handed out again, but only while every input it was built from is
provably unchanged. A stale table is worse than a slow one: an input this module cannot identify exactly is identified
conservatively (a whole folder of owner-editable rules, every file of the fight), so an unrelated change costs one
rebuild, never an out-of-date answer.

What identifies a kept answer (:meth:`TabletopService._state_inputs` builds it from the helpers below). It is worked out
before the build and again after it, and an answer whose inputs moved while it was being built is returned but not
kept:

* the fight's saved files: the journal by size, inode and last bytes (``CombatService._fingerprint``; every load touches
  its modification time), every other file in the fight's folder by size, modification time and inode, small files
  also by their bytes (seat and pause choices, the saved Ask-me prompt, the controller journal, divergence notes), and
  its saved snapshots; resolving the fight's folder (which refuses colliding folders) runs again for every read;
* the in-memory divergence note of the fight's last commit;
* the owner-editable rules and printed text (``combat/rules``, ``authority``), the summon pictures that ship with the
  program and the engine's generated locks and battlefield (``combat_gate*/generated``; :data:`SHARED_TREES`);
* what the table reads from user data besides the fight: round tokens and summon pictures, each character's saved
  buttons, table name and advancement (``tabletop_buttons``) and the installed character packages;
* ``CF_*`` switches in the environment;
* the code a read runs that can be swapped while the process runs (:func:`code_identity`): plug-in hooks and effects
  registered after start-up, and any function of the table or combat service (or of their classes) replaced at run
  time, as tests replace seams;
* how the menu ranking used cached text embeddings (``menu_rank.ranking_record``): an answer ranked without them is not
  reused once they have arrived, nor one ranked with them once they are evicted. A reuse asks the embedding client to
  warm the missing texts again, exactly as a fresh build would.

A build that had to fall back (a menu or item list it could not work out, :func:`decline`) is returned but not
kept, so the next read tries again.

An answer is kept as pickled bytes and unpickled for each read, so no caller ever receives an object another caller or
the cache holds, and each value has exactly the type a fresh build gives (tuples stay tuples). ``CF_TABLE_STATE_REUSE=0``
turns reuse off. Bounded per fight and in total bytes; thread-safe.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import threading
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parents[1]
#: Owner-editable rules and text, the summon pictures shipped with the program and the generated engine files. Whole
#: trees, so a new reader of any file inside them is covered without keeping a list of file names.
SHARED_TREES: tuple[Path, ...] = (
    APP_ROOT / "combat" / "rules",
    APP_ROOT / "authority",
    APP_ROOT / "static" / "tabletop" / "summon_tokens",
    # The engine's generated locks and battlefield, read again by every fight load.
    *(APP_ROOT / f"combat_gate{gate}" / "generated" for gate in range(1, 6)),
)
#: Files at most this size are identified by their bytes too: an atomic same-size rewrite inside the clock's
#: granularity can reuse an inode, and seat, pause and prompt files are small.
SMALL_FILE_BYTES = 64 * 1024
PER_MATCH = 4
TOTAL_BYTES = 48 * 1024 * 1024


def enabled() -> bool:
    return os.environ.get("CF_TABLE_STATE_REUSE", "1") != "0"


_DECLINED: ContextVar[list | None] = ContextVar("table_state_declined", default=None)


def decline(reason: str) -> None:
    """Called by a build that fell back after a failure (a menu or item list it could not work out): never keep it.

    The next read builds again instead of repeating the fallback until the fight changes. Inert outside a read.
    """
    rows = _DECLINED.get()
    if rows is not None:
        rows.append(reason)


def _identity(path: str, stat: os.stat_result, *, content: bool) -> tuple:
    row: tuple = (path, stat.st_size, stat.st_mtime_ns, stat.st_ino)
    if content and stat.st_size <= SMALL_FILE_BYTES:
        try:
            with open(path, "rb") as stream:
                row += (hashlib.blake2b(stream.read(), digest_size=16).digest(),)
        except OSError:
            row += (None,)
    return row


def folder_files(folder: Path, *, skip: tuple[str, ...] = (), content: bool = True) -> tuple | None:
    """Every top-level file of ``folder`` (dot files, which are locks and temporary saves, excluded); None if absent."""
    rows = []
    try:
        entries = list(os.scandir(folder))
    except (FileNotFoundError, NotADirectoryError):
        return None
    for entry in entries:
        if entry.name.startswith(".") or entry.name in skip:
            continue
        try:
            if not entry.is_file():
                continue
            rows.append(_identity(entry.name, entry.stat(), content=content))
        except OSError:
            rows.append((entry.name, None))
    return tuple(sorted(rows, key=repr))


def tree_files(root: Path) -> tuple:
    """Every file below ``root`` by size, modification time and inode; an absent folder is recorded as absent."""
    rows: list = []

    def walk(folder: str) -> None:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            rows.append((folder, None))
            return
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    walk(entry.path)
                elif entry.is_file():
                    rows.append(_identity(entry.path, entry.stat(), content=False))
            except OSError:
                rows.append((entry.path, None))

    walk(str(root))
    return tuple(sorted(rows, key=repr))


def project_files(install_root: Path | None) -> tuple | None:
    """The files of every installed character package (``<install root>/<project>/current.zip`` and its neighbours)."""
    if install_root is None:
        return None
    try:
        projects = sorted(entry.path for entry in os.scandir(install_root) if entry.is_dir())
    except OSError:
        return None
    return tuple((path, folder_files(Path(path), content=False)) for path in projects)


def shared_inputs() -> tuple:
    return tuple(tree_files(root) for root in SHARED_TREES)


def switches() -> tuple:
    return tuple(sorted((key, value) for key, value in os.environ.items() if key.startswith("CF_")))


def code_identity(*services: Any) -> tuple:
    """Which functions a read would run: the plug-in registries and each service's own and class functions.

    Production registers plug-ins once at start-up and never replaces a method, so this stays fixed there. A hook
    registered later, or a seam replaced on an instance or class, changes it and the next read is built again.
    """
    from . import ext

    # Asking for a hook point nobody registered adds an empty list to the registry; that is not a change.
    rows: list = [id(ext._HOOKS), tuple((point, tuple(map(id, functions))) for point, functions in ext._HOOKS.items()
                                        if functions),
                  id(ext._EFFECTS), tuple(map(id, ext._EFFECTS.values())), id(ext._HOOK_PRIORITIES)]
    for service in services:
        rows.append(tuple((name, id(value)) for name, value in vars(service).items() if callable(value)))
        rows.append(tuple(id(value) for value in vars(type(service)).values()))
    return tuple(rows)


class StateReuse:
    """Bounded store of built table states, keyed by the exact request and checked against its inputs on every read."""

    def __init__(self, per_match: int = PER_MATCH, total_bytes: int = TOTAL_BYTES):
        self.per_match, self.total_bytes = per_match, total_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple, tuple[Any, bytes, tuple]] = OrderedDict()
        self._bytes = 0
        self.hits = self.misses = 0

    def read(self, key: tuple, build: Callable[[], dict], inputs: Callable[[], Any]) -> dict:
        """``build()``'s answer for ``key``: a kept copy while ``inputs()`` is unchanged, otherwise a fresh build."""
        from . import menu_rank

        if not enabled():
            return build()
        try:
            before = inputs()
        except Exception:  # noqa: BLE001 - an input that cannot be identified is never reused
            return build()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] == before and menu_rank.ranking_current(entry[2]):
                self._entries.move_to_end(key)
                self.hits += 1
                payload, ranking = entry[1], entry[2]
            else:
                payload = ranking = None
        if payload is not None:
            menu_rank.rewarm(ranking)
            return pickle.loads(payload)
        with self._lock:
            self.misses += 1
        declined = []
        token = _DECLINED.set(declined)
        try:
            with menu_rank.ranking_record() as ranking:
                value = build()
        finally:
            _DECLINED.reset(token)
        if declined or not isinstance(value, dict):
            return value
        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            after = inputs()
        except Exception:  # noqa: BLE001 - an answer that cannot be copied or re-identified is not kept
            return value
        if after == before:
            self._keep(key, before, payload, tuple(ranking))
        return value

    def _keep(self, key: tuple, stamp: Any, payload: bytes, ranking: tuple) -> None:
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= len(old[1])
            if len(payload) > self.total_bytes:
                return
            self._entries[key] = (stamp, payload, ranking)
            self._bytes += len(payload)
            same_match = [k for k in self._entries if k[0] == key[0]]
            for stale in same_match[:-self.per_match]:
                self._bytes -= len(self._entries.pop(stale)[1])
            while self._bytes > self.total_bytes and self._entries:
                self._bytes -= len(self._entries.popitem(last=False)[1][1])
