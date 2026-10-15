"""Deterministic, task-owned base/head captures without another project copy.

Run via test_projection_replay_compatibility. The optional Git revision loads
only changed Python modules from retained Git blobs; other sources/data are
identical. No engine functions are patched and no live fight is read.
"""
import importlib.abc
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]


def _blob(revision, path):
    """One file as the retained base revision had it, or '' when that revision never had the file.

    ``combat/ext/system_bookkeeping.py`` was stubbed empty because the base this harness was written for predates it.
    From the commit that added it onward the real module is the base's, and stubbing it empty made every later base
    crash on ``gate5_service``'s ``from .ext.system_bookkeeping import recovery_provenance`` -- a failure in the
    BASELINE capture, so the comparison reported a broken base rather than a changed replay.
    """
    try:
        return subprocess.check_output(['git', 'show', f'{revision}:APP/{path}'], cwd=APP.parent,
                                       stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError:
        return ''


def use_baseline(revision):
    sources = {}
    for name, path in {
        'combat.ext': 'combat/ext/__init__.py',
        'combat.ext.astral_projection': 'combat/ext/astral_projection.py',
        'combat.gate5_service': 'combat/gate5_service.py',
    }.items():
        sources[name] = (path, subprocess.check_output(
            ['git', 'show', f'{revision}:APP/{path}'], cwd=APP.parent).decode())
    sources['combat.ext.system_bookkeeping'] = ('combat/ext/system_bookkeeping.py',
                                               _blob(revision, 'combat/ext/system_bookkeeping.py'))

    class Baseline(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in sources:
                return importlib.util.spec_from_loader(fullname, self, is_package=fullname == 'combat.ext')

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            path, code = sources[module.__name__]
            module.__file__ = str(APP / path)
            if module.__name__ == 'combat.ext':
                module.__path__ = [str(APP / 'combat/ext')]
            exec(compile(code, module.__file__, 'exec'), module.__dict__)

    sys.meta_path.insert(0, Baseline())


def capture(path, scenario):
    from combat.gate4_runner import Gate4AutonomousRunner
    if scenario.startswith('stock-'):
        session, decisions = Gate4AutonomousRunner(APP, path).run(
            match_seed=f'TIANXIA-GATE4-BENCH-{int(scenario[-1]):04d}')
    else:
        from tests.r1i_service_support import OWNER, FOE, SECOND, fixture
        combat, table, mid, _, _ = fixture(path, [], seed='PROJECTION-UNAFFECTED-TABLE')
        for actor in (OWNER, FOE, SECOND):
            combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
        for _ in range(200):
            if combat._load_session(mid).engine.state.terminal_result is not None:
                break
            result = table.auto_step(mid, 0)
            assert result['status'] == 'COMMITTED', result
        else:
            raise AssertionError('ordinary AI fight did not reach its round limit')
        session = combat._load_session(mid)
        assert session.engine.state.terminal_result is not None
        match = next(path.rglob('ControllerJournal.ndjson'))
        decisions = [json.loads(line) for line in match.read_text().splitlines()]
    assert session.mechanical.replay()['status'] == 'PASS'
    controller_journal = [json.loads(line) for line in
                          (session.store.match_dir / 'ControllerJournal.ndjson').read_text().splitlines()]
    return {'decisions': decisions,
            'controller_journal': controller_journal,
            'events': [e.model_dump(mode='json') for e in session.engine.events],
            'rolls': [r.model_dump(mode='json') for r in session.engine.rolls],
            'state': session.engine.state.model_dump(mode='json')}


if __name__ == '__main__':
    if len(sys.argv) > 3:
        use_baseline(sys.argv[3])
    print(json.dumps(capture(Path(sys.argv[1]), sys.argv[2]), sort_keys=True,
                     ensure_ascii=False, separators=(',', ':')))
