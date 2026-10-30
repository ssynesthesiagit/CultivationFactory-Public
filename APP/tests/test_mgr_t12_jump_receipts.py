"""MGRT12TPF5: every jump menu quotes the receipts its table commit spends."""
import pytest

from combat import ext, flight
from combat.ext import athletics
from combat.gate2_runtime_models import Position
from combat.granted_movement import native_path_cost
from tests.auto8f1_table_support import OWNER, FOE, SECOND, fixture, candidate_id
from tests.test_lock_choices import install
from tests.test_mgr_t12_tumble_pursuit import held_passages, finish


def held_jump_and_passages(count, *, movement_ft=45):
    def transform(bundles):
        held_passages(count)(bundles)
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        owner['actor_template']['strength_score'] = 30
        owner['actor_template']['speed_ft'] = movement_ft
        row = next(a for a in owner['action_catalog'] if a['source_definition_id'] == 'action:test.t12.receipts')
        row['parameters']['typed']['effects'].append({
            'type': 'condition', 'condition': 'flowing_pursuit_jump',
            'applies_to': 'self', 'expires_on': 'END_OF_CURRENT_TURN'})
    return transform


@pytest.mark.parametrize('passages,difficult,expected', [(1, False, None), (1, True, 25), (2, False, 20)])
def test_horizontal_jump_two_allies_table_quote_commit_reload(tmp_path, monkeypatch, passages, difficult, expected):
    from combat.relations import relation, ALLY
    if difficult:
        install(monkeypatch, 'pass_through', lambda e,a,b: 'difficult' if relation(e,a,b) == ALLY else None)
    game = fixture(tmp_path, [athletics.PURSUIT], seed=f'T12-horizontal-{passages}-{difficult}',
        bundle_transform=held_jump_and_passages(passages, movement_ft=25), allies=(FOE, SECOND),
        places={OWNER:{'x':3,'y':6}, FOE:{'x':4,'y':6}, SECOND:{'x':6,'y':6}})
    game['commit'](candidate_id(game['menu'](), 'Test held receipts'))
    finish(game)
    engine = game['stored_engine']()
    actor = engine.state.actors[OWNER]
    assert any(c.condition_id == athletics.PURSUIT_JUMP for c in actor.conditions.values())
    destination = Position(x=7,y=6)
    path = tuple(Position(x=x,y=6) for x in range(3,8))
    # Menus for manual, local AI and model seats must agree on feasibility/cost.
    for mode in ('MANUAL', 'LOCAL_AUTO', 'API_AUTO'):
        engine.typed_control_modes[OWNER] = mode
        candidates = engine._movement_candidates(actor)
        jumps = [c for c in candidates if c.metadata.get('movement_mode') == 'jump']
        target = [c for c in jumps if c.destination == destination]
        assert [c.movement_cost_ft for c in target] == ([] if expected is None else [expected])
        # A single receipt still supports the shorter crossing and all straight
        # headings, including a non-cardinal endpoint from the original menu.
        assert any(c.destination == Position(x=5,y=6) for c in jumps)
        assert any(c.destination == Position(x=4,y=8) for c in jumps)
        assert any(c.destination == Position(x=5,y=6)
                   and c.metadata.get('movement_mode', 'walk') == 'walk' for c in candidates)
    if expected is None:
        from combat.tabletop_service import TabletopError
        with pytest.raises(ValueError, match='legal path'):
            native_path_cost(engine, actor, path, mode='jump')
        menu = game['menu']()
        with pytest.raises(TabletopError, match='legal path'):
            game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'],
                OWNER, [p.model_dump(mode='json') for p in path], 'jump')
        chosen = next(c for c in engine.legal_candidates() if c.metadata.get('movement_mode') == 'jump'
                      and c.destination == Position(x=5,y=6))
        paid = 10
    else:
        assert native_path_cost(engine, actor, path, mode='jump') == expected
        menu = game['menu']()
        quote = game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'],
            OWNER, [p.model_dump(mode='json') for p in path], 'jump')
        assert quote['candidate']['movement_cost_ft'] == expected
        chosen = next(c for c in engine.legal_candidates() if c.metadata.get('movement_mode') == 'jump'
                      and c.destination == destination)
        paid = expected
    menu = game['menu']()
    quote = game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'],
        OWNER, [p.model_dump(mode='json') for p in chosen.canonical_path], 'jump')
    assert quote['candidate']['movement_cost_ft'] == paid
    before = actor.movement_remaining_ft
    game['commit'](chosen.candidate_id, lambda p,c: pytest.fail('No creature qualifies for a new pursuit benefit'))
    finish(game)
    loaded = game['reload_owner']()
    assert loaded.position == chosen.destination
    assert loaded.movement_remaining_ft == before - paid
    assert not any(c.condition_id in {athletics.PURSUIT_PASSAGE, athletics.PURSUIT_JUMP}
                   for c in loaded.conditions.values())


def test_supported_jump_landing_reprices_complete_runup_inventory(monkeypatch):
    from tests.test_roof_movement import engine_at_wall
    engine, actor = engine_at_wall(wall_x=6, height_ft=10)
    actor.position = Position(x=3,y=5)
    actor.strength_score = 30
    actor.speed_ft = actor.movement_remaining_ft = 45
    allies = [a for a in engine.state.actors.values() if a is not actor][:2]
    for other, position in zip(allies, (Position(x=4,y=5), Position(x=5,y=5,z=1))):
        other.team_id = actor.team_id
        other.position = position
    ids = {a.entity_id for a in allies}
    install(monkeypatch, 'pass_through_limited_grant',
            lambda e,a,b: [('free',None,'test:one-passage')] if a is actor and b.entity_id in ids else None)
    install(monkeypatch, 'pass_through', lambda e,a,b: 'difficult' if a is actor and b.entity_id in ids else None)
    ground = tuple(Position(x=x,y=5) for x in (3,4,5))
    # The native ground projection also prices the elevated ally's column.
    ground_cost = native_path_cost(engine, actor, ground, mode='walk')
    assert ground_cost == 15
    landing = Position(x=6,y=5,z=2)
    path, quote, mode = flight.jumps(engine, actor, {ground[-1]:(ground,ground_cost)})[landing]
    assert path == (*ground, Position(x=5,y=5,z=1), Position(x=5,y=5,z=2), landing)
    assert quote == native_path_cost(engine, actor, path, mode=mode) == 35


def test_jump_preview_hook_contract_is_documented():
    contract = ext.__doc__
    assert 'jump_preview_allowed(engine, actor) -> True or None' in contract
    assert 'With no True answer the ordinary gate remains in force' in contract
    assert 'It only enables enumeration' in contract
    assert 'execution still requires the real extension and native admission' in contract


def test_supported_landing_table_quote_commit_reload(tmp_path, monkeypatch):
    """The run-up, ascent and supported last step spend one shared inventory."""
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.gate2_runtime_content import AN
    from combat.relations import relation, ALLY
    from tests.h1_support import ROOT, sheet
    from tests.auto8f1_table_support import reload_identical

    install(monkeypatch, 'pass_through',
            lambda e,a,b: 'difficult' if relation(e,a,b) == ALLY else None)
    bundles = [compile_character(sheet([athletics.PURSUIT] if who == OWNER else [], cl=17),
                                 actor_id=who) for who in (OWNER, FOE, SECOND)]
    held_jump_and_passages(1)(bundles)
    # Keep the one-square ascending ally aloft through ordinary native flight.
    elevated = next(b for b in bundles if b['actor_id'] == SECOND)
    elevated['actor_template'].update(fly_speed_ft=5, hover=True)
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({
        'display_name': 'T12 supported receipt jump', 'width_squares': 12,
        'height_squares': 10,
        'walls': [{'shape':'rect', 'points':[[6,3],[10,8]], 'filled':False}],
        'roofs': {'height_ft':10, 'climb_check':'none'},
    })
    arena = combat.factory_arenas()['battlefield:map.' + saved['map_id']]
    ids = (OWNER, FOE, SECOND, AN)
    mid = combat._finish_factory_match(bundles, list(ids),
        {who:('team:b' if who == AN else 'team:a') for who in ids},
        {OWNER:{'x':3,'y':5}, FOE:{'x':4,'y':5}, SECOND:{'x':5,'y':5,'z':1}, AN:{'x':1,'y':1}},
        arena, [OWNER], [FOE, SECOND], control_modes={who:'MANUAL' for who in ids},
        match_seed='T12-supported-table', display_name='T12 jump regression', maximum_rounds=5)['match_id']
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == OWNER:
            break
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])['status'] == 'COMMITTED'
    else:
        pytest.fail('Owner never received a turn')
    assert table.act(mid, candidate_id(menu, 'Test held receipts'),
                     menu['decision_id'], menu['state_version'], 0, [])['status'] == 'COMMITTED'
    reload_identical(combat, mid, tmp_path)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert engine.state.actors[SECOND].position == Position(x=5,y=5,z=1)
    ground = tuple(Position(x=x,y=5) for x in (3,4,5))
    path = (*ground, Position(x=5,y=5,z=1), Position(x=5,y=5,z=2), Position(x=6,y=5,z=2))
    cost = native_path_cost(engine, actor, path, mode='jump')
    ground_cost = native_path_cost(engine, actor, ground, mode='walk')
    quoted = flight.jumps(engine, actor, {ground[-1]:(ground,ground_cost)})[path[-1]]
    assert quoted == (path, cost, 'jump')
    assert cost == 35
    menu = table.state(mid)['menu']
    points = [p.model_dump(mode='json') for p in path]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], OWNER, points, 'jump')
    assert quote['candidate']['movement_cost_ft'] == cost
    result = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
        menu['state_version'], OWNER, points, movement_mode='jump')
    assert result['status'] == 'COMMITTED'
    reload_identical(combat, mid, tmp_path)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert loaded.position == path[-1]
    assert loaded.movement_remaining_ft == actor.movement_remaining_ft - cost
    assert not any(c.condition_id in {athletics.PURSUIT_PASSAGE, athletics.PURSUIT_JUMP}
                   for c in loaded.conditions.values())
