"""Foundation data must ship with its native service regressions.

Explicit resource paths also let the public test exporter follow the data that
the runtime loader discovers through a directory glob. Missing registration data
must fail visibly instead of silently turning every owned ability inert.
"""
import json
from pathlib import Path

import pytest

from tests.test_a2_foundations3 import owner_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,feature,block', [
    ('combat/rules/feature_blocks.d/foundations3.json',
     'foundation.red_lotus_ash_returning_v0_2B.generate_funeral_ash', 'generate'),
    ('combat/rules/feature_blocks.d/foundations3.json',
     'foundation.red_lotus_ash_returning_v0_2B.refined_ash_mercy_boundary', 'foundation_mercy'),
])
def test_native_service_registration_data_is_packaged(path, feature, block):
    data = json.loads((ROOT / path).read_text())
    assert data['features'][feature]['block'] == block


@pytest.mark.parametrize('kind', ['ash', 'mirror', 'lotus', 'bitter', 'spirit'])
def test_compiled_foundation_keeps_owned_generation_registration(kind):
    bundle = owner_bundle(kind, initial=0)
    assert any(row.get('block') == 'generate' and 'foundations3_' + kind in row.get('on', [])
               for row in bundle['typed_passives'])
