"""Consciousness boundaries at committed support receipt delivery.

The scenario action loses consciousness before its already accepted support
packet settles. Conditions, HP/temp HP and resource receipts use native effects;
no support classification or consciousness metadata is injected.
"""
import pytest

from tests.test_a2_foundations3 import add_action, owner_bundle, pool
from tests.worker2_support import OWNER, ALLY, candidate, fixture, reload, settle


@pytest.mark.parametrize('kind', ['healing', 'temp_hp'])
@pytest.mark.parametrize('conscious', [False, True])
def test_support_requires_conscious_provider_at_settlement(tmp_path, kind, conscious):
    def delivery(bundles):
        effects = [] if conscious else [
            {'type': 'condition', 'condition': 'unconscious', 'applies_to': 'self'}]
        # Healing needs an injured beneficiary. Use a real committed damage
        # effect rather than editing HP or manufacturing a healing receipt.
        effects += [
            {'type': 'damage', 'flat': 10, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': kind, 'flat': 4, 'applies_to': 'target'}]
        add_action(bundles[0], 'Settling support', effects, target_kind='ALLY_OR_SELF')

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle('spirit', initial=0),
                                bundle_transform=delivery, seed='DEW-CONSCIOUS-SETTLEMENT')
    settle(table, mid, candidate(combat, mid, 'Settling support', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    event_type = 'HEALING_APPLIED' if kind == 'healing' else 'TEMP_HP_GRANTED'
    receipt = next(e for e in engine.events if e.event_type == event_type and e.actor_id == OWNER)
    assert ALLY in receipt.target_ids
    assert receipt.payload['after'] > receipt.payload['before']
    assert engine.state.actors[OWNER].resources[pool('spirit')] == int(conscious)
