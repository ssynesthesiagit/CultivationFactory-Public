"""Model seats use their own admitted menu; fake transport, no live inference."""
import json

import pytest

from agent_seats import SeatRunner
from agent_seats.providers import ProviderRegistry
from combat.ext.foundation_combat import held
from tests.test_a2_foundations_two import table_fixture
from tests.glass_refraction_support import declare
from tests.worker2_support import OWNER, reload


@pytest.mark.parametrize('admit', [False, True])
def test_model_seat_cannot_invent_entry_and_can_choose_admitted_paid_state(tmp_path, admit):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    if admit:
        declare(combat, table, mid)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = []
    def fake(provider, prompt, png):
        prompts.append(prompt)
        frame = json.loads(prompt.split('\n', 1)[1])
        legal = frame['legal_menu']
        state = next((k for k, row in legal.items()
                      if 'Glass Heart Refraction' in row['action']), None)
        assert bool(state) == admit
        end = next(k for k, row in legal.items() if row['action'] == 'End turn')
        return json.dumps({'plan': [state, end] if state else [end]}), {'total_tokens': 12}
    registry = tmp_path / 'providers.json'
    registry.write_text(json.dumps({'providers': [{'id': 'fake', 'kind': 'local', 'model': 'offline',
        'base_url': 'http://127.0.0.1:1/v1', 'timeout_s': 1}]}))
    runner = SeatRunner(table, registry=ProviderRegistry(registry), provider=fake, background=False)
    runner.set_seat(mid, OWNER, 'MODEL', 'fake')
    assert runner.drive(mid, max_steps=1) == 1
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert bool(held(owner, 'glass_refraction')) == admit
    assert owner.resources['resource:core.qi'] == before - (2 if admit else 0)
    assert len(prompts) == 1
    assert 'mirror tribunal' not in prompts[0].lower()
    assert all(row.get('fallback') is None for row in runner.decisions(mid))
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
