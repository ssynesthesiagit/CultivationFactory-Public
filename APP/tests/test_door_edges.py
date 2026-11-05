"""DOOREDGE (owner 2026-10-10): a door, gate or window may sit on any edge of its square.

The map editor now snaps an opening to the straight wall line nearest the pointer inside the
square -- an edge or the middle. An edge is stored as an integer hundredth of a square
(mount_line), in the square the line rounds into, which is what the wall/opening geometry has
always used. These checks that such an edge-mounted door blocks movement and line of sight
while closed, lets both through while open, survives the table's own commit path
(TabletopService -> session execute_intent) and a cold reload, and replays.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_r3i_thread_object import _sheet
from tests.test_r3i_thread_door import _row
from tests.test_auto_lane1 import ROOT
from tests import test_sys_placed_effects as P


@pytest.mark.parametrize('axis', ['h', 'v'])
@pytest.mark.parametrize('opened', [False, True])
def test_edge_mounted_door_blocks_then_opens_at_the_table(tmp_path, axis, opened):
    owner, foe = P.ME, 'actor:factory.dooredge-foe'
    # 'h': the wall runs along y=7 (whole row 7), so the door on line 700 sits at (4, 7) -- the top
    # edge of its square, and the bottom edge of (4, 6). 'v' is the mirror along x=7 at (7, 4).
    if axis == 'h':
        wall = {'shape': 'line', 'points': [[0, 7], [19, 7]]}
        door_at, door_square = (4, 7), (4, 7)
        origin, target = {'x': 4, 'y': 6}, Position(x=4, y=8)
        foe_at = {'x': 16, 'y': 2}
    else:
        wall = {'shape': 'line', 'points': [[7, 0], [7, 13]]}
        door_at, door_square = (7, 4), (7, 4)
        origin, target = {'x': 6, 'y': 4}, Position(x=8, y=4)
        foe_at = {'x': 2, 'y': 2}
    door_pos = Position(x=door_square[0], y=door_square[1])
    document = normalize_map({
        'display_name': 'DOOREDGE', 'width_squares': 20, 'height_squares': 14,
        'walls': [wall],
        'objects': [_row(opened=1 if opened else 0, x=door_at[0], y=door_at[1], mount_axis=axis, mount_line=700)],
    })
    sheets = [_sheet(), _sheet()]
    # Both fighters mundane: this lane is about the door geometry, and a talent such as Raise the
    # Vessel would add its own reaction prompt to an ordinary move and hide the rule under test.
    sheets[0]['spheres_and_talents'] = {}
    sheets[1]['spheres_and_talents'] = {}
    bundles = [compile_character(sheet, actor_id=actor, reaction_plan={'ask': True})
               for sheet, actor in zip(sheets, [owner, foe])]
    combat = CombatService(ROOT, tmp_path / 'combat')
    table = TabletopService(combat, tmp_path / 'combat')
    mid = combat._finish_factory_match(bundles, [owner, foe], {owner: 'team:a', foe: 'team:b'},
        {owner: origin, foe: foe_at}, to_battlefield(document), [owner], [foe],
        control_modes={owner: 'MANUAL', foe: 'MANUAL'}, match_seed=f'DOOREDGE-{axis}-{opened}',
        display_name='Edge door', maximum_rounds=5)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    for _ in range(3):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == owner:
            break
        assert act(menu['end_turn'])['status'] == 'COMMITTED'

    engine = combat._load_session(mid).engine
    assert (door_square in engine.grid.blocked) is not opened
    assert engine.grid.line_of_sight(Position(**origin), target) == opened
    moves = [c for c in engine.legal_candidates() if c.destination == door_pos]
    assert bool(moves) is opened

    reloaded = CombatService(ROOT, tmp_path / 'combat')
    loaded = reloaded._load_session(mid)
    loaded.engine.legal_candidates()
    assert (door_square in loaded.engine.grid.blocked) is not opened
    assert loaded.engine.grid.line_of_sight(Position(**origin), target) == opened
    door = loaded.engine.state.objects['object:map.1']
    assert door.component['mount_axis'] == axis and door.component['mount_line'] == 700
    assert loaded.mechanical.replay()['status'] == 'PASS'

    if not opened:
        return
    menu = table.state(mid)['menu']
    assert TabletopService(reloaded, tmp_path / 'combat').act(
        mid, moves[0].candidate_id, menu['decision_id'], menu['state_version'], 0)['status'] == 'COMMITTED'
    final = CombatService(ROOT, tmp_path / 'combat')._load_session(mid)
    assert final.engine.state.actors[owner].position == door_pos
    assert final.mechanical.replay()['status'] == 'PASS'
