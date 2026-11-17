"""S0 measured count ceilings. No shared-runner wall-time assertions.

test_tabletop_speed retains its single-load/candidate-reuse assertions; these
cases add dispatch budgets and cover the other named request paths.
"""
import json
import pytest
from tools.speedbench_scenarios import SCENARIOS, build, sample, mantis_fixture

# Measured on b65b21abde plus S0; loads, builds, dispatches, subscriber calls.
BUDGETS = {
    'toggle': (2, 1, 35088, 168609),  # measured: (2, 1, 35088, 168609)
    'melee': (2, 1, 32397, 154863),  # measured: (2, 1, 32397, 154863)
    'area': (4, 7, 720552, 3519432),  # measured: (4, 7, 720552, 3519432)
    'movement': (1, 2, 51761, 287364),  # measured: (1, 2, 51761, 287364)
    'ai_step': (1, 3, 89595, 371003),  # measured: (1, 3, 89595, 371003)
    'ai_sequence': (7, 5, 181201, 668318),  # measured: (7, 5, 181201, 668318)
    'events': (1, 0, 213, 4526),  # measured: (1, 0, 213, 4526)
    'state': (1, 1, 28404, 123215),  # measured: (1, 1, 28404, 123215)
    'cold_50': (1, 0, 199, 4500),  # measured: (1, 0, 199, 4500)
    'cold_150': (1, 0, 199, 4500),  # measured: (1, 0, 199, 4500)
    'cold_300': (1, 0, 199, 4500),  # measured: (1, 0, 199, 4500)
    'mantis_native': (2, 2, 105833, 470614),  # measured: (2, 2, 105833, 470614)
}


@pytest.fixture(scope='module')
def small(tmp_path_factory):
    root = tmp_path_factory.mktemp('speed-budgets')
    mid, points = build(root/'data', actors=2, records=0)
    return root, mid, points[0][0]


@pytest.mark.parametrize('scenario', (*SCENARIOS, 'mantis_native'))
def test_speed_budget(small, tmp_path, scenario, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    root, mid, source = small
    if scenario == 'mantis_native':
        source = tmp_path/'mantis'
        mid = mantis_fixture(source)
    row = sample(source, tmp_path/'sample', mid, scenario, counted=True)
    print('SPEEDBUDGET', scenario, json.dumps(row, sort_keys=True))
    loads, candidates, dispatches, subscriber_calls = BUDGETS[scenario]
    assert row['loads'] <= loads, (scenario, 'loads', row)
    assert row['candidates'] <= candidates, (scenario, 'candidates', row)
    assert row['dispatches'] <= dispatches, (scenario, 'dispatches', row)
    assert row['subscriber_calls'] <= subscriber_calls, (scenario, 'subscriber_calls', row)


def test_whole_request_and_ai_sequence_metrics(tmp_path, monkeypatch):
    from tests.test_tabletop_speed import _fight, _to_the_humans_turn
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = _fight(tmp_path)
    state, after = _to_the_humans_turn(table, mid)
    menu = state['menu']
    table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], after, prepare_only=True)
    table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], after)
    combat.local_run(mid, maximum_steps=1)
    operations = [json.loads(line)['operation'] for line in combat.performance_path.read_text().splitlines()]
    assert operations.count('table_action') == 2
    assert operations.count('ai_sequence') == 1
