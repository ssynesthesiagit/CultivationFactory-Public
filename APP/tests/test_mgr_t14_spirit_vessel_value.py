"""Origin-Spirit's first native value contract: paid Life Temporary HP at a table."""
import pytest
from combat.canonical import canonical_sha256
from combat.temp_hp_offers import offered_bonus
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.cw2_service_support import add_action

VESSEL = 'foundation.origin_spirit_body_v0_2B.origin_spirit_vessel'
LIFE = 'tianxia.talent.life.greater_invigorate'
CHOICE = 'choice:needle.origin_spirit_support_value'
ROUND = 'foundation_round_origin_spirit_support_value'


def setup(tmp_path, *, owns=True):
    return fixture(tmp_path, [LIFE, *([VESSEL] if owns else [])], named=True,
                   seed='MGR-T14-VESSEL')


def cast(combat, table, mid, target=ALLY, *, accept=True):
    return settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Greater Invigorate',
                  target=target).candidate_id, picks={CHOICE: 'increase' if accept else None})


def test_native_paid_support_commits_bonus_and_primitive_receipt(tmp_path):
    combat, table, mid = setup(tmp_path)
    before = reload(tmp_path, mid)
    source = candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).source_definition_id
    action = before.action_catalog[source]
    assert action.parameters['typed']['source'] == 'LIFE_BASE_BORROWED_BREATH'
    assert action.parameters['typed']['sphere'] == 'tianxia.sphere.life'
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    prompts = cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 24
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 1
    assert type(engine.state.actors[OWNER].turn_flags[ROUND]) is int
    receipts = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.payload.get('receipt_kind') == 'origin_spirit_support_value']
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.actor_id == OWNER and receipt.target_ids == (ALLY,)
    assert receipt.payload['method'] == 'LIFE_BASE_BORROWED_BREATH'
    assert receipt.payload['support_source'] == source and receipt.payload['bonus'] == 4
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)


@pytest.mark.parametrize('owns,target,accept,expected', [
    (False, ALLY, True, 20), (True, OWNER, True, 20), (True, ALLY, False, 20)])
def test_native_controls_do_not_spend_round_allowance(tmp_path, owns, target, accept, expected):
    combat, table, mid = setup(tmp_path, owns=owns)
    prompts = cast(combat, table, mid, target, accept=accept)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[target].temporary_hp == expected
    assert ROUND not in engine.state.actors[OWNER].turn_flags
    assert not [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value']
    assert bool([p for p in prompts if p['context']['reaction_source_id'] == CHOICE]) == (owns and target != OWNER)


def test_repeated_previews_are_pure_and_native_round_renews(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    source = candidate(combat, mid, 'Borrowed Breath + Greater Invigorate', target=ALLY).source_definition_id
    def snapshot():
        return canonical_sha256({'state': engine.state.model_dump(mode='json'),
                                 'events': [e.model_dump(mode='json') for e in engine.events]})
    before = snapshot()
    for _ in range(5):
        assert offered_bonus(engine, engine.state.actors[ALLY], 20, source, OWNER, consume=False) == 4
    assert snapshot() == before
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    used_round = engine.state.actors[OWNER].turn_flags[ROUND]
    before = snapshot()
    assert offered_bonus(engine, engine.state.actors[ALLY], 20, source, OWNER, consume=False) == 0
    assert snapshot() == before
    turn(table, mid, FOE)
    assert reload(tmp_path, mid).state.actors[OWNER].turn_flags[ROUND] == used_round
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.round_number > used_round
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    receipts = [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value']
    assert len(receipts) == 2
    assert receipts[0].payload['round'] < receipts[1].payload['round']


@pytest.mark.parametrize('reserve', [False, True])
def test_two_native_patients_select_one_value_and_keep_other_options(tmp_path, reserve):
    other = 'actor:factory.worker2-ally3'
    def prepare(bundles):
        add_action(bundles[0], 'Seal patient', [{'type': 'mark', 'mark': 'Pulse Seal',
                   'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
        add_action(bundles[0], 'Injure patient', [{'type': 'damage', 'flat': 30,
                   'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [VESSEL, 'tianxia.talent.life.pulse_array_treatment'],
                               extra_allies=1, bundle_transform=prepare, named=True)
    for patient in (ALLY, other):
        for name in ('Seal patient', 'Injure patient'):
            settle(table, mid, candidate(combat, mid, name, target=patient).candidate_id)
    engine = reload(tmp_path, mid)
    cast_candidate = next(c for c in engine.legal_candidates() if c.target_ids == (ALLY,)
                          and all(word in engine.action_catalog[c.source_definition_id].display_name
                                  for word in ('Borrowed Breath', 'Pulse Array')))
    prompts = settle(table, mid, cast_candidate.candidate_id, picks={
        'choice:needle.life_patients': other, CHOICE: (None, 'increase') if reserve else 'increase'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == (4 if reserve else 8)
    assert engine.state.actors[other].temporary_hp == (8 if reserve else 4)
    assert len([p for p in prompts if p['context']['reaction_source_id'] == CHOICE]) == (2 if reserve else 1)
    receipts = [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value']
    assert len(receipts) == 1 and receipts[0].target_ids == (other if reserve else ALLY,)
    # A later recipient in the same activation cannot consume a second bonus.
    assert offered_bonus(engine, engine.state.actors[ALLY], 20, cast_candidate.source_definition_id,
                         OWNER, consume=False) == 0


def test_unlisted_source_and_unrelated_damage_never_qualify(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Unlisted support', [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}],
                   typed={'sphere': 'tianxia.sphere.life'})
        add_action(bundles[0], 'Unrelated damage', [{'type': 'damage', 'flat': 3,
                   'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [VESSEL, LIFE], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Unlisted support', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Unrelated damage', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 7
    assert ROUND not in engine.state.actors[OWNER].turn_flags
    assert not [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value']


@pytest.mark.parametrize('owner_ai', [False, True])
def test_native_delayed_grant_on_ai_enemy_turn_routes_owner_choice(tmp_path, owner_ai):
    from tests.worker2_support import sealed_native_attack
    from tests.test_a2_daemonic import select_native_primary
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Injure nearby patient', count=1, sides=4,
                             modifier=30, attack_bonus=100, range_ft=5)
    combat, table, mid = fixture(tmp_path, [VESSEL, 'tianxia.talent.life.latent_healing'],
                               bundle_transform=prepare, named=True, foe_position={'x': 5, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath + Latent Healing', target=ALLY).candidate_id)
    assert ROUND not in reload(tmp_path, mid).state.actors[OWNER].turn_flags
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    if owner_ai:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    # Select a legal native attack; retain the real AI choice/reaction controller.
    # Primary policy ranking is separate from this Foundation's transport contract.
    select_native_primary(combat, mid, 'Injure nearby patient', ALLY)
    prompts = settle(table, mid, '', auto=True, picks={
        'choice:needle.latent_healing': 'use', CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    # All actual support values now qualify: a manual owner reserves the
    # earlier Returning Source Guard value; an AI selects that legal first
    # value automatically and receives unboosted delayed Borrowed Breath.
    assert engine.state.actors[ALLY].temporary_hp == (4 if owner_ai else 8)
    value_prompts = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert bool(value_prompts) == (not owner_ai)
    if value_prompts:
        prompt = next(p for p in value_prompts if 'Borrowed Breath' in str(p))
        assert prompt['context']['reactor_id'] == OWNER
        assert all(name in str(prompt) for name in ('Origin-Spirit Vessel', 'Borrowed Breath', 'Tobin'))
    receipt = next(e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value')
    assert receipt.actor_id == OWNER and receipt.target_ids == (ALLY,)
    assert engine.state.actors[OWNER].turn_flags[ROUND] == engine.state.round_number
