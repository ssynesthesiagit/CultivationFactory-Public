"""Foundation data must ship with its native service regressions.

Explicit resource paths also let the public test exporter follow the data that
the runtime loader discovers through a directory glob. Missing registration data
must fail visibly instead of silently turning every owned ability inert.
"""
import json
from pathlib import Path

import pytest

from tests.test_a2_foundations3 import owner_bundle
from tests.h1_support import sheet
from combat.factory_compiler import compile_character

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,feature,block', [
    ('combat/rules/feature_blocks.d/foundations3.json',
     'foundation.red_lotus_ash_returning_v0_2B.generate_funeral_ash', 'generate'),
    ('combat/rules/feature_blocks.d/foundations3.json',
     'foundation.red_lotus_ash_returning_v0_2B.refined_ash_mercy_boundary', 'foundation_mercy'),
    ('combat/rules/feature_blocks.d/mgr_t14_spirit_vessel_value.json',
     'foundation.origin_spirit_body_v0_2B.origin_spirit_vessel', 'foundations3_spirit_value'),
])
def test_native_service_registration_data_is_packaged(path, feature, block):
    data = json.loads((ROOT / path).read_text())
    assert data['features'][feature]['block'] == block


@pytest.mark.parametrize('kind', ['ash', 'mirror', 'lotus', 'bitter', 'spirit'])
def test_compiled_foundation_keeps_owned_generation_registration(kind):
    bundle = owner_bundle(kind, initial=0)
    assert any(row.get('block') == 'generate' and 'foundations3_' + kind in row.get('on', [])
               for row in bundle['typed_passives'])


def test_compiled_foundation_keeps_owned_optional_support_registration():
    """The amount driver's Life fixture needs Vessel's dynamically loaded row."""
    feature = 'foundation.origin_spirit_body_v0_2B.origin_spirit_vessel'
    bundle = compile_character(sheet(['tianxia.talent.life.greater_invigorate', feature]),
                               actor_id='actor:test.packaged_spirit_vessel')
    assert any(row.get('block') == 'foundations3_spirit_value'
               and row.get('kind') == 'temporary_hp' and row.get('feature_id') == feature
               and row.get('pb') == 4 for row in bundle['typed_passives'])
