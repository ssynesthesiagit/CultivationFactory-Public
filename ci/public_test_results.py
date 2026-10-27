"""Compact JUnit results shared by the public runner and private collector."""
import math
import xml.etree.ElementTree as ET


def first_line(value):
    return next((line.strip()[:500] for line in (value or '').splitlines() if line.strip()), '')


def _stems(selected):
    return {p.removeprefix('APP/').removesuffix('.py').replace('/', '.'): p for p in selected}


def _case_file(case, selected, stems):
    """The selected file a JUnit testcase belongs to, or '' when it cannot be attributed."""
    classname = case.get('classname', '')
    filename = case.get('file', '').removeprefix('./')
    file = next((p for p in selected if filename in (p, p.removeprefix('APP/'))), '') if filename else ''
    if not file:
        file = next((p for stem, p in sorted(stems.items(), key=lambda row: -len(row[0]))
                     if classname == stem or classname.startswith(stem + '.')), '')
    if not file:
        # pytest collection errors name the module path instead of setting
        # classname; keep their file attribution rather than losing it.
        name = case.get('name', '')
        file = next((p for p in selected if name in (p, p.removeprefix('APP/'))), '')
    return file


def junit_results(path, selected):
    """Retain every testcase, including setup errors and skips; never infer PASS."""
    root = ET.parse(path).getroot()
    results = []
    stems = _stems(selected)
    for case in root.iter('testcase'):
        classname = case.get('classname', '')
        file = _case_file(case, selected, stems)
        problem = case.find('error')
        status = 'ERROR' if problem is not None else 'PASS'
        if problem is None:
            problem = case.find('failure')
            if problem is not None:
                status = 'FAIL'
        if case.find('skipped') is not None:
            status = 'SKIP'
        error = first_line(problem.get('message') or problem.text) if problem is not None else ''
        results.append({'file': file, 'test': '::'.join(filter(None, (classname, case.get('name')))),
                        'status': status, 'error': error})
    return results


def _seconds(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def junit_seconds(path, selected, single=None):
    """Summed per-testcase JUnit time for each selected file: {file: seconds}.

    single: a node job runs one file per process, so every case in its report counts toward that file.
    """
    root = ET.parse(path).getroot()
    seconds = {}
    stems = _stems(selected)
    for case in root.iter('testcase'):
        file = single or _case_file(case, selected, stems)
        if file:
            seconds[file] = seconds.get(file, 0.0) + _seconds(case.get('time'))
    return {file: round(total, 3) for file, total in seconds.items()}


def file_results(selected, tests, exit_code, seconds=None):
    """No attributed cases means NOT_RUN, even after a successful process exit.

    Intentionally empty files cannot satisfy this gate; use an explicit skipped
    testcase when a selected file has no runnable cases in this environment.
    seconds: {file: JUnit seconds}; a file without a JUnit report (not run, or its process was stopped) records
    None, unknown: never 0, which would make the slowest unfinished files look free to the shard packing.
    """
    seconds = seconds or {}
    rows = []
    for file in selected:
        statuses = {t['status'] for t in tests if t['file'] == file}
        status = next((s for s in ('ERROR', 'FAIL', 'PASS', 'SKIP') if s in statuses),
                      'NOT_RUN')
        error = next((t['error'] for t in tests if t['file'] == file and t['error']), '')
        rows.append({'file': file, 'status': status, 'error': error,
                     'seconds': round(seconds[file], 3) if file in seconds else None})
    return rows
