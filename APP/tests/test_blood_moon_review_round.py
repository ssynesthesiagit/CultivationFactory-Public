"""Regression tests for the Blood-Moon review round (each fails without its fix).

No model, network or live server. Pure registry and helper checks only.
"""
from types import SimpleNamespace as NS

from combat import ext, table_advance
from combat.ext import mgr_reserve_blood_moon_execution_saber_cultivator_write_the_first_sentence as blood

FEATURE = 'tianxia.subpath.qi.blood_moon_execution_saber_cultivator.feature.write_the_first_sentence'
ACCESS = {'kind': 'scripture', 'classification': 'Restricted Scripture', 'reference': 'campaign:execution-hall-scroll'}


def test_acquired_feature_survives_table_normalization():
    # Finding P1: acquire_feature reads saved['features']; normalized() used to drop that key.
    table = table_advance.normalized({'features': [{'id': FEATURE, 'source': dict(ACCESS), 'at': 'now'}]})
    assert table['features'] == [{'id': FEATURE, 'source': dict(ACCESS), 'at': 'now'}]
    assert 'features' in table_advance.empty()


def test_observer_direction_rows_register_on_the_point_information_results_runs():
    # Finding 4: rows were registered on observer_information_rows, which for_observer never runs.
    assert blood.directions in ext._HOOKS['observer_information']
    assert blood.directions not in ext._HOOKS.get('observer_information_rows', [])


def test_core_execution_cp_surcharge_is_quoted_on_the_held_cp_pool(monkeypatch):
    # Finding 3: a CP surcharge used to be dropped unless the feature was Qi-powered.
    from combat import activation_settlement
    monkeypatch.setattr(activation_settlement, 'profile', lambda *_a, **_k: {'qi_powered': False})
    surcharge = NS(condition_id=blood.STATE, data={'kind': 'surcharge', 'resource': 'CP', 'amount': 5})
    actor = NS(conditions={'s': surcharge}, resources={'resource:core.stamina': 4})
    engine = NS(action_catalog={'a': NS()})
    listed = {'resource:core.stamina': 2}
    assert blood.surcharge(engine, actor, 'a', listed) == {'resource:core.stamina': 5}
