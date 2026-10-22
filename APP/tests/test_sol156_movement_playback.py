"""Headless table/board regressions; no GUI or browser is launched."""
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest


def test_real_table_movement_playback(tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for headless table playback tests')
    # Record the real table's Ask-me route response, rather than assuming where
    # the atomic server puts its pause or how it packages committed steps.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import table_fight, RIGHT
    from tests.test_sol137_movement_routes import table_route

    data = tmp_path / 'table'
    combat, table, mid = table_fight(data, [], ask=True)
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state, menu, path = table_route(table, mid)
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], RIGHT, path)
    args = (mid, quote['candidate']['candidate_id'], menu['decision_id'], menu['state_version'], RIGHT, path, state['last_sequence'])
    paused = table.commit_move_path(*args)
    assert paused['status'] == 'REACTION_REQUIRED'
    reopened = TabletopService(CombatService(ROOT, data), data)
    pending = reopened.state(mid)['pending_action']
    assert pending and pending['reaction'] == paused['reaction']
    committed = reopened.commit_move_path(*args, reactions=[{**paused['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}])
    assert committed['status'] == 'COMMITTED'
    recording = tmp_path / 'move.json'
    # Exercise the real table's generic snapshot/prompt boundary with native
    # movement events. No ability-specific mechanics or locked seams needed.
    from combat.choice_presentation import capture_space_positions
    from combat.history_feed import format_history_feed
    scenarios = []
    for routes in ([[1, 2], [2, 3]], [[1, 2, 3, 2]]):
        engine = reopened.combat._load_session(mid).engine
        actor = engine.state.actors[RIGHT]
        start_count = len(engine.events)
        for route in routes:
            points = [{'x': x, 'y': 1} for x in route]
            actor.position = actor.position.__class__(**points[-1])
            engine._append_event('MOVEMENT_COMMITTED', 'test:route', actor_id=RIGHT,
                                 payload={'path': points, 'destination': points[-1]})
        snapshot = capture_space_positions(engine, ['cell:4,1'])
        context = {'reactor_id': RIGHT, 'reaction_source_id': 'choice:needle.example',
                   'checkpoint': 'example', 'extension_choice': {'option_ids': ['cell:4,1']},
                   'choice_trigger': {'name': 'Example', 'space_positions': snapshot}}
        prompt = reopened._reaction_prompt(mid, context, engine=engine)
        token = next(t for t in prompt['choice']['space_map']['tokens'] if t['id'] == RIGHT)
        cursor = token['movement_cursor']
        assert cursor == {'event_sequence': engine.events[-1].sequence, 'path_index': len(routes[-1]) - 1}
        saved = {**pending, 'reaction': prompt}
        reopened._save_pending_action(mid, saved)
        loaded_table = TabletopService(CombatService(ROOT, data), data)
        loaded = loaded_table._pending_action(mid, saved['request'])
        assert loaded['reaction'] == prompt
        # Multiple step events continue in another event; a route event can
        # continue beyond its already displayed repeated-square prefix.
        if len(routes) > 1:
            engine._append_event('MOVEMENT_COMMITTED', 'test:route', actor_id=RIGHT,
                                 payload={'path': [{'x': 3, 'y': 1}, {'x': 4, 'y': 1}],
                                          'destination': {'x': 4, 'y': 1}})
        events = [e.model_dump(mode='json') for e in engine.events[start_count:]]
        if len(routes) == 1:
            events[-1]['payload']['path'].append({'x': 4, 'y': 1})
            events[-1]['payload']['destination'] = {'x': 4, 'y': 1}
        feed = format_history_feed(events, [], pre_state=None, post_state={}, actor_names={RIGHT: 'Ana'}, definition_names={})
        for row in feed:
            row['actor_id'] = 'a'
        scenarios.append({'pause': token['position'], 'cursor': cursor, 'prompt': loaded['reaction'],
                          'events': {'events': feed, 'dice': [], 'last_sequence': events[-1]['sequence']},
                          'expected': [{'x': 4, 'y': 1}]})
    recording.write_text(json.dumps({'paused': paused['events'], 'committed': committed['events'],
                                     'pending': pending, 'scenarios': scenarios}))
    script = Path(__file__).with_name('movement_playback_ui.test.mjs')
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'SOL156_RECORDING': str(recording)})
    assert result.returncode == 0, result.stdout + result.stderr
