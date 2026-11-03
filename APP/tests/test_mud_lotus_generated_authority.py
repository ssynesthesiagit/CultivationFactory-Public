"""Generated Mud Lotus metadata retains reviewed native ownership and area."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'foundation.mud_lotus_dantian_v0_2A.'


def test_mud_lotus_generated_coverage_and_field_area():
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    for name in ('humble_medicine_witness', 'refined_muddy_filter_dantian'):
        assert authority[PREFIX + name]['coverage'] == 'CORE_WITH_RIDERS'
    field = authority[PREFIX + 'lotus_recovery_field']
    assert field['area'] == {'shape': 'emanation', 'size_ft': 20, 'centered_on_self': True}
    assert field['target']['text'] == 'Chosen allies in area'
