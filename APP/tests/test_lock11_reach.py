"""Condition-bound reach proofs; final ability adapters remain rider-owned."""
import pytest
from combat import attack_reach, ext
from combat.ext.effect_durations import round_token
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, duel, ME
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.r10_fixup_support import cast_sender, commit

COURT = 'TAL_IRON_FIST_COURT_OF_ONE_HUNDRED_FORMS'
BRIAR = 'tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
STATE = 'condition:typed.reach_proof'


def unarmed(action):
    return any(e.get('type') == 'attack' and e.get('attack_kind') == 'unarmed'
               for e in (action.parameters.get('typed') or {}).get('effects') or [])


def natural(engine, actor=H.LEFT):
    return next(a for a in engine.action_catalog.values() if a.owner_id == actor and
                '.natural.' in a.source_definition_id and '#' not in a.source_definition_id)


def reach_reply(engine, actor, action, opportunity):
    if not unarmed(action):
        return None
    state = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    if state is None or (state.data.get('own_turn') and (opportunity or engine.state.current_actor_id != actor.entity_id)):
        return None
    return {'source_id': state.source_definition_id, 'feet': state.data['feet'], 'condition_id': state.instance_id}


def apply_reach(engine, actor, source, feet, *, expires=None):
    engine._apply_condition(actor, STATE, source, actor.entity_id,
        expires_on=expires or round_token(engine, 10),
        data={'feet': feet, 'label': f'Unarmed reach increased by {feet} feet'})


def move_fixture(engine, target, x):
    before = target.position; target.position = Position(x=x, y=4)
    engine._append_event('MOVEMENT_COMMITTED', 'test:position', actor_id=target.entity_id,
        payload={'destination': target.position.model_dump(mode='json'),
                 'path': [before.model_dump(mode='json'), target.position.model_dump(mode='json')], 'cost_ft': 0})


def checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_court_native_attack_reach_five_ten_five_through_expiry_and_reload(monkeypatch, tmp_path):
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    service, ui, mid = H.table_fight(tmp_path, [COURT])
    def setup(engine):
        actor = engine.state.actors[H.LEFT]
        engine._gain_resource(actor, 'resource:core.martial_focus', 1, 'test:focus')
        move_fixture(engine, engine.state.actors[H.RIGHT], 5)
    H.on_hold(monkeypatch, setup)
    assert act(ui, mid, H.HOLD)['status'] == 'COMMITTED'
    e = service._load_session(mid).engine; action = natural(e)
    assert attack_reach.maximum(e, e.state.actors[H.LEFT], action) == 5
    assert not any(c.source_definition_id == action.source_definition_id and c.target_ids == (H.RIGHT,) for c in e.legal_candidates())
    def activate(ctx):
        if ctx.typed.get('source') == COURT:
            apply_reach(ctx.engine, ctx.actor, ctx.source, 5)
    install(monkeypatch, 'technique_final', activate)
    commit(cast_sender(service, ui, mid, 'Court of One Hundred Forms'))
    e = checked(tmp_path, mid); actor = e.state.actors[H.LEFT]
    assert attack_reach.maximum(e, actor, natural(e)) == 10
    before = e.state.model_dump(mode='json')
    for _ in range(2):
        assert any(c.source_definition_id == action.source_definition_id and c.target_ids == (H.RIGHT,) for c in e.legal_candidates())
    assert e.state.model_dump(mode='json') == before
    commit(cast_sender(service, ui, mid, action.display_name, target=H.RIGHT))
    e = checked(tmp_path, mid)
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == action.source_definition_id for ev in e.events)
    # The actual ten-round clock, not an invented expiry token or catalog reset.
    for _ in range(40):
        if not any(c.condition_id == STATE for c in e.state.actors[H.LEFT].conditions.values()):
            break
        assert act(ui, mid, 'end')['status'] == 'COMMITTED'
        e = service._load_session(mid).engine
    else:
        raise AssertionError('Court reach did not expire after ten rounds')
    turn(ui, mid, H.LEFT)
    e = checked(tmp_path, mid)
    assert attack_reach.maximum(e, e.state.actors[H.LEFT], natural(e)) == 5
    assert not any(c.source_definition_id == action.source_definition_id and c.target_ids == (H.RIGHT,) for c in e.legal_candidates())


def test_briar_reach_applies_to_native_opportunity_attack_and_reloads(monkeypatch, tmp_path):
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    service, ui, mid = H.table_fight(tmp_path, [BRIAR, COURT])
    def setup(engine):
        apply_reach(engine, engine.state.actors[H.LEFT], BRIAR, 10)
        move_fixture(engine, engine.state.actors[H.RIGHT], 6)
    H.on_hold(monkeypatch, setup)
    assert act(ui, mid, H.HOLD)['status'] == 'COMMITTED'
    e = checked(tmp_path, mid)
    assert attack_reach.maximum(e, e.state.actors[H.LEFT], natural(e)) == 15
    assert e._typed_opportunity_reach(e.state.actors[H.LEFT]) == 15
    turn(ui, mid, H.RIGHT)
    e = service._load_session(mid).engine
    candidate = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=7, y=4))
    assert ui.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, ui.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    e = checked(tmp_path, mid)
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == H.LEFT and ev.source_definition_id.endswith('.opportunity_attack') for ev in e.events)
    assert not e.state.actors[H.LEFT].reaction_available


def test_duplicate_source_and_expired_or_removed_condition_never_add_twice(monkeypatch):
    e = duel([COURT]); actor = e.state.actors[ME]; action = natural(e, ME)
    apply_reach(e, actor, COURT, 5)
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    monkeypatch.setitem(ext._HOOKS, 'attack_reach_bonus', [reach_reply, reach_reply])
    assert attack_reach.maximum(e, actor, action) == 10
    variant = action.model_copy(update={'source_definition_id': action.source_definition_id + '#variant'})
    assert attack_reach.maximum(e, actor, variant) == 10
    condition = next(c for c in actor.conditions.values() if c.condition_id == STATE)
    condition.expires_on = round_token(e, 1)
    e.state.round_number += 1
    before = e.state.model_dump(mode='json')
    assert attack_reach.maximum(e, actor, action) == 5
    assert e.state.model_dump(mode='json') == before
    actor.conditions.clear()
    assert attack_reach.maximum(e, actor, action) == 5


def test_reach_lost_in_before_attack_rechecks_before_rolling_and_reloads(monkeypatch, tmp_path):
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    service, ui, mid = H.table_fight(tmp_path, [COURT])
    def setup(engine):
        apply_reach(engine, engine.state.actors[H.LEFT], COURT, 5)
        move_fixture(engine, engine.state.actors[H.RIGHT], 5)
    H.on_hold(monkeypatch, setup)
    assert act(ui, mid, H.HOLD)['status'] == 'COMMITTED'
    e = service._load_session(mid).engine
    action = natural(e)
    before_hp = e.state.actors[H.RIGHT].current_hp
    def expire(engine, actor, target, intent, context):
        if actor.entity_id == H.LEFT:
            engine._remove_condition(actor, STATE, 'test:reach_ended')
        # No reply is needed for a recorded intervening condition removal.
    install(monkeypatch, 'before_attack', expire)
    commit(cast_sender(service, ui, mid, action.display_name, target=H.RIGHT))
    e = checked(tmp_path, mid)
    assert e.state.actors[H.RIGHT].current_hp == before_hp
    assert not any(ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == action.source_definition_id for ev in e.events)
    assert attack_reach.maximum(e, e.state.actors[H.LEFT], natural(e)) == 5


@pytest.mark.parametrize('same_group,expected', [(True, 15), (False, 20)])
def test_largest_same_group_and_additive_independent_sources(monkeypatch, same_group, expected):
    e = duel([COURT]); actor = e.state.actors[ME]
    apply_reach(e, actor, COURT, 5)
    apply_reach(e, actor, BRIAR, 10)
    conditions = list(c for c in actor.conditions.values() if c.condition_id == STATE)
    providers = []
    for condition in conditions:
        row = {'source_id': condition.source_definition_id, 'feet': condition.data['feet'], 'condition_id': condition.instance_id}
        if same_group:
            row['stacking_group'] = 'test:same_printed_increase'
        providers.append(lambda *args, reply=row: reply)
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'attack_reach_bonus', providers)
    assert attack_reach.maximum(e, actor, natural(e, ME)) == expected
    ranged = natural(e, ME).model_copy(update={'range_ft': 120, 'resolution_kind': 'ATTACK', 'parameters': {}})
    assert attack_reach.maximum(e, actor, ranged) == 120


def test_own_turn_contribution_never_extends_opportunity_reach(monkeypatch):
    e = duel([COURT]); actor = e.state.actors[ME]
    apply_reach(e, actor, COURT, 5)
    next(c for c in actor.conditions.values() if c.condition_id == STATE).data['own_turn'] = True
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    assert attack_reach.maximum(e, actor, natural(e, ME)) == 10
    assert e._typed_opportunity_reach(actor) == 5


@pytest.mark.parametrize('reply', [{'feet': True}, {'feet': -5}, {'feet': 5, 'unknown': 1}])
def test_reach_query_rejects_bad_provider_without_mutation(monkeypatch, reply):
    e = duel([COURT]); actor = e.state.actors[ME]
    install(monkeypatch, 'attack_reach_bonus', lambda *args: reply)
    before = e.state.model_dump(mode='json')
    with pytest.raises(ValueError):
        attack_reach.maximum(e, actor, natural(e, ME))
    assert e.state.model_dump(mode='json') == before
