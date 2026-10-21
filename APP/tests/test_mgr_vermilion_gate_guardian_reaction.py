"""Guardian at the Gate is the printed Reaction on a hostile crossing, not a passive row."""
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
KEY = 'tianxia.subpath.body.vermilion_gate_guardian_body.feature.guardian_at_the_gate'


def _record(path):
    doc = json.loads(Path(path).read_text())
    rows = doc.get('mechanics', doc) if isinstance(doc, dict) else doc
    if isinstance(rows, list):
        return next(r for r in rows if r.get('mechanic_id') == KEY)
    return rows[KEY]


@pytest.mark.parametrize('path', [
    'authority/typed_mechanics/reviewed_final.d/riders_c7.json',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
])
def test_guardian_at_the_gate_is_printed_reaction_on_hostile_crossing(path):
    row = _record(APP / path)
    assert row['activation']['economy'] == 'reaction'
    assert 'hostile creature crosses' in row['activation']['trigger'].lower()
    assert row['header_economy'] is True


def test_shelter_landing_choices_are_distinct_without_internal_coordinates():
    from combat.ext.vermilion_gate import _shelter_landing_label, _shelter_landing_relative_location
    from combat.gate2_runtime_models import Position

    origin = Position(x=12, y=7, z=0)
    left = Position(x=11, y=7, z=0)
    right = Position(x=13, y=7, z=0)
    labels = [
        _shelter_landing_label('cell:11,7,0', 1, _shelter_landing_relative_location(origin, left)),
        _shelter_landing_label('cell:13,7,0', 2, _shelter_landing_relative_location(origin, right)),
    ]
    assert labels[0] != labels[1]
    assert 'to your left' in labels[0]
    assert 'to your right' in labels[1]
    assert 'choice 1' in labels[0]
    assert 'choice 2' in labels[1]
    for label in labels:
        assert '12,7' not in label and '13,7' not in label
        assert 'cell:' not in label
        assert 'square beside the threshold' in label
