"""A2R03F8: printed Beast-Echo creature and Guard source boundaries at the table."""
from types import SimpleNamespace

import pytest

from combat.ext import beast_echo_marrow as marrow
from combat.gate5_service import CombatService
from tests.test_a2r03_fix_round import _prepare_pressure, _play_picked
from tests.test_a2r03_review_repairs import _action
from tests.test_a2r03_review_round5 import _owner_action, _take_owner_turn
from tests.test_a2r11_foundations import (
    ROOT, FIGHTER, SERVICE_FOE, MARROW_BARE, ECHO,
    _marrow, _service_fight, _candidate, _engine, _play, _until,
)


@pytest.mark.parametrize('kind,qualifies', [('Demon Beast', True), ('Demon', False)])
def test_demon_beast_hit_echo_and_predator_after_cold_table_reload(
        tmp_path, monkeypatch, kind, qualifies):
    def prepare(bundles):
        _owner_action(bundles, 'Measured hit', [{
            'type': 'attack', 'attack_kind': 'melee', 'count': 1,
            'on_hit': [{'type': 'damage', 'applies_to': 'target', 'flat': 1,
                        'dice': {'count': 1, 'sides': 2}, 'damage_types': ['piercing']}],
            'on_miss': []}])['parameters']['typed']['numbers']['attack_bonus'] = 30

    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                      foe_creature_types=(kind,), prepare=prepare)
    _take_owner_turn(table, mid)
    assert _engine(combat, mid).state.actors[FIGHTER].resources[ECHO] == 0
    _, prompts = _play_picked(table, mid, _candidate(table, mid, 'Measured hit', SERVICE_FOE),
                             lambda p: 'temp_hp' if p['reaction'] == 'Predator Answer' else 'DECLINE')
    cold = _engine(CombatService(ROOT, tmp_path), mid)
    owner = cold.state.actors[FIGHTER]
    assert marrow.beast_kinded(cold.state.actors[SERVICE_FOE]) is qualifies
    assert owner.resources[ECHO] == int(qualifies)
    assert owner.temporary_hp == (owner.proficiency_bonus if qualifies else 0)
    assert any(p['reaction'] == 'Predator Answer' for p in prompts) is qualifies


@pytest.mark.parametrize('source,qualifies', [
    ('TAL_BRUTE_MOUNTAIN_MOVING_PALM', False),
    ('TAL_BERSERKER_BATTER', False), ('TAL_ATHLETICS_RUSH', False),
    ('TAL_WRESTLING_THROW', False), ('TAL_SPIRIT_COMPANIONS_BINDING_SEAL', False),
    ('tianxia.talent.warleader.command', False), ('action:radiance.aura', False),
    ('tianxia.talent.blood.strike', True), ('TAL_BEASTMASTERY_BITE', True),
    ('action:predator.bite', True), ('action:natural_weapon.claw', True),
    ('action:fear.pressure', True), ('action:pack_aura.pulse', True),
])
def test_guard_source_taxonomy_is_distinct_from_technique_compatibility(source, qualifies):
    engine = SimpleNamespace(_active_action_source_id=source)
    assert marrow._scope_source(engine, SimpleNamespace(creature_types=('Humanoid',))) is qualifies


@pytest.mark.parametrize('source,linked,qualifies', [
    ('TAL_BRUTE_MOUNTAIN_MOVING_PALM', False, False),
    ('action:radiance.aura', False, False),
    ('tianxia.talent.blood.strike', False, True),
    ('TAL_BRUTE_MOUNTAIN_MOVING_PALM', True, True),
])
def test_guard_printed_source_or_prior_damage_link_after_cold_table_reload(
        tmp_path, monkeypatch, source, linked, qualifies):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        _action(bundles, 'Incoming technique', [{'type': 'damage', 'applies_to': 'target',
            'flat': 10, 'damage_types': ['bludgeoning']}], source=source)
        _owner_action(bundles, 'Establish link', [{'type': 'damage', 'applies_to': 'target',
            'flat': 1, 'damage_types': ['piercing']}])

    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow('Awakened'), MARROW_BARE,
                                      foe_creature_types=('Humanoid',), prepare=prepare)
    if linked:
        _take_owner_turn(table, mid)
        _play(table, mid, _candidate(table, mid, 'Establish link', SERVICE_FOE), answer='DECLINE')
        _play(table, mid, table.state(mid)['menu']['end_turn'], answer='DECLINE')
        _until(table, mid, SERVICE_FOE, answer='DECLINE')
    before = _engine(combat, mid)
    owner = before.state.actors[FIGHTER]
    hp, held = owner.current_hp, owner.resources[ECHO]
    assert held == 1 and owner.reaction_available
    _, prompts = _play_picked(table, mid, _candidate(table, mid, 'Incoming technique', FIGHTER),
                             lambda p: 'USE' if p['reaction'] == 'Marrow Pack Guard' else 'DECLINE')
    cold = _engine(CombatService(ROOT, tmp_path), mid)
    owner = cold.state.actors[FIGHTER]
    assert any(p['reaction'] == 'Marrow Pack Guard' for p in prompts) is qualifies
    assert owner.resources[ECHO] == held - int(qualifies)
    assert owner.reaction_available is (not qualifies)
    reduction = before.state.actors[FIGHTER].proficiency_bonus + 2
    assert owner.current_hp == hp - 10 + (reduction if qualifies else 0)
    receipts = [e for e in cold.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == marrow.GUARD]
    assert len(receipts) == int(qualifies)
