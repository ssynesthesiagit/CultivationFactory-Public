"""Movement cards through real table commit/reload; Node runs the board renderer."""
import json
from pathlib import Path
import subprocess

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, ROOT, table_fight, on_hold


def flat_ground_fight():
    """Normal-turn checks need flat ground; the default arena has base terrain costs."""
    from tests.test_lock8_movement_explanations import fight
    engine = fight()
    engine.grid.base_movement_cost.clear()
    base = engine._wall_base
    engine._wall_base = (*base[:3], {})
    return engine


@pytest.mark.parametrize('effect,code', [('fear', 'FRIGHTENED_CLOSER'),
                                       ('zero', 'SPEED_ZERO'), ('grapple', 'GRAPPLED'),
                                       ('terrain', 'DIFFICULT_TERRAIN'),
                                       ('affliction', 'SPEED_PENALTY')])
def test_movement_cards_after_table_commit_reload(tmp_path, monkeypatch, effect, code):
    combat, table, mid = table_fight(tmp_path, [])

    def apply(engine):
        from combat.ext.rider_movement import step
        actor, source = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        step(engine, source, [source.position, source.position.model_copy(update={'x': 5}),
                              source.position.model_copy(update={'x': 6})], HOLD)
        if effect == 'fear':
            engine._apply_condition(actor, 'condition:typed.frightened', 'test:fear', RIGHT,
                                    expires_on='END_OF_HOLDER_NEXT_TURN')
        elif effect == 'zero':
            engine._add_modifier(actor, 'test:slow', 'speed_ft', 'ADD', -actor.speed_ft, 'SELF',
                                 expires_on='END_OF_HOLDER_NEXT_TURN')
        elif effect == 'grapple':
            engine._apply_condition(actor, 'condition:core.grappled', 'test:grapple', RIGHT,
                                    expires_on='END_OF_HOLDER_NEXT_TURN')
        elif effect == 'affliction':
            from combat.ext.afflictions import condition_id
            engine._apply_condition(actor, condition_id(), 'test:slow', RIGHT,
                                    expires_on='END_OF_HOLDER_NEXT_TURN',
                                    data={'speed': -actor.speed_ft, 'label': 'Crippling Curse: Heavy legs'})
        else:
            from combat import zones, typed_executor
            from types import SimpleNamespace
            # A real persisted difficult-terrain zone, not a mock diagnostic.
            ctx = typed_executor.Context(engine, source, SimpleNamespace(source_definition_id='test:terrain'),
                                         None, {'numbers': {}}, [actor], actor, {})
            zones.create(ctx, {'name': 'Sticky ground', 'shape': 'sphere', 'size_ft': 10,
                               'difficult': 'hostile', 'duration': {}})

    with monkeypatch.context() as fixture:
        on_hold(fixture, apply)
        assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    state = TabletopService(fresh, tmp_path).state(mid)
    menu = state['menu']
    assert menu['manual'] and menu['actor_id'] == LEFT
    movement = menu['movement_explanation']
    assert code in [r['code'] for r in movement['summary']['reasons']]
    near = movement['destinations']['4,4']
    assert code in [r['code'] for r in near['reasons']]
    if effect == 'fear':
        assert not near['available'] and near['explained_refusal']
        assert "You are Frightened of Right: you can't move closer to them while you can see them." in [r['message'] for r in near['reasons']]
        assert '2,4' not in movement['destinations']  # legal movement away
    elif effect in {'zero', 'grapple', 'affliction'}:
        assert movement['summary']['effective_speed_ft'] == 0
        assert not menu['moves'] and not near['available']
        if effect == 'affliction':
            assert any('Crippling Curse: Heavy legs reduces Speed by' in r['message'] for r in near['reasons'])
            assert any('Caused by: Crippling Curse: Heavy legs.' in r['message'] for r in near['reasons'])
    else:
        terrain = next(r for r in near['reasons'] if r['code'] == code)
        assert terrain['step_cost_ft'] == 10 and near['available']
        assert 'Difficult terrain slows you here: this 5-foot step costs 10 feet' in terrain['message']
        summary = next(r for r in movement['summary']['reasons'] if r['code'] == code)
        assert 'step_cost_ft' not in summary and 'depends on the path' in summary['message']
        distant = next(r for r in movement['destinations']['5,4']['reasons'] if r['code'] == code)
        assert 'step_cost_ft' not in distant and 'depends on the path' in distant['message']
    loaded = fresh._load_session(mid)
    from combat.movement_presentation import for_menu
    from tests.test_lock8_movement_explanations import snapshot
    before = snapshot(loaded.engine)
    names = {key: actor.display_name for key, actor in loaded.engine.state.actors.items()}
    assert for_menu(loaded.engine, menu, names) == movement
    assert snapshot(loaded.engine) == before
    assert TabletopService(fresh, tmp_path).state(mid)['menu']['movement_explanation'] == movement
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    payload = tmp_path / 'movement.json'
    payload.write_text(json.dumps(movement), encoding='utf-8')
    result = subprocess.run(['node', str(Path(__file__).with_suffix('.cjs')), str(payload)],
                            capture_output=True, text=True, check=True)
    assert 'PASS' in result.stdout


def test_no_diagnostics_for_ai_or_missing_menu():
    from combat.movement_presentation import for_menu
    assert for_menu(object(), None, {}) is None
    assert for_menu(object(), {'manual': False}, {}) is None


def test_table_diagnostics_preserve_saved_bytes_and_ai_transaction(tmp_path, monkeypatch):
    """Query a saved synthetic fight, then compare its AI commit with an unqueried engine.

    Covers the real table boundary and a recorded local-AI transaction without
    opening historical/private saves. Every event, roll and state field counts.
    """
    from combat.canonical import canonical_bytes
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate3_reducer import enrich_committed_events
    from combat import movement_presentation

    combat, table, mid = table_fight(tmp_path, [])
    match_dir = combat._match_dir(mid)

    def saved_bytes():
        return {str(path.relative_to(match_dir)): path.read_bytes()
                for path in match_dir.rglob('*') if path.is_file()}

    before = saved_bytes()
    manual = table.state(mid)['menu']
    assert manual['manual'] and manual['movement_explanation']['summary']['actor_id'] == LEFT
    fresh_combat = CombatService(ROOT, tmp_path)
    assert TabletopService(fresh_combat, tmp_path).state(mid)['menu'] == manual
    assert saved_bytes() == before

    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    # This separate engine is loaded before the AI table queries, and never
    # receives a tooltip query. Re-execute the recorded intent on it below.
    baseline = CombatService(ROOT, tmp_path)._load_session(mid).engine
    event_start, roll_start = len(baseline.events), len(baseline.rolls)
    before = saved_bytes()

    def unexpected_diagnostics(*args, **kwargs):
        pytest.fail('An AI menu must not build manual movement diagnostics')

    with monkeypatch.context() as guard:
        guard.setattr(movement_presentation, 'for_menu', unexpected_diagnostics)
        ai_state = table.state(mid)
        ai_menu = ai_state['menu']
        assert not ai_menu['manual'] and 'movement_explanation' not in ai_menu
        fresh_combat = CombatService(ROOT, tmp_path)
        assert TabletopService(fresh_combat, tmp_path).state(mid)['menu'] == ai_menu
        assert saved_bytes() == before
    assert table.auto_step(mid, ai_state['last_sequence'])['status'] == 'COMMITTED'

    rows = [json.loads(line) for line in (match_dir / 'Journal.ndjson').read_text().splitlines()]
    prepare, committed = rows[-2:]
    assert prepare['record_type'] == 'PREPARE' and committed['record_type'] == 'COMMIT'
    assert prepare['transaction_id'] == committed['transaction_id']
    controller_rows = [json.loads(line) for line in
                       (match_dir / 'ControllerJournal.ndjson').read_text().splitlines()]
    decision = next(row['primary_decision_record'] for row in controller_rows
                    if row.get('intent_id') == prepare['intent']['intent_id'])
    assert decision['controller_id'] == 'controller:local_deterministic.gate4'
    assert decision['actor_id'] == LEFT
    assert decision['selected_candidate_id'] == prepare['intent']['candidate_id']
    baseline.execute_intent(ActionIntent.model_validate(prepare['intent']))
    actual_events = list(enrich_committed_events(baseline.events[event_start:], post_engine=baseline))
    actual_rolls = [roll.model_dump(mode='json') for roll in baseline.rolls[roll_start:]]
    assert canonical_bytes(actual_events) == canonical_bytes(committed['events'])
    assert canonical_bytes(actual_rolls) == canonical_bytes(committed['rolls'])
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert canonical_bytes(baseline.state.model_dump(mode='json')) == canonical_bytes(
        reloaded.engine.state.model_dump(mode='json'))
    assert reloaded.verify()['status'] == reloaded.mechanical.replay()['status'] == 'PASS'


def test_normal_and_zero_speed_queries_do_not_scale_with_map_area(monkeypatch):
    from combat.movement_presentation import for_menu
    from tests import lock8_support as S
    engine = flat_ground_fight()
    original = engine.movement_explanation
    calls = []
    def counted(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(engine, 'movement_explanation', counted)
    menu = {'manual': True, 'actor_id': S.ME, 'moves': []}
    for_menu(engine, menu, {})
    assert len(calls) == 1
    engine._add_modifier(engine.state.actors[S.ME], 'test:slow', 'speed_ft', 'ADD', -30, 'SELF',
                         expires_on='END_OF_HOLDER_NEXT_TURN')
    calls.clear()
    for_menu(engine, menu, {})
    assert len(calls) == 1


def test_hidden_fear_and_normal_turn_do_not_invent_restrictions():
    from combat.movement_presentation import for_menu
    from tests.test_lock8_movement_explanations import snapshot
    from tests import lock8_support as S
    engine = flat_ground_fight()
    def menu():
        return {'manual': True, 'actor_id': S.ME, 'moves': [
            {'destination': c.destination.model_dump(mode='json')}
            for c in engine.legal_candidates() if c.kind == 'MOVE']}
    normal = for_menu(engine, menu(), {})
    assert not normal['summary']['reasons']
    assert all(not row['available'] and not row['explained_refusal'] for row in normal['destinations'].values())
    engine._apply_condition(engine.state.actors[S.ME], 'condition:typed.frightened', 'test:fear', S.FOE,
                            expires_on='END_OF_HOLDER_NEXT_TURN')
    engine._apply_condition(engine.state.actors[S.FOE], 'condition:typed.invisible', 'test:hide', S.FOE,
                            expires_on='UNTIL_REMOVED')
    engine.state.observations.get(engine.state.actors[S.ME].team_id, {}).pop(S.FOE, None)
    before = snapshot(engine)
    hidden = for_menu(engine, menu(), {S.FOE: 'Secret name'})
    assert 'Secret name' not in json.dumps(hidden)
    assert not hidden['summary']['reasons']
    assert snapshot(engine) == before
