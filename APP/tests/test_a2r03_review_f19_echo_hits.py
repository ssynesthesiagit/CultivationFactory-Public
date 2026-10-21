"""Canonical hit scope and actual prior damage survive table commit/reload."""
import pytest

from combat import pressure
from combat.ext import beast_echo_marrow as marrow
from combat.gate5_service import CombatService
from tests import test_a2r11_foundations as f
from tests.public_snapshot import requires_private_prose
from tests.test_a2r03_fix_round import _prepare_pressure, _play_picked
from tests.test_a2r03_review_repairs import _action
from tests.test_a2r03_review_round5 import _owner_action, _take_owner_turn


def test_actual_unarmed_hit_generates_echo_after_commit_and_reload(tmp_path, monkeypatch):
    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE, ally=True,
        foe_creature_types=('Humanoid',))
    _take_owner_turn(table, mid)
    before = f._engine(combat, mid)
    assert before.state.actors[f.FIGHTER].resources[f.ECHO] == 0
    f._play(table, mid, f._candidate(table, mid, 'Unarmed Strike', f.SERVICE_FOE))
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    actor = cold.state.actors[f.FIGHTER]
    assert actor.resources[f.ECHO] == 1
    assert actor.turn_flags[pressure.CLOCK][f.ECHO] == {
        'round': cold.state.round_number, 'count': 1, 'ends_left': 2}
    assert sum(e.event_type == 'RESOURCE_GAINED' and e.actor_id == f.FIGHTER
               and e.source_definition_id == 'passive:' + marrow.GENERATE
               for e in cold.events) == 1
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == f.FIGHTER
                   and e.payload.get('resource_id') == f.ECHO for e in cold.events)


def test_echo_does_not_generate_without_a_packmate_at_the_table(tmp_path, monkeypatch):
    """Printed trigger: an ally or bonded companion within 30 ft of the fighter
    or the target (or a beast-aspected target). A lone enemy is not enough."""
    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE, ally=False,
        foe_creature_types=('Humanoid',))
    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, 'Unarmed Strike', f.SERVICE_FOE))
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    owner = cold.state.actors[f.FIGHTER]
    assert owner.resources[f.ECHO] == 0
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.actor_id == f.FIGHTER
                   and e.source_definition_id == 'passive:' + marrow.GENERATE
                   for e in cold.events)
    assert f.ECHO not in (owner.turn_flags.get(pressure.CLOCK) or {})


def test_echo_once_per_round_refreshes_instead_of_stacking_at_the_table(tmp_path, monkeypatch):
    def prepare(bundles):
        row = _owner_action(bundles, 'Measured hit', [{
            'type': 'attack', 'attack_kind': 'melee', 'count': 1,
            'on_hit': [{'type': 'damage', 'applies_to': 'target', 'flat': 1,
                        'damage_types': ['bludgeoning']}], 'on_miss': []}])
        row['parameters']['typed']['numbers']['attack_bonus'] = 30

    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE, ally=True,
        foe_creature_types=('Humanoid',), prepare=prepare)
    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, 'Measured hit', f.SERVICE_FOE))
    first = f._engine(CombatService(f.ROOT, tmp_path), mid)
    clock = dict(first.state.actors[f.FIGHTER].turn_flags[pressure.CLOCK][f.ECHO])
    assert first.state.actors[f.FIGHTER].resources[f.ECHO] == 1
    f._play(table, mid, f._candidate(table, mid, 'Measured hit', f.SERVICE_FOE))
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    owner = cold.state.actors[f.FIGHTER]
    assert owner.resources[f.ECHO] == 1
    assert owner.turn_flags[pressure.CLOCK][f.ECHO] == clock
    gains = [e for e in cold.events if e.event_type == 'RESOURCE_GAINED'
             and e.actor_id == f.FIGHTER
             and e.source_definition_id == 'passive:' + marrow.GENERATE]
    assert len(gains) == 1


def _prior_damage(bundles, receipt):
    _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
    # Establish the receipt with legal table effects, not fields that belong
    # to ActorState but are forbidden on the compiled ActorTemplate.
    effects = ([{'type': 'temp_hp', 'applies_to': 'target', 'flat': 1}]
               if receipt == 'temporary' else [])
    effects.append({'type': 'damage', 'applies_to': 'target',
                    'flat': 0 if receipt == 'zero' else 1, 'damage_types': ['piercing']})
    _owner_action(bundles, 'Establish link', effects)
    _action(bundles, 'Incoming technique', [{
        'type': 'damage', 'applies_to': 'target', 'flat': 10,
        'damage_types': ['bludgeoning']}], source='action:test.ordinary_pressure')


def _assert_prior(cold, receipt):
    event = next(e for e in cold.events if e.event_type == 'DAMAGE_COMMITTED'
                 and e.source_definition_id.endswith('Establish_link'))
    assert event.payload['hp_damage'] == int(receipt == 'hp')
    assert event.payload['temporary_hp_absorbed'] == int(receipt == 'temporary')


@pytest.mark.parametrize('receipt', [
    'zero',
    pytest.param('hp', marks=requires_private_prose),
    pytest.param('temporary', marks=requires_private_prose),
])
def test_guard_requires_positive_prior_damage_at_table(tmp_path, monkeypatch, receipt):
    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow('Awakened'), f.MARROW_BARE,
        foe_creature_types=('Humanoid',), prepare=lambda b: _prior_damage(b, receipt))
    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, 'Establish link', f.SERVICE_FOE))
    _assert_prior(f._engine(CombatService(f.ROOT, tmp_path), mid), receipt)
    f._play(table, mid, table.state(mid)['menu']['end_turn'])
    f._until(table, mid, f.SERVICE_FOE, answer='DECLINE')
    before = f._engine(combat, mid).state.actors[f.FIGHTER]
    _, prompts = _play_picked(
        table, mid, f._candidate(table, mid, 'Incoming technique', f.FIGHTER),
        lambda p: 'USE' if p['reaction'] == 'Marrow Pack Guard' else 'DECLINE')
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    owner = cold.state.actors[f.FIGHTER]
    qualifies = receipt != 'zero'
    assert any(p['reaction'] == 'Marrow Pack Guard' for p in prompts) is qualifies
    assert owner.resources[f.ECHO] == 1 - int(qualifies)
    assert owner.reaction_available is (not qualifies)
    assert owner.current_hp == before.current_hp - 10 + (
        owner.proficiency_bonus + 2 if qualifies else 0)


@pytest.mark.parametrize('receipt', ['zero', 'hp', 'temporary'])
def test_pack_marrow_requires_positive_owner_damage_at_table(tmp_path, monkeypatch, receipt):
    def prepare(bundles):
        _prior_damage(bundles, receipt)
        row = _owner_action(bundles, 'Ally scope hit', [{
            'type': 'attack', 'attack_kind': 'melee', 'count': 1,
            'on_hit': [{'type': 'damage', 'applies_to': 'target',
                        'flat': 1, 'damage_types': ['bludgeoning']}], 'on_miss': []}])
        row['parameters']['typed']['numbers']['attack_bonus'] = 30
        owner = next(b for b in bundles if b['actor_id'] == f.FIGHTER)
        ally = next(b for b in bundles if b['actor_id'] == f.SERVICE_ALLY)
        owner['action_catalog'].remove(row)
        owner['actor_template']['action_ids'].remove(row['source_definition_id'])
        row['owner_id'] = f.SERVICE_ALLY
        row['costs'] = []
        ally['action_catalog'].append(row)
        ally['actor_template']['action_ids'].append(row['source_definition_id'])

    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE, ally=True,
        foe_creature_types=('Humanoid',), prepare=prepare)
    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, 'Establish link', f.SERVICE_FOE))
    _assert_prior(f._engine(CombatService(f.ROOT, tmp_path), mid), receipt)
    f._play(table, mid, table.state(mid)['menu']['end_turn'])
    f._until(table, mid, f.SERVICE_ALLY, answer='DECLINE')
    _, prompts = _play_picked(
        table, mid, f._candidate(table, mid, 'Ally scope hit', f.SERVICE_FOE),
        lambda p: 'strike' if p['reaction'] == 'Pack-Marrow Strike' else 'DECLINE')
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    bonus = cold.state.actors[f.FIGHTER].proficiency_bonus * (1 if receipt == 'zero' else 2)
    assert any(p['reaction'] == 'Pack-Marrow Strike' and f'add {bonus} damage' in p['moment']
               for p in prompts)
    extra = [e for e in cold.events if e.event_type == 'DAMAGE_COMMITTED'
             and e.actor_id == f.FIGHTER and f.SERVICE_FOE in e.target_ids]
    assert extra[-1].payload['hp_damage'] == bonus
    assert cold.state.actors[f.FIGHTER].resources[f.ECHO] == 0
