"""Option-listing evidence for the mode-suffixed journey move options (F11R 12b).

journey.py offers one move option per native mode a creature can use. Each
mode is a separate option with a unique id, its own payload mode and a label
naming the mode, so the menu never has two options that a client or AI
cannot tell apart. Walking keeps its unsuffixed id.
"""
from tests.test_mgr_t15_swift_movement import A, B, PEER, OWNER, build, offline  # noqa: F401  (autouse fixture)


def test_journey_menu_lists_each_native_mode_as_its_own_move(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch)
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    moves = [row for row in service.journey_menu(state['journey_id'], A)['options'] if row['kind'] == 'move']
    ids = [row['id'] for row in moves]
    assert len(ids) == len(set(ids)), 'every move option needs a unique id'
    assert 'move:2,1,0' in ids, 'walking keeps its unsuffixed id'
    assert 'move:2,1,0:walk' not in ids
    fly = next(row for row in moves if row['id'] == 'move:2,1,0:fly')
    assert fly['payload'] == {'path': [{'x': 2, 'y': 1}], 'mode': 'fly'}
    assert 'fly to square (2, 1), 0 feet high' in fly['label']
    assert 'uses travel time at your current Speed' in fly['label']


def test_journey_menu_without_native_modes_keeps_only_walk_moves(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch, native=False)
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    ids = [row['id'] for row in service.journey_menu(state['journey_id'], A)['options'] if row['kind'] == 'move']
    assert ids and all(i.count(':') == 1 for i in ids), 'walk ids are move:x,y,z with no mode suffix'
