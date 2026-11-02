"""Heavenly Body F3 review fixes: no unused activation/admission scaffolding,
and Heaven-Rejecting Marrow's timing prompt respects a fixed save outcome.
"""
from types import SimpleNamespace

from combat import activation_settlement, feature_access
from combat.ext import heavenly_rejection as hr
from combat.ext.foundation_combat import feature

MARROW = feature('integrity', 'heaven_rejecting_marrow')


def test_activation_settlement_exposes_only_the_provenance_profile():
    for name in ('settle', 'receipt', 'path_numbers'):
        assert not hasattr(activation_settlement, name)
    assert callable(activation_settlement.profile)


def test_feature_access_has_no_unwired_admission_path():
    assert not hasattr(feature_access, 'admit')
    assert not hasattr(feature_access, 'effective_cl')
    assert callable(feature_access.acquire)


def run_rejection(monkeypatch, declared):
    asked = {}

    def ask(engine, intent, checkpoint, target, kind, options, **kw):
        asked.update(options=list(options), prompt=kw['prompt'], automatic=kw['automatic'])
        return []

    monkeypatch.setattr(hr, 'row_of', lambda engine, aid, block, key: {'pb': 2, 'x': 1})
    monkeypatch.setattr(hr, 'available', lambda *a: True)
    monkeypatch.setattr(hr, 'payable', lambda *a, **k: True)
    monkeypatch.setattr(hr, 'declared_outcome', lambda engine, target, roll: declared)
    monkeypatch.setattr(hr, 'held', lambda target, key: SimpleNamespace(data={'feature': MARROW}))
    monkeypatch.setattr(hr, 'vessel_ready', lambda engine, target: False)
    monkeypatch.setattr(hr, 'roll_names', lambda named: set())
    monkeypatch.setattr(hr, 'checkpoint_id', lambda *a: 'checkpoint')
    monkeypatch.setattr(hr, 'ask', ask)
    monkeypatch.setattr('combat.ext.heavenly_body_source.bodily_source', lambda *a: False)
    engine = SimpleNamespace(state=SimpleNamespace(actors={}), action_catalog={})
    roll = SimpleNamespace(roll_id='r1', total=5, natural_result=None)
    target = SimpleNamespace(entity_id='owner', display_name='Owner')
    result = hr.rejection(engine, target, 'CON', 14, roll, 'save:test', 'before_outcome', {})
    assert result is None
    return asked


def test_fixed_success_offers_no_marrow_wait_and_no_failure_claim(monkeypatch):
    asked = run_rejection(monkeypatch, 'success')
    assert asked['options'] == ['use']
    assert asked['automatic'] is False
    assert 'already fixed as a success' in asked['prompt']
    assert 'declared a failure' not in asked['prompt']
    assert 'may wait' not in asked['prompt']


def test_declared_failure_keeps_marrow_wait_before_consequences(monkeypatch):
    asked = run_rejection(monkeypatch, 'failure')
    assert asked['options'][0] == 'wait'
    assert asked['automatic'] is True
    assert 'may wait for Heaven-Rejecting Marrow' in asked['prompt']


def test_unforced_roll_keeps_marrow_wait(monkeypatch):
    asked = run_rejection(monkeypatch, None)
    assert asked['options'][0] == 'wait'
    assert 'may wait for Heaven-Rejecting Marrow' in asked['prompt']
