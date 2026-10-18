"""Deterministic budgets; no clocks in assertions, providers or browsers."""
import json
import os
from pathlib import Path

import pytest

from tools.perf_suite import (BUDGET_FILE, REQUIRED, Suite, baseline_budgets, offline,
                              copy_fight, load_budgets, owned_scratch, run, safe_scratch, violations)
from tools.perf_suite import stage2_summary


def test_guard_rejects_one_extra_call_and_ignores_wall_time(tmp_path):
    suite = Suite(tmp_path / 'counts.json')
    suite.measure('fixture', 'operation', lambda: None)
    row = suite.rows[0]
    row['counters'] = {'legal_candidates': 2}
    budgets = {'fixture/operation': {'legal_candidates': 2}}
    assert not violations(suite.rows, budgets)
    row['wall_ms'] = 10**12
    assert not violations(suite.rows, budgets)
    row['counters']['legal_candidates'] += 1
    assert 'legal_candidates=3 > budget 2' in violations(suite.rows, budgets)[0]
    assert violations([], budgets)
    row['status'] = 'ERROR'
    assert violations(suite.rows, budgets)


def test_scratch_rejects_existing_nested_live_and_ram_paths(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for bad in (source, source / 'nested', tmp_path, Path('/tmp/perfsuite1')):
        with pytest.raises(ValueError):
            safe_scratch(source, bad)


def test_copy_only_installed_ids_and_cleanup_on_failure(tmp_path):
    import base64
    source = tmp_path / 'source'
    mid = 'match:fixture'
    folder = 'm1_' + base64.urlsafe_b64encode(mid.encode()).decode().rstrip('=')
    fight = source / 'Combat/Matches' / folder
    fight.mkdir(parents=True)
    metadata = json.dumps({'participant_control_modes': {'actor:factory.aaaaaaaa': 'MANUAL'},
                           'display_name': 'long descriptive text ' * 100})
    (fight / 'FactoryIntegration.json').write_text(metadata)
    installation = source / 'portable_characters/aaaaaaaa'
    installation.mkdir(parents=True)
    (installation / 'current.zip').write_bytes(b'fixture')
    copied = tmp_path / 'copied'
    with pytest.raises(RuntimeError, match='failure after copy'):
        with owned_scratch(copied):
            copy_fight(source, copied / 'data', mid)
            assert (copied / 'data/portable_characters/aaaaaaaa/current.zip').read_bytes() == b'fixture'
            raise RuntimeError('failure after copy')
    assert not copied.exists()
    assert (fight / 'FactoryIntegration.json').read_text() == metadata


def test_failed_phase_keeps_codes_without_private_payload(tmp_path):
    suite = Suite(tmp_path / 'failure.json')
    result, _ = suite.measure('fixture', 'blocked', lambda: {
        'status': 'NEEDS_REVIEW', 'blockers': [{'code': 'FIXTURE_BLOCKER'}],
        'private_sheet': 'must-not-be-retained'}, expected=lambda r: False)
    assert result is None
    assert suite.rows[0]['outcome']['blocker_codes'] == ['FIXTURE_BLOCKER']
    assert 'must-not-be-retained' not in suite.output.read_text()


def test_failed_compile_cannot_calibrate_partial_stage2(tmp_path):
    def _stage2_commit():
        raise ValueError('incomplete Stage 2')
    suite = Suite(tmp_path / 'partial-stage2.json')
    result, stats = suite.measure('factory', 'compile', _stage2_commit)
    assert result is None
    stage2_summary(suite, stats, complete=False)
    assert suite.rows[-1]['status'] == 'PARTIAL'
    assert 'factory/stage2' not in baseline_budgets(suite.rows)


def test_offline_blocks_model_sockets():
    import socket
    with offline():
        with pytest.raises(RuntimeError, match='network access prohibited'):
            socket.socket.connect(None, ('127.0.0.1', 11448))
        with pytest.raises(RuntimeError, match='network access prohibited'):
            socket.socket.connect_ex(None, ('127.0.0.1', 8765))


def test_profiler_counts_real_application_work_without_replacing_engine(tmp_path):
    from tests.h1_support import duel
    engine = duel([])
    suite = Suite(tmp_path / 'real-counts.json')
    suite.measure('fixture', 'menu', engine.legal_candidates)
    counters = suite.rows[0]['counters']
    assert counters['legal_candidates'] >= 1 and counters['application_calls'] > 0
    budget = {'fixture/menu': dict(counters)}
    assert not violations(suite.rows, budget)
    suite.measure('fixture', 'menu', lambda: (engine.legal_candidates(), engine.legal_candidates()))
    assert any('legal_candidates' in issue for issue in violations([suite.rows[-1]], budget))


def test_whole_game_work_budgets(tmp_path):
    """Small real table + real provider-free CL20 compile, Stage 2, finalize.

    HeavyQ selectors may run this once with PERF_SUITE_CALIBRATE pointing at
    an evidence file. Normal CI compares committed budgets and cannot bless
    its own regression. Owner saves are an additional explicit opt-in below.
    """
    scratch = tmp_path / 'suite-data'
    rows = run(tmp_path / 'suite.json', scratch)
    assert REQUIRED - {'reaction_open', 'reaction_answer'} <= {
        r['path'] for r in rows if r['scenario'] == 'small'}
    assert {'compile', 'stage2', 'finalize', 'character_sheet'} <= {
        r['path'] for r in rows if r['scenario'] == 'factory'}
    candidate = os.environ.get('PERF_SUITE_CALIBRATE')
    if candidate:
        Path(candidate).write_text(json.dumps(baseline_budgets(rows), indent=2, sort_keys=True) + '\n')
        assert all(row['status'] == 'PASS' for row in rows), [(r['path'], r.get('error')) for r in rows if r['status'] != 'PASS']
    else:
        budgets = load_budgets()
        assert not violations(rows, budgets), '\n'.join(violations(rows, budgets))
    assert not scratch.exists(), 'Disposable database/fight copy was retained'


@pytest.mark.skipif(not os.environ.get('PERF_SUITE_SOURCE'), reason='Explicit offline owner-data benchmark')
def test_owner_saved_fight_budgets(tmp_path):
    matches = os.environ['PERF_SUITE_MATCH_IDS'].split(',')
    rows = run(tmp_path / 'owner-suite.json', tmp_path / 'owner-data', Path(os.environ['PERF_SUITE_SOURCE']),
               matches=matches, factory=False)
    budgets = load_budgets(Path(os.environ.get('PERF_SUITE_OWNER_BUDGETS', str(BUDGET_FILE))), source=True, factory=False)
    assert not violations(rows, budgets), '\n'.join(violations(rows, budgets))
