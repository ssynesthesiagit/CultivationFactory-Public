"""Regression tests for the Blood-Moon review round (each fails without its fix).

No model, network or live server. Pure registry and helper checks only.
"""
from types import SimpleNamespace as NS

from combat import ext, table_advance
from combat.ext import fate_reader
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


def test_thread_questions_are_the_printed_six():
    import hashlib
    import json
    from pathlib import Path

    rules = json.loads((Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/rules_text.json').read_text())
    section = rules[fate_reader.READ].split('Choose one Thread Question', 1)[1].split('The answer is symbolic', 1)[0]
    printed = [line[2:] for line in section.splitlines() if line.startswith('- ')]
    assert [hashlib.sha256(item.encode()).hexdigest() for item in printed] == [
        '9b5cdbe1636cdea2865d50bc03f73bef88e465f32e6d5d9de8aa2b331cbbe0af',
        '8e98904231c18f094a2b550dee4d9499beba3c5cc970515df074b61387319916',
        'b0f49ae7dfd3857e346d261ac69ea3cc9a39a6492a377d2184f1b202996425f1',
        '521a813a21e99d0ec5223a0d7cc9f2d836b894873d566a0b80a55f6447076c5b',
        'c03a1dd660874ee895ff7b4637e90535ec2aa8c38cf45a39381c858e595c50c2',
        'db4fbecb72b88dbe43d451f3f5235a3a8c2a2af6b81663ec6a2703d0e9e3bcd1',
    ]
    assert fate_reader.THREAD_QUESTIONS == dict(zip(
        ('improve', 'cause', 'danger', 'fail', 'authority', 'branch'), printed))


def test_core_execution_cp_surcharge_is_quoted_on_the_held_cp_pool(monkeypatch):
    # Finding 3: a CP surcharge used to be dropped unless the feature was Qi-powered.
    from combat import activation_settlement
    monkeypatch.setattr(activation_settlement, 'profile', lambda *_a, **_k: {'qi_powered': False})
    surcharge = NS(condition_id=blood.STATE, data={'kind': 'surcharge', 'resource': 'CP', 'amount': 5})
    actor = NS(conditions={'s': surcharge}, resources={'resource:core.stamina': 4})
    engine = NS(action_catalog={'a': NS()})
    listed = {'resource:core.stamina': 2}
    assert blood.surcharge(engine, actor, 'a', listed) == {'resource:core.stamina': 5}
