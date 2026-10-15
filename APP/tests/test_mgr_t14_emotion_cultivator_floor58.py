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
    assert readings(engine, engine.state.actors[Q.ALLY]) == []
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.emotion.contagion']) == 1


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
