"""Compact JUnit results shared by the public runner and private collector."""
import xml.etree.ElementTree as ET


def first_line(value):
    return next((line.strip()[:500] for line in (value or '').splitlines() if line.strip()), '')


def junit_results(path, selected):
    """Retain every testcase, including setup errors and skips; never infer PASS."""
    root = ET.parse(path).getroot()
    results = []
    stems = {p.removeprefix('APP/').removesuffix('.py').replace('/', '.'): p for p in selected}
    for case in root.iter('testcase'):
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


def file_results(selected, tests, exit_code):
    """Collection/crash/missing-report files remain visible, including empty files."""
    rows = []
    for file in selected:
        statuses = {t['status'] for t in tests if t['file'] == file}
        status = next((s for s in ('ERROR', 'FAIL', 'PASS', 'SKIP') if s in statuses),
                      'NOT_RUN' if exit_code else 'NO_TESTS')
        error = next((t['error'] for t in tests if t['file'] == file and t['error']), '')
        rows.append({'file': file, 'status': status, 'error': error})
    return rows
