"""Public synthetic native acquisition/continuation coverage for multi-Path sheets."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from combat import factory_compiler
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import normalize_map, to_battlefield

ROOT = Path(__file__).resolve().parents[1]
BODY = 'tianxia.path.body_refining'
QI = 'tianxia.path.qi_cultivation'
SUMO = 'tianxia.subpath.body.sumo'
OLD = 'tianxia.subpath.qi.sound_cultivator'
NEW = 'tianxia.subpath.qi.poison_cultivator'
SPIRIT = 'tianxia.tradition.spirit.dreamweaver'
OTHER_FEATURE = OLD + '.feature.instrument_of_qi'
A = FACTORY_ACTOR_PREFIX + 'multi'


def sheet():
    return {
        'identity': {'display_name': 'Multi-Path practitioner', 'proficiency_bonus': 2,
                     'cultivation_level': 3, 'path': 'Body Refining', 'key_ability': 'CON'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Stamina', 'maximum': 12},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 30},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 12,
            'technique_attack_bonus': 4},
        'path_and_subpath': {
            'path_record_ids': [BODY, QI],
            'paths': [{'path_id': p, 'attained_cl': 3, 'effective_cl': 3} for p in (BODY, QI)],
            'path_feature_record_ids': [OTHER_FEATURE]},
        'spheres_and_talents': {}, 'equipment': [],
    }


@pytest.mark.parametrize('selection_shape', ['both', 'singular', 'list'])
def test_native_sumo_preserves_other_paths_at_acquisition_and_later_continuation(
        tmp_path, monkeypatch, selection_shape):
    current = sheet()
    paths = current['path_and_subpath']
    paths['subpath_record_ids'] = [] if selection_shape == 'singular' else [OLD]
    paths['subpath_record_id'] = None if selection_shape == 'list' else OLD
    if selection_shape != 'list':
        current['identity'].update(path='Qi Cultivation', key_ability='INT')
        paths['path_record_id'] = QI
        current['ability_scores_and_statistics']['primary_resource']['name'] = 'Cultivation Points'
    compiled = {}
    compile_character = factory_compiler.compile_character

    def capture(owner_sheet, *, actor_id, **kwargs):
        compiled[actor_id] = deepcopy(owner_sheet)
        return compile_character(owner_sheet, actor_id=actor_id, **kwargs)

    monkeypatch.setattr(factory_compiler, 'compile_character', capture)
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid: deepcopy(current))
    arena = to_battlefield(normalize_map({
        'display_name': 'Multi-Path school', 'width_squares': 10,
        'height_squares': 10, 'objects': [], 'starts': {}}))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'school': arena})

    def cold():
        return CombatService(ROOT, tmp_path)

    def start():
        return cold().create_journey(
            project_ids=['multi'], arena_id='school', positions={A: {'x': 3, 'y': 3}},
            base_paces={A: 5}, control_modes={A: 'MANUAL'})

    state = start()
    jid = state['journey_id']
    state = cold().journey_world_fact(jid, state['revision'], {
        'source': SUMO, 'subject': A, 'kind': 'school_access', 'scope': 'school',
        'value': {'school': SUMO, 'teacher': 'Open School teacher',
                  'source_rule': 'Body Path R8: one Subpath at CL3; Sumo Open School'},
        'expires_at': 1000, 'readers': []})
    state = cold().journey_acquire_source(jid, state['revision'], A, SUMO, {'access_scope': 'school'})
    assert cold().journey_state(jid) == state
    acquired = compiled[A]['path_and_subpath']
    assert acquired['subpath_record_ids'] == [OLD, SUMO]
    assert acquired['subpath_record_id'] == (SUMO if selection_shape == 'list' else OLD)
    assert acquired['path_feature_record_ids'] == [OTHER_FEATURE, SUMO + '.feature.rooted_stance']
    receipt = state['actors'][A]['source_states'][SUMO]['acquired_sheet']
    assert json.loads(receipt)['path_and_subpath'] == acquired

    # The owner changes a different Path after acquisition. A new native journey
    # must project only Sumo from its persisted receipt, not restore the stale sheet.
    state = cold().journey_act(jid, state['revision'], A, 'finish', {})
    assert cold().journey_state(jid) == state
    paths.update(subpath_record_id=NEW, subpath_record_ids=[NEW, SPIRIT],
                 path_feature_record_ids=[NEW + '.feature.venomous_qi'])
    paths['path_record_ids'].append('tianxia.path.spirit_awakening')
    paths['paths'].append({'path_id': 'tianxia.path.spirit_awakening', 'attained_cl': 3, 'effective_cl': 3})
    before = deepcopy(current)
    state = start()
    assert state['journey_id'] != jid
    assert cold().journey_state(state['journey_id']) == state
    continued = compiled[A]['path_and_subpath']
    assert continued['subpath_record_ids'] == [NEW, SPIRIT, SUMO]
    assert continued['subpath_record_id'] == NEW
    assert OLD not in continued['subpath_record_ids']
    assert continued['path_feature_record_ids'] == [
        NEW + '.feature.venomous_qi', SUMO + '.feature.rooted_stance']
    assert continued['paths'] == paths['paths']
    assert continued['path_record_ids'] == paths['path_record_ids']
    assert state['actors'][A]['source_states'][SUMO]['acquired_sheet'] == receipt
    assert current == before

    # Repeated continuation does not duplicate Sumo or resurrect old selections.
    state = cold().journey_act(state['journey_id'], state['revision'], A, 'finish', {})
    again = start()
    assert compiled[A]['path_and_subpath'] == continued
    assert cold().journey_state(again['journey_id']) == again
