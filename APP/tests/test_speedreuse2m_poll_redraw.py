"""SPEEDREUSE2M: an unchanged compact poll must not redraw the board and action bar.

Runs the production renderObservedState body in Node against a test context (tests/speedreuse2m_poll_redraw.mjs);
no browser, network or model. The same harness fails on main, where renderObservedState compares the compact poll
with the movement-expanded copy render() stored (checked against main 1844d4f2: "an unchanged compact poll must
not rebuild the table, 1 !== 0"). An .mjs harness, not .cjs: the public test export clears .js/.mjs dependencies
and withholds .cjs, so this regression can run on public CI.
"""
import subprocess
from pathlib import Path


def test_unchanged_compact_poll_keeps_the_table():
    subprocess.run(["node", str(Path(__file__).with_name("speedreuse2m_poll_redraw.mjs"))],
                   check=True, timeout=120)
