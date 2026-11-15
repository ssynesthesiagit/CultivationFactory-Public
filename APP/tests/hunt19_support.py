"""Synthetic portable characters for hunt19 table commit/reload regressions."""
import json
import zipfile

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT, sheet
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, PROJECTS
from tests.test_lock2_persistence import act


def fight(tmp_path, talents, *, right_types=(), rider=False, right_rider=False, mode="MANUAL", ask=True, walls=None):
    for name in PROJECTS:
        doc = sheet(talents if name == 'left' else ['BEASTMASTERY_BASE_RIDER_PACKAGE'] if name == 'right' and right_rider else [], cl=15)
        doc['identity']['display_name'] = name.title()
        if name == 'right':
            doc['identity']['creature_types'] = list(right_types)
        if rider and name == 'left':
            doc['spheres_and_talents']['automatic_sphere_component_record_ids'].append('BEASTMASTERY_BASE_RIDER_PACKAGE')
        folder = tmp_path / 'portable_characters' / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    if ask:
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PROJECTS['left'], {'mode': 'ask'}, {'opportunity_attack'})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Hunt19 regression yard', 'width_squares': 16, 'height_squares': 12,
                              'walls': walls or [], 'starts': {'team1': [[4, 4], [4, 7]], 'team2': [[7, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS['left'], PROJECTS['ally']], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: mode, ALLY: 'MANUAL', RIGHT: 'MANUAL'},
        arena_id='battlefield:map.hunt19-regression-yard', match_seed='HUNT19-REGRESSION')['match_id']
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        if table.state(mid)['menu']['actor_id'] == LEFT:
            return combat, table, mid
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('Left never got a turn')


def send(table, mid, label, *, target=None):
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == label)
    option = next(o for o in group['options'] if target is None or o['target_ids'] == [target])
    return lambda answers: table.act(mid, option['candidate_id'], menu['decision_id'], menu['state_version'],
                                    state['last_sequence'], answers)


def reload(combat, tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine
