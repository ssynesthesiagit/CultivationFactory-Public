"""Run one planned public Python shard or the requested Node tests."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_test_results import file_results, first_line, junit_results


def select(files, index, count):
    if not 0 <= index < count:
        raise ValueError('invalid shard')
    return sorted(p for p in files if int(hashlib.sha256(p.encode()).hexdigest(), 16) % count == index)


def requested_files(root):
    qualified = json.loads((root / 'PUBLIC_TEST_FILES.json').read_text())
    if len(qualified) != len(set(qualified)) or any(
        not p.startswith('APP/tests/') or '..' in Path(p).parts or not (root / p).is_file()
        for p in qualified
    ):
        raise ValueError('invalid or missing qualified test path')
    request = root / 'PUBLIC_TEST_REQUEST.txt'
    if not request.exists():
        return qualified
    files = [line.strip() for line in request.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not files or len(files) != len(set(files)) or set(files) - set(qualified):
        raise ValueError('test request must be a nonempty unique subset of qualified files')
    return sorted(files)


# 2026-10-20 (sweep-20261020-full: 6 of 12 first-wave shards and the node job hit their job timeouts and uploaded
# nothing). Per-test limit and shard deadline, both under the workflow's job timeouts (pytest 90 min, node 60 min).
TEST_LIMIT_S = 1200          # slowest passing CI test seen ~26 min on loaded Tabik; GitHub runners are not slower
SHARD_DEADLINE_S = 80 * 60   # pytest stops here and the shard reports what ran (public_test_guard progress log)
NODE_FILE_LIMIT_S = 600


def _module_class(nodeid):
    """'tests/x.py::Cls::test_a' -> ('APP/tests/x.py', 'tests.x.Cls', 'test_a'), the junit classname/name pair."""
    parts = nodeid.split('::')
    module = parts[0].removesuffix('.py').replace('/', '.')
    return 'APP/' + parts[0], '.'.join([module, *parts[1:-1]]), parts[-1]


def progress_results(log, selected):
    """Test results from public_test_guard's progress log when pytest produced no JUnit report (killed at the
    deadline, or ended by the hang fallback). The test that was running when it stopped is an ERROR."""
    rank = {'PASS': 0, 'SKIP': 1, 'FAIL': 2, 'ERROR': 3}
    rows, started, finished = {}, [], set()
    try:
        lines = log.read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if 'start' in row:
            started.append(row['start'])
            continue
        finished.add(row.get('nodeid'))
        status = {'passed': 'PASS', 'skipped': 'SKIP'}.get(row.get('outcome'),
                                                         'FAIL' if row.get('when') == 'call' else 'ERROR')
        old = rows.get(row.get('nodeid'))
        if old is None or rank[status] > rank[old['status']]:
            rows[row.get('nodeid')] = {'status': status, 'error': row.get('error') or ''}
    for nodeid in started:
        if nodeid not in finished:
            rows[nodeid] = {'status': 'ERROR', 'error': 'the shard stopped while this test ran (deadline or a hang)'}
    tests = []
    for nodeid, row in rows.items():
        file, classname, name = _module_class(nodeid)
        if file in selected:
            tests.append({'file': file, 'test': '::'.join(filter(None, (classname, name))), **row})
    return tests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--count', type=int, default=None)
    parser.add_argument('--node', action='store_true')
    a = parser.parse_args()
    if a.count is None:
        a.count = 1 if a.node else 19
    root = Path(__file__).resolve().parents[1]
    result = {'kind': 'node' if a.node else 'pytest', 'shard': a.index,
              'selected': [], 'tests': [], 'files': [], 'exit_code': 1, 'error': ''}
    scratch = Path('/var/tmp/public-test-pytest')
    xml = root / 'result.xml'
    try:
        files = [p for p in requested_files(root) if p.endswith(('.mjs', '.js') if a.node else '.py')]
        selected = select(files, a.index, a.count)
        result['selected'] = selected
        progress = root / 'progress.jsonl'
        progress.unlink(missing_ok=True)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / 'APP'), str(root / 'ci'))),
                   TIANXIA_R4V_TEST_INTEGRITY_KEY_HEX=os.urandom(32).hex(),
                   PUBLIC_TEST_LIMIT_S=str(TEST_LIMIT_S), PUBLIC_TEST_PROGRESS=str(progress))
        command = (['node', '--test', '--test-reporter=junit', '--test-reporter-destination=' + str(xml)]
                   if a.node else [sys.executable, '-m', 'pytest', '-q', '-p', 'public_test_guard', '--durations=25',
                                  '--basetemp=' + str(scratch), '--junitxml=' + str(xml)])
        result['exit_code'] = 0
        # Node JUnit does not consistently provide source filenames. One
        # process per file preserves attribution for every nested testcase.
        groups = [[p] for p in selected] if a.node else ([selected] if selected else [])
        for group in groups:
            xml.unlink(missing_ok=True)
            try:
                code = subprocess.call([*command, *(p.removeprefix('APP/') for p in group)], cwd=root / 'APP', env=env,
                                       timeout=NODE_FILE_LIMIT_S if a.node else SHARD_DEADLINE_S)
            except subprocess.TimeoutExpired:
                code = 124
                if a.node:              # one hung file must not cost the job (6 public node files hung 2026-10-20)
                    xml.unlink(missing_ok=True)
                    result['tests'].append({'file': group[0], 'test': group[0].removeprefix('APP/'), 'status': 'ERROR',
                                            'error': f'TestTimeout: node --test still running after {NODE_FILE_LIMIT_S} s'})
                    result['exit_code'] = result['exit_code'] or code
                    continue
                result['error'] = f'pytest stopped at the {SHARD_DEADLINE_S // 60}-min shard deadline'
            result['exit_code'] = result['exit_code'] or code
            if not a.node and not xml.exists():
                tests = progress_results(progress, group)
                result['tests'].extend(tests)
                result['error'] = ((result['error'] or 'Test process produced no JUnit report')
                                   + f'; {len(tests)} result(s) from the progress log')
                continue
            if xml.exists():
                tests = junit_results(xml, group)
                if a.node:
                    for test in tests:
                        test['file'] = group[0]
                result['tests'].extend(tests)
            else:
                result['error'] = 'Test process produced no JUnit report'
        result['files'] = file_results(selected, result['tests'], result['exit_code'])
        if result['error'] and not result['exit_code']:
            result['exit_code'] = 1
    except Exception as exc:
        result['error'] = first_line(str(exc))
        result['exit_code'] = 1
    finally:
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if not a.node:
            shutil.rmtree(scratch, ignore_errors=True)
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
