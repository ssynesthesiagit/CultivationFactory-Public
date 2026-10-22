"""Public regression: NS1R-recorded Heaven-Devouring Black Cauldron acquisition reaches compiled rows.

Synthetic sheets only: no private authority pack, evidence store, live model or GUI. Each assertion compiles the
real factory compiler, so it fails if the compiler stops consuming recorded native Subpath acquisition.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.ext import black_cauldron as C
QI = 'tianxia.path.qi_cultivation'
ACTOR = 'actor:factory.cauldron-public'


def base_sheet(cl):
    """Minimal owner sheet: identity, abilities and combat statistics, no spheres or talents."""
    score = 14
    return {
        'identity': {'proficiency_bonus': 4, 'cultivation_level': cl, 'path': 'Qi Cultivation',
                     'key_ability': 'CON', 'name': 'Cauldron keeper'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': score, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 30}, 'armor_class': {'base_value': 14},
            'hit_points': {'maximum': 60}, 'speed': {'walking_ft': 30},
            'technique_save_dc': 16, 'technique_attack_bonus': 8},
    }


def acquired_sheet(cl, *, parent=C.PARENT, path_id=QI):
    doc = base_sheet(cl)
    doc['path_and_subpath'] = {'paths': [{
        'path_id': path_id, 'attainment': cl, 'effective_cl': cl,
        'subpath_or_tradition_id': parent,
        'subpath_or_tradition_acquisition_provenance': {
            'schema': 'TianxiaFactory.AcquisitionProvenance.v1', 'canonical_content_id': parent,
            'content_type': 'Qi Cultivation Subpath', 'access_category': 'Open',
            'source': 'post-creation-authority-selection', 'recorded': True},
    }]}
    return doc


def black_cauldron_features(bundle):
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get('block') == 'black_cauldron' and node.get('feature_id'):
                found.add(node['feature_id'])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(bundle)
    return found


@pytest.mark.parametrize('cl', [3, 6, 10, 14, 18])
def test_acquired_cauldron_tiers_compile_into_rows(cl):
    expected = {fid for fid, tier in C.TIERS.items() if cl >= tier}
    bundle = compile_character(acquired_sheet(cl), actor_id=ACTOR)
    assert black_cauldron_features(bundle) == expected


def test_below_first_tier_grants_nothing():
    bundle = compile_character(acquired_sheet(2), actor_id=ACTOR)
    assert black_cauldron_features(bundle) == set()


def test_wrong_path_parent_grants_nothing():
    bundle = compile_character(acquired_sheet(18, path_id='tianxia.path.not_qi'), actor_id=ACTOR)
    assert black_cauldron_features(bundle) == set()


def test_stale_exported_grant_list_does_not_reopen_unrecorded_tier():
    doc = acquired_sheet(18)
    doc['path_and_subpath']['paths'][0]['subpath_or_tradition_acquisition_provenance']['recorded'] = False
    doc['path_and_subpath']['source_granted_subpath_feature_record_ids'] = [C.RESIDUE, C.FIELD]
    bundle = compile_character(doc, actor_id=ACTOR)
    assert black_cauldron_features(bundle) == set()
