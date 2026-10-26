"""Retained defensive instances replay through suppression and restoration."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from tests.r1i_service_support import ROOT, OWNER, FOE, SECOND, fixture, candidate, force_ai_candidate

BEHEADING = 'tianxia.talent.sabers.battlefield_beheading_line'
REOPEN = 'tianxia.talent.life.reopen_the_living_meridian'
RECORD = 'TAL_KARMA_RECORD_THE_DEED'


@pytest.mark.parametrize('kind', ['condition', 'modifier'])
@pytest.mark.parametrize('auto', [False, True])
def test_beheading_suppression_and_restore_survive_table_reload(tmp_path, kind, auto):
    def setup(bundles):
        # Commit a controlled defensive instance through an actual table action;
        # Beheading's printed effects, costs, save and choice remain unchanged.
        foe = next(b for b in bundles if b['actor_id'] == FOE)
        action = next(a for a in foe['action_catalog'] if a['display_name'].startswith('Void Needle'))
        action['parameters']['typed']['effects'] = [
            {'type': 'condition', 'condition': 'invisible', 'applies_to': 'self',
             'duration': {'kind': 'minutes', 'amount': 1}} if kind == 'condition' else
            {'type': 'ac_bonus', 'flat': 2, 'applies_to': 'self',
             'duration': {'kind': 'minutes', 'amount': 1}}]
        action['parameters']['typed']['riders'] = []
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)

    # Native lock6 targeting now correctly prevents sight-required attacks on
    # invisible creatures. Give this suppression fixture real reviewed sight.
    talents = [BEHEADING] + (['TAL_THE_HIDDEN_EYE_TRUE_SIGHT'] if kind == 'condition' else [])
    combat, table, mid, send, commit = fixture(tmp_path, talents,
        foe_talents=['TAL_VOID_VOID_NEEDLE'], seed='R21-REPLAY-SUPPRESSION', bundle_transform=setup)
    def end():
        commit(table.state(mid)['menu']['end_turn'])
    end()
    while table.state(mid)['menu']['actor_id'] != FOE:
        end()
    commit(candidate(table, mid, 'Void Needle', OWNER))
    end()
    while table.state(mid)['menu']['actor_id'] != OWNER:
        end()
    before = combat._load_session(mid).engine.state.actors[FOE]
    instances = before.conditions if kind == 'condition' else before.modifiers
    key, original = next((key, item.model_dump(mode='json')) for key, item in instances.items()
        if (item.condition_id == 'condition:typed.invisible' if kind == 'condition' else item.target_field == 'armor_class'))
    if kind == 'condition':
        from combat import senses
        engine = combat._load_session(mid).engine
        assert senses.sees_hidden(engine, engine.state.actors[OWNER], before)
    cid = candidate(table, mid, 'Battlefield Beheading Line', FOE)
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
        # The test's manual controller still owns the reaction choices.
        answers = []
        for _ in range(16):
            result = send(cid, answers, auto=True)
            if result['status'] == 'COMMITTED':
                break
            assert result['status'] == 'REACTION_REQUIRED', result
            prompt = result['reaction']
            answer = {**prompt['context'], 'selection': 'DECLINE'}
            if prompt.get('choice'):
                answer.update(selection='USE', option_ids=[key])
            answers.append(answer)
        else:
            pytest.fail('too many reaction prompts')
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    else:
        commit(cid)
    def fresh():
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        replay = session.mechanical.replay()
        assert replay['status'] == 'PASS'
        assert canonical_state_sha256(session.engine.state) == canonical_sha256(replay['state'])
        return session.engine.state.actors[FOE]
    suppressed = fresh()
    item = (suppressed.conditions if kind == 'condition' else suppressed.modifiers)[key]
    assert (item.condition_id if kind == 'condition' else item.target_field).startswith(
        'condition:typed.suppressed.' if kind == 'condition' else 'suppressed:')
    assert item.expires_on == original['expires_on']
    end()
    while table.state(mid)['menu']['actor_id'] != FOE:
        end()
    end()  # End of the holder's next turn restores the same retained instance.
    restored = fresh()
    assert (restored.conditions if kind == 'condition' else restored.modifiers)[key].model_dump(mode='json') == original


def test_retained_silence_update_does_not_offer_a_fresh_karma_cause(tmp_path):
    """A real harmful application offers Debt; relieving it in a later round does not."""
    from combat.ext import karma_imprints

    def setup(bundles):
        foe = next(b for b in bundles if b['actor_id'] == FOE)
        # Only the hostile application fixture changes. Reopen's real failed-check
        # suppression, Karma's Ask decision, and all table persistence are shipped code.
        for action in foe['action_catalog']:
            if action['display_name'].startswith('Void Needle'):
                action['parameters']['typed']['effects'] = [
                    {'type': 'condition', 'condition': 'silenced', 'applies_to': 'target',
                     'expires_on': 'UNTIL_REMOVED'}]
                action['parameters']['typed']['numbers']['save_dc'] = 1000
                action['parameters']['typed']['riders'] = []
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)

    combat, table, mid, send, commit = fixture(tmp_path, [REOPEN, RECORD],
        foe_talents=['TAL_VOID_VOID_NEEDLE'], allies=(SECOND,),
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 3, 'y': 7}},
        seed='R21-KARMA-RETAINED-SILENCE', bundle_transform=setup)

    def end():
        commit(table.state(mid)['menu']['end_turn'])

    end()
    while table.state(mid)['menu']['actor_id'] != FOE:
        end()
    cid = candidate(table, mid, 'Void Needle', SECOND)
    result = send(cid)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['checkpoint'].startswith('TYPED:KARMIC_CAUSE@')
    assert prompt['context']['reactor_id'] == OWNER
    assert send(cid, [{**prompt['context'], 'selection': 'DECLINE'}])['status'] == 'COMMITTED'
    end()
    while (table.state(mid)['menu']['actor_id'] != OWNER
           or combat._load_session(mid).engine.state.round_number < 2):
        end()

    def fresh():
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        replay = session.mechanical.replay()
        assert replay['status'] == 'PASS'
        assert canonical_state_sha256(session.engine.state) == canonical_sha256(replay['state'])
        return session

    session = fresh()
    owner = session.engine.state.actors[OWNER]
    assert owner.reaction_available
    assert not karma_imprints.held(session.engine.state.actors[FOE], OWNER)
    resources = dict(owner.resources)
    key, original = next((k, c.model_dump(mode='json'))
        for k, c in session.engine.state.actors[SECOND].conditions.items()
        if c.condition_id == 'condition:typed.silenced')
    sequence = session.engine.events[-1].sequence
    result = send(candidate(table, mid, 'Reopen the Living Meridian', SECOND))
    # In particular, do not use commit(), which would silently decline a false Cause.
    assert result['status'] == 'COMMITTED', result
    session = fresh()
    assert session.engine.state.actors[SECOND].conditions[key].condition_id == 'condition:typed.suppressed.silenced'
    assert session.engine.state.actors[OWNER].reaction_available
    assert not karma_imprints.held(session.engine.state.actors[FOE], OWNER)
    # Only Reopen's printed CP payment, never a ledger payment.
    payments = [e for e in session.engine.events if e.sequence > sequence and e.event_type == 'RESOURCE_SPENT']
    assert len(payments) == 1
    assert session.engine.action_catalog[payments[0].source_definition_id].parameters['typed']['source'] == REOPEN
    assert payments[0].actor_id == OWNER and payments[0].payload['amount'] == 2
    paid = payments[0].payload['amount']
    assert sum(resources.values()) - sum(session.engine.state.actors[OWNER].resources.values()) == paid
    end()
    while table.state(mid)['menu']['actor_id'] != SECOND:
        end()
    end()
    session = fresh()
    assert session.engine.state.actors[SECOND].conditions[key].model_dump(mode='json') == original
    assert session.engine.state.actors[OWNER].reaction_available
    assert not karma_imprints.held(session.engine.state.actors[FOE], OWNER)
    assert not any(e.sequence > sequence and e.event_type == 'REACTION_WINDOW_OPENED'
        and 'KARMIC_CAUSE' in str(e.payload.get('checkpoint') or '') for e in session.engine.events)
    updates = [e for e in session.engine.events if e.sequence > sequence
        and e.event_type == 'CONDITION_APPLIED' and e.payload.get('instance_id') == key]
    assert [e.payload['condition_id'] for e in updates] == [
        'condition:typed.suppressed.silenced', 'condition:typed.silenced']
    assert all(e.payload.get('retained_instance_update') == 1
        and e.actor_id == original['source_actor_id'] for e in updates)


@pytest.mark.parametrize('kind', ['CONDITION_APPLIED', 'MODIFIER_APPLIED', 'ZONE_CREATED'])
@pytest.mark.parametrize('nested', [False, True])
def test_retained_updates_skip_all_application_subscribers(monkeypatch, kind, nested):
    from combat import ext
    from tests.test_lock3_nested_events import subscribe

    seen = []
    def ordinary(*args):
        seen.append('ordinary')
    def child(*args):
        seen.append('child')
    subscribe(monkeypatch, ordinary, child)
    dispatch = ext.run_nested if nested else ext.run
    dispatch('event', None, kind, {'payload': {'retained_instance_update': 1}})
    assert seen == []
    # The same event without the opt-in marker retains legacy delivery.
    dispatch('event', None, kind, {'payload': {}})
    assert seen == (['child'] if nested else ['ordinary', 'child'])


def test_restoration_is_neither_new_pressure_nor_a_new_shield_echo():
    from types import SimpleNamespace
    from combat import pressure
    from combat.ext import shield_riders
    from tests.test_auto_tabik import _engine, ME, AN

    engine, _ = _engine([])
    actor, other = engine.state.actors[ME], engine.state.actors[AN]
    engine.events = []
    engine._append_event('ATTACK_ROLLED', 'test:attack', actor_id=AN)
    update = SimpleNamespace(event_type='CONDITION_APPLIED', actor_id=AN, target_ids=(ME,),
        payload={'condition_id': shield_riders.ECHO, 'retained_instance_update': 1})
    engine.events.append(update)
    assert not pressure._pressed_by(engine, actor, other)
    assert not shield_riders._echoed_by_this_attack(engine, other, actor)
    # An actual new application still proves both histories.
    update.payload.pop('retained_instance_update')
    assert pressure._pressed_by(engine, actor, other)
    assert shield_riders._echoed_by_this_attack(engine, other, actor)


@pytest.mark.parametrize('kind', ['CONDITION_APPLIED', 'MODIFIER_APPLIED'])
def test_replay_only_updates_do_not_print_a_fresh_application(kind):
    from combat.history_feed import format_history_feed

    event = {'event_type': kind, 'actor_id': OWNER, 'target_ids': [SECOND],
        'source_definition_id': 'test:original', 'sequence': 1,
        'payload': {'condition_id': 'condition:typed.silenced', 'target_field': 'armor_class',
                    'retained_instance_update': 1}}
    kwargs = {'pre_state': {}, 'post_state': {}, 'actor_names': {}, 'definition_names': {}}
    assert format_history_feed([event], [], **kwargs) == []
    event['payload'].pop('retained_instance_update')
    assert len(format_history_feed([event], [], **kwargs)) == 1


def test_restoring_a_provenance_marker_preserves_later_temporary_hp():
    from combat.ext import riders_shared
    from combat.ext.end_effect import suppress, suppressed_effects_return
    from tests.test_auto_tabik import _engine, ME

    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    cid = 'condition:typed.singleton.test'
    engine._grant_temp_hp(actor, 10, 'test:owned', ME)
    engine._add_modifier(actor, 'test:owned', riders_shared.SINGLETON_HP + cid,
        'SET', 10, 'ALWAYS', expires_on='UNTIL_REMOVED')
    key, marker = next((k, m) for k, m in actor.modifiers.items()
        if m.target_field == riders_shared.SINGLETON_HP + cid)
    suppress(actor, 'modifier', key, marker, engine=engine)
    engine._grant_temp_hp(actor, 20, 'test:other', ME)
    actor.turns_started += 1
    suppressed_effects_return(engine, actor)
    riders_shared.clear_singleton_hp(engine, actor, cid)
    assert key not in actor.modifiers
    assert actor.temporary_hp == 20  # The later grant superseded the owned HP.
