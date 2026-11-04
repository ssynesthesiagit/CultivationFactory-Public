"""API decisions pause for the player and resume the identical stored action.

fix/hunt23 (247d3b85, merged ee4b718f; approved FIX23r3.review.md)
adds Flowing Evasion's printed post-damage movement choices. A USE answer must
resolve distance and destination before committing; DECLINE has neither choice.
Every API case below still requires one provider call and transactional resumption.
"""
import json
import zipfile

import httpx
import pytest

from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX, AI_RESPONSE_SCHEMA
from combat.gate3_reducer import canonical_state_sha256
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.test_lock4_flowing_evasion import sheet, ROOT, FLOWING
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

ATTACK_PROJECT, DEFEND_PROJECT = 'aaaaaaaa', 'dddddddd'
ATTACKER, DEFENDER = FACTORY_ACTOR_PREFIX + ATTACK_PROJECT, FACTORY_ACTOR_PREFIX + DEFEND_PROJECT


class Provider:
    def __init__(self):
        self.calls = 0
        self.payload = None

    def status(self):
        return {'ready': True}

    def complete_json(self, *, prompt_text, **kwargs):
        self.calls += 1
        frame = json.loads(prompt_text.split('\n\n', 1)[1])
        candidate = next(c for c in frame['legal_candidates'] if c['display_name'].startswith('Dao'))
        self.payload = {key: candidate[key] for key in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
        self.payload.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
        return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': self.payload, 'rationale': 'Use the chosen Dao attack.'},
                'provider_id': 'test:offline', 'model': 'fake', 'request_sha256': 'test-request'}


def table_fight(tmp_path, monkeypatch, *, ask=True, defender_mode='MANUAL'):
    for name in (ATTACK_PROJECT, DEFEND_PROJECT):
        content = sheet(name == DEFEND_PROJECT)
        if name == ATTACK_PROJECT:
            content['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}}]
        archive = tmp_path / 'portable_characters' / name / 'current.zip'
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(content))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(DEFEND_PROJECT, {'mode': 'ask' if ask else 'auto'}, {FLOWING})
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:critical', 'operation': 'replace', 'natural_result': 20})
    provider = Provider()
    service = CombatService(ROOT, tmp_path, ai_provider=provider)
    service.tabletop_maps.save({'display_name': 'API yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4]]}})
    view = service.create_factory_match(project_ids=[ATTACK_PROJECT], opponent_actor_ids=[DEFENDER],
        control_modes={ATTACKER: 'MANUAL', DEFENDER: 'MANUAL'}, arena_id='battlefield:map.api-yard', match_seed='LOCK4-API')
    mid, table = view['match_id'], TabletopService(service, tmp_path)
    if table.state(mid)['menu']['actor_id'] != ATTACKER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    service.set_controller_mode(mid, actor_id=ATTACKER, controller_mode='API_AUTO')
    service.set_controller_mode(mid, actor_id=DEFENDER, controller_mode=defender_mode)
    return service, table, mid, provider


def answer(context, selection='USE'):
    return {key: context[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')} | {
        'selection': selection, 'option_ids': ['halve'] if selection == 'USE' else []}


def evasion_answer(context, source):
    assert context['reaction_source_id'] == 'choice:needle.flowing_evasion_' + source
    assert context['reactor_id'] == DEFENDER
    trigger = context['choice_trigger']
    assert 'Flowing Evasion' in trigger['prompt']
    assert not trigger['allow_decline']
    options = trigger['needle_options']
    option = '5' if source == 'distance' else trigger['preferred'][0]
    assert option in options
    return {**answer(context), 'option_ids': [option]}


def finish_evasion(service, mid, result):
    """Require both reviewed movement choices, preserving rollback at each pause."""
    before = canonical_state_sha256(service._load_session(mid).engine.state)
    destination = None
    for source in ('distance', 'move'):
        assert result['status'] == 'AWAITING_REACTION'
        assert canonical_state_sha256(service._load_session(mid).engine.state) == before
        response = evasion_answer(result['reaction_context'], source)
        if source == 'move':
            destination = dict(zip(('x', 'y'), map(int, response['option_ids'][0][5:].split(','))))
        # Restart at every choice; stored answers must survive without a provider.
        service = CombatService(ROOT, service.userdata_root)
        result = service.provider_step(mid, [response])
    assert result['status'] == 'COMMITTED'
    loaded = service._load_session(mid)
    assert loaded.engine.state.actors[DEFENDER].position.model_dump(mode='json') == destination
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return result


@pytest.mark.parametrize('selection', ['USE', 'DECLINE'])
def test_provider_called_once_and_exact_decision_resumes_after_restart(tmp_path, monkeypatch, selection):
    service, table, mid, provider = table_fight(tmp_path, monkeypatch)
    before = service._load_session(mid).engine.state
    first = table.auto_step(mid, 0)
    assert first['status'] == 'REACTION_REQUIRED' and provider.calls == 1
    assert 'Flowing Evasion' in json.dumps(first['reaction'])
    assert canonical_state_sha256(service._load_session(mid).engine.state) == canonical_state_sha256(before)
    pending = service._read_metadata(mid)['pending_provider_decision']
    assert pending['payload'] == provider.payload and pending['rationale'] == 'Use the chosen Dao attack.'
    # A fresh service has no provider attached; answering must not require another completion.
    reopened = CombatService(ROOT, tmp_path)
    repeated = reopened.provider_step(mid)
    assert repeated['status'] == 'AWAITING_REACTION'
    result = reopened.provider_step(mid, [answer(repeated['reaction_context'], selection)])
    if selection == 'USE':
        result = finish_evasion(reopened, mid, result)
    assert result['status'] == 'COMMITTED' and provider.calls == 1
    loaded = reopened._load_session(mid)
    assert 'pending_provider_decision' not in reopened._read_metadata(mid)
    assert loaded.engine.state.actors[DEFENDER].resources['resource:core.qi'] == before.actors[DEFENDER].resources['resource:core.qi'] - (2 if selection == 'USE' else 0)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    records = [json.loads(line) for line in (loaded.store.match_dir / 'ProviderController.ndjson').read_text().splitlines()]
    assert len(records) == 1 and records[0]['candidate_id'] == provider.payload['candidate_id']
    assert records[0]['rationale'] == pending['rationale']


def test_ai_controlled_ask_me_reactor_decides_automatically(tmp_path, monkeypatch):
    service, _, mid, provider = table_fight(tmp_path, monkeypatch, defender_mode='LOCAL_AUTO')
    assert service.provider_step(mid)['status'] == 'COMMITTED'
    assert provider.calls == 1 and 'pending_provider_decision' not in service._read_metadata(mid)


def test_direct_ai_execute_accepts_answers_and_rejects_stale_extra_answer(tmp_path, monkeypatch):
    service, _, mid, provider = table_fight(tmp_path, monkeypatch)
    frame = service.ai_frame(mid)
    payload = provider.complete_json(prompt_text=frame['frame_text'])['value']['action_intent']
    token = service.ai_validate(mid, payload)['validation_token']
    first = service.ai_execute(mid, payload, token)
    assert first['status'] == 'AWAITING_REACTION'
    response = answer(first['reaction_context'])
    before = canonical_state_sha256(service._load_session(mid).engine.state)
    responses = [response]
    distance = service.ai_execute(mid, payload, token, reactions=responses)
    assert distance['status'] == 'AWAITING_REACTION'
    responses.append(evasion_answer(distance['reaction_context'], 'distance'))
    move = service.ai_execute(mid, payload, token, reactions=responses)
    assert move['status'] == 'AWAITING_REACTION'
    responses.append(evasion_answer(move['reaction_context'], 'move'))
    assert canonical_state_sha256(service._load_session(mid).engine.state) == before
    extra = {**response, 'checkpoint': 'stale:other-attack'}
    with pytest.raises(CombatServiceError, match='no longer applies'):
        service.ai_execute(mid, payload, token, reactions=[*responses, extra])
    assert canonical_state_sha256(service._load_session(mid).engine.state) == before
    assert service.ai_execute(mid, payload, token, reactions=responses)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    destination = dict(zip(('x', 'y'), map(int, responses[-1]['option_ids'][0][5:].split(','))))
    assert loaded.engine.state.actors[DEFENDER].position.model_dump(mode='json') == destination
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    with pytest.raises(CombatServiceError):
        service.ai_execute(mid, payload, token, reactions=responses)


def test_changed_state_discards_pending_decision_and_rejects_old_answers(tmp_path, monkeypatch):
    service, _, mid, provider = table_fight(tmp_path, monkeypatch)
    first = service.provider_step(mid)
    response = answer(first['reaction_context'])
    # Commit an independently checked legal end-turn, simulating another authorized client.
    context = service.decision(mid)['context']
    candidate = next(c for c in context['legal_candidates'] if c['kind'] == 'END_TURN')
    payload = {key: candidate[key] for key in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
    payload.update(decision_id=context['decision_id'], state_version=context['state_version'])
    checked = service.ai_validate(mid, payload)
    assert service.ai_execute(mid, payload, checked['validation_token'])['status'] == 'COMMITTED'
    with pytest.raises(CombatServiceError, match='fight changed'):
        service.provider_step(mid, [response])
    assert 'pending_provider_decision' not in service._read_metadata(mid) and provider.calls == 1


def test_wrong_prompt_answer_is_rejected_without_poisoning_pending_choice(tmp_path, monkeypatch):
    service, _, mid, provider = table_fight(tmp_path, monkeypatch)
    first = service.provider_step(mid)
    response = answer(first['reaction_context'])
    pending = service._read_metadata(mid)['pending_provider_decision']
    with pytest.raises(CombatServiceError, match='waiting reaction'):
        service.provider_step(mid, [{**response, 'checkpoint': 'stale:choice'}])
    assert service._read_metadata(mid)['pending_provider_decision'] == pending
    result = service.provider_step(mid, [response])
    assert finish_evasion(service, mid, result)['status'] == 'COMMITTED' and provider.calls == 1


def test_two_player_prompts_keep_first_answer_across_restart(tmp_path, monkeypatch):
    from combat.ext.needle import ask, CHOICE
    def second_choice(engine, kind, kwargs):
        if kind == 'DAMAGE_COMMITTED' and kwargs.get('target_ids') == (DEFENDER,):
            target = engine.state.actors[DEFENDER]
            ask(engine, engine._active_intent, 'test:second-choice', target, CHOICE + 'second-check', ['finish'],
                prompt='Finish resolving this attack?', name='Second test choice', allow_decline=True, default='decline')
    install(monkeypatch, 'event', second_choice)
    service, _, mid, provider = table_fight(tmp_path, monkeypatch)
    before = canonical_state_sha256(service._load_session(mid).engine.state)
    first = service.provider_step(mid)
    second = service.provider_step(mid, [answer(first['reaction_context'])])
    assert second['status'] == 'AWAITING_REACTION'
    assert second['reaction_context']['checkpoint'] == 'test:second-choice'
    assert canonical_state_sha256(service._load_session(mid).engine.state) == before
    pending = service._read_metadata(mid)['pending_provider_decision']
    assert len(pending['reactions']) == 1
    restarted = CombatService(ROOT, tmp_path)
    last_answer = answer(second['reaction_context'], 'DECLINE')
    result = restarted.provider_step(mid, [last_answer])
    assert finish_evasion(restarted, mid, result)['status'] == 'COMMITTED'
    assert provider.calls == 1 and restarted._load_session(mid).verify()['status'] == 'PASS'


def test_http_provider_and_execute_routes_transport_answers_without_services(tmp_path, monkeypatch):
    from tests.async_support import run_asgi
    from app.api import create_app
    from app.core import Settings
    service, _, mid, provider = table_fight(tmp_path, monkeypatch)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.combat.ai_provider = provider
    async def exercise():
        # In-process ASGI; no server, startup/shutdown service hooks, network or real provider.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            session = await client.get('/api/session')
            assert session.status_code == 200, session.text
            token = session.json()['token']
            headers = {'x-foundry-token': token}
            first = await client.post(f'/api/combat/matches/{mid}/provider-step', headers=headers)
            assert first.status_code == 200, first.text
            body = first.json()
            assert body['status'] == 'AWAITING_REACTION'
            pending = service._read_metadata(mid)['pending_provider_decision']
            done = await client.post(f'/api/combat/matches/{mid}/ai-intent/execute', headers=headers,
                json={'action_intent': pending['payload'], 'validation_token': pending['validation_token'],
                      'reactions': [answer(body['reaction_context'], 'DECLINE')]})
            assert done.status_code == 200 and done.json()['status'] == 'COMMITTED', done.text
    run_asgi(exercise())
    assert provider.calls == 1
    assert 'pending_provider_decision' not in service._read_metadata(mid)
