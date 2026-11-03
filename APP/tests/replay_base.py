"""Shared Git revision that replay guard tests compare the checkout against.

Used by the stock AI capture guards (``tests/wall_height_stock_capture``
based): ``test_wall_height_replays``, ``test_fog_altitude``,
``test_bounce_replays``, ``test_ai_flight_replays``,
``test_map_height_replays``, ``test_d1_seat``, ``test_a2_glass_stock``,
``test_a2_qisub6r3_stock`` and ``finalize_speed2_replay_check``.

Resolution rule (owner 2026-10-12), in order:

1. ``CF_REPLAY_BASE`` (or its historical alias ``WALLHEIGHT_REPLAY_BASE``)
   in the environment is used verbatim.  A release check that must compare
   against one exact reviewed commit pins it here instead of editing tests.
   A pin that does not name a revision in this repository raises
   :class:`ReplayPinError` - a mistyped release base must fail loudly, never
   turn the guards into silent skips.
2. Otherwise the base is the merge-base of ``HEAD`` with the first of
   ``main``, ``origin/main``, ``github/main``, ``swarmlord-main`` that both
   resolves in this repository *and* shares a commit with ``HEAD``, so a
   mainline ref that exists but is unrelated to the checkout (an imported
   history) no longer blocks a later remote mainline from anchoring the
   guard.  The guard then answers the question it exists for - "did the
   changes on *this* branch move the stock AI trajectories?" - and does not
   blame the branch for mainline commits it legitimately merged in.  A
   checkout without a local ``main`` (shallow or detached CI, a lane repo)
   still compares against its remote-tracking mainline instead of erroring.
3. When ``HEAD`` *is* that merge-base (the checkout is that mainline
   ref itself) the merge-base rule would compare the checkout against
   itself and pass for no reason, so the base is ``HEAD^1`` instead:
   the same test then asks "did the newest mainline commit move the
   stock AI trajectories?".

The resolved rev is always a full commit id verified to exist in this
repository.  :func:`replay_base` raises :class:`ReplayBaseError` when
no override is set and no mainline ref is usable: a caller that must
fail closed gets a failure, never a silent pass.  Guard tests call
:func:`replay_base_or_skip` from inside the test body instead: it
resolves lazily (cached for the session, never at import time, so
collection cannot fail) and calls ``pytest.skip`` - naming
``CF_REPLAY_BASE`` - when nothing resolves, so such a checkout skips
the guard instead of failing it.  A broken explicit pin and a Git
failure are the two cases that still fail loudly there: only the
automatic no-mainline case may skip.

Absent ref versus Git failure: the two are told apart by Git's exit
protocol.  A lookup that fails with exit status 1 and no diagnostic
names nothing (an absent ref, or two refs with no common ancestor),
so the resolver falls through to the next candidate and, when no
candidate is usable, the guard skips.  Anything else - any other
exit status, any stderr output, Git not running at all, a timeout -
is an operational failure (:class:`ReplayGitError`) that must fail
the guard: an unverified comparison must never count as a pass.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
MAIN_REFS = ("main", "origin/main", "github/main", "swarmlord-main")
OVERRIDE_VARS = ("CF_REPLAY_BASE", "WALLHEIGHT_REPLAY_BASE")
GIT_TIMEOUT = 120


class ReplayBaseError(RuntimeError):
    """The replay comparison base is unknown, so the guard test must fail."""


class ReplayPinError(ReplayBaseError):
    """An explicit ``CF_REPLAY_BASE`` override names no revision in this repo."""


class ReplayGitError(ReplayBaseError):
    """Git itself failed, so the guard must fail instead of skipping.

    Git being unavailable, a repository being inaccessible, or a
    lookup timing out is not a missing ref: an operational failure
    must never degrade a replay guard into a skip, or an unverified
    comparison would count as a pass.
    """


def _probe(root: Path, *arguments: str) -> str | None:
    """Run a read-only Git lookup where a clean failure means "not found".

    Returns the stripped stdout, or ``None`` when Git exits 1 without
    any diagnostic - its signal for an absent ref or a missing
    merge-base.  A probe that fails any other way (Git unavailable, a
    broken repository, any stderr output, a timeout) raises
    :class:`ReplayGitError`: only a genuinely absent ref may be treated
    as "not found", never a Git failure.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "-c", f"safe.directory={root}", *arguments],
            text=True, capture_output=True, env=environment, timeout=GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ReplayGitError(f"git {' '.join(arguments)} could not run in {root}: {error}") from error
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 1 and not result.stderr.strip():
        return None
    raise ReplayGitError(
        f"git {' '.join(arguments)} failed in {root}: "
        f"{result.stderr.strip() or result.stdout.strip() or f'exit {result.returncode}'}"
    )


def _commit(root: Path, revision: str) -> str | None:
    """The full commit id of ``revision`` in ``root``, or ``None``.

    ``None`` means ``revision`` names no commit here (an absent ref).
    A broken repository or any other Git failure raises
    :class:`ReplayGitError` instead of masquerading as an absent ref.
    """
    resolved = _probe(root, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
    if resolved is None:
        return None
    if len(resolved) != 40 or any(character not in "0123456789abcdef" for character in resolved):
        raise ReplayGitError(
            f"git rev-parse returned a malformed commit id for {revision!r} "
            f"in {root}: {resolved!r}"
        )
    return resolved


def override() -> str | None:
    """The pinned base from the environment, if a release check set one."""
    for name in OVERRIDE_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _mainline_base(root: Path, head: str) -> str | None:
    """The base from the first *usable* mainline ref in ``root``, or ``None``.

    :data:`MAIN_REFS` are tried in order.  A candidate that does not
    resolve in this repository is skipped, and so is one that resolves
    but shares no commit with ``HEAD`` (an unrelated import, for
    example): a later remote mainline gets its chance before the guard
    gives up.  Any other failure while probing a candidate is a Git
    error and propagates as :class:`ReplayGitError` - it must not be
    mistaken for an absent ref.  When ``HEAD`` is the candidate's
    merge-base with HEAD (the checkout is that mainline ref itself) the
    base is ``HEAD^1``, so a guard is never a self-comparison; a
    mainline without a first parent leaves no usable base (``None``).
    """
    for name in MAIN_REFS:
        if _commit(root, name) is None:
            continue
        shared = _probe(root, "merge-base", "HEAD", name)
        if shared is None:
            continue
        base = _commit(root, shared)
        if base is None:
            raise ReplayGitError(
                f"git merge-base reported {shared!r} as the merge-base of "
                f"HEAD and {name} in {root}, but it names no commit"
            )
        if base == head:
            base = _commit(root, "HEAD^1")
            if base is None:
                return None
        return base
    return None


def replay_base(root: Path | str | None = None) -> str:
    """Return the full commit id the replay guards must compare the checkout to.

    ``root`` defaults to this repository; tests pass their own temporary
    repository to prove the rule without depending on live branch state.
    Raises :class:`ReplayPinError` when an env override names a revision
    that does not exist here, :class:`ReplayGitError` when Git itself
    fails, and :class:`ReplayBaseError` when no override is set and none
    of :data:`MAIN_REFS` is usable: a caller that must not guess gets a
    failure, never a silent pass.
    """
    root = Path(root).resolve() if root is not None else ROOT
    pinned = override()
    if pinned:
        resolved = _commit(root, pinned)
        if resolved is None:
            raise ReplayPinError(
                f"{'/'.join(OVERRIDE_VARS)}={pinned!r} does not name a "
                f"revision in {root}; fix the pin or unset it"
            )
        return resolved
    head = _commit(root, "HEAD")
    if head is None:
        raise ReplayBaseError(
            f"HEAD names no commit in {root}, so there is no replay "
            "comparison base. Pin an exact commit with CF_REPLAY_BASE instead."
        )
    base = _mainline_base(root, head)
    if base is None:
        raise ReplayBaseError(
            f"Cannot resolve the replay base in {root}: none of "
            f"{', '.join(MAIN_REFS)} resolves here with a common ancestor "
            "of HEAD. Pin an exact commit with CF_REPLAY_BASE instead."
        )
    return base


_session_base: str | None = None


def replay_base_or_skip(root: Path | str | None = None) -> str:
    """The replay base for guard tests, resolved lazily inside the test.

    Caches the default repository's base for the session, so a
    parametrized guard pays for one resolution, not one per test.
    Two cases fail the guard loudly instead of skipping: an invalid
    explicit pin (``CF_REPLAY_BASE`` naming a revision that does not
    exist here - the release check must never degrade into a silent
    skip) and a Git failure (Git unavailable, a broken repository, a
    timeout - an unverified comparison must never count as a pass).
    Only the automatic case - no override set and no mainline ref
    usable - skips the test with a message naming ``CF_REPLAY_BASE``:
    a shallow or detached checkout without a mainline ref must never
    fail collection and must never silently pass.
    """
    global _session_base
    if root is None and _session_base is not None:
        return _session_base
    try:
        base = replay_base(root)
    except ReplayPinError as error:
        pytest.fail(f"Invalid replay base pin: {error}")
    except ReplayGitError as error:
        pytest.fail(f"Replay base lookup failed: {error}")
    except ReplayBaseError as error:
        pytest.skip(
            f"No replay comparison base resolves ({error}) Set "
            "CF_REPLAY_BASE to one exact commit to run this guard; "
            "skipping because this checkout has no mainline ref to "
            "compare against."
        )
    if root is None:
        _session_base = base
    return base
