"""Stone Fist review-3 regression: CombatService.create_journey must create a real journey.

Before the fix, gate5_service passed an unsupported source_sheets keyword to
JourneyStore.create, so every Journey creation raised TypeError before saving.
Self-contained: plain synthetic sheets (no Stone Fist features, no private fixtures).
"""
import json
import zipfile

from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE


def test_service_create_journey_saves_and_replays(tmp_path):
    documents = {'worker2-owner': sheet([], cl=18, name='Owner'), 'worker2-foe': sheet([], cl=18, name='Foe')}
    for pid, doc in documents.items():
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 5000
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'map_id': 'stone-practice', 'display_name': 'Stone practice yard',
        'width_squares': 20, 'height_squares': 14, 'objects': []})
    state = service.create_journey(project_ids=list(documents), arena_id="battlefield:map.stone-practice",
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}}, base_paces={OWNER: 30, FOE: 30},
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'})
    jid = state['journey_id']
    saved = service.journey_state(jid)
    assert saved['phase'] == 'travel'
    assert set(saved["actors"]) == {OWNER, FOE}
    assert service.journey_replay(jid)['status'] == 'PASS'
