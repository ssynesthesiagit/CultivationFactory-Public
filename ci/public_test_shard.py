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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--count', type=int, default=19)
    parser.add_argument('--node', action='store_true')
    a = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = {'kind': 'node' if a.node else 'pytest', 'shard': a.index,
              'selected': [], 'tests': [], 'files': [], 'exit_code': 1, 'error': ''}
    scratch = Path('/var/tmp/public-test-pytest')
    xml = root / 'result.xml'
    try:
        files = [p for p in requested_files(root) if p.endswith(('.mjs', '.js') if a.node else '.py')]
        selected = sorted(files) if a.node else select(files, a.index, a.count)
        result['selected'] = selected
        env = dict(os.environ, PYTHONPATH=str(root / 'APP'),
                   TIANXIA_R4V_TEST_INTEGRITY_KEY_HEX=os.urandom(32).hex())
        command = (['node', '--test', '--test-reporter=junit', '--test-reporter-destination=' + str(xml)]
                   if a.node else [sys.executable, '-m', 'pytest', '-q', '--basetemp=' + str(scratch),
                                  '--junitxml=' + str(xml)])
        result['exit_code'] = 0
        # Node JUnit does not consistently provide source filenames. One
        # process per file preserves attribution for every nested testcase.
        groups = [[p] for p in selected] if a.node else ([selected] if selected else [])
        for group in groups:
            xml.unlink(missing_ok=True)
            code = subprocess.call([*command, *(p.removeprefix('APP/') for p in group)],
                                   cwd=root / 'APP', env=env)
            result['exit_code'] = result['exit_code'] or code
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
