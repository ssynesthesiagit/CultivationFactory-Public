"""Real table choices for concealment ordering and ordinary ally-miss responses."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, OWNER, FOE, SECOND, force_ai_candidate
from tests.r10_fixup_support import cast_sender, commit, fixed_dice

INVISIBLE = 'tianxia.talent.illusion.greater_invisibility'
TWIST = 'TAL_FATE_TWIST_OF_FATE'
BORROW = 'TAL_THREAD_BORROW_THE_ALLY_S_ARM'


def use_reaction(prompt):
    return {**prompt['context'], 'selection': 'USE'}


def concealed_table(tmp_path, talent, monkeypatch, *, thread=False):
    combat, table, mid, send, decline = fixture(tmp_path, [talent],
        second_talents=[INVISIBLE], allies=[FOE],
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 5, 'y': 6}})
    # Give the ally an actual compiled melee attack rather than a synthetic miss hook.
    # The fixture's foe sheet has no weapon, so its base unarmed attack is used.
    if thread:
        # A willing ally's pre-existing physical line is fixture state, recorded
        # by the ordinary condition event during a table commit. The response
        # under test is the real compiled Borrow the Ally's Arm, never a hook stub.
        from combat.gate4_engine import Gate4ControllerEngine
        from combat.typed_executor import mark_condition_id
        original = Gate4ControllerEngine.execute_intent
        def connected(engine, *args, **kwargs):
            result = original(engine, *args, **kwargs)
            engine._apply_condition(engine.state.actors[FOE], mark_condition_id('Thread Line', OWNER),
                'fixture:thread-line', OWNER, expires_on='UNTIL_REMOVED')
            return result
        with monkeypatch.context() as setup:
            setup.setattr(Gate4ControllerEngine, 'execute_intent', connected)
            decline(table.state(mid)['menu']['end_turn'])
    else:
        decline(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != SECOND:
        decline(table.state(mid)['menu']['end_turn'])
    commit(cast_sender(combat, table, mid, 'Greater Invisibility', target=SECOND),
           lambda p: (None, True))
    decline(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        decline(table.state(mid)['menu']['end_turn'])
    engine = combat._load_session(mid).engine
    attacks = [c for c in engine.legal_candidates() if SECOND in c.target_ids
               and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('weapon')]
    if not attacks:
        attacks = [c for c in engine.legal_candidates() if SECOND in c.target_ids
                   and 'Unarmed' in c.display_name]
    assert attacks, [c.display_name for c in engine.legal_candidates()]
    return combat, table, mid, attacks[0].candidate_id, send


@pytest.mark.parametrize('die', [1, 100])
@pytest.mark.parametrize('reactor_auto', [False, True])
@pytest.mark.parametrize('attacker_auto', [False, True])
def test_concealment_before_paid_fate_decision(tmp_path, monkeypatch, die, reactor_auto, attacker_auto):
    from combat import targeting
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    combat, table, mid, cid, send = concealed_table(tmp_path, TWIST, monkeypatch)
    if reactor_auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    if attacker_auto:
        force_ai_candidate(combat, mid, FOE, cid)
    before = combat._load_session(mid).engine
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    seq = before.state.event_sequence
    fixed_dice(monkeypatch, [die, 6, 20, 20] + [6] * 30)
    result = send(cid, auto=attacker_auto)
    if die == 100 and not reactor_auto:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == 'reaction:typed.' + TWIST
        assert prompt['reaction'] == 'Twist of Fate' and prompt['action'] == 'Unarmed Strike'
        assert prompt['trigger_actor'] == prompt['affected'] == 'Foe'
        assert 'D20_PENDING' in prompt['context']['checkpoint']
        result = send(cid, [use_reaction(prompt)], auto=attacker_auto)
    assert result['status'] == 'COMMITTED', result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in loaded.engine.events if e.sequence > seq]
    receipts = [e for e in events if 'miss_chance_percent' in e.payload]
    assert len(receipts) == 1 and receipts[0].payload['missed'] is (die == 1)
    paid = [e for e in events if e.event_type == 'REACTION_RESOLVED' and TWIST in e.source_definition_id]
    assert len(paid) == int(die == 100)
    owner = loaded.engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == qi - int(die == 100)
    assert owner.reaction_available is (die == 1)
    assert bool([e for e in events if e.event_type == 'ATTACK_ROLLED']) is (die == 100)
    if paid:
        assert receipts[0].sequence < paid[0].sequence
    else:
        assert not [r for r in loaded.engine.rolls if r.reason == 'REACTION_DIE' and r.actor_id == OWNER
                    and r.roll_id not in {v.roll_id for v in before.rolls}]
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('die', [20, 21])
def test_portable_conflagration_light_concealment_table_reload(tmp_path, monkeypatch, die):
    from combat.tabletop_service import TabletopService
    from combat import targeting
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    from tests.test_c3d_p1_portable_live_combat import (
        _install_pointer, _catalog_payload, RUNTIME_PACKAGE, DYNAMIC_ACTOR_ID, BUILTIN_OPPONENT,
        _manual_end_turn,
    )
    _install_pointer(tmp_path, RUNTIME_PACKAGE)
    combat = CombatService(ROOT, tmp_path)
    payload = _catalog_payload(combat, maximum_rounds=10)
    payload['participants'][1]['placement'] = {'x': 3, 'y': 4}
    preflight = combat.preflight_new_fight(payload)
    assert preflight['ready'], preflight
    mid = combat.create_confirmed_fight({**payload, 'owner_confirmed': True,
        'preflight_commitment': preflight['preflight_commitment'], 'idempotency_key': 'sol132r1-light'})['match_id']
    table = TabletopService(combat, tmp_path)
    while table.state(mid)['menu']['actor_id'] != DYNAMIC_ACTOR_ID:
        _manual_end_turn(combat, mid)
    commit(cast_sender(combat, table, mid, 'Conflagration', at=(3, 4)))
    # Reload the real stored FIRE_TERRAIN representation before attacking.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    e = combat._load_session(mid).engine
    zone = next(z for z in e.state.zones.values() if z.trigger_profile.get('kind') == 'FIRE_TERRAIN')
    assert zone.active and zone.trigger_profile['lightly_obscured'] is True
    assert targeting.concealment_percent(e, e.state.actors[DYNAMIC_ACTOR_ID], e.state.actors[BUILTIN_OPPONENT]) == 20
    _manual_end_turn(combat, mid)
    _manual_end_turn(combat, mid)
    assert table.state(mid)['menu']['actor_id'] == DYNAMIC_ACTOR_ID
    before = combat._load_session(mid).engine
    seq = before.state.event_sequence
    hp = before.state.actors[BUILTIN_OPPONENT].current_hp
    fixed_dice(monkeypatch, [die, 20, 20] + [6] * 30)
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=BUILTIN_OPPONENT))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in loaded.engine.events if e.sequence > seq]
    receipts = [e for e in events if 'miss_chance_percent' in e.payload]
    assert len(receipts) == 1
    assert receipts[0].payload['miss_chance_percent'] == 20
    assert receipts[0].payload['missed'] is (die == 20)
    assert bool([e for e in events if e.event_type == 'ATTACK_ROLLED']) is (die == 21)
    if die == 20:
        assert loaded.engine.state.actors[BUILTIN_OPPONENT].current_hp == hp
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('die', [1, 100])
def test_real_thread_ally_miss_choice_commit_reload(tmp_path, monkeypatch, die):
    from combat import targeting
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    combat, table, mid, cid, send = concealed_table(tmp_path, BORROW, monkeypatch, thread=True)
    before = combat._load_session(mid).engine
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    hp = before.state.actors[SECOND].current_hp
    seq = before.state.event_sequence
    fixed_dice(monkeypatch, [die, 1, 1] + [6] * 30)
    result = send(cid)
    if die == 1:
        # AUTO Thread corrects a failed rolled d20, not a concealment miss
        # which produced no attack roll to add a Proficiency Bonus to.
        assert result['status'] == 'COMMITTED', result
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        events = [e for e in loaded.engine.events if e.sequence > seq]
        assert not [e for e in events if e.event_type == 'ATTACK_ROLLED']
        assert not [e for e in events if e.event_type == 'REACTION_RESOLVED' and BORROW in e.source_definition_id]
        assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == qi
        assert loaded.engine.state.actors[OWNER].reaction_available
        assert loaded.engine.state.actors[SECOND].current_hp == hp
        assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
        return
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.thread_correction.' + BORROW
    assert prompt['reaction'].replace('’', "'") == "Borrow the Ally's Arm" and prompt['action'] == 'Unarmed Strike'
    assert prompt['trigger_actor'] == prompt['affected'] == 'Foe'
    assert 'thread_correction' in prompt['context']['checkpoint']
    assert send(cid)['reaction'] == prompt
    options = prompt['choice']['options']
    answers = [{**use_reaction(prompt), 'option_ids': [options[0]['id']]}]
    result = send(cid, answers)
    assert result['status'] == 'REACTION_REQUIRED', result
    consent = result['reaction']
    assert 'willing' in consent['context']['reaction_source_id']
    answers.append({**use_reaction(consent), 'option_ids': [consent['choice']['options'][0]['id']]})
    assert send(cid, answers)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in loaded.engine.events if e.sequence > seq]
    paid = [e for e in events if e.event_type == 'REACTION_RESOLVED' and BORROW in e.source_definition_id]
    assert len(paid) == 1  # Rolled misses must not be dispatched twice.
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 1
    assert not loaded.engine.state.actors[OWNER].reaction_available
    assert loaded.engine.state.actors[SECOND].current_hp == hp
    assert bool([e for e in events if e.event_type == 'ATTACK_ROLLED']) is (die == 100)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
