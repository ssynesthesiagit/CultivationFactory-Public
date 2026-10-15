"""Lightning flight and limited chosen melee shock, through persisted tables."""
import pytest
from combat import flight
from combat.ext import lightning_riders as lightning
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, turn, action_sender

SOVEREIGN = 'TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION'
BODY = 'TAL_LIGHTNING_LIGHTNING_GOD_BODY'
WINGS = lightning.WINGS
BURST = 'TAL_LIGHTNING_LIGHTNING_WINGS_BURST'


def ascend(combat, table, mid):
    state = table.state(mid)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
        if c.destination is not None and c.metadata.get('movement_mode') == 'fly'
        and (c.destination.x, c.destination.y, c.destination.z) == (3, 6, 1))
    menu = state['menu']
    return table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], [])


@pytest.mark.parametrize('owned', [False, True])
def test_wings_flight_requires_owned_feature_and_body_state(tmp_path, owned):
    combat, table, mid = fight(tmp_path, [BODY, *([WINGS] if owned else [])])
    engine = reload(combat, mid)
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == 0
    assert act(table, mid, 'Lightning-God Body')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[LEFT]) == 40
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == (40 if owned else 0)
    if owned:
        assert ascend(combat, table, mid)['status'] == 'COMMITTED'
        assert reload(combat, mid).state.actors[LEFT].position.z == 1


@pytest.mark.parametrize('ai', [False, True])
def test_sovereign_grants_hover_without_adding_land_speed(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [SOVEREIGN])
    assert action_sender(combat, table, mid, SOVEREIGN, ai=ai)([])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert actor.position.z == 0 and engine._effective_speed(actor) == 30
    assert flight.profile(engine, actor).speed_ft == 60 and flight.profile(engine, actor).hover
    assert actor.resources['resource:core.qi'] == 97
    if not ai:
        assert ascend(combat, table, mid)['status'] == 'COMMITTED'
        assert reload(combat, mid).state.actors[LEFT].position.z == 1


@pytest.mark.parametrize('cl,sustain', [(5, False), (15, False), (15, True)])
def test_wings_burst_duration_and_concentration_commit(tmp_path, cl, sustain):
    combat, table, mid = fight(tmp_path, [BURST], cl=cl)
    send = action_sender(combat, table, mid, BURST)
    result = send([])
    if cl >= 11:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        result = send([{**prompt['context'], 'selection': 'USE' if sustain else 'DECLINE',
            'option_ids': ['SUSTAIN'] if sustain else []}])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert flight.profile(engine, actor).speed_ft == 30
    assert actor.resources['resource:core.qi'] == 99 and actor.position.z == 0
    assert bool(actor.concentration) == sustain
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == (30 if sustain else 0)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == 0
    assert engine.state.actors[LEFT].concentration is None


@pytest.mark.parametrize('owned,ai,accept', [(False, False, False), (True, False, True), (True, False, False), (True, True, True)])
def test_electric_fist_choice_and_pb_uses_survive_rounds(tmp_path, owned, ai, accept):
    combat, table, mid = fight(tmp_path, [lightning.FIST] if owned else [], left_score=30, right_score=14)
    for index in range(5):
        send = action_sender(combat, table, mid, 'Unarmed Strike', ai=ai, target_id=RIGHT)
        result = send([])
        if owned and not ai and (not accept or index < 4):
            assert result['status'] == 'REACTION_REQUIRED', result
            prompt = result['reaction']
            assert 'Electric Fist Method' in str(prompt) and 'Visitor' in str(prompt)
            result = send([{**prompt['context'], 'selection': 'USE' if accept else 'DECLINE',
                'option_ids': ['SHOCK'] if accept else []}])
        assert result['status'] == 'COMMITTED', result
        engine = reload(combat, mid)
        target = engine.state.actors[RIGHT]
        assert engine._effective_speed(target) == (20 if owned and accept and index < 4 else 30)
        if owned and accept and index < 4:
            saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
            assert saved.payload['dc'] == 100
        counter = next((c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == lightning.FIST_USES), None)
        assert (counter.data['uses'] if counter else 0) == (min(index + 1, 4) if owned and accept else 0)
        if ai:
            combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)


@pytest.mark.parametrize('talents,activation', [([SOVEREIGN], SOVEREIGN), ([BODY, WINGS], BODY)])
def test_lightning_state_flight_ends_with_incapacitation(tmp_path, talents, activation):
    combat, table, mid = fight(tmp_path, talents,
        cause=[{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target', 'duration': 'until_removed'}])
    assert act(table, mid, activation)['status'] == 'COMMITTED'
    assert ascend(combat, table, mid)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == 0
