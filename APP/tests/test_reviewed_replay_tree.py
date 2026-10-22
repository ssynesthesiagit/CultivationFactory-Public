"""Public synthetic subprocess tests; no project history or private fixtures."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.reviewed_replay_tree import patched_tree


@pytest.mark.parametrize('conflict', [False, True])
def test_reviewed_patch_uses_temporary_index_and_fails_closed(tmp_path, monkeypatch, conflict):
    repo = tmp_path / 'synthetic'
    repo.mkdir()
    patch = tmp_path / 'approved.patch'
    patch.write_text('synthetic reviewed delta')
    scratch = tmp_path / 'scratch'
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
            patched_tree(repo, 'current-main', patch, scratch)
    else:
        assert patched_tree(repo, 'current-main', patch, scratch) == 'approved-tree'
    assert [c[0][3:] for c in calls] == [
        ['read-tree', 'current-main'],
        ['apply', '--cached', '--3way', str(patch)],
        *([] if conflict else [['write-tree']]),
    ]
    for _, kwargs in calls:
        assert kwargs['env']['GIT_INDEX_FILE'] == str(scratch / 'reviewed.index')
        assert 'GIT_WORK_TREE' not in kwargs['env']
    assert not list(scratch.iterdir()), 'success and conflict both clean the temporary index'
    assert not list(repo.iterdir()), 'never alter the checkout, refs, or its normal index'


def test_reviewed_patch_never_overwrites_an_existing_index(tmp_path, monkeypatch):
    index = tmp_path / 'reviewed.index'
    index.write_text('another operation')
    def unexpected_git(*args, **kwargs):
        pytest.fail('existing scratch index must fail before invoking Git')
    monkeypatch.setattr('tests.reviewed_replay_tree.subprocess.run', unexpected_git)
    with pytest.raises(ValueError, match='already exists'):
        patched_tree(tmp_path, 'current-main', tmp_path / 'approved.patch', tmp_path)
    assert index.read_text() == 'another operation'
