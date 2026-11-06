"""Acquiring Mantis Style at the table keeps the character's equipment and saved settings.

Round MGR-T14 review F13 finding 1: the native acquisition compiled the acquired
sheet with a bare compiler, so the creature that walked into the fight had lost
every item its owner gave it and every Ask/powering/attunement choice saved for it.
It now publishes through the same settings-preserving compiler an ordinary
matching fight uses, so these assertions fail without that change.

The two characters get hex project ids because ButtonStore saves a character's
table settings under its project id and accepts only those ids; everything else
here is the ordinary portable-character and journey path.
"""

import json
import zipfile

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import ButtonStore
from factory_authoring import owner_items as O
from tests.h1_support import ROOT, sheet
from tests.worker2_support import reload

PARENT = 'tianxia.subpath.body.mantis_style'
DAGGER = 'tianxia.mortal.weapon.bi_shou'
PROJECT = 'a1b2c3d4'
COMPANION_PROJECT = 'b2c3d4e5'
OWNER = FACTORY_ACTOR_PREFIX + PROJECT
COMPANION = FACTORY_ACTOR_PREFIX + COMPANION_PROJECT


def _journey(tmp_path):
    """Two portable characters on one journey map: the practitioner and a plain companion."""
    for project, owner in ((PROJECT, True), (COMPANION_PROJECT, False)):
        doc = sheet([], cl=18, primary='Stamina' if owner else 'Qi', score=30 if owner else 10,
                    dc=100 if owner else 16, name='Mantis practitioner' if owner else 'Companion')
        if owner:
            doc['identity']['path'] = 'Body Refining'
            # The installed build has its automatic core attacks; Mantis itself is
            # acquired only by the native source operation.
            doc['path_and_subpath'] = {'path_feature_record_ids': ['tianxia.path.body_refining.feature.iron_fist',
                                                                   'tianxia.path.body_refining.feature.extra_attack']}
        stats = doc['ability_scores_and_statistics']
        stats['primary_resource']['maximum'] = 100
        stats['hit_points']['maximum'] = 1000
        stats['armor_class']['base_value'] = 5
        folder = tmp_path / 'portable_characters' / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'map_id': 'mantis-acquire', 'display_name': 'Mantis training yard',
        'width_squares': 20, 'height_squares': 14, 'objects': [],
        'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]}})
    journey = combat.create_journey(project_ids=[PROJECT, COMPANION_PROJECT],
        arena_id='battlefield:map.mantis-acquire',
        positions={OWNER: {'x': 3, 'y': 6}, COMPANION: {'x': 4, 'y': 6}},
        base_paces={OWNER: 3000, COMPANION: 3000})
    return combat, journey


def test_acquisition_keeps_the_given_weapon_and_the_asked_reactions(tmp_path):
    combat, journey = _journey(tmp_path)
    choices = O.weapon_choices(DAGGER, 'Saint', None, [])
    item = O.OwnerItemStore(tmp_path / 'owner_items').give(
        PROJECT, {'kind': 'weapon', 'chassis_id': DAGGER, 'grade': 'Saint', 'material_id': choices['material_id']})
    # "Ask me" (step 16) is a saved table setting, not part of the sheet.
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PROJECT, {'mode': 'ask'}, set())

    acquired = combat.journey_acquire_source(journey['journey_id'], journey['revision'], OWNER, PARENT, {'operation': 'select'})
    started = combat.journey_start_combat(acquired['journey_id'], acquired['revision'],
        {OWNER: 'team:factory', COMPANION: 'team:opponents'}, maximum_rounds=10)
    fight = next(row for row in reload(tmp_path, started['match_id']).typed_bundle_documents
                 if row.get('actor_id') == OWNER)
    attack = item['name'] + ' attack'
    # Both the acquired journey bundle and the fight it started carry the build.
    for bundle in (acquired['actors'][OWNER]['bundle'], fight):
        assert any(row['row']['name'] == item['name'] for row in bundle['weapons']), bundle['weapons']
        assert any(row['display_name'] == attack for row in bundle['action_catalog'])
        assert bundle['reaction_plan']['mode'] == 'ask'
