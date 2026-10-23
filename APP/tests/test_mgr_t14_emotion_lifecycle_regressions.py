"""Behavioural regressions for Kyle's Emotion Cultivator lifecycle (MGR-T14).

These drive the real journey -> native combat -> committed resume -> reopen path
through CombatService/TabletopService, so they fail when a hook is never called,
a save classification is missing, a cure is lost on reopen, or Heart Release
cannot reach the authoritative impairment record.

Public-CI safe: synthetic sheets and journeys only; no history reads, private
fixtures or live model servers.
"""
import json

from combat.ext.emotion_cultivator import HEART, PULSE, WEATHER, WEAVER
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests import auto11_service_support as S
from tests.h1_support import ROOT
from tests.test_mgr_t14_emotion_cultivator_floor58 import acquired
from tests.test_mgr_t14_sol_seam_emotion_review_fixes import journey

SEER = FACTORY_ACTOR_PREFIX + 'lifecycle_seer'
OTHER = FACTORY_ACTOR_PREFIX + 'lifecycle_other'
POSITIONS = {SEER: {'x': 3, 'y': 6}, OTHER: {'x': 4, 'y': 6}}
ANCHOR = 'condition:typed.heart_anchor'
IMPAIRMENT = 'condition:typed.ordinary_emotional_impairment'
RAGE = 'condition:typed.emotional_rage'
CONTINUATION = 'emotion_native_continuation'
IMPAIRMENT_KIND = 'ordinary_emotional_impairment'


def game(tmp_path, monkeypatch, seer, other=(), *, dc=30):
    """One real journey over synthetic sheets, shared by the service checks."""
    docs = {'lifecycle_seer': acquired(seer), 'lifecycle_other': acquired(list(other))}
    docs['lifecycle_seer']['ability_scores_and_statistics']['technique_save_dc'] = dc
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)[
        'battlefield:factory_pillar_arena']
    cold, jid = journey(tmp_path, monkeypatch, docs, arena=arena, positions=POSITIONS)
    return cold, jid


def heart_rite(cold, jid, anchor, release, *, creator=SEER, target=OTHER):
    """A willing Heart-Shaping Rite through the real journey commands."""
    state = cold().journey_state(jid)
    cold().journey_world_fact(jid, state['revision'], {'source': WEAVER, 'subject': creator,
        'kind': 'outside_scene', 'scope': jid, 'value': 1, 'expires_at': 86400, 'readers': [creator]})
    state = cold().journey_state(jid)
    cold().journey_act(jid, state['revision'], target, 'declare_fact', {'source': WEAVER,
        'subject': target, 'kind': 'heart_rite_consent', 'scope': creator,
        'value': {'consent': 1, 'anchor': anchor, 'release': release},
        'expires_at': 86400, 'readers': [creator]})
    state = cold().journey_state(jid)
    return cold().journey_act(jid, state['revision'], creator, 'emotion_rite', {'target_id': target})


def declare_impairment(cold, jid, aid):
    """The table owner records a real ordinary emotional impairment and its source rule."""
    state = cold().journey_state(jid)
    return cold().journey_world_fact(jid, state['revision'], {'source': PULSE, 'subject': aid,
        'kind': IMPAIRMENT_KIND, 'scope': jid, 'value': {
            'source_reference': 'Source Rule: the grief is a real ordinary emotional impairment',
            'category': 'grief', 'source_cl': 5, 'label': 'Grief: ordinary emotional impairment'},
        'expires_at': 32400, 'readers': [aid]})


def start(cold, jid, *, rounds=3):
    state = cold().journey_state(jid)
    return cold().journey_start_combat(jid, state['revision'], {SEER: 'team:a', OTHER: 'team:b'},
        maximum_rounds=rounds, positions=POSITIONS)['match_id']


def finish(cold, tmp_path, mid):
    """Play out the round-capped fight through the real table."""
    table = TabletopService(cold(), tmp_path)
    for _ in range(40):
        if cold()._load_session(mid).engine.state.terminal_result is not None:
            return
        menu = table.state(mid)['menu']
        table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                  table.state(mid)['last_sequence'], [])
    raise AssertionError('Round-capped combat did not finish')


def at(table, mid, actor):
    for _ in range(8):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError(f'{actor} never got a turn')


def held(engine, aid, condition):
    return [row for row in engine.state.actors[aid].conditions.values()
            if row.condition_id == condition]


def continuation(state, aid):
    return state['actors'][aid]['source_states'][CONTINUATION]


def cure_answer(prompt):
    source = prompt['context'].get('reaction_source_id')
    if source == 'choice:needle.heartmend':
        return 'emotional'
    if source == 'choice:needle.source_relief':
        return prompt['choice']['options'][0]['id']
    return None


def roll_answer(prompt):
    # Decline the offer to fail the save without rolling: this checks the real d20.
    if prompt['context'].get('reaction_source_id') == 'choice:willing.consent':
        return 'refuse'
    return None


def test_patience_heart_anchor_grants_advantage_and_release_against_pulse_of_rage(tmp_path, monkeypatch):
    # Patience protects against provoked Rage; a success spends the chosen Heart Release.
    cold, jid = game(tmp_path, monkeypatch, [PULSE, WEAVER], dc=1)
    heart_rite(cold, jid, 'patience', 'temporary_hp')
    mid = start(cold, jid)
    engine = cold()._load_session(mid).engine
    anchor = held(engine, OTHER, ANCHOR)
    assert len(anchor) == 1 and anchor[0].data['anchor'] == 'patience'
    temporary_hp = 2 * int(anchor[0].data['pb'])
    table = TabletopService(cold(), tmp_path)
    at(table, mid, SEER)
    result, _ = S.play(table, mid, S.candidate(table, mid, 'Pulse of Rage', target=OTHER),
        answer=roll_answer)
    assert result['status'] == 'COMMITTED'
    loaded = cold()._load_session(mid).engine
    saves = [event for event in loaded.events
             if event.event_type == 'SAVE_ROLLED' and event.actor_id == OTHER]
    assert saves and saves[-1].payload['mode'] == 'ADVANTAGE'
    assert loaded.state.actors[OTHER].temporary_hp == temporary_hp
    assert not held(loaded, OTHER, RAGE)


def test_patience_heart_anchor_grants_advantage_and_release_against_rage_weather(tmp_path, monkeypatch):
    # Forced emotional escalation from hostile Rage weather uses the same classification.
    cold, jid = game(tmp_path, monkeypatch, [WEAVER, WEATHER], dc=1)
    heart_rite(cold, jid, 'patience', 'temporary_hp')
    mid = start(cold, jid)
    engine = cold()._load_session(mid).engine
    anchor = held(engine, OTHER, ANCHOR)
    temporary_hp = 2 * int(anchor[0].data['pb'])
    table = TabletopService(cold(), tmp_path)
    at(table, mid, SEER)
    result, _ = S.play(table, mid,
        S.candidate(table, mid, 'Weather of the Heart: Rage (centered on you)'))
    assert result['status'] == 'COMMITTED'
    # The aura's save resolves at the start of the affected creature's turn.
    at(table, mid, OTHER)
    loaded = cold()._load_session(mid).engine
    saves = [event for event in loaded.events
             if event.event_type == 'SAVE_ROLLED' and event.actor_id == OTHER]
    assert saves and saves[-1].payload['mode'] == 'ADVANTAGE'
    assert loaded.state.actors[OTHER].temporary_hp == temporary_hp


def test_cured_source_declaration_stays_ended_after_commit_and_reopen(tmp_path, monkeypatch):
    # Heartmend ends the impairment; the committed journey must retire the declaration
    # so the next encounter cannot recreate it from the same fact.
    cold, jid = game(tmp_path, monkeypatch, [PULSE, HEART])
    declare_impairment(cold, jid, SEER)
    mid = start(cold, jid)
    engine = cold()._load_session(mid).engine
    cured = held(engine, SEER, IMPAIRMENT)
    assert len(cured) == 1
    receipt = cured[0].data['declaration_receipt']
    table = TabletopService(cold(), tmp_path)
    at(table, mid, SEER)
    result, _ = S.play(table, mid, S.candidate(table, mid, 'Heartmend', target=SEER),
        answer=cure_answer)
    assert result['status'] == 'COMMITTED'
    assert not held(cold()._load_session(mid).engine, SEER, IMPAIRMENT)

    finish(cold, tmp_path, mid)
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    assert continuation(resumed, SEER)['ended_declaration_receipts'] == [receipt]
    assert continuation(resumed, SEER)['records'] == []
    assert cold().journey_state(jid) == resumed  # committed state survives a cold reload

    reopened = cold()._load_session(start(cold, jid, rounds=1)).engine
    assert not held(reopened, SEER, IMPAIRMENT)


def test_surviving_source_declaration_keeps_one_lifetime_across_reopen(tmp_path, monkeypatch):
    # A live declaration is represented by its continued instance, not by a second
    # fresh application alongside it.
    cold, jid = game(tmp_path, monkeypatch, [PULSE])
    declare_impairment(cold, jid, SEER)
    mid = start(cold, jid)
    assert len(held(cold()._load_session(mid).engine, SEER, IMPAIRMENT)) == 1
    finish(cold, tmp_path, mid)
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    records = [json.loads(row['instance']) for row in continuation(resumed, SEER)['records']
               if json.loads(row['instance'])['condition_id'] == IMPAIRMENT]
    assert len(records) == 1
    reopened = cold()._load_session(start(cold, jid, rounds=1)).engine
    current = held(reopened, SEER, IMPAIRMENT)
    assert len(current) == 1
    assert current[0].instance_id == records[0]['instance_id']


def test_heart_release_short_rest_ends_a_continued_impairment_and_stays_ended(tmp_path, monkeypatch):
    # The printed short-rest Heart Release reaches the authoritative continued
    # instance (not only an encounter snapshot) and its ending is durable.
    cold, jid = game(tmp_path, monkeypatch, [WEAVER])
    heart_rite(cold, jid, 'courage', 'short_rest')
    declare_impairment(cold, jid, OTHER)
    mid = start(cold, jid, rounds=1)
    finish(cold, tmp_path, mid)
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    record = next(json.loads(row['instance']) for row in continuation(resumed, OTHER)['records']
                  if json.loads(row['instance'])['condition_id'] == IMPAIRMENT)
    receipt = record['data']['declaration_receipt']
    options = [option for option in cold().journey_menu(jid, OTHER)['options']
               if option['kind'] == 'emotion_release_short_rest']
    assert len(options) == 1 and 'Grief' in options[0]['label']

    after = cold().journey_act(jid, resumed['revision'], OTHER,
        options[0]['kind'], options[0]['payload'])
    assert after['events'][-1]['kind'] == 'HEART_RELEASE_IMPAIRMENT_ENDED'
    remaining = continuation(after, OTHER)
    assert remaining['records'] == [] and remaining['ended_declaration_receipts'] == [receipt]
    assert not [option for option in cold().journey_menu(jid, OTHER)['options']
                if option['kind'] == 'emotion_release_short_rest']
    assert cold().journey_state(jid) == after

    reopened = cold()._load_session(start(cold, jid, rounds=1)).engine
    assert not held(reopened, OTHER, IMPAIRMENT)
