"""Owner's Funeral Ash normalization through table commits and cold replay."""
import hashlib
import json
import re

import pytest

from combat.ext.foundation_context import public_scene_choices
from tests.h1_support import ROOT, mechanics
from tests.test_a2_foundations3 import add_action, pool
from tests.test_mgr_t14_ash_parent import OLD_FACT_PROMPT, declare_residue, native_fixture
from tests.test_mgr_t14_ash_mercy_parent import (
    scene, mercy, SCENE, TARGET, FEATURE,
)
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn, reload

CAUTERY = 'foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery'


def fire_actions(bundles):
    for index in (0, 1):
        add_action(bundles[index], 'Listed fire damage', [
            {'type': 'damage', 'flat': 12, 'damage_types': ['fire'], 'applies_to': 'target'},
        ], target_kind='ANY_CREATURE', economy='NONE')


@pytest.mark.parametrize('source_actor', [OWNER, ALLY], ids=['self', 'ally'])
def test_listed_damage_from_self_or_ally_generates_without_circumstances(tmp_path, source_actor):
    # Owner ask (i): listed damage counts whatever its source, without a situation vote.
    combat, table, mid = native_fixture(tmp_path, bundle_transform=fire_actions)
    turn(table, mid, source_actor)
    prompts = settle(table, mid, candidate(combat, mid, 'Listed fire damage', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert 0 < engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)
    assert not any('circumstances' in e.payload for e in engine.events)


def test_wounded_helpless_enemy_generates_and_strike_data_has_no_situation_gate(tmp_path):
    # Owner ask (ii): helplessness does not bar generation or add a condition to Strike's printed trigger, target or cost.
    def prepare(bundles):
        bundles[0] = declare_residue(bundles[0], 1)
        add_action(bundles[1], 'Wound and paralyze', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'condition', 'condition': 'paralyzed', 'applies_to': 'target',
             'duration': {'kind': 'until_removed'}},
        ], target_kind='ANY_CREATURE', economy='NONE')
    combat, table, mid = native_fixture(tmp_path, incoming=False,
        owner_talents=['FIRE_TAL_FLAME_LASH'], foe_hp=500, bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Wound and paralyze', target=FOE).candidate_id)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Flame Lash', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id.endswith('.paralyzed') for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)
    hit = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.actor_id == OWNER and e.target_ids == (FOE,))
    assert 0 < hit.payload['hp_before'] < engine.state.actors[FOE].maximum_hp
    assert any(c.endswith('.paralyzed') for c in hit.payload['target_conditions_before'])
    # This committed hit exercises the shared Meridian alignment code. Strike's
    # native paid producer is a separate pre-existing gap, not a normalization requirement.
    strike_id = 'foundation.red_lotus_ash_returning_v0_2B.ash_returning_strike'
    strike = mechanics()[strike_id]
    # Load prose from the published corpus, not a private sentence copied here.
    # Pin the exact trigger and target bytes as before; the public export rewrites
    # text commitments together with their corpus, preserving both checks.
    printed = json.loads((ROOT / 'authority/typed_mechanics/tooltip_digests.json').read_text())['records'][strike_id]
    facts = dict(printed['sections'][0]['facts'])
    trigger = facts['Trigger']
    assert hashlib.sha256(trigger.encode()).hexdigest() == (
        'be4d3c5d282af4f6abadf227bb179f2449a2857a15f92943c62a7167964874c1')
    assert strike['activation']['trigger'] == trigger
    target = facts['Target']
    assert hashlib.sha256(target.encode()).hexdigest() == (
        '63f12e4622328fbe7efa2cee26c1031f1f7f0d0ce4143244d4783495c56b09e6')
    assert strike['target'] == {'text': target}
    assert strike['cost'] == [[{'resource': 'text', 'text': '1 Funeral Ash'}]]
    assert strike['modifier']['precondition'] == ''
    assert not re.search(
        r'\b(?:helpless|circumstances|situations?|real|meaningful|staged|friendly|harmless|'
        r'voluntary|training|genuine|farming)\b', json.dumps(strike), re.I)


def test_observed_enemy_defeat_needs_no_meaningful_question(tmp_path):
    # Owner ask (iii): an observed defeat qualifies even with no human witness or setup declaration.
    combat, table, mid = native_fixture(tmp_path, foe_hp=1)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)


def test_mercy_subject_choice_is_the_trigger_without_genuine_question(tmp_path):
    # Owner ask (iv): choosing the helpless creature is sufficient; no genuine/farming approval.
    combat, table, mid = scene(tmp_path)
    prompts = mercy(combat, table, mid, recipient=ALLY, subject=FOE)
    engine = reload(tmp_path, mid)
    assert {SCENE, TARGET} <= {p['context']['reaction_source_id'] for p in prompts}
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.ash_mercy.context' for p in prompts)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE]
    assert len(grants) == 1 and grants[0].target_ids == (ALLY,)
    assert grants[0].payload['offered'] == engine.state.actors[OWNER].proficiency_bonus


def test_setup_keeps_residue_but_has_no_circumstances_or_ending(tmp_path):
    # Owner ask (v): setup retains the mechanical residue fact, not situation judgments.
    combat, table, mid = native_fixture(tmp_path)
    bundle = next(b for b in combat._load_session(mid).engine.typed_bundle_documents
                  if b['actor_id'] == OWNER)
    ids = {row['id'] for row in public_scene_choices(bundle)}
    assert ids == {'ash_public_residue'}


def test_red_lotus_cautery_reduces_self_inflicted_fire(tmp_path):
    # Owner ask (vi): Cautery can reduce self-inflicted listed damage.
    def prepare(bundles):
        fire_actions(bundles)
        bundles[0]['actor_template']['maximum_hp'] = 21
    combat, table, mid = native_fixture(tmp_path, incoming=False, initial=1,
        owner_talents=['FIRE_TAL_FLAME_LASH', CAUTERY], bundle_transform=prepare)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Listed fire damage', target=OWNER).candidate_id,
           choices={'reaction:typed.' + CAUTERY: None})
    before = reload(tmp_path, mid)
    assert 0 < before.state.actors[OWNER].current_hp * 2 < before.state.actors[OWNER].maximum_hp
    reaction = next(r for r in before.typed_reaction_rows[OWNER] if r.get('feature_id') == CAUTERY)
    expected = reaction['numbers']['pb'] + reaction['numbers']['key_mod'] + before.state.actors[OWNER].proficiency_bonus
    settle(table, mid, candidate(combat, mid, 'Listed fire damage', target=OWNER).candidate_id,
           choices={'reaction:typed.' + CAUTERY: 'first'})
    engine = reload(tmp_path, mid)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == CAUTERY]
    assert len(resolved) == 1 and resolved[0].payload['reduction'] == expected
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.actor_id == OWNER
    assert resolved[0].sequence < damage.sequence
