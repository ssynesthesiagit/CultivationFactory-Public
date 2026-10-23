"""Finding 1 regression: Foundation stages are cumulative for every Foundation.

Finding 6 (F12R) extends this to the shared Refined/Perfected change: every
Foundation that resolves at Integrated keeps the same passive HP at Refined and
Perfected, because the Integrated "another PB" rider is cumulative and the
Integrated-or-higher features stay available. Before that change, Refined and
Perfected dropped the rider and the Integrated-or-higher rows.

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


FOUNDATION_PATHS = [
    ['tianxia.path.body_refining'], ['tianxia.path.qi_cultivation'], ['tianxia.path.spirit_awakening'],
]


def _resolvable_paths(source, stage):
    for paths in FOUNDATION_PATHS:
        try:
            return paths, resolve_foundation_stage_mechanics(source, paths, stage=stage)
        except Exception:
            continue
    return None, None


def test_every_foundation_keeps_integrated_passives_at_refined_and_perfected():
    checked = []
    for record_id, source in sorted(verified_foundation_records().items()):
        paths, integrated = _resolvable_paths(source, 'Integrated')
        if paths is None:
            continue
        expected = _hp_value(integrated, pb=3)
        for stage in ('Refined', 'Perfected'):
            result = resolve_foundation_stage_mechanics(source, paths, stage=stage)
            assert result['initial_state']['stage'] == stage, record_id
            assert _hp_value(result, pb=3) == expected, (record_id, stage)
            assert len(result['hp_maximum_modifiers']) == len(integrated['hp_maximum_modifiers']), (record_id, stage)
        checked.append(record_id)
    # Most Foundations resolve on some Path; this guards against silently checking nothing.
    assert len(checked) >= 20
    assert SWORD_BONES in checked
