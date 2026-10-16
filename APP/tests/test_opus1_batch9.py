"""OPUS1 batch 9: Dawn Physician through the real table, with cold reloads."""
import copy

from combat.canonical import canonical_sha256
from combat.ext import radiance_insights as ri
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, prompt_turn, reload, settle

RADIANCE = ['tianxia.talent.radiance.gentle_dawn', 'tianxia.talent.radiance.purifying_radiance']
DREAD = [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target', 'duration': 'until_removed'}]
SWIFT = 'Purifying Radiance: End Charm or Fear (Dawn Physician: Bonus Action, once per fight)'


def seal(bundle, name, effects):
    aid = 'action:test.opus1b9.' + bundle['actor_id'].rsplit('.', 1)[-1] + '.' + name.replace(' ', '_').lower()
    typed = {'source': 'test:opus1', 'effects': copy.deepcopy(effects), 'riders': [], 'duration': {'kind': 'instant'},
             'numbers': {'cl': 15, 'pb': 5, 'save_dc': 10, 'attack_bonus': 10}}
    bundle['action_catalog'].append({'source_definition_id': aid, 'display_name': name, 'owner_id': bundle['actor_id'],
                                     'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
                                     'range_ft': 60, 'costs': [], 'parameters': {'typed': typed, 'expected_damage': 0}})
    bundle['actor_template']['action_ids'].append(aid)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def _frightened(actor):
    return any(c.condition_id == 'condition:typed.frightened' for c in actor.conditions.values())


def test_dawn_physician_bonus_action_cleanse_and_temporary_hit_points(tmp_path):
    combat, table, mid = fixture(tmp_path, RADIANCE, owner_insights=[ri.DAWN], ally_position={'x': 3, 'y': 7},
                                 bundle_transform=lambda bundles: seal(bundles[2], 'Dread', DREAD))
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Dread', target=ALLY).candidate_id)
    prompt_turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, SWIFT, target=ALLY).candidate_id,
                     picks={'choice:needle.radiance_insights': 'grant'})
    assert any('Dawn Physician' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert not _frightened(ally)
    assert ally.temporary_hp == owner.proficiency_bonus
    assert not owner.bonus_action_available and owner.action_available  # the Bonus Action, not the Action, was spent
    assert owner.resources[ri.USES] == 0
    assert not [c for c in engine.legal_candidates() if c.source_definition_id.endswith('#dawn_physician')]


def test_dawn_physician_is_absent_without_the_insight(tmp_path):
    combat, table, mid = fixture(tmp_path, RADIANCE, ally_position={'x': 3, 'y': 7})
    engine = reload(tmp_path, mid)
    assert not [a for a in engine.action_catalog.values() if a.source_definition_id.endswith('#dawn_physician')]
    prompts = settle(table, mid, candidate(combat, mid, 'Gentle Dawn: Repeat Save vs Poisoned', target=ALLY).candidate_id)
    assert not any('Dawn Physician' in str(p) for p in prompts)
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 0


# ------------------------------------------------------------------------------- Corpse-Tempered Body (batch 12)
NECROTIC = [{'type': 'damage', 'damage_types': ['necrotic'], 'flat': 20, 'applies_to': 'target'}]


def _necrotic_hits(tmp_path, insights):
    from combat.ext import martial_insights as mi
    combat, table, mid = fixture(tmp_path, [], owner_insights=insights, ally_position={'x': 1, 'y': 9},
                                 bundle_transform=lambda bundles: seal(bundles[2], 'Grave Breath', NECROTIC))
    hp = reload(tmp_path, mid).state.actors[OWNER].current_hp
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grave Breath', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    return mi, engine, hp - engine.state.actors[OWNER].current_hp


def test_grave_tempering_resists_the_first_necrotic_packet_and_lasts(tmp_path):
    mi, engine, lost = _necrotic_hits(tmp_path, ['insight.corpse-tempered-body'])
    owner = engine.state.actors[OWNER]
    assert lost == 10  # 20 Necrotic, halved by the Resistance gained from that very packet
    held = [c for c in owner.conditions.values() if c.condition_id == mi.GRAVE]
    assert len(held) == 1 and held[0].expires_on != 'UNTIL_REMOVED'
    assert owner.turn_flags.get(mi.GRAVE_FLAG) == 1


def test_grave_tempering_needs_the_insight(tmp_path):
    _mi, _engine, lost = _necrotic_hits(tmp_path, [])
    assert lost == 20
