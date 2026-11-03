"""Public synthetic subprocess tests; no project history or private fixtures."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
from types import SimpleNamespace

import pytest

from tests.reviewed_replay_tree import patched_tree, replay_env


@pytest.mark.parametrize('conflict', [False, True])
def test_reviewed_patch_uses_temporary_index_and_fails_closed(tmp_path, monkeypatch, conflict):
    repo = tmp_path / 'synthetic'
    (repo / '.git').mkdir(parents=True)
    patch = tmp_path / 'approved.patch'
    patch.write_text('synthetic reviewed delta')
    scratch = tmp_path / 'scratch'
    objects = tmp_path / 'objects'
    calls = []

    def fake_git(command, **kwargs):
        calls.append((command, kwargs))
        index = Path(kwargs['env']['GIT_INDEX_FILE'])
        index.write_text('fake index')
        if 'apply' in command and conflict:
            return SimpleNamespace(returncode=1, stdout='', stderr='conflicting reviewed geometry')
        return SimpleNamespace(returncode=0, stdout='approved-tree\n' if 'write-tree' in command else '', stderr='')

    monkeypatch.setenv('GIT_WORK_TREE', '/must-not-use-this')
    monkeypatch.setattr('tests.reviewed_replay_tree.subprocess.run', fake_git)
    if conflict:
        with pytest.raises(RuntimeError, match='conflicting reviewed geometry'):
            patched_tree(repo, 'current-main', patch, scratch, objects)
    else:
        assert patched_tree(repo, 'current-main', patch, scratch, objects) == 'approved-tree'
    assert [c[0][3:] for c in calls] == [
        ['read-tree', 'current-main'],
        ['apply', '--cached', '--3way', str(patch)],
        *([] if conflict else [['write-tree']]),
    ]
    for _, kwargs in calls:
        assert kwargs['env']['GIT_INDEX_FILE'] == str(scratch / 'reviewed.index')
        assert kwargs['env']['GIT_OBJECT_DIRECTORY'] == str(objects.resolve())
        assert kwargs['env']['GIT_ALTERNATE_OBJECT_DIRECTORIES'] == str((repo / '.git').resolve() / 'objects')
        assert 'GIT_WORK_TREE' not in kwargs['env']
    assert not list(scratch.iterdir()), 'success and conflict both clean the temporary index'
    assert [p.name for p in repo.iterdir()] == ['.git'] and not list((repo / '.git').iterdir()), \
        'never alter the checkout, refs, or its normal index'


def test_reviewed_patch_never_overwrites_an_existing_index(tmp_path, monkeypatch):
    index = tmp_path / 'reviewed.index'
    index.write_text('another operation')
    def unexpected_git(*args, **kwargs):
        pytest.fail('existing scratch index must fail before invoking Git')
    monkeypatch.setattr('tests.reviewed_replay_tree.subprocess.run', unexpected_git)
    with pytest.raises(ValueError, match='already exists'):
        patched_tree(tmp_path, 'current-main', tmp_path / 'approved.patch', tmp_path, tmp_path / 'objects')
    assert index.read_text() == 'another operation'


@pytest.mark.skipif(shutil.which('git') is None, reason='needs git')
def test_a_read_only_repository_object_store_is_never_written(tmp_path):
    """2026-10-25 (int/20261025o): in the test jail the shared .git is read-only, and `git apply --cached --3way`
    failed with "unable to create temporary file: Read-only file system". The replay's objects go to its own store.
    A throwaway repository with one commit made by plumbing; the patch is written out (no repository history)."""
    repo = tmp_path / 'repo'
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t',
               GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
    git = lambda *a, extra=None: subprocess.run(['git', '-C', str(repo), *a], env={**env, **(extra or {})}, check=True,
                                                capture_output=True, text=True).stdout.strip()
    repo.mkdir()
    git('init', '-q')
    (repo / 'APP').mkdir()
    (repo / 'APP' / 'map.json').write_text('{"wall": 1}\n')
    git('add', '.')
    base = git('commit-tree', git('write-tree'), '-m', 'base')
    patch = tmp_path / 'reviewed.patch'
    patch.write_text('--- a/APP/map.json\n+++ b/APP/map.json\n@@ -1 +1 @@\n-{"wall": 1}\n+{"wall": 2}\n')
    store = repo / '.git' / 'objects'
    modes = {p: p.stat().st_mode for p in (store, *store.rglob('*'))}
    for p in modes:
        p.chmod(modes[p] & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        objects = tmp_path / 'replay-objects'
        tree = patched_tree(repo, base, patch, tmp_path / 'scratch', objects)
        out = tmp_path / 'out'
        read = {**replay_env(repo, objects), 'GIT_INDEX_FILE': str(tmp_path / 'read.index')}
        git('read-tree', tree, extra=read)
        git('checkout-index', '-a', f'--prefix={out}/', extra=read)
        assert (out / 'APP' / 'map.json').read_text() == '{"wall": 2}\n'
        assert set(store.rglob('*')) == set(modes) - {store}, 'nothing new in the repository object store'
    finally:
        for p, mode in modes.items():
            p.chmod(mode)
