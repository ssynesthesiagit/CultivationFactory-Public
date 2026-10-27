"""A creature's Eye of the Mantis keeps the rest of its minute when the journey is reopened.

Round MGR-T14 review F13 finding 2: the journey re-anchors every carried Eye by
writing its remaining time onto the new clock, but it did so once per creature,
so a creature initialized early recomputed (and stretched) a later roster
member's still-stale deadline. A journey that ended at 120 s with 30 s left on a
later member's Eye handed that member 150 s on reopen.
"""

import json
import zipfile

from fractions import Fraction

from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY

PARENT = 'tianxia.subpath.body.mantis_style'


def reopenable(tmp_path):
    """The practitioner joins second, behind a plain companion."""
    for aid, owner in ((ALLY, False), (OWNER, True)):
        doc = sheet([], cl=18, primary='Stamina' if owner else 'Qi', score=30 if owner else 10,
                    dc=100 if owner else 16, name='Mantis practitioner' if owner else 'Defender')
        if owner:
            doc['identity']['path'] = 'Body Refining'
            # Mantis itself arrives only through the native source operation.
            doc['path_and_subpath'] = {'path_feature_record_ids': ['tianxia.path.body_refining.feature.iron_fist']}
        stats = doc['ability_scores_and_statistics']
        stats['primary_resource']['maximum'] = 100
        stats['hit_points']['maximum'] = 1000
        stats['armor_class']['base_value'] = 5
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'map_id': 'mantis-reopen', 'display_name': 'Mantis training yard',
        'width_squares': 20, 'height_squares': 14, 'objects': [],
        'starts': {'team1': [[3, 6], [3, 7]], 'team2': [[4, 6]]}})
    return combat


def travel(combat):
    return combat.create_journey(project_ids=['worker2-ally', 'worker2-owner'],
        arena_id='battlefield:map.mantis-reopen',
        positions={ALLY: {'x': 3, 'y': 6}, OWNER: {'x': 3, 'y': 7}},
        base_paces={ALLY: 3000, OWNER: 3000})


def remaining(combat, journey_id):
    eye = combat.journey_menu(journey_id, OWNER)['properties']['mantis_private_diagnosis']
    return Fraction(eye['remaining_num'], eye['remaining_den'])


def test_a_later_members_eye_keeps_the_rest_of_its_minute_across_a_reopen(tmp_path):
    combat = reopenable(tmp_path)
    first = travel(combat)
    journey_id = first['journey_id']
    state = combat.journey_acquire_source(journey_id, first['revision'], OWNER, PARENT, {'operation': 'select'})
    state = combat.journey_act(journey_id, state['revision'], OWNER, 'wait', {'seconds': 90})
    # The printed minute: the Eye is opened after 90 s of travel, so it would
    # end at 150 s, and the journey ends 30 s later with 30 s left on it.
    state = combat.journey_act(journey_id, state['revision'], OWNER, 'mantis_eye', {'target': ALLY})
    state = combat.journey_act(journey_id, state['revision'], OWNER, 'wait', {'seconds': 30})
    assert remaining(combat, journey_id) == 30
    combat.journey_act(journey_id, state['revision'], OWNER, 'finish', {})

    second = travel(combat)
    assert remaining(combat, second['journey_id']) == 30
    assert [row['remaining_seconds'] for row in second['actors'][OWNER]['bundle']['mantis_travel_eyes']] == [30]
    # A cold read of the reopened journey agrees: the duration is carried, not
    # restarted and not slid forward off a stale deadline.
    assert remaining(CombatService(ROOT, tmp_path), second['journey_id']) == 30
    # And it really ends after its minute: 30 s later the diagnosis is gone.
    state = combat.journey_act(second['journey_id'], second['revision'], OWNER, 'wait', {'seconds': 30})
    assert state['seconds'] == 30
    assert 'mantis_private_diagnosis' not in combat.journey_menu(second['journey_id'], OWNER)['properties']
    assert 'mantis_travel_eyes' not in state['actors'][OWNER]['bundle']
