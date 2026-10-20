"""Stage 2 must accept the same acquired Sphere effects as native creation."""
from copy import deepcopy
import json

import pytest

from character_creation.constructed_arts.forged_technique import construct_forged_technique
from character_creation.constructed_arts.forging_authority import load_forging_authority
from character_creation.constructed_arts.records import build_forged_technique_record
from character_creation.constructed_arts.sphere_effects import base_effect_rows
from tests.test_constructed_forged_technique_bindings import _case, ROOT


@pytest.mark.parametrize('mutation', [None, 'unowned', 'hash', 'text', 'name', 'source', 'sphere'])
def test_stage2_compiles_only_authentic_base_effects_of_acquired_spheres(tmp_path, mutation):
    request, service, state = _case(tmp_path)
    mechanics = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_bytes())['mechanics']
    printed = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_bytes())
    sources = base_effect_rows(state['known_spheres'], mechanics, printed)
    assert sources
    base = deepcopy(sources[0])
    parent = base['sphere_id']
    # Forge only this real automatic ability, not one of the synthetic learned
    # talents in the fixture. The parent still has a genuine locked source.
    request['known_talents'] = [base]
    request['concept'] = {'primary_talent_id': base['talent_id'], 'base_form': 'strike'}
    if mutation == 'hash':
        base['record_hash'] = 'f' * 64
    elif mutation == 'text':
        base['published_text'] = 'An invented effect.'
    elif mutation == 'name':
        base['display_name'] = 'An invented ability'
    elif mutation == 'source':
        base['source']['source_id'] = 'invented-source'
    elif mutation == 'sphere':
        base['sphere_id'] = next(row['sphere_id'] for row in request['known_spheres'] if row['sphere_id'] != parent)
    technique = construct_forged_technique(load_forging_authority(ROOT), request)
    if mutation == 'unowned':
        state['known_spheres'].remove(parent)
    state['record_event_ids'][parent] = 'acquired-sphere-event'
    before = deepcopy(state)
    blockers, outputs, bindings = service._forged_technique_compile(
        None, 'project-1', build_forged_technique_record(technique), state, '/test', 10)
    assert state == before
    if mutation is None:
        assert not blockers, blockers
        assert outputs['forged_technique']['primary_sphere_effect']['talent_id'] == base['talent_id']
        assert any(row['record_id'] == parent and row['causal_event_id'] == 'acquired-sphere-event' for row in bindings)
        assert base['talent_id'] not in state['known_talents']
    else:
        assert not outputs and not bindings
        assert {row['code'] for row in blockers} & {
            'FORGING_TALENT_NOT_KNOWN', 'FORGING_EFFECT_SOURCE_MISMATCH'}
