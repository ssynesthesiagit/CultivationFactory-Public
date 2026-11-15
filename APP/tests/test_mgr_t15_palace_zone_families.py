"""Structured shape names must match only their own area, with a real trigger."""
import pytest

from combat.factory_compiler import _zone_shapes, compile_character
from combat.gate2_runtime_models import ActionDefinition
from tests.h1_support import sheet
from tests.worker2_support import OWNER


@pytest.mark.parametrize('name', ['Darkness', 'Ashfall', 'Fragrance', 'Patrol Zone', 'Conflagration'])
def test_redacted_shape_association_does_not_admit_unrelated_or_inert_names(name, monkeypatch):
    from combat import factory_compiler
    monkeypatch.setattr(factory_compiler, '_rules_text', lambda: {})
    bundle = compile_character(sheet(['FIRE_BASE_IGNITE']), actor_id=OWNER)
    row = ActionDefinition.model_validate(bundle['action_catalog'][0])
    def talent(title, trigger):
        return {'name': title, 'activation': {'economy': 'passive', 'trigger': trigger},
                'description': [], 'effects': [{'type': 'damage', 'flat': 1, 'applies_to': 'target'}]}
    mechanics = {
        'matching': talent('Fearful ' + name, 'A creature enters the area or starts its turn inside.'),
        'inert': talent('Greater ' + name, ''),
        'unrelated': talent('Fearful Unrelated Area', 'A creature enters the area or starts its turn inside.'),
        'substring': talent('Fearful Not' + name, 'A creature enters the area or starts its turn inside.'),
    }
    shapes = _zone_shapes(name, 'base', mechanics, list(mechanics), {}, row,
                          lambda *args: [], 'resource:test')['shapes']
    assert set(shapes) == {'matching'}
    assert shapes['matching']['triggers'][0]['on'] == ['enter', 'start']
