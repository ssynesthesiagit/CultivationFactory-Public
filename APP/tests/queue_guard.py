"""Admission check shared by pytest sessions and standalone replay captures.

This is an accidental-execution guard, not a security boundary: the explicit
override is reserved for an owner-authorized direct run.
"""
import os
from datetime import datetime, timezone
from pathlib import Path


QUEUE_MESSAGE = (
    "Run tests through the queue. Write the test files or node ids, one per line, to a list file "
    "under /var/tmp, then: cd APP && python3 /var/tmp/auto-tools/heavyq.py run --label <LANE>-<what> -- "
    "<venv python> /var/tmp/auto-audit/sweeprun/r25chunk.py <list file> <basetemp under /var/tmp>"
)
DIRECT_LOG = Path("/var/tmp/heavyq/direct.log")


def require_test_queue():
    """Admit queued cgroups, GitHub shards, or a receipted owner override.

    Queue environment markers are deliberately insufficient. Agent lanes need a
    real queue cgroup; owner/GitHub overrides apply only outside lanes.slice.
    Unreadable cgroups retain owner/GitHub admission; failed receipts fail closed.
    """
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        cgroup = ""
    lane = "lanes.slice" in cgroup
    if not lane and os.environ.get("CF_ALLOW_DIRECT_TESTS") == "1":
        try:
            DIRECT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with DIRECT_LOG.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now(timezone.utc).isoformat()} "
                             f"pid={os.getpid()} CF_ALLOW_DIRECT_TESTS=1\n")
        except OSError:
            pass
        else:
            return
    elif not lane and os.environ.get("GITHUB_ACTIONS") == "true":
        return
    elif "pueued.service" in cgroup or "heavyq-" in cgroup:
        return
    import pytest

    pytest.exit(QUEUE_MESSAGE, returncode=4)
