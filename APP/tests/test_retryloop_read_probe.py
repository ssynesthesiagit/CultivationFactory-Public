"""Relevant-only scratch measurement requested by the RETRYLOOP1 lead review.

Keep the corrected lead probe in a subprocess: its instrumentation cannot leak
into other tests. Fixtures, ASGI transport and all writes are synthetic/local.
"""
import json
from pathlib import Path
import subprocess
import sys


def test_scratch_events_read_probe(tmp_path, capsys):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'timings.json'
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('retryloop_read_probe_worker.py')),
         str(root), str(tmp_path / 'data'), str(output)],
        cwd=root, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    timings = json.loads(output.read_text())
    assert [read['kind'] for read in timings['reads']] == ['idle-cold', 'with-menu', 'idle-warm']
    assert all(read['event_rows'] for read in timings['reads'])
    # Measurements, not latency assertions: the Event-based HTTP regression
    # owns the correctness check. Emit evidence even with pytest's quiet capture.
    with capsys.disabled():
        print('\nRETRYLOOP1F1_READ_PROBE ' + json.dumps(timings, sort_keys=True), flush=True)
