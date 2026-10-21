"""Regressions for the F16R review: the printed CL3/CL10 payment exclusions
must stay enforced after the shared payment rules were factored out.

Source records: ``tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw``
(CL3) and ``...feature.second_furnace_core`` (CL10).
"""
import pytest

from combat.ext import furnace_payments as payments
from combat.ext import furnace_runtime as runtime
from tests.test_second_furnace_native import (
    game, fight, engine, OWNER, f,
)
from tests.test_second_furnace_review_f15 import _admit, _payments, _resources


@pytest.mark.parametrize('key', ['sacrifice', 'lifespan', 'maximum_reduction',
                                 'expensive_materials', 'another_creature'])
def test_core_cannot_pay_a_printed_excluded_cost(key):
    """CL10: "Devil Qi cannot pay" each of these, so no Core substitution is quoted."""
    assert payments.core_cost_allowed({'ordinary_qi': 1, key: 1}) is False


@pytest.mark.parametrize('key', ['artifact_charges', 'secret', 'secret_law', 'immortal', 'immortal_art'])
def test_core_needs_the_source_to_accept_devil_qi_for_artifact_and_high_law_costs(key):
    """CL10: artifact charges / Secret-Law / Immortal-Art costs only when the source permits it."""
    assert payments.core_cost_allowed({'ordinary_qi': 1, key: 1}) is False
    assert payments.core_cost_allowed({'ordinary_qi': 1, key: 1, 'accepts_devil_qi': 1}) is True


def test_core_allows_ordinary_and_plain_permanent_duration_costs():
    """CL10 excludes a *permanent sacrifice*, not every permanent-duration feature;
    the Overdraw record's separate "permanent or indefinite transformations" floor
    is tested below."""
    assert payments.core_cost_allowed({'ordinary_qi': 1}) is True
    assert payments.core_cost_allowed({'ordinary_qi': 1, 'permanent': 1}) is True
    assert payments.core_cost_allowed({'ordinary_qi': 0}) is False


@pytest.mark.parametrize('key', ['lifespan', 'maximum_reduction', 'another_creature'])
def test_overdraw_cannot_reduce_lifespan_maximum_resource_or_another_creatures_cost(key):
    """CL3: "Demon Seed Overdraw cannot reduce" these, so no reduction is quoted at all."""
    assert payments.overdraw_reduction({'ordinary_qi': 1, key: 1}, 8, 6) is None


@pytest.mark.parametrize('key', ['expensive_materials', 'permanent', 'indefinite', 'sacrifice'])
def test_overdraw_keeps_the_printed_one_qi_floor_for_protected_costs(key):
    """CL3: these costs "remain at least 1 Qi", so the reduction stops one short."""
    assert payments.overdraw_reduction({'ordinary_qi': 1, key: 1}, 8, 6) == 6


@pytest.mark.parametrize('classification,expected', [
    ({'lifespan': 1}, {'ordinary'}),
    ({'maximum_reduction': 1}, {'ordinary'}),
    ({'another_creature': 1}, {'ordinary'}),
    ({'expensive_materials': 1}, {'ordinary', 'seed'}),
    ({'sacrifice': 1}, {'ordinary', 'seed'}),
])
def test_journey_payments_obey_the_restored_printed_exclusions(tmp_path, monkeypatch, classification, expected):
    """Service level: a source-scoped printed classification admitted through the
    real Journey world fact removes the excluded payments from the cold-reloaded menu."""
    cold, jid, declare, state = game(tmp_path, monkeypatch, cl=18, seed='f17-exclusion-' + str(classification))
    _resources(cold, jid, QI=8, DEVIL=2, CORRUPTION=0)
    action = next(a for a in state['actors'][OWNER]['bundle']['action_catalog']
                  if a.get('parameters', {}).get('typed', {}).get('source') == runtime.ENGINE)
    _admit(cold, jid, declare, 'cost_profile', {
        'source_rule': action['source_definition_id'],
        'quotation': 'The printed CL3/CL10 exclusion applies to this activation.',
        'classification': classification}, 'f17-printed-price')
    _menu, offered = _payments(cold, jid)
    assert set(offered) == expected


def test_declared_lifespan_cost_blocks_combat_core_substitution_but_not_without_it(tmp_path, monkeypatch):
    """Engine level: the same admitted printed classification reaches the real
    combat source profile, so ``devil_payment_permitted`` declines the Core quote."""
    from combat import alternative_payments
    for declared in (False, True):
        cold, jid, declare, state = game(tmp_path / str(declared), monkeypatch, cl=10,
                                         seed='f17-combat-lifespan-' + str(declared))
        _resources(cold, jid, QI=2, DEVIL=3, CORRUPTION=0)
        action = next(a for a in state['actors'][OWNER]['bundle']['action_catalog']
                      if a['display_name'] == 'Force Mantle')
        if declared:
            _admit(cold, jid, declare, 'cost_profile', {
                'source_rule': action['source_definition_id'],
                'quotation': 'This activation costs lifespan.',
                'classification': {'lifespan': 1}}, 'f17-combat-printed-price')
        mid = fight(cold, jid)
        saved = engine(cold, mid)
        actor = saved.state.actors[OWNER]
        plans = alternative_payments.options(saved, actor, action['source_definition_id'], ((f.QI, 3),))
        core = [plan for plan in plans if plan.source_id == f.CORE]
        assert bool(core) is (not declared), (declared, [(p.source_id, p.covered) for p in plans])
