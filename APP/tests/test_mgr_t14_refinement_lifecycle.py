"""Native payment, preparation, failure and interruption of Refine the Meal."""
import json
import pytest

from tests.test_mgr_t14_hunger_meals import (
    A, CP, IMP, KEY, REFINE, SAT, game, portion, refine, journey_activity,
)


@pytest.mark.parametrize('mode,seconds', [('TEN_MINUTE_REFINE', 600), ('SHORT_REST_REFINE', 3600)])
def test_refinement_pays_on_activation_before_preparation_and_never_pays_again(tmp_path, monkeypatch, mode, seconds):
    from combat.journey_activity import replay_record
    cold, jid, command = game(tmp_path, monkeypatch, natural=6)
    command('record_essence_portion', portion())
    state = refine(command, mode=mode, steady_cp=2)
    records = [e for e in state['events'] if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED']
    preparations = [e for e in records if any(row['event_type'] == 'RESOURCE_SPENT'
        and row['source_definition_id'] == REFINE for row in e['events'])]
    checks = [e for e in records if any(row['event_type'] == 'CHECK_ROLLED'
        and row['source_definition_id'] == REFINE for row in e['events'])]
    assert len(preparations) == len(checks) == 1 and preparations[0] is not checks[0]
    paid, checked = preparations[0], checks[0]
    assert paid['seconds'] == 0 and checked['seconds'] == seconds
    assert replay_record(paid).actors[A].resources[CP] == 27
    assert json.loads(checked['pre_state'])['actors'][A]['resources'][CP] == 27
    actor = replay_record(checked).actors[A]
    assert actor.resources[CP] == 27 and actor.resources[SAT] == 1
    assert not any(row['event_type'] == 'RESOURCE_SPENT' for row in checked['events'])
    assert not state['actors'][A]['travel_uses'][KEY]['portions']
    assert not state['actors'][A]['travel_uses'][KEY].get('refining')
    assert not any(c.condition_id == 'condition:typed.hunger_refinement_prepared' for c in actor.conditions.values())
    assert actor.turns_started == 0 and actor.action_available and actor.bonus_action_available
    assert state['seconds'] == seconds and cold().journey_state(jid) == state


def test_failed_refinement_impurity_is_in_the_native_commit_and_cold_mechanical_replay(tmp_path, monkeypatch):
    from combat.journey_activity import replay_record
    cold, jid, command = game(tmp_path, monkeypatch, natural=1)
    command('record_essence_portion', portion())
    state = refine(command)
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    actor = replay_record(committed).actors[A]
    assert actor.resources[IMP] == 1 and actor.resources[SAT] == 0 and actor.resources[CP] == 29
    assert any(row['event_type'] == 'RESOURCE_GAINED' and row['payload']['resource_id'] == IMP
        and row['payload']['gained'] == 1 for row in committed['events'])
    assert state['actors'][A]['resources'] == actor.resources
    assert cold().journey_state(jid) == state


def test_real_indigestion_interrupts_refinement_without_refunding_cost_or_rewinding_time(tmp_path, monkeypatch):
    from combat.journey_activity import load, replay_record
    from combat.ext.forged_exhaustion import level
    cold, jid, command = game(tmp_path, monkeypatch, natural=[1, 1, 1, 1, 6], save_natural=1)
    for index in range(5):
        pid = 'indigestion-preparation-' + str(index)
        command('record_essence_portion', portion(pid))
        refine(command, pid)
    native = load(cold().journeys.load(jid))
    candidate = next(c for c in native.legal_candidates() if c.display_name == 'Digestive Mantle: Thick Hide')
    journey_activity(cold, jid, A, {'candidate_id': candidate.candidate_id})
    command('native_activity_end')
    command('travel_exhaustion', {'levels': 5, 'ordinary': True})
    command('record_essence_portion', portion('interrupted'))
    before = cold().journey_state(jid)
    state = refine(command, 'interrupted')
    pending = state['native_activity_pending']
    request = pending['request']
    assert request['reactor_id'] == A and request['reaction_source_id'] == 'choice:needle.hunger.indigestion'
    answer = {key: request[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')}
    answer.update(selection='USE', option_ids=['exhaustion'])
    state = command('native_activity_answer', answer)
    assert not state.get('native_activity_pending') and not state.get('native_activity')
    assert state['seconds'] == before['seconds'] + 600
    assert state['actors'][A]['resources'][CP] == before['actors'][A]['resources'][CP] - 1
    assert state['actors'][A]['resources'][IMP] == 4 and state['actors'][A]['resources'][SAT] == 0
    assert not state['actors'][A]['travel_uses'][KEY]['portions']
    assert not state['actors'][A]['travel_uses'][KEY].get('refining')
    assert any(e['kind'] == 'REFINE_INTERRUPTED' for e in state['events'])
    actor = load(cold().journeys.load(jid)).state.actors[A]
    assert not actor.active and actor.current_hp == 0 and level(actor) == 6
    settlement = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    assert not any(e['event_type'] == 'CHECK_ROLLED' for e in settlement['events'])
    assert replay_record(settlement).actors[A].resources == actor.resources
    assert cold().journey_state(jid) == state
