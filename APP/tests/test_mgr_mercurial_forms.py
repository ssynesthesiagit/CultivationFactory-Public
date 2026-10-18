"""Prima Materia's owner turn choices through committed native table actions."""
import pytest
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


def test_prima_materia_form_condition_label_states_effect_and_expiry(tmp_path):
    combat, table, mid = formed(tmp_path, 'Adamant')
    engine = reload(tmp_path, mid)
    label = m.held(engine.state.actors[OWNER], 'perfected').data['label']
    assert label == 'Adamant: +2 AC until your next turn starts'
    assert label != 'Adamant Form'
