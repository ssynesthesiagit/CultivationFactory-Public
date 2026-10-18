"""SPEEDREUSE2M: an unchanged compact poll must not redraw the board and action bar.

Runs the production renderObservedState body in Node against a test context (tests/speedreuse2m_poll_redraw.cjs);
no browser, network or model. The same harness fails on the base commit, where renderObservedState compares the
compact poll with the movement-expanded copy render() stored.
"""
import subprocess
from pathlib import Path


def test_unchanged_compact_poll_keeps_the_table():
    subprocess.run(["node", str(Path(__file__).with_name("speedreuse2m_poll_redraw.cjs"))],
                   check=True, timeout=120)