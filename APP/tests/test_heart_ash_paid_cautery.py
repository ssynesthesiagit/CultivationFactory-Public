"""Heart-Ash rides one paid native Cautery reduction, never retaliation."""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import pool, add_action
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload,
)

CAUTERY = 'foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery'
REACTION = 'reaction:typed.' + CAUTERY


@pytest.mark.parametrize('owned,automatic,accept,hostile,prior_target', [
    pytest.param(True, False, True, True, OWNER, id='paid'),
    pytest.param(False, False, True, True, OWNER, id='unowned'),
    pytest.param(True, True, True, True, OWNER, id='automatic'),
    pytest.param(True, False, False, True, OWNER, id='decline'),
    pytest.param(True, False, True, False, OWNER, id='friendly-source'),
    pytest.param(True, False, True, True, ALLY, id='other-target'),
])
def test_heart_ash_paid_cautery_prior_receipt(tmp_path, owned, automatic, accept, hostile, prior_target):
    def delivery(bundles):
        for name, economy in [('Prior fire hit', 'ACTION'), ('Later fire hit', 'BONUS_ACTION')]:
            add_action(bundles[2], name, [{'type': 'damage', 'flat': 12,
                       'damage_types': ['fire'], 'applies_to': 'target'}], economy=economy,
                       target_kind='ANY_CREATURE')

    prefix = 'foundation.red_lotus_ash_returning_v0_2B.'
    slugs = ['red_lotus_cautery', 'generate_funeral_ash']
    if owned:
        slugs.append('refined_red_lotus_heart_ash')
    doc = sheet([prefix + slug for slug in slugs],
                foundation={'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': 'Refined' if owned else 'Awakened',
                            'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                                         'maximum': 1, 'current': 0}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    modes = {OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}
    if not hostile:
        modes['actor:factory.worker2-foe1'] = 'MANUAL'
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle,
                               bundle_transform=delivery, seed='HEART-ASH-PAID', modes=modes,
                               team_overrides=None if hostile else {FOE: 'team:factory'},
                               extra_foes=0 if hostile else 1)
    turn(table, mid, FOE)
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    settle(table, mid, candidate(combat, mid, 'Prior fire hit', target=prior_target).candidate_id)
    engine = reload(tmp_path, mid)
    prior_ash = hostile and prior_target == OWNER
    assert engine.state.actors[OWNER].resources[pool('ash')] == int(prior_ash)
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
             and e.payload.get('resource_id') == pool('ash')]
    assert len(gains) == int(prior_ash)
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == CAUTERY
                   for e in engine.events)
    before = engine.state.actors[OWNER].current_hp
    foe_hp = engine.state.actors[FOE].current_hp
    sequence = engine.state.event_sequence
    state_hash = canonical_sha256(engine.state.model_dump(mode='json'))
    for _ in range(3):
        engine.legal_candidates()
    assert canonical_sha256(engine.state.model_dump(mode='json')) == state_hash
    assert engine.state.event_sequence == sequence
    choice = candidate(combat, mid, 'Later fire hit', target=OWNER)
    assert reload(tmp_path, mid).state.event_sequence == sequence
    prompts = settle(table, mid, choice.candidate_id, picks={REACTION: 'first'} if accept else {})
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts) == (prior_ash and not automatic)
    engine = reload(tmp_path, mid)
    reactions = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                 and e.source_definition_id == CAUTERY]
    paid = accept and prior_ash
    assert len(reactions) == int(paid)
    if paid:
        assert reactions[0].payload['reduction'] == (10 if owned else 6)
        assert engine.state.actors[OWNER].current_hp == before - reactions[0].payload['pending_after']
    else:
        assert engine.state.actors[OWNER].current_hp == before - 12
    assert engine.state.actors[FOE].current_hp == foe_hp
    expected_ash = (prior_ash and not paid) or (hostile and not prior_ash)
    assert engine.state.actors[OWNER].resources[pool('ash')] == int(expected_ash)
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.payload.get('resource_id') == pool('ash')]
    assert len(spends) == int(paid)
    if paid:
        assert spends[0].payload['amount'] == 1
        assert gains[0].sequence < spends[0].sequence < reactions[0].sequence
        assert gains[0].transaction_id != spends[0].transaction_id
