"""Task-owned full stock capture, optionally loading changed sources from Git.

The baseline uses a sparse resource root: unchanged rules/assets are symlinks,
changed built-in map JSON is read from the base commit. No extra project copy,
live fight, browser or engine monkey-patch is used.
"""
import builtins
import importlib.abc
import importlib.machinery
import io
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]


def revision_sources(revision, scratch):
    """Load APP modules and resources from one Git tree.

    In particular, do not mix unchanged historical combat modules with new
    current modules: cross-branch imports can otherwise fail before a replay.
    """
    repo = APP.parent
    root = scratch / 'base-resources'
    tree = subprocess.check_output(['git', 'ls-tree', '-rz', '--full-tree', revision, '--', 'APP'],
                                   cwd=repo)
    entries = {}
    for record in tree.split(b'\0'):
        if not record:
            continue
        metadata, path = record.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        if kind == 'blob':
            entries[path.decode()] = (mode, oid)
    blobs = {path: subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=repo)
             for path, (_mode, oid) in entries.items()}

    app_roots = {path.split('/')[1] for path in blobs
                 if path.startswith('APP/') and path.endswith('.py')}

    def relative(path):
        for base in (root, APP):
            try:
                return Path(path).resolve().relative_to(base.resolve()).as_posix()
            except (ValueError, TypeError, OSError):
                pass
        return None

    original_open = builtins.open

    def tree_open(file, mode='r', *args, **kwargs):
        rel = relative(file)
        key = f'APP/{rel}' if rel else None
        if key in blobs and not any(flag in mode for flag in 'wax+'):
            encoding = kwargs.get('encoding')
            encoding = 'utf-8' if encoding in (None, 'locale') else encoding
            return io.BytesIO(blobs[key]) if 'b' in mode else io.StringIO(blobs[key].decode(encoding))
        return original_open(file, mode, *args, **kwargs)

    builtins.open = tree_open
    Path.open = lambda self, mode='r', *args, **kwargs: tree_open(self, mode, *args, **kwargs)

    class GitTree(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.partition('.')[0] not in app_roots:
                return None
            rel = fullname.replace('.', '/')
            package, source = f'APP/{rel}/__init__.py', f'APP/{rel}.py'
            if package in blobs:
                is_package, key = True, package
            elif source in blobs:
                is_package, key = False, source
            else:
                raise ModuleNotFoundError(f'{fullname} is absent from Git tree {revision}')
            spec = importlib.machinery.ModuleSpec(fullname, self, is_package=is_package)
            spec.origin = str(repo / key)
            if is_package:
                spec.submodule_search_locations = [str(repo / f'APP/{rel}')]
            return spec

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            key = module.__spec__.origin.removeprefix(str(repo) + '/')
            module.__file__ = str(repo / key)
            if module.__spec__.submodule_search_locations is not None:
                module.__path__ = [str(repo / key.rsplit('/', 1)[0])]
            if key.startswith('APP/combat/ext/'):
                # The registry discovers providers by listing its package
                # directory. Point that listing at baseline-only metadata,
                # while this loader still executes exact Git blob bytes.
                module.__file__ = str(root / key.removeprefix('APP/'))
                if module.__spec__.submodule_search_locations is not None:
                    module.__path__ = [str(Path(module.__file__).parent)]
            exec(compile(blobs[key], module.__file__, 'exec'), module.__dict__)

    sys.meta_path.insert(0, GitTree())
    (root / 'combat/maps').mkdir(parents=True)
    for name in ('authority', 'static', 'fixtures', *(p.name for p in APP.glob('combat_gate*') if p.is_dir())):
        if any(path.startswith(f'APP/{name}/') for path in entries):
            (root / name).symlink_to(APP / name, target_is_directory=True)
    for path in (APP / 'combat').iterdir():
        if path.name not in {'maps', 'ext', '__pycache__'} and (APP / 'combat' / path.name).exists():
            (root / 'combat' / path.name).symlink_to(path, target_is_directory=path.is_dir())
    for name in entries:
        if name.startswith('APP/combat/ext/') and name.endswith('.py'):
            metadata = root / name.removeprefix('APP/')
            metadata.parent.mkdir(parents=True, exist_ok=True)
            metadata.touch()
    for name, (_mode, _oid) in entries.items():
        prefix = 'APP/combat/maps/'
        if name.startswith(prefix) and name.endswith('.json'):
            (root / 'combat' / name[len('APP/combat/'):]).write_bytes(blobs[name])
    return root


def working_tree_sources():
    """Use the current checkout for the candidate arm's code and resources."""
    return APP


def main(argv=None):
    """Run the stock capture, using the working checkout when revision is omitted."""
    from tests.queue_guard import require_test_queue

    require_test_queue()
    argv = sys.argv[1:] if argv is None else argv
    scratch, seed = Path(argv[0]), argv[1]
    revision = argv[2] if len(argv) > 2 else None
    if len(argv) > 3:
        from tests.reviewed_replay_tree import patched_tree
        revision = patched_tree(APP.parent, revision, argv[3], scratch / 'reviewed-tree')
    # Load this read-only diagnostic helper before selecting historical sources;
    # old trees need not contain it. The capture itself still uses that exact tree.
    from tests.ai_stock_audit import journal_decisions, write_decision_evidence
    root = revision_sources(revision, scratch) if revision else working_tree_sources()
    from tests import test_save_reload_equivalence as stock
    stock.ROOT = root  # Test helper's resource root; production classes remain untouched.
    saved = {}
    def start(data):
        session, match_id = stock._start_stock(data, seed)
        saved['match_dir'] = session.store.match_dir
        return session, match_id
    capture = stock._play(scratch / 'fight', start)
    def rows(name):
        return [json.loads(line) for line in (saved['match_dir'] / name).read_text().splitlines()]
    decisions = journal_decisions(rows('Journal.ndjson'), rows('ControllerJournal.ndjson'))
    write_decision_evidence(scratch, seed, decisions)
    print(stock._bytes_of(capture))


if __name__ == '__main__':
    main()
