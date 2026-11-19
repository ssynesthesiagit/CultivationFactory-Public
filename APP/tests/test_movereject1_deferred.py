"""Native route binding also works with main's deferred table acknowledgement."""
import socket
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopError, TabletopService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import table_match


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1, 0] for _ in texts], prefetch=lambda *a, **kw: None))

    def denied(*a, **kw):
        raise AssertionError('Movement regressions must not contact a live server')

    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)


@pytest.mark.parametrize('controller', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('token', ['native', 'explicit'])
def test_route_commit_defers_menu_and_preserves_binding_after_reload(tmp_path, controller, token):
    combat, table, mid = table_match(tmp_path)
    actor = table.state(mid)['menu']['actor_id']
    combat.set_controller_mode(mid, actor_id=actor, controller_mode=controller)
    before = table.state(mid)
    menu = before['menu']
    # Move away from the adjacent opponent without provoking an attack.
    safe = {c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
            if c.kind == 'MOVE' and not c.metadata.get('expected_opportunity_attack_count')}
    move = next(m for m in menu['moves'] if len(m['path']) == 2 and m['candidate_id'] in safe)
    path, mode = move['path'], move.get('movement_mode', 'walk')
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], actor, path, mode)
    cid = move['candidate_id'] if token == 'native' else quote['candidate']['candidate_id']

    result = table.commit_move_path(mid, cid, menu['decision_id'], menu['state_version'],
        actor, path, before['last_sequence'], mode, defer_menu=True)
    assert result['status'] == 'COMMITTED'
    assert result['state']['menu'] is None
    assert result['state']['menu_pending']['state_version'] > menu['state_version']
    cold = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert result['state'] == cold.state(mid, include_menu=False, fog=True)
    loaded = cold.combat._load_session(mid)
    movement = next(e for e in reversed(loaded.engine.events) if e.event_type == 'MOVEMENT_COMMITTED')
    assert movement.payload['path'] == path
    assert loaded.engine.state.actors[actor].position.model_dump(mode='json') == path[-1]
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    with pytest.raises(TabletopError) as stale:
        cold.commit_move_path(mid, cid, menu['decision_id'], menu['state_version'],
            actor, path, before['last_sequence'], mode, defer_menu=True)
    assert stale.value.code == 'TABLETOP_STALE'
    # Fetching the deferred menu retains every legal movement candidate.
    expanded = cold.state(mid)
    expected = {c.candidate_id for c in cold.combat._load_session(mid).engine.legal_candidates()
                if c.kind == 'MOVE'}
    assert {m['candidate_id'] for m in expanded['menu']['moves']} == expected
