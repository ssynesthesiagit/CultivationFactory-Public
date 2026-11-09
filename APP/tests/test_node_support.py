"""A payload given to run_node_test reaches the node --test file, so its cases run instead of skipping.

Without an isolation flag (Node 20) `node --test` runs each file in a child process that never gets the caller's
stdin. The fixture must still arrive; otherwise the file's skip guard reports a skip and the Python caller passes.
"""
import json
from pathlib import Path

from tests import node_support
from tests.node_support import run_node_test

STDIN_HELPER = Path(__file__).with_name('node_stdin.mjs')


def test_payload_reaches_node_test_file_without_isolation_flag(tmp_path, monkeypatch):
    # Node 20 shape: no in-process isolation flag, so the file runs in its own child process.
    monkeypatch.setattr(node_support, 'isolation_flag', lambda node='node': None)
    script = tmp_path / 'payload_probe.test.mjs'
    script.write_text(
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        f"import {{readStdinPayload}} from {json.dumps(STDIN_HELPER.as_uri())};\n"
        "const input = await readStdinPayload();\n"
        "test('payload reaches the child', () => { assert.equal(JSON.parse(input).answer, 42); });\n",
        encoding='utf-8')
    result = run_node_test(json.dumps({'answer': 42}), '--test-reporter=tap', str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ok 1 - payload reaches the child' in result.stdout
    assert '# SKIP' not in result.stdout
