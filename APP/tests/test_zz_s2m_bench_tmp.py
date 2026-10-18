"""TEMPORARY bench wrapper (SPEEDREUSE2M): runs the timing probe through the admitted queue entry point.

Deleted before the commit; never committed.
"""
import subprocess
import sys
from pathlib import Path

BENCH = Path("/var/tmp/auto-audit/wt-speedreuse2/.scratch/bench_state.py")
APP = Path("/var/tmp/auto-audit/wt-speedreuse2/APP")
SCRATCH = Path("/var/tmp/auto-audit/wt-speedreuse2/.scratch/bench")


def test_state_timing_bench():
    proc = subprocess.run([sys.executable, str(BENCH), str(APP), "16acaeb1", str(SCRATCH)],
                          capture_output=True, text=True, timeout=3000)
    print("\n===== BENCH STDOUT =====\n" + proc.stdout[-20000:])
    print("\n===== BENCH STDERR =====\n" + proc.stderr[-8000:])
    assert proc.returncode == 0, f"bench failed {proc.returncode}"