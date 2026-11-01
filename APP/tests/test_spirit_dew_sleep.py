"""Native Dream Sleep cannot pay a previously created outward support trigger.

All state changes go through accepted table actions and cold disk replay. The
ward is deliberately not Concentration: ending a sleeping provider's technique
must not mask the consciousness boundary of an independently lasting benefit.
"""
import copy
import json

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.test_a2_foundations3 import add_action, owner_bundle, pool
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

SLEEP_ID = 'TAL_DREAM_SLEEP'
SLEEP = 'condition:typed.dream_sleep'


def _sleep_effect():
    """Use the native sealed sleep rule, not a condition-name-only stand-in."""
    mechanic = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][SLEEP_ID]
    save = next(e for e in mechanic['effects'] if e['type'] == 'save')
    return copy.deepcopy(next(e for e in save['on_fail'] if e.get('condition') == 'dream_sleep'))


@pytest.mark.parametrize('sleeping', [True, False], ids=['dream-asleep', 'awake'])
def test_existing_protection_requires_conscious_provider_after_native_sleep(tmp_path, sleeping):
    def delivery(bundles):
        add_action(bundles[0], 'Lasting heart ward', [{
            'type': 'advantage', 'on': 'saving throws against Frightened',
            'applies_to': 'target', 'duration': {'kind': 'until_end_of_next_turn'}}],
            target_kind='ALLY_OR_SELF')
        bundles[2] = compile_character(sheet([SLEEP_ID], dc=100), actor_id=FOE,
                                       reaction_plan={'ask': True})
        add_action(bundles[2], 'Prepare drowsiness', [{
            'type': 'drowsy', 'applies_to': 'target',
            'expires_on': 'START_OF_TARGET_NEXT_TURN'}], economy='NONE')
        add_action(bundles[2], 'Hostile fear', [{
            'type': 'save', 'ability': 'WIS', 'save_categories': ['frightened'],
            'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}],
            'on_success': []}], economy='NONE', dc=1)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle('spirit', initial=0),
        bundle_transform=delivery, seed='DEW-NATIVE-SLEEP-PROTECTION', named=True)
    settle(table, mid, candidate(combat, mid, 'Lasting heart ward', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    ward = next(c for c in engine.state.actors[ALLY].conditions.values()
                if c.condition_id == 'condition:typed.save_against')
    assert ward.source_actor_id == OWNER
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Prepare drowsiness', target=OWNER).candidate_id)
    if sleeping:
        settle(table, mid, candidate(combat, mid, 'Sleep', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    provider = engine.state.actors[OWNER]
    assert provider.active and provider.current_hp > 0
    assert any(c.condition_id == SLEEP for c in provider.conditions.values()) == sleeping
    assert not any(c.condition_id == 'condition:typed.unconscious' for c in provider.conditions.values())
    assert any(c.instance_id == ward.instance_id for c in engine.state.actors[ALLY].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Hostile fear', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'ADVANTAGE'
    assert saved.payload['success'] is True
    assert not any(c.condition_id == 'condition:typed.frightened' for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[OWNER].resources[pool('spirit')] == int(not sleeping)


@pytest.mark.parametrize('kind', ['healing', 'temp_hp'])
@pytest.mark.parametrize('sleeping', [True, False], ids=['dream-asleep', 'awake'])
def test_accepted_support_checks_native_sleep_at_receipt_settlement(tmp_path, kind, sleeping):
    def delivery(bundles):
        sleep = {**_sleep_effect(), 'applies_to': 'self',
                 'duration': {'kind': 'until_end_of_next_turn'}}
        effects = [sleep] if sleeping else []
        effects += [
            {'type': 'damage', 'flat': 10, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': kind, 'flat': 4, 'applies_to': 'target'}]
        add_action(bundles[0], 'Settling support', effects, target_kind='ALLY_OR_SELF')

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle('spirit', initial=0),
        bundle_transform=delivery, seed='DEW-SLEEP-SUPPORT-SETTLEMENT')
    settle(table, mid, candidate(combat, mid, 'Settling support', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    provider = engine.state.actors[OWNER]
    assert provider.active and provider.current_hp > 0
    assert any(c.condition_id == SLEEP for c in provider.conditions.values()) == sleeping
    receipt_type = 'HEALING_APPLIED' if kind == 'healing' else 'TEMP_HP_GRANTED'
    receipt = next(e for e in engine.events if e.event_type == receipt_type and e.actor_id == OWNER)
    assert ALLY in receipt.target_ids
    assert receipt.payload['after'] > receipt.payload['before']
    assert provider.resources[pool('spirit')] == int(not sleeping)
