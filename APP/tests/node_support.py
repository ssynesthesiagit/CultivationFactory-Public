"""Build ``node --test`` commands for Python tests that drive client modules.

Some client tests read fixture payloads or share globals with the caller. Node's
runner does that with "isolation none", whose flag changed between releases:
``--experimental-test-isolation=none`` (Node 22.8+),
``--test-isolation=none`` (Node 23.6+ and newer), or no supported flag on older
Nodes (Node 20 runs each file in its own process). Probe each candidate once;
without a supported flag, run with Node's default isolation. Tests use
``node_test_command`` instead of spelling the flag.
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
