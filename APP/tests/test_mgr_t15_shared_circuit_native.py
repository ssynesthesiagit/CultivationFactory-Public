"""Shared Circuit's two paid producers, using stage access and earlier support.

The imported Foundation stage is explicit starting character data, not inferred
from CL. No rider, Dew, reward condition or successful receipt is installed.
"""
import json
import zipfile
from hashlib import sha256

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, sealed_native_attack
from tests.test_shared_circuit_settlement import add_action, fake_menu_embeddings

PREFIX = 'foundation.origin_spirit_body_v0_2B.'
SHARED = PREFIX + 'refined_shared_circuit_memory'
GUARD = PREFIX + 'returning_source_guard'
FEED = PREFIX + 'feed_the_living_circuit'
CHOICE = 'choice:needle.shared_circuit_memory'
POOL = 'resource:foundation.spirit_source_dew'
MEMORY = 'condition:typed.foundations3_shared_memory.'
FIXTURE_INPUTS = (
    'combat/rules/feature_blocks.d/foundations3.json',
    'authority/typed_mechanics/rules_text.json',
    'combat/rules/targeting.json',
    'non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
    'non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
)


def document(stage='Refined'):
    # The owner must own Returning Source Guard; without it no Guard row is compiled and every Guard-path test is inert.
    doc = sheet([GUARD], name='Wren')
    doc['foundation'] = {'foundation_id': 'origin_spirit_body_v0_2B', 'stage': stage,
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 0}}
    return doc


def test_exact_source_and_portable_stage_acquisition(tmp_path):
    # Source provenance is typed data, not the printed prose: the public mirror scrambles prose, so a hash of
    # rules_text.json differs there. The authority's recorded source hash must equal the reviewed final's pin.
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][SHARED]
    reviewed = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/foundations3.json').read_text())['mechanics'][SHARED]
    assert authority['source']['text_sha256'] == reviewed['text_sha256'] == 'c7cfa7e04163653d764e1ae2613239ec5a5f75c715d4ab41367bada0b6ccd6ee'
    # The prose itself is still the printed source record: the pin above is the sole public-safe provenance (prose hash dropped deliberately, #5388).
    assert SHARED in json.loads((ROOT / FIXTURE_INPUTS[1]).read_text())
    for relative in FIXTURE_INPUTS:
        assert (ROOT / relative).is_file()
    for stage, expected in [('Awakened', False), ('Refined', True)]:
        folder = tmp_path / 'portable_characters' / stage.lower()
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(stage)))
        combat = CombatService(ROOT, tmp_path)
        view = combat.create_factory_match(project_ids=[stage.lower()], match_seed='SHARED-IMPORT',
            control_modes={'actor:factory.' + stage.lower(): 'MANUAL'})
        mid = view['match_id']
        actor_id = 'actor:factory.' + stage.lower()
        engine = reload(tmp_path, mid)
        assert any(r.get('feature_id') == SHARED for r in engine.typed_passive_rows[actor_id]) is expected
        assert engine.state.actors[actor_id].resources[POOL] == 0


def test_owner_is_granted_returning_source_guard_row(tmp_path):
    from combat import typed_reactions as tr
    _, _, mid = setup_native(tmp_path, feed=False)
    engine = reload(tmp_path, mid)
    rows = [r.get('feature_id') for r in tr._rows(engine, OWNER, 'generic')]
    assert GUARD in rows, f'owner rows: {rows}'


def test_guard_self_protection_pays_dew_and_reduces_own_damage(tmp_path):
    combat, table, mid = setup_native(tmp_path, feed=False)
    settle(table, mid, candidate(combat, mid, 'Native pressure', target=OWNER).candidate_id,
           choices={'reaction:typed.' + GUARD: 'first'})
    engine = reload(tmp_path, mid)
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == GUARD]
    assert len(spent) == 1, f'guard spends: {len(spent)}'
    resolved_guard = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == GUARD]
    assert resolved_guard and resolved_guard[-1].payload['protects'] == OWNER
    assert resolved_guard[-1].payload['reduction'] > 0, f"reduction: {resolved_guard[-1].payload['reduction']}"
    assert engine.state.actors[OWNER].resources[POOL] == 0


def setup_native(tmp_path, *, stage='Refined', distance=10, feed=False, blocked=False,
                 support=True, damage_modifier=18, near_support=False):
    owner = compile_character(document(stage), actor_id=OWNER, reaction_plan={'ask': True})
    def actions(bundles):
        # Deterministic starting support spell, resolved by the production
        # typed executor. Its outcome/recipient are NOT pre-seeded receipts.
        add_action(bundles[0], 'Prior outward support',
            [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}], target_kind='ALLY_OR_SELF')
        bundles[0]['action_catalog'][-1]['range_ft'] = 70
        bundles[0]['action_catalog'][-1]['parameters']['typed']['range_ft'] = 70
        add_action(bundles[1], 'Maintain technique', [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}],
                   target_kind='SELF')
        bundles[1]['action_catalog'][-1]['parameters']['typed']['duration'] = {
            'kind': 'one_minute', 'concentration': True}
        sealed_native_attack(bundles[2], 'Native pressure', count=1, sides=2,
                             modifier=damage_modifier, attack_bonus=100)
        add_action(bundles[2], 'Same-source save', [{'type': 'save', 'ability': 'WIS', 'dc': 30,
            'save_categories': ['damage:psychic'], 'on_fail': [], 'on_success': []}], economy='NONE')
        add_action(bundles[2], 'Bind ally', [{'type': 'condition', 'condition': 'restrained',
            'applies_to': 'target', 'duration': {'kind': 'until_end_of_next_turn'}}], economy='NONE')
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    # A clear fixture arena isolates distance from line of effect. The blocked
    # control below adds a real full-height wall on that same support ray.
    positions = {OWNER: {'x': 1, 'y': 6}, ALLY: {'x': 1 + distance // 5, 'y': 6},
                 FOE: {'x': 1 + distance // 5, 'y': 5}}
    def wall(arena):
        arena['terrain_regions'] = []
        if blocked:
            arena['terrain_regions'].append({'region_id': 'shared-test-wall',
                'terrain_type': 'BLOCKED', 'movement_cost': 0,
                'cells': [{'x': 7, 'y': y} for y in range(4, 9)]})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, bundle_transform=actions,
        positions=positions, named=True, ally_score=6, seed='MGR-FEED-1', battlefield_transform=wall,
        extra_allies=1 if blocked or near_support else 0)
    support_target = 'actor:factory.worker2-ally3' if blocked or near_support else ALLY
    if support:
        settle(table, mid, candidate(combat, mid, 'Prior outward support', target=support_target).candidate_id, choices={})
    if feed:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Maintain technique').candidate_id, choices={})
    turn(table, mid, FOE)
    return combat, table, mid


def memories(engine):
    return [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id.startswith(MEMORY)]


class ColdTable:
    """Reopen the saved pending decision for EVERY answer, not only final state."""
    def __init__(self, root):
        self.root = root

    def state(self, *args, **kwargs):
        return TabletopService(CombatService(ROOT, self.root), self.root).state(*args, **kwargs)

    def act(self, *args, **kwargs):
        return TabletopService(CombatService(ROOT, self.root), self.root).act(*args, **kwargs)


@pytest.mark.parametrize('feed', [False, True])
@pytest.mark.parametrize('benefit', ['advantage', 'move', None])
def test_paid_native_protection_one_recipient_choice_and_cold_replay(tmp_path, feed, benefit):
    combat, table, mid = setup_native(tmp_path, feed=feed)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[POOL] == 1
    assert any(e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER for e in before.events)
    prompts = settle(ColdTable(tmp_path), mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: None if feed else 'first',
                 'reaction:typed.' + FEED: 'first',
                 'choice:needle.foundations3_feed_accept': 'accept', CHOICE: benefit,
                 'choice:needle.shared_circuit_destination': 'first'})
    engine = reload(tmp_path, mid)
    paid = FEED if feed else GUARD
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == paid]) == 1
    assert not engine.state.actors[OWNER].reaction_available
    choices = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert len(choices) == 1 and choices[0]['context']['reactor_id'] == ALLY
    receipts = [e for e in engine.events if e.source_definition_id == SHARED
                and e.payload.get('receipt_kind') == 'shared_circuit_choice']
    assert len(receipts) == 1 and receipts[0].payload['benefit'] == (benefit or 'decline')
    # The benefit names the actual pressure: a damaging attack defers its one
    # Concentration save to the attack's final damage, after the damage packet
    # has closed, so the source must come from the save's own roll context.
    assert receipts[0].payload['source_actor_id'] == FOE
    if feed:
        rewrite = next(e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == FEED)
        save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
        assert rewrite.payload['original']['total'] < save.payload['dc'] <= save.payload['total']
        assert save.payload['success'] and engine.state.actors[ALLY].concentration is not None
    if benefit == 'advantage':
        assert memories(engine), 'Feed must not consume its new memory on the granting save'
        settle(table, mid, candidate(combat, mid, 'Same-source save', target=ALLY).candidate_id, choices={})
        engine = reload(tmp_path, mid)
        assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1].payload['mode'] == 'ADVANTAGE'
        assert not memories(engine)
    elif benefit == 'move':
        assert engine.state.actors[ALLY].position != before.state.actors[ALLY].position
        assert engine.state.actors[ALLY].movement_remaining_ft == before.state.actors[ALLY].movement_remaining_ft
    else:
        assert not memories(engine)


@pytest.mark.parametrize('feed', [False, True])
@pytest.mark.parametrize('distance', [30, 60, 65])
def test_native_open_channels_support_generation_and_protection_range(tmp_path, feed, distance):
    combat, table, mid = setup_native(tmp_path, distance=distance, feed=feed)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[POOL] == (1 if distance <= 60 else 0)
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: None if feed else 'first',
                 'reaction:typed.' + FEED: 'first',
                 'choice:needle.foundations3_feed_accept': 'accept', CHOICE: 'advantage'})
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts) is (distance <= 60)
    reload(tmp_path, mid)


@pytest.mark.parametrize('feed', [False, True])
def test_open_channels_extension_requires_clear_line_of_effect(tmp_path, feed):
    combat, table, mid = setup_native(tmp_path, distance=60, feed=feed, blocked=True)
    before = reload(tmp_path, mid)
    from combat.targeting import line_of_effect
    assert not line_of_effect(before, before.state.actors[OWNER], target=before.state.actors[ALLY])
    assert before.state.actors[OWNER].resources[POOL] == 1
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: None if feed else 'first',
                 'reaction:typed.' + FEED: 'first',
                 'choice:needle.foundations3_feed_accept': 'accept', CHOICE: 'advantage'})
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert not memories(reload(tmp_path, mid))


@pytest.mark.parametrize('feed', [False, True])
@pytest.mark.parametrize('automatic_ally', [False, True])
def test_feed_and_guard_recipient_control_on_automatic_enemy_turn(tmp_path, feed, automatic_ally):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = setup_native(tmp_path, feed=feed)
    # Owner's printed reaction plan reserves Dew for Feed in automatic mode.
    # The human owner remains Ask me; the protected ally's control is separate.
    if automatic_ally:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id
    policy = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: policy.choose_reaction(context).decision)
    prompts = settle(table, mid, cid, auto=True, choices={
        'reaction:typed.' + GUARD: None if feed else 'first',
        'reaction:typed.' + FEED: 'first',
        'choice:needle.foundations3_feed_accept': 'accept', CHOICE: 'advantage'})
    assert bool([p for p in prompts if p['context']['reaction_source_id'] == CHOICE]) is (not automatic_ally)
    assert memories(reload(tmp_path, mid))


@pytest.mark.parametrize('case', ['empty', 'decline', 'unowned', 'failure'])
def test_feed_requires_paid_success_and_owned_rider(tmp_path, case):
    combat, table, mid = setup_native(tmp_path, feed=True, support=case != 'empty',
        stage='Awakened' if case == 'unowned' else 'Refined',
        damage_modifier=54 if case == 'failure' else 18)
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: None,
                 'reaction:typed.' + FEED: None if case == 'decline' else 'first',
                 'choice:needle.foundations3_feed_accept': 'accept', CHOICE: 'advantage'})
    engine = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert not memories(engine)
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED]
    assert bool(paid) is (case in ('unowned', 'failure'))
    if case == 'failure':
        assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1].payload['success'] is False


def test_immobilized_ally_cannot_take_granted_step(tmp_path):
    combat, table, mid = setup_native(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Bind ally', target=ALLY).candidate_id, choices={})
    before = reload(tmp_path, mid)
    assert before._effective_speed(before.state.actors[ALLY]) == 0
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: 'first', CHOICE: 'move'})
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.shared_circuit_destination' for p in prompts)
    assert reload(tmp_path, mid).state.actors[ALLY].position == before.state.actors[ALLY].position


@pytest.mark.parametrize('feed', [False, True])
def test_beyond_sixty_feet_cannot_protect_even_with_prior_dew(tmp_path, feed):
    combat, table, mid = setup_native(tmp_path, distance=65, feed=feed, near_support=True)
    engine = reload(tmp_path, mid)
    from combat.targeting import line_of_effect
    assert line_of_effect(engine, engine.state.actors[OWNER], target=engine.state.actors[ALLY])
    assert engine.state.actors[OWNER].resources[POOL] == 1
    prompts = settle(table, mid, candidate(combat, mid, 'Native pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: None if feed else 'first',
                 'reaction:typed.' + FEED: 'first',
                 'choice:needle.foundations3_feed_accept': 'accept', CHOICE: 'advantage'})
    assert not any(p['context']['reaction_source_id'] in
                   ('reaction:typed.' + GUARD, 'reaction:typed.' + FEED, CHOICE) for p in prompts)
    assert not memories(reload(tmp_path, mid))
