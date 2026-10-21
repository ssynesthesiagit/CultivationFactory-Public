"""Native source acquisition, committed choices and cold replay for Emotion."""
import pytest
from combat.ext.emotion_cultivator import PULSE, HEART, CONTAGION, WEATHER, WEAVER
from combat.feature_access import acquire
from combat.factory_compiler import compile_character
from combat.observer_information import readings
from tests.h1_support import sheet
from tests import test_a2_qi_subpaths_1_service as Q


def answer(prompt):
    source = prompt['context']['reaction_source_id']
    if source == 'choice:willing.consent':
        return 'refuse'
    if source == 'choice:needle.fact_admission.visible_emotional_response':
        return 'joy'
    if source == 'choice:needle.emotion.contagion':
        return Q.ALLY
    return None


def acquired(features, cl=18):
    doc = sheet([], cl=cl)
    doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    for feature in features:
        doc = acquire(doc, feature, {'kind': 'scripture', 'reference': 'Recorded standard Emotion Scripture instruction',
            'classification': 'Restricted Scripture'})
    return doc


@pytest.mark.parametrize('feature,level', [(PULSE, 3), (CONTAGION, 6), (HEART, 10), (WEATHER, 14), (WEAVER, 18)])
def test_native_acquisition_rejects_missing_access_wrong_path_and_low_cl(feature, level):
    doc = acquired([feature], level)
    assert feature in doc['path_and_subpath']['path_feature_record_ids']
    for invalid in ({'kind': 'scripture', 'classification': 'Open School', 'reference': 'wrong'},
                    {'kind': 'scripture', 'classification': 'Restricted Scripture', 'reference': ''}):
        with pytest.raises(ValueError):
            acquire(doc, feature, invalid)
    low = sheet([], cl=level-1)
    low['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    with pytest.raises(ValueError):
        acquire(low, feature, doc['feature_access'][feature])
    bare = compile_character(sheet([feature], cl=level), actor_id='actor:factory.unlicensed')
    assert not any((a.get('parameters', {}).get('typed') or {}).get('source') == feature for a in bare['action_catalog'])


def test_failed_pulse_collects_actual_response_and_contagion_replays(tmp_path):
    svc, table, mid = Q.fight(tmp_path, [PULSE, CONTAGION])
    result, prompts = Q.use(table, mid, 'Emotional Pulse: Pulse of Sorrow', target=Q.FOE, answer=answer)
    assert result['status'] == 'COMMITTED'
    engine = Q.cold(svc, mid)
    assert Q.conditions(engine.state.actors[Q.FOE], 'emotional_sorrow')
    assert Q.conditions(engine.state.actors[Q.ALLY], 'emotional_sorrow')
    assert engine.state.actors[Q.ME].resources[Q.QI] == 26
    view = readings(engine, engine.state.actors[Q.ME])
    assert any(v['details']['strongest_visible_response'] == 'joy' for v in view)
    # "Whether it is currently Charmed, Frightened, or under another active
    # emotional effect you can perceive": the failed Pulse of Sorrow is one.
    assert any('Sorrow' in v['details']['perceived_conditions'] for v in view)
    assert readings(engine, engine.state.actors[Q.ALLY]) == []
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.emotion.contagion']) == 1


def test_native_attainment_effective_cl_and_replacement_remain_authoritative():
    doc = acquired([WEAVER])
    doc['identity']['effective_cl'] = 17
    bundle = compile_character(doc, actor_id='actor:factory.suppressed')
    assert not any((a.get('parameters', {}).get('typed') or {}).get('source') == WEAVER
        for a in bundle['action_catalog'])
    doc = acquired([PULSE])
    doc['path_and_subpath']['paths'] = [{'path_id':'tianxia.path.qi_cultivation','attainment':2,'effective_cl':18}]
    bundle = compile_character(doc, actor_id='actor:factory.unattained')
    assert not any((a.get('parameters', {}).get('typed') or {}).get('source') == PULSE
        for a in bundle['action_catalog'])
    doc['path_and_subpath']['subpaths'] = [{'owning_path_id':'tianxia.path.qi_cultivation',
        'subpath_id':'tianxia.subpath.qi.heart_stealing_emotion_cultivator'}]
    with pytest.raises(ValueError):
        acquire(doc, PULSE, {'kind':'scripture','reference':'Standard Emotion Scripture',
            'classification':'Restricted Scripture'})


def test_declined_willing_pulse_does_not_create_heartbreak_receipt(tmp_path):
    svc, table, mid = Q.fight(tmp_path, [PULSE, HEART])
    Q.use(table, mid, 'Emotional Pulse: Willing Joy', answer=answer)
    engine = Q.cold(svc, mid)
    assert not any(c.condition_id == Q.EXPOSURE for c in engine.state.actors[Q.ALLY].conditions.values())
    assert engine.state.actors[Q.ALLY].temporary_hp == 0


def test_non_owner_has_no_contagion_or_private_inferred_emotion(tmp_path):
    svc, table, mid = Q.fight(tmp_path, [PULSE])
    Q.use(table, mid, 'Emotional Pulse: Pulse of Fear', target=Q.FOE,
        answer=lambda p: 'refuse' if p['context']['reaction_source_id'] == 'choice:willing.consent' else None)
    engine = Q.cold(svc, mid)
    assert not engine.state.actors[Q.ALLY].conditions
    assert not readings(engine, engine.state.actors[Q.ME])
    assert engine.state.actors[Q.ME].resources[Q.QI] == 28


@pytest.mark.parametrize('weather,expected', [('rage','emotional_rage'), ('sorrow','emotional_sorrow'),
    ('fear','frightened'), ('joy','reaction_denied'), ('calm','emotional_calm')])
def test_each_weather_is_a_paid_native_aura_with_committed_start_trigger(tmp_path, weather, expected):
    svc, table, mid = Q.fight(tmp_path, [WEATHER], cl=18)
    result, prompts = Q.use(table, mid, f'Weather of the Heart: {weather.title()} (centered on you)', target=Q.ME,
        answer=lambda p: Q.ALLY if p['context']['reaction_source_id'] == 'choice:needle.emotion.weather_allies' else None)
    assert result['status'] == 'COMMITTED'
    engine = Q.cold(svc, mid)
    assert engine.state.actors[Q.ME].resources[Q.QI] == 25
    assert engine.state.actors[Q.ME].concentration is not None
    # Creating a field on somebody is not entry; the actual turn start triggers.
    assert not Q.conditions(engine.state.actors[Q.FOE], expected)
    Q.S.to_thief(table, mid, end_thief=True)
    engine = Q.cold(svc, mid)
    assert Q.conditions(engine.state.actors[Q.FOE], expected)
    if weather == 'joy':
        assert engine.state.actors[Q.ALLY].temporary_hp == 4
    assert not any(e.source_definition_id == 'ext:combat.ext.emotion_cultivator' for e in engine.events)


def test_heartweaver_free_pulse_and_discounted_healing_keep_native_economy_and_reload(tmp_path):
    svc, table, mid = Q.fight(tmp_path, [WEAVER, PULSE, HEART, WEATHER], cl=18)
    Q.use(table, mid, 'Heartweaver — 1 minute', target=Q.ME)
    engine = Q.cold(svc, mid)
    assert engine.state.actors[Q.ME].resources[Q.QI] == 22
    assert Q.conditions(engine.state.actors[Q.ME], 'heartweaver')
    Q.use(table, mid, 'Emotional Pulse: Pulse of Sorrow — Heartweaver free Pulse', target=Q.FOE, answer=answer)
    engine = Q.cold(svc, mid)
    assert engine.state.actors[Q.ME].resources[Q.QI] == 22
    assert engine.state.actors[Q.ME].action_available
    assert not any('Heartweaver free Pulse' in group['label'] for group in table.state(mid)['menu']['actions'])
    Q.use(table, mid, 'Heartmend — Heartweaver', target=Q.ALLY,
        answer=lambda p: 'accept' if p['context']['reaction_source_id'] == 'choice:willing.consent' else 'temporary_hp')
    engine = Q.cold(svc, mid)
    assert engine.state.actors[Q.ME].resources[Q.QI] == 20
    assert engine.state.actors[Q.ALLY].temporary_hp == 8


def test_rite_uses_real_gm_scope_recipient_consent_elapsed_time_and_cold_state(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    A, B = 'actor:factory.rite_owner', 'actor:factory.rite_target'
    docs = {'rite_owner': acquired([WEAVER]), 'rite_target': acquired([])}
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid: docs[pid])
    arena = {'stable_id': 'emotion:rite', 'width_squares': 10, 'height_squares': 10,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': arena})
    svc = CombatService(ROOT, tmp_path)
    state = svc.create_journey(project_ids=list(docs), arena_id='scene',
        positions={A:{'x':1,'y':1}, B:{'x':1,'y':2}}, base_paces={A:5,B:5}, control_modes={A:'MANUAL',B:'MANUAL'})
    jid = state['journey_id']
    def cold(): return CombatService(ROOT, tmp_path)
    def act(aid, kind, payload):
        current = cold().journey_state(jid)
        result = cold().journey_act(jid, current['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    with pytest.raises(ValueError):
        act(A, 'emotion_rite', {'target_id': B})
    current = cold().journey_state(jid)
    cold().journey_world_fact(jid, current['revision'], {'source':WEAVER,'subject':A,'kind':'outside_scene',
        'scope':jid,'value':1,'expires_at':86400,'readers':[A]})
    consent = {'source':WEAVER,'subject':B,'kind':'heart_rite_consent','scope':A,
        'value':{'consent':1,'anchor':'courage','release':'temporary_hp'},'expires_at':86400,'readers':[A]}
    with pytest.raises(ValueError):
        act(A, 'declare_fact', consent)
    act(B, 'declare_fact', consent)
    state = act(A, 'emotion_rite', {'target_id':B})
    assert state['seconds'] == 3600 and state['actors'][A]['resources'][Q.QI] == 25
    held = state['actors'][B]['source_states']['emotion_cultivator']['rites'][A]
    assert held['anchor'] == 'courage' and held['expires_at'] == 32400
    act(B, 'declare_fact', {'source':WEAVER,'subject':B,'kind':'deep_anchor_consent','scope':A,
        'value':{'consent':1},'expires_at':86400,'readers':[A]})
    state = act(A, 'emotion_deep_anchor', {'target_id':B})
    assert state['seconds'] == 28800 and state['actors'][A]['resources'][Q.QI] == 15
    assert state['actors'][B]['source_states']['emotion_cultivator']['anchors'][A]['deep'] == 1
    state = act(B, 'wait', {'seconds':3601})
    assert not state['actors'][B]['source_states']['emotion_cultivator']['rites']
    assert state['actors'][B]['source_states']['emotion_cultivator']['anchors'][A]['deep'] == 1


def test_native_calm_movement_closes_and_cold_reopens_without_resetting_weather(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from combat.gate2_runtime_models import MatchState
    from tests.h1_support import ROOT
    aid = 'actor:factory.calm_traveller'
    doc = acquired([WEATHER])
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid: doc)
    arena = {'stable_id':'emotion:calm_travel', 'width_squares':10, 'height_squares':10,
        'square_size_ft':5, 'starting_positions':{}, 'terrain_regions':[]}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene':arena})
    def cold(): return CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=['calm_traveller'], arena_id='scene',
        positions={aid:{'x':1,'y':1}}, base_paces={aid:5}, control_modes={aid:'MANUAL'})
    jid = state['journey_id']
    def act(kind, payload):
        before = cold().journey_state(jid)
        result = cold().journey_act(jid, before['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    def options(): return cold().journey_menu(jid, aid)['options']
    def offered(predicate, description):
        rows = options()
        selected = [o for o in rows if o['kind'] == 'native_activity' and predicate(o)]
        assert selected, (description, [(o['label'], o.get('destination')) for o in rows])
        return selected[0]
    weather = offered(lambda o: 'Weather of the Heart: Calm (centered on you)' in o['label'],
        'paid Calm weather')
    state = act('native_activity', weather['payload'])
    request = state['native_activity_pending']['request']
    assert request['reaction_source_id'] == 'choice:needle.emotion.weather_allies'
    state = act('native_activity_answer', {key:request[key] for key in
        ('checkpoint','reactor_id','reaction_source_id')} | {'selection':'USE','option_ids':[aid]})
    move = offered(lambda o: o.get('destination') is not None
        and (o['destination']['x'], o['destination']['y'], o['destination'].get('z', 0)) == (2,1,0),
        'five-foot native movement')
    state = act('native_activity', move['payload'])
    native = MatchState.model_validate_json(state['native_activity']['state'])
    counter = Q.conditions(native.actors[aid], 'emotion_distance_this_turn')
    assert len(counter) == 1 and counter[0].data['feet'] == 5
    assert counter[0].source_definition_id == WEATHER
    # Closing projects actual timed instances before finishing the round. A
    # record-id source must not be mistaken for an unsupported foreign effect.
    state = act('native_activity_end', {})
    assert 'native_activity' not in state
    assert state['actors'][aid]['resources'][Q.QI] == 25
    assert not any('emotion_distance_this_turn' in raw for raw in
        state['actors'][aid]['encounter_snapshot']['conditions'].values())
    # Re-enter through a genuine native intent, with the original paid aura
    # restored rather than recast or charged again.
    dodge = offered(lambda o: 'Dodge' in o['label'], 'native Dodge after cold reopening')
    state = act('native_activity', dodge['payload'])
    if state.get('native_activity_pending'):
        request = state['native_activity_pending']['request']
        assert request['reaction_source_id'] == 'choice:needle.emotion.weather_change'
        state = act('native_activity_answer', {key:request[key] for key in
            ('checkpoint','reactor_id','reaction_source_id')} | {'selection':'DECLINE','option_ids':[]})
    native = MatchState.model_validate_json(state['native_activity']['state'])
    assert Q.conditions(native.actors[aid], 'heart_weather')
    assert not Q.conditions(native.actors[aid], 'emotion_distance_this_turn')
    assert native.actors[aid].resources[Q.QI] == 25
