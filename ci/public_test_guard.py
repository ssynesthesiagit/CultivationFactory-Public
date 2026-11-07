"""pytest plugin for public CI shards: a per-test time limit and a progress log (2026-10-20).

sweep-20261020-full lost 6 of its first 12 pytest shards to the 90-minute job timeout. A cancelled job uploads nothing,
so every test in those shards went unreported, including the ones that had passed. With this plugin:
- a test still running after PUBLIC_TEST_LIMIT_S fails with TestTimeout and the shard carries on (SIGALRM in the
  main thread; a hang inside C code that the alarm cannot interrupt ends the process 120 s later, with every
  thread's stack on stderr);
- every finished test is appended to PUBLIC_TEST_PROGRESS as one JSON line as it ends, so a shard that is killed
  at its deadline still reports what ran (public_test_shard.progress_results).
"""
import faulthandler
import json
import os
import signal

import pytest

LIMIT = float(os.environ.get('PUBLIC_TEST_LIMIT_S') or 0)
LOG = os.environ.get('PUBLIC_TEST_PROGRESS')


class TestTimeout(Exception):
    __test__ = False


def _alarm(signum, frame):
    raise TestTimeout(f'TestTimeout: still running after {LIMIT:.0f} s (public CI per-test limit; a hang?)')


def _log(row):
    if LOG:
        with open(LOG, 'a') as stream:
            stream.write(json.dumps(row) + '\n')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _log({'start': item.nodeid})
    old = None
    if LIMIT > 0:
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, LIMIT)
        faulthandler.dump_traceback_later(LIMIT + 120, exit=True)
    try:
        yield
    finally:
        if LIMIT > 0:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
            faulthandler.cancel_dump_traceback_later()


def pytest_runtest_logreport(report):
    if report.when == 'call' or report.outcome != 'passed':
        error = ''
        if report.failed and report.longrepr:
            lines = [line for line in str(report.longrepr).splitlines() if line.strip()]
            error = (lines[-1] if lines else '')[:500]
        _log({'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome, 'error': error})
