"""LOSLINES3 review regressions, using portable fights and no live servers."""
from pathlib import Path

import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from combat.terrain_occlusion import sight_geometry, segment_clear
from tests.test_loslines2 import isolated_menu_embeddings  # pytest fixture shared by table regressions
from tests.test_save_reload_equivalence import _install_factory

APP = Path(__file__).resolve().parents[1]


def p(x, y, z=0):
    return Position(x=x, y=y, z=z)


def test_enter_target_from_and_leave_screen_through_table_and_reload(tmp_path):
    from combat import target_knowledge
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    ids, bundles = _install_factory(tmp_path, 'screen', ['TAL_SOUND_RESONANT_NOTE'], 'Qi')
    combat = CombatService(APP, tmp_path)
    arena = to_battlefield(normalize_map({'width_squares':10, 'height_squares':8}))
    arena['terrain_regions'] = [{'region_id':'screen', 'terrain_type':'SIGHT_BLOCKED',
        'movement_cost':1, 'cells':[{'x':4, 'y':4}]}]
    mid = combat._finish_factory_match(bundles, ids, {ids[0]:'team:a', ids[1]:'team:b'},
        {ids[0]:{'x':3,'y':4}, ids[1]:{'x':5,'y':4}}, arena, [ids[0]], [ids[1]],
        control_modes={aid:'MANUAL' for aid in ids}, match_seed='SCREEN-ENDPOINT',
        display_name='Walk-through screen', maximum_rounds=10)['match_id']
    table = TabletopService(combat, tmp_path)
    for _ in range(4):
        state = table.state(mid)
        menu = state['menu']
        if menu['actor_id'] == ids[0]:
            break
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                         state['last_sequence'])['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == ids[0]
    engine = combat._load_session(mid).engine
    assert not target_knowledge.can_see(engine, engine.state.actors[ids[0]], engine.state.actors[ids[1]])
    for destination, visible in ((p(4,4),True), (p(4,5),False), (p(5,5),True)):
        state = table.state(mid)
        move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == destination)
        assert any(o['candidate_id'] == move.candidate_id for o in state['menu']['moves'])
        assert table.act(mid, move.candidate_id, move.decision_id, move.state_version,
                         state['last_sequence'])['status'] == 'COMMITTED'
        combat = CombatService(APP, tmp_path)
        table = TabletopService(combat, tmp_path)
        engine = combat._load_session(mid).engine
        actor, target = (engine.state.actors[aid] for aid in ids)
        assert actor.position == destination
        fresh = table.state(mid, fog=True)
        assert (ids[1] in fresh['fog_perception'][ids[0]]['creatures']) == visible
        assert target_knowledge.can_see(engine, actor, target) == visible
        assert engine.grid.line_of_sight(actor.position, target.position) == visible
        assert engine.grid.line_of_sight(target.position, actor.position) == visible
        assert combat._load_session(mid).verify()['status'] == 'PASS'
        if not visible:
            continue  # a closed end cap still hides a target after leaving
        candidates = [c for c in engine.legal_candidates() if c.target_ids == (ids[1],)
                      and engine.action_catalog.get(c.source_definition_id)
                      and engine.action_catalog[c.source_definition_id].display_name.startswith('Resonant Note:')]
        assert candidates, 'sight-dependent targeting must stay reachable after entering and leaving'
        assert all(c.candidate_id in str(fresh['menu']) for c in candidates)
        policy, _ = PolicyLibrary(APP).for_actor(ids[0])
        ai = build_decision_context(engine, policy, for_ai=True)
        assert {c.candidate_id for c in candidates} <= {c.candidate_id for c in ai.legal_candidates}


@pytest.mark.parametrize('cells', [[(4,4)], [(4,4),(4,5),(4,6)], [(4,4),(6,4)]])
def test_occupied_line_span_exempts_only_endpoint_cell(cells):
    grid = SquareGrid({'width_squares':10, 'height_squares':10, 'square_size_ft':5,
        'starting_positions':{}, 'terrain_regions':[{'terrain_type':'SIGHT_BLOCKED',
        'movement_cost':1, 'height_ft':10, 'cells':[{'x':x,'y':y} for x,y in cells]}]})
    for end in (p(3,4),p(5,4),p(4,3),p(3,3),p(5,5)):
        assert grid.line_of_sight(p(4,4),end)
        assert grid.line_of_sight(end,p(4,4))
    if len(cells) > 1:
        end = p(4,7) if (4,5) in cells else p(7,4)
        assert not grid.line_of_sight(p(4,4),end), 'intervening cells remain barriers'
        assert not grid.line_of_sight(end,p(4,4))
    assert not segment_clear(grid,p(4,4),p(5,4)), 'surface-ended sight queries retain exact geometry'
    # Neither endpoint occupies this raised span; vertical crossings still block.
    raised = SquareGrid({'width_squares':10, 'height_squares':10, 'square_size_ft':5,
        'starting_positions':{}, 'terrain_regions':[{'terrain_type':'SIGHT_BLOCKED',
        'movement_cost':1, 'height_ft':10, 'base_altitude_ft':10, 'cells':[{'x':4,'y':4}]}]})
    assert not raised.line_of_sight(p(4,4),p(4,4,6))


def test_solid_blocker_keeps_its_near_face_visible_but_still_blocks_through():
    """A movement-blocking wall or object is a target in its own square, not a blind spot.

    The centre-line seam must keep the near-side endpoint of a BLOCKED span
    visible (object targeting, cell aim) while an intervening cell of the same
    solid still stops the ray. Without the endpoint clip a blocking map object
    could never be seen, so no object action or Crumble-style option existed.
    """
    grid = SquareGrid({'width_squares':10, 'height_squares':10, 'square_size_ft':5,
        'starting_positions':{}, 'terrain_regions':[{'terrain_type':'BLOCKED',
        'movement_cost':1, 'height_ft':5, 'cells':[{'x':4,'y':4}]}]})
    assert (4, 4) in grid.blocked
    for start in (p(2,4), p(6,4), p(4,2), p(4,6), p(2,5)):
        assert grid.line_of_sight(start, p(4,4)), 'the blocker in its own square is its visible near face'
        assert grid.line_of_sight(p(4,4), start), 'sight is symmetric at the near face'
    assert not grid.line_of_sight(p(2,4), p(6,4)), 'an intervening solid cell still blocks sight'


@pytest.mark.parametrize('mode', ['centerline','cell'])
@pytest.mark.parametrize('height', ['unlimited','finite','roof'])
@pytest.mark.parametrize('blocks', ['sight','sight_and_movement'])
def test_wall_occluder_mode_survives_every_height_path(mode, height, blocks):
    doc = normalize_map({'width_squares':10,'height_squares':8,
        'walls':[{'shape':'rect','points':[[4,3],[5,4]],'blocks':blocks,'occluder':mode}]})
    if height != 'finite':
        doc['walls'][0].pop('height_ft')  # supported sealed/imported unlimited map data
    if height == 'roof':
        surround = normalize_map({'width_squares':10,'height_squares':8,
            'walls':[{'shape':'rect','points':[[1,1],[9,7]],'filled':False}],
            'roofs':{'height_ft':10}})
        doc['walls'].extend(surround['walls'])
        doc['roofs'] = surround['roofs']
    arena = to_battlefield(doc)
    if height == 'roof':
        assert arena['roof_surfaces']
    row = next(r for r in arena['terrain_regions'] if {'x':4,'y':3} in r['cells']
               and r['region_id'].startswith(('wall.','roof.wall.')))
    if height == 'roof':
        assert row['region_id'].startswith('roof.wall.')
    assert row['occluder'] == mode
    grid = SquareGrid(arena)
    geometry = sight_geometry(grid)
    own_lines = [r for r in geometry['lines'] if (4,3) in r['cells']]
    if mode == 'centerline':
        assert not own_lines
        assert any(r['mode']=='centerline' and (r['x'],r['y'])==(4,3) for r in geometry['volumes'])
    else:
        assert own_lines
    assert not grid.line_of_sight(p(2,3),p(7,3))
    assert bool(grid.terrain_at((4,3),'BLOCKED')) == (blocks == 'sight_and_movement')
    assert grid.line_of_physical_transmission(p(2,3),p(7,3)) == (blocks == 'sight')


def test_default_wall_regression_needs_no_private_capture(tmp_path):
    from tests import test_loslines2
    test_loslines2.test_talisman_wall_maple_shrine_copy_commit_reload_and_fog(tmp_path)
