"""Synthetic S0 scenarios for table_speed_probe; no live files or providers.

Run with python -m tools.speedbench_scenarios OUTPUT_DIRECTORY. Each sample
restores the same synthetic boundary; setup/copying is outside the measurement.
Counts and uninstrumented wall timings are separate passes.
"""
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import random
import shutil
import statistics
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile

from tools.table_speed_probe import ROOT, sheet

SCENARIOS = ('toggle', 'melee', 'area', 'movement', 'ai_step', 'ai_sequence',
             'events', 'state', 'cold_50', 'cold_150', 'cold_300')


@contextmanager
def counters():
    from combat import ext, gate3_storage
    from combat.gate5_service import CombatService
    from combat.gate4_engine import Gate4ControllerEngine
    counts = Counter()
    # Adopted from Ino's a1prof/count.py: _selected counts dispatches,
    # invoke counts actual subscriber calls, run_strict estimates its fan-out.
    dispatches, subscribers = Counter(), Counter()
    hooks = {}
    def wrap(original, key):
        def call(*args, **kwargs):
            counts[key] += 1
            return original(*args, **kwargs)
        return call
    invoke, selected, strict = ext.invoke, ext._selected, ext.run_strict
    def dispatch(point, *args, **kwargs):
        subscribers[point] += 1
        return invoke(point, *args, **kwargs)
    def select(point, args):
        dispatches[point] += 1
        return selected(point, args)
    def run_strict(point, *args, **kwargs):
        dispatches['strict:' + point] += 1
        subscribers['strict:' + point] += len(ext._HOOKS.get(point, ()))
        return strict(point, *args, **kwargs)
    with patch.object(CombatService, '_load_session', wrap(CombatService._load_session, 'session_loads')), \
         patch.object(gate3_storage.Gate3Persistence, '_plan_load', wrap(gate3_storage.Gate3Persistence._plan_load, 'loads')), \
         patch.object(Gate4ControllerEngine, 'legal_candidates', wrap(Gate4ControllerEngine.legal_candidates, 'candidates')), \
         patch.object(ext, 'invoke', dispatch), \
         patch.object(ext, '_selected', select), \
         patch.object(ext, 'run_strict', run_strict):
        try:
            yield counts, hooks
        finally:
            counts['dispatches'] = sum(dispatches.values())
            counts['subscriber_calls'] = sum(subscribers.values())
            for point in sorted(dispatches.keys() | subscribers.keys()):
                d, s = dispatches[point], subscribers[point]
                hooks[point] = {'dispatches': d, 'subscriber_calls': s,
                                'subscribers_per_dispatch': s/max(d, 1)}


def build(data, *, actors=7, records=300):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    rng = random.Random(17016)
    ids = [f'speedbench-{i}' for i in range(actors)]
    for i, pid in enumerate(ids):
        doc = sheet()
        doc['identity']['display_name'] = f'Synthetic {rng.randrange(100000)}'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 100000
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100000
        doc['spheres_and_talents'] = {
            'sphere_record_ids': ['tianxia.sphere.brute', 'tianxia.sphere.sabers'] + (['tianxia.sphere.ash'] if i == 0 else []),
            'learned_talent_record_ids': ['TAL_BERSERKER_BERSERK'] + (['ASH_BASE_ASHFALL'] if i == 0 else [])}
        path = data / 'portable_characters' / pid / 'current.zip'
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, 'w') as out:
            out.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, data)
    walls = [{'id': str(i), 'shape': 'line', 'points': points,
              'blocks': 'sight_and_movement', 'height_ft': 10}
             for i, points in enumerate(([[8,1],[10,1]], [[10,1],[10,4]],
                                        [[10,4],[8,4]], [[8,4],[8,1]]))]
    combat.tabletop_maps.save({'display_name': 'Speedbench roof', 'width_squares': 12,
        'height_squares': 8, 'walls': walls, 'roofs': {'enabled': True, 'height_ft': 10},
        'starts': {'team1': [[2, y] for y in range(2, 2 + actors//2)],
                   'team2': [[3, y] for y in range(2, 2 + actors-actors//2)]}})
    mid = combat.create_factory_match(project_ids=ids[:actors//2],
        opponent_actor_ids=[FACTORY_ACTOR_PREFIX+p for p in ids[actors//2:]],
        control_modes={FACTORY_ACTOR_PREFIX+p: 'LOCAL_AUTO' for p in ids},
        arena_id='battlefield:map.speedbench-roof', match_seed='SPEEDBENCH1', maximum_rounds=200)['match_id']
    journal = combat._match_dir(mid) / 'Journal.ndjson'
    checkpoints = {}
    session = combat._load_session(mid)
    for step in range(300):
        n = len(journal.read_bytes().splitlines())
        for target in (50,150,300):
            if n >= target and target not in checkpoints:
                dest = data.parent / f'boundary-{target}'
                shutil.copytree(data, dest)
                checkpoints[target] = (dest, n)
                print(f'S0 history: {n} records', file=sys.stderr, flush=True)
        if n >= records:
            break
        result = combat.local_step(mid, session=session)
        assert result['status'] == 'COMMITTED', result
        assert session.engine.state.terminal_result is None, 'synthetic fight ended before history target'
    else:
        raise AssertionError('history exceeded 300 AI steps')
    if records:
        assert sum(z.active for z in session.engine.state.zones.values()) == 1, 'AI did not leave exactly one standing zone'
    checkpoints[0] = (data, len(journal.read_bytes().splitlines()))
    return mid, checkpoints


def operation(data, mid, name):
    """Prepare outside the counters; measure a whole service request body."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    combat = CombatService(ROOT, data)
    table = TabletopService(combat, data)
    if name == 'mantis_native':
        from tests.mantis_native_support import candidate, FOE
        from tests.table_act_support import act
        selected = candidate(combat, mid, 'Eye of the Mantis', target=FOE)
        def mantis_action():
            result = act(table, mid, selected.candidate_id)
            assert result['status'] == 'COMMITTED', result
            return result
        return mantis_action
    if name.startswith('cold_'):
        return lambda: combat.get_match(mid)
    if name == 'events':
        return lambda: table.events(mid, 0)
    if name == 'state':
        return lambda: table.state(mid)
    if name.startswith('ai_'):
        if name == 'ai_step':
            return lambda: table.auto_step(mid, 0)
        return lambda: combat.local_run(mid, maximum_steps=5)
    def matches(c):
        action = session.engine.action_catalog.get(c.source_definition_id)
        if action is None:
            return False
        if name == 'toggle':
            return action.economy == 'NONE' and 'Adrenaline: Berserk' in c.display_name
        if name == 'area':
            return c.display_name.startswith('Ashfall')
        return 'attack' in c.display_name.lower() and bool(c.target_ids)
    # History may stop after spending an action. Reach a legal boundary through
    # ordinary end-turn commits, outside both timing and count windows.
    for _ in range(16):
        session = combat._load_session(mid)
        actor = session.engine.state.current_actor_id
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')
        state = table.state(mid)
        menu = state['menu']
        if name == 'movement':
            move = next((c for c in menu['moves'] if c.get('path') and len(c['path']) >= 2), None)
            if move:
                return lambda: table.commit_move_path(mid, move['candidate_id'], menu['decision_id'],
                    menu['state_version'], actor, move['path'], 0)
        else:
            candidates = combat._legal_candidates(combat._load_session(mid))
            candidate = next((c for c in candidates if matches(c)), None)
            if candidate:
                break
        result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0)
        assert result['status'] == 'COMMITTED', result
    else:
        raise AssertionError(f'No legal {name} boundary in 16 turns')
    def act():
        args = (mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], 0)
        preview = table.act(*args, prepare_only=True)
        result = table.act(*args)
        answers = []
        for _ in range(64):
            if result['status'] != 'REACTION_REQUIRED':
                break
            prompt = result['reaction']
            answer = {**prompt['context'], 'selection': 'USE'}
            if prompt.get('choice'):
                answer['option_ids'] = [prompt['choice']['options'][0]['id']]
            answers.append(answer)
            result = table.act(*args, reactions=answers)
        assert result['status'] == 'COMMITTED', result
        return {'prepare': preview, 'act': result}
    return act


def sample(source, scratch, mid, name, *, counted):
    shutil.copytree(source, scratch)
    try:
        run = operation(scratch, mid, name)
        if counted:
            with counters() as (counts, hooks):
                value = run()
            return {**{k: counts[k] for k in ('loads','session_loads','candidates')},
                    'dispatches': counts['dispatches'], 'subscriber_calls': counts['subscriber_calls'],
                    'hooks': hooks,
                    'response_bytes': len(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode())}
        start = time.perf_counter()
        run()
        return (time.perf_counter()-start)*1000
    finally:
        shutil.rmtree(scratch)


def mantis_fixture(data):
    from tests.mantis_native_support import native
    # Journey ids seed the native fixture's dice. Bind that public random seam
    # during fixture creation only; do not replace dice or action outcomes.
    with patch('combat.journey.secrets.token_hex', return_value='170160'*4):
        _, _, mid = native(data)
    return mid


class MantisCounts:
    """Pytest call-phase counters for the existing whole native file."""
    def __init__(self):
        self.rows = []

    @staticmethod
    def plugin():
        import pytest
        owner = MantisCounts()
        class Plugin:
            @pytest.hookimpl(hookwrapper=True)
            def pytest_runtest_call(self, item):
                with counters() as (counts, hooks):
                    outcome = yield
                owner.rows.append({'test': item.nodeid, **dict(counts),
                    'dispatches': counts['dispatches'], 'subscriber_calls': counts['subscriber_calls'], 'hooks': hooks,
                    'passed': outcome.excinfo is None})
        return owner, Plugin()


def measure(root, *, mantis_tests=True):
    import os
    os.environ['CF_EMBED_MENU'] = '0'
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='scratch-', dir=root) as tmp:
        tmp = Path(tmp)
        mid, checkpoints = build(tmp / 'data')
        rows = []
        for name in SCENARIOS:
            print(f'S0 scenario: {name}', file=sys.stderr, flush=True)
            target = int(name.split('_')[1]) if name.startswith('cold_') else 300
            source, records = checkpoints[target]
            values = [sample(source, tmp/'sample', mid, name, counted=False) for _ in range(5)]
            counts = sample(source, tmp/'sample', mid, name, counted=True)
            rows.append({'scenario': name, 'records': records, 'median_ms': statistics.median(values),
                         'p90_ms': sorted(values)[-1], **counts})
        mantis = tmp/'mantis'
        mantis_mid = mantis_fixture(mantis)
        counts = sample(mantis, tmp/'sample', mantis_mid, 'mantis_native', counted=True)
        rows.append({'scenario': 'mantis_native', 'records': 0, 'median_ms': None, 'p90_ms': None, **counts})
        report = {'label': 'base', 'seed': 'SPEEDBENCH1', 'actors': 7, 'benchmark_records': 300,
                  'p90_method': 'nearest rank, n=5', 'response': 'compact JSON service body, not HTTP framing',
                  'subscriber_calls': 'actual invoke calls plus run_strict registered-subscriber estimate (A1 convention)',
                  'timing': 'uninstrumented service request; counts in a separate restored sample', 'scenarios': rows}
        from combat.gate5_service import CombatService
        def rss():
            return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')//1024
        service = CombatService(ROOT, checkpoints[300][0])
        before = rss()
        retained_session = service._load_session(mid)
        assert len(retained_session.engine.state.actors) == 7
        assert sum(z.active for z in retained_session.engine.state.zones.values()) == 1
        report['resident_memory'] = {'process_before_load_kib': before,
            'process_with_one_retained_session_kib': rss(), 'actors': len(retained_session.engine.state.actors),
            'active_zones': sum(z.active for z in retained_session.engine.state.zones.values()),
            'note': 'process RSS, allocator reuse included; does not establish a four-fight warm-host cap'}
    (root/'base.json').write_text(json.dumps(report, indent=2)+'\n')
    columns = ('scenario','records','median_ms','p90_ms','loads','session_loads','candidates','dispatches','subscriber_calls','response_bytes')
    table = '| '+' | '.join(columns)+' |\n| '+' | '.join('---' for _ in columns)+' |\n'
    for row in rows:
        table += '| '+' | '.join(f'{row[k]:.3f}' if isinstance(row[k],float) else str(row[k]) for k in columns)+' |\n'
    (root/'base.md').write_text(table)
    if mantis_tests:
        import pytest
        owner, plugin = MantisCounts.plugin()
        rc = pytest.main(['-vv', '--basetemp', str(root/'mantis-test-scratch'),
                         str(ROOT/'tests/test_mgr_mantis_native.py')], plugins=[plugin])
        (root/'mantis-tests.json').write_text(json.dumps(owner.rows, indent=2)+'\n')
        assert rc == 0, f'Mantis per-test count run failed: {rc}'
    return report


if __name__ == '__main__':
    import sys
    measure(sys.argv[1])
