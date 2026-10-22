"""Read-only replay control: apply a frozen reviewed patch to a baseline tree.

Used by the LoS stock guard and synthetic repository tests. Only a temporary
index and Git objects are written; no ref, checkout, or live resource changes.
The caller owns the patch's approval and its immutable digest.
"""
import os
from pathlib import Path
import subprocess


def patched_tree(repo, revision, patch, scratch):
    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    index = scratch / 'reviewed.index'
    # Git requires an absent index initially, not an empty file.
    if index.exists():
        raise ValueError(f'replay index already exists: {index}')
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_INDEX_FILE=str(index), GIT_OPTIONAL_LOCKS='0')
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
