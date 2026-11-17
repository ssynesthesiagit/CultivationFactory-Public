"""A model seat reuses the table's verified read boundary, never its authority."""
import json
from types import SimpleNamespace
import pytest

from combat import menu_rank
from tests.test_agent_seats import runner_for
from tests.test_hunt5_player_choices import fixture


@pytest.mark.parametrize('verified', [True, False])
def test_model_step_initial_view_reuses_verified_session_only(tmp_path, monkeypatch, verified):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **k: None))
    combat, table, mid, *_ = fixture(tmp_path, 'AIR_BASE_GATHER_CURRENT')
    def provider(config, prompt, png):
        legal = json.loads(prompt.split('\n', 1)[1])['legal_menu']
        end = next(key for key, row in legal.items() if row['action'] == 'End turn')
        return json.dumps({'plan': [end]}), None
    runner, _ = runner_for(tmp_path, table, provider, render_png=lambda view: None)
    actor_id = combat._load_session(mid).engine.state.current_actor_id
    runner.set_seat(mid, actor_id, 'MODEL', 'fake')
    original = combat._load_session
    loads = []
    def load(match_id):
        loads.append(match_id)
        return original(match_id)
    monkeypatch.setattr(combat, '_load_session', load)
    if not verified:
        monkeypatch.setattr(combat, 'presentation_session', lambda session: None)
    assert runner.drive(mid, max_steps=1) == 1
    # One initial load plus the ordinary fresh commit load. A rejected view
    # causes another initial load and a cold post-commit response as before.
    assert len(loads) == (2 if verified else 4), f'session loads: {len(loads)}'
    assert runner.decisions(mid)[-1]['status'] == 'COMMITTED'
    assert original(mid).mechanical.replay()['status'] == 'PASS'
