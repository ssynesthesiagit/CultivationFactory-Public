"""Guard's objective damage subset through native table commits and cold replay.

Preloaded Dew is an explicit scenario setup, not a new generation route. Fixed
pressure uses the production typed damage caller; one case uses the unchanged
printed Deliver the Dose action too. No scene/Minor/scope facts are fabricated.
"""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

FOUNDATION = 'mud_lotus_dantian_v0_2A'
GUARD = 'foundation.' + FOUNDATION + '.mud_lotus_guard'
REACTION = 'reaction:typed.' + GUARD
POOL = 'resource:foundation.lotus_dew'


def setup(tmp_path, *, key_score=14, owns=True, initial=1, modes=None, distant=False):
    doc = sheet([GUARD] if owns else [], score=key_score, name='Lotus healer', foundation={
        'foundation_id': FOUNDATION, 'stage': 'Awakened',
        'resource': {'name': 'Lotus Dew', 'resource_id': 'tianxia.resource.lotus_dew',
                     'maximum': 1, 'current': initial}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        for source in (bundles[1], bundles[2]):
            for kind in ('poison', 'acid', 'necrotic', 'fire', 'slashing'):
                add_action(source, kind.title() + ' pressure',
                    [{'type': 'damage', 'flat': 20, 'damage_types': [kind], 'applies_to': 'target'}],
                    target_kind='ANY_CREATURE', economy='NONE')

    return fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=delivery,
        foe_sheet=sheet(['POISON_BASE_DELIVER_THE_DOSE'], name='Poison attacker'),
        modes=modes, seed='MGR-T14-MUD-LOTUS-2', named=True,
        # The stock arena's centre pillar occupies (9,6) and (10,6).
        # Use the clear row above it so these are distance controls, not illegal spawns.
        positions={OWNER: {'x': 3, 'y': 5}, FOE: {'x': 6, 'y': 5},
                   ALLY: {'x': 9 if distant == 'boundary' else 10, 'y': 5}} if distant else None)


def pressure(tmp_path, combat, table, mid, kind, target, *, accept=True, source=FOE):
    turn(table, mid, source)
    prompts = settle(table, mid, candidate(combat, mid, kind.title() + ' pressure', target=target).candidate_id,
                     picks={REACTION: 'first'} if accept else {})
    engine = reload(tmp_path, mid)
    receipts = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD]
    return engine, prompts, receipts


@pytest.mark.parametrize('kind,key_score,expected', [
    ('poison', 14, 10), ('acid', 14, 6),
    ('poison', 8, 7), ('acid', 8, 3),
])
@pytest.mark.parametrize('target', [OWNER, ALLY])
def test_guard_printed_single_signed_sum_and_poison_bonus(tmp_path, kind, key_score, expected, target):
    combat, table, mid = setup(tmp_path, key_score=key_score)
    engine, prompts, receipts = pressure(tmp_path, combat, table, mid, kind, target)
    assert len(receipts) == 1
    assert receipts[0].payload['reduction'] == expected
    assert engine.state.actors[target].current_hp == 60 - (20 - expected)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not engine.state.actors[OWNER].reaction_available
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    assert len(paid) == 1 and paid[0].payload['amount'] == 1
    assert paid[0].sequence < receipts[0].sequence
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REACTION)
    text = str(prompt)
    assert 'Mud-Lotus Guard' in text and 'Lotus Dew' in text and 'Reaction' in text
    assert engine.state.actors[target].display_name in text


@pytest.mark.parametrize('kind,source', [
    ('necrotic', FOE), ('fire', FOE), ('slashing', FOE), ('poison', ALLY),
])
def test_unknown_rot_nonscoped_and_friendly_damage_are_not_admitted(tmp_path, kind, source):
    combat, table, mid = setup(tmp_path)
    engine, prompts, receipts = pressure(tmp_path, combat, table, mid, kind, OWNER, source=source)
    assert not receipts
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[OWNER].current_hp == 40


@pytest.mark.parametrize('control', ['decline', 'empty', 'wrong_owner', 'out_of_range'])
def test_guard_decline_payment_ownership_and_range_controls(tmp_path, control):
    combat, table, mid = setup(tmp_path, owns=control != 'wrong_owner',
        initial=0 if control == 'empty' else 1, distant=control == 'out_of_range')
    target = ALLY if control == 'out_of_range' else OWNER
    engine, prompts, receipts = pressure(tmp_path, combat, table, mid, 'poison', target,
                                         accept=control != 'decline')
    assert not receipts
    assert engine.state.actors[target].current_hp == 40
    assert engine.state.actors[OWNER].resources.get(POOL, 0) == (0 if control in {'empty', 'wrong_owner'} else 1)


def test_guard_reaction_cannot_be_used_twice_before_owners_next_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine, _, receipts = pressure(tmp_path, combat, table, mid, 'poison', ALLY)
    assert len(receipts) == 1
    # A second actual packet reloads the settled state and has no paid Reaction
    # or Dew remaining; it cannot repeat the protection.
    engine, prompts, receipts = pressure(tmp_path, combat, table, mid, 'acid', ALLY)
    assert len(receipts) == 1
    assert engine.state.actors[ALLY].current_hp == 30
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)


def test_guard_includes_ally_at_exact_thirty_foot_boundary(tmp_path):
    combat, table, mid = setup(tmp_path, distant='boundary')
    engine, _, receipts = pressure(tmp_path, combat, table, mid, 'poison', ALLY)
    assert len(receipts) == 1 and receipts[0].payload['reduction'] == 10
    assert engine.state.actors[ALLY].current_hp == 50


def test_ai_owner_uses_guard_automatically_on_a_manual_attackers_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine, prompts, receipts = pressure(tmp_path, combat, table, mid, 'poison', ALLY)
    assert len(receipts) == 1 and receipts[0].payload['reduction'] == 10
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert engine.state.actors[OWNER].resources[POOL] == 0


def test_guard_handles_real_printed_poison_attack_after_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Deliver the Dose', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    engine = reload(tmp_path, mid)
    attack = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE)
    assert attack.payload['provisional_hit'] is True
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == GUARD)
    assert receipt.payload['reduction'] == min(10, receipt.payload['pending_before'])
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and e.source_definition_id == GUARD and e.payload.get('resource_id') == POOL]
    assert len(paid) == 1 and paid[0].payload['amount'] == 1
    assert paid[0].sequence < receipt.sequence
