"""Relevant-only corrected lead scratch probe, with no live data/model access.

Self-contained so the public export ships the same probe it executes. Run it in
its own subprocess to keep timing instrumentation out of other tests.
"""
import contextlib
import copy
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import subprocess


def _probe(root, data, output):
    sys.path.insert(0, str(root))
    os.environ['CF_EMBED_MENU'] = '0'
    # No transport from this probe may reach a live model server.
    connect = socket.socket.connect
    def offline(self, address):
        if isinstance(address, tuple) and address[1] in (11434, 11448, 11449):
            raise OSError('live model transport forbidden in scratch probe')
        return connect(self, address)
    socket.socket.connect = offline

    from tests.asyncio_wakeup import install_if_needed
    install_if_needed()
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    from tests.test_factory_combat_compiler import SHEET
    import combat.tabletop_service as table_module

    for pid in ('left', 'right'):
        document = copy.deepcopy(SHEET)
        if pid == 'left':
            document['ability_scores_and_statistics']['initiative'] = json.dumps({'bonus':100})
        folder = data / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))

    local = threading.local()
    lock = table_module._match_lock
    @contextlib.contextmanager
    def timed_lock(mid):
        started = time.perf_counter()
        with lock(mid):
            if hasattr(local, 'waits'):
                local.waits.append(time.perf_counter() - started)
            yield
    table_module._match_lock = timed_lock
    records = []
    events = table_module.TabletopService.events
    def measured_events(self, *args, **kwargs):
        local.waits = []
        started = time.perf_counter()
        try:
            return events(self, *args, **kwargs)
        finally:
            records.append({'seconds':time.perf_counter()-started, 'lock_wait_s':sum(local.waits)})
            del local.waits
    table_module.TabletopService.events = measured_events

    application = create_app(Settings.from_env(root, data))
    results = {'app_root':str(root), 'reads':[]}
    with TestClient(application) as client:
        headers = {'x-foundry-token':client.get('/api/session').json()['token']}
        started = time.perf_counter()
        response = client.post('/api/combat/factory-matches', headers=headers, json={
            'project_ids':['left'], 'opponent_actor_ids':['actor:factory.right'],
            'control_modes':{'actor:factory.left':'MANUAL','actor:factory.right':'LOCAL_AUTO'},
            'match_seed':'RETRYLOOP1-READ'})
        assert response.status_code == 200, response.text
        results['create_s'] = time.perf_counter()-started
        mid = response.json()['match_id']
        url = '/api/tabletop/matches/' + mid
        started = time.perf_counter()
        response = client.get(url + '/state?fog=true&include_menu=false&compact=true')
        assert response.status_code == 200, response.text
        results['initial_state_s'] = time.perf_counter()-started
        results['initial_sequence'] = response.json()['last_sequence']
        results['first_actor'] = response.json()['presentation']['current_actor_id']
        for kind in ('idle-cold', 'with-menu', 'idle-warm'):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = None
                if kind == 'with-menu':
                    entered = threading.Event()
                    original = table_module.TabletopService._built_state
                    def observed(self, *args, **kwargs):
                        entered.set()
                        return original(self, *args, **kwargs)
                    table_module.TabletopService._built_state = observed
                    pending = pool.submit(client.get, url + '/state?fog=true&include_menu=true&compact=true')
                    assert entered.wait(60), 'scratch menu read never entered'
                started = time.perf_counter()
                response = client.get(url + '/events?after=0')
                assert response.status_code == 200, response.text
                results['reads'].append({'kind':kind,'http_s':time.perf_counter()-started,
                    'event_rows':len(response.json()['events']), 'last_sequence':response.json()['last_sequence'],
                    'service':records[-1]})
                if pending:
                    menu_response = pending.result(timeout=120)
                    assert menu_response.status_code == 200, menu_response.text
                    table_module.TabletopService._built_state = original
    results['instrumented_events'] = records
    output.write_text(json.dumps(results, indent=2) + '\n')


def test_scratch_events_read_probe(tmp_path, capsys):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'timings.json'
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()),
         str(root), str(tmp_path / 'data'), str(output)],
        cwd=root, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    timings = json.loads(output.read_text())
    assert [read['kind'] for read in timings['reads']] == ['idle-cold', 'with-menu', 'idle-warm']
    assert all(read['event_rows'] for read in timings['reads'])
    # Measurements, not latency assertions: the Event-based HTTP regression
    # owns the correctness check. Emit evidence even with pytest's quiet capture.
    with capsys.disabled():
        print('\nRETRYLOOP1F1_READ_PROBE ' + json.dumps(timings, sort_keys=True), flush=True)


if __name__ == "__main__":
    _probe(*map(Path, sys.argv[1:]))
