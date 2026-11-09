"""Heart-Ash's tier replacement crosses native admission, commit and reload."""
import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from non_sphere_authority.foundation_mechanics import (
    resolve_initial_foundation_mechanics, verified_foundation_records,
)
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, turn, candidate, settle
from tests.test_a2_foundations3 import add_action, pool

FOUNDATION = 'red_lotus_ash_returning_v0_2B'
HEART = 'foundation.' + FOUNDATION + '.refined_red_lotus_heart_ash'


@pytest.mark.parametrize('stage,expected', [('Awakened', 60), ('Refined', 64), ('Perfected', 64)])
def test_heart_ash_hp_tier_native(tmp_path, stage, expected):
    # The shipped initial calculator has already included one PB in these 60 HP.
    # Keep its real source-bound projection so a tier replaces that contribution.
    mechanics = resolve_initial_foundation_mechanics(
        verified_foundation_records()[FOUNDATION], ['tianxia.path.qi_cultivation'])
    doc = sheet(['foundation.' + FOUNDATION + '.ash_returning_meridian'],
                foundation={'foundation_id': FOUNDATION, 'stage': stage,
                            'mechanics': mechanics})
    bundle = compile_character(doc, actor_id=OWNER)
    assert compile_character(doc, actor_id=OWNER) == bundle
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, seed='HEART-ASH-HP')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].maximum_hp == expected
    assert engine.state.actors[ALLY].maximum_hp == 60
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == expected


def test_heart_ash_rejects_changed_hp_provenance():
    mechanics = resolve_initial_foundation_mechanics(
        verified_foundation_records()[FOUNDATION], ['tianxia.path.qi_cultivation'])
    mechanics['hp_maximum_modifiers'][0]['formula']['root']['terms'][0]['value'] = 2
    doc = sheet([HEART], foundation={'foundation_id': FOUNDATION, 'stage': 'Refined',
                                    'mechanics': mechanics})
    with pytest.raises(FoundryError) as error:
        compile_character(doc, actor_id=OWNER)
    assert error.value.code == 'COMBAT_FOUNDATION_HP_PROJECTION_INVALID'


def test_heart_ash_legacy_hp_is_preserved(tmp_path):
    # No authenticated contribution means the compiler must not add PB to a
    # total that could already include the Refined benefit.
    doc = sheet([HEART], foundation={'foundation_id': FOUNDATION, 'stage': 'Refined'})
    bundle = compile_character(doc, actor_id=OWNER)
    _, _, mid = fixture(tmp_path, [], owner_bundle=bundle, seed='HEART-ASH-LEGACY-HP')
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == 60


def test_heart_ash_exhausted_receipt_cannot_qualify_unrelated_ash(tmp_path):
    prefix = 'foundation.' + FOUNDATION + '.'
    cautery = prefix + 'red_lotus_cautery'
    doc = sheet([prefix + 'generate_funeral_ash', cautery, HEART],
                foundation={'foundation_id': FOUNDATION, 'stage': 'Refined',
                            'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                                         'maximum': 1, 'current': 0}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def deliveries(bundles):
        add_action(bundles[2], 'Prior fire', [{'type': 'damage', 'flat': 12,
                   'damage_types': ['fire'], 'applies_to': 'target'}])
        add_action(bundles[0], 'Spend old Ash', [{'type': 'spend_resource',
                   'resource_id': pool('ash'), 'flat': 1, 'applies_to': 'self'}], target_kind='SELF')
        # A real resource effect with a different producer is a negative control,
        # not evidence that a Foundation-aligned source generated this unit.
        add_action(bundles[2], 'Unrelated resource grant', [{'type': 'gain_resource',
                   'resource_id': pool('ash'), 'flat': 1, 'applies_to': 'target'}],
                   target_kind='ANY_CREATURE', economy='BONUS_ACTION')

    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle,
                               bundle_transform=deliveries, seed='HEART-ASH-EXHAUSTED')
    picks = {'reaction:typed.' + cautery: 'first'}
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Prior fire', target=OWNER).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 1
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Spend old Ash', target=OWNER).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 0
    turn(table, mid, FOE)
    # The old generation's native end-of-turn clock has now settled. Give
    # this unrelated unit afterwards, so expiry cannot erase the control.
    settle(table, mid, candidate(combat, mid, 'Unrelated resource grant', target=OWNER).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 1
    settle(table, mid, candidate(combat, mid, 'Prior fire', target=OWNER).candidate_id, picks=picks)
    engine = reload(tmp_path, mid)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == cautery]
    assert len(resolved) == 1
    assert resolved[-1].payload['reduction'] == 6
