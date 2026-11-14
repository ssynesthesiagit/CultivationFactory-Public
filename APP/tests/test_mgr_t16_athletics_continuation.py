"""5F2: terminal journey checkpoints through real tables and cold disk reloads."""
import json
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_mgr_t16_athletics_travel import game, activate, A, B, ROOT


SPOTS = {A: {'x': 3, 'y': 6}, B: {'x': 8, 'y': 6}}


def party(tmp_path, monkeypatch):
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    return game(tmp_path, monkeypatch, battlefield=arena)


def condition(aid, iid, cid, *, timed=False):
    row = dict(instance_id=iid, condition_id=cid, source_definition_id='test:prior_effect',
               source_actor_id=aid, target_id=aid, stacks=1, applied_sequence=0,
               expires_on='TURN_END' if timed else 'UNTIL_REMOVED', data={})
    if timed:
        row['expires_turn_count'] = 100
    return json.dumps(row)


def seed(cold, jid, aid, *, hp=20, life='CONSCIOUS', conditions=None, saves=None, initiative=None):
    session = cold().journeys.load(jid)
    snapshot = dict(maximum_hp=60, current_hp=hp, temporary_hp=0, active=1,
                    life_state=life, conditions=conditions or {})
    if saves is not None:
        snapshot['death_saves'] = saves
    session.state['actors'][aid]['encounter_snapshot'] = snapshot
    if initiative is not None:
        session.state['actors'][aid]['bundle']['actor_template']['initiative_bonus'] = initiative
    with cold().journeys.locked(jid):
        cold().journeys.save(session)


def finish(cold, mid):
    for _ in range(20):
        fresh = cold()
        if fresh._load_session(mid).engine.state.terminal_result is not None:
            return
        table = TabletopService(fresh, fresh.userdata_root)
        menu = table.state(mid)['menu']
        table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0)
    pytest.fail('Round-capped table did not finish')


def test_f1_terminal_timed_effect_can_be_explicitly_resolved_and_released(tmp_path, monkeypatch):
    cold, jid, act = party(tmp_path, monkeypatch)
    activate(act)
    seed(cold, jid, A, conditions={'timed': condition(A, 'timed', 'stunned', timed=True),
                                  'injury': condition(A, 'injury', 'prone')})
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=1, positions=SPOTS)['match_id']
    # Resolution is unavailable while a fight is live; stale/invalid requests
    # must never release ownership or change the ledger.
    bound = cold().journey_state(jid)
    with pytest.raises(ValueError, match='Finish'):
        cold().journey_resume(jid, bound['revision'], effect_resolutions={A: 'GM ends the stun.'})
    finish(cold, mid)
    terminal = cold()._load_session(mid).engine.state.model_dump(mode='json')
    assert 'timed' in terminal['actors'][A]['conditions']
    for kwargs in ({}, {'effect_resolutions': {A: ''}}, {'effect_resolutions': {'unknown': 'Ended'}}):
        with pytest.raises(ValueError):
            cold().journey_resume(jid, bound['revision'], **kwargs)
        assert cold().journey_state(jid) == bound
    with pytest.raises(ValueError, match='Refresh'):
        cold().journey_resume(jid, bound['revision'] - 1, effect_resolutions={A: 'Ended'})
    # Exercise the real HTTP request/forwarding path without a socket/browser.
    import asyncio
    import httpx
    from app.api import create_app
    from app.core import Settings
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    async def resume():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            token = (await client.get('/api/session')).json()['token']
            response = await client.post(f'/api/combat/journeys/{jid}/resume', headers={'x-foundry-token': token},
                json={'revision': bound['revision'], 'effect_resolutions': {A: 'GM confirms the stun has ended.'}})
            assert response.status_code == 200, response.text
            return response.json()
    resumed = asyncio.run(resume())
    assert cold().journey_state(jid) == resumed
    actor = resumed['actors'][A]
    assert actor['incapacitated'] == 0
    assert actor['encounter_snapshot']['current_hp'] == terminal['actors'][A]['current_hp'] == 20
    assert actor['resources'] == terminal['actors'][A]['resources']
    assert set(actor['encounter_snapshot']['conditions']) == {'injury'}
    receipt = next(e for e in resumed['events'] if e['kind'] == 'ENCOUNTER_EFFECTS_RESOLVED')
    assert receipt['reason'] == 'GM confirms the stun has ended.'
    assert json.loads(receipt['previous_state']) == terminal['actors'][A]
    assert cold()._load_session(mid).engine.state.model_dump(mode='json') == terminal
    act('finish')
    newer = cold().create_journey(project_ids=['traveller', 'companion'], arena_id='scene',
                                 positions=SPOTS, base_paces={A: 5, B: 5})
    assert newer['actors'][A]['encounter_snapshot'] == actor['encounter_snapshot']
    assert newer['actors'][A]['resources'] == actor['resources']
    second = cold().journey_start_combat(newer['journey_id'], newer['revision'],
                                        {A: 'team:a', B: 'team:b'}, positions=SPOTS)
    survivor = cold()._load_session(second['match_id']).engine.state.actors[A]
    assert survivor.current_hp == 20 and 'injury' in survivor.conditions and 'timed' not in survivor.conditions


def test_f2_death_save_progress_survives_two_encounters_and_cold_tables(tmp_path, monkeypatch):
    from combat.ext.life_state import UNCONSCIOUS, encounter_death_saves, is_deceased
    from tests.test_mgr_t16_athletics_strict_journey import death_failures
    cold, jid, _ = party(tmp_path, monkeypatch)
    # Deterministic dice transport only; no live model/embedding client.
    death_failures(monkeypatch)
    seed(cold, jid, B, hp=0, life='DYING', conditions={
        'unconscious': condition(B, 'unconscious', UNCONSCIOUS)}, saves={'ok': 1, 'bad': 1}, initiative=1000)
    # Forced initiative puts companion first: the first save now occurs during
    # initialization, so one round still proves exactly one save per encounter.
    first = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'},
                                        maximum_rounds=1, positions=SPOTS)
    finish(cold, first['match_id'])
    dying = cold()._load_session(first['match_id']).engine.state.actors[B]
    assert dying.life_state == 'DYING' and dying.active
    assert encounter_death_saves(dying) == {'ok': 1, 'bad': 2}
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    assert cold().journey_state(jid)['actors'][B]['encounter_snapshot']['death_saves'] == {'ok': 1, 'bad': 2}
    second = cold().journey_start_combat(jid, resumed['revision'], {A: 'team:a', B: 'team:b'},
                                         maximum_rounds=2, positions=SPOTS)
    finish(cold, second['match_id'])
    dead = cold()._load_session(second['match_id']).engine.state.actors[B]
    # The next ordinary failure is the third and kills it, rather than starting
    # a fresh count. This asserts runtime consequences, not snapshot equality.
    assert is_deceased(dead) and not dead.active
    assert encounter_death_saves(dead) == {'ok': 1, 'bad': 3}


def test_resume_request_exposes_explicit_resolution():
    from app.models import JourneyResumeRequest
    assert JourneyResumeRequest(revision=3, effect_resolutions={A: 'GM ended the effect.'}).model_dump() == {
        'revision': 3, 'effect_resolutions': {A: 'GM ended the effect.'}}


@pytest.mark.parametrize('maximum,current', [(50, 20), (70, 65)])
def test_explicit_resolution_clears_untransferable_state_without_healing(tmp_path, monkeypatch, maximum, current):
    from combat.ext.journey_setup import encounter_snapshot
    from combat.ext.life_state import restore_encounter_death_saves
    from combat.concentration import HELD
    from combat.gate2_runtime_models import ConcentrationState, MaximumHPAdjustment, ModifierInstance, ConditionInstance
    cold, jid, _ = party(tmp_path, monkeypatch)
    mid = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, positions=SPOTS)['match_id']
    actor = cold()._load_session(mid).engine.state.actors[A].model_copy(deep=True)
    actor.current_hp = min(actor.current_hp, maximum)
    actor.maximum_hp = maximum
    actor.maximum_hp_base = 60
    actor.current_hp = current
    actor.temporary_hp = 9
    actor.maximum_hp_adjustments['adjustment'] = MaximumHPAdjustment(amount=maximum - 60,
        source_id='test:effect', source_actor_id=A, label='Changed maximum HP')
    actor.transformed_size_category = 'Large'
    actor.concentration = ConcentrationState(source_definition_id='test:effect', started_sequence=0)
    actor.modifiers['modifier'] = ModifierInstance(modifier_id='modifier', source_definition_id='test:effect',
        source_actor_id=A, target_id=A, target_field='armor_class', operation='ADD', value=2, applies_to='ALL')
    actor.conditions['held'] = ConditionInstance.model_validate(json.loads(condition(A, 'held', HELD)))
    actor.conditions['injury'] = ConditionInstance.model_validate(json.loads(condition(A, 'injury', 'prone')))
    restore_encounter_death_saves(actor, {'ok': 1, 'bad': 2})
    original = actor.model_dump(mode='json')
    with pytest.raises(ValueError, match='encounter effects'):
        encounter_snapshot(actor)
    snapshot = encounter_snapshot(actor, effects_ended=True)
    assert snapshot['current_hp'] == min(current, 60) and snapshot['maximum_hp'] == 60
    assert snapshot['temporary_hp'] == 9 and snapshot['death_saves'] == {'ok': 1, 'bad': 2}
    assert set(snapshot['conditions']) == {'injury'}
    assert actor.model_dump(mode='json') == original
