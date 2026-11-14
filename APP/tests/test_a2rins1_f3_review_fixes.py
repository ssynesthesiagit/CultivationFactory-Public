"""Third Sol review: service commits and cold replay for each reported edge.

All scenario actions and the off-turn relay are local sealed test fixtures;
no model, embedding server, browser or live fight is used.
"""
import pytest

from combat import ext, typed_executor
from combat.ext import ancestral_bloodline as lineage, qi_path
from combat.gate2_runtime_models import CandidateKind
from combat.tabletop import engine_button_description
from combat.turn_uses import current_turn_key
from tests.cw2_service_support import add_action, seal
from tests.test_a2r_ancestral_bloodline import setup as lineage_setup, pick, qi_bolt, strikes
from tests.test_a2r_battle_musician import (
    _owner_bundle, RHYTHMIC_GUARD, KEEP_THE_MEASURE, FREE_TEMP_HP,
)
from tests.test_a2r_borrowed_golden_form import setup as golden_setup, use, borrowed_condition
from tests.test_a2rins1_f2_review_fixes import qi_spend
from tests.worker2_support import ALLY, FOE, OWNER, fixture, candidate, settle, reload, turn


@pytest.mark.parametrize('amount,bypass,rescue', [
    (65, False, True), (10, True, True), (65, True, False), (20, False, False),
])
def test_f1_phoenix_uses_actual_hp_damage(tmp_path, amount, bypass, rescue):
    def prepare(bundles):
        strikes(bundles)
        add_action(bundles[2], 'Temporary HP buffer', [
            {'type': 'temp_hp', 'applies_to': 'target', 'flat': 20}])
        add_action(bundles[2], 'Threshold strike', [
            {'type': 'damage', 'applies_to': 'target', 'flat': amount,
             'damage_types': ['bludgeoning'], 'bypass_temporary_hp': bypass}])
        seal(bundles[2])

    combat, table, mid = lineage_setup(tmp_path, bundle_transform=prepare, owner_dc=100)
    pick(combat, table, mid, 'Ancestral Bloodline: Vermilion Phoenix -- Fire')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Drain', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Temporary HP buffer', target=OWNER).candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert (before.current_hp, before.temporary_hp, before.maximum_hp) == (5, 20, 60)
    prompts = settle(table, mid, candidate(combat, mid, 'Threshold strike', target=OWNER).candidate_id,
                     picks={'choice:needle.phoenix_continuity': 'remain'})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.phoenix_continuity']
    assert bool(asked) is rescue
    if asked:
        assert 'Ember Continuity' in asked[0]['moment'] and 'Threshold strike' in asked[0]['moment']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.current_hp == (1 if rescue else 0 if bypass else 5)
    assert owner.temporary_hp == (20 if bypass else 0)
    assert owner.resources[lineage.QI] == (96 if rescue else 100)
    assert any(c.condition_id == lineage.PHOENIX_USED for c in owner.conditions.values()) is rescue
    bursts = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id == lineage.INSIGHT]
    assert bool(bursts) is rescue


@pytest.mark.parametrize('name', ['Shove: Prone', 'Grapple', 'Separate attack technique'])
def test_f2_opening_phrase_requires_attack_action_identity(tmp_path, name):
    def prepare(bundles):
        add_action(bundles[0], 'Separate attack technique', [
            {'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1,
             'on_hit': [{'type': 'damage', 'applies_to': 'target', 'flat': 1,
                         'damage_types': ['force']}]}], target='HOSTILE_ENTITY')
        bundles[0]['action_catalog'][-1]['economy'] = 'ACTION'
        seal(bundles[0])

    combat, table, mid = fixture(
        tmp_path, [RHYTHMIC_GUARD], cl=4,
        owner_bundle=_owner_bundle([RHYTHMIC_GUARD], cl=4, qi=100),
        foe_position={'x': 2, 'y': 6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, KEEP_THE_MEASURE).candidate_id)
    engine = reload(tmp_path, mid)
    attack = engine.action_catalog[candidate(combat, mid, name, target=FOE).source_definition_id]
    assert attack.parameters['typed'].get('attack_action', False) is (name != 'Separate attack technique')
    settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    free = [c for c in engine.legal_candidates() if c.display_name == FREE_TEMP_HP]
    assert bool(free) is (name != 'Separate attack technique')
    if free:
        settle(table, mid, candidate(combat, mid, FREE_TEMP_HP, target=ALLY).candidate_id)
        engine = reload(tmp_path, mid)
        assert engine.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
        assert not [c for c in engine.legal_candidates() if c.display_name == FREE_TEMP_HP]


@pytest.mark.parametrize('cl', [16, 17])
def test_f3_first_turn_permanent_selection_preserves_paid_borrow(tmp_path, cl):
    combat, table, mid = golden_setup(tmp_path, cl=cl, bundle_transform=qi_spend)
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    before = reload(tmp_path, mid).state.actors[OWNER]
    borrowed_id = borrowed_condition(before).instance_id
    assert before.resources[qi_path.QI] == 96
    use(combat, table, mid, 'Golden Core Form: Golden Core Reservoir')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert borrowed_condition(owner) is not None
    assert borrowed_condition(owner).instance_id == borrowed_id
    assert qi_path.forms(owner, permanent_only=True) == ('reservoir',)
    assert set(qi_path.forms(owner)) == {'circulating', 'reservoir'}
    assert qi_path.form_state(engine, owner, 'circulating') is False
    assert qi_path.form_state(engine, owner, 'reservoir') is (cl >= 17)
    assert not [c for c in engine.legal_candidates() if c.display_name == 'Borrowed Golden Form']
    use(combat, table, mid, 'Spend test Qi', choices={'choice:needle.golden_benefits': ['temp_hp']})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[qi_path.QI] == 1
    assert owner.temporary_hp == owner.proficiency_bonus
    assert borrowed_condition(owner).instance_id == borrowed_id


@pytest.mark.parametrize('cl', [17, 20])
def test_f3_permanent_overlap_uses_permanent_perfection_without_losing_borrow(tmp_path, cl):
    from tests.test_a2r_borrowed_golden_form import Q
    features = (Q + 'golden_core_form',) + ((Q + 'second_golden_core_form',) if cl == 20 else ())
    combat, table, mid = golden_setup(tmp_path, cl=cl, features=features, bundle_transform=qi_spend)
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    borrowed_id = borrowed_condition(reload(tmp_path, mid).state.actors[OWNER]).instance_id
    # A permanent build choice may coincide with the temporary grant. It must
    # get its own Perfected benefits, then leave the borrowed copy when replaced.
    use(combat, table, mid, 'Golden Core Form: Circulating Golden Core')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert borrowed_condition(owner) is not None
    assert borrowed_condition(owner).instance_id == borrowed_id
    assert qi_path.form_state(engine, owner, 'circulating') is True
    use(combat, table, mid, 'Spend test Qi',
        choices={'choice:needle.golden_benefits': ['temp_hp', 'move'],
                 'choice:needle.golden_step': 'first'})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.temporary_hp == 2 * owner.proficiency_bonus
    if cl == 17:
        use(combat, table, mid, 'Golden Core Form: Golden Core Reservoir')
        engine = reload(tmp_path, mid)
        owner = engine.state.actors[OWNER]
        assert borrowed_condition(owner).instance_id == borrowed_id
        assert qi_path.form_state(engine, owner, 'circulating') is False
        assert qi_path.form_state(engine, owner, 'reservoir') is True
    else:
        assert set(qi_path.forms(owner, permanent_only=True)) == {'stable', 'circulating'}


def test_f4_demon_rider_refreshes_on_another_creatures_turn(tmp_path, monkeypatch):
    def prepare(bundles):
        qi_bolt(bundles)
        add_action(bundles[0], 'Qi counter', [
            {'type': 'damage', 'applies_to': 'target', 'flat': 5, 'damage_types': ['force']}],
            target='HOSTILE_ENTITY', typed={'qi_powered': True})
        bundles[0]['action_catalog'][-1]['costs'] = [[lineage.QI, 1]]
        seal(bundles[0])
        add_action(bundles[2], 'Provoke Qi counter', [{'type': 'test_f3_qi_counter'}], target='SELF')

    def counter(ctx, row):
        # Scenario-only relay: a foe's committed action causes an owned, paid
        # Qi feature to resolve off-turn through the full typed activation path.
        engine = ctx.engine
        owner = engine.state.actors[OWNER]
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == 'Qi counter')
        engine._spend_resource(owner, lineage.QI, 1, action.source_definition_id)
        activation = engine._candidate(CandidateKind.REACTION, owner, action.source_definition_id,
                                       action.display_name, target_ids=(ctx.actor.entity_id,))
        typed_executor.resolve_typed(engine, owner, ctx.actor, action, activation, ctx.intent)

    monkeypatch.setitem(ext.effects(), 'test_f3_qi_counter', counter)
    combat, table, mid = lineage_setup(tmp_path, bundle_transform=prepare)
    pick(combat, table, mid, 'Ancestral Bloodline: Demon-Blood -- Necrotic')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Qi Bolt', target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    stamp = current_turn_key(before)
    rider_count = lambda engine: len([e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                                     and e.source_definition_id == lineage.INSIGHT])
    assert rider_count(before) == 1
    turn(table, mid, FOE)
    assert current_turn_key(reload(tmp_path, mid)) != stamp
    settle(table, mid, candidate(combat, mid, 'Provoke Qi counter').candidate_id)
    engine = reload(tmp_path, mid)
    assert rider_count(engine) == 2
    assert engine.state.actors[OWNER].resources[lineage.QI] == 99
    # A second activation on this same hostile turn cannot take another rider.
    settle(table, mid, candidate(combat, mid, 'Provoke Qi counter').candidate_id)
    engine = reload(tmp_path, mid)
    assert rider_count(engine) == 2
    assert engine.state.actors[OWNER].resources[lineage.QI] == 98


def test_c13_borrowed_reservoir_help_states_form_dependent_amounts(tmp_path):
    combat, table, mid = golden_setup(tmp_path, cl=17, bundle_transform=qi_spend)
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'reservoir'})
    # Leave room below the maximum so the full unperfected recovery is visible.
    use(combat, table, mid, 'Spend test Qi')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    row = candidate(combat, mid, 'Golden Core Reservoir')
    action = engine.action_catalog[row.source_definition_id]
    numbers = action.parameters['typed']['numbers']
    pb, key = int(numbers['pb']), int(numbers['key_mod'])
    text = engine_button_description(action.model_dump(mode='json')).split('\n\n')[0]
    assert f'Unperfected Reservoir: regain {pb + key} Qi' in text
    assert f'Perfected Reservoir: regain {2 * pb + key} Qi' in text
    assert 'borrowed' in text.lower() and 'once per scene' in text
    before = engine.state.actors[OWNER].resources[qi_path.QI]
    use(combat, table, mid, 'Golden Core Reservoir')
    assert reload(tmp_path, mid).state.actors[OWNER].resources[qi_path.QI] == before + pb + key
