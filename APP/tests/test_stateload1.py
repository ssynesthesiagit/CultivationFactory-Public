"""HTTP state reads never enumerate choices; full menus remain available on demand."""
from pathlib import Path

import httpx

from app.api import create_app
from app.core import Settings
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.async_support import run_asgi
from tests.test_stateload1_core import setup

ROOT = Path(__file__).resolve().parents[1]


def test_http_snapshot_has_zero_candidate_generation_and_full_menu_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')  # Choice completeness, no live ranking/model transport.
    combat, session = setup(tmp_path)
    mid = session.match_id
    session.mechanical.explicit_snapshot()
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    table = app.state.agent_seats.table
    expected = TabletopService(combat, tmp_path).state(mid, fog=True, fog_view='own')
    generated = []
    original = CombatService._legal_candidates
    replayed = []
    original_replay = table.combat.persistence._replay_from

    def suffix_only(state, commits):
        commits = list(commits)
        replayed.append(len(commits))
        return original_replay(state, commits)

    monkeypatch.setattr(table.combat.persistence, '_replay_from', suffix_only)

    def counted(self, *args, **kwargs):
        generated.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CombatService, '_legal_candidates', counted)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            path = f'/api/tabletop/matches/{mid}/state'
            for fog in ('false', 'true'):
                response = await client.get(path, params={'fog': fog, 'fog_view': 'own'})
                assert response.status_code == 200, response.text
                snapshot = response.json()
                assert generated == [], 'state read generated legal choices before showing the fight'
                assert replayed and all(count == 0 for count in replayed), 'state read replayed checkpoint history'
                assert snapshot['menu'] is None
                assert snapshot['shapes'] == snapshot['button_states'] == {}
                assert snapshot['menu_pending']['state_version'] == session.engine.state.state_version
                assert snapshot == table.state(mid, fog=fog == 'true', fog_view='own', include_menu=False)
            response = await client.get(path, params={'fog': 'true', 'fog_view': 'own', 'include_menu': 'true'})
            assert response.status_code == 200, response.text
            assert generated
            assert response.json() == expected
            assert 'menu_pending' not in response.json()
    run_asgi(exercise())
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.model_dump(mode='json') == session.engine.state.model_dump(mode='json')
