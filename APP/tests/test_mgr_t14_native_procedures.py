"""Native source-procedure boundaries shared by the seven assigned rows.

These tests acquire real source rows and use public journey/controller intents.
They never inject ownership, conditions, event receipts or random results into
persisted state. Only the fixture's dice transport is controlled.
"""
import json
import pytest

from tests.test_mgr_t14_hunger_meals import (
    A as MEAL_OWNER, KEY, SAT, game as meal_game, portion, refine,
)


def test_native_refinement_hunger_check_keeps_actual_exhaustion_penalty(tmp_path, monkeypatch):
    import json
    from combat.journey_activity import replay_record
    from tests.test_mgr_t14_hunger_meals import CP
    cold, jid, command = meal_game(tmp_path, monkeypatch, natural=6)
    command('travel_exhaustion', {'levels': 1, 'ordinary': True})
    state = cold().journey_state(jid)
    assert state['actors'][MEAL_OWNER]['exhaustion'] == 1
    command('record_essence_portion', portion())
    state = refine(command)
    event = next(e for e in reversed(state['events']) if e['kind'] == 'MEAL_REFINED')
    assert event['dc'] == 12 and event['roll']['total'] == 10
    assert event['margin'] == -2 and state['actors'][MEAL_OWNER]['resources'][SAT] == 0
    assert not state['actors'][MEAL_OWNER]['travel_uses'][KEY]['portions']
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(committed)
    before = json.loads(committed['pre_state'])['actors'][MEAL_OWNER]
    assert replayed.actors[MEAL_OWNER].resources[CP] == before['resources'][CP] - 1
    assert replayed.actors[MEAL_OWNER].action_available == before['action_available']
    assert replayed.actors[MEAL_OWNER].turns_started == before['turns_started']
    assert state['seconds'] == 600, 'The ten-minute ritual grants no extra round or turn.'
    assert state['actors'][MEAL_OWNER]['resources'] == replayed.actors[MEAL_OWNER].resources
    assert cold().journey_state(jid) == state


def test_uncapped_counter_native_resource_operations_keep_bounded_pools_and_reduce_cold(tmp_path, monkeypatch):
    """General counter math guard; direct gains certify no ability activation."""
    from combat.journey_activity import load
    from combat.gate2_runtime_models import MatchState, ResourceDefinition
    from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
    from tests.test_mgr_t14_hunger_meals import A, CP, IMP
    cold, jid, _ = meal_game(tmp_path, monkeypatch)
    engine = load(cold().journeys.load(jid))
    actor = engine.state.actors[A]
    assert actor.resource_maximums[IMP] == -1 and actor.resource_maximums[SAT] == 4
    with pytest.raises(ValueError):
        ResourceDefinition(resource_id='counter:invalid', initial=0, maximum=-2)
    before, first = engine.state.model_copy(deep=True), len(engine.events)
    engine._gain_resource(actor, IMP, 120, 'test:counter.gain')
    assert actor.resources[IMP] == 120
    engine._spend_resource(actor, IMP, 3, 'test:counter.spend')
    assert actor.resources[IMP] == 117
    engine._set_resource_maximum(actor, IMP, 10, 'test:counter.bound')
    assert actor.resources[IMP] == 10
    engine._set_resource_maximum(actor, IMP, -1, 'test:counter.unbound')
    engine._gain_resource(actor, IMP, 120, 'test:counter.gain')
    assert actor.resources[IMP] == 130
    engine._spend_resource(actor, CP, actor.resources[CP], 'test:bounded.spend')
    engine._gain_resource(actor, CP, 999, 'test:bounded.gain')
    assert actor.resources[CP] == actor.resource_maximums[CP]
    replayed = Gate3EventReducer().apply_events(before,
        enrich_committed_events(engine.events[first:], post_engine=engine))
    restored = MatchState.model_validate_json(replayed.model_dump_json()).actors[A]
    assert restored.resources == actor.resources and restored.resource_maximums == actor.resource_maximums


@pytest.mark.parametrize('effective,expected', [(4, 4), (5, 5), (9, 5), (10, 7)])
def test_base_capacity_adapter_keeps_printed_realm_boundaries(effective, expected):
    """Pure boundary guard, not acquisition or closure of either talent."""
    from combat.ext.hunger_meals import satiety_capacity, REFINE
    info = {'owned_ids': [REFINE, 'tianxia.talent.hunger.second_stomach_method',
            'tianxia.talent.hunger.cauldron_stomach'], 'numbers': {'cl': 10}, 'pb': 4,
        'owner_sheet': {'identity': {'effective_cl': effective}}}
    rows = satiety_capacity(info)
    assert next(row.maximum for row in rows if row.resource_id == SAT) == expected
    assert satiety_capacity({**info, 'owned_ids': []}) is None


def test_native_table_requested_check_uses_real_skill_variant_privacy_and_single_resolution(tmp_path, monkeypatch):
    from combat.ext.native_check_challenges import SOURCE, KIND
    from combat.journey_activity import replay_record
    from tests.test_mgr_t14_hunger_meals import A, B, CP
    cold, jid, command = meal_game(tmp_path, monkeypatch, natural=6,
        skills=[{'skill': 'Athletics', 'ability': 'STR', 'bonus': 7, 'proficiency_multiplier': 1}], ability_mods={'STR': 3})
    assert not any(row['kind'] == 'ability_check' for row in cold().journey_menu(jid, A)['options'])
    command('travel_exhaustion', {'levels': 1, 'ordinary': True})
    command('record_essence_portion', portion())
    before = cold().journey_state(jid)
    value = {'name': 'Keep the sealed spirit ration steady through fatigue', 'ability': 'CON', 'skill': 'Athletics',
        'dc': 12, 'obstacle_id': 'portion-1:steady-wrapping',
        'ruling': 'The actual recorded ration must remain steady under prolonged physical strain; the table requests Constitution with Athletics.'}
    payload = {'source': SOURCE, 'subject': A, 'kind': KIND, 'scope': 'ration-wrapping', 'value': value,
        'expires_at': before['seconds'] + 60, 'readers': []}
    with pytest.raises(ValueError):
        cold().journey_act(jid, before['revision'], A, 'declare_fact', payload)
    with pytest.raises(ValueError):
        cold().journey_world_fact(jid, before['revision'], {**payload, 'value': {**value, 'success': 1}})
    with pytest.raises(ValueError):
        cold().journey_world_fact(jid, before['revision'], {**payload, 'value': {**value, 'skill': 'Medicine'}})
    assert cold().journey_state(jid) == before
    state = cold().journey_world_fact(jid, before['revision'], payload)
    menu = cold().journey_menu(jid, A)
    requested = next(row for row in menu['options'] if row['kind'] == 'ability_check')
    assert value['name'] not in json.dumps(cold().journey_menu(jid, B))
    with pytest.raises(ValueError):
        command('ability_check', requested['payload'], aid=B)
    assert cold().journey_state(jid) == state

    state = command('ability_check', requested['payload'])
    assert not state.get('native_activity_pending') and not state.get('native_activity')
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(committed)
    rolled = next(e for e in committed['events'] if e['event_type'] == 'CHECK_ROLLED')
    assert rolled['payload']['actor']['total'] == 10, 'd20 6 + actual Athletics 7 - Strength 3 + Constitution 2 - Exhaustion 2.'
    assert not rolled['payload']['success']
    assert replayed.actors[A].resources[CP] == before['actors'][A]['resources'][CP]
    assert replayed.actors[A].action_available and replayed.actors[A].turns_started == 0
    assert state['seconds'] == before['seconds'] and state['actors'][A]['travel_uses'][KEY]['portions']
    assert not any(row['kind'] == 'ability_check' for row in cold().journey_menu(jid, A)['options'])
    with pytest.raises(ValueError):
        command('ability_check', requested['payload'])
    assert cold().journey_state(jid) == state
    # A new immutable table ruling can authorize another actual attempt. Its
    # expiry cannot revive the earlier, completed version of this obstacle.
    state = cold().journey_world_fact(jid, state['revision'], {**payload, 'value': {**value, 'dc': 13},
        'expires_at': state['seconds'] + 1})
    assert any(row['kind'] == 'ability_check' for row in cold().journey_menu(jid, A)['options'])
    state = command('wait', {'seconds': 1})
    assert not any(row['kind'] == 'ability_check' for row in cold().journey_menu(jid, A)['options'])
    assert cold().journey_state(jid) == state


def test_native_refinement_menu_keeps_every_affordable_check_bonus(tmp_path, monkeypatch):
    from tests.test_mgr_t14_hunger_meals import A, CP
    from combat.journey_activity import replay_record
    cold, jid, command = meal_game(tmp_path, monkeypatch, natural=6)
    command('record_essence_portion', portion())
    menu = cold().journey_menu(jid, A)['options']
    for mode in ('TEN_MINUTE_REFINE', 'SHORT_REST_REFINE'):
        assert {row['payload']['steady_cp'] for row in menu
            if row['kind'] == 'refine_meal' and row['payload']['mode'] == mode} == set(range(5))
    state = refine(command, steady_cp=4)
    event = next(e for e in reversed(state['events']) if e['kind'] == 'MEAL_REFINED')
    assert event['roll']['total'] == 16 and event['margin'] == 4
    assert state['actors'][A]['resources'][SAT] == 1 and state['actors'][A]['resources'][CP] == 25
    assert state['seconds'] == 600 and not state['actors'][A]['travel_uses'][KEY]['portions']
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    assert replay_record(committed).actors[A].resources == state['actors'][A]['resources']
    assert cold().journey_state(jid) == state


def test_native_refinement_at_capacity_keeps_cost_consumption_and_legal_additional_rewards(tmp_path, monkeypatch):
    from tests.test_mgr_t14_hunger_meals import A, CP
    cold, jid, command = meal_game(tmp_path, monkeypatch, natural=[6, 6, 6, 6, 20])
    for index in range(4):
        pid = 'capacity-' + str(index)
        command('record_essence_portion', portion(pid))
        refine(command, pid)
    state = command('record_essence_portion', portion('excess', memories=['The harmless scent of late-summer hay.']))
    assert state['actors'][A]['resources'][SAT] == 4
    assert any(row['kind'] == 'refine_meal' and row['payload']['portion_id'] == 'excess'
        for row in cold().journey_menu(jid, A)['options'])
    state = refine(command, 'excess')
    assert state['seconds'] == 3000 and state['actors'][A]['resources'][CP] == 25
    assert state['actors'][A]['resources'][SAT] == 4
    meals = state['actors'][A]['travel_uses'][KEY]
    assert not meals['portions'] and len(meals['charges']) == 4
    assert all(charge['portion_id'] != 'excess' for charge in meals['charges'])
    event = next(e for e in reversed(state['events']) if e['kind'] == 'MEAL_REFINED')
    assert event['margin'] >= 5 and event['satiety_gained'] == 0
    choices = {row['payload']['reward'] for row in cold().journey_menu(jid, A)['options'] if row['kind'] == 'refine_reward'}
    assert choices == {'cleanse', 'temporary_hp', 'memory'}
    with pytest.raises(ValueError, match='charge'):
        command('refine_reward', {'reward': 'free_mantle'})
    assert cold().journey_state(jid) == state
    assert all(not charge['free_mantle'] for charge in meals['charges'])
    state = command('refine_reward', {'reward': 'temporary_hp'})
    assert state['actors'][A]['encounter_snapshot']['temporary_hp'] == 4
    assert state['actors'][A]['resources'][SAT] == 4 and state['actors'][A]['resources'][CP] == 25
    assert cold().journey_state(jid) == state


@pytest.mark.parametrize('demon', [0, 1])
def test_native_mantle_continues_and_settles_its_real_meal_at_exact_travel_expiry(tmp_path, monkeypatch, demon):
    from tests.test_mgr_t14_hunger_meals import A, CP, IMP, game, journey_activity
    from fractions import Fraction
    from combat.journey_activity import load, replay_record
    from combat.ext.hunger_riders import MANTLE as HELD
    cold, jid, command = game(tmp_path, monkeypatch)
    benefits = ['Thick Hide', 'Beast Strength'] if demon else ['Thick Hide']
    command('record_essence_portion', portion(demon_beast=demon, benefits=benefits))
    refine(command)
    command('refine_reward', {'reward': 'free_mantle'})
    native = load(cold().journeys.load(jid))
    name = 'Digestive Mantle: Demon-Beast Course' if demon else 'Digestive Mantle: Thick Hide'
    candidate = next(c for c in native.legal_candidates() if c.display_name == name)
    state = journey_activity(cold, jid, A, {'candidate_id': candidate.candidate_id})
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    actor = replay_record(committed).actors[A]
    held = next(c for c in actor.conditions.values() if c.condition_id == HELD)
    assert held.data['meal_source']['portion_id'] == 'portion-1' and actor.resources[SAT] == 0
    assert len(held.data['benefits']) == 1 + demon
    state = command('native_activity_end')
    rows = state['actors'][A]['source_states']['hunger.mantle_continuation']
    main = next(row for row in rows if row['kind'] == 'condition' and json.loads(row['instance'])['condition_id'] == HELD)
    deadline = Fraction(*main['deadline'])
    session = cold().journeys.load(jid)
    remaining = deadline - session.clock()
    assert remaining.denominator == 1 and remaining > 1
    before_cp = state['actors'][A]['resources'][CP]
    state = command('wait', {'seconds': int(remaining) - 1})
    cold_actor = load(cold().journeys.load(jid)).state.actors[A]
    assert any(c.condition_id == HELD for c in cold_actor.conditions.values())
    assert cold_actor.resources[IMP] == 0 and cold_actor.resources[CP] == before_cp
    state = command('wait', {'seconds': 1})
    expiry = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ELAPSED_EFFECTS_COMMITTED')
    replayed = replay_record(expiry)
    assert replayed.actors[A].resources[IMP] == demon
    assert not any(c.condition_id == HELD for c in replayed.actors[A].conditions.values())
    assert any(row['runtime_instance_id'] != row['instance_id'] for row in expiry['timer_references'])
    after = load(cold().journeys.load(jid)).state.actors[A]
    assert not any(c.condition_id == HELD for c in after.conditions.values())
    assert after.resources[IMP] == demon and after.resources[CP] == before_cp and after.resources[SAT] == 0
    assert not state['actors'][A]['travel_uses'][KEY]['charges']
    assert cold().journey_state(jid) == state


@pytest.mark.parametrize('consequence', ['success', 'poisoned', 'no_satiety', 'exhaustion', 'monstrous'])
def test_native_impurity_unstable_mantle_save_owner_choice_and_actual_rest(tmp_path, monkeypatch, consequence):
    from combat.journey_activity import load, replay_record
    from combat.ext.forged_exhaustion import level
    from tests.test_mgr_t14_hunger_meals import A, B, CP, IMP, game, journey_activity
    held_id = 'condition:typed.digestive_mantle'
    cold, jid, command = game(tmp_path, monkeypatch, natural=[1, 1, 1, 1, 6],
        save_natural=20 if consequence == 'success' else 1)
    for index in range(4):
        pid = 'failed-refinement-' + str(index)
        command('record_essence_portion', portion(pid))
        state = refine(command, pid)
        assert state['actors'][A]['resources'][IMP] == index + 1
    command('record_essence_portion', portion('stored'))
    state = refine(command, 'stored')
    assert state['actors'][A]['resources'][SAT] == 1
    native = load(cold().journeys.load(jid))
    candidate = next(c for c in native.legal_candidates() if c.display_name == 'Digestive Mantle: Thick Hide')
    state = journey_activity(cold, jid, A, {'candidate_id': candidate.candidate_id})
    native = load(cold().journeys.load(jid))
    held = next(c for c in native.state.actors[A].conditions.values() if c.condition_id == held_id)
    assert held.data['unstable'] == 1
    assert native.state.actors[A].resource_maximums[IMP] == -1
    state = command('native_activity_end')
    before_resources = dict(state['actors'][A]['resources'])
    state = command('wait', {'seconds': 60})
    observed = []
    for _ in range(8):
        pending = state.get('native_activity_pending')
        if pending is None:
            break
        request = pending['request']
        observed.append(request)
        answer = {key: request[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')}
        if request['reaction_source_id'] == 'choice:needle.hunger.indigestion':
            assert request['reactor_id'] == A and consequence != 'success'
            spec = request.get('extension_choice') or {}
            assert set(request.get('legal_option_ids') or spec.get('option_ids')) == {'poisoned', 'no_satiety', 'exhaustion', 'monstrous'}
            answer.update(selection='USE', option_ids=[consequence])
        else:
            answer.update(selection='DECLINE', option_ids=[])
        state = command('native_activity_answer', answer, aid=request['reactor_id'])
    assert not state.get('native_activity_pending')
    assert bool(observed) is (consequence != 'success')
    expiry = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ELAPSED_EFFECTS_COMMITTED')
    replayed = replay_record(expiry)
    actor = replayed.actors[A]
    assert actor.resources[IMP] == (3 if consequence == 'success' else 4)
    assert actor.resources[CP] == before_resources[CP] and actor.resources[SAT] == 0
    assert not any(c.condition_id == held_id for c in actor.conditions.values())
    assert not any(c.source_definition_id == 'HUNGER_BASE_DIGESTIVE_MANTLE' for c in replayed.actors[B].conditions.values())
    assert level(actor) == int(consequence == 'exhaustion')
    condition_id = {'poisoned': 'poisoned', 'no_satiety': 'condition:typed.hunger.indigestion_no_satiety',
        'monstrous': 'condition:typed.hunger.indigestion_monstrous'}.get(consequence)
    if condition_id:
        assert any(c.condition_id == condition_id for c in actor.conditions.values())
        cold_actor = load(cold().journeys.load(jid)).state.actors[A]
        assert any(c.condition_id == condition_id for c in cold_actor.conditions.values())
        assert all(c.expires_on == 'UNTIL_REMOVED' for c in cold_actor.conditions.values() if c.condition_id == condition_id)
    if consequence == 'no_satiety':
        # A real second ritual consumes its actual portion and CP but cannot
        # grant a charge while the native indigestion condition remains.
        command('record_essence_portion', portion('blocked'))
        state = refine(command, 'blocked')
        assert state['actors'][A]['resources'][SAT] == 0 and not state['actors'][A]['travel_uses'][KEY]['charges']
    before_clock = cold().journey_state(jid)['seconds']
    state = command('short_rest')
    assert state['seconds'] == before_clock + 3600 and state['actors'][A]['short_rests'] == 1
    after_short = load(cold().journeys.load(jid)).state.actors[A]
    assert level(after_short) == int(consequence == 'exhaustion')
    if condition_id:
        assert any(c.condition_id == condition_id for c in after_short.conditions.values()) is (consequence == 'monstrous')
    state = command('long_rest')
    assert state['actors'][A]['resources'][IMP] == 0
    after_long = load(cold().journeys.load(jid)).state.actors[A]
    if condition_id:
        assert not any(c.condition_id == condition_id for c in after_long.conditions.values())
    assert cold().journey_state(jid) == state


def test_native_replacing_an_unstable_mantle_preserves_its_real_ending_debt(tmp_path, monkeypatch):
    from combat.journey_activity import load, replay_record
    from combat.ext.forged_exhaustion import level
    from tests.test_mgr_t14_hunger_meals import A, CP, IMP, game, journey_activity
    cold, jid, command = game(tmp_path, monkeypatch, natural=[1, 1, 1, 1, 6, 6], save_natural=1)
    for index in range(6):
        pid = 'replacement-meal-' + str(index)
        command('record_essence_portion', portion(pid))
        refine(command, pid)
    assert cold().journey_state(jid)['actors'][A]['resources'][SAT] == 2
    def activate():
        native = load(cold().journeys.load(jid))
        candidate = next(c for c in native.legal_candidates() if c.display_name == 'Digestive Mantle: Thick Hide')
        return journey_activity(cold, jid, A, {'candidate_id': candidate.candidate_id},
            choices={'choice:needle.hunger.indigestion': 'exhaustion'})
    activate()
    command('native_activity_end')
    state = activate()
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(committed)
    actor = replayed.actors[A]
    assert actor.resources[IMP] == 4 and actor.resources[SAT] == 0 and actor.resources[CP] == 22
    assert level(actor) == 1
    mantles = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.digestive_mantle']
    assert len(mantles) == 1 and mantles[0].data['unstable'] == 1 and not mantles[0].data.get('ended')
    saves = [e for e in committed['events'] if e['event_type'] == 'SAVE_ROLLED'
        and e['source_definition_id'] == 'HUNGER_BASE_DIGESTIVE_MANTLE']
    assert len(saves) == 1 and not saves[0]['payload']['success']
    state = command('native_activity_end')
    restored = load(cold().journeys.load(jid)).state.actors[A]
    assert level(restored) == 1 and restored.resources == actor.resources
    assert len([c for c in restored.conditions.values() if c.condition_id == 'condition:typed.digestive_mantle']) == 1
    assert cold().journey_state(jid) == state
