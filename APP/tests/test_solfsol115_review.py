"""Review regressions: granted walking offers agree with native table commits."""
import pytest

from combat import granted_movement, posture
from combat.ext import portable_steps
from combat.gate2_runtime_models import Position
from tests import lock8_support as S
from tests.test_lock8_prone import knock, prone_table, record_setup
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

HEAVENLY = 'tianxia.subpath.body.drunken_fist.feature.heavenly_drunk'


def fall(engine, actor, heavenly):
    if heavenly:
        engine._apply_condition(actor, 'condition:typed.state.heavenly_drunk', HEAVENLY,
            actor.entity_id, expires_on='END_OF_TURN',
            data={'name': 'heavenly_drunk', 'label': 'Heavenly Drunk'})
    knock(engine, actor)


@pytest.mark.parametrize('heavenly', [False, True])
def test_every_granted_route_commits_in_table_transaction_and_replays(tmp_path, monkeypatch, heavenly):
    service, ui, mid, left, _ = prone_table(tmp_path)
    record_setup(ui, mid, []); turn(ui, mid, left)
    def grant(engine, event_type, kwargs):
        if event_type != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != left:
            return
        actor = engine.state.actors[left]
        fall(engine, actor, heavenly)
        origin, allowance = actor.position, actor.movement_remaining_ft
        offered = granted_movement.candidates(engine, actor, 15, engine._active_intent, 'test:grant')
        assert offered
        expected_extra = 0 if heavenly else 1
        assert posture.walking_extra(engine, actor) == expected_extra
        assert max(len(c.canonical_path) - 1 for c in offered.values()) == (3 if heavenly else 1)
        for candidate in offered.values():
            assert actor.position == origin
            path = candidate.canonical_path
            assert candidate.movement_cost_ft == granted_movement.path_cost(engine, actor, path)
            assert engine.grant_movement(actor, path, 'test:grant', feet=15,
                provokes=False) == candidate.movement_cost_ft <= 15
            assert actor.position == candidate.destination
            assert actor.movement_remaining_ft == allowance
            assert engine.grant_movement(actor, tuple(reversed(path)), 'test:return',
                feet=15, provokes=False) <= 15
    install(monkeypatch, 'event', grant)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = service._load_session(mid)
    assert posture.prone_conditions(loaded.engine.state.actors[left])
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == 'test:grant'
               for e in loaded.engine.events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('heavenly', [False, True])
def test_portable_prone_step_offers_preview_and_persist(tmp_path, monkeypatch, heavenly):
    from tests.test_lock25_portable_step import fight, SOURCE, DYNAMIC_ACTOR_ID
    from tests.test_c3d_p1_portable_live_combat import _preview_commit, _intent_from_candidate
    service, mid = fight(tmp_path)
    def knock_on_hold(engine, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == DYNAMIC_ACTOR_ID:
            fall(engine, engine.state.actors[DYNAMIC_ACTOR_ID], heavenly)
    install(monkeypatch, 'event', knock_on_hold)
    context = service.decision(mid)['context']
    hold = next(c for c in context['legal_candidates'] if c['source_definition_id'] == 'system:combat.hold_position')
    _preview_commit(service, mid, _intent_from_candidate(context, hold))
    context = service.decision(mid)['context']
    engine = service._load_session(mid).engine; actor = engine.state.actors[DYNAMIC_ACTOR_ID]
    assert posture.prone_conditions(actor)
    steps = [c for c in context['legal_candidates'] if c['source_definition_id'] == SOURCE]
    assert steps
    for candidate in steps:
        destination = Position(**candidate['destination'])
        path, cost = portable_steps.route(engine, actor, destination)
        assert granted_movement.path_cost(engine, actor, path, mode='walk') == cost <= 15
        preview = service.preview(mid, _intent_from_candidate(context, candidate), [])
        assert preview['status'] == 'PREVIEW_COMPLETE', preview
    assert max(engine.grid.distance_ft(actor.position, Position(**c['destination']))
               for c in steps) == (15 if heavenly else 5)
    chosen = next(c for c in steps if Position(**c['destination']) != actor.position)
    before = actor.movement_remaining_ft
    _preview_commit(service, mid, _intent_from_candidate(context, chosen))
    loaded = service._load_session(mid)
    assert loaded.engine.state.actors[DYNAMIC_ACTOR_ID].position == Position(**chosen['destination'])
    assert loaded.engine.state.actors[DYNAMIC_ACTOR_ID].movement_remaining_ft == before
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_standing_transition_uses_offer_query_and_preserves_overrides(monkeypatch):
    engine = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); actor = engine.state.actors[S.ME]
    knock(engine, actor)
    actor.speed_ft = 0
    install(monkeypatch, 'stand_cost', lambda *args: pytest.fail('explicit cost must bypass providers'))
    before = actor.movement_remaining_ft
    assert posture.stand_up(engine, actor, cost=0, ignore_speed=True)
    assert actor.movement_remaining_ft == before
    assert not posture.prone_conditions(actor)
    assert any(event.event_type == 'STOOD_UP' and event.actor_id == actor.entity_id
               and event.payload['cost_ft'] == 0 for event in engine.events)


def test_explicit_standing_cost_cannot_spend_beyond_movement_budget():
    engine = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); actor = engine.state.actors[S.ME]
    knock(engine, actor)
    actor.movement_remaining_ft = 5
    before_conditions = dict(actor.conditions)
    before_events = len(engine.events)
    assert not posture.stand_up(engine, actor, cost=15)
    assert actor.movement_remaining_ft == 5
    assert actor.conditions == before_conditions
    assert len(engine.events) == before_events


def test_prone_forced_path_keeps_physical_distance_budget():
    from tests.test_lock9_granted_paths import request
    engine = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(10, 6))
    actor = engine.state.actors[S.ME]
    knock(engine, actor)
    path = (actor.position, Position(x=2, y=6), Position(x=1, y=6))
    assert granted_movement.path_cost(engine, actor, path) == 20
    allowance = actor.movement_remaining_ft
    assert engine.move_path(actor, path, 'test:push', kind='forced', feet=10,
        source_actor_id=S.FOE, intent=request(engine)) == 10
    assert actor.position == path[-1] and actor.movement_remaining_ft == allowance


@pytest.mark.parametrize('hook,answer', [('stand_allowed', 1), ('stand_cost', True), ('stand_cost', -1)])
def test_offer_and_transition_reject_same_invalid_provider(monkeypatch, hook, answer):
    engine = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); actor = engine.state.actors[S.ME]
    knock(engine, actor)
    install(monkeypatch, hook, lambda *args: answer)
    before = actor.model_dump(mode='json')
    for query in (posture.standing_cost, posture.stand_up):
        with pytest.raises(ValueError):
            query(engine, actor)
        assert actor.model_dump(mode='json') == before
