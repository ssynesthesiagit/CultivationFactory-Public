"""Native movement IDs accept only the path and mode they currently quote."""
import pytest

from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopError, TabletopService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import table_match


@pytest.mark.parametrize('mismatch', ['path', 'mode', 'action'])
def test_native_move_cannot_authorize_another_route(tmp_path, mismatch):
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    move = next(m for m in menu['moves'] if len(m['path']) == 3)
    path = list(move['path'])
    cid, mode = move['candidate_id'], move.get('movement_mode', 'walk')
    if mismatch == 'path':
        # A still-legal out-and-back detour ending at the quoted destination.
        # A native endpoint ID must not authorize a different chosen path.
        path = [path[0], path[1], path[0], *path[1:]]
        table.preview_move_path(mid, menu['decision_id'], menu['state_version'], menu['actor_id'], path)
    elif mismatch == 'mode':
        mode = 'jump'
    else:
        cid = menu['end_turn']
    before = canonical_state_sha256(combat._load_session(mid).engine.state)
    with pytest.raises(TabletopError):
        table.commit_move_path(mid, cid, menu['decision_id'], menu['state_version'],
            menu['actor_id'], path, state['last_sequence'], mode)
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == before


def test_native_menu_route_reaction_continues_after_reload(tmp_path):
    from tests.test_tabletop_hunt6 import table_fight, RIGHT, LEFT
    from tests.test_lock2_persistence import act
    combat, table, mid = table_fight(tmp_path, [], ask=True)
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    native = next(c for c in combat._load_session(mid).engine.legal_candidates()
                  if c.kind == 'MOVE' and c.metadata.get('expected_opportunity_attack_count'))
    path = [p.model_dump(mode='json') for p in native.canonical_path]
    before = canonical_state_sha256(combat._load_session(mid).engine.state)

    def send(current, answers=()):
        return current.commit_move_path(mid, native.candidate_id, menu['decision_id'],
            menu['state_version'], RIGHT, path, state['last_sequence'],
            native.metadata.get('movement_mode', 'walk'), list(answers))

    paused = send(table)
    assert paused['status'] == 'REACTION_REQUIRED'
    assert paused['reaction']['context']['reactor_id'] == LEFT
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == before
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    result = send(reopened, [{**paused['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    movement = next(e for e in reversed(loaded.engine.events) if e.event_type == 'MOVEMENT_COMMITTED')
    assert movement.payload['path'] == path
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
