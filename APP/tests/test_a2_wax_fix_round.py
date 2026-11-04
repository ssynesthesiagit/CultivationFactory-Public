"""Review regressions through table/session commits, cold loads and replay.

Seed actions only supply represented triggers; real Wax and compiled wall actions
resolve them. Test event subscribers model another plug-in emitting child events.
"""
import json

import pytest

from combat import ext, stealth, typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.test_a2_wax_second_pass import (
    CLINGING, MOLD, NO_DASH, PRESS, REBUKE, TRACE, TRAIL, commit, owned_seal,
    seal, setup_trail,
)
from tests.test_r5i_integration import (
    AN, OTHER, PLAYER, act, answer, candidate, check_reload, fixture, pin_ai, seed, turn,
)


def direct_commit(combat, mid, tmp_path, cid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    c = next(c for c in session.engine.legal_candidates() if c.candidate_id == cid)
    session.mechanical.execute_intent(ActionIntent(intent_id='wax-review-direct',
        decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    return check_reload(combat, mid, tmp_path)


@pytest.mark.parametrize('change', ['teleport', 'invisible', 'polymorphed', 'petrified'])
@pytest.mark.parametrize('nested', [False, True])
def test_strengthened_traced_seal_snap_restores_dash(tmp_path, monkeypatch, change, nested):
    def setup(bundle, other):
        setup_trail(bundle, other)
        seed(bundle, 'End transformation', [{'type': 'remove_condition', 'condition': 'petrified', 'applies_to': 'target'}], target='ANY_CREATURE')
        seed(other, 'Child event trigger', [{'type': 'condition', 'condition': 'review_trigger', 'applies_to': 'self'}], target='SELF')
    combat, table, mid = fixture(tmp_path, [PRESS, CLINGING, TRAIL], configure=setup)
    turn(table, mid, PLAYER)
    seal(combat, table, mid)
    turn(table, mid, OTHER)
    commit(table, mid, candidate(combat, mid, 'Other Wax'))
    move = next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.kind.value == 'MOVE' and c.destination == Position(x=5, y=6))
    commit(table, mid, move.candidate_id, {'Waxen Trail': ['trace']})
    engine = check_reload(combat, mid, tmp_path)
    assert {NO_DASH, TRACE} <= {c.condition_id for c in engine.state.actors[OTHER].conditions.values()}
    assert not any(c.display_name == 'Dash' for c in engine.legal_candidates())
    departure = engine.state.actors[OTHER].position
    if nested:
        ext.effects()
        def child(engine, event_type, kwargs):
            if event_type != 'CONDITION_APPLIED' or (kwargs.get('payload') or {}).get('condition_id') != 'condition:typed.review_trigger':
                return
            subject = engine.state.actors[OTHER]
            if change == 'teleport':
                from combat.ext import spirit_traditions as st
                action = next(a for a in engine.action_catalog.values() if a.owner_id == OTHER and a.display_name == 'Test teleport')
                ctx = st.context(engine, subject, action, [], intent=engine._active_intent)
                typed_executor.teleport_subject(ctx, subject, Position(x=6, y=6))
            else:
                engine._apply_condition(subject, 'condition:typed.' + change, 'test:child', OTHER, expires_on='UNTIL_REMOVED')
        monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS['event'], child])
        commit(table, mid, candidate(combat, mid, 'Child event trigger'))
    else:
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name.startswith('Test ' + change))
        commit(table, mid, cid, {'Test teleport': 'first'} if change == 'teleport' else {})
    engine = check_reload(combat, mid, tmp_path)
    subject = engine.state.actors[OTHER]
    assert not owned_seal(subject)
    assert owned_seal(subject, OTHER)
    assert not {NO_DASH, TRACE} & {c.condition_id for c in subject.conditions.values()}
    marks = [z for z in engine.state.zones.values() if z.source_definition_id == TRAIL]
    assert len(marks) == 1 and marks[0].center == departure
    # Dash is an actual legal action after the cold service load; commit it via
    # the direct session transport, then cold-load and replay that commit too.
    if change == 'petrified':
        # Petrification has its own action ban. Cure that represented condition
        # through a separate table action before checking Dash availability.
        turn(table, mid, PLAYER)
        commit(table, mid, candidate(combat, mid, 'End transformation', OTHER))
        turn(table, mid, OTHER)
        engine = check_reload(combat, mid, tmp_path)
    dash = next(c for c in engine.legal_candidates() if c.display_name == 'Dash')
    engine = direct_commit(combat, mid, tmp_path, dash.candidate_id)
    assert not engine.state.actors[OTHER].action_available


@pytest.mark.parametrize('auto_mover', [False, True])
@pytest.mark.parametrize('use', [False, True])
def test_unseen_mover_keeps_manual_owner_trace_choice(tmp_path, auto_mover, use):
    def setup(bundle, other):
        setup_trail(bundle, other)
        seed(other, 'Obscuring smoke', [{'type': 'zone'}], target='SELF')
        other['action_catalog'][-1]['parameters']['typed']['zone_spec'] = {
            'name': 'Obscuring smoke', 'shape': 'square', 'size_ft': 20, 'centered_on_self': True,
            'duration': {'kind': 'rounds', 'amount': 10}, 'obscured': 'heavy', 'triggers': [], 'inside': []}
    combat, table, mid = fixture(tmp_path, [TRAIL], configure=setup)
    turn(table, mid, PLAYER)
    commit(table, mid, candidate(combat, mid, 'Seed Wax', OTHER))
    turn(table, mid, OTHER)
    commit(table, mid, candidate(combat, mid, 'Obscuring smoke'))
    engine = check_reload(combat, mid, tmp_path)
    assert not stealth.sees(engine, engine.state.actors[PLAYER], engine.state.actors[OTHER])
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination == Position(x=5, y=6))
    if auto_mover:
        pin_ai(combat, mid, OTHER, cid)
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_mover else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    responses = []
    result = send()
    while result['status'] == 'REACTION_REQUIRED' and result['reaction']['reaction'] != 'Waxen Trail':
        responses.append(answer(result, 'DECLINE'))
        result = send(responses)
    assert result['status'] == 'REACTION_REQUIRED', result
    assert result['reaction']['reaction'] == 'Waxen Trail'
    assert result['reaction']['context']['reactor_id'] == PLAYER
    label = json.dumps(result['reaction']['choice'])
    assert 'while the seal remains' in label
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    assert send([*responses, answer(result, 'USE' if use else 'DECLINE', ['trace'] if use else [])])['status'] == 'COMMITTED'
    engine = check_reload(combat, mid, tmp_path)
    assert any(c.condition_id == TRACE for c in engine.state.actors[OTHER].conditions.values()) == use
    end = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    direct_commit(combat, mid, tmp_path, end.candidate_id)


def weapon_setup(item, damage):
    def setup(bundle, other):
        # A legal smaller Set Shape: one 5-foot wall section. A destroying hit
        # can then destroy the whole form, independently of optional Rebuke.
        for action in bundle['action_catalog']:
            if 'Wax Rampart: Half Cover' in action['display_name']:
                spec = action['parameters']['typed']['zone_spec']
                spec['size_ft'] = 5
                spec['wall']['length_ft'] = 5
        doc = sheet([], cl=15, dc=50, kit={'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.weapon.' + item, 'name': item, 'quantity': 1}]}})
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 900
        real = compile_character(doc, actor_id=OTHER, reaction_plan={'ask': True})
        other.clear()
        other.update(real)
        # Preserve the compiler's weapon and delivery metadata. Only deterministic
        # damage/to-hit inputs change to exercise damage and destruction boundaries.
        wall = next(a for a in other['action_catalog'] if a['display_name'] == 'Attack a wall section')
        wall['parameters']['typed']['numbers']['attack_bonus'] = 100
        wall['parameters']['typed']['wall_weapon']['fixed_damage'] = damage
    return setup


@pytest.mark.parametrize('item,cell,triggers', [('jian', (5, 6), True), ('ji', (5, 6), True), ('ji', (6, 6), False), ('gong_jian', (5, 6), False)])
@pytest.mark.parametrize('destroy', [False, True])
def test_compiled_wall_delivery_rebuke_and_destroying_hit(tmp_path, item, cell, triggers, destroy):
    combat, table, mid = fixture(tmp_path, [MOLD, 'TAL_WAX_WAX_RAMPART', REBUKE], configure=weapon_setup(item, 10000 if destroy else 1))
    turn(table, mid, PLAYER)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
        if 'Wax Rampart: Half Cover' in c.display_name and c.destination == Position(x=cell[0], y=cell[1]))
    commit(table, mid, cid)
    turn(table, mid, OTHER)
    engine = check_reload(combat, mid, tmp_path)
    wall = next(a for a in engine.action_catalog.values() if a.owner_id == OTHER and a.display_name == 'Attack a wall section')
    assert wall.range_ft >= (5 if item == 'jian' else 10)
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name.startswith('Attack a wall section') and c.destination == Position(x=cell[0], y=cell[1]))
    before = engine.state.model_dump(mode='json')
    result = act(table, mid, cid)
    if triggers:
        assert result['status'] == 'REACTION_REQUIRED', result
        assert result['reaction']['reaction'] == 'Melting Rebuke'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        label = json.dumps(result['reaction']['choice'])
        assert 'temporary Wax mark' in label
        assert 'Proficiency Bonus' in label
        assert act(table, mid, cid, [answer(result, options=['rebuke'])])['status'] == 'COMMITTED'
    else:
        assert result['status'] == 'COMMITTED', result
    engine = check_reload(combat, mid, tmp_path)
    assert (engine.state.actors[OTHER].current_hp < before['actors'][OTHER]['current_hp']) == triggers
    assert engine.state.actors[PLAYER].reaction_available == (not triggers)
    active = [z for z in engine.state.zones.values() if z.active and MOLD in z.source_definition_id]
    assert bool(active) == (not (triggers or destroy))
    if destroy:
        assert any(e.event_type == 'ZONE_REMOVED' and e.payload.get('reason') == 'DESTROYED' for e in engine.events)
    end = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    direct_commit(combat, mid, tmp_path, end.candidate_id)


def test_clinging_prompt_expands_cultivation_points(tmp_path):
    combat, table, mid = fixture(tmp_path, [PRESS, CLINGING])
    turn(table, mid, PLAYER)
    engine = combat._load_session(mid).engine
    cid = min((c for c in engine.legal_candidates() if c.display_name.startswith('Press Seal') and OTHER in c.target_ids
        and (c.display_name == 'Press Seal' or 'Clinging Seal' in c.display_name)), key=lambda c: 'Clinging Seal' not in c.display_name).candidate_id
    result = act(table, mid, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    assert '1 additional Cultivation Point' in result['reaction']['moment']
    assert act(table, mid, cid, [answer(result, options=['strengthen'])])['status'] == 'COMMITTED'
    engine = check_reload(combat, mid, tmp_path)
    end = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    direct_commit(combat, mid, tmp_path, end.candidate_id)


def test_unseen_movement_does_not_grant_ai_owner_a_trace(tmp_path):
    def setup(bundle, other):
        setup_trail(bundle, other)
        seed(bundle, 'Blind keeper', [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self',
            'duration': {'kind': 'until_removed'}}], target='SELF')
    combat, table, mid = fixture(tmp_path, [TRAIL], configure=setup)
    turn(table, mid, PLAYER)
    commit(table, mid, candidate(combat, mid, 'Seed Wax', OTHER))
    commit(table, mid, candidate(combat, mid, 'Blind keeper'))
    turn(table, mid, OTHER)
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode='LOCAL_AUTO')
    engine = check_reload(combat, mid, tmp_path)
    assert not stealth.sees(engine, engine.state.actors[PLAYER], engine.state.actors[OTHER])
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination == Position(x=5, y=6))
    commit(table, mid, cid)
    engine = check_reload(combat, mid, tmp_path)
    assert not any(c.condition_id == TRACE for c in engine.state.actors[OTHER].conditions.values())
    end = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    direct_commit(combat, mid, tmp_path, end.candidate_id)
