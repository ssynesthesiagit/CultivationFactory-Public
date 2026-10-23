"""Public-runnable Oath-Skin Frame regression: frame reader, no private harness.

Uses only the pinned Foundation release and the Oath-Skin Frame calculator. The
table and HTTP cases with private-only needs are in
tests/test_mgr_t15_oath_skin_frame_table_private.py (documented there).
"""
from copy import deepcopy

from combat.ext import oath_skin_frame as frame
from non_sphere_authority.foundation_mechanics import (
    resolve_initial_foundation_mechanics, verified_foundation_records,
)

PATHS = ['tianxia.path.body_refining']


def test_frame_reader_does_not_withdraw_another_passive_hp_bonus():
    source = verified_foundation_records()[frame.FOUNDATION]
    mechanics = resolve_initial_foundation_mechanics(source, PATHS)
    extra = deepcopy(mechanics['hp_maximum_modifiers'][0])
    extra['feature_name'] = 'Another passive'
    mechanics['hp_maximum_modifiers'].append(extra)
    assert frame.hp_value(mechanics, 4) == 4
