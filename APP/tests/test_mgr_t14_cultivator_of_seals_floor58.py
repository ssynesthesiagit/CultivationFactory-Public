"""Native acquisition and persisted seal lifecycle regressions; no live models."""
from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from combat.factory_compiler import compile_character
from combat.feature_access import acquire
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.ext.qi_sealing_chains import LEVELS, MINOR, MARK, SOURCE, PRISON, EDICT, SEAL
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
PATH = 'tianxia.path.qi_cultivation'
PARENT = 'tianxia.subpath.qi.cultivator_of_seals'
ME, FOE = FACTORY_ACTOR_PREFIX + 'seal-owner', FACTORY_ACTOR_PREFIX + 'seal-target'


def acquired_sheet(cl=18, *, acquired=True):
    sheet = deepcopy(SHEET)
    sheet['identity'].update(cultivation_level=cl, name='Seal Cultivator')
    sheet['spheres_and_talents'] = {}
    sheet['path_and_subpath'] = {'path_record_ids': [PATH],
        'subpaths': [{'subpath_id': PARENT, 'owning_path_id': PATH}]}
    sheet['ability_scores_and_statistics']['technique_save_dc'] = 50
    if acquired:
        for feature, minimum in LEVELS.items():
            if minimum <= cl:
                sheet = acquire(sheet, feature, {'kind': 'scripture', 'reference': 'Test campaign: granted Seals scripture',
                    'classification': 'Restricted Scripture'})
    return sheet


def install(root, name, sheet):
    folder = root / 'portable_characters' / name
    folder.mkdir(parents=True)
    with ZipFile(folder / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))


def setup(tmp_path):
    install(tmp_path, 'seal-owner', acquired_sheet())
    target = deepcopy(SHEET)
    target['identity'].update(name='Target', cultivation_level=10)
    target['spheres_and_talents'] = {}
    target['path_and_subpath'] = {'path_record_ids': [PATH]}
    install(tmp_path, 'seal-target', target)
    service = CombatService(ROOT, tmp_path)
    arena = service.tabletop_maps.save({'display_name': 'Seal Test', 'width_squares': 16, 'height_squares': 12,
        'starts': {'team1': [[4, 5]], 'team2': [[5, 5]]},
        'objects': [{'id': 1, 'kind': 'door', 'x': 4, 'y': 6, 'size': 'medium',
                     'door_open': 0, 'door_locked': 0, 'door_jammed': 0}]})
    view = service.create_factory_match(project_ids=['seal-owner'], opponent_actor_ids=[FOE],
        match_seed='SEAL-NATIVE', arena_id='battlefield:map.' + arena['map_id'],
        control_modes={ME: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'})
    session = service._load_session(view['match_id'])
    for _ in range(4):
        if session.engine.state.current_actor_id == ME:
            break
        act(session, next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN'))
    assert session.engine.state.current_actor_id == ME
    return service, session


def act(session, candidate):
    session.submit_intent(ActionIntent(intent_id='seal-test:' + str(session.engine.state.state_version),
        candidate_id=candidate.candidate_id, decision_id=candidate.decision_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination),
        primary_decision_record=None, reaction_provider=None)


def test_native_restricted_progression_requires_access_and_respects_level():
    denied = compile_character(acquired_sheet(acquired=False), actor_id=ME)
    assert not [a for a in denied['action_catalog'] if (a['parameters'].get('typed') or {}).get('source') in LEVELS]
    low = compile_character(acquired_sheet(6), actor_id=ME)
    sources = {(a['parameters'].get('typed') or {}).get('source') for a in low['action_catalog']}
    assert {MINOR, SOURCE} <= sources
    assert not {MARK, PRISON, EDICT} & sources
    wrong = acquired_sheet()
    wrong['path_and_subpath']['subpaths'][0]['owning_path_id'] = 'tianxia.path.body_refining'
    wrong['path_and_subpath']['path_feature_record_ids'] = []
    assert not [a for a in compile_character(wrong, actor_id=ME)['action_catalog']
                if (a['parameters'].get('typed') or {}).get('source') in LEVELS]


@pytest.mark.parametrize('feature,cost', [(SOURCE, 3), (MINOR, 1), (MARK, 5), (PRISON, 6), (EDICT, 8)])
def test_native_source_activation_commits_and_cold_reloads(tmp_path, feature, cost):
    service, session = setup(tmp_path)
    engine = session.engine
    before = engine.state.actors[ME].resources['resource:core.qi']
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == feature
        and (feature != MARK or not c.source_definition_id.endswith(('.meridian', '.core')))]
    assert candidates
    act(session, candidates[0])
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert reloaded.engine.state.actors[ME].resources['resource:core.qi'] == before - cost
    state = reloaded.engine.state
    if feature == SOURCE:
        assert any(c.data.get('qi5_chain') for c in state.actors[FOE].conditions.values())
        assert reloaded.engine._effective_speed(state.actors[FOE]) == 0
    else:
        bound = [c for a in state.actors.values() for c in a.conditions.values()
                 if c.condition_id == SEAL and c.data.get('seal_feature') == feature]
        assert len(bound) == (3 if feature == EDICT else 1)
        anchors = [o for o in state.objects.values() if (o.component or {}).get('seal_feature') == feature]
        assert len(anchors) == len(bound)
        assert all(o.current_hp > 0 and o.component['source_cl'] == 18 for o in anchors)
        if feature in {PRISON, EDICT}:
            assert reloaded.engine._effective_speed(state.actors[FOE]) == 0
