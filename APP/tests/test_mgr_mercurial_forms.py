"""Prima Materia's owner turn choices through committed native table actions."""
from types import SimpleNamespace

import pytest

from combat import activation_settlement
from combat.ext import rider_choices
from combat.ext import mgr_reserve_mercurial_cultivator_mercurial_qi as m
from combat.flight import profile
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, FOE
from tests.mgr_mercurial_support import source_candidate
from tests.h1_support import sheet


def formed(tmp_path, name):
    features = [m.PREFIX + key for key in m.LEVELS]
    combat, table, mid = fixture(tmp_path, [*features, 'FIRE_BASE_IGNITE'], cl=18,
        seed='MERCURIAL-FIRE', foe_sheet=sheet(['FIRE_BASE_CONFLAGRATION'], cl=18))
    settle(table, mid, candidate(combat, mid, 'Prima Materia').candidate_id)
    choices = {'choice:needle.mercurial.form': [name], 'choice:needle.mercurial.flowing_foe': [FOE]}
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices=choices)
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices=choices)
    else:
        pytest.fail('Owner turn did not begin')
    return combat, table, mid


@pytest.mark.parametrize('name', ['Adamant', 'Flowing', 'Vapor', 'Reflective', 'Restorative'])
def test_perfected_forms_native_modifiers_flight_hp_and_reload(tmp_path, name):
    combat, table, mid = formed(tmp_path, name)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert m.held(actor, 'perfected').data['form'] == name
    if name == 'Adamant':
        assert any(r.target_field == 'armor_class' and r.value == 2 for r in actor.modifiers.values())
    elif name == 'Flowing':
        assert engine._effective_speed(actor) == 45
        assert m.held(actor, 'flowing_foe').data['creature'] == FOE
    elif name == 'Vapor':
        assert profile(engine, actor).speed_ft == 40 and profile(engine, actor).hover
        moves = [c for c in engine.legal_candidates() if c.destination and c.destination.z > 0 and c.canonical_path]
        assert moves
        settle(table, mid, moves[0].candidate_id)
        assert reload(tmp_path, mid).state.actors[OWNER].position.z > 0
    elif name == 'Reflective':
        assert m.held(actor, 'next_save')
    elif name == 'Restorative':
        assert actor.temporary_hp == 2 * actor.proficiency_bonus


@pytest.mark.parametrize('name', ['Conductive', 'Corrosive'])
def test_perfected_damage_riders_use_real_qi_attack_and_one_recipient(tmp_path, name):
    combat, table, mid = formed(tmp_path, name)
    settle(table, mid, source_candidate(combat, mid, 'FIRE_BASE_IGNITE', FOE).candidate_id, choices={
        'choice:needle.mercurial.transmute': None, 'choice:needle.mercurial.mutable_attack': None,
        'choice:needle.mercurial.conductive_target': [FOE], 'choice:needle.mercurial.conductive': ['THUNDER']})
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER and FOE in e.target_ids]
    assert damage, 'The deterministic attack must actually damage the creature'
    if name == 'Conductive':
        assert any(e.payload['damage_type'] == 'THUNDER' for e in damage)
    else:
        assert any(c.condition_id == 'condition:typed.reaction_denied' for c in engine.state.actors[FOE].conditions.values())


def test_mutable_damage_uses_selected_die_new_result_and_cold_replay(tmp_path):
    combat, table, mid = formed(tmp_path, 'Adamant')
    prompts = settle(table, mid, source_candidate(combat, mid, 'FIRE_BASE_IGNITE', FOE).candidate_id, choices={
        'choice:needle.mercurial.transmute': None, 'choice:needle.mercurial.mutable_attack': ['0']})
    engine = reload(tmp_path, mid)
    rerolls = [r for r in engine.rolls if r.reason == 'MUTABLE_DAMAGE']
    assert len(rerolls) == 1 and len(rerolls[0].dice) == 1
    committed = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER and FOE in e.target_ids]
    assert committed, 'the reroll must reach committed damage'
    # Exact arithmetic: the packet is the original attack roll, minus the SELECTED die (index 0) and plus the new result.
    pos = next(i for i, r in enumerate(engine.rolls) if r is rerolls[0])
    original = [r for r in engine.rolls[:pos] if r.reason.startswith('DAMAGE')][-1]
    assert committed[0].payload['rolled_or_pending_damage'] == original.total - original.dice[0] + rerolls[0].total
    assert any(p['context']['reaction_source_id'] == 'choice:needle.mercurial.mutable_attack' for p in prompts)
    assert engine.state.actors[OWNER].turn_flags.get('_round_mercurial_mutable')


def _mutable_damage_call(monkeypatch, rolls, packet, chosen):
    """Drive the real mutable_damage hook with a synthetic packet; the Prima Materia gate and the picker are doubles."""
    labels_seen = {}

    def fake_pick(engine, actor, key, title, options, **kwargs):
        labels_seen.update(kwargs['labels'])
        return chosen

    monkeypatch.setattr(m, 'active', lambda engine, actor, name: True)
    monkeypatch.setattr(m, 'stamp', lambda engine: 1)
    monkeypatch.setattr(m, 'proficiency', lambda engine, actor: 2)
    monkeypatch.setattr(activation_settlement, 'profile', lambda engine, actor, action: {'qi_powered': True})
    monkeypatch.setattr(rider_choices, 'pick', fake_pick)
    ctx = SimpleNamespace(engine=SimpleNamespace(rolls=rolls), actor=SimpleNamespace(turn_flags={}, entity_id='owner'),
                          action=SimpleNamespace(display_name='Fire Ignite'), intent=None, damage_roll=packet)
    answer = m.mutable_damage(ctx, {}, [], 2)
    return answer, labels_seen


def test_mutable_damage_labels_the_packets_own_roll_after_a_check(monkeypatch):
    """Regression: the reroll must name the packet's own dice even when a check is logged after the damage roll.
    Taking the last roll in the log would label the check's single d20 instead of the two damage dice."""
    packet = SimpleNamespace(dice=(2, 2), total=4, reason='DAMAGE:Fire Ignite', roll_id='d1')
    check = SimpleNamespace(dice=(17,), total=17, reason='CHECK:Perception', roll_id='c1')
    answer, labels = _mutable_damage_call(monkeypatch, [packet, check], packet, chosen=['1'])
    assert sorted(labels) == ['0', '1']
    assert labels['0'].startswith('Die 1: 2;')
    assert answer == {'indices': [1]}


def test_mutable_damage_ignores_a_later_damage_roll_of_another_packet(monkeypatch):
    """Regression: with two damage packets in the log, the reroll must name the packet being rerolled, not the newest one."""
    packet = SimpleNamespace(dice=(2, 2), total=4, reason='DAMAGE:Fire Ignite', roll_id='d1')
    other = SimpleNamespace(dice=(6, 6, 6), total=18, reason='DAMAGE:Other Source', roll_id='d2')
    answer, labels = _mutable_damage_call(monkeypatch, [packet, other], packet, chosen=['0'])
    assert sorted(labels) == ['0', '1']
    assert answer == {'indices': [0]}


def test_prima_materia_form_condition_label_states_effect_and_expiry(tmp_path):
    combat, table, mid = formed(tmp_path, 'Adamant')
    engine = reload(tmp_path, mid)
    label = m.held(engine.state.actors[OWNER], 'perfected').data['label']
    assert label == 'Adamant: +2 AC until your next turn starts'
    assert label != 'Adamant Form'
