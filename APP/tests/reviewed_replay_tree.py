"""Read-only replay control: apply a frozen reviewed patch to a baseline tree.

Used by the LoS stock guard and synthetic repository tests. Only a temporary
index and Git objects are written, both under the caller's scratch: the
repository's own .git (read-only in the test jail, and shared by every lane) is
only read, as an alternate object store. No ref, checkout, or live resource
changes. The caller owns the patch's approval and its immutable digest.
"""
import os
from pathlib import Path
import subprocess


def replay_env(repo, objects):
    """Git's environment for a reviewed replay: new objects go to OBJECTS, the repository's objects are read as an
    alternate (2026-10-25: `git apply --cached --3way` wrote blobs into the shared .git, which the jail makes
    read-only, and every stock capture of a reviewed patch failed). Read the patched tree with this same env."""
    objects = Path(objects).resolve()
    objects.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OBJECT_DIRECTORY=str(objects),
               GIT_ALTERNATE_OBJECT_DIRECTORIES=str(common_git_dir(repo) / 'objects'),
               GIT_OPTIONAL_LOCKS='0')
    return env


def common_git_dir(repo):
    """The repository's shared Git directory, read from its .git entry: a folder, or a linked work folder's "gitdir:"
    file whose commondir names the shared one. No Git command: this needs no history."""
    dotgit = Path(repo) / '.git'
    if dotgit.is_dir():
        return dotgit.resolve()
    text = dotgit.read_text() if dotgit.is_file() else ''
    if not text.startswith('gitdir:'):
        raise RuntimeError(f'reviewed replay: no git dir for {repo}')
    gitdir = (Path(repo) / text[len('gitdir:'):].strip()).resolve()
    commondir = gitdir / 'commondir'
    return (gitdir / commondir.read_text().strip()).resolve() if commondir.is_file() else gitdir


def patched_tree(repo, revision, patch, scratch, objects):
    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    index = scratch / 'reviewed.index'
    # Git requires an absent index initially, not an empty file.
    if index.exists():
        raise ValueError(f'replay index already exists: {index}')
    env = replay_env(repo, objects)
    env.update(GIT_INDEX_FILE=str(index))
    def git(*args):
        result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(f'reviewed replay patch failed: {result.stderr}')
        return result.stdout.strip()
    try:
        git('read-tree', revision)
        git('apply', '--cached', '--3way', str(Path(patch).resolve()))
        return git('write-tree')
    finally:
        index.unlink(missing_ok=True)
        index.with_name(index.name + '.lock').unlink(missing_ok=True)
