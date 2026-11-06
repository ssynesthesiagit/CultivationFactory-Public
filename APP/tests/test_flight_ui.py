"""Player altitude destinations through the table, accepted intents and cold disk loads."""
from combat.gate5_service import CombatService
from combat.target_knowledge import is_attack
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
from tests.test_lock2_persistence import act


def test_ground_penalty_cards_survive_height_adapter_and_board(tmp_path, monkeypatch):
    import json
    import subprocess
    from pathlib import Path
    from combat.tabletop_service import TabletopService
    from tests.test_tabletop_hunt6 import HOLD, on_hold

    combat, table, mid = table_fight(tmp_path, [])

    def apply(engine):
        from combat import zones, typed_executor
        from types import SimpleNamespace
        actor, source = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        from combat.ext.rider_movement import step
        step(engine, source, [source.position, source.position.model_copy(update={'x': 5}),
                              source.position.model_copy(update={'x': 6})], HOLD)
        engine._apply_condition(actor, 'condition:typed.prone', 'test:prone', RIGHT,
                                expires_on='END_OF_HOLDER_NEXT_TURN')
        ctx = typed_executor.Context(engine, source, SimpleNamespace(source_definition_id='test:terrain'),
                                     None, {'numbers': {}}, [actor], actor, {})
        zones.create(ctx, {'name': 'Sticky ground', 'shape': 'sphere', 'size_ft': 10,
                           'difficult': 'hostile', 'duration': {}})

    with monkeypatch.context() as fixture:
        on_hold(fixture, apply)
        assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    menu = TabletopService(fresh, tmp_path).state(mid)['menu']
    movement = menu['movement_explanation']
    assert {'DIFFICULT_TERRAIN', 'CRAWLING'} <= {
        row['code'] for row in movement['destinations']['4,4']['reasons']}
    payload = tmp_path / 'ground-cards.json'
    payload.write_text(json.dumps({'movement': movement, 'moves': menu['moves']}))
    result = subprocess.run(['node', str(Path(__file__).with_name('flight_ui_ground_cards.mjs')), str(payload)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'real ground reasons and height quotes: PASS' in result.stdout
    loaded = fresh._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def move(table, mid, z):
    state = table.state(mid)
    menu = state['menu']
    actor = next(row for row in state['presentation']['actors'] if row['entity_id'] == LEFT)
    position = actor['position']
    row = next(row for row in menu['moves'] if row['destination']['x'] == position['x']
               and row['destination']['y'] == position['y'] and row['destination'].get('z', 0) == z)
    result = table.act(mid, row['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    return row['cost_ft']


def test_stock_sparrow_player_ascends_descends_and_cold_reloads(tmp_path):
    combat, table, mid = table_fight(tmp_path, ['TAL_ATHLETICS_SPARROW_S_PATH'])
    state = table.state(mid)
    actor = next(row for row in state['presentation']['actors'] if row['entity_id'] == LEFT)
    assert actor['fly_speed_ft'] == actor['speed_ft'] // 2
    before = actor['flying_movement_remaining_ft']
    # Five feet stays inside enemy reach; the established flight/OA tests cover
    # the paused upward leave-reach path separately.
    assert move(table, mid, 1) == 5
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position.z == 1
    actor = next(row for row in table.state(mid)['presentation']['actors'] if row['entity_id'] == LEFT)
    assert actor['altitude_ft'] == 5 and actor['flying_movement_remaining_ft'] == before - 5
    assert move(table, mid, 0) == 5
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position.z == 0
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_stock_wind_borne_body_expires_and_falls_through_table(tmp_path):
    combat, table, mid = table_fight(tmp_path, ['TAL_AIR_WIND_BORNE_BODY'], cl=11)
    menu = table.state(mid)['menu']
    engine = combat._load_session(mid).engine
    gather_id = next(action.source_definition_id for action in engine.action_catalog.values()
                     if action.owner_id == LEFT and action.parameters.get('typed', {}).get('source') == 'AIR_BASE_GATHER_CURRENT')
    gather = next(row for row in menu['actions'] if row['source_definition_id'] == gather_id)
    assert act(table, mid, gather['source_definition_id'])['status'] == 'COMMITTED'
    actor = next(row for row in table.state(mid)['presentation']['actors'] if row['entity_id'] == LEFT)
    assert actor['fly_speed_ft'] == 30
    assert move(table, mid, 1) == 5
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position.z == 0
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_table_melee_targets_count_height_after_flight_and_cold_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ['TAL_ATHLETICS_SPARROW_S_PATH'])
    engine = combat._load_session(mid).engine
    melee = {a.source_definition_id for a in engine.action_catalog.values()
             if a.owner_id == LEFT and is_attack(a) and (a.reach_ft or a.range_ft) == 5}
    def offered(state):
        return {g['source_definition_id'] for g in state['menu']['actions'] if g['source_definition_id'] in melee
                and any(RIGHT in row['target_ids'] for row in g['options'])}
    assert offered(table.state(mid))
    assert move(table, mid, 2) == 10
    assert not offered(table.state(mid)), 'enemy ten feet below is outside five-foot melee reach'
    loaded = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService
    assert not offered(TabletopService(loaded, tmp_path).state(mid))
    assert loaded._load_session(mid).verify()['status'] == 'PASS'


def test_player_ascent_opportunity_prompt_survives_cold_reload(tmp_path):
    from combat.tabletop import ButtonStore
    from combat.tabletop_service import TabletopService
    from tests.test_tabletop_hunt6 import PROJECTS
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PROJECTS['right'], {'mode': 'ask'}, {'opportunity_attack'})
    combat, table, mid = table_fight(tmp_path, ['TAL_ATHLETICS_SPARROW_S_PATH'])
    state = table.state(mid)
    menu = state['menu']
    actor = next(row for row in state['presentation']['actors'] if row['entity_id'] == LEFT)
    destination = {**actor['position'], 'z': 2}
    row = next(row for row in menu['moves'] if row['destination'] == destination)
    args = (mid, row['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    paused = table.act(*args)
    assert paused['status'] == 'REACTION_REQUIRED'
    assert paused['reaction']['context']['reactor_id'] == RIGHT
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)['pending_action']['reaction'] == paused['reaction']
    reply = {**paused['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}
    assert reopened.act(*args, reactions=[reply])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position.z == 2
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
