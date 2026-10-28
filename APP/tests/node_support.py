"""The one place that builds a `node --test` command for the Python tests that drive client modules.

Several client tests must run in the runner's own process: they read their fixture from a payload (see `run_node_test`), or share one file's globals
with the caller's environment. Node's runner does that with "isolation none", and the flag's name changed between releases:
`--experimental-test-isolation=none` (Node 22.8+), `--test-isolation=none` (Node 23.6+ and newer), nothing at all in older
Nodes (Node 20 runs each file in its own process). Asking `node --test-isolation=none` on a Node that has only the old name
fails with "node: bad option" before any test loads, so the flag is probed once per process and used if the installed Node
accepts it; without it the file still runs, just under the runner's default isolation. Tests call ``node_test_command`` and
never spell the flag.
"""
import functools
import os
import subprocess
import tempfile

ISOLATION_FLAGS = ("--test-isolation=none", "--experimental-test-isolation=none")


@functools.lru_cache(maxsize=None)
def isolation_flag(node: str = "node") -> str | None:
    """The in-process isolation flag the installed Node accepts, or None."""
    for flag in ISOLATION_FLAGS:
        probe = subprocess.run([node, flag, "-e", ""], capture_output=True, text=True)
        if probe.returncode == 0:
            return flag
    return None


def node_test_command(*arguments: str, node: str = "node", before: tuple[str, ...] = ()) -> list[str]:
    """``node [before...] --test [isolation flag] arguments...``; ``before`` holds options such as ``--import loader``."""
    flag = isolation_flag(node)
    return [node, *before, "--test", *([flag] if flag else []), *arguments]


FIXTURE_ENV = "PI_NODE_TEST_FIXTURE"


def run_node_test(payload: str, *arguments: str, node: str = "node", before: tuple[str, ...] = (),
                  timeout: int = 120) -> subprocess.CompletedProcess:
    """Run ``node_test_command(*arguments)`` with ``payload`` as the file's fixture (read by ``readStdinPayload``).

    The payload goes in a temp file named by ``FIXTURE_ENV``, not on stdin: without an isolation flag (Node 20) the runner
    starts each file in a child process that never receives this process's stdin, so a stdin payload was silently lost and
    the file skipped its cases. The environment reaches that child on every Node version.
    """
    with tempfile.TemporaryDirectory() as folder:
        fixture = os.path.join(folder, "fixture.json")
        with open(fixture, "w", encoding="utf-8") as handle:
            handle.write(payload)
        env = {**os.environ, FIXTURE_ENV: fixture}
        return subprocess.run(node_test_command(*arguments, node=node, before=before), env=env,
                              stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=timeout)
