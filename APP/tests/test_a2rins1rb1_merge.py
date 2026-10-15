"""Merged Reservoir refinement and borrowed Forms through table commits/reload."""
import pytest

from combat.ext import forged_exhaustion as exhaustion, qi_path as qi
from combat.ext.reservoir_refinement import FEATURE
from combat.tabletop import engine_button_description
from tests.cw2_service_support import add_action
from tests.test_a2r_borrowed_golden_form import INSIGHT, setup, use, by_name
from tests.worker2_support import FOE, OWNER, candidate, reload, turn


def drain(amount):
    def prepare(bundles):
        add_action(bundles[0], 'Drain scenario Qi', [
            {'type': 'spend_resource', 'applies_to': 'self',
             'resource_id': qi.QI, 'flat': amount}], target='SELF')
    return prepare


@pytest.mark.parametrize('permanent', [False, True])
def test_refinement_keeps_form_amount_and_second_use_cost_after_reload(tmp_path, permanent):
    combat, table, mid = setup(tmp_path, cl=17, insights=(INSIGHT, FEATURE),
                               bundle_transform=drain(80))
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'reservoir'})
    if permanent:
        use(combat, table, mid, 'Golden Core Form: Golden Core Reservoir')
    use(combat, table, mid, 'Drain scenario Qi')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    action = engine.action_catalog[candidate(combat, mid, 'Golden Core Reservoir').source_definition_id]
    numbers = action.parameters['typed']['numbers']
    amount = (2 if permanent else 1) * int(numbers['pb']) + int(numbers['key_mod'])
    text = engine_button_description(action.model_dump(mode='json')).split('\n\n')[0]
    assert 'Unperfected Reservoir: regain' in text and 'Perfected Reservoir: regain' in text
    assert 'borrowed' in text and 'twice per scene' in text and 'Exhaustion' in text
    assert qi.form_state(engine, engine.state.actors[OWNER], 'reservoir') is permanent
    before = engine.state.actors[OWNER].resources[qi.QI]
    use(combat, table, mid, 'Golden Core Reservoir')
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[qi.QI] == before + amount
    assert owner.turn_flags['golden_core_reservoir_round_used'] == 1
    assert exhaustion.level(owner) == 0
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert by_name(engine, 'Golden Core Reservoir')
    before = engine.state.actors[OWNER].resources[qi.QI]
    use(combat, table, mid, 'Golden Core Reservoir')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[qi.QI] == before + amount
    assert owner.turn_flags['golden_core_reservoir_round_used'] == 2
    assert exhaustion.level(owner) == 1
    assert exhaustion.locked_level(engine, owner) == 1
    restored = max(e.sequence for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                   and e.payload.get('resource_id') == qi.QI)
    exhausted = max(e.sequence for e in engine.events if e.event_type == 'CONDITION_APPLIED'
                    and e.payload.get('condition_id') == exhaustion.CONDITION_ID)
    assert restored < exhausted
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    assert not by_name(reload(tmp_path, mid), 'Golden Core Reservoir')


def test_borrowed_unperfected_reservoir_does_not_spend_refinement_at_turn_start(tmp_path):
    combat, table, mid = setup(tmp_path, cl=17, insights=(INSIGHT, FEATURE),
                               bundle_transform=drain(96))
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'reservoir'})
    use(combat, table, mid, 'Drain scenario Qi')
    assert reload(tmp_path, mid).state.actors[OWNER].resources[qi.QI] == 0
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not owner.turn_flags.get('golden_core_reservoir_round_used')
    assert owner.resources[qi.QI] == 2  # Only permanent Perfected Stable recovers.
    assert owner.bonus_action_available
    assert by_name(engine, 'Golden Core Reservoir')
