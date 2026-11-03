"""Headless SPEED1 benchmark; all mutable data must be in task-owned folders.

Example: python tools/benchmark_ai_turns.py --output /var/tmp/speed1-evidence/base
  --scratch /var/tmp/speed1-data/base --live-copy /var/tmp/speed1-data/original
Never point --scratch at live user data. Private captures stay outside Git.
"""
from __future__ import annotations

import argparse
import cProfile
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import pstats
import shutil
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from combat.gate5_service import CombatService
from tests.test_save_reload_equivalence import STOCK_SEEDS, _start_stock, _bytes_of


def metrics(values):
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "median_ms": None, "p90_ms": None}
    return {"n": len(values), "median_ms": statistics.median(values),
            "p90_ms": ordered[math.ceil(len(ordered) * .9) - 1]}


def prepare_scenario(name, data, live_copy):
    data.mkdir(parents=True, exist_ok=False)
    if live_copy:
        shutil.copytree(live_copy / 'Combat', data / 'Combat')
    service = CombatService(ROOT, data)
    if live_copy:
        manifest = next(data.glob('Combat/Matches/*/Manifest.json'))
        mid = json.loads(manifest.read_text())['match_id']
        # Offline benchmark fixture only: bind copied immutable source hashes
        # to this checkout, without replaying a different historical engine.
        # No state, events, rolls, bundles or arena inputs are rewritten.
        from combat.canonical import sha256_file
        from combat.gate3_storage import _match_lock_deterministic_hash
        from combat.saved_fight_compat import engine_version
        folder = manifest.parent
        lock = json.loads((folder / 'MatchLock.json').read_text())
        for row in lock['content_identities']:
            if row.get('authority_scope', 'SOURCE') == 'SOURCE':
                row['sha256'] = sha256_file(ROOT / row['relative_path'])
        lock['deterministic_payload_sha256'] = _match_lock_deterministic_hash(lock)
        controller = service.persistence._controller_lock_document()
        for filename, document in [('MatchLock.json', lock), ('ControllerLock.json', controller),
                                   ('EngineVersion.json', engine_version(lock, controller))]:
            (folder / filename).write_text(json.dumps(document, sort_keys=True) + '\n')
        session = service._load_session(mid)
    else:
        session, mid = _start_stock(data, name.removeprefix('stock-'))
    metadata = service._read_metadata(mid, session)
    metadata['paused'] = False
    metadata['participant_control_modes'] = {aid: 'LOCAL_AUTO' for aid in session.engine.state.actors}
    service._write_metadata(mid, metadata)
    session = service._load_session(mid)
    return service, session, mid


def run(name, data, output, live_copy=None, limit=200, profile_steps=3, manual_menu=False):
    service, session, mid = prepare_scenario(name, data, live_copy)
    profile = cProfile.Profile()
    choices, times, menus, actors, statuses = [], [], [], [], []
    while session.engine.state.terminal_result is None and len(times) < limit:
        # Record the complete canonical menu independently. Do not prefill the
        # service's candidate cache: the timed AI action must enumerate itself.
        if manual_menu:
            session.engine.typed_control_modes = {
                **getattr(session.engine, 'typed_control_modes', {}),
                session.engine.state.current_actor_id: 'MANUAL'}
        start = time.perf_counter()
        candidates = session.engine.legal_candidates()
        menus.append((time.perf_counter() - start) * 1000)
        choices.append([c.model_dump(mode='json') for c in candidates])
        actors.append(session.engine.state.current_actor_id)
        # A menu and an AI turn each start from a fresh service load. Never
        # measure a menu-warmed engine as a cold AI step.
        session = service._load_session(mid)
        start = time.perf_counter()
        result = service.local_step(mid, session=session)
        times.append((time.perf_counter() - start) * 1000)
        statuses.append(result['status'])
        assert result['status'] == 'COMMITTED', result['status']
        (output / (name + '.partial.json')).write_text(json.dumps({
            'step_ms': times, 'menu_ms': menus, 'candidate_counts': [len(c) for c in choices]}))
        print(name, 'step', len(times), round(times[-1], 2), 'ms; menu', round(menus[-1], 2),
              'ms;', len(candidates), 'candidates', flush=True)
        session = service._load_session(mid)
    # Profile several fresh first actions separately. Instrumentation never
    # inflates the wall-time samples and a terminal endpoint cannot hide work.
    profile_data = data.parent / (name + '-profile')
    prof_service, prof_session, prof_mid = prepare_scenario(name, profile_data, live_copy)
    for _ in range(profile_steps):
        if prof_session.engine.state.terminal_result is not None:
            break
        profile.enable()
        result = prof_service.local_step(prof_mid, session=prof_session)
        profile.disable()
        assert result['status'] == 'COMMITTED', result['status']
        prof_session = prof_service._load_session(prof_mid)
    profile.dump_stats(str(output / (name + '.pstats')))
    stats = pstats.Stats(profile) if profile_steps else pstats.Stats()
    rows = sorted(({'file': k[0], 'line': k[1], 'function': k[2], 'calls': v[1],
                    'self_s': v[2], 'cumulative_s': v[3]} for k, v in stats.stats.items()),
                  key=lambda row: row['cumulative_s'], reverse=True)
    enumeration = sum(v[3] for k, v in stats.stats.items()
                      if k[2] == '_legal_candidates' and k[0].endswith('gate5_service.py'))
    state = session.engine.state.model_dump(mode='json')
    state['match_id'] = None
    capture = {'choices': choices, 'events': [e.model_dump(mode='json') for e in session.engine.events],
               'rolls': [r.model_dump(mode='json') for r in session.engine.rolls], 'state': state}
    raw = _bytes_of(capture).encode()
    (output / (name + '.json.gz')).write_bytes(gzip.compress(raw, mtime=0))
    summary = {'scenario': name, 'local_step': metrics(times), 'menu': metrics(menus),
               'backend': os.environ.get('CF_GEOMETRY_BACKEND', 'auto'),
               'menu_control_mode': 'MANUAL' if manual_menu else 'LOCAL_AUTO',
               'step_ms': times, 'menu_ms': menus, 'actors': actors, 'statuses': statuses,
               'sha256': hashlib.sha256(raw).hexdigest(), 'profile_total_s': stats.total_tt,
               'profile': rows[:100], 'enumeration_cumulative_s': enumeration,
               'enumeration_share': enumeration / stats.total_tt if stats.total_tt else None,
               'candidate_counts': [len(c) for c in choices],
               'verify': session.verify()['status'], 'replay': session.mechanical.replay()['status']}
    (output / (name + '.summary.json')).write_text(json.dumps(summary, indent=2) + '\n')
    (output / (name + '.partial.json')).unlink()
    print(name, json.dumps({k:summary[k] for k in ('local_step','menu','sha256','verify','replay')}), flush=True)
    shutil.rmtree(data)
    shutil.rmtree(profile_data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--live-copy', type=Path)
    parser.add_argument('--scenario', default='all')
    parser.add_argument('--live-steps', type=int, default=12)
    parser.add_argument('--profile-steps', type=int, default=3)
    parser.add_argument('--manual-menu', action='store_true', help='Measure the manual player menu; AI uses a separate load')
    args = parser.parse_args()
    args.scratch = args.scratch.resolve()
    if not args.scratch.is_relative_to(Path('/var/tmp')):
        parser.error('--scratch must be task-owned storage under /var/tmp')
    if args.live_copy:
        args.live_copy = args.live_copy.resolve()
        if args.live_copy == args.scratch or args.live_copy.is_relative_to(args.scratch):
            parser.error('--live-copy must be separate from disposable scratch')
    args.output.mkdir(parents=True, exist_ok=True)
    args.scratch.mkdir(parents=True, exist_ok=True)
    names = ['stock-' + s for s in STOCK_SEEDS]
    if args.live_copy:
        names.insert(0, 'live-3v3')
    for name in names:
        if args.scenario not in ('all', name):
            continue
        run(name, args.scratch / name, args.output,
            args.live_copy if name == 'live-3v3' else None,
            args.live_steps if name == 'live-3v3' else 200, args.profile_steps, args.manual_menu)


if __name__ == '__main__':
    main()
