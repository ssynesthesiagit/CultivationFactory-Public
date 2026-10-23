"""Regression tests for the Sol seam review blocking findings on Emotion Cultivator."""
from fractions import Fraction
import pytest
from combat.ext import emotion_cultivator as E
from combat.ext import emotion_continuation as C
from combat.ext.emotion_cultivator import WEATHER, WEAVER
from tests import test_a2_qi_subpaths_1_service as Q


def weather_held(engine, aid):
    rows = Q.conditions(engine.state.actors[aid], 'heart_weather')
    assert len(rows) == 1
    return rows[0]


def journey(tmp_path, monkeypatch, docs, *, positions, arena=None):
    """One real journey over synthetic sheets, shared by the service-level checks."""
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from tests.h1_support import ROOT
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid: docs[pid])
    arena = arena or {'stable_id': 'emotion:scene', 'width_squares': 10, 'height_squares': 10,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    ids = [FACTORY_ACTOR_PREFIX + pid for pid in docs]
    state = cold().create_journey(project_ids=list(docs), arena_id='scene', positions=positions,
        base_paces={aid: 5 for aid in ids}, control_modes={aid: 'MANUAL' for aid in ids})
    return cold, state['journey_id']


def test_weather_change_keeps_the_held_instance_and_its_concentration(tmp_path, monkeypatch):
    # Finding 1: changing weather must update the held aura in place, keeping
    # its instance, source, and Concentration ledger entry.
    svc, table, mid = Q.fight(tmp_path, [WEATHER], cl=18)
    Q.use(table, mid, 'Weather of the Heart: Calm (centered on you)', target=Q.ME, answer=lambda p: None)
    engine = Q.cold(svc, mid)
    before = weather_held(engine, Q.ME)
    assert engine.state.actors[Q.ME].concentration is not None
    monkeypatch.setattr(E, 'pick', lambda *args, **kwargs: ['joy'])
    ctx = E.context_for(engine, engine.state.actors[Q.ME], WEATHER)
    assert ctx is not None
    E.change_weather(ctx, {})
    after = weather_held(engine, Q.ME)
    assert after.data['weather'] == 'joy'
    assert after.instance_id == before.instance_id
    assert after.source_definition_id == before.source_definition_id
    assert after.expires_on == before.expires_on
    assert engine.state.actors[Q.ME].concentration is not None


def test_weather_calm_failed_save_reduces_speed_by_ten_feet(tmp_path, monkeypatch):
    # Finding 2 (printed-outcome check): Weather of Calm's failed save reduces
    # Speed by 10 feet; the Pulse Hostile Calm failure does not.
    from combat import typed_executor
    from combat.ext.emotion_cultivator import weather_trigger
    svc, table, mid = Q.fight(tmp_path, [WEATHER], cl=18)
    Q.use(table, mid, 'Weather of the Heart: Calm (centered on you)', target=Q.ME, answer=lambda p: None)
    engine = Q.cold(svc, mid)
    seen = []
    monkeypatch.setattr(typed_executor, 'run_effects', lambda ctx, effects, *a, **k: seen.append(effects))
    weather_trigger(engine, engine.state.actors[Q.ME], weather_held(engine, Q.ME), engine.state.actors[Q.FOE], None)
    saves = [e for effects in seen for e in effects if e.get('type') == 'save']
    assert saves, 'the Weather save must run for the creature in the aura'
    assert any(e.get('type') == 'speed' and e.get('flat') == -10 for e in saves[0]['on_fail'])


def test_restored_concentration_deadline_targets_the_restored_copy(monkeypatch):
    # Finding 3: after journey continuation, the concentration deadline must
    # point at the restored copy's new start sequence, not the old one.
    import json
    from types import SimpleNamespace
    from combat import concentration, effect_continuation
    from combat.ext import effect_durations
    old_copy = {'started_sequence': 5, 'source_definition_id': WEATHER}
    deadline = {'instance_id': 'deadline-1', 'condition_id': C.DEADLINE,
        'data': {'started_sequence': 5, 'hidden': True}}
    other = {'instance_id': 'other-1', 'condition_id': 'condition:typed.heart_weather',
        'data': {'started_sequence': 9}}
    data = {'copies': [{'instance': json.dumps(old_copy), 'order': 0}],
        'records': [{'kind': 'condition', 'instance': json.dumps(deadline), 'remaining': [1, 1]},
                    {'kind': 'condition', 'instance': json.dumps(other), 'remaining': [1, 1]}]}
    actor = SimpleNamespace(entity_id='a', conditions={})
    engine = SimpleNamespace(typed_bundle_documents=[{'actor_id': 'a',
        'journey_setup': {'emotion_continuation': json.dumps(data)}}],
        state=SimpleNamespace(actors={'a': actor}, match_id='m', event_sequence=0))
    monkeypatch.setattr(concentration, 'restore_copy', lambda engine, actor, previous, **kw: SimpleNamespace(started_sequence=77))
    restored = []
    monkeypatch.setattr(effect_continuation, 'restore_condition',
        lambda engine, target, condition, *, expires_on: restored.append(condition))
    monkeypatch.setattr(effect_durations, 'expiry_after_seconds', lambda engine, left: 'EXPIRES')
    C.restore(engine)
    by_id = {row['instance_id']: row for row in restored}
    assert by_id['deadline-1']['data']['started_sequence'] == 77
    assert by_id['other-1']['data'] == {'started_sequence': 9}


def test_joy_temporary_hp_goes_only_to_allies_the_owner_chose(tmp_path):
    # Finding 2: an ally inside a Joy aura receives Temporary HP only when the
    # owner selected that ally at activation. With no selection, none is granted.
    svc, table, mid = Q.fight(tmp_path, [WEATHER], cl=18)
    Q.use(table, mid, 'Weather of the Heart: Joy (centered on you)', target=Q.ME, answer=lambda p: None)
    Q.S.to_thief(table, mid, end_thief=True)
    engine = Q.cold(svc, mid)
    assert engine.state.actors[Q.ALLY].temporary_hp == 0


class _Session:
    def __init__(self, state, seconds):
        self.state = state
        self._seconds = seconds

    def clock(self):
        return Fraction(self._seconds)


class _Actor:
    def __init__(self, conditions):
        self.conditions = conditions


class _Held:
    def __init__(self, condition_id, source_actor_id, data):
        self.condition_id = condition_id
        self.source_actor_id = source_actor_id
        self.data = data
        self.source_definition_id = WEAVER


def test_spent_heart_release_advantage_is_persisted_in_the_source_rite(monkeypatch):
    # Finding 3: after the anchor is serialized away, reopening must not
    # restore an unused Heart Release Advantage. The spent use lives on the
    # source rite and anchor records, which the rebuild path copies from.
    owner = 'actor:factory.rite_owner'
    aid = 'actor:factory.rite_target'
    state = {'journey_id': 'journey-' + '0' * 24, 'actors': {aid: {'source_states': {E.STATE: {
        'rites': {owner: {'anchor': 'courage', 'expires_at': 99999, 'release': 'sincere_emotion'}},
        'anchors': {owner: {'anchor': 'courage', 'expires_at': 99999, 'release': 'sincere_emotion'}}}}}}}
    session = _Session(state, 3600)
    anchor = _Held('condition:typed.heart_anchor', owner, {'deep': 1, 'release': 'sincere_emotion',
        'release_check_used': 1})
    monkeypatch.setattr(C, 'exported', lambda engine, actor: ([], []))
    C.settled(session, aid, None, _Actor({'anchor': anchor}))
    source = state['actors'][aid]['source_states'][E.STATE]
    assert source['rites'][owner]['release_check_used'] == 1
    assert source['anchors'][owner]['release_check_used'] == 1


def test_scene_end_is_blocked_by_the_journey_transition_gate(tmp_path, monkeypatch):
    # Finding 4: explicit scene end must pass the common transition gate; a
    # gate refusal leaves the journey, revision and scene unchanged.
    from combat import journey as J
    from combat.ext import run_strict as real
    from tests.test_mgr_t14_emotion_cultivator_floor58 import acquired
    aid = 'actor:factory.scene_owner'
    cold, jid = journey(tmp_path, monkeypatch, {'scene_owner': acquired([])},
        positions={aid: {'x': 1, 'y': 1}})
    seen = []
    def gate(point, *args, **kwargs):
        if point == 'journey_transition_gate' and args and args[-1] == 'end_scene':
            seen.append(point)
            raise ValueError('blocked by transition gate')
        return real(point, *args, **kwargs)
    monkeypatch.setattr(J, 'run_strict', gate)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        cold().journey_end_scene(jid, before['revision'], 'The storm passes.')
    assert seen == ['journey_transition_gate']
    after = cold().journey_state(jid)
    assert after['revision'] == before['revision']
    assert after.get('scene_id') == before.get('scene_id')


def test_world_fact_and_end_scene_routes_forward_through_the_http_layer(tmp_path, monkeypatch):
    # Finding 5: the two new journey routes are exercised through real HTTP
    # request parsing and forwarding, not by calling CombatService directly.
    import asyncio
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.h1_support import ROOT
    from tests.test_mgr_t14_emotion_cultivator_floor58 import acquired
    aid = 'actor:factory.route_owner'
    cold, jid = journey(tmp_path, monkeypatch, {'route_owner': acquired([])},
        positions={aid: {'x': 1, 'y': 1}})
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False

    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='http://testserver') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            before = cold().journey_state(jid)
            fact = {'source': WEAVER, 'subject': aid, 'kind': 'outside_scene', 'scope': jid,
                'value': 1, 'expires_at': 86400, 'readers': [aid]}
            response = await client.post(f'/api/combat/journeys/{jid}/world-facts',
                headers=headers, json={'revision': before['revision'], 'payload': fact})
            assert response.status_code == 200, response.text
            recorded = response.json()
            assert recorded['revision'] == before['revision'] + 1
            assert recorded['fact_consent_admission'][-1]['kind'] == 'outside_scene'
            assert cold().journey_state(jid) == recorded
            stale = await client.post(f'/api/combat/journeys/{jid}/world-facts',
                headers=headers, json={'revision': before['revision'], 'payload': fact})
            assert stale.status_code == 400 and 'refresh' in stale.json()['detail'].lower()
            ended = await client.post(f'/api/combat/journeys/{jid}/end-scene',
                headers=headers, json={'revision': recorded['revision'], 'reason': 'The storm passes.'})
            assert ended.status_code == 200, ended.text
            final = ended.json()
            assert final['scene_number'] == 1 and final['scene_id'] == jid + ':scene:1'
            assert final['revision'] == recorded['revision'] + 1
            assert any(event['kind'] == 'SCENE_ENDED' for event in final['events'])
            assert cold().journey_state(jid) == final
            stale = await client.post(f'/api/combat/journeys/{jid}/end-scene',
                headers=headers, json={'revision': recorded['revision'], 'reason': 'Again.'})
            assert stale.status_code == 400, stale.text

    asyncio.run(requests())


def test_heart_release_advantage_spend_survives_combat_commit_and_cold_reload(tmp_path, monkeypatch):
    # Finding 6: the target's own Insight check spends its Heart Release
    # Advantage; after the fight commits back to the journey, a cold reload
    # still has the use recorded and never grants Advantage a second time.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.cw2_service_support import add_action
    from tests.h1_support import ROOT
    from tests.test_mgr_t14_emotion_cultivator_floor58 import acquired
    from tests import auto11_service_support as S
    A, B = 'actor:factory.rite_owner', 'actor:factory.rite_target'
    docs = {'rite_owner': acquired([WEAVER]), 'rite_target': acquired([])}
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    cold, jid = journey(tmp_path, monkeypatch, docs, arena=arena,
        positions={A: {'x': 1, 'y': 1}, B: {'x': 1, 'y': 2}})
    # The trigger is the target's own real skill check, prepared as any table
    # setup action is and sealed into the journey bundle before the fight.
    session = cold().journeys.load(jid)
    with cold().journeys.locked(jid):
        add_action(session.state['actors'][B]['bundle'], 'Sincere Insight',
            [{'type': 'skill_check', 'applies_to': 'self', 'ability': 'wis', 'skill': 'Insight',
              'dc': 1, 'on_success': [], 'on_failure': []}], target='SELF')
        cold().journeys.save(session)
    state = cold().journey_state(jid)
    cold().journey_world_fact(jid, state['revision'], {'source': WEAVER, 'subject': A,
        'kind': 'outside_scene', 'scope': jid, 'value': 1, 'expires_at': 86400, 'readers': [A]})
    state = cold().journey_state(jid)
    cold().journey_act(jid, state['revision'], B, 'declare_fact', {'source': WEAVER, 'subject': B,
        'kind': 'heart_rite_consent', 'scope': A,
        'value': {'consent': 1, 'anchor': 'courage', 'release': 'sincere_emotion'},
        'expires_at': 86400, 'readers': [A]})
    state = cold().journey_state(jid)
    state = cold().journey_act(jid, state['revision'], A, 'emotion_rite', {'target_id': B})
    rite = state['actors'][B]['source_states']['emotion_cultivator']['rites'][A]
    assert rite['release'] == 'sincere_emotion' and rite['anchor'] == 'courage'

    def start():
        current = cold().journey_state(jid)
        return cold().journey_start_combat(jid, current['revision'], {A: 'team:a', B: 'team:b'},
            maximum_rounds=2, positions={A: {'x': 3, 'y': 6}, B: {'x': 4, 'y': 6}})['match_id']

    def finish(mid):
        for _ in range(20):
            if cold()._load_session(mid).engine.state.terminal_result is not None:
                return
            service = cold()
            table = TabletopService(service, tmp_path)
            menu = table.state(mid)['menu']
            table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                      table.state(mid)['last_sequence'])
        pytest.fail('Round-capped combat did not finish')

    def take_the_check(mid):
        service = cold()
        table = TabletopService(service, tmp_path)
        for _ in range(6):
            if table.state(mid)['menu']['actor_id'] == B:
                break
            S.play(table, mid, table.state(mid)['menu']['end_turn'])
        assert table.state(mid)['menu']['actor_id'] == B
        result, prompts = S.play(table, mid, S.candidate(table, mid, 'Sincere Insight'),
            answer=lambda prompt: 'yes' if prompt['context']['reaction_source_id']
                == 'choice:needle.fact_admission.sincere_communication' else None)
        assert result['status'] == 'COMMITTED'
        return prompts

    mid = start()
    prompts = take_the_check(mid)
    assert any(prompt['context']['reaction_source_id']
        == 'choice:needle.fact_admission.sincere_communication' for prompt in prompts)
    engine = cold()._load_session(mid).engine
    held = [c for c in engine.state.actors[B].conditions.values()
        if c.condition_id == 'condition:typed.heart_anchor']
    assert len(held) == 1 and held[0].data['release_check_used'] == 1
    finish(mid)
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    rite = resumed['actors'][B]['source_states']['emotion_cultivator']['rites'][A]
    assert rite['release_check_used'] == 1
    assert cold().journey_state(jid) == resumed

    mid = start()
    prompts = take_the_check(mid)
    assert not any(prompt['context']['reaction_source_id']
        == 'choice:needle.fact_admission.sincere_communication' for prompt in prompts)
    rolls = [r for r in cold()._load_session(mid).engine.rolls
        if r.actor_id == B and r.reason.startswith('CHECK:')]
    assert rolls and rolls[-1].mode == 'NORMAL'
