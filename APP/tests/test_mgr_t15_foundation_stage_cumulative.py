"""Finding 1 regression: Foundation stages are cumulative for every Foundation.

The rule is generic, not Oath-Skin-Frame-specific. The printed "Cumulative stages"
clause appears on all 30 authoritative Foundation entries (catalog line 107),
and Stage Progression runs Awakened -> Integrated -> Refined -> Perfected. An
unrelated Foundation, Sword Bones, therefore must give the same passive numbers
as Oath-Skin Frame: 1x PB at Awakened, 2x PB at Integrated, Refined and Perfected
(the Integrated "another PB" rider keeps applying), and nothing at Latent.

Sword Bones is used because it is a different Foundation with the same printed
"Integrated: ... another PB" rider. This test reads only the pinned Foundation
release through the same calculator; it does not import any private fixture.
"""
import pytest

from stage2.formulas import evaluate_formula
from non_sphere_authority.foundation_mechanics import (
    resolve_foundation_stage_mechanics, verified_foundation_records,
)

SWORD_BONES = 'sword_bones_v0_2B'
PATHS = ['tianxia.path.body_refining']


def _hp_value(result, pb):
    return sum(
        evaluate_formula(row['formula']['root'], {'pb': pb}).value
        for row in result['hp_maximum_modifiers']
    )


@pytest.mark.parametrize('stage,multiple', [
    ('Awakened', 1), ('Integrated', 2), ('Refined', 2), ('Perfected', 2),
])
def test_unrelated_foundation_hp_is_cumulative_by_stage(stage, multiple):
    source = verified_foundation_records()[SWORD_BONES]
    result = resolve_foundation_stage_mechanics(source, PATHS, stage=stage)
    assert result['initial_state']['stage'] == stage
    assert result['initial_state']['stage_origin'] == 'authenticated_source_event'
    assert _hp_value(result, pb=3) == 3 * multiple


def test_unrelated_foundation_hp_is_unavailable_at_latent():
    source = verified_foundation_records()[SWORD_BONES]
    result = resolve_foundation_stage_mechanics(source, PATHS, stage='Latent')
    assert result['hp_maximum_modifiers'] == []
    assert [row['availability'] for row in result['conditional_modifiers']
            if row['statistic'] == 'hp_maximum'] == ['unavailable']
