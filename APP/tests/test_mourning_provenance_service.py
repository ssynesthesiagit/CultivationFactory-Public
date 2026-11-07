"""Mourning witness concealment through paid table actions and cold saved-fight reloads."""
import pytest

from combat import senses
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

PRIOR = 'actor:factory.worker2-ally3'
UNHARMED = 'actor:factory.worker2-ally4'
GE = 'tianxia.tradition.spirit.grief_eater.feature.'
GE_ALL = ['tianxia.path.spirit_awakening.feature.mind_spike'] + [GE + name for name in (
    'taste_of_sorrow', 'eat_the_bitter_memory', 'shared_burden',
    'weight_of_mourning', 'vessel_of_ten_thousand_sorrows')]
BURDEN = 'resource:named.sorrow_burden'


def mourning_bundle():
    """Same native C8 creature statistics, independent of historical test modes."""
    modifiers = {'STR': 1, 'DEX': 2, 'CON': 2, 'INT': 1, 'WIS': 4, 'CHA': 1}
    return compile_character({
        'identity': {'proficiency_bonus': 6, 'cultivation_level': 18,
                     'path': 'Spirit Awakening', 'key_ability': 'WIS'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 10 + 2 * m, 'modifier': m}
                          for a, m in modifiers.items()],
            'primary_resource': {'name': 'Resonance', 'maximum': 60},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 90},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 100, 'technique_attack_bonus': 9},
        'path_and_subpath': {'path_record_ids': [], 'path_feature_record_ids': GE_ALL},
    }, actor_id=OWNER)


@pytest.mark.parametrize('weight,chair,observer_outside',
                         [(True, False, False), (False, True, False), (True, True, False), (False, True, True)],
                         ids=['weight', 'empty-chair', 'both', 'empty-chair-observer-outside'])
def test_mourning_witness_perception_after_table_commit_and_cold_reload(tmp_path, weight, chair, observer_outside):
    owner_bundle = mourning_bundle()

    def setup(bundles):
        for resource in bundles[0]['actor_template']['resources']:
            if resource['resource_id'] == BURDEN:
                resource['initial'] = 2
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
        for name in ('Earlier unrelated harm', 'Qualifying harm'):
            add_action(bundles[2], name, [{'type': 'damage', 'flat': 1,
                'damage_types': ['force'], 'applies_to': 'target'}], economy='NONE')
        conditions = (['hidden'] if weight else []) + (['invisible'] if chair else [])
        add_action(bundles[2], 'Conceal self', [{'type': 'condition', 'condition': cid,
            'applies_to': 'self', 'duration': {'kind': 'minutes', 'amount': 1}}
            for cid in conditions], target_kind='SELF', economy='NONE')

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle,
        bundle_transform=setup, extra_allies=2,
        ally_position={'x': 10, 'y': 5} if observer_outside else None,
        seed='MOURNING-PROVENANCE-'+str(weight)+str(chair)+str(observer_outside))

    def press(name, target=None, picks=None):
        return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, picks=picks)

    turn(table, mid, FOE)
    press('Earlier unrelated harm', PRIOR)
    press('Qualifying harm', ALLY)
    turn(table, mid, OWNER)
    if weight:
        press('Weight of Mourning', FOE)
    if chair:
        prompts = press('Vessel of Ten Thousand Sorrows', picks={
            'choice:needle.grief_eater.offices': ['empty_chair']})
        assert any(p['context']['reaction_source_id'] == 'choice:needle.grief_eater.offices' for p in prompts)
    turn(table, mid, FOE)
    press('Conceal self')

    # The table has committed every act; reload creates an independent service and replays the save.
    engine = reload(tmp_path, mid)
    owner, ally, foe, prior, unharmed = [engine.state.actors[aid]
        for aid in (OWNER, ALLY, FOE, PRIOR, UNHARMED)]
    if weight:
        held = next(c for c in foe.conditions.values() if c.condition_id == 'condition:typed.mourning_weight')
        assert held.data['harmed'] == [ALLY]
        assert held.source_actor_id == OWNER
    if chair:
        field = next(c for c in owner.conditions.values() if c.condition_id == 'condition:typed.mourning_field')
        assert field.data['offices'] == ['empty_chair']
        if observer_outside:
            from combat.ext.grief_eater import _in_field
            assert not _in_field(engine, owner, ally)
            assert _in_field(engine, owner, foe)
    assert owner.resources[BURDEN] == 2 - int(weight) - int(chair)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FOE]
    earlier = next(e for e in damage if PRIOR in e.target_ids)
    qualifying = next(e for e in damage if ALLY in e.target_ids)
    assert earlier.trigger_or_intent_id != qualifying.trigger_or_intent_id
    conditions = {c.condition_id: iid for iid, c in foe.conditions.items()}
    masks = senses.masked_conditions(engine, ally, foe).get(FOE, set())
    if weight:
        assert conditions['condition:typed.hidden'] in masks
        assert conditions['condition:typed.hidden'] not in senses.masked_conditions(engine, prior, foe).get(FOE, set())
    if chair:
        assert conditions['condition:typed.invisible'] in masks
        # Empty Chair's printed relationship includes earlier harm during the scene.
        assert conditions['condition:typed.invisible'] in senses.masked_conditions(engine, prior, foe).get(FOE, set())
    assert senses.perceives(engine, ally, foe, locate_concealed=True, sight_only=True)
    assert senses.perceives(engine, owner, foe, locate_concealed=True, sight_only=True) == (not chair)
    assert senses.perceives(engine, prior, foe, locate_concealed=True, sight_only=True) == (not weight)
    assert not senses.perceives(engine, unharmed, foe, locate_concealed=True, sight_only=True)
