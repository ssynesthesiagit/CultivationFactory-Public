"""Freeze queued test inputs in both full-history and exported Git snapshots.

This fixture needs only the current checkout, never a historical commit or an
owner document: it records the checkout's own bytes (every tracked file) and
the working-tree status, so a source edit or commit that lands during the run
is caught by comparing bytes, not by naming a revision. Its manifest records
source identity, not runtime game data.

The pre-run gate covers edited tracked files, the same set the manifest hashes:
a public CI checkout writes its own untracked run artifacts beside the sources,
and those are never part of the checkpoint.
"""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope='module', autouse=True)
def source_checkpoint(tmp_path_factory, request):
    root = Path(__file__).resolve().parents[2]

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True)

    def hashes():
        names = git('ls-files', '-z').split('\0')
        return {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in names
            if name and (root / name).is_file()
        }

    dirty = git('status', '--short', '--untracked-files=no')
    before = hashes()
    manifest = tmp_path_factory.getbasetemp() / (
        'source-' + request.module.__name__.rsplit('.', 1)[-1] + '.json')
    manifest.write_text(json.dumps({'status': dirty, 'sha256': before}, indent=2) + '\n')
    assert not dirty, ('Commit the source checkpoint before its queued verification starts: '
                       + ' | '.join(dirty.splitlines()[:8]))
    yield
    assert hashes() == before, 'Source changed during queued verification; rerun this checkpoint.'
