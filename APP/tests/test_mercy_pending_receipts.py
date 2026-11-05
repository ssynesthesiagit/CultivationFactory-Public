"""Relevant-only regression for Mercy's support-event bookkeeping."""
from types import SimpleNamespace

from combat.ext import foundation_damage_support as support


def test_uncommitted_mercy_reduction_cannot_suppress_later_support(monkeypatch):
    owner = SimpleNamespace(entity_id='owner', turn_flags={support.MERCY_PENDING: {
        'source': 'ward', 'target': 'ally', 'kind': 'damage_reduction'}})
    ally = SimpleNamespace(entity_id='ally')
    engine = SimpleNamespace(state=SimpleNamespace(actors={'owner': owner, 'ally': ally}))
    proposal = SimpleNamespace(actor_id='owner', beneficiary_id='ally',
                               source_id='ward', kind='damage_reduction')
    generated = []
    monkeypatch.setattr(support, '_generate_dew', lambda *args: generated.append(args[-1]))
    support.support_resolved(engine, proposal, None, 3)
    assert support.MERCY_PENDING not in owner.turn_flags
    support.support_receipt(engine, 'TEMP_HP_GRANTED', {
        'actor_id': 'owner', 'target_ids': ('ally',),
        'source_definition_id': 'later', 'payload': {'before': 0, 'after': 2}})
    assert generated == ['later']


def test_unrelated_support_receipt_does_not_claim_pending_mercy(monkeypatch):
    owner = SimpleNamespace(entity_id='owner', turn_flags={support.MERCY_PENDING: {
        'source': 'ward', 'target': 'ally', 'kind': 'damage_reduction'}})
    ally = SimpleNamespace(entity_id='ally')
    engine = SimpleNamespace(state=SimpleNamespace(actors={'owner': owner, 'ally': ally}))
    generated = []
    monkeypatch.setattr(support, '_generate_dew', lambda *args: generated.append(args[-1]))
    support.support_receipt(engine, 'TEMP_HP_GRANTED', {
        'actor_id': 'owner', 'target_ids': ('ally',),
        'source_definition_id': 'later', 'payload': {'before': 0, 'after': 2}})
    assert generated == ['later']
    assert support.MERCY_PENDING in owner.turn_flags
