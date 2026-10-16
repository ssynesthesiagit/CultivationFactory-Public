"""OPUS1 batch 4: Iron Mercy, Demon-Slaying Demon and Weapon and Technique Weave through the real table, with cold reloads."""
import copy

from combat.canonical import canonical_sha256
from combat.ext import daemonic_insights as di
from combat.ext import life_insights as li
from combat.ext import qi_insights as qi
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, prompt_turn, reload, settle

LIFE = 'tianxia.talent.life.empathic_transfer'
JIAN = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'name': 'jian', 'quantity': 1}]}}


def seal(bundle, name, effects, *, attack_bonus=100, economy='ACTION'):
    aid = 'action:test.opus1b4.' + bundle['actor_id'].rsplit('.', 1)[-1] + '.' + name.replace(' ', '_').lower()
    typed = {'source': 'test:opus1', 'effects': copy.deepcopy(effects), 'riders': [], 'duration': {'kind': 'instant'},
             'numbers': {'cl': 15, 'pb': 5, 'save_dc': 10, 'attack_bonus': attack_bonus}}
    bundle['action_catalog'].append({'source_definition_id': aid, 'display_name': name, 'owner_id': bundle['actor_id'],
                                     'economy': economy, 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
                                     'range_ft': 60, 'costs': [], 'parameters': {'typed': typed, 'expected_damage': 0}})
    bundle['actor_template']['action_ids'].append(aid)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def _conditions(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


# -------------------------------------------------------------------------------------------------------- Iron Mercy
def test_iron_mercy_buffer_follows_the_transferred_affliction(tmp_path):
    venom = [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target', 'duration': 'until_removed'}]
    combat, table, mid = fixture(tmp_path, [LIFE], ally_talents=[LIFE], owner_insights=[li.IRON_MERCY],
                                 ally_position={'x': 3, 'y': 7},
                                 bundle_transform=lambda bundles: seal(bundles[2], 'Venom', venom))
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Venom', target=ALLY).candidate_id)
    prompt_turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Purify the Pulse: Remove Poisoned + Empathic Transfer', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    poison = _conditions(owner, 'condition:typed.poisoned')
    buffer = _conditions(owner, li.BUFFER)
    assert poison and not _conditions(engine.state.actors[ALLY], 'condition:typed.poisoned')
    assert len(buffer) == 1 and buffer[0].data['affliction_instance_id'] == poison[0].instance_id
    assert buffer[0].data['amount'] == 2 + owner.proficiency_bonus  # CON 14 (+2) + Proficiency Bonus
    assert owner.temporary_hp == 0  # not ordinary Temporary Hit Points
    # The ally purifies the owner: the recorded affliction ends, and so does the buffer.
    prompt_turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Purify the Pulse: Remove Poisoned', target=OWNER).candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert not _conditions(owner, 'condition:typed.poisoned') and not _conditions(owner, li.BUFFER)


def test_iron_mercy_needs_the_insight(tmp_path):
    venom = [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target', 'duration': 'until_removed'}]
    combat, table, mid = fixture(tmp_path, [LIFE], ally_position={'x': 3, 'y': 7},
                                 bundle_transform=lambda bundles: seal(bundles[2], 'Venom', venom))
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Venom', target=ALLY).candidate_id)
    prompt_turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Purify the Pulse: Remove Poisoned + Empathic Transfer', target=ALLY).candidate_id)
    assert not _conditions(reload(tmp_path, mid).state.actors[OWNER], li.BUFFER)


# ------------------------------------------------------------------------------------------------ Demon-Slaying Demon
def _fiend(hp):
    foe = sheet([], cl=15)
    foe['identity']['creature_type'] = 'Fiend'
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = hp
    return foe


def test_demon_slaying_demon_adds_pb_and_feeds_on_a_felled_fiend(tmp_path):
    combat, table, mid = fixture(tmp_path, ['TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE'], owner_insights=[di.DEMON_SLAYING],
                                 foe_sheet=_fiend(4), foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9})
    essence = reload(tmp_path, mid).state.actors[OWNER].resources[di.ESSENCE]
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id,
                     picks={'choice:needle.daemonic_insights': 'essence'})
    engine = reload(tmp_path, mid)
    notes = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == f'passive:{di.DEMON_SLAYING}']
    assert any('adds' in e.payload['log'] for e in notes)
    assert engine.state.actors[FOE].current_hp == 0
    assert any('Demon-Slaying Demon' in str(p) for p in prompts)
    assert engine.state.actors[OWNER].resources[di.ESSENCE] >= essence + 2  # Devour Essence may add its own
    assert any('gains 2 Devoured Essence' in e.payload['log'] for e in notes)
    assert engine.state.actors[OWNER].turn_flags.get(di.TURN_FLAG)


def test_demon_slaying_demon_ignores_an_ordinary_humanoid(tmp_path):
    foe = _fiend(200)
    foe['identity']['creature_type'] = 'Humanoid'
    combat, table, mid = fixture(tmp_path, [], owner_insights=[di.DEMON_SLAYING], foe_sheet=foe,
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9})
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any(e.source_definition_id == f'passive:{di.DEMON_SLAYING}' for e in engine.events)


# ----------------------------------------------------------------------------------------- Weapon and Technique Weave
CULTIVATION_STRIKE = [{'type': 'attack', 'attack_kind': 'cultivation_melee', 'count': 1, 'on_miss': [],
                       'on_hit': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 1, 'sides': 4},
                                   'damage_types': ['force'], 'flat': 0, 'formula': 'none'}]}]


def test_weave_after_a_weapon_hit_adds_one_to_the_next_cultivation_attack(tmp_path):
    foe = sheet([], cl=15)
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 300
    combat, table, mid = fixture(tmp_path, [], owner_insights=[qi.WEAVE], owner_kit=JIAN, foe_sheet=foe,
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9},
                                 bundle_transform=lambda bundles: seal(bundles[0], 'Palm of Qi', CULTIVATION_STRIKE,
                                                                       attack_bonus=10, economy='BONUS_ACTION'))
    prompts = settle(table, mid, candidate(combat, mid, 'Jian (Straight Sword) attack', target=FOE).candidate_id,
                     picks={'choice:needle.qi_insights': 'cultivation'})
    assert any('Weapon and Technique Weave' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    held = _conditions(engine.state.actors[OWNER], qi.HELD)
    assert len(held) == 1 and held[0].data['weave'] == 'cultivation'
    assert held[0].expires_on.startswith('END_OF_SOURCE_TURN_AT:')
    settle(table, mid, candidate(combat, mid, 'Palm of Qi', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    roll = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and 'palm_of_qi' in str(e.payload.get('reason'))][-1]
    assert roll.payload['modifier'] == 11
    assert not _conditions(engine.state.actors[OWNER], qi.HELD)
    assert any(e.event_type == 'CONDITION_REMOVED' and (e.payload or {}).get('reason') == 'CONSUMED'
               and e.source_definition_id == qi.WEAVE for e in engine.events)
