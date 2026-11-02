"""The one place that builds a `node --test` command for the Python tests that drive client modules.

Several client tests must run in the runner's own process: they read their fixture from stdin, or share one file's globals
with the caller's environment. Node's runner does that with "isolation none", and the flag's name changed between releases:
`--experimental-test-isolation=none` (Node 22.8+), `--test-isolation=none` (Node 23.6+ and newer), nothing at all in older
Nodes (Node 20 runs each file in its own process). Asking `node --test-isolation=none` on a Node that has only the old name
fails with "node: bad option" before any test loads, so the flag is probed once per process and used if the installed Node
accepts it; without it the file still runs under the default isolation. Fixture-backed callers use ``run_node_test`` so
payloads survive runners that isolate each file's stdin. Tests never spell the flag.
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


def run_node_test(*arguments: str, input: str | None = None, node: str = "node", **kwargs):
    """Run a Node test and deliver fixtures via file, independent of runner stdin isolation."""
    if input is None:
        return subprocess.run(node_test_command(*arguments, node=node), **kwargs)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as fixture:
        fixture.write(input)
        fixture_path = fixture.name
    env = os.environ.copy()
    env["PI_NODE_TEST_FIXTURE"] = fixture_path
    try:
        return subprocess.run(node_test_command(*arguments, node=node), env=env, **kwargs)
    finally:
        os.unlink(fixture_path)
